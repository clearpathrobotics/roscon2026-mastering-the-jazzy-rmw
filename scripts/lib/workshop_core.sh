#!/usr/bin/env bash
# workshop multi-lab runner infrastructure.
# shellcheck disable=SC1091,SC2317

GEN="$SCRIPT_DIR/gen_topology.sh"
NMAX=25
NETEM_PROFILE="$REPO_ROOT/lab2-on-the-wire/scripts/netem_profile.sh"
AP_SHAPE="$REPO_ROOT/lab3-stress-testing/scripts/ap_shape.sh"
FLEET_COLLECTOR="$REPO_ROOT/lab3-stress-testing/scripts/mock_fleet_netdata.sh"
FLEET_PIDFILE="$DOCKER_ROOT/.fleet_netdata.pid"
LAB4_SCRIPTS="$REPO_ROOT/lab4-benchmarking-and-decision/scripts"

# shellcheck source=workshop_preflight.sh
. "$SCRIPT_DIR/lib/workshop_preflight.sh"

declare -A TOPO_PROFILE=(   [star]=mock [flat]=mock   [routed]=routed )
declare -A TOPO_DEFAULT_N=( [star]=3    [flat]=3      [routed]=15 )

_check_topo() { [[ -n "${TOPO_PROFILE[$1]:-}" ]] || { fail "unknown topology '$1' (star|flat|routed)"; return 1; }; }
_check_n()    { [[ "$1" =~ ^[0-9]+$ && "$1" -ge 1 && "$1" -le "$NMAX" ]] || { fail "N must be 1..$NMAX, got '$1'"; return 1; }; }

# Normalize a friendly RMW name to its rmw_*_cpp impl (mirrors gen_topology.sh).
_resolve_rmw() {
    case "$1" in
        cyclone|cyclonedds|rmw_cyclonedds_cpp)  echo rmw_cyclonedds_cpp ;;
        fast|fastdds|fastrtps|rmw_fastrtps_cpp) echo rmw_fastrtps_cpp ;;
        zenoh|rmw_zenoh_cpp)                    echo rmw_zenoh_cpp ;;
        *) return 1 ;;
    esac
}

# Absolute -f makes compose's project dir docker/compose/, so pass --env-file at
# docker/.env[.local] explicitly for RMW / ROS_DOMAIN_ID overrides to still apply.
compose_topo() {
    local topo="$1"; shift
    local env_args=()
    [[ -f "$DOCKER_ROOT/.env" ]]       && env_args+=(--env-file "$DOCKER_ROOT/.env")
    [[ -f "$DOCKER_ROOT/.env.local" ]] && env_args+=(--env-file "$DOCKER_ROOT/.env.local")
    docker compose "${env_args[@]}" -f "$COMPOSE_DIR/$topo.yml" --profile "${TOPO_PROFILE[$topo]}" "$@"
}

# Expand the comma-separated --model / WORKSHOP_MODEL spec into per-robot
# MOCK_ROBOT_<k>_MODEL exports (k=1..N). The list cycles when it's shorter than N
# and extra entries (list longer than N) are ignored; an empty spec leaves each
# topology's built-in default model in place.
_export_models() {
    local n="$1" spec="${WORKSHOP_MODEL:-}"
    [[ -n "$spec" ]] || return 0
    local models; IFS=',' read -ra models <<< "$spec"
    local count="${#models[@]}" k model
    for k in $(seq 1 "$n"); do
        model="$(echo "${models[$(( (k - 1) % count ))]}" | xargs)"   # trim surrounding spaces
        [[ -n "$model" ]] && export "MOCK_ROBOT_${k}_MODEL=$model"
    done
}

# Robots this harness brought up, by container name - the topology fleet only.
# lab4's scaled fleet-N replicas belong to a different verb and are left alone.
running_robots() {
    docker ps --format '{{.Names}}' | grep -E '^mock-robot-[0-9]+$' || true
}

# up brings the fleet up and never removes a container as a side effect, so a smaller
# N than what is already running would silently strand the extra robots (their service
# names vanish from the regenerated compose). Surface the mismatch and let the user
# choose; only an explicit 'yes' runs the destructive teardown, and a non-interactive
# up (ex1_up.sh, CI) proceeds without prompting so it never hangs.
_confirm_scale_down() {
    local n="$1"
    local -a running=(); mapfile -t running < <(running_robots)
    (( ${#running[@]} > n )) || return 0
    if [[ ! -t 0 ]]; then
        warn "${#running[@]} robots running exceed the $n requested; keeping them - run 'workshop down' then 'workshop up $n' for exactly $n"
        return 0
    fi
    local ans
    read -r -p "${#running[@]} robots running, but you asked for $n. Type 'yes' to bring the fleet down and back up at $n; anything else keeps all ${#running[@]}: " ans
    if [[ "$ans" == yes ]]; then
        teardown_running_fleet
    else
        warn "keeping ${#running[@]} robots (you asked for $n) - run 'workshop down' then 'workshop up $n' for exactly $n"
    fi
}

topo_up() {
    local topo="$1" n="${2:-${TOPO_DEFAULT_N[$1]}}"
    local rmw_sel="${3:-${WORKSHOP_RMW:-}}"           # explicit choice, if any
    local skip_gen="${4:-}"                           # reuse existing generated output
    local rmw="${rmw_sel:-rmw_cyclonedds_cpp}"
    _check_n "$n" || return 1
    _confirm_scale_down "$n"
    _export_models "$n"
    if [[ -n "$skip_gen" ]]; then
        [[ -f "$COMPOSE_DIR/$topo.yml" ]] || die "no $COMPOSE_DIR/$topo.yml to reuse - run 'workshop -t $topo up' once before '--skip-gen'"
        info "Skipping generation; reusing the existing $topo compose file and rmw_configurations"
    else
        info "Generating $topo topology (N=$n, rmw=$rmw)"
        bash "$GEN" "$topo" "$n" "$rmw"
    fi
    # An explicit RMW choice (positional arg or WORKSHOP_RMW) must beat docker/.env's
    # default: exporting it into compose's shell env wins over --env-file interpolation.
    if [[ -n "$rmw_sel" ]]; then
        local impl; impl="$(_resolve_rmw "$rmw")" || die "unknown rmw '$rmw' (cyclone|fastdds|zenoh)"
        export RMW_IMPLEMENTATION="$impl"
    fi
    info "Bringing up the $topo stack"
    compose_topo "$topo" up -d
    ok "$topo stack up. Allow a moment for bringup (first start / --build compiles the workspace)."
    ok "Observer is idle; start its Foxglove bridge with: workshop observer bridge"
}

teardown_topology() {
    local topo="$1"
    local -a services=()

    [[ -f "$COMPOSE_DIR/$topo.yml" ]] || {
        warn "no $COMPOSE_DIR/$topo.yml - run 'workshop -t $topo up' first"
        return 0
    }

    mapfile -t services < <(compose_topo "$topo" config --services)
    if [[ ${#services[@]} -eq 0 ]]; then
        warn "no services found in $COMPOSE_DIR/$topo.yml"
        return 0
    fi

    info "Tearing the $topo stack down"
    compose_topo "$topo" rm -sf "${services[@]}"
    ok "$topo stack down."
}

# The live topology, read from the networks the observer container is attached to:
# flat-net, observer-net, and mock-b* are each unique to one topology. Reading the
# running observer (not `compose ps`) avoids a false match, since flat.yml and
# routed.yml share the mock-robot-N/observer service names. Empty if no observer is up.
running_topology() {
    local nets
    nets="$(docker inspect observer --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>/dev/null)" || return 0
    case "$nets" in
        *flat-net*)     echo flat ;;
        *observer-net*) echo routed ;;
        *mock-b*)       echo star ;;
    esac
}

# Tear down whichever topology is running, regardless of the -t in effect.
teardown_running_fleet() {
    local topo torn=false
    topo="$(running_topology)"
    [[ -n "$topo" ]] && { teardown_topology "$topo"; torn=true; }
    # An additive scale-down (a non-'yes' 'up N' below the running count) leaves robots
    # whose service name was dropped from the regenerated compose, so the compose
    # teardown above can no longer see them. Sweep them by name so down clears them too.
    local -a orphans=(); mapfile -t orphans < <(running_robots)
    if (( ${#orphans[@]} )); then
        docker rm -f "${orphans[@]}" >/dev/null 2>&1 && ok "removed ${#orphans[@]} orphaned robot(s)"
    elif [[ "$torn" == false ]]; then
        info "no running fleet"
    fi
}

cmd_down() {
    local topo="$1"; shift
    local all=false arg
    for arg in "$@"; do
        case "$arg" in
            --all) all=true ;;
            *) fail "unknown down option: $arg"; return 2 ;;
        esac
    done
    # Finalize any running capture inside the observer so its last pcap is
    # complete and host-owned before the container is torn out from under it.
    docker inspect observer >/dev/null 2>&1 &&
        docker exec -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" observer bash /scripts/run_observer.sh capture stop >/dev/null 2>&1 || true
    teardown_running_fleet
    # `rm -sf` in teardown removes the fleet's containers but not its networks, and a
    # smaller-N `down` can't see a previous larger-N fleet's per-robot networks either.
    # Prune this project's now-unused networks so a plain `down` leaves nothing behind.
    # Prune only removes networks with no container attached, so a running webshark or
    # netdata keeps its own. The project matches the `name:` in the generated compose.
    docker network prune -f --filter label=com.docker.compose.project=roscon2026-jazzy-rmw >/dev/null 2>&1 || true
    # Each standalone service has its own `down`; a plain `down` leaves them running
    # by design. --all is the whole-session cleanup that stops them too.
    if [[ "$all" == true ]]; then
        cmd_collector "$topo" down 2>/dev/null || true
        cmd_webshark down 2>/dev/null || true
        cmd_lichtblick down 2>/dev/null || true
        cmd_netdata down 2>/dev/null || true
        lab4_core_down
        # Best-effort cleanup does not abort, but report anything that did not
        # actually stop rather than hiding it behind a clean exit.
        local svc; local -a still=()
        for svc in webshark netdata lichtblick ubuntu-headless; do
            [[ "$(docker inspect -f '{{.State.Running}}' "$svc" 2>/dev/null)" == true ]] && still+=("$svc")
        done
        if fleet_collector_alive; then still+=(collector); fi
        [[ ${#still[@]} -eq 0 ]] || warn "down --all: still running after cleanup: ${still[*]}"
    fi
}

netem_targets() {
    local requested="${1:-}" target
    if [[ -n "$requested" ]]; then
        target="mock-robot-$requested"
        [[ "$(docker inspect -f '{{.State.Running}}' "$target" 2>/dev/null)" == true ]] || {
            fail "robot '$requested' is not running"
            return 1
        }
        printf '%s\n' "$target"
        return 0
    fi

    docker ps --format '{{.Names}}' \
        | grep -E '^(mock-robot-[0-9]+|fleet-[0-9]+)$' \
        | sort -V
}

# Bare `netem` shows the current shaping state instead of applying a profile.
# flat reports each robot's own link; routed reports the AP's one shared budget;
# star has no shaping story.
netem_state() {
    local topology="$1"
    case "$topology" in
        flat)   netem_state_flat ;;
        routed) bash "$AP_SHAPE" status ;;
        star)   info "star topology has no network shaping"; return 0 ;;
    esac
}

# The impairment on one device's netem qdisc (delay/loss/rate/...) with tc's own
# handle and queue bookkeeping stripped off; "clean" if the device has no netem,
# "?" if its qdisc could not be read.
netem_spec_on() {
    local container="$1" dev="$2" out
    if ! out="$(docker exec "$container" tc qdisc show dev "$dev" 2>/dev/null)"; then
        # eth0 always exists, so a failed read there is a real error ("?"); ifb0 is
        # simply absent until ingress shaping is applied, which reads as unshaped.
        [[ "$dev" == ifb0 ]] && { echo clean; return 0; }
        echo "?"; return 0
    fi
    local spec; spec="$(sed -nE 's/^qdisc netem [^ ]+ root (refcnt [0-9]+ )?limit [0-9]+ //p' <<<"$out" | head -1)"
    echo "${spec:-clean}"
}

# flat robots are single-homed on flat-net, so the shaped link is eth0 (egress)
# plus the per-container ifb0 that mirrors ingress onto it. A robot that no longer
# answers reads as unreachable, distinct from a running-but-unshaped one.
netem_state_flat() {
    local -a targets=()
    mapfile -t targets < <(netem_targets)
    if [[ ${#targets[@]} -eq 0 ]]; then
        info "no running fleet robots"
        return 0
    fi
    local t egress ingress
    printf "%-16s %s\n" "ROBOT" "SHAPING (eth0 egress / ifb0 ingress)"
    for t in "${targets[@]}"; do
        if ! docker exec "$t" true 2>/dev/null; then
            printf "%-16s %s\n" "$t" "(unreachable)"
            continue
        fi
        egress="$(netem_spec_on "$t" eth0)"
        ingress="$(netem_spec_on "$t" ifb0)"
        printf "%-16s %s / %s\n" "$t" "$egress" "$ingress"
    done
}

# Topology comes from the caller's own -t/--topology resolution (main()'s $topo),
# not re-detected here - flat uses the per-link IFB engine, routed uses the
# AP's shared-budget HTB engine; star has no shaping story at all.
cmd_netem() {
    local topology="$1"; shift
    local action="${1:-}"
    [[ $# -gt 0 ]] && shift
    local target_arg="" rate="" target rc=0
    local -a targets=()

    _check_topo "$topology" || return 2

    # `netem status` is an explicit alias for the bare status view, so it reads the
    # same on every topology (routed's ap_shape already accepts `status`; flat's
    # profile engine would otherwise reject it as an unknown profile).
    if [[ -z "$action" || "$action" == status ]]; then
        netem_state "$topology" || rc=1
        return "$rc"
    fi

    case "$topology" in
        flat)
            while [[ $# -gt 0 ]]; do
                case "$1" in
                    --rate)
                        [[ $# -ge 2 ]] || { fail "--rate needs a value"; return 2; }
                        rate="$2"; shift 2 ;;
                    [0-9]*)
                        [[ -z "$target_arg" ]] || { fail "usage: workshop netem <profile|clear|list> [robot] [--rate RATE]"; return 2; }
                        target_arg="$1"; shift ;;
                    *)
                        fail "usage: workshop netem <profile|clear|list> [robot] [--rate RATE]"
                        return 2 ;;
                esac
            done
            case "$action" in
                list)
                    [[ -z "$target_arg" && -z "$rate" ]] || {
                        fail "usage: workshop netem list"
                        return 2
                    }
                    bash "$NETEM_PROFILE" list ;;
                clear)
                    [[ -z "$rate" ]] || {
                        fail "--rate cannot be used with 'clear'"
                        return 2
                    }
                    mapfile -t targets < <(netem_targets "$target_arg")
                    [[ ${#targets[@]} -gt 0 ]] || {
                        fail "no running robot targets found"
                        return 1
                    }
                    for target in "${targets[@]}"; do
                        LINK_RATE='' bash "$NETEM_PROFILE" "$action" "$target" || rc=1
                    done
                    return "$rc" ;;
                *)
                    mapfile -t targets < <(netem_targets "$target_arg")
                    [[ ${#targets[@]} -gt 0 ]] || {
                        fail "no running robot targets found"
                        return 1
                    }
                    for target in "${targets[@]}"; do
                        LINK_RATE="$rate" bash "$NETEM_PROFILE" "$action" "$target" || rc=1
                    done
                    return "$rc" ;;
            esac
            ;;
        routed)
            case "$action" in
                rateonly)
                    [[ $# -ge 1 ]] || { fail "usage: workshop netem rateonly <rate> [netem-spec]"; return 2; }
                    [[ $# -le 2 ]] || { fail "usage: workshop netem rateonly <rate> [netem-spec]"; return 2; }
                    bash "$AP_SHAPE" rateonly "$1" "${2:-}" ;;
                *)
                    [[ $# -eq 0 ]] || { fail "usage: workshop netem <profile|clear|list>"; return 2; }
                    bash "$AP_SHAPE" "$action" ;;
            esac
            ;;
        star)
            fail "netem is supported for flat (per-link) and routed (shared AP) topologies, not star"
            return 2
            ;;
    esac
}

fleet_collector_alive() {
    [[ -f "$FLEET_PIDFILE" ]] || return 1
    local pid
    pid="$(cat "$FLEET_PIDFILE" 2>/dev/null)"
    [[ -n "$pid" ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    if [[ -r "/proc/$pid/cmdline" ]]; then
        grep -qa "mock_fleet_netdata.sh" "/proc/$pid/cmdline" 2>/dev/null
    else
        ps -p "$pid" -o args= 2>/dev/null | grep -q "mock_fleet_netdata.sh"
    fi
}

fleet_running_containers() {
    docker ps --format '{{.Names}}' \
        | grep -E '^(observer|mock-robot-[0-9]+)$' \
        | sort -V \
        || true
}

# collector up|down: the fleet-targeted Netdata collector, layered on top of
# whatever topology is already running. Netdata is shared core-stack
# infrastructure (also used by Lab 4), so `collector down` never stops it -
# only the collector process it started.
cmd_collector() {
    local topology="$1" action="${2:-}"
    local targets pid

    _check_topo "$topology" || return 2
    [[ -n "$action" ]] || {
        fail "usage: workshop collector <up|down>"
        return 2
    }

    case "$action" in
        up)
            [[ $# -eq 2 ]] || {
                fail "usage: workshop collector up"
                return 2
            }
            targets="$(fleet_running_containers)"
            [[ -n "$targets" ]] || {
                fail "no running fleet containers - bring up the $topology topology first"
                return 1
            }
            if fleet_collector_alive; then
                ok "Fleet collector already running (pid $(cat "$FLEET_PIDFILE"))"
                return 0
            fi
            if [[ "$(docker inspect -f '{{.State.Running}}' netdata 2>/dev/null)" != true ]]; then
                fail "Netdata is not running - bring it up first: workshop netdata up"
                return 1
            fi
            info "Starting fleet collector for: ${targets//$'\n'/ }"
            if [[ "$topology" == flat ]]; then
                # Pinned robots (mock-robot-1..EX1_PINNED_ROBOTS) are the named group; the
                # higher-numbered default replicas are matched by pattern at collect time,
                # so scaling the fleet updates the charts without a collector restart.
                local pinned="${EX1_PINNED_ROBOTS:-3}" target
                local -a named_containers=()
                while IFS= read -r target; do
                    if [[ "$target" =~ ^mock-robot-([0-9]+)$ ]] && (( BASH_REMATCH[1] > pinned )); then
                        continue
                    fi
                    named_containers+=("$target")
                done <<< "$targets"
                FLEET_NAMED_CONTAINERS="${named_containers[*]}" \
                    FLEET_DEFAULT_PATTERN='mock-robot' \
                    setsid nohup env -u FLEET_DEFAULT_CONTAINERS bash "$FLEET_COLLECTOR" >/dev/null 2>&1 &
            else
                FLEET_NAMED_CONTAINERS="${targets//$'\n'/ }" \
                    FLEET_DEFAULT_PATTERN='__workshop_fleet_no_default_group__' \
                    setsid nohup env -u FLEET_DEFAULT_CONTAINERS bash "$FLEET_COLLECTOR" >/dev/null 2>&1 &
            fi
            pid=$!
            echo "$pid" > "$FLEET_PIDFILE"
            ok "Fleet collector up (pid $pid). Netdata: http://localhost:19999"
            ;;
        down)
            [[ $# -eq 2 ]] || {
                fail "usage: workshop collector down"
                return 2
            }
            if fleet_collector_alive; then
                pid="$(cat "$FLEET_PIDFILE")"
                kill "$pid" 2>/dev/null || true
                ok "Fleet collector stopped (pid $pid)"
            else
                info "Fleet collector is not running"
            fi
            rm -f "$FLEET_PIDFILE"
            ;;
        *)
            fail "collector action must be 'up' or 'down'"
            return 2
            ;;
    esac
}

# Lab 4 uses the repository's full compose file rather than a generated
# topology overlay. Keep this adapter separate from compose_topo: Lab 4's
# ubuntu-headless and netdata services are shared infrastructure, not a
# topology that should be regenerated or torn down by the generic verbs.
lab4_compose() {
    (
        cd "$DOCKER_ROOT" || exit 1
        set -a
        [[ -f .env.local ]] && . ./.env.local
        set +a
        docker compose "$@"
    )
}

lab4_core_up() {
    info "Bringing up Lab 4 core stack: ubuntu-headless"
    lab4_compose up -d ubuntu-headless
}

# A plain `down` leaves the Lab 4 core stack running (exercises reuse it across
# sweeps); `down --all` tears it down as part of the whole-session cleanup.
lab4_core_down() {
    info "Bringing down Lab 4 core stack"
    lab4_compose down 2>/dev/null || true
}

cmd_lab4_genbag() {
    ensure_capture_dir "$DOCKER_ROOT/bags"
    bash "$LAB4_SCRIPTS/gen_bag.sh" "$@"
}

cmd_lab4_fetchbag() {
    bash "$LAB4_SCRIPTS/fetch_bag.sh" "$@"
}

cmd_lab4_run() {
    local arg dry_run=false
    for arg in "$@"; do
        [[ "$arg" == --dry-run ]] && dry_run=true
    done

    if [[ "$dry_run" == true ]]; then
        info "Skipping host preflight and Lab 4 core bring-up for dry-run"
    else
        info "Running host preflight before the Lab 4 sweep"
        bash "$DOCKER_ROOT/scripts/preflight.sh"
        ensure_capture_dir "$DOCKER_ROOT/bags"
        ensure_capture_dir "$DOCKER_ROOT/captures"
        lab4_core_up
    fi

    bash "$LAB4_SCRIPTS/run_sweep.sh" "$@"
}

# Off flat, the observer's one interface can't see the whole fleet (star: it is on every
# isolated spoke; routed: every packet crosses the wifi-ap), so an automated capture would
# record a partial, misleading pcap. Hand the operator the exact commands to record it
# themselves - as they would on a real robot - into the same mounted captures directory.
capture_guide() {
    local topo="$1" vantage why
    case "$topo" in
        routed) vantage=wifi-ap;  why="every packet crosses the wifi-ap" ;;
        star)   vantage=observer; why="the observer sits on every isolated spoke" ;;
    esac
    info "capture is automated on flat only; on $topo, record it yourself ($why):"
    cat <<EOF
  list interfaces:  docker exec $vantage dumpcap -D
  record all nets:  docker exec -d $vantage dumpcap -i any -w /lab2-captures/$topo.pcap
  view in webshark: http://localhost:8085/webshark/   ($topo.pcap appears there)
  stop recording:   docker exec $vantage pkill dumpcap
The /lab2-captures directory is already mounted, so the file appears in webshark with no
extra step, and it is yours to keep - 'observer capture clear' removes only the harness's
own live_/stream_ captures.
EOF
}

# Capture/bag dirs must be world-writable with the sticky bit (1777, like /tmp):
# tshark/dumpcap drops privileges to write the pcap, so a user-owned 775 dir gives it
# "Permission denied"; and compose would otherwise auto-create a missing bind mount as
# root. Creating the dir here as the invoking user keeps it writable without sudo. If it
# is already owned by another user (a prior root-created dir), warn with the exact fix.
ensure_capture_dir() {
    local dir="$1" current_mode
    mkdir -p "$dir" 2>/dev/null
    current_mode="$(stat -c '%a' "$dir" 2>/dev/null)"
    [[ "$current_mode" == 1777 ]] && return 0
    chmod 1777 "$dir" 2>/dev/null || warn "cannot set 1777 on $dir; if captures fail run: sudo chmod 1777 $dir"
}

# `observer capture start` parses the operator-facing flags on the host, then runs
# the capture inside the observer via run_observer.sh - forwarding the ring/stream
# limits as environment and the host uid/gid so the pcaps come out owned by the
# host user (readable from the webshark container while they are still growing).
observer_capture_start() {
    local n=3 mode=rotating duration=30 files=6 autostop=1800 max_mb=2000
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --streaming) mode=streaming; shift ;;
            --duration|--files|--autostop|--max-mb)
                [[ $# -ge 2 && "$2" =~ ^[1-9][0-9]*$ ]] || { fail "$1 needs a positive integer value"; return 2; }
                case "$1" in
                    --duration) duration="$2" ;;
                    --files)    files="$2" ;;
                    --autostop) autostop="$2" ;;
                    --max-mb)   max_mb="$2" ;;
                esac
                shift 2 ;;
            [0-9]*)
                [[ "$1" =~ ^[1-9][0-9]*$ ]] || { fail "robot count must be a positive integer, got '$1'"; return 2; }
                n="$1"; shift ;;
            *) fail "unknown capture option '$1'"; return 2 ;;
        esac
    done
    # Each file in the rotating ring needs at least 1 MB (tshark's per-file size is
    # LIVE_MAX_MB*1000/RETENTION KB), so a total smaller than the file count is invalid.
    if [[ "$mode" == rotating && "$max_mb" -lt "$files" ]]; then
        fail "--max-mb ($max_mb) must be at least --files ($files); each ring file needs >=1MB"
        return 2
    fi
    # The automated observer capture only sees the whole fleet on flat; off flat it would
    # record a partial pcap, so hand the operator the manual recipe instead.
    local topo; topo="$(running_topology)"
    if [[ "$topo" == star || "$topo" == routed ]]; then
        capture_guide "$topo"
        return 0
    fi
    ensure_capture_dir "$REPO_ROOT/lab2-on-the-wire/captures"
    docker exec \
        -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
        -e RETENTION="$files" -e LIVE_MAX_SECONDS="$autostop" -e LIVE_MAX_MB="$max_mb" \
        observer bash /scripts/run_observer.sh capture start "$mode" "$n" "$duration" || return 1
    ok "capture running at the observer. webshark: http://localhost:8085/webshark/"
    info "re-trigger discovery: workshop observer capture bounce   |   stop: workshop observer capture stop"
}

# Delete the capture files this harness wrote to the shared captures directory,
# freeing the disk they use between labs. Manual-only (no other verb calls it) and
# interactive (a destructive delete, so it confirms first). Confined to the captures
# directory, and within it only this harness's own live_/stream_ output - never a
# fixture or an operator's own pcap.
observer_capture_clear() {
    local dir="$REPO_ROOT/lab2-on-the-wire/captures"
    # Never delete out from under a running capture.
    if docker inspect -f '{{.State.Running}}' observer >/dev/null 2>&1 \
       && docker exec observer sh -c 'ps -eo comm 2>/dev/null | grep -qx tshark'; then
        fail "a capture is running - stop it first: workshop observer capture stop"
        return 1
    fi
    local -a files=()
    mapfile -t files < <(ls -1 "$dir"/live_*.pcap "$dir"/stream_*.pcap "$dir"/live_*.arrivals.csv 2>/dev/null)
    [[ ${#files[@]} -gt 0 ]] || { info "no capture files to clear in lab2-on-the-wire/captures/"; return 0; }
    local size; size="$(du -ch "${files[@]}" 2>/dev/null | tail -1 | cut -f1)"
    [[ -t 0 ]] || { fail "capture clear is interactive - run it yourself in a terminal"; return 1; }
    local ans
    read -r -p "delete ${#files[@]} capture files (${size:-?}) from lab2-on-the-wire/captures/? type 'yes' to confirm: " ans
    [[ "$ans" == yes ]] || { info "cancelled"; return 0; }
    rm -f "${files[@]}"
    ok "cleared ${#files[@]} capture files (${size:-?}) from lab2-on-the-wire/captures/"
}

# The observer container (named `observer` in every topology) comes up idle - a
# persistent vantage. `observer bridge` starts its Foxglove bridge on demand (+
# fleet_map for routed); `observer capture` drives tshark inside it.
cmd_observer() {
    local action="${1:-}"
    case "$action" in
        bridge)
            docker inspect observer >/dev/null 2>&1 || { fail "no 'observer' container - bring a topology up first"; return 1; }
            info "Starting the observer's Foxglove bridge"
            docker exec -d observer bash /scripts/run_observer.sh bridge
            local port="${FOXGLOVE_BRIDGE_PORT:-8765}"
            ok "Foxglove bridge on :$port. Lichtblick: http://localhost:8080/?ds=foxglove-websocket&ds.url=ws://localhost:$port" ;;
        capture)
            shift
            local sub="${1:-}"; shift || true
            # clear is host-side disk cleanup that must work with the fleet down
            # (between labs), so it runs before the container-exists check.
            if [[ "$sub" == clear ]]; then observer_capture_clear "$@"; return; fi
            docker inspect observer >/dev/null 2>&1 || { fail "no 'observer' container - bring a fleet up first: workshop -t flat up 3"; return 1; }
            case "$sub" in
                start)  observer_capture_start "$@" ;;
                stop)   docker exec -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" observer bash /scripts/run_observer.sh capture stop ;;
                bounce) docker exec observer bash /scripts/run_observer.sh capture bounce ;;
                *) fail "usage: workshop observer capture <start|stop|bounce|clear> [options]"; return 2 ;;
            esac ;;
        *) fail "usage: workshop observer <bridge|capture>"; return 2 ;;
    esac
}

# Open an interactive shell in any container the topology brought up. Star/routed
# pin container_name (so `mock-robot-1` is exact); scaled flat replicas get the
# compose-prefixed name (e.g. <project>-mock-robot-1), which we resolve by an
# end-anchored `docker ps` name match so the short name the attendee typed works.
cmd_shell() {
    local target="${1:-}"
    [[ -n "$target" ]] || { fail "usage: workshop shell <container>  (e.g. mock-robot-1, observer)"; return 2; }
    local container
    if docker inspect "$target" >/dev/null 2>&1; then
        container="$target"
    else
        container="$(docker ps --format '{{.Names}}' --filter "name=${target}$" | head -n1)"
    fi
    [[ -n "$container" ]] || { fail "no running container matching '$target' - is a topology up? try 'docker ps'"; return 1; }
    info "Opening a shell in $container (exit to leave)"
    docker exec -it "$container" bash
}

# Lichtblick is a standalone tool overlay (its own compose file under the same
# project name), orthogonal to any topology. `up` pulls+starts just the
# lichtblick service; `down` stops only it, leaving any running topology intact.
LICHTBLICK_YML="$DOCKER_ROOT/lichtblick/lichtblick.yml"
compose_lichtblick() { docker compose -f "$LICHTBLICK_YML" --profile lichtblick "$@"; }

cmd_lichtblick() {
    local action="${1:-}"
    case "$action" in
        up)
            info "Bringing up the lichtblick container"
            compose_lichtblick up -d lichtblick
            local port="${LICHTBLICK_PORT:-8080}"
            ok "Lichtblick on http://localhost:$port/?ds=foxglove-websocket&ds.url=ws://172.30.11.20:8765"
            info "The observer's Foxglove bridge must be running for Lichtblick to connect: workshop observer bridge" ;;
        down)
            info "Bringing the lichtblick container down"
            compose_lichtblick down
            ok "lichtblick down." ;;
        *) fail "usage: workshop lichtblick <up|down>"; return 2 ;;
    esac
}

# Webshark is a standalone capture viewer (its own compose files under the same
# project name), independent of any fleet: it only serves the shared captures/
# directory, so no observer or robot container needs to be up. `up` pulls+starts
# just the webshark service; `down` stops only it, leaving any running fleet intact.
WEBSHARK_YML="$DOCKER_ROOT/webshark/webshark.yml"
WEBSHARK_LAB2_YML="$DOCKER_ROOT/webshark/webshark.lab2.yml"
# COMPOSE_IGNORE_ORPHANS: webshark shares the fleet's compose project name, so
# compose would otherwise warn that the running robots/observer are orphans of the
# webshark-only compose. Silencing that is safe - down never reaps them either.
compose_webshark() { COMPOSE_IGNORE_ORPHANS=true docker compose -f "$WEBSHARK_YML" -f "$WEBSHARK_LAB2_YML" "$@"; }

cmd_webshark() {
    local action="${1:-}"
    case "$action" in
        up)
            info "Bringing up the webshark viewer (independent of the fleet)"
            compose_webshark up -d
            ok "webshark: http://localhost:8085/webshark/"
            info "Take a capture the viewer can read with: workshop observer capture start N" ;;
        down)
            # No --remove-orphans: webshark shares the fleet's compose project name,
            # so it would reap the robots/observer as orphans.
            info "Bringing the webshark viewer down"
            compose_webshark down
            ok "webshark down (any running fleet left intact)." ;;
        *) fail "usage: workshop webshark <up|down>"; return 2 ;;
    esac
}

# Netdata is a standalone host-level observer, independent of any fleet or
# topology. `up` pulls+starts just the netdata service; `down` stops only it,
# leaving any running fleet intact.
NETDATA_YML="$DOCKER_ROOT/netdata/netdata.yml"
compose_netdata() { docker compose -f "$NETDATA_YML" --profile netdata "$@"; }

cmd_netdata() {
    local action="${1:-}"
    case "$action" in
        up)
            info "Bringing up Netdata (independent of the fleet)"
            compose_netdata up -d netdata || {
                fail "Netdata failed to start"
                return 1
            }
            if [[ "$(docker inspect -f '{{.State.Running}}' netdata 2>/dev/null)" != true ]]; then
                fail "Netdata did not reach the running state"
                return 1
            fi
            ok "netdata: http://localhost:19999" ;;
        down)
            # No --remove-orphans: netdata shares the fleet's compose project name,
            # so it would reap the robots/observer as orphans.
            info "Bringing Netdata down"
            compose_netdata down
            ok "netdata down (any running fleet left intact)." ;;
        *) fail "usage: workshop netdata <up|down>"; return 2 ;;
    esac
}

# The four published workshop images share one registry path and differ only by
# tag; these mirror the image refs in the compose files.
WORKSHOP_IMAGE_REPO="ghcr.io/clearpathrobotics/roscon2026-mastering-the-jazzy-rmw"
WORKSHOP_IMAGE_TAGS=(ubuntu-headless-latest webshark-latest netdata-latest lichtblick-latest)

cmd_pull() {
    [[ $# -eq 0 ]] || { fail "usage: workshop pull (takes no arguments)"; return 2; }
    local tag
    for tag in "${WORKSHOP_IMAGE_TAGS[@]}"; do
        info "Pulling $tag"
        docker pull "$WORKSHOP_IMAGE_REPO:$tag" || {
            fail "could not pull $tag (check your network connection and try again)"
            return 1
        }
    done
    ok "all four workshop images are up to date"
}
