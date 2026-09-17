#!/usr/bin/env bash
# host_forwarding.sh - diagnose and temporarily control bridge-netfilter filtering
# for the routed Lab 3 topology. The read-only commands are safe to run before
# setup; disable-filtering/enable-filtering require root and change host state.
set -uo pipefail

SYSCTL_KEY="net.bridge.bridge-nf-call-iptables"
SYSCTL_PROC="/proc/sys/net/bridge/bridge-nf-call-iptables"
AP_CONTAINER="${AP_CONTAINER:-wifi-ap}"
ROBOT_A="${ROBOT_A:-mock-robot-1}"
ROBOT_B="${ROBOT_B:-mock-robot-2}"

bridge_nf() { cat "$SYSCTL_PROC" 2>/dev/null || echo "unavailable"; }

robot_ip() {
    docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$1" 2>/dev/null
}

forwarding_works() {
    docker exec "$AP_CONTAINER" true >/dev/null 2>&1 || return 2
    docker exec "$ROBOT_A" true >/dev/null 2>&1 || return 2
    docker exec "$ROBOT_B" true >/dev/null 2>&1 || return 2
    docker exec "$ROBOT_A" ping -c1 -W1 "$(robot_ip "$ROBOT_B")" >/dev/null 2>&1
}

check() {
    echo "=== routed host forwarding check ==="
    echo "kernel:         $(uname -r)"
    if grep -qi microsoft /proc/version 2>/dev/null; then
        echo "environment:    WSL2"
    else
        echo "environment:    non-WSL2"
    fi
    echo "bridge-nf-call: $(bridge_nf) (1 filters bridged frames; 0 bypasses that filter)"

    forwarding_works
    rc=$?
    if [[ "$rc" -eq 0 ]]; then
        echo "robot->robot:   OK (traffic crosses the AP)"
        return 0
    fi

    if [[ "$rc" -eq 2 ]]; then
        echo "robot->robot:   not tested (start a two-robot routed topology first)"
        echo "next step:      bash scripts/workshop -t routed up 2"
        return 2
    fi

    echo "robot->robot:   BLOCKED (the routed probe failed)"
    echo "next step:      sudo bash docker/scripts/host_forwarding.sh disable-filtering"
    return 1
}

status() {
    echo "live $SYSCTL_KEY: $(bridge_nf)"
}

require_root() {
    if [[ "$(id -u)" -ne 0 ]]; then
        echo "This command changes host state and requires root." >&2
        echo "Re-run with: sudo bash docker/scripts/host_forwarding.sh $1" >&2
        return 1
    fi
}

set_live() {
    local value="$1" action="$2"
    require_root "$action" || return
    modprobe br_netfilter 2>/dev/null || true
    [[ -e "$SYSCTL_PROC" ]] || {
        echo "$SYSCTL_KEY is unavailable; br_netfilter is not exposed by this kernel." >&2
        return 1
    }
    sysctl -w "$SYSCTL_KEY=$value"
}

disable_filtering() {
    echo "WARNING: this changes bridge-netfilter behaviour for all bridged IPv4 traffic on this host."
    echo "The change is temporary and will not be persisted across reboot."
    set_live 0 disable-filtering || return
    echo "bridge filtering disabled for the current boot."
    check
}

enable_filtering() {
    set_live 1 enable-filtering || return
    echo "bridge filtering restored for the current boot."
}

usage() {
    sed -n '2,4p' "$0"
    echo "usage: $0 <check|status|disable-filtering|enable-filtering>"
}

case "${1:-check}" in
    check) check ;;
    status) status ;;
    disable-filtering) disable_filtering ;;
    enable-filtering) enable_filtering ;;
    -h|--help) usage ;;
    *) usage >&2; exit 2 ;;
esac
