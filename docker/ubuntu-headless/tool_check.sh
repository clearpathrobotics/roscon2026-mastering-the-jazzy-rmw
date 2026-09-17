#!/usr/bin/env bash
# Verifies the bundled toolset resolves on PATH and basic ROS 2 commands work.
# Runs inside any of the project's containers.
#
# From docker/:
#   docker run --rm -v "$PWD/ubuntu-headless/tool_check.sh:/tool_check.sh:ro" \
#     ghcr.io/clearpathrobotics/roscon2026-mastering-the-jazzy-rmw:ubuntu-headless-latest bash /tool_check.sh

set -euo pipefail

PASS=0; FAIL=0
RED='\033[0;31m'; GRN='\033[0;32m'; NC='\033[0m'

# docker exec skips ENTRYPOINT, so re-source the ROS env from the apt install.
# setup.bash references variables that may be unset, so relax nounset around it.
set +u
if ! command -v ros2 &>/dev/null; then
    for setup in /opt/ros/jazzy/setup.bash /opt/ros/humble/setup.bash; do
        [[ -f "$setup" ]] && source "$setup" && break
    done
fi
set -u

check() {
    local label="$1"; shift
    local cmd="$1"
    if command -v "$cmd" &>/dev/null; then
        printf "${GRN}OK${NC}      %-30s (%s)\n" "$label" "$cmd"
        PASS=$((PASS+1))
    else
        printf "${RED}MISSING${NC} %-30s (%s)\n" "$label" "$cmd"
        FAIL=$((FAIL+1))
    fi
}

echo "=== Networking diagnostics ==="
check "iperf3" iperf3
check "ping"   ping
check "tc"     tc
check "ethtool" ethtool
check "nmap"   nmap
check "ncat"   ncat
check "socat"  socat
check "mtr"    mtr
check "traceroute" traceroute
check "dig (dnsutils)" dig

echo
echo "=== Packet capture ==="
check "tcpdump" tcpdump
check "tshark"  tshark

echo
echo "=== Monitoring ==="
check "htop"  htop
check "iftop" iftop

echo
echo "=== Shell QoL ==="
check "tmux"  tmux
check "vim"   vim
check "nano"  nano
check "less"  less
check "jq"    jq
check "git"   git
check "ssh"   ssh

echo
echo "=== DDS / ROS 2 ==="
check "ros2"     ros2
check "ddsperf"  ddsperf
check "idlc"     idlc

if command -v ros2 &>/dev/null; then
    echo
    echo "ros2 sanity:"
    if ros2 pkg prefix demo_nodes_cpp &>/dev/null; then
        printf "  ${GRN}OK${NC}    demo_nodes_cpp present\n"; PASS=$((PASS+1))
    else
        printf "  ${RED}MISSING${NC} demo_nodes_cpp\n"; FAIL=$((FAIL+1))
    fi
    if ros2 pkg prefix performance_test &>/dev/null; then
        printf "  ${GRN}OK${NC}    performance_test present\n"; PASS=$((PASS+1))
    else
        printf "  ${RED}MISSING${NC} performance_test\n"; FAIL=$((FAIL+1))
    fi
    if ros2 pkg prefix tracetools &>/dev/null; then
        printf "  ${GRN}OK${NC}    tracetools present\n"; PASS=$((PASS+1))
    else
        printf "  ${RED}MISSING${NC} tracetools\n"; FAIL=$((FAIL+1))
    fi
    # All three RMWs must resolve, since the image exists to compare them.
    for pkg in rmw_cyclonedds_cpp rmw_fastrtps_cpp rmw_zenoh_cpp action_tutorials_cpp example_interfaces; do
        if ros2 pkg prefix "$pkg" &>/dev/null; then
            printf "  ${GRN}OK${NC}    %s present\n" "$pkg"; PASS=$((PASS+1))
        else
            printf "  ${RED}MISSING${NC} %s\n" "$pkg"; FAIL=$((FAIL+1))
        fi
    done
fi

echo
echo "=== Summary ==="
echo "  pass:    $PASS"
echo "  fail:    $FAIL"
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
