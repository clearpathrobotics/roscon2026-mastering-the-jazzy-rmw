#!/usr/bin/env bash
# pubsub.sh - cross-container pub/sub perf_test.
#
# Publisher runs in $A, subscriber in $B. Both use whatever RMW is set in
# their container env, so one script covers all three RMWs. Reliability is
# per-invocation so the caller can run reliable and best-effort back-to-back.
#
# Usage:
#   pubsub.sh <container-a> <container-b> <reliability: reliable|best_effort> \
#             [duration_sec] [msg_type] [rate_hz]
#
# Emits a single line to stdout:
#   mean_ms max_ms recv_hz
# - or "n/a n/a n/a" if perf_test's CSV couldn't be parsed. Per-run logs
# land at /tmp/rmw_bench_pubsub_<A>_<B>_<reliability>.log for inspection.

set -uo pipefail

A="${1:?container-a required}"
B="${2:?container-b required}"
RELIABILITY="${3:?reliability required (reliable|best_effort)}"
DURATION="${4:-10}"
MSG_TYPE="${5:-Array1k}"
RATE="${6:-1000}"

case "$RELIABILITY" in
    reliable)     REL_FLAG="RELIABLE" ;;
    best_effort)  REL_FLAG="BEST_EFFORT" ;;
    *) echo "reliability must be reliable|best_effort" >&2; exit 2 ;;
esac

DOCKER_BIN="${LAB4_DOCKER_BIN:-docker}"
# `command` is required when DOCKER_BIN is the default name `docker`; otherwise
# this function resolves itself recursively until Bash crashes.
docker() { command "$DOCKER_BIN" "$@"; }
LOG="${LAB4_BENCH_LOG:-/tmp/rmw_bench_pubsub_${A}_${B}_${RELIABILITY}.log}"
: > "$LOG"

# Publisher: -p 1 -s 0. Backgrounded via -d so we can start the sub.
# Redirect output - with -d there's no consumer for stdout/stderr and
# perf_test's periodic writes can wedge on a closed pipe.
docker exec -d "$A" bash -c "
    source /opt/ros/jazzy/setup.bash
    ros2 run performance_test perf_test \
        -c rclcpp-single-threaded-executor \
        -m ${MSG_TYPE} \
        -r ${RATE} \
        --reliability ${REL_FLAG} \
        --max-runtime $((DURATION + 4)) \
        --wait-for-matched-timeout 10 \
        -p 1 -s 0 > /tmp/perf_pub.log 2>&1
" || exit $?

# Give the pub a moment so discovery lands before the sub starts sampling.
sleep 2

# Subscriber: -p 0 -s 1. --print-to-console emits the summary table.
docker exec "$B" bash -c "
    source /opt/ros/jazzy/setup.bash
    ros2 run performance_test perf_test \
        -c rclcpp-single-threaded-executor \
        -m ${MSG_TYPE} \
        -r ${RATE} \
        --reliability ${REL_FLAG} \
        --max-runtime ${DURATION} \
        --wait-for-matched-timeout 10 \
        --print-to-console \
        -p 0 -s 1
" 2>&1 | tee "$LOG" > /dev/null
subscriber_status=$?
[[ "$subscriber_status" -eq 0 ]] || exit "$subscriber_status"

# Wait for the backgrounded publisher to exit on its own max-runtime.
sleep 4

# perf_test emits two side-by-side tables per frame (recv+latency, then
# a system-usage table). Frames are printed once per second, over-written
# via terminal escape codes - the log accumulates all of them.
#
# The samples/latency row has an empty "seam" cell between the two
# sub-tables, so under `-F|` it splits into 12 fields - that's the
# discriminator that separates it from the 10-field system-usage rows.
# All time values are in SECONDS. Take the last matching frame (max recv).
read -r TOTAL_RECV MEAN_S _STD_S MAX_S < <(awk -F'|' '
    NF == 12 && $2 ~ /^ *[0-9]+ *$/ {
        gsub(/^[ \t]+|[ \t]+$/,"",$2)   # recv (per-frame count)
        gsub(/^[ \t]+|[ \t]+$/,"",$9)   # max latency (s)
        gsub(/^[ \t]+|[ \t]+$/,"",$10)  # mean latency (s)
        total_recv += $2
        if ($10 + 0 > 0) { latency_sum += $10 * $2; latency_sq_sum += $10 * $10 * $2; latency_n += $2 }
        if ($9 + 0 > max_s) max_s = $9 + 0
    }
    END {
        if (latency_n > 0) {
            mean_s = latency_sum / latency_n
            var_s = latency_sq_sum / latency_n - mean_s * mean_s
            std_s = (var_s > 0) ? sqrt(var_s) : 0
            printf "%d %.9f %.9f %.9f\n", total_recv, mean_s, std_s, max_s
        }
    }
' "$LOG")

if [[ -z "${TOTAL_RECV:-}" ]]; then
    echo "n/a n/a n/a"
    exit 0
fi

MEAN_MS=$(awk -v v="$MEAN_S" 'BEGIN{ printf "%.3f", v*1000 }')
MAX_MS=$(awk  -v v="$MAX_S"  'BEGIN{ printf "%.3f", v*1000 }')
# Derive rate from complete one-second report frames. Dividing by DURATION
# instead counts performance_test's startup/reporting gap as dropped messages.
FRAME_COUNT=$(awk -F'|' '
    NF == 12 && $2 ~ /^ *[0-9]+ *$/ { frames += 1 }
    END { print frames + 0 }
' "$LOG")
RECV_HZ=$(awk -v r="$TOTAL_RECV" -v f="$FRAME_COUNT" 'BEGIN{ if(f>0) printf "%.0f", r/f; else print "n/a" }')

# 3 fields only (mean_ms max_ms recv_hz) - matches run_sweep.sh's `read -r m mx hz`.
# STD_S is computed above for anyone reading $LOG by hand, but isn't part of the contract.
echo "$MEAN_MS $MAX_MS $RECV_HZ"
