#!/usr/bin/env bash
# routed_test.sh - layered health check for the generated Lab 3 routed topology.
set -uo pipefail

VERBOSE=false
while (($#)); do
    case "$1" in
        --verbose) VERBOSE=true ;;
        -h|--help) echo "usage: $0 [--verbose]"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

AP="${AP_CONTAINER:-wifi-ap}"
CONSOLE="${CONSOLE_CONTAINER:-observer}"
ROBOT_A="${ROBOT_A:-}"
ROBOT_B="${ROBOT_B:-}"
RMW="${RMW_IMPLEMENTATION:-}"
failures=0

pass() { printf 'PASS  %-14s %s\n' "$1" "$2"; }
fail() { printf 'FAIL  %-14s %s\n' "$1" "$2"; failures=$((failures + 1)); }
detail() { $VERBOSE && printf '      %s\n' "$1" || true; }

running() { docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null | grep -qx true; }
exec_in() { docker exec "$1" bash -lc "$2"; }

fleet_robots() {
    docker ps --format '{{.Names}}' \
        | grep -E '^mock-robot-[0-9]+$' \
        | sort -V \
        || true
}

container_env() {
    local container="$1" key="$2"
    docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$container" 2>/dev/null \
        | sed -n "s/^${key}=//p" \
        | head -1
}

robot_ip() {
    docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$1" 2>/dev/null
}

robot_gw() { container_env "$1" AP_GW; }
robot_ns() { container_env "$1" ROBOT_NS; }

select_robots() {
    local robots
    mapfile -t robots < <(fleet_robots)
    [[ -n "$ROBOT_A" ]] || ROBOT_A="${robots[0]:-}"
    [[ -n "$ROBOT_B" ]] || ROBOT_B="${robots[1]:-}"
}
console_ros_env() {
    if [[ -z "$RMW" ]]; then
        RMW="$(container_env "$CONSOLE" RMW_IMPLEMENTATION)"
    fi
    case "$RMW" in
        rmw_cyclonedds_cpp)
            printf 'export CYCLONEDDS_URI=%q; ' "$(container_env "$CONSOLE" CYCLONEDDS_URI)"
            ;;
        rmw_fastrtps_cpp)
            printf 'export FASTRTPS_DEFAULT_PROFILES_FILE=%q; ' \
                "$(container_env "$CONSOLE" FASTRTPS_DEFAULT_PROFILES_FILE)"
            ;;
        rmw_zenoh_cpp)
            printf 'export ZENOH_SESSION_CONFIG_URI=%q; ' \
                "$(container_env "$CONSOLE" ZENOH_SESSION_CONFIG_URI)"
            ;;
        *)
            detail "unknown or unset RMW_IMPLEMENTATION='$RMW'; using the container defaults"
            ;;
    esac
}
container_hint() {
    local state
    state="$(docker inspect -f '{{.State.Status}}' "$1" 2>/dev/null || echo missing)"
    case "$state" in
        exited|dead)
            detail "$1 is $state; recent log:"
            docker logs --tail 4 "$1" 2>&1 | sed 's/^/      /' >&2
            ;;
        missing)
            detail "$1 does not exist; regenerate and start the routed topology"
            ;;
    esac
}

select_robots
for container in "$AP" "$CONSOLE" "$ROBOT_A" "$ROBOT_B"; do
    if running "$container"; then
        pass topology "$container is running"
    else
        fail topology "$container is not running"
        container_hint "$container"
    fi
done

if ((failures)); then
    echo "Start a routed topology with: bash scripts/workshop -t routed up 2" >&2
    exit 2
fi

robot_b_ip="$(robot_ip "$ROBOT_B")"
robot_a_gw="$(robot_gw "$ROBOT_A")"
robot_a_ns="$(robot_ns "$ROBOT_A")"

if [[ -z "$robot_b_ip" || -z "$robot_a_gw" || -z "$robot_a_ns" ]]; then
    fail inventory "could not read routed IP, gateway, or namespace metadata"
    exit 1
fi

if exec_in "$ROBOT_A" "ip route get $robot_b_ip" | grep -q "via $robot_a_gw"; then
    pass route "${ROBOT_A} reaches ${ROBOT_B} via the AP"
else
    fail route "${ROBOT_A} route to ${ROBOT_B} does not use $robot_a_gw"
fi

if exec_in "$ROBOT_A" "ping -c1 -W1 $robot_b_ip" >/dev/null 2>&1; then
    pass ip-transit "${ROBOT_A} reached ${ROBOT_B}"
else
    fail ip-transit "${ROBOT_A} could not reach ${ROBOT_B}"
fi

before="$(docker exec "$AP" bash -lc 'awk "/eth[0-9]+:/ {sum += \$2 + \$10} END {print sum+0}" /proc/net/dev' 2>/dev/null)"
exec_in "$ROBOT_A" "ping -c2 -W1 $robot_b_ip" >/dev/null 2>&1 || true
after="$(docker exec "$AP" bash -lc 'awk "/eth[0-9]+:/ {sum += \$2 + \$10} END {print sum+0}" /proc/net/dev' 2>/dev/null)"
if [[ "$after" =~ ^[0-9]+$ && "$before" =~ ^[0-9]+$ && "$after" -gt "$before" ]]; then
    pass ap-transit "AP interface counters increased during the probe"
else
    fail ap-transit "could not prove AP counters increased"
fi

topic="${ROUTED_TEST_TOPIC:-/$robot_a_ns/scan}"
topic_list=""
for _ in $(seq 1 6); do
    topic_list="$(exec_in "$CONSOLE" "source /opt/ros/jazzy/setup.bash; source /mock_robot_ws/install/setup.bash 2>/dev/null || true; $(console_ros_env) ros2 topic list --no-daemon" 2>/dev/null || true)"
    grep -Fxq "$topic" <<<"$topic_list" && break
    sleep 2
done
if grep -Fxq "$topic" <<<"$topic_list"; then
    pass discovery "$topic is visible from the console"
    type="$(exec_in "$CONSOLE" "source /opt/ros/jazzy/setup.bash; source /mock_robot_ws/install/setup.bash 2>/dev/null || true; $(console_ros_env) ros2 topic info '$topic' -v --no-daemon" 2>/dev/null \
        | sed -n 's/^Type: //p' | head -1)"
    data_ok=false
    if [[ -n "$type" ]]; then
        for _ in $(seq 1 3); do
            if exec_in "$CONSOLE" "source /opt/ros/jazzy/setup.bash; source /mock_robot_ws/install/setup.bash 2>/dev/null || true; $(console_ros_env) timeout 12 ros2 topic echo '$topic' '$type' --once --no-daemon" >/dev/null 2>&1; then
                data_ok=true
                break
            fi
            sleep 2
        done
    fi
    if [[ "$data_ok" == true ]]; then
        pass data "received one message on $topic"
    else
        fail data "topic exists but no message was received on $topic"
    fi
else
    fail discovery "$topic is not visible from the console"
    detail "Available topics: ${topic_list//$'\n'/, }"
fi

if ((failures)); then
    echo "routed-check: $failures check(s) failed" >&2
    exit 1
fi
echo "routed-check: all checks passed"
