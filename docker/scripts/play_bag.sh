#!/usr/bin/env bash
# play_bag.sh - loop-replay a bag with per-replica topic namespacing.
#
# Used by the fleet (--profile fleet) replicas. Each replica prefixes every bag topic
# with /robot_<id>, where <id> is the last octet of its IP (unique per replica on the
# shared subnet). The bag topics are already namespaced by robot serial (e.g.
# /a300_00070/...), so a replica publishes /robot_7/a300_00070/..., identifying the
# sender to any subscriber (console, or `ubuntu-headless` on the bridge) instead of N
# replicas colliding on one name.
#
# `--loop` means bag LENGTH doesn't matter for `--duration` - a 20-30s bag (whether
# generated with `scripts/workshop gen-bag` or fetched with `scripts/workshop fetch-bag`)
# covers any sweep duration.
#
# Env:
#   BAG        bag file to play (default: first /bags/*.mcap)
#   BAG_RATE   replay rate (e.g. 0.25); unset = full speed
#   ROBOT_NS   namespace override; "none" disables namespacing (raw topics)

set -uo pipefail
set +u; source /opt/ros/jazzy/setup.bash; set -u

BAG="${BAG:-$(ls /bags/*.mcap 2>/dev/null | head -1)}"
if [[ -z "$BAG" ]]; then
    {
        echo "================================================================"
        echo "  play_bag: NO BAG FOUND. This replica has nothing to publish, so it"
        echo "  will exit now. Looked for /bags/*.mcap; /bags currently contains:"
        if [ -n "$(ls -A /bags 2>/dev/null)" ]; then ls -A /bags | sed 's/^/    /'; else echo "      (nothing)"; fi
        echo "  Get one on the host, then start the fleet again:"
        echo "      scripts/workshop fetch-bag      # pre-published benchmark bag, no wait"
        echo "      scripts/workshop gen-bag        # generate a synthetic one locally"
        echo "  or drop your own *.mcap (+ metadata.yaml) into docker/bags/."
        echo "  See docker/RUNNING.md."
        echo "================================================================"
    } >&2
    exit 1
fi

# Per-replica namespace: /robot_<last IP octet>, unique on the shared subnet.
if [[ "${ROBOT_NS:-}" == "none" ]]; then
    NS=""
else
    NS="${ROBOT_NS:-/robot_$(hostname -I 2>/dev/null | awk '{print $1}' | awk -F. '{print $NF}')}"
    [[ "$NS" == "/robot_" ]] && NS="/robot_$(hostname)"   # fallback if no IP yet
fi

RATE_ARG=(); [[ -n "${BAG_RATE:-}" ]] && RATE_ARG=(--rate "$BAG_RATE")

REMAP=()
if [[ -n "$NS" ]]; then
    while IFS= read -r t; do
        [[ -n "$t" ]] && REMAP+=("${t}:=${NS}${t}")
    done < <(ros2 bag info "$BAG" 2>/dev/null | grep -oE 'Topic: [^ ]+' | awk '{print $2}')
fi

if [[ ${#REMAP[@]} -gt 0 ]]; then
    echo "play_bag: $BAG${BAG_RATE:+ @ ${BAG_RATE}x}, namespaced under ${NS} (${#REMAP[@]} topics)"
    exec ros2 bag play "$BAG" --loop "${RATE_ARG[@]}" --remap "${REMAP[@]}"
else
    echo "play_bag: $BAG${BAG_RATE:+ @ ${BAG_RATE}x}, raw topics (no namespace)"
    exec ros2 bag play "$BAG" --loop "${RATE_ARG[@]}"
fi