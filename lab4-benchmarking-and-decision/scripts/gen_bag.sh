#!/usr/bin/env bash
# gen_bag.sh - one-shot synthetic bag generator for Lab 4 (no representative MCAP
# of your own yet). Runs gen_bag.py (a live multi-class publisher: sensor/control/
# state topics matching benchmark.yaml's classes) together with `ros2 bag record`
# for a fixed window inside the always-on core container, so students get one
# command instead of three manual docker exec steps.
#
# Bags are never committed (see repo .gitignore: *.mcap/*.bag) - this always
# (re)generates a fresh local one under docker/bags/<name>/.
#
# Usage (after `scripts/workshop up`):
#   scripts/workshop gen-bag [name] [duration_seconds]
# Then replay it:
#   scripts/workshop run --template B --bag bags/<name> --rmw cyclone,fastdds,zenoh --scale 3 --duration 30
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"  # lab4/scripts
DOCKER_ROOT="$(cd "$SCRIPT_DIR/../../docker" && pwd)"       # docker/
SCRIPTS_DIR="$DOCKER_ROOT/scripts"                            # docker/scripts
# shellcheck source=../lib.sh
. "$SCRIPTS_DIR/lib.sh"

NAME="${1:-synth}"
DURATION="${2:-20}"
SVC="${GEN_BAG_SERVICE:-ubuntu-headless}"

compose() { ( cd "$DOCKER_ROOT" && docker compose "$@" ); }

# Fast DDS carries same-host data over shared memory, and a recorder cannot open segments
# that a root publisher created, so the publisher and the recorder both run as the host user.
AS_HOST_USER=(--user "$(id -u):$(id -g)" -e HOME=/tmp)

# Create the bind-mount target as the host user first, or Docker auto-creates
# it as root on first container start and the --user exec below can't write to it.
mkdir -p "$DOCKER_ROOT/bags"

info "ensuring $SVC is up"
compose up -d "$SVC" >/dev/null 2>&1 || { fail "could not start $SVC"; exit 1; }
sleep 2

info "generating synthetic bag '$NAME' (${DURATION}s): /camera/image_raw, /cmd_vel, /tf"
compose exec -d "${AS_HOST_USER[@]}" "$SVC" bash -c 'source /opt/ros/jazzy/setup.bash && exec python3 /scripts/lab4/gen_bag.py' \
    || { fail "could not start gen_bag.py publisher"; exit 1; }
sleep 2

compose exec "${AS_HOST_USER[@]}" "$SVC" bash -c "source /opt/ros/jazzy/setup.bash && cd /bags && rm -rf '$NAME' && timeout ${DURATION}s ros2 bag record -o '$NAME' /camera/image_raw /cmd_vel /tf" \
    || warn "ros2 bag record exited non-zero (timeout stopping it is expected)"

compose exec "$SVC" pkill -f gen_bag.py >/dev/null 2>&1 || true

METADATA="$DOCKER_ROOT/bags/$NAME/metadata.yaml"
if [[ ! -f "$METADATA" ]]; then
    fail "bags/$NAME/metadata.yaml not found - check the container logs (compose logs $SVC)"
    exit 1
fi

# rosbag2 writes the bag-wide total before the per-topic counts.
total_messages="$(awk '/message_count:/ { print $2; exit }' "$METADATA")"
if [[ "${total_messages:-0}" -eq 0 ]]; then
    fail "bags/$NAME recorded 0 messages, so a replay would publish nothing - check the container logs (compose logs $SVC)"
    exit 1
fi

ok "wrote docker/bags/$NAME/ ($total_messages messages)"
printf "  replay it: scripts/workshop run --template B --bag /bags/%s --rmw cyclone,fastdds,zenoh --scale 3 --duration 30\n" "$NAME"
