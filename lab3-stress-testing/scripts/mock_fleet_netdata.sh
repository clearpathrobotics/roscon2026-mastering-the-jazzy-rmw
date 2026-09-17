#!/usr/bin/env bash
# mock_fleet_netdata.sh - export healthy-fleet discovery metrics to Netdata
# StatsD for Lab 3's fleet deployment.
#
# The generator names the routed operator container `observer` and the fleet
# `mock-robot-N`. The list is discovered from running containers so it follows
# the generated fleet size.
#
# Runs on the HOST (not inside a container) - it shells out to `docker exec` for
# each container's interface counters, so it works for any container regardless
# of which network it is on. Netdata publishes its StatsD UDP port to the host,
# allowing the collector to send directly without an additional `docker exec`.
#
# Metrics (see docker/netdata/statsd.d/lab3_fleet.conf):
#   multicast_tx   RTPS SPDP multicast packets/s transmitted from eth0. This
#                  distinguishes the default multicast configuration from the
#                  pinned peer-list configuration. Measured with a short
#                  outbound tcpdump capture, NOT
#                  /sys/class/net/eth0/statistics/multicast: that counter never
#                  increments on Docker's veth interfaces even when real RTPS
#                  multicast is transmitted. The capture also restricts packets to
#                  the RTPS SPDP multicast port, so user data sent to the same
#                  multicast group is not counted.
# The default-config group uses an explicit container list when set, otherwise
# the optional scaled-container name pattern. It is captured in parallel.
# The dashboard shows the actual group
# total, rather than extrapolating a small sample or hiding scale behind an average.
#
# Usage: bash mock_fleet_netdata.sh [interval_seconds]
# Env:
#   FLEET_NAMED_CONTAINERS   optional space-separated containers to collect
#   FLEET_DEFAULT_CONTAINERS optional space-separated default group; overrides pattern
#   FLEET_DEFAULT_PATTERN    optional docker name prefix for an extra group
#   MCAST_CAPTURE_SECS       tcpdump capture window per container (default 1)
#   DISCOVERY_MCAST_PORT     RTPS SPDP multicast port (default follows ROS_DOMAIN_ID)
set -uo pipefail

INTERVAL="${1:-2}"
STATSD_PORT="${NETDATA_STATSD_PORT:-8125}"
STATSD_HOST="${NETDATA_STATSD_HOST:-127.0.0.1}"
MCAST_CAPTURE_SECS="${MCAST_CAPTURE_SECS:-1}"
PUBLISH_INTERVAL="${NETDATA_PUBLISH_INTERVAL:-1}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-25}"
DISCOVERY_MCAST_PORT="${DISCOVERY_MCAST_PORT:-$((7400 + 250 * ROS_DOMAIN_ID))}"

# Discover the observer and individually numbered robots in the running fleet.
discover_named_containers() {
    docker ps --format '{{.Names}}' \
        | grep -E '^(observer|mock-robot-[0-9]+)$' \
        | sort -V \
        || true
}

if [[ -n "${FLEET_NAMED_CONTAINERS:-}" ]]; then
    read -ra NAMED_CONTAINERS <<< "$FLEET_NAMED_CONTAINERS"
else
    mapfile -t NAMED_CONTAINERS < <(discover_named_containers)
fi
DEFAULT_PATTERN="${FLEET_DEFAULT_PATTERN:-}"

# Real outbound RTPS SPDP multicast packets/s, counted directly (see header comment for
# why the sysfs `multicast` stat can't be trusted here). A fixed-length capture
# window IS already a rate - do not run this through delta_rate().
read_mcast_rate() {
    local c="$1" n=""
    # grep -c, not wc -l: tcpdump emits a trailing blank line when the capture window
    # ends, so wc -l reports 1 packet/s on a silent interface. The trailing `|| true`
    # matters: grep -c exits 1 on a zero count, which is the normal case for a pinned
    # robot, and a non-zero exit here would otherwise propagate out of docker exec.
    n="$(docker exec "$c" sh -c "timeout $MCAST_CAPTURE_SECS tcpdump -Q out -i eth0 -n 'dst host 239.255.0.1 and udp dst port $DISCOVERY_MCAST_PORT' 2>/dev/null | grep -c . || true" 2>/dev/null)" || true
    # Trailing newline matters: the reader uses `read`, which reports failure on a final
    # line without one even though it assigned the value.
    awk -v n="${n:-0}" -v s="$MCAST_CAPTURE_SECS" 'BEGIN{printf "%.3f\n", n/s}'
}

# One metric per UDP datagram: Netdata's StatsD listener only reads the first
# line of each packet. A new UDP write is one datagram, so publish every line
# separately from the host through Netdata's published StatsD port.
push() { printf '%s\n' "$2" >> "$1"; }
flush_metrics() {
    local metric
    while IFS= read -r metric; do
        [[ -n "$metric" ]] || continue
        printf '%s\n' "$metric" >"/dev/udp/$STATSD_HOST/$STATSD_PORT" || {
            echo "mock_fleet_netdata: failed to send metrics to Netdata StatsD" >&2
            return 1
        }
    done < "$1"
}

# printf, not a here-string: <<< appends a trailing newline that tr -c would
# otherwise turn into a spurious trailing underscore on every tag.
sanitize() { printf '%s' "$1" | tr -c 'a-zA-Z0-9_' '_'; }

info_once() {
    local group=""
    if [[ ${FLEET_DEFAULT_CONTAINERS+x} ]]; then
        group=" + default group [${FLEET_DEFAULT_CONTAINERS}]"
    elif [[ -n "$DEFAULT_PATTERN" ]]; then
        group=" + '${DEFAULT_PATTERN}-*' group"
    fi
    echo "mock_fleet_netdata: watching [${NAMED_CONTAINERS[*]}]$group, every ${INTERVAL}s -> Netdata StatsD ${STATSD_HOST}:${STATSD_PORT}" >&2
}
info_once

# Netdata samples statsd charts once per second and draws a gap for any second that
# received no value; "gaps when not collected" is not honoured for these synthetic
# charts. One measurement cycle takes several seconds (a tcpdump window per container,
# plus docker exec overhead), so measuring and publishing run at different rates:
# collect_once refreshes a cache in the background, and the foreground loop republishes
# that cache every second. The values are real captures, resampled to the chart's rate.
CACHE_FILE="$(mktemp)"

collect_once() {
    declare -A JOB_FILES=()
    local metrics_file

    for c in "${NAMED_CONTAINERS[@]}"; do
        docker inspect -f '{{.State.Running}}' "$c" >/dev/null 2>&1 || continue
        f="$(mktemp)"; JOB_FILES["named:$c"]="$f"
        read_mcast_rate "$c" > "$f" &
    done

    # Explicit membership takes precedence, including an explicitly empty list.
    # Otherwise match Compose replicas <project>-<service>-<n> by suffix.
    DEFAULT_C=()
    if [[ ${FLEET_DEFAULT_CONTAINERS+x} ]]; then
        read -ra DEFAULT_C <<< "$FLEET_DEFAULT_CONTAINERS"
    elif [[ -n "$DEFAULT_PATTERN" ]]; then
        # Re-scanned each cycle so a scaled fleet is reflected without a collector restart;
        # exclude the pinned/named robots, which are collected as their own group.
        local dc n
        while IFS= read -r dc; do
            for n in "${NAMED_CONTAINERS[@]}"; do
                [[ "$dc" == "$n" ]] && continue 2
            done
            DEFAULT_C+=("$dc")
        done < <(docker ps --format '{{.Names}}' | grep -E "${DEFAULT_PATTERN}-[0-9]+\$" || true)
    fi
    # Parallel captures keep collection time independent of the group size.
    for c in "${DEFAULT_C[@]}"; do
        f="$(mktemp)"; JOB_FILES["default:$c"]="$f"
        read_mcast_rate "$c" > "$f" &
    done

    wait
    metrics_file="$(mktemp)"

    for c in "${NAMED_CONTAINERS[@]}"; do
        f="${JOB_FILES["named:$c"]:-}"
        [[ -n "$f" && -f "$f" ]] || continue
        # `read` returns non-zero at EOF even when it assigned the value, so never
        # overwrite mcast on failure - only default it when nothing was read at all.
        mcast=""
        read -r mcast < "$f" || true
        rm -f "$f"
        tag="$(sanitize "$c")"
        push "$metrics_file" "lab3_fleet.multicast_tx.${tag}:${mcast:-0}|g"
    done

    if [[ ${#DEFAULT_C[@]} -gt 0 ]]; then
        sum_m=0
        for c in "${DEFAULT_C[@]}"; do
            f="${JOB_FILES["default:$c"]:-}"
            [[ -n "$f" && -f "$f" ]] || continue
            mcast=""
            read -r mcast < "$f" || true
            rm -f "$f"
            sum_m=$(awk -v a="$sum_m" -v b="${mcast:-0}" 'BEGIN{printf "%.3f", a+b}')
        done
        n=${#DEFAULT_C[@]}
        push "$metrics_file" "lab3_fleet.multicast_tx.default_group_total:${sum_m}|g"
        push "$metrics_file" "lab3_fleet.default_group_size:${n}|g"
    fi
    # Swap in one step so the publisher never reads a half-written cache.
    mv -f "$metrics_file" "$CACHE_FILE"
}

publish_cache() {
    local metrics_file
    metrics_file="$(mktemp)"
    cp "$CACHE_FILE" "$metrics_file"
    flush_metrics "$metrics_file"
    rm -f "$metrics_file"
}

while true; do collect_once; sleep "$INTERVAL"; done &
COLLECT_PID=$!

cleanup() {
    local status=$?
    echo "mock_fleet_netdata: exiting with status $status" >&2
    kill "$COLLECT_PID" 2>/dev/null || true
    rm -f "$CACHE_FILE"
}
trap cleanup EXIT
trap 'exit 143' HUP INT TERM

while sleep "$PUBLISH_INTERVAL"; do
    [[ -s "$CACHE_FILE" ]] || continue
    publish_cache
done
