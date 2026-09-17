#!/usr/bin/env bash
# netem_profile.sh - apply a named wireless-impairment profile to one or all
# running fleet containers (per-netns qdisc: egress on eth0 + ingress via ifb0).
#
# tc/netem runs inside each replica's network namespace. Egress is shaped on
# eth0; inbound is shaped by redirecting eth0 ingress to a per-container ifb0
# device and running netem there, so the link is impaired in BOTH directions.
# Ingress is best-effort: it needs the `ifb` module on the host (`sudo modprobe
# ifb`); without it the profile still applies egress-only. To simulate a medium
# that's bad for everyone, apply the same profile to all replicas.
#
# Usage:
#   bash scripts/netem_profile.sh <profile>                # apply to all
#   bash scripts/netem_profile.sh <profile> <replica-name> # apply to one
#   bash scripts/netem_profile.sh clear [<replica-name>]   # remove qdisc
#   bash scripts/netem_profile.sh list                     # show profiles
#
# Interface: defaults to eth0 (the fleet convention). Docker may place the DDS
# subnet on a different iface per container (e.g. mock-robot-1's DDS net is eth1),
# so pass the real one as a 3rd arg or IFACE= env:
#   IFACE=eth1 bash scripts/netem_profile.sh <profile> <name>
#   bash scripts/netem_profile.sh <profile> <name> eth1
#
# Profiles (applied both directions; bursty GE loss + paretonormal jitter).
# These model INDEPENDENT per-robot links (NOT one shared medium). "clean" isn't one of
# them. A link starts with no impairment. Use `clear` (see Usage above) to remove a profile
# you've already applied.
#   healthy       5ms +/-1,   0.2% bursty loss   } the sub-1% knee, where a
#   fair          10ms +/-3,  0.4% bursty loss   } ~28-fragment camera frame
#   poor          20ms +/-6,  0.6% bursty loss   } cliffs. Monotonic.
#   bad           35ms +/-10, 0.8% bursty loss   }
#   heavy         30ms +/-10, 5% bursty loss     past the knee, for lab3
#   severe        80ms +/-30, 15% bursty loss    past the knee, for lab3
#   constrained   50ms +/-15, 1% bursty loss      milder loss than heavy/severe -
#                                                the point is a light bandwidth cap
#                                                (layer LINK_RATE=50mbit on top), not
#                                                extra loss; for lab3
#   sparse        5ms +/-1,   0.05% UNIFORM loss near-clean, and deliberately
#                                                not bursty: record-fixtures.sh
#                                                needs a steady 1-in-2000 drop
#   reorder       200ms +/-50, 3% loss + reorder
#   corrupt       100ms +/-40, 10% loss + 1% corruption
#
# Names describe severity and failure mode, not link technology. The old
# wifi_*/cellular_* names claimed to model specific radios, which was never
# measured, and wifi_good collided with the ladder's own healthy at a different
# loss rate.
#
# Optional per-link bandwidth cap (default off, so the fleet demo is unchanged):
#   LINK_RATE=20mbit ...       add a rate ceiling to each replica's own link
#   LINK_OVERHEAD=60 ...        charge that many bytes of per-frame overhead on the
#                               rate, so small chatty traffic (heartbeats, discovery)
#                               costs real airtime like it does on wifi. Needs
#                               LINK_RATE (netem charges overhead only against a rate).
#
# Wire-sized frames (default ON while a profile is applied): the segmentation and
# coalescing offloads (gso/tso/gro) are turned off on eth0 so netem shapes real
# frames instead of 64KB GSO superframes. This matters most for the TCP-based
# transport (Zenoh) and for receive-side coalescing; UDP DDS is already IP-fragmented
# in the stack. `clear` turns them back on. Checksum offload is left alone on purpose.
#   KEEP_OFFLOADS=1 ...        leave offloads untouched (e.g. to compare against).
#
# Example workshop demo:
#   scripts/workshop -t flat up 3
#   scripts/workshop webshark up
#   sleep 15  # warmup + first 5s of capture
#   bash scripts/netem_profile.sh heavy        # all 5 replicas now lossy
#   wait
#   # → timeline.png shows the shift from clean to lossy at t=15

set -euo pipefail

# Bursty loss (Gilbert-Elliott `loss gemodel`) and heavy-tailed jitter
# (`distribution paretonormal`) are closer to real wireless than IID `loss X%`
# + uniform jitter.
declare -A PROFILES=(
    [healthy]="delay 5ms 1ms distribution paretonormal loss gemodel 0.2%"
    [fair]="delay 10ms 3ms distribution paretonormal loss gemodel 0.4%"
    [poor]="delay 20ms 6ms distribution paretonormal loss gemodel 0.6%"
    [bad]="delay 35ms 10ms distribution paretonormal loss gemodel 0.8%"
    [heavy]="delay 30ms 10ms distribution paretonormal loss gemodel 5%"
    [severe]="delay 80ms 30ms distribution paretonormal loss gemodel 15%"
    [constrained]="delay 50ms 15ms distribution paretonormal loss gemodel 1%"
    [sparse]="delay 5ms 1ms distribution paretonormal loss 0.05%"
    [reorder]="delay 200ms 50ms distribution paretonormal loss gemodel 3% reorder 25% 50%"
    [corrupt]="delay 100ms 40ms distribution paretonormal loss gemodel 10% corrupt 1%"
)

action="${1:-}"
target="${2:-}"
# Interface to shape. Defaults to eth0 (the fleet convention), but Docker may put
# the DDS subnet on a different iface per container (e.g. mock-robot-1's DDS net is
# eth1), so callers resolve the real iface and pass it as $3 or IFACE=.
IFACE="${3:-${IFACE:-eth0}}"

if [[ -z "$action" || "$action" == "-h" || "$action" == "--help" ]]; then
    sed -n '2,70p' "$0"; exit 0
fi

if [[ "$action" == "list" ]]; then
    printf "%-15s %s\n" "PROFILE" "NETEM ARGS"
    for k in "${!PROFILES[@]}"; do
        printf "%-15s %s\n" "$k" "${PROFILES[$k]}"
    done | sort
    exit 0
fi

# Resolve target list: one replica, or all running fleet containers
if [[ -n "$target" ]]; then
    TARGETS=("$target")
else
    mapfile -t TARGETS < <(docker ps --format '{{.Names}}' | grep -E 'mock-robot-[0-9]+$' || true)
fi
if [[ ${#TARGETS[@]} -eq 0 ]]; then
    echo "no running fleet containers found (and no explicit target)" >&2
    exit 1
fi

if [[ "$action" == "clear" ]]; then
    for t in "${TARGETS[@]}"; do
        # Remove egress netem, the eth0 ingress qdisc, and the ifb0 device.
        # Success if either direction had something to clear.
        if docker exec -e IFACE="$IFACE" "$t" sh -c '
            e=1
            tc qdisc del dev "$IFACE" root 2>/dev/null && e=0
            tc qdisc del dev "$IFACE" ingress 2>/dev/null && e=0
            tc qdisc del dev ifb0 root 2>/dev/null || true
            ip link del ifb0 2>/dev/null || true
            ethtool -K "$IFACE" gso on tso on gro on 2>/dev/null || true
            exit $e
        ' 2>/dev/null; then
            echo "cleared netem on $t"
        else
            echo "no netem to clear on $t (or container not running)"
        fi
    done
    exit 0
fi

if [[ -z "${PROFILES[$action]+x}" ]]; then
    echo "unknown profile '$action'. Run: $0 list" >&2
    exit 2
fi
NETEM_ARGS="${PROFILES[$action]}"

# Optional per-link rate cap (+ per-frame overhead), both off by default. netem's
# `rate` takes the overhead as its trailing byte count, so small frames then cost
# more of the budget. Appended to the same NETEM_ARGS used for both directions.
LINK_RATE="${LINK_RATE:-}"
LINK_OVERHEAD="${LINK_OVERHEAD:-}"
if [[ -n "$LINK_RATE" ]]; then
    NETEM_ARGS="$NETEM_ARGS rate $LINK_RATE${LINK_OVERHEAD:+ $LINK_OVERHEAD}"
elif [[ -n "$LINK_OVERHEAD" ]]; then
    echo "note: LINK_OVERHEAD needs LINK_RATE (netem charges overhead only against a rate); ignoring it" >&2
fi

rc=0
for t in "${TARGETS[@]}"; do
    # Egress on eth0 (replace atomically). This is the hard requirement - if the
    # kernel has no usable sch_netem, fail here.
    if ! out=$(docker exec "$t" sh -c "tc qdisc del dev $IFACE root 2>/dev/null; tc qdisc add dev $IFACE root netem $NETEM_ARGS" 2>&1); then
        if [[ "$out" == *"qdisc kind is unknown"* ]]; then
            echo "FAIL $t: NOT shaping. This kernel has no usable sch_netem." >&2
            echo "         On a stock Linux host try: sudo modprobe sch_netem." >&2
            echo "         On WSL2/macOS use a stock-kernel Linux VM; on Jetson (L4T) use the recorded capture." >&2
        else
            echo "FAIL $t: $out" >&2
        fi
        rc=1
        continue
    fi
    # Wire-sized frames: drop segmentation/coalescing offloads so netem shapes real
    # frames, not GSO superframes (KEEP_OFFLOADS=1 to skip). Checksum left on. `clear`
    # restores them.
    if [[ -z "${KEEP_OFFLOADS:-}" ]]; then
        if docker exec "$t" sh -c "ethtool -K $IFACE gso off tso off gro off" >/dev/null 2>&1; then
            off=" +offloads-off"
        else
            off=" (offloads unchanged: ethtool -K failed)"
        fi
    else
        off=" (offloads kept)"
    fi
    # Ingress via a per-container ifb0 (redirect eth0 ingress -> ifb0, netem on
    # ifb0), so the link is impaired in both directions. Best-effort: needs the
    # ifb module on the host; without it, egress-only, and we say so.
    ing=$(docker exec -e IFACE="$IFACE" "$t" sh -c '
        ip link add ifb0 type ifb 2>/dev/null || true
        ip link show ifb0 >/dev/null 2>&1 || { echo NO_IFB; exit 0; }
        ip link set ifb0 up
        tc qdisc del dev "$IFACE" ingress 2>/dev/null || true
        tc qdisc add dev "$IFACE" handle ffff: ingress
        tc filter add dev "$IFACE" parent ffff: protocol all u32 match u32 0 0 \
            action mirred egress redirect dev ifb0
        tc qdisc replace dev ifb0 root netem '"$NETEM_ARGS"' && echo OK
    ' 2>&1) || true
    if [[ "$ing" == *OK* ]]; then
        echo "applied [$action] to $t: $NETEM_ARGS (both directions)${off}"
    else
        echo "applied [$action] to $t: $NETEM_ARGS (egress only - ingress unavailable, load ifb on host: sudo modprobe ifb)${off}"
    fi
done

exit "$rc"
