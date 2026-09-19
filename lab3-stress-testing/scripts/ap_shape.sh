#!/usr/bin/env bash
# ap_shape.sh - shape ONE shared airtime budget at the `wifi-ap` router.
#
# In the routed-peer topology every robot and the console sits on its own subnet
# and the wifi-ap is the only path between them, so EVERY peer flow - robot<->robot
# as well as robot<->console - transits the AP. This script funnels all of that
# traffic through a SINGLE HTB rate + netem, so the whole topology shares one
# budget: aggregate throughput caps regardless of N, each flow's share falls ~1/N,
# and loss/queueing correlate across the fleet. That is the full shared-medium property:
# unlike shaping only a base-station uplink, here robot<->robot flows consume the budget too.
#
# Mechanism: rather than an egress qdisc on each AP interface (one budget PER
# direction/interface), here we redirect the INGRESS of
# every subnet-facing interface into one `ifb0` and shape ifb0 alone. Every packet
# entering the AP from any subnet is counted once against the single budget. A
# routed hop robot-a->robot-b enters on robot-a's interface (counted) and leaves on
# robot-b's; counting it once at ingress is the deliberate half-duplex airtime
# simplification (one transmission = one debit), not a bug.
#
# Usage (from the prototype directory):
#   bash scripts/ap_shape.sh <profile>    # apply the shared budget at the AP
#   bash scripts/ap_shape.sh clear        # remove ifb0 + all ingress redirects
#   bash scripts/ap_shape.sh status       # tc -s stats for the shared budget
#   bash scripts/ap_shape.sh sample [secs] [interval]  # CSV of the shared queue over time
#   bash scripts/ap_shape.sh rateonly <rate> [netem]  # rate-only HTB (no airtime); optional netem layered on top
#   bash scripts/ap_shape.sh list         # show profiles
#
# Profiles (rate = shared channel capacity; bursty Gilbert-Elliott loss;
# heavy-tailed paretonormal jitter - closer to real wireless than IID). Names
# match the severity ladder lab2's netem_profile.sh already uses (good/.../bad);
# no `wifi_`/`cellular_` prefix, since those claimed specific radios that were
# never measured (same reasoning as netem_profile.sh's own naming):
#   good      100mbit  5ms±1ms     0.1% ge
#   degraded  100mbit  15ms±5ms    no loss
#   lossy      50mbit  30ms±10ms   5%   ge
#   bad        20mbit  80ms±30ms   15%  ge
#   severe     10mbit  150ms±50ms  30%  ge                 - stalls a control loop routed over the AP
#   reorder    10mbit  150ms±50ms  30%  ge + 25% reorder   - severe plus packet reordering; hardest rung
#
# MTU is set at network-creation time (LINK_MTU in the compose), not here:
# shrinking a live interface's MTU blackholes established TCP. The container is
# `wifi-ap` (override AP_CONTAINER=). Interfaces are resolved by their AP address
# (172.40.*.2) since Docker doesn't guarantee ethN ordering.
#
# Two knobs raise wireless fidelity without changing the topology:
#   AIRTIME_OVERHEAD / AIRTIME_MPU  (default 60 / 128 bytes) - a size table on the
#     HTB so EVERY frame pays a fixed cost regardless of size. On real wifi a tiny
#     40-byte DDS heartbeat pays nearly as much airtime as a full data frame, so
#     chatty discovery/heartbeat traffic actually eats the medium. Set both 0 to
#     charge pure bytes (the old behaviour).
#   AP_SLOT  (default off, e.g. AP_SLOT="1ms 8ms") - netem slotted channel access:
#     packets leave in transmit slots instead of a smooth stream, adding the bursty
#     access delay of "wait your turn on the channel" that plain jitter can't.

set -euo pipefail

AP_CONTAINER="${AP_CONTAINER:-wifi-ap}"
AP_PREFIX="${AP_PREFIX:-172.40.}"   # every AP interface is 172.40.<subnet>.2
IFB="ifb0"
AIRTIME_OVERHEAD="${AIRTIME_OVERHEAD:-60}"   # per-frame MAC overhead charged to every packet (bytes)
AIRTIME_MPU="${AIRTIME_MPU:-128}"            # minimum airtime cost per packet (bytes); models fixed framing
AP_SLOT="${AP_SLOT:-}"                        # optional slotted channel access, e.g. "1ms 8ms"
AP_EXEC_TIMEOUT="${AP_EXEC_TIMEOUT:-5}"

# profile -> "rate | netem-args"
declare -A PROFILES=(
    [good]="100mbit|delay 5ms 1ms distribution paretonormal loss gemodel 0.1%"
    [degraded]="100mbit|delay 15ms 5ms distribution paretonormal"
    [lossy]="50mbit|delay 30ms 10ms distribution paretonormal loss gemodel 5%"
    [bad]="20mbit|delay 80ms 30ms distribution paretonormal loss gemodel 15%"
    [severe]="10mbit|delay 150ms 50ms distribution paretonormal loss gemodel 30%"
    [reorder]="10mbit|delay 150ms 50ms distribution paretonormal loss gemodel 30% reorder 25% 50%"
)

in_ap() {
    local status=0
    timeout --foreground "$AP_EXEC_TIMEOUT" docker exec "$AP_CONTAINER" "$@" || status=$?
    if [[ "$status" -eq 124 ]]; then
        echo "timed out after ${AP_EXEC_TIMEOUT}s running a command in AP container '$AP_CONTAINER'" >&2
    fi
    return "$status"
}

# All subnet-facing interfaces on the AP (those holding a 172.40.*.2 address).
ap_ifaces() {
    in_ap ip -o -4 addr show 2>/dev/null \
        | awk -v p="$AP_PREFIX" 'index($4, p) == 1 { print $2 }' | sort -u
}

usage() { sed -n '2,33p' "$0"; }

action="${1:-}"
[[ -z "$action" || "$action" == "-h" || "$action" == "--help" ]] && { usage; exit 0; }

if [[ "$action" == "list" ]]; then
    printf "%-13s %-9s %s\n" "PROFILE" "RATE" "NETEM"
    for k in "${!PROFILES[@]}"; do
        IFS='|' read -r rate netem <<<"${PROFILES[$k]}"
        printf "%-13s %-9s %s\n" "$k" "$rate" "$netem"
    done | sort
    exit 0
fi

case "$action" in
    clear|status|sample|rateonly|good|degraded|lossy|bad|severe|reorder) ;;
    *) echo "unknown profile '$action'. Run: $0 list" >&2; exit 2 ;;
esac

ap_status=0
in_ap true >/dev/null 2>&1 || ap_status=$?
if [[ "$ap_status" -ne 0 ]]; then
    if [[ "$ap_status" -eq 124 ]]; then
        echo "timed out waiting for AP container '$AP_CONTAINER'" >&2
        exit 124
    fi
    echo "AP container '$AP_CONTAINER' not running - 'docker compose up -d' first" >&2
    exit "$ap_status"
fi

iface_output=""
iface_status=0
iface_output="$(ap_ifaces)" || iface_status=$?
if [[ "$iface_status" -ne 0 ]]; then
    exit "$iface_status"
fi
IFACES=()
if [[ -n "$iface_output" ]]; then
    mapfile -t IFACES <<<"$iface_output"
fi
if [[ ${#IFACES[@]} -eq 0 ]]; then
    echo "could not resolve any AP interface with a ${AP_PREFIX}*.2 address" >&2
    echo "is '$AP_CONTAINER' the router multi-homed onto the robot/console subnets?" >&2
    exit 1
fi

clear_all() {
    # shellcheck disable=SC2016
    in_ap sh -c '
        ifb="$1"
        shift
        for ifc in "$@"; do
            tc qdisc del dev "$ifc" ingress 2>/dev/null || true
        done
        tc qdisc del dev "$ifb" root 2>/dev/null || true
        ip link del "$ifb" 2>/dev/null || true
        rm -f /run/ap_shape.env
    ' sh "$IFB" "${IFACES[@]}"
}

if [[ "$action" == "status" ]]; then
    echo "=== shared AP budget ($IFB) ==="
    netem_line="$(in_ap tc qdisc show dev "$IFB" 2>/dev/null | grep -m1 netem || true)"
    if [[ -n "$netem_line" ]]; then
        rate="$(in_ap tc class show dev "$IFB" 2>/dev/null | grep -m1 'class htb' | grep -oE 'rate [0-9A-Za-z]+' || true)"
        # drop tc's 'qdisc netem NN: parent N:N limit NNNN' prefix; keep the shaping spec
        printf "  %s | %s\n" "${rate:-rate ?}" "$(sed -E 's/^.*limit [0-9]+ //' <<<"$netem_line")"
        # cumulative counters (first Sent/backlog = the shared htb budget), so "is it
        # dropping?" is answered here instead of needing `netem sample` or Netdata.
        counters="$(in_ap tc -s qdisc show dev "$IFB" 2>/dev/null | awk '
            /^ Sent/    && !seen_sent    { pkts=$4; dropped=$7; gsub(/,/,"",dropped); seen_sent=1 }
            /^ backlog/ && !seen_backlog { backlog=$3; sub(/p$/,"",backlog); seen_backlog=1 }
            END { printf "sent %d pkts, dropped %d, backlog %d pkts", pkts, dropped, backlog }')"
        printf "  %s\n" "$counters"
    else
        echo "  (no shaping applied)"
    fi
    echo "=== ingress redirects ==="
    for ifc in "${IFACES[@]}"; do
        printf "  %-8s " "$ifc"
        in_ap tc qdisc show dev "$ifc" ingress 2>/dev/null | grep -q ingress \
            && echo "-> $IFB" || echo "(none)"
    done
    exit 0
fi

if [[ "$action" == "clear" ]]; then
    clear_status=0
    clear_all || clear_status=$?
    [[ "$clear_status" -eq 0 ]] || exit "$clear_status"
    echo "cleared shared budget on $AP_CONTAINER (${IFACES[*]} ingress + $IFB)"
    exit 0
fi

# Emit the shared budget's cumulative counters as CSV over a window; pipe it to
# scripts/plot_contention.py to chart throughput / drops / backlog.
if [[ "$action" == "sample" ]]; then
    dur="${2:-30}"; interval="${3:-1}"
    parse_ifb() {
        in_ap tc -s qdisc show dev "$IFB" 2>/dev/null | awk '
            /^ Sent/ && !hs { sb=$2; sp=$4; d=$7; gsub(/,/,"",d); hs=1 }
            /^ backlog/ && !hb { bb=$2; bp=$3; sub(/b$/,"",bb); sub(/p$/,"",bp); hb=1 }
            END { printf "%s,%s,%s,%s,%s\n", sb+0, sp+0, d+0, bb+0, bp+0 }'
    }
    echo "elapsed,sent_bytes,sent_pkts,dropped_pkts,backlog_bytes,backlog_pkts"
    start=$(date +%s.%N)
    while :; do
        now=$(date +%s.%N)
        el=$(awk "BEGIN{printf \"%.1f\", $now-$start}")
        echo "$el,$(parse_ifb)"
        awk "BEGIN{exit !($now-$start >= $dur)}" && break
        sleep "$interval"
    done
    exit 0
fi

RATEONLY=0
if [[ "$action" == "rateonly" ]]; then
    RATEONLY=1
fi

# Preflight: usable sch_netem/sch_htb/ifb in this kernel? (absent on Jetson L4T)
if ! in_ap sh -c 'cleanup() { tc qdisc del dev lo root 2>/dev/null || true; ip link del shapechk 2>/dev/null || true; }; trap cleanup EXIT; ip link add shapechk type ifb 2>/dev/null && tc qdisc add dev lo root netem delay 1ms 2>/dev/null'; then
    in_ap rm -f /run/ap_shape.env 2>/dev/null || true
    echo "SKIP: running WITHOUT shaping. The AP kernel has no usable sch_netem/sch_htb/ifb," >&2
    echo "      so the shared medium is NOT rate-limited. Topology and discovery still run." >&2
    echo "      On a stock Linux host: sudo modprobe ifb sch_netem sch_htb. On WSL2/macOS run" >&2
    echo "      Docker in a stock-kernel Linux VM; on Jetson (L4T) use the recorded capture." >&2
    exit 0
fi

if [[ "$RATEONLY" == 1 ]]; then
    # rate-only: an explicit HTB rate at the shared budget, no airtime table. With no
    # 3rd arg, netem is empty and loss EMERGES purely from queue overflow (contention).
    # An optional netem spec layers a fixed medium impairment (loss/delay/jitter) ON TOP
    # of the same rate, so the fair comparison can hold capacity equal while varying the
    # medium - e.g. rateonly 94mbit "delay 30ms 10ms loss gemodel 5%".
    RATE="${2:?usage: ap_shape.sh rateonly <rate e.g. 94mbit> [netem-spec]}"
    NETEM="${3:-}"
    AIRTIME_OVERHEAD=0; AIRTIME_MPU=0
else
    IFS='|' read -r RATE NETEM <<<"${PROFILES[$action]}"
fi

capacity_mbps="$(awk -v rate="$RATE" 'BEGIN {
    value=rate+0
    if (rate ~ /gbit$/) value*=1000
    else if (rate ~ /kbit$/) value/=1000
    printf "%.3f", value
}')"
delay_ms="$(awk -v spec="$NETEM" 'BEGIN {
    if (match(spec, /delay [0-9.]+ms/)) {
        value=substr(spec, RSTART+6, RLENGTH-8)
    } else value=0
    printf "%.3f", value
}')"
loss_pct="$(awk -v spec="$NETEM" 'BEGIN {
    if (match(spec, /loss (gemodel )?[0-9.]+%/)) {
        value=substr(spec, RSTART, RLENGTH)
        sub(/^loss (gemodel )?/, "", value); sub(/%$/, "", value)
    } else value=0
    printf "%.3f", value
}')"

# A size table (stab) makes the HTB charge every frame a fixed overhead + minimum,
# so small chatty traffic costs real airtime instead of ~nothing. Slotted access
# (AP_SLOT) releases packets in transmit slots for bursty channel-access delay.
STAB=""
if [[ "$AIRTIME_OVERHEAD" != "0" || "$AIRTIME_MPU" != "0" ]]; then
    STAB="stab overhead $AIRTIME_OVERHEAD mpu $AIRTIME_MPU"
fi
NETEM_ARGS="$NETEM"
[[ -n "$AP_SLOT" ]] && NETEM_ARGS="$NETEM_ARGS slot $AP_SLOT"

clear_status=0
clear_all || clear_status=$?
if [[ "$clear_status" -ne 0 ]]; then
    echo "failed to clear existing shaping state" >&2
    exit "$clear_status"
fi

# One shared HTB class (rate=ceil=channel capacity) with a netem child, on a
# single ifb0. Every AP interface's ingress is redirected into it, so all peer
# traffic contends for the one budget. `default 10` routes everything to the class.
# An sfq leaf under the netem shares that budget fairly across contending flows,
# so each robot's throughput falls to ~1/N of the medium (as CSMA airtime would)
# instead of one blaster starving the rest.
apply_profile() {
    in_ap sh -c "
        set -e
        ip link add $IFB type ifb 2>/dev/null || true
        ip link set $IFB up
        tc qdisc add dev $IFB root handle 1: $STAB htb default 10
        tc class add dev $IFB parent 1: classid 1:10 htb rate $RATE ceil $RATE quantum 1514
        tc qdisc add dev $IFB parent 1:10 handle 10: netem $NETEM_ARGS
        tc qdisc add dev $IFB parent 10: handle 110: sfq perturb 10
    " || return $?
    for ifc in "${IFACES[@]}"; do
        in_ap sh -c "
            set -e
            tc qdisc add dev $ifc handle ffff: ingress
            tc filter add dev $ifc parent ffff: protocol all u32 match u32 0 0 \
                action mirred egress redirect dev $IFB
        " || return $?
    done
    in_ap sh -c "printf 'capacity_mbps=%s\ndelay_ms=%s\nloss_pct=%s\n' \
        '$capacity_mbps' '$delay_ms' '$loss_pct' >/run/ap_shape.env"
}

apply_status=0
apply_profile || apply_status=$?
if [[ "$apply_status" -ne 0 ]]; then
    clear_all || true
    echo "failed to apply [$action]; cleaned partial shaping state" >&2
    exit "$apply_status"
fi

echo "applied [$action] shared budget at $AP_CONTAINER: rate $RATE, netem '$NETEM_ARGS'"
echo "  interfaces funnelled into $IFB: ${IFACES[*]}"
[[ -n "$STAB" ]] && echo "  per-frame airtime: $STAB (small frames pay real airtime)"
[[ -n "$AP_SLOT" ]] && echo "  slotted channel access: slot $AP_SLOT"
echo "  shared medium: robot<->robot AND robot<->console contend for one $RATE budget"
