#!/usr/bin/env bash
# run_sweep.sh - matrix executor for the RMW workshop.
#
# Sweeps the TEMPLATE x SCENARIO x RMW matrix defined in benchmark.yaml,
# running a controlled workload per cell, collecting template-specific delivery,
# arrival-gap or latency, silence, throughput, and receiver-CPU metrics, and writing a structured
# result per cell to captures/<SWEEP_ID>/results.jsonl. Then generates the
# cross-RMW comparison sheet and the weighted Pugh matrix.
#
# Metrics are file artifacts (results.jsonl -> comparison.md / comparison.csv /
# comparison.png + pugh.md). Live per-container system pressure is observed
# separately via netdata (`--profile netdata`, http://localhost:19999).
#
# Invoked via `scripts/workshop run ...`. Lists are comma-separated.
#
# Usage:
#   run_sweep.sh --template A,B --scenario S0,S1 --rmw cyclone,fastdds \
#                --scale 3 --duration 20 [--rate 1000] [--msg Array1k] [--dry-run]
#                [--bag PATH]
#
# Lab 4: BENCHMARKING & DECISION MATRIX - every RMW sees
#   the same declared workload settings under the selected controlled scenario. Bring your own
#   MCAP or generate one with scripts/workshop gen-bag:
#     --template A   SYNTHETIC - performance_test pub/sub + service round-trip on the
#                    `--profile rmw` A/B bridge pair. netem scenarios (S2/S3) are
#                    skipped with a note (Template A has no network to shape).
#     --template B   MCAP replay across the bridge fleet with the selected clean or
#                    impaired scenario - a controlled cross-RMW comparison.
#   Omitted --scenario means S0. --scenario all means every scenario configured
#   for the selected template. S1 uses its configured replica scales (1 and 3);
#   --scale controls other Template B scenarios. Template A is its actual pair.

set -uo pipefail   # NOT -e: recoverable cell failures must not abort the sweep

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # lab4-benchmarking-and-decision/scripts
DOCKER_ROOT="$(cd "$SCRIPT_DIR/../../docker" && pwd)"          # docker/
SCRIPTS_DIR="$DOCKER_ROOT/scripts"
LAB2_SCRIPTS="$DOCKER_ROOT/../lab2-on-the-wire/scripts"
LAB4_SCRIPTS="$DOCKER_ROOT/../lab4-benchmarking-and-decision/scripts"
BENCH_DIR="$LAB4_SCRIPTS/bench"                              # main's example benches
DOCKER_BIN="${LAB4_DOCKER_BIN:-docker}"
BENCH_DIR="${LAB4_BENCH_DIR:-$BENCH_DIR}"
NETEM_HELPER="${LAB4_NETEM_HELPER:-$LAB2_SCRIPTS/netem_profile.sh}"
docker() { timeout --kill-after=2 45 "$DOCKER_BIN" "$@"; }

# Shared TTY-safe logging helpers (info/ok/warn/fail/die) - all to stderr, so
# stdout stays reserved for a function's return data: run_synthetic/run_mcap
# write their metric tuple to a per-cell file in the parent shell.
# The path is resolved from the checkout at runtime.
# shellcheck source=../../docker/scripts/lib.sh disable=SC1091
. "$SCRIPTS_DIR/lib.sh"


# --- defaults ---------------------------------------------------------------
TEMPLATES="A"; SCENARIOS=""; RMWS="cyclone,fastdds"; DRY_RUN=0
SCALE=3; DURATION=20; RATE=1000; MSG="Array1k"
BAG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --template) [[ $# -ge 2 ]] || { fail "--template needs a value"; exit 2; }; TEMPLATES="$2"; shift 2 ;;
        --scenario) [[ $# -ge 2 ]] || { fail "--scenario needs a value"; exit 2; }; SCENARIOS="$2"; shift 2 ;;
        --rmw)      [[ $# -ge 2 ]] || { fail "--rmw needs a value"; exit 2; }; RMWS="$2"; shift 2 ;;
        --scale)    [[ $# -ge 2 ]] || { fail "--scale needs a value"; exit 2; }; SCALE="$2"; shift 2 ;;
        --duration) [[ $# -ge 2 ]] || { fail "--duration needs a value"; exit 2; }; DURATION="$2"; shift 2 ;;
        --rate)     [[ $# -ge 2 ]] || { fail "--rate needs a value"; exit 2; }; RATE="$2"; shift 2 ;;
        --msg)      [[ $# -ge 2 ]] || { fail "--msg needs a value"; exit 2; }; MSG="$2"; shift 2 ;;
        --bag)      [[ $# -ge 2 ]] || { fail "--bag needs a value"; exit 2; }; BAG="$2"; shift 2 ;;
        --dry-run)  DRY_RUN=1; shift ;;
        -h|--help)  sed -n '2,30p' "$0"; exit 0 ;;
        *) fail "unknown flag: $1"; exit 2 ;;
    esac
done

IFS=',' read -ra RMW_LIST      <<< "$RMWS"
[[ -n "$SCENARIOS" ]] && IFS=',' read -ra SCENARIO_OVERRIDE <<< "$SCENARIOS" || SCENARIO_OVERRIDE=()

IFS=',' read -ra TEMPLATE_LIST <<< "$TEMPLATES"

for list_name in TEMPLATES RMWS SCENARIOS; do
    list_value="${!list_name}"
    [[ ( "$list_name" == SCENARIOS && -z "$list_value" ) || ( -n "$list_value" && "$list_value" != ,* && "$list_value" != *, && "$list_value" != *,,* ) ]] || {
        fail "malformed comma list: --${list_name,,}"; exit 2;
    }
done

is_uint() { [[ "$1" =~ ^[1-9][0-9]*$ ]]; }
is_known() { local needle="$1"; shift; local value; for value in "$@"; do [[ "$value" == "$needle" ]] && return 0; done; return 1; }
is_uint "$SCALE" || { fail "--scale must be a positive integer: $SCALE"; exit 2; }
is_uint "$DURATION" || { fail "--duration must be a positive integer: $DURATION"; exit 2; }
is_uint "$RATE" || { fail "--rate must be a positive integer: $RATE"; exit 2; }
defs() { python3 "$SCRIPT_DIR/benchmark_defs.py" "$@"; }

# Resolve before touching Docker, bags, locks, or capture directories. The
# same pure plan is used by dry-run and by the execution loop below.
if [[ "$DRY_RUN" -eq 1 ]]; then
    plan_json="$(defs plan "$TEMPLATES" "$SCENARIOS" "$RMWS" "$SCALE")" || {
        fail "cannot resolve benchmark plan"; exit 2;
    }
    printf 'Resolved Lab 4 plan (S1=configured scale; other Template B=--scale; Template A=two-container pair)\n'
    printf '%s\n' "$plan_json" | python3 -c '
import json, sys
for line in sys.stdin:
    if line.strip():
        cell = json.loads(line)
        print("template={template} scenario={scenario} rmw={rmw} scale={scale} ({scale_source}) executor={executor} topology={topology} netem={netem} link_rate={link_rate}".format(**cell))
'
    exit 0
fi

# Validate the complete requested matrix before creating an output directory or
# starting Docker. This deliberately uses the checked-in taxonomy on the host.
if ! python3 -c 'import yaml' >/dev/null 2>&1; then
    fail "host Python requires PyYAML to validate benchmark.yaml"; exit 2
fi
known="$(defs templates)" || { fail "cannot load benchmark.yaml"; exit 2; }
read -ra KNOWN_TEMPLATES <<< "$known"
known="$(defs rmws)" || { fail "cannot load benchmark.yaml"; exit 2; }
read -ra KNOWN_RMWS <<< "$known"
for t in "${TEMPLATE_LIST[@]}"; do
    is_known "$t" "${KNOWN_TEMPLATES[@]}" || { fail "unknown template: $t"; exit 2; }
done
for r in "${RMW_LIST[@]}"; do
    is_known "$r" "${KNOWN_RMWS[@]}" || { fail "unknown RMW: $r"; exit 2; }
done
if [[ -n "$SCENARIOS" && "$SCENARIOS" != all ]]; then
    for s in "${SCENARIO_OVERRIDE[@]}"; do
        found=0
        for t in "${KNOWN_TEMPLATES[@]}"; do
            known="$(defs scenarios "$t")" || exit 2
            read -ra known_scenarios <<< "$known"
            is_known "$s" "${known_scenarios[@]}" && found=1
        done
        [[ "$found" -eq 1 ]] || { fail "unknown scenario: $s"; exit 2; }
    done
fi
for t in "${TEMPLATE_LIST[@]}"; do
    if [[ "$SCENARIOS" == all ]]; then
        read -ra check_scenarios <<< "$(defs scenarios "$t")"
    elif [[ ${#SCENARIO_OVERRIDE[@]} -gt 0 ]]; then
        check_scenarios=("${SCENARIO_OVERRIDE[@]}")
    else
        check_scenarios=(S0)
    fi
    for s in "${check_scenarios[@]}"; do
        defs allowed "$t" "$s" >/dev/null 2>&1 || {
            fail "unsupported template/scenario combination: $t/$s"; exit 2;
        }
        executor_check="$(defs harness-executor "$t" 2>/dev/null || true)"
        [[ "$executor_check" == synthetic || "$executor_check" == mcap ]] || { fail "unsupported executor for template $t: $executor_check"; exit 2; }
        [[ -n "$(defs harness-profile "$t" 2>/dev/null || true)" && -n "$(defs harness-topology "$t" 2>/dev/null || true)" && -n "$(defs harness-workload "$t" 2>/dev/null || true)" && -n "$(defs harness-impairment "$t" 2>/dev/null || true)" ]] || { fail "incomplete harness definition: $t"; exit 2; }
        if [[ "$executor_check" == synthetic && "$s" != S0 ]]; then
            fail "unsupported impairment for Template A: $t/$s"; exit 2
        fi
    done
done
for r in "${RMW_LIST[@]}"; do
    [[ -n "$(defs rmw-impl "$r" 2>/dev/null || true)" ]] || { fail "RMW has no implementation: $r"; exit 2; }
    if is_known A "${TEMPLATE_LIST[@]}" && [[ "$r" == zenoh-lowlat ]]; then
        fail "RMW zenoh-lowlat has no Template A bridge service"; exit 2
    fi
done
case "$MSG" in Array1k|Array4k|Array16k|Array64k|Array256k|Array1m) ;; *) fail "unsupported --msg: $MSG"; exit 2 ;; esac

for binary in python3 timeout setsid flock "$DOCKER_BIN"; do
    command -v "$binary" >/dev/null || { fail "required command missing: $binary"; exit 2; }
done
for number in "$SCALE" "$DURATION" "$RATE"; do
    [[ ${#number} -le 9 ]] || { fail "numeric argument exceeds supported range"; exit 2; }
done
# Helpers honour a test Docker executable too; no environment override can
# silently send a fixture subprocess to the real daemon.
export LAB4_DOCKER_BIN="$DOCKER_BIN"
# The exercises use /bags/<name> to name the path seen by fleet containers,
# while Compose needs the matching host-relative bind-mount source. Accept both
# that student-facing form and an explicit path relative to docker/.
if [[ "$BAG" == /bags/* ]]; then
    BAG="./bags/${BAG#/bags/}"
fi
if is_known B "${TEMPLATE_LIST[@]}"; then
    bag_check="${BAG:-./bags/benchmark}"
    [[ "$bag_check" == /* ]] || bag_check="$DOCKER_ROOT/$bag_check"
    BAG="$(realpath -e -- "$bag_check")" || { fail "missing bag: $bag_check"; exit 2; }
    [[ -d "$BAG" && -f "$BAG/metadata.yaml" ]] || { fail "Template B bag directory is missing: $bag_check"; exit 2; }
fi

for r in "${RMW_LIST[@]}"; do
    zcfg="$(defs rmw-zenoh-config "$r")" || exit 2
    if [[ -n "$zcfg" ]]; then
        [[ "$zcfg" == /scripts/lab4/* && -f "$SCRIPT_DIR/${zcfg#/scripts/lab4/}" ]] || { fail "missing or unsupported Zenoh config: $zcfg"; exit 2; }
    fi
done
for config in "$DOCKER_ROOT/rmw_configuration/cyclone/default_cyclone.xml" \
              "$DOCKER_ROOT/rmw_configuration/fast/default_fast.xml" \
              "$DOCKER_ROOT/rmw_configuration/zenoh/default_zenoh.json5" "$NETEM_HELPER"; do
    [[ -r "$config" ]] || { fail "required configuration missing: $config"; exit 2; }
done
# Serialize this checkout's runner; Compose conflicts are checked separately.
lock_key="$(printf %s "$DOCKER_ROOT" | sha256sum | cut -d' ' -f1)"
exec 9>"${TMPDIR:-/tmp}/lab4-sweep-$lock_key.lock" || exit 2
flock -n 9 || { fail "another Lab 4 sweep is active in this checkout"; exit 2; }
# msg type -> payload bytes (for throughput derivation)
msg_bytes() {
    case "$1" in
        Array1k)   echo 1024 ;;
        Array4k)   echo 4096 ;;
        Array16k)  echo 16384 ;;
        Array64k)  echo 65536 ;;
        Array256k) echo 262144 ;;
        Array1m)   echo 1048576 ;;
        *)         echo 1024 ;;
    esac
}

# rmw short name -> bridge A/B service names (from `--profile rmw`)
svc_a() { echo "ros2-$1"; }
svc_b() { echo "ros2-$1-b"; }

sample_cpu() {  # container -> instantaneous CPU% (numeric) or empty
    docker stats --no-stream --format '{{.CPUPerc}}' "$1" 2>/dev/null | tr -d '%' | head -1
}

# Run each blocking workload in its own process group. The parent owns the
# wait, so a signal can terminate the complete local command tree promptly.
managed() {
    local limit="$1" output="$2" pid rc=0; shift 2
    [[ "$INTERRUPTED" -eq 0 ]] || return 130
    setsid timeout --kill-after=2 "$limit" "$@" >"$output" &
    pid=$!; CHILD_PIDS+=("$pid")
    CPU_MEAN=""
    if [[ -n "${CPU_CONTAINER:-}" ]]; then
        local sample total=0 count=0
        while kill -0 "$pid" 2>/dev/null && [[ "$INTERRUPTED" -eq 0 ]]; do
            sample="$(sample_cpu "$CPU_CONTAINER")"
            if [[ "$sample" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
                total="$(awk -v a="$total" -v b="$sample" 'BEGIN{print a+b}')"; count=$((count+1))
                if [[ -n "${CPU_SAMPLE_OUT:-}" ]]; then
                    printf '{"timestamp":%s,"cpu_pct":%s}\n' "$(date +%s.%N)" "$sample" >> "$CPU_SAMPLE_OUT"
                fi
            fi
            sleep 0.1
        done
        if ((count>0)); then CPU_MEAN="$(awk -v a="$total" -v b="$count" 'BEGIN{print a/b}')"; fi
    fi
    wait "$pid" || rc=$?
    if [[ "$INTERRUPTED" -ne 0 ]]; then kill_children; rc=130; fi
    CHILD_PIDS=()
    return "$rc"
}
managed_compose() {
    local output="$1"; shift
    local previous="$PWD" rc=0
    cd "$DOCKER_ROOT" || return 1
    managed 90 "$output" "$DOCKER_BIN" compose "$@" || rc=$?
    cd "$previous" || return 1
    return "$rc"
}

compose() { ( cd "$DOCKER_ROOT" && docker compose "$@" ); }

# fleet replica container names (project-fleet-<n>), one per line
OWNED_IDS=()
CELL_FLEET_IDS=()
CELL_RECEIVER_IDS=()
CELL_RMW_IDS=()
CELL_ROUTER_IDS=()
CHILD_PIDS=()
INTERRUPTED=0
CELL_ACTIVE=0
OWNERSHIP_UNSAFE=0
CELL_CLEANUP_FAILED=0
CURRENT_CELL=""
SHAPING_ARTIFACT=""
register_ids() {
    local id existing found
    for id in "$@"; do
        [[ -n "$id" ]] || continue
        found=0
        for existing in "${OWNED_IDS[@]}"; do [[ "$existing" == "$id" ]] && found=1; done
        [[ "$found" -eq 0 ]] && OWNED_IDS+=("$id")
    done
}
container_conflict() {
    local name="$1" ids
    if ! ids="$(docker ps -aq --filter "name=^/${name}$" 2>/dev/null)"; then
        fail "cannot inspect possible benchmark resource: $name"
        OWNERSHIP_UNSAFE=1; return 2
    fi
    [[ -z "$ids" ]] || { fail "benchmark resource already exists: $name (refusing to adopt it)"; return 1; }
}
register_service_ids() {
    local profile="$1" service="$2" ids
    if ! ids="$(compose --profile "$profile" ps -aq "$service" 2>/dev/null)"; then
        fail "cannot enumerate Compose service IDs: project profile=$profile service=$service"
        OWNERSHIP_UNSAFE=1; return 2
    fi
    local -a service_ids=()
    if [[ -n "$ids" ]]; then mapfile -t service_ids <<< "$ids"; fi
    register_ids "${service_ids[@]}"
    if [[ "$service" == fleet ]]; then CELL_FLEET_IDS=("${service_ids[@]}"); fi
    if [[ "$service" == lab4-receiver ]]; then CELL_RECEIVER_IDS=("${service_ids[@]}"); fi
    if [[ "$service" != fleet && "$service" != zenoh-router && "$service" != lab4-receiver ]]; then CELL_RMW_IDS+=("${service_ids[@]}"); fi
    [[ "$service" == zenoh-router ]] && CELL_ROUTER_IDS+=("${service_ids[@]}")
    return 0
}
kill_children() {
    local pid deadline alive
    for pid in "${CHILD_PIDS[@]}"; do
        kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    done
    deadline=$((SECONDS + 2))
    while (( SECONDS < deadline )); do
        alive=0
        for pid in "${CHILD_PIDS[@]}"; do kill -0 "$pid" 2>/dev/null && alive=1; done
        (( alive == 0 )) && return 0
        sleep 0.1
    done
    for pid in "${CHILD_PIDS[@]}"; do
        kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
}
# Called by the INT/TERM traps below.
# shellcheck disable=SC2329
request_interrupt() { INTERRUPTED=1; kill_children; }
remove_ids() {
    local id remaining
    for id in "$@"; do
        [[ -n "$id" ]] || continue
        docker rm -f "$id" >/dev/null 2>&1 || { CELL_CLEANUP_FAILED=1; continue; }
    done
    for id in "$@"; do
        [[ -n "$id" ]] || continue
        if ! remaining="$(docker ps -aq --no-trunc)"; then CELL_CLEANUP_FAILED=1
        elif grep -Fxq "$id" <<<"$remaining"; then CELL_CLEANUP_FAILED=1; fi
    done
}
cleanup_cell() {
    kill_children
    clear_netem_fleet
    remove_ids "${CELL_FLEET_IDS[@]}" "${CELL_RECEIVER_IDS[@]}" "${CELL_ROUTER_IDS[@]}" "${CELL_RMW_IDS[@]}"
    if [[ "$CELL_CLEANUP_FAILED" -ne 0 ]]; then
        fail "owned resource cleanup could not be verified; refusing to continue"
        return 1
    fi
    CELL_FLEET_IDS=(); CELL_RECEIVER_IDS=(); CELL_ROUTER_IDS=(); CELL_RMW_IDS=(); OWNED_IDS=()
    return 0
}
capture_shaping_state() {
    local aggregate=0
    local phase="$1" profile="${2:-none}" rate="${3:-}" role="${4:-fleet}" id name qdisc ingress ifb ifb_qdisc validation
    local -a target_ids=()
    [[ "$role" == fleet ]] && target_ids=("${CELL_FLEET_IDS[@]}") || target_ids=("${CELL_RMW_IDS[@]}")
    [[ -n "$SHAPING_ARTIFACT" ]] || return 0
    [[ ${#target_ids[@]} -gt 0 ]] || return 1
    for id in "${target_ids[@]}"; do
        name="$(docker inspect --format '{{.Name}}' "$id" 2>/dev/null | sed 's#^/##')"
        qdisc="$(docker exec "$id" sh -c 'tc -j qdisc show dev eth0 2>/dev/null' 2>/dev/null || true)"
        ingress="$(docker exec "$id" sh -c 'tc -j filter show dev eth0 ingress 2>/dev/null' 2>/dev/null || true)"
        ifb="$(docker exec "$id" sh -c 'ip -j link show 2>/dev/null' 2>/dev/null || true)"
        ifb_qdisc="$(docker exec "$id" sh -c 'tc -j qdisc show 2>/dev/null' 2>/dev/null || true)"
        validation="$(python3 "$SCRIPT_DIR/shaping_state.py" "$qdisc" "$ingress" "$ifb" "$ifb_qdisc" "$profile" "$rate" 2>/dev/null || true)"
        python3 - "$SHAPING_ARTIFACT" "$phase" "$profile" "$rate" "$id" "$name" "$qdisc" "$ingress" "$ifb" "$ifb_qdisc" "$validation" <<'PY'
import json, sys
path, phase, profile, rate, cid, name, qdisc, ingress, ifb, ifb_qdisc, validation = sys.argv[1:]
with open(path, "a", encoding="utf-8") as output:
    json.dump({"phase": phase, "requested_profile": profile, "requested_rate": rate or None,
               "container_id": cid, "container": name, "qdisc_json": qdisc or None,
               "ingress_filter_json": ingress or None, "ifb_json": ifb or None,
               "ifb_qdisc_json": ifb_qdisc or None,
               "validation": json.loads(validation) if validation else {"valid": False, "reasons": ["state_unavailable"]}}, output,
              allow_nan=False)
    output.write("\n")
PY
        if ! python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("valid") else 1)' <<<"$validation"; then
            aggregate=1
        fi
    done
    return "$aggregate"
}

# Apply a named profile (lab2-on-the-wire/scripts/netem_profile.sh - the same
# catalog Lab 2 teaches) to every fleet replica's link, optionally capped by a
# LINK_RATE. Delegates rather than reimplementing: gets bidirectional (egress +
# ingress) shaping and GSO/TSO/GRO offload handling for free, and "heavy"/
# "severe"/"constrained" are already reserved there for exactly this use.
apply_netem_fleet() {
    local profile="$1" rate="${2:-}" id rc=0
    [[ ${#CELL_FLEET_IDS[@]} -gt 0 ]] || return 1
    for id in "${CELL_FLEET_IDS[@]}"; do
        managed 60 "$OUT_DIR/${CURRENT_CELL}.${id}.netem.log" env LINK_RATE="$rate" bash "$NETEM_HELPER" "$profile" "$id" || rc=1
    done
    return "$rc"
}
clear_netem_fleet() {
    # Owned network namespaces disappear with their containers. No shared
    # helper cleanup is necessary, including after partial shaping/startup.
    return 0
}

# --- sweep setup ------------------------------------------------------------
if ! docker exec ubuntu-headless test -d /captures; then
    fail "ubuntu-headless does not have the /captures mount; run: docker compose up -d --force-recreate ubuntu-headless"
    exit 2
fi
if ! docker exec ubuntu-headless test -w /captures; then
    fail "ubuntu-headless cannot write /captures; fix ownership with: sudo chown -R \$(id -u):\$(id -g) $DOCKER_ROOT/captures"
    exit 2
fi
SWEEP_ID="$(date +%Y%m%d_%H%M%S_%N)_${BASHPID}_sweep"
CAPTURE_ROOT="${LAB4_CAPTURE_ROOT:-$DOCKER_ROOT/captures}"
mkdir -p "$CAPTURE_ROOT" || { fail "cannot create capture root: $CAPTURE_ROOT"; exit 2; }
OUT_DIR="$CAPTURE_ROOT/$SWEEP_ID"
if ! mkdir "$OUT_DIR"; then fail "capture directory already exists or cannot be created: $OUT_DIR"; exit 2; fi
RESULTS="$OUT_DIR/results.jsonl"
: > "$RESULTS"
CONTAINER_OUT_DIR="/captures/$SWEEP_ID"

# Called by the EXIT trap below.
# shellcheck disable=SC2329
cleanup() {
    local exit_status=$?
    trap - EXIT
    if [[ "$CELL_ACTIVE" -eq 1 ]]; then
        workload_status=${exit_status:-1}
        [[ "$workload_status" -ne 0 ]] || workload_status=1
        finalize_cell || true
    fi
    kill_children
    local id
    for id in "${OWNED_IDS[@]}"; do docker rm -f "$id" >/dev/null 2>&1 || true; done
}
trap cleanup EXIT
trap request_interrupt INT TERM

info "Sweep $SWEEP_ID"
info "templates=[$TEMPLATES] rmws=[$RMWS] scale=$SCALE duration=${DURATION}s"

# Sweep metadata is constructed from argv values, not interpolated source code.
metadata_json="$(python3 - "$SWEEP_ID" "$TEMPLATES" "$RMWS" "$SCENARIOS" "$SCALE" "$DURATION" "$RATE" "$MSG" "$BAG" <<'PY'
import datetime, json, sys
sid, templates, rmws, scenarios, scale, duration, rate, msg, bag = sys.argv[1:]
print(json.dumps({"sweep_id": sid, "templates": templates.split(","), "rmws": rmws.split(","),
    "scenarios_override": scenarios.split(",") if scenarios else None,
    "scale": int(scale), "duration": int(duration), "rate": int(rate), "msg": msg,
    "bag": bag or None, "started": datetime.datetime.now(datetime.timezone.utc).isoformat()}))
PY
)" || { fail "could not construct sweep metadata"; exit 2; }
printf "%s\n" "$metadata_json" > "$OUT_DIR/sweep.json"
if ! docker exec --user "$(id -u):$(id -g)" -e HOME=/tmp -i ubuntu-headless python3 -c 'import json,sys; json.dump(json.load(sys.stdin), open(sys.argv[1], "w"), indent=2)' "$CONTAINER_OUT_DIR/sweep.json" <<<"$metadata_json"; then
    fail "could not persist sweep metadata"; exit 2
fi

# --- workload: synthetic (Lab 4, Template A) --------------------------------
# Runs the perf_test pub/sub + service round-trip between the bridge A/B pair
# for the given RMW. Echoes: "<drop%> <p99_ms> <freshness_ms> <throughput_mbps> <cpu%>"
service_conflict() {
    local profile="$1" service="$2" existing
    existing="$(compose --profile "$profile" ps -aq "$service")" || { OWNERSHIP_UNSAFE=1; return 1; }
    [[ -z "$existing" ]] || { fail "existing benchmark service: $service"; return 1; }
}
start_services() {
    local profile="$1" rc=0 service; shift
    for service in "$@"; do service_conflict "$profile" "$service" || return 1; done
    managed_compose "$OUT_DIR/${CURRENT_CELL}.startup.log" --profile "$profile" up -d --no-deps "$@" || rc=$?
    # Even failed or interrupted Compose may have created some containers.
    for service in "$@"; do register_service_ids "$profile" "$service" || rc=1; done
    return "$rc"
}
run_synthetic() {
    local rmw="$1" profile="$2" A B m mx hz sm smx shz p99 rm rmx rhz cpu
    A="$(svc_a "$rmw")"; B="$(svc_b "$rmw")"
    container_conflict "$A" && container_conflict "$B" || return 1
    start_services "$profile" "$A" "$B" || return
    [[ ${#CELL_RMW_IDS[@]} -eq 2 ]] || return 1
    A="${CELL_RMW_IDS[0]}"; B="${CELL_RMW_IDS[1]}"
    capture_shaping_state before none "" rmw || { CELL_INVALID=1; return 1; }
    managed 10 /dev/null sleep "${LAB4_STARTUP_WAIT:-5}" || return $?
    OBS_WORKLOAD_START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    CPU_SAMPLE_OUT="$OUT_DIR/${CURRENT_CELL}.cpu.samples.jsonl" CPU_CONTAINER="$B" managed "$((DURATION+40))" "$OUT_DIR/${CURRENT_CELL}.sensor.metrics" env LAB4_BENCH_LOG="$OUT_DIR/${CURRENT_CELL}.sensor.log" bash "$BENCH_DIR/pubsub.sh" "$A" "$B" best_effort "$DURATION" "$MSG" "$RATE" || return $?
    read -r m mx hz < "$OUT_DIR/${CURRENT_CELL}.sensor.metrics" || return 1
    numeric_tuple "$m" "$mx" "$hz" || return 1
    cpu="${CPU_MEAN:-n/a}"
    docker exec -d "$A" bash -c 'source /opt/ros/jazzy/setup.bash; exec ros2 run demo_nodes_cpp add_two_ints_server' || return 1
    managed 10 /dev/null sleep "${LAB4_SERVICE_WAIT:-2}" || return $?
    managed 60 "$OUT_DIR/${CURRENT_CELL}.service.metrics" "$DOCKER_BIN" exec "$B" bash -c 'source /opt/ros/jazzy/setup.bash; python3 /scripts/lab4/bench/service_bench.py 200 10' || return $?
    read -r sm smx shz p99 < "$OUT_DIR/${CURRENT_CELL}.service.metrics" || return 1
    numeric_tuple "$sm" "$smx" "$shz" "$p99" || return 1
    docker exec "$A" bash -c 'pkill -f "[a]dd_two_ints_server"' || true
    managed "$((DURATION+40))" "$OUT_DIR/${CURRENT_CELL}.state.metrics" env LAB4_BENCH_LOG="$OUT_DIR/${CURRENT_CELL}.state.log" bash "$BENCH_DIR/pubsub.sh" "$A" "$B" reliable "$DURATION" "$MSG" "$RATE" || return $?
    read -r rm rmx rhz < "$OUT_DIR/${CURRENT_CELL}.state.metrics" || return 1
    numeric_tuple "$rm" "$rmx" "$rhz" || return 1
    OBS_WORKLOAD_END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    capture_shaping_state post_measurement none "" rmw || { CELL_INVALID=1; return 1; }
    python3 - "$OUT_DIR/${CURRENT_CELL}.synthetic.metrics.json" "$m" "$mx" "$hz" "$p99" "$rm" "$rmx" "$rhz" <<'CHECK'
import json,sys
out,mean,maxv,rate,rtt,reliable_mean,reliable_max,reliable_rate=sys.argv[1:]
json.dump({"template_a": {"pubsub_latency_mean_ms": float(mean), "pubsub_latency_max_ms": float(maxv),
    "pubsub_received_hz": float(rate), "service_rtt_p99_ms": float(rtt),
    "reliable_pubsub_latency_mean_ms": float(reliable_mean),
    "reliable_pubsub_latency_max_ms": float(reliable_max),
    "reliable_pubsub_received_hz": float(reliable_rate)}}, open(out,"w",encoding="utf-8"), indent=2)
CHECK
    local drop=n/a thru=n/a
    if [[ "$hz" != n/a ]]; then
        drop="$(awk -v r="$RATE" -v h="$hz" 'BEGIN{ d=(r-h)/r*100; if(d<0)d=0; printf "%.2f", d }')"
        thru="$(awk -v b="$(msg_bytes "$MSG")" -v h="$hz" 'BEGIN{ printf "%.2f", b*h*8/1e6 }')"
    fi
    echo "$drop $p99 $rm $thru $cpu"
}
numeric_tuple() {
    python3 - "$@" <<'CHECK'
import math,sys
try:
    assert all(x == "n/a" or math.isfinite(float(x)) for x in sys.argv[1:])
except (ValueError, AssertionError):
    raise SystemExit(1)
CHECK
}

# --- workload: mcap (Lab 4 Template B) --------------------------------------
# Brings up N `fleet` replicas replaying the bag, applies the scenario's netem
# to every replica, runs class_probe.py in the dedicated unshaped receiver on
# fleet-net, and samples that receiver's CPU.
# Tears the fleet down between cells so each RMW starts clean.
# Echoes: "<drop%> <p99_ms> <freshness_ms> <throughput_mbps> <cpu%>"
run_mcap() {
    local rmw="$1" scenario="$2" netem="$3" profile="$4" cell_scale="$5" impl zcfg link_rate rc=0
    impl="$(defs rmw-impl "$rmw")"; zcfg="$(defs rmw-zenoh-config "$rmw")"
    link_rate="$(defs netem-link-rate "$scenario")"
    cp "$BAG/metadata.yaml" "$OUT_DIR/${CURRENT_CELL}.bag_metadata.yaml" || return 1
    service_conflict "$profile" fleet || return 1
    if [[ "$zcfg" == *router* ]]; then
        container_conflict zenoh-router || return 1
        start_services zenoh-router zenoh-router || return
        [[ ${#CELL_ROUTER_IDS[@]} -eq 1 ]] || return 1
    fi
    # Explicit services are essential: a profile also includes default services.
    service_conflict "$profile" lab4-receiver || return 1
    RMW_IMPLEMENTATION="$impl" ZENOH_SESSION_CONFIG_URI="${zcfg:-/zenoh_session.json5}" \
        start_services "$profile" lab4-receiver || return
    [[ ${#CELL_RECEIVER_IDS[@]} -eq 1 ]] || return 1
    RMW_IMPLEMENTATION="$impl" BAG_DIR="$BAG" ZENOH_SESSION_CONFIG_URI="${zcfg:-/zenoh_session.json5}" \
        managed_compose "$OUT_DIR/${CURRENT_CELL}.startup.log" --profile "$profile" up -d --no-deps --scale "fleet=$cell_scale" fleet || rc=$?
    register_service_ids "$profile" fleet || rc=1
    [[ "$rc" -eq 0 ]] || return "$rc"
    [[ ${#CELL_FLEET_IDS[@]} -eq "$cell_scale" ]] || return 1
    # Docker creates the actual replica addresses and immutable image IDs. Use
    # those facts to construct the expected namespace inventory; discovery is
    # intentionally not involved.
    local namespaces image_ids inspect_line ip image_id ns_json image_json
    namespaces=(); image_ids=()
    for id in "${CELL_FLEET_IDS[@]}"; do
        inspect_line="$(docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}|{{.Image}}' "$id" 2>/dev/null)" || return 1
        ip="${inspect_line%%|*}"; image_id="${inspect_line#*|}"
        [[ "$ip" =~ ^[0-9]+([.][0-9]+){3}$ && -n "$image_id" ]] || return 1
        ns="/robot_$(awk -F. '{print $NF}' <<<"$ip")"
        namespaces+=("$ns"); image_ids+=("$image_id")
    done
    ns_json="$(printf '%s\n' "${namespaces[@]}" | python3 -c 'import json,sys; print(json.dumps([x.strip() for x in sys.stdin if x.strip()]))')"
    image_json="$(python3 - "${namespaces[*]}" "${image_ids[*]}" <<'PY'
import json, sys
print(json.dumps(dict(zip(sys.argv[1].split(), sys.argv[2].split()))))
PY
)"
    python3 "$SCRIPT_DIR/replay_inventory.py" "$BAG" --namespaces-json "$ns_json" \
        --image-ids-json "$image_json" --requested-replicas "$cell_scale" --rate 1 \
        --qos-json "$(python3 -c 'import yaml,json; print(json.dumps(yaml.safe_load(open("'"$SCRIPT_DIR/benchmark.yaml"'"))["topic_classes"]))')" \
        --benchmark-config "$SCRIPT_DIR/benchmark.yaml" --output "$OUT_DIR/${CURRENT_CELL}.inventory.json" || return 1
    python3 - "$OUT_DIR/${CURRENT_CELL}.inventory.json" "$impl" "$scenario" "$link_rate" "$rmw" "$netem" <<'PY'
import json,sys
path, impl, scenario, link_rate, rmw, netem = sys.argv[1:]
data=json.load(open(path, encoding="utf-8"))
data["effective_settings"]={"rmw":rmw, "rmw_implementation":impl,
    "scenario":scenario, "netem_profile":netem,
    "link_rate":link_rate or None, "replay_entrypoint":"replay_lab4.py",
    "receiver":"lab4-receiver"}
json.dump(data, open(path,"w",encoding="utf-8"), indent=2, sort_keys=True)
PY
    docker cp "$OUT_DIR/${CURRENT_CELL}.inventory.json" "${CELL_RECEIVER_IDS[0]}:/tmp/lab4-inventory.json" || return 1
    capture_shaping_state before none "" fleet || { CELL_INVALID=1; return 1; }
    managed 30 /dev/null sleep "${LAB4_REPLAY_WAIT:-12}" || return $?
    for id in "${CELL_FLEET_IDS[@]}" "${CELL_RECEIVER_IDS[@]}"; do
        if [[ "$(docker inspect --format '{{.State.Running}}' "$id" 2>/dev/null)" != true ]]; then
            fail "benchmark container stopped during startup: $id"
            docker logs "$id" >&2 || true
            return 1
        fi
    done
    if [[ "$netem" != none ]]; then apply_netem_fleet "$netem" "$link_rate" || rc=1; fi
    capture_shaping_state pre_measurement "$netem" "$link_rate" fleet || rc=1
    [[ "$rc" -eq 0 ]] || { CELL_INVALID=1; return 1; }
    local receiver="${CELL_RECEIVER_IDS[0]}" probe_out="$OUT_DIR/${CURRENT_CELL}.probe.stdout"
    OBS_PROBE_START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    CPU_SAMPLE_OUT="$OUT_DIR/${CURRENT_CELL}.cpu.samples.jsonl" CPU_CONTAINER="$receiver" managed "${LAB4_PROBE_TIMEOUT:-$((DURATION+45))}" "$probe_out" "$DOCKER_BIN" exec "$receiver" bash -c \
        'source /opt/ros/jazzy/setup.bash && exec python3 /scripts/lab4/class_probe.py "$@"' bash \
        --duration "$DURATION" --publishers "$cell_scale" --expected-inventory /tmp/lab4-inventory.json --out /tmp/probe.json \
        --template B --scenario "$scenario" --rmw "$rmw" --rmw-impl "$impl" --run-id "$CURRENT_CELL" || rc=$?
    OBS_PROBE_END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    docker cp "$receiver:/tmp/probe.json" "$OUT_DIR/${CURRENT_CELL}.probe.json" || {
        [[ "$rc" -ne 0 ]] || rc=1
    }
    capture_shaping_state post_measurement "$netem" "$link_rate" fleet || {
        CELL_INVALID=1
        [[ "$rc" -ne 0 ]] || rc=1
    }
    [[ "$rc" -eq 0 ]] || return "$rc"
    local fields cpu
    fields="$(python3 - "$probe_out" <<'CHECK'
import json,math,sys
try:
    d=json.loads(open(sys.argv[1]).read().splitlines()[-1])
    values=[d[k] for k in ('sensor_drop_pct','control_p99_ms','state_freshness_ms','throughput_mbps')]
    assert all(v is None or (type(v) in (int,float) and math.isfinite(v)) for v in values)
    print(*['n/a' if v is None else v for v in values])
except (OSError,ValueError,KeyError,IndexError,TypeError,AssertionError):
    raise SystemExit(1)
CHECK
)" || return 1
    cpu="${CPU_MEAN:-n/a}"
    echo "$fields ${cpu:-n/a}"
}

finalize_cell() {
    ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    local drop=n/a p99=n/a fresh=n/a thru=n/a cpu=n/a status=ok reasons="" cleanup_ok=true
    read -r drop p99 fresh thru cpu < "$cell_metrics" || true
    # Preserve the workload's specific exit status. An empty metrics file is a
    # secondary symptom after startup/probe failure and must not collapse 7 or
    # 124 into a generic exit 1.
    if [[ "$workload_status" -eq 0 ]]; then
        numeric_tuple "$drop" "$p99" "$fresh" "$thru" "$cpu" || workload_status=1
    fi
    if [[ "$workload_status" -ne 0 ]]; then status=failed; reasons="workload_exit_$workload_status"; fi
    if [[ "$CELL_INVALID" -ne 0 ]]; then status=invalid; reasons="${reasons:+$reasons,}shaping_mismatch"; fi
    if ! cleanup_cell; then status=failed; cleanup_ok=false; reasons="${reasons:+$reasons,}cleanup_failed"; fi
    if [[ "$OWNERSHIP_UNSAFE" -ne 0 ]]; then status=failed; reasons="${reasons:+$reasons,}ownership_unverified"; fi
    if [[ "$INTERRUPTED" -ne 0 ]]; then status=interrupted; reasons="${reasons:+$reasons,}signal"; fi
    [[ "$status" == ok ]] || SWEEP_STATUS=1
    local window artifacts observations cpu_measurement explicit_metrics template_a_metrics legacy_fresh
    window="$(python3 - "$started" "$ended" "$OBS_WORKLOAD_START" "$OBS_WORKLOAD_END" "$OBS_PROBE_START" "$OBS_PROBE_END" <<'CHECK'
import json,sys
print(json.dumps(dict(zip(('cell_started','cell_ended','observed_workload_started','observed_workload_ended','observed_probe_started','observed_probe_ended'),[v or None for v in sys.argv[1:]]))))
CHECK
)"
    artifacts="$(python3 - "$OUT_DIR" "$CURRENT_CELL" "$cleanup_ok" <<'CHECK'
import json,sys,pathlib
root,cell,clean=sys.argv[1:]
print(json.dumps({'files':[str(p) for p in sorted(pathlib.Path(root).glob(cell+'.*'))], 'cleanup_verified':clean=='true'}))
CHECK
)"
    observations="{}"; explicit_metrics="{}"; template_a_metrics="{}"
    if [[ -f "$OUT_DIR/${CURRENT_CELL}.probe.json" ]]; then
        observations="$(python3 - "$OUT_DIR/${CURRENT_CELL}.probe.json" <<'CHECK'
import json,sys
d=json.load(open(sys.argv[1], encoding="utf-8"))
print(json.dumps({"measurement_window":d.get("measurement_window"), "inventory_summary":d.get("inventory_summary"),
                  "topic_metrics":d.get("topic_metrics",{}), "class_silence":d.get("class_silence",{})}))
CHECK
)"
        explicit_metrics="$(python3 - "$OUT_DIR/${CURRENT_CELL}.probe.json" <<'CHECK'
import json,sys
m=json.load(open(sys.argv[1], encoding="utf-8")).get("metrics",{})
print(json.dumps(m))
CHECK
)"
    fi
    if [[ -f "$OUT_DIR/${CURRENT_CELL}.synthetic.metrics.json" ]]; then
        observations="$(cat "$OUT_DIR/${CURRENT_CELL}.synthetic.metrics.json")"
        explicit_metrics="$observations"
        template_a_metrics="$(python3 - "$explicit_metrics" <<'CHECK'
import json,sys
print(json.dumps(json.loads(sys.argv[1]).get("template_a",{})))
CHECK
)"
    fi
    cpu_measurement="{}"
    if [[ -f "$OUT_DIR/${CURRENT_CELL}.cpu.samples.jsonl" ]]; then
        cpu_measurement="$(python3 - "$OUT_DIR/${CURRENT_CELL}.cpu.samples.jsonl" <<'CHECK'
import json,sys
samples=[json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
values=[x["cpu_pct"] for x in samples]
print(json.dumps({"samples":samples, "sample_count":len(samples),
                  "mean_cpu_pct":round(sum(values)/len(values),2) if values else None,
                  "available":bool(samples), "kind":"receiver_workload_cpu"}))
CHECK
)"
    fi
    sensor_shortfall="$(python3 - "$explicit_metrics" <<'CHECK'
import json,sys
v=json.loads(sys.argv[1]).get("sensor_estimated_delivery_shortfall_pct")
print("n/a" if v is None else v)
CHECK
)"
    sensor_ratio="$(python3 - "$explicit_metrics" <<'CHECK'
import json,sys
v=json.loads(sys.argv[1]).get("sensor_received_expected_ratio")
print("n/a" if v is None else v)
CHECK
)"
    control_gap="$(python3 - "$explicit_metrics" <<'CHECK'
import json,sys
v=json.loads(sys.argv[1]).get("control_arrival_gap_p99_ms")
print("n/a" if v is None else v)
CHECK
)"
    state_gap="$(python3 - "$explicit_metrics" <<'CHECK'
import json,sys
v=json.loads(sys.argv[1]).get("state_arrival_gap_p95_ms")
print("n/a" if v is None else v)
CHECK
)"
    control_silence="$(python3 - "$explicit_metrics" <<'CHECK'
import json,sys
v=json.loads(sys.argv[1]).get("control_max_silence_ms")
print("n/a" if v is None else v)
CHECK
)"
    state_silence="$(python3 - "$explicit_metrics" <<'CHECK'
import json,sys
v=json.loads(sys.argv[1]).get("state_max_silence_ms")
print("n/a" if v is None else v)
CHECK
)"
    provenance="{}"
    [[ -f "$OUT_DIR/${CURRENT_CELL}.inventory.json" ]] && provenance="$(cat "$OUT_DIR/${CURRENT_CELL}.inventory.json")"
    legacy_fresh="$fresh"
    [[ "$t" != A ]] || legacy_fresh=n/a
    R_TEMPLATE="$t" R_TOPOLOGY="$cell_topo" R_SCENARIO="$s" R_RMW="$r" R_RMW_IMPL="$local_impl" \
    R_REQUESTED_RMWS="$RMWS" \
    R_WORKLOAD="$workload" R_ENGINE="$engine" R_SCALE="$cell_scale" R_SCALE_SOURCE="$scale_source" R_DURATION="$DURATION" R_NETEM="$impair" \
    R_RUN_ID="$SWEEP_ID" R_CELL_ID="$CURRENT_CELL" R_STARTED="$started" R_ENDED="$ended" R_STATUS="$status" \
    R_REASONS="$reasons" R_MEASUREMENT_WINDOW="$window" R_ARTIFACTS="$artifacts" R_PROVENANCE="$provenance" \
    R_OBSERVATIONS="$observations" R_CPU_MEASUREMENT="$cpu_measurement" \
    R_TEMPLATE_A_METRICS="$template_a_metrics" \
    R_SENSOR_DROP="$drop" R_CONTROL_P99="$p99" R_STATE_FRESH="$legacy_fresh" R_THROUGHPUT="$thru" R_CPU="$cpu" \
    R_SENSOR_SHORTFALL="$sensor_shortfall" R_SENSOR_RATIO="$sensor_ratio" R_CONTROL_GAP_P99="$control_gap" \
    R_STATE_GAP_P95="$state_gap" R_CONTROL_SILENCE="$control_silence" R_STATE_SILENCE="$state_silence" \
        python3 "$SCRIPT_DIR/emit_result.py" > "$OUT_DIR/${CURRENT_CELL}.result.json" || { SWEEP_STATUS=1; CELL_CLEANUP_FAILED=1; }
    cat "$OUT_DIR/${CURRENT_CELL}.result.json" >> "$RESULTS" || { SWEEP_STATUS=1; CELL_CLEANUP_FAILED=1; }
    CELL_ACTIVE=0
    CELL_COUNT=$((CELL_COUNT + 1))
    [[ "$status" == ok ]] || warn "cell $CURRENT_CELL: $status ($reasons)"
}

# --- main sweep -------------------------------------------------------------
CELL_COUNT=0
SWEEP_STATUS=0
for t in "${TEMPLATE_LIST[@]}"; do
    executor="$(defs harness-executor "$t" 2>/dev/null || echo unavailable)"
    case "$executor" in
        synthetic|mcap) ;;
        unavailable) warn "skip: template $t has no runnable workshop deployment"; continue ;;
        *) warn "skip: template $t has unknown executor '$executor'"; continue ;;
    esac
    compose_profile="$(defs harness-profile "$t" 2>/dev/null || true)"
    topology="$(defs harness-topology "$t" 2>/dev/null || true)"
    workload="$(defs harness-workload "$t" 2>/dev/null || true)"
    impairment_mode="$(defs harness-impairment "$t" 2>/dev/null || true)"
    if [[ -z "$compose_profile" || -z "$topology" || -z "$workload" || -z "$impairment_mode" ]]; then
        warn "skip: template $t has an incomplete harness definition"; continue
    fi
    # scenario set for this template
    if [[ "$SCENARIOS" == all ]]; then
        # shellcheck disable=SC2207
        SCEN_SET=($(defs scenarios "$t" 2>/dev/null))
    elif [[ ${#SCENARIO_OVERRIDE[@]} -gt 0 ]]; then
        SCEN_SET=("${SCENARIO_OVERRIDE[@]}")
    else
        SCEN_SET=(S0)
    fi
    if [[ ${#SCEN_SET[@]} -eq 0 ]]; then
        warn "template $t has no runnable scenarios - skipping"
        continue
    fi

    for r in "${RMW_LIST[@]}"; do
        local_impl="$(defs rmw-impl "$r" 2>/dev/null || echo unknown)"
        for s in "${SCEN_SET[@]}"; do
            if ! defs allowed "$t" "$s" >/dev/null 2>&1; then
                warn "skip: scenario $s not allowed for template $t"
                continue
            fi
            netem="none"
            if [[ "$impairment_mode" == "per_replica_netem" ]]; then
                netem="$(defs netem "$s" 2>/dev/null || echo none)"
            elif [[ "$impairment_mode" != "none" ]]; then
                warn "skip: template $t has unknown impairment mode '$impairment_mode'"; continue
            fi
            engine="$executor"
            cell_topo="$topology"
            impair="$netem"

            # The synthetic A/B executor has no per-link shaping implementation.
            if [[ "$engine" == "synthetic" && "$netem" != "none" ]]; then
                warn "skip: scenario $s needs netem ('$netem') - use --template B"
                continue
            fi

            if [[ "$engine" == synthetic ]]; then
                SCALE_SET=(2)
                scale_source="template-a-pair"
            elif [[ "$s" == S1 ]]; then
                # S1 is a configured replica sweep, not a playback multiplier.
                read -ra SCALE_SET <<< "$(defs scenario-scales "$s")"
                scale_source="scenario-config"
            else
                SCALE_SET=("$SCALE")
                scale_source="cli"
            fi
            [[ ${#SCALE_SET[@]} -gt 0 ]] || { fail "scenario $s has no configured scales"; exit 2; }
            for cell_scale in "${SCALE_SET[@]}"; do

            info "cell: template=$t topology=$cell_topo scenario=$s rmw=$r scale=$cell_scale engine=$engine workload=$workload impair='$impair'"
            [[ "$INTERRUPTED" -eq 0 ]] || break 4
            started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
            cell_id="${SWEEP_ID}_${CELL_COUNT}_${t}_${cell_topo}_${s}_${r}_${cell_scale}x"
            CURRENT_CELL="$cell_id"
            SHAPING_ARTIFACT="$OUT_DIR/${cell_id}.shaping.jsonl"
            : > "$SHAPING_ARTIFACT"
            cell_metrics="$OUT_DIR/${CURRENT_CELL}.metrics"
            : > "$cell_metrics"
            CELL_INVALID=0
            OBS_WORKLOAD_START=""; OBS_WORKLOAD_END=""; OBS_PROBE_START=""; OBS_PROBE_END=""
            CELL_FLEET_IDS=(); CELL_RECEIVER_IDS=(); CELL_ROUTER_IDS=(); CELL_RMW_IDS=(); OWNED_IDS=()
            CELL_CLEANUP_FAILED=0
            CELL_ACTIVE=1
            workload_status=0
            if [[ "$engine" == "mcap" ]]; then
                run_mcap "$r" "$s" "$netem" "$compose_profile" "$cell_scale" >"$cell_metrics" 2>"$OUT_DIR/${cell_id}.log" || workload_status=$?
            else
                run_synthetic "$r" "$compose_profile" >"$cell_metrics" 2>"$OUT_DIR/${cell_id}.log" || workload_status=$?
            fi
            finalize_cell
            if [[ "$INTERRUPTED" -ne 0 || "$OWNERSHIP_UNSAFE" -ne 0 || "$CELL_CLEANUP_FAILED" -ne 0 ]]; then break 4; fi
            done
        done
    done
done

ok "Ran $CELL_COUNT cell(s) -> $RESULTS"

# --- analysis ---------------------------------------------------------------
if [[ "$CELL_COUNT" -eq 0 ]]; then
    warn "No cells ran - check --template/--scenario/--rmw against benchmark.yaml."
    SWEEP_STATUS=1
elif [[ "$INTERRUPTED" -ne 0 ]]; then
    warn "Interrupted after $CELL_COUNT cell(s); skipping comparison + Pugh generation."
    SWEEP_STATUS=1
else
    info "Generating comparison sheet + Pugh matrix"
    if ! docker exec --user "$(id -u):$(id -g)" -e HOME=/tmp ubuntu-headless python3 /scripts/lab4/comparison.py "$CONTAINER_OUT_DIR"; then SWEEP_STATUS=1; fi
    if ! docker exec --user "$(id -u):$(id -g)" -e HOME=/tmp ubuntu-headless python3 /scripts/lab4/pugh.py "$CONTAINER_OUT_DIR"; then SWEEP_STATUS=1; fi
    if ! docker exec --user "$(id -u):$(id -g)" -e HOME=/tmp ubuntu-headless python3 /scripts/lab4/plot_comparison.py "$CONTAINER_OUT_DIR" 2>/dev/null; then
        warn "comparison.png generation failed inside ubuntu-headless"; SWEEP_STATUS=1
    fi
fi

[[ "$INTERRUPTED" -eq 0 ]] || SWEEP_STATUS=130
exit "$SWEEP_STATUS"
