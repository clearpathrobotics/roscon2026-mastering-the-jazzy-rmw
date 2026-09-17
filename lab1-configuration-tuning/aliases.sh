#!/bin/bash

# Lab 1 — Mock robot aliases
# Source this file: source aliases.sh

_LAB1_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOCK_COMPOSE="${_LAB1_DIR}/../docker/mock_robots/mock.yml"
_MC="docker compose -f ${MOCK_COMPOSE} --profile mock"

LICHTBLICK_COMPOSE="${_LAB1_DIR}/../docker/lichtblick/lichtblick.yml"
_LB="docker compose -f ${LICHTBLICK_COMPOSE} --profile lichtblick"

# ---------------------------------------------------------------------------
# Robot-count helpers
# ---------------------------------------------------------------------------

# Echo the service names for mock robots 1..N (default N=1).
# Usage: _mock_robot_list [N]
_mock_robot_list() {
    local n="${1:-1}"
    if ! [[ "$n" =~ ^[1-9][0-9]*$ ]]; then
        echo "Invalid robot count: '$n' (expected a positive integer)" >&2
        return 1
    fi
    local i
    for ((i = 1; i <= n; i++)); do
        printf 'mock-robot-%d ' "$i"
    done
}

# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

# Bring up the observer plus mock robots 1..N (default N=1).
# Usage: mock-up [N]
mock_up() {
    local robots
    robots="$(_mock_robot_list "${1:-1}")" || return 1
    ${_MC} up -d --no-build --remove-orphans observer ${robots}
}
alias mock-up="mock_up"

# Rebuild images and bring up the observer plus mock robots 1..N (default N=1).
# Usage: mock-up-rebuild [N]
mock_up_rebuild() {
    local robots
    robots="$(_mock_robot_list "${1:-1}")" || return 1
    ${_MC} up -d --build --force-recreate --remove-orphans observer ${robots}
}
alias mock-up-rebuild="mock_up_rebuild"

# Recreate the observer plus mock robots 1..N without rebuilding (default N=1).
# Usage: mock-restart [N]
mock_restart() {
    local robots
    robots="$(_mock_robot_list "${1:-1}")" || return 1
    ${_MC} up -d --no-build --force-recreate --remove-orphans observer ${robots}
}
alias mock-restart="mock_restart"

alias mock-down="${_MC} down"
alias mock-ps="${_MC} ps"
alias mock-logs="${_MC} logs --tail=100 --follow"

# Follow logs for a single mock robot (default robot 1).
# Usage: logs-robot [N]
logs_robot() {
    ${_MC} logs --tail=100 --follow "mock-robot-${1:-1}"
}
alias logs-robot="logs_robot"

alias logs-observer="${_MC} logs --tail=100 --follow observer"

# ---------------------------------------------------------------------------
# Shell access
# ---------------------------------------------------------------------------

# Open a bash shell in a single mock robot (default robot 1).
# Usage: shell-robot [N]
shell_robot() {
    ${_MC} exec "mock-robot-${1:-1}" bash
}
alias shell-robot="shell_robot"

alias shell-observer="${_MC} exec observer bash"

# ---------------------------------------------------------------------------
# RViz2
# ---------------------------------------------------------------------------

alias rviz-observer="${_MC} exec observer bash -lc 'source /opt/ros/jazzy/setup.bash && source /mock_robot_ws/install/setup.bash && rviz2'"

# Launch mock_robot_viz for a single robot namespace (default robot 1).
# Usage: rviz-robot [N]
rviz_robot() {
    local n="${1:-1}"
    ${_MC} exec observer bash -lc \
        "source /opt/ros/jazzy/setup.bash && source /mock_robot_ws/install/setup.bash && \
         ros2 launch mock_robot_viz mock_robot_viz.launch.py robot_namespace:=mock_robot_${n} frame_id:=robot${n}"
}
alias rviz-robot="rviz_robot"

rviz_robots() {
    ${_MC} exec observer bash -lc \
        'source /opt/ros/jazzy/setup.bash && source /mock_robot_ws/install/setup.bash && \
         ros2 launch mock_robot_viz mock_robot_viz_dual.launch.py'
}

alias rviz-robots="rviz_robots"

# ---------------------------------------------------------------------------
# Foxglove Bridge
# ---------------------------------------------------------------------------

foxglove_robots() {
    ${_MC} exec observer bash -lc \
        'source /opt/ros/jazzy/setup.bash && source /mock_robot_ws/install/setup.bash && \
         ros2 launch mock_robot_viz foxglove_bridge.launch.py'
}

alias foxglove-robots="foxglove_robots"

# ---------------------------------------------------------------------------
# Lichtblick (web UI with pre-installed joystick extensions)
# ---------------------------------------------------------------------------

alias lichtblick-up="${_LB} up -d --build lichtblick"
alias lichtblick-down="${_LB} down"
alias lichtblick-restart="${_LB} up -d --build --force-recreate lichtblick"
alias lichtblick-rebuild="${_LB} build --no-cache lichtblick && ${_LB} up -d --force-recreate lichtblick"
alias lichtblick-ps="${_LB} ps"
alias lichtblick-logs="${_LB} logs --tail=100 --follow lichtblick"
alias lichtblick-shell="${_LB} exec lichtblick sh"

# Open the Lichtblick web UI in the default browser.
alias lichtblick-open="xdg-open http://localhost:\${LICHTBLICK_PORT:-8080}"

# ---------------------------------------------------------------------------
# X11 / host display helpers
# ---------------------------------------------------------------------------

# Allow root in local containers to connect to the host X server.
alias x11-allow="xhost +SI:localuser:root"

# Revoke the X server permission granted by x11-allow.
alias x11-deny="xhost -SI:localuser:root"

# Start the mock stack targeting display :1 on hosts using that display.
# Usage: mock-up-d1 [N]
mock_up_d1() {
    DISPLAY=:1 mock_up "$@"
}
alias mock-up-d1="mock_up_d1"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Show all running containers for this compose project
alias compose-ps="docker ps --filter label=com.docker.compose.project=roscon2026-jazzy-rmw --format 'table {{.Names}}\t{{.Status}}\t{{.Networks}}'"

# Print each mock robot's assigned IP for robots 1..N (default N=1).
# Usage: mock-ips [N]
mock_ips() {
    local robots
    robots="$(_mock_robot_list "${1:-1}")" || return 1
    local svc
    for svc in ${robots} observer; do
        printf "%-20s " "$svc"
        ${_MC} exec -T "$svc" ip -4 addr show eth0 2>/dev/null \
            | awk '/inet /{print $2}' \
            || echo "(not running)"
    done
}
alias mock-ips="mock_ips"

echo "Lab 1 aliases loaded. Available commands (N = number of robots, default 1):"
echo "  mock-up [N] / mock-down / mock-restart [N] / mock-ps"
echo "  mock-up-rebuild [N]      — rebuild images and (re)start observer + robots 1..N"
echo "  mock-logs               — follow logs from all mock services"
echo "  logs-robot [N] / logs-observer  — follow logs for one container"
echo "  shell-robot [N] / shell-observer"
echo "  rviz-observer       — launch RViz2 on the observer"
echo "  rviz-robot [N]          — launch mock_robot_viz for robot N's namespace"
echo "  rviz-robots             — launch dual-robot RViz with both RobotModel displays"
echo "  foxglove-robots         — launch Foxglove Bridge for the mock robot graph"
echo "  lichtblick-up / lichtblick-down / lichtblick-restart / lichtblick-ps"
echo "  lichtblick-rebuild      — rebuild the Lichtblick image (--no-cache) and recreate"
echo "  lichtblick-logs         — follow Lichtblick container logs"
echo "  lichtblick-shell        — open a shell in the Lichtblick container"
echo "  lichtblick-open         — open the Lichtblick web UI in a browser"
echo "  x11-allow / x11-deny   — allow or revoke Docker GUI access to host X11"
echo "  mock-up-d1 [N]          — start observer + robots 1..N with DISPLAY=:1"
echo "  compose-ps              — all running containers"
echo "  mock-ips [N]            — show IP addresses of mock containers"
