#!/usr/bin/env bash
# run_mock_robot.sh - the ONE mock-robot entrypoint for every topology
# (star, flat, routed). Runs inside the container; behaviour is selected by env
# so all three generated compose files can share a single command.
#
# Env switches:
#   AP_GW + REMOTE_SUBNETS   routed: add cross-subnet routes via the AP first
#   MOCK_BUILD=true          star: colcon build the editable /ws before launch
#                            (else source the image's prebuilt /mock_robot_ws)
#   WORKLOAD=bag             routed evidence lab: replay an MCAP instead of driving
#   MOCK_RUN_PILOT=true      drive the robot with pilot.py (flat/routed mock)
#   MOCK_USE_NAV2=true       also bring up the mock_robot_nav2 stack (star)
#   ROBOT_NS, MOCK_FRAME_ID, MOCK_ROBOT_MODEL, MOCK_SENSOR_TOPICS,
#   MOCK_SENSOR_COUNT, MOCK_USE_MECANUM, MOCK_PILOT_RATE, MOCK_NAV2_SLAM,
#   MOCK_SENSOR_QOS_FILE (params file with qos_overrides for the sensor publishers)
set -uo pipefail
set +u; source /opt/ros/jazzy/setup.bash; set -u

# routed: route peer subnets through the AP before any discovery traffic.
if [[ -n "${AP_GW:-}" ]]; then
    for net in ${REMOTE_SUBNETS:-}; do ip route replace "$net" via "$AP_GW"; done
fi

# star: build the editable workspace; otherwise use the prebuilt image workspace.
if [[ "${MOCK_BUILD:-false}" == "true" ]]; then
    cd /ws
    colcon build --symlink-install --packages-select \
        mock_sensor_tools mock_robot_description mock_robot_bringup \
        urdf_raycast_sensors dynamic_image_publisher mock_robot_nav2
    set +u; source install/setup.bash; set -u
else
    set +u; [ -f /mock_robot_ws/install/setup.bash ] && source /mock_robot_ws/install/setup.bash; set -u
fi

# Zenoh: every robot runs its OWN rmw_zenohd router, so its nodes (clients of
# tcp/localhost:7447) keep talking locally even if the uplink to the observer/AP
# drops. Start it before any node opens a session, or rcl init aborts at exit 1.
if [[ "${RMW_IMPLEMENTATION:-}" == "rmw_zenoh_cpp" ]]; then
    echo "run_mock_robot: starting local Zenoh router (rmw_zenohd) on :7447" \
         "cfg=${ZENOH_ROUTER_CONFIG_URI:-<default>}"
    ros2 run rmw_zenoh_cpp rmw_zenohd &
    for _ in $(seq 1 30); do
        ss -ltn 2>/dev/null | grep -q ':7447 ' && break
        sleep 0.5
    done
fi

# routed "bag" workload: replay a recorded MCAP across the shaped link, then idle.
if [[ "${WORKLOAD:-}" == "bag" ]]; then
    exec bash /scripts/play_bag.sh
fi

# Exercise 1 only: hold this robot's ROS startup so the Netdata fleet collector can attach
# and start recording before the discovery burst fires. Unset or 0 (every other lab) skips
# it. After the bag branch so Lab 4 replay is untouched; before the launch below so the
# whole robot starts late as one unit.
start_delay="${MOCK_START_DELAY:-0}"
if [[ "$start_delay" != 0 ]]; then
    echo "run_mock_robot: holding startup ${start_delay}s so a collector can attach first"
    sleep "$start_delay"
fi

# Namespace: explicit (routed pins robot_a, robot_b, ...) or /robot_<last IP octet>.
if [[ -n "${ROBOT_NS:-}" ]]; then
    NS="${ROBOT_NS#/}"
else
    OCTET="$(hostname -I 2>/dev/null | awk '{print $1}' | awk -F. '{print $NF}')"
    NS="robot_${OCTET:-$(hostname)}"
fi
FRAME="${MOCK_FRAME_ID:-$NS}"
MODEL="${MOCK_ROBOT_MODEL:-a300}"
TOPICS="${MOCK_SENSOR_TOPICS:-/camera/image_raw,/scan}"
SENSORS="${MOCK_SENSOR_COUNT:-1}"
MECANUM="${MOCK_USE_MECANUM:-false}"
RUN_PILOT="${MOCK_RUN_PILOT:-false}"
USE_NAV2="${MOCK_USE_NAV2:-false}"

# ros2 launch rejects name:= with an empty value, so omit it rather than pass nothing.
QOS_ARGS=()
[[ -n "${MOCK_SENSOR_QOS_FILE:-}" ]] && QOS_ARGS+=(sensor_qos_file:="$MOCK_SENSOR_QOS_FILE")

echo "run_mock_robot: ns=/$NS model=$MODEL sensors=$SENSORS build=${MOCK_BUILD:-false}" \
     "pilot=$RUN_PILOT nav2=$USE_NAV2 rmw=${RMW_IMPLEMENTATION:-?}"

# Drive the robot once its command chain is up (flat/routed mock workloads).
if [[ "$RUN_PILOT" == "true" ]]; then
    ( sleep 12; exec python3 /scripts/lab3/pilot.py --ns "$NS" --rate "${MOCK_PILOT_RATE:-10}" ) &
    trap 'kill $! 2>/dev/null || true' EXIT
fi

# star NAV2 path: launch the robot with use_nav2:=true, then the Nav2 stack.
if [[ "$USE_NAV2" == "true" ]]; then
    ros2 launch mock_robot_bringup mock_robot.launch.py \
        robot_name:="$NS" frame_id:="$FRAME" robot_model:="$MODEL" \
        sensor_topics:="$TOPICS" sensor_count:="$SENSORS" \
        use_mecanum:="$MECANUM" use_nav2:=true "${QOS_ARGS[@]}" &
    exec ros2 launch mock_robot_nav2 nav2_bringup.launch.py \
        robot_name:="$NS" frame_id:="$FRAME" robot_model:="$MODEL" \
        use_mecanum:="$MECANUM" slam:="${MOCK_NAV2_SLAM:-true}"
fi

exec ros2 launch mock_robot_bringup mock_robot.launch.py \
    robot_name:="$NS" frame_id:="$FRAME" robot_model:="$MODEL" \
    sensor_topics:="$TOPICS" sensor_count:="$SENSORS" \
    use_mecanum:="$MECANUM" use_nav2:=false "${QOS_ARGS[@]}"
