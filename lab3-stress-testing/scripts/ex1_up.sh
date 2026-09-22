#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEFAULT_ROBOTS="${1:-6}"
PINNED_ROBOTS="${EX1_PINNED_ROBOTS:-3}"

# ex1 builds its fixture for one specific RMW, so pin that RMW for the whole run.
# Left unset, topo_up leaves RMW_IMPLEMENTATION to docker/.env.local, and a value
# persisted there from an earlier lab would silently override the fixture's RMW.
export WORKSHOP_RMW="${WORKSHOP_RMW:-cyclone}"

# Hold each robot's ROS startup a few seconds so the fleet collector (started at the end of
# this script) is already recording when the fleet emits its discovery burst. Overridable
# so the delay can be tuned to the host's bringup speed.
export MOCK_START_DELAY="${MOCK_START_DELAY:-12}"

[[ "$DEFAULT_ROBOTS" =~ ^[1-9][0-9]*$ ]] || {
    echo "usage: ex1_up.sh [default-robot-count]" >&2
    exit 2
}
[[ "$PINNED_ROBOTS" =~ ^[1-9][0-9]*$ ]] || {
    echo "EX1_PINNED_ROBOTS must be a positive integer" >&2
    exit 2
}

TOTAL_ROBOTS="$((DEFAULT_ROBOTS + PINNED_ROBOTS))"

if [[ "${WORKSHOP_RMW:-cyclone}" == cyclone ||
      "${WORKSHOP_RMW:-cyclone}" == cyclonedds ||
      "${WORKSHOP_RMW:-cyclone}" == rmw_cyclonedds_cpp ]]; then
    fixture_dir="$(mktemp -d)"
    cleanup() {
        rm -rf -- "$fixture_dir"
    }
    trap cleanup EXIT
    "$SCRIPT_DIR/ex1_gen_fixture.sh" "$fixture_dir" "$TOTAL_ROBOTS" "$PINNED_ROBOTS"
    "$REPO_ROOT/scripts/workshop" -t flat up "$TOTAL_ROBOTS" --rmw-directory "$fixture_dir"
else
    "$REPO_ROOT/scripts/workshop" -t flat up "$TOTAL_ROBOTS"
fi

# The fleet collector is normally its own step (`workshop -t flat collector up`). Start it
# here, right after bringup, so it attaches during the MOCK_START_DELAY window and records
# the discovery burst instead of the settled tail. Export the pinned count so the collector
# splits named vs default robots the same way the fixture did. Needs Netdata already up.
export EX1_PINNED_ROBOTS="$PINNED_ROBOTS"
"$REPO_ROOT/scripts/workshop" -t flat collector up
