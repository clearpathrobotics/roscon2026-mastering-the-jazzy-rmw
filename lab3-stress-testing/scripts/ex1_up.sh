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
