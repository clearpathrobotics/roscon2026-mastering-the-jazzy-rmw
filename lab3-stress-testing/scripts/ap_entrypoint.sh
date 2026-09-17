#!/usr/bin/env bash
# ap_entrypoint.sh - the wifi-ap role in the routed-peer topology: routes every
# robot/console subnet and, for Zenoh, runs the router every node connects to.
# See routed_common.sh's header for the topology diagram.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=routed_common.sh
. "$SCRIPT_DIR/routed_common.sh"

sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
bash /scripts/lab3/ap_netdata.sh &
AP_METRICS_PID=$!
trap 'kill "$AP_METRICS_PID" 2>/dev/null || true' EXIT

if [[ "$RMW" == "rmw_zenoh_cpp" ]]; then
    echo "wifi-ap: starting Zenoh router (rmw_zenohd) on tcp/:7447"
    exec ros2 run rmw_zenoh_cpp rmw_zenohd
fi
echo "wifi-ap: routing only for $RMW (unicast/static discovery); no hub daemon"
exec sleep infinity
