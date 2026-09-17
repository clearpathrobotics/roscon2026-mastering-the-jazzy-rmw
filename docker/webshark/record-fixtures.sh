#!/usr/bin/env bash
# record-fixtures.sh - record, trim and document the failure-mode fixture library.
#
# The captures in fixtures/ are the workshop's take-home material and the test suites'
# input. This script is how they are made, so a re-record lands at the same size and the
# numbers the guide quotes can be regenerated rather than trusted.
#
# Usage:
#   ./record-fixtures.sh list                 show the catalogue and what each fixture needs
#   ./record-fixtures.sh record <name|all>    record raw captures into fixtures-raw/
#   ./record-fixtures.sh trim <name|all>      cut to the symptom window, gzip into fixtures/
#   ./record-fixtures.sh manifest             regenerate fixtures/manifest.tsv
#   ./record-fixtures.sh verify               re-check every committed fixture against the manifest
#
# Recording needs the fleet up (scripts/workshop -t flat up 3, then scripts/workshop webshark up). Scenarios say which RMW they need; a
# scenario whose RMW does not match the running fleet refuses rather than mislabelling a
# capture, which is the mistake _capture_rmw_label in scripts/workshop exists to prevent.
#
# ALL packet analysis runs inside the webshark container, never on the host. The host's
# tshark has no Zenoh dissector at all, so a Zenoh filter silently returns 0 instead of
# erroring: measured 0 declares on the host against 1534 in the container, same file, same
# filter. Counting on the host is not a slower path, it is a wrong one.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
LAB2="$REPO/lab2-on-the-wire"
NETEM="$LAB2/scripts/netem_profile.sh"
RAW="$LAB2/captures/fixtures-raw"        # scratch, gitignored with the rest of captures/
OUT="$HERE/fixtures"                     # committed
IMAGE=roscon2026-jazzy-rmw:webshark
DDS_SUBNET='172\.31\.0\.'

# Per-file and total ceilings, checked by `trim`. Discovery fixtures land at 66-373 KB. The
# image fixtures cannot: one camera sample is a 2.6 MB frame spread over roughly 1800
# packets, and pixel data does not compress, so even the 2000-frame floor is about 780 KB.
# The ceiling is set above that rather than shrinking the fixture that carries the workshop's
# central QoS lesson down to nothing.
MAX_FILE_KB=900
MAX_TOTAL_KB=10240

# name ; rmw ; window filter ; absent filter ; description ; head filter (optional)
#
# Semicolon-delimited because a display filter contains || and a pipe delimiter splits the
# row in the middle of the filter. That failed silently: cut took everything before the
# first ||, so the row still parsed and the fixture was checked against half a filter.
#
# The window filter is load-bearing: `trim` uses it to find the symptom window and then
# re-runs it on the output, so a cut that loses the evidence fails instead of shipping.
#
# The absent filter is for the fixtures whose lesson is a silence. "Nothing on the wire"
# cannot be shown by a filter that matches; it is shown by a live capture full of other
# traffic in which one particular thing is missing. Where it is set, the count must be
# zero, and a non-zero count means the scenario failed to induce what it claims.
FIXTURES=(
  "qos-mismatch;cyclone;rtps.param.topicName contains \"fixture_qos\";;Best-effort writer against a reliable reader, both announced in one file"
  "domain-mismatch;cyclone;udp.dstport == 17900 || udp.dstport == 26650;rtps.sm.id == 0x06 && (udp.dstport == 17900 || udp.dstport == 26650);Two domains announcing on disjoint ports, never seeing each other"
  "multicast-storm;cyclone;ip.dst == 239.255.0.1;;SPDP announcements flooding the discovery multicast group"
  "nothing-on-wire;cyclone;rtps;rtps.param.topicName contains \"fixture_localhost\";A healthy node publishing, and a busy bus it never reaches"
  "multicast-blocked;cyclone;ip.dst == 239.255.0.1;ip.dst == 239.255.0.1 && ip.src == __MCAST_BLOCKED_IP__;One robot announcing to the group with nothing coming back"
  "node-death;cyclone;rtps.sm.wrEntityId == 0x000100c2;;Two participants going silent at different moments, with no departure notice"
  "fragment-loss;cyclone;rtps.sm.id == 0x16;;Image fragments under loss, samples that never complete"
  "reliable-vs-besteffort;cyclone;rtps.sm.id == 0x07;;The same image stream on both reliability settings under one impairment;rtps.param.topicName contains \"fixture_img\""
  "zenoh-no-router;zenoh;tcp.flags.syn == 1 && tcp.flags.ack == 0;;A Zenoh session dialling a router that is not there"
  "zenoh-router-killed;zenoh;zenoh;;A router stopped mid-capture, and the sessions reacting"
  # Healthy baselines. A failure library is unreadable without them: every "broken" shape in
  # the guide is stated against a "healthy" one. These are imported from existing captures
  # rather than recorded, so they need no fleet.
  "healthy-fastdds;import;rtps;;Fast DDS discovery and traffic with nothing wrong"
  "healthy-cyclone;import;rtps;;A short healthy Cyclone capture that opens in a couple of seconds"
  "healthy-cyclone-discovery;import;rtps.sm.id == 0x15 && (rtps.sm.wrEntityId == 0x000003c2 || rtps.sm.wrEntityId == 0x000004c2);;Cyclone endpoint discovery, the reference for what SEDP should look like"
  "healthy-zenoh;import;zenoh.body.frame.payload.body.declare.body.declare_key_expr.wire_expr;;A Zenoh session declaring its key expressions normally"
)

# Where each imported baseline comes from. Kept out of the table so the table stays one line
# per fixture; these are the only fixtures with a source outside this script.
BASELINE_SRC=(
  "healthy-fastdds;guide_nodaemon.pcap"
  "healthy-cyclone;live_cyclone_00043_20260818181021.pcap"
  "healthy-cyclone-discovery;sedp_cyclone_bounce_20260819223138.pcap"
  "healthy-zenoh;live_zenoh_00001_20260819224310.pcap"
)

_fx_field() {  # _fx_field <name> <1-5>
    local row; for row in "${FIXTURES[@]}"; do
        [[ "${row%%;*}" == "$1" ]] && { echo "$row" | cut -d';' -f"$2"; return 0; }
    done
    return 1
}
_fx_names() { local row; for row in "${FIXTURES[@]}"; do echo "${row%%;*}"; done; }

_die() { echo "ERROR: $*" >&2; exit 1; }
_say() { echo "[*] $*"; }

# Analysis runs in a throwaway webshark container with the directory mounted, so it works
# on fixtures/ (never mounted into the running viewer) as well as on raw scratch.
_tshark() {  # _tshark <host-dir> <args...>
    local dir="$1"; shift
    docker run --rm -v "$dir":/d --entrypoint tshark "$IMAGE" "$@"
}
# An invalid display filter makes tshark exit non-zero and print nothing, which reads as a
# count of 0. Every absence check in this script would then pass vacuously, so a filter
# that does not compile has to be an error rather than a zero.
_count() {  # _count <host-dir> <file> <display-filter> -> integer
    local dir="$1" f="$2" filt="$3" out rc
    out=$(_tshark "$dir" -r "/d/$f" -Y "$filt" -T fields -e frame.number 2>&1); rc=$?
    if [[ $rc -ne 0 ]]; then
        echo "ERROR: filter did not compile: '${filt}'" >&2
        echo "       $(echo "$out" | head -1)" >&2
        return 1
    fi
    echo "$out" | grep -c .
}

_rmw_label() {
    local impl; impl="$(docker exec observer printenv RMW_IMPLEMENTATION 2>/dev/null)"
    case "$impl" in
        rmw_cyclonedds_cpp) echo cyclone ;;
        rmw_fastrtps_cpp)   echo fast ;;
        rmw_zenoh_cpp)      echo zenoh ;;
        *) return 1 ;;
    esac
}
_dds_iface() {
    local o; o="$(docker exec "$1" sh -c "ip -o -4 addr show | awk '/${DDS_SUBNET}/{print \$2; exit}'" 2>/dev/null)"
    echo "${o:-eth0}"
}
# _dds_ip <container> -> that container's own address on DDS_SUBNET, no /mask. Docker's
# bridge driver assigns these by connection order rather than pinning one per service, so a
# fixture that needs to name a specific robot's address (multicast-blocked) has to resolve it
# fresh each recording rather than hardcode a value that drifts the moment the network is
# recreated.
_dds_ip() {
    docker exec "$1" sh -c "ip -o -4 addr show | awk '/${DDS_SUBNET}/{sub(\"/.*\", \"\", \$4); print \$4; exit}'" 2>/dev/null
}

# netem shapes ingress only if the host has the ifb module; without it the profile is
# egress-only and netem_profile.sh mentions that in passing. An egress-only loss capture
# looks the same on its face as a bidirectional one, so record which one this is rather
# than leaving a reader to guess.
IFB_STATE=unknown
_check_ifb() {
    # /proc/modules rather than lsmod: /usr/sbin is not on PATH for a non-login shell, so
    # lsmod silently fails to run and every recording reads as egress-only.
    if grep -q '^ifb ' /proc/modules 2>/dev/null; then IFB_STATE=bidirectional
    else
        IFB_STATE=egress-only
        echo "WARNING: ifb not loaded, netem will shape egress only." >&2
        echo "         Run 'sudo modprobe ifb' for a bidirectional impairment." >&2
    fi
    echo "$IFB_STATE" > "$RAW/.ifb-state"
}

_need_fleet() {  # _need_fleet <required-rmw>
    docker ps --format '{{.Names}}' | grep -q '^observer$' \
        || _die "the fleet is not up. Run: scripts/workshop -t flat up 3, then scripts/workshop webshark up"
    local have; have="$(_rmw_label)" || _die "cannot read RMW_IMPLEMENTATION from the observer"
    [[ "$have" == "$1" ]] || _die "this fixture needs RMW=$1 but the fleet is running $have. Re-run: WORKSHOP_RMW=$1 scripts/workshop -t flat up 3, then scripts/workshop webshark up"
}

# Capture at the observer, the vantage that sees every robot. Robots are configured
# hub-and-spoke and cannot see each other, so this is the only vantage that sees the fleet.
# Capture to /tmp inside the container and copy out afterwards. tshark cannot write to the
# bind-mounted /lab2-captures even as root, which is the same reason scripts/workshop captures to
# /tmp and docker-cps the result.
CAP_NAME=""
_cap_start() {  # _cap_start <name> [extra tshark args...]
    CAP_NAME="$1"; shift
    local iface; iface="$(_dds_iface observer)"
    docker exec observer rm -f "/tmp/${CAP_NAME}.pcap" 2>/dev/null
    docker exec -d observer tshark -i "$iface" -F pcap -q -w "/tmp/${CAP_NAME}.pcap" "$@"
    sleep 3   # tshark needs to be on the wire before the scenario starts, not alongside it
    docker exec observer pgrep -x tshark >/dev/null 2>&1 \
        || _die "tshark did not start at the observer"
}
_cap_stop() {
    docker exec observer pkill -SIGINT tshark 2>/dev/null
    local waited=0
    while docker exec observer pgrep -x tshark >/dev/null 2>&1; do
        sleep 1; waited=$((waited + 1))
        [[ "$waited" -ge 8 ]] && { docker exec observer pkill -SIGKILL tshark; break; }
    done
    docker cp "observer:/tmp/${CAP_NAME}.pcap" "$RAW/${CAP_NAME}.pcap" 2>/dev/null \
        || echo "WARNING: could not copy ${CAP_NAME}.pcap out of the observer" >&2
    docker exec observer rm -f "/tmp/${CAP_NAME}.pcap" 2>/dev/null
}

_ros() {  # _ros <container> <command...>  - run with ROS sourced
    local c="$1"; shift
    docker exec "$c" bash -lc "source /opt/ros/jazzy/setup.bash 2>/dev/null; source /ws/install/setup.bash 2>/dev/null; $*"
}
_ros_bg() {
    local c="$1"; shift
    docker exec -d "$c" bash -lc "source /opt/ros/jazzy/setup.bash 2>/dev/null; source /ws/install/setup.bash 2>/dev/null; $*"
}

# A scenario that quietly fails to start its publishers records a file full of unrelated
# fleet traffic and still looks like a success. Wait for the topic to actually exist, and
# refuse to keep recording if it never shows up.
_await_topic() {  # _await_topic <topic> [timeout-seconds]
    local topic="$1" limit="${2:-30}" waited=0
    while [[ "$waited" -lt "$limit" ]]; do
        if _ros observer "ros2 topic list 2>/dev/null" | grep -qx "$topic"; then
            _say "  $topic is up after ${waited}s"; return 0
        fi
        sleep 3; waited=$((waited + 3))
    done
    echo "ERROR: $topic never appeared after ${limit}s; the scenario did not start" >&2
    return 1
}

# ---------------------------------------------------------------- scenarios, group B ---

# A reliable reader can never match a best-effort writer, and by default neither side says
# so. The wire settles it: both endpoints announce in SEDP, and no user data follows.
rec_qos_mismatch() {
    _need_fleet cyclone
    _cap_start qos-mismatch
    _say "best-effort writer against a reliable reader on /fixture_qos"
    _ros_bg mock-robot-1 "ros2 topic pub -r 5 --qos-reliability best_effort /fixture_qos std_msgs/msg/String '{data: mismatched}'"
    # A volatile writer against a transient-local reader fails the same way for a different
    # reason, so the one capture carries both mismatch kinds a reader is likely to hit.
    _ros_bg mock-robot-2 "ros2 topic pub -r 5 --qos-durability volatile /fixture_durability std_msgs/msg/String '{data: mismatched}'"
    _await_topic /fixture_qos || return 1
    _await_topic /fixture_durability || return 1
    # Readers join only once the writers are announced, so the capture holds the reader's
    # SEDP arriving against an already-published writer, which is the order a reader of the
    # capture has to reason about.
    _ros_bg observer "ros2 topic echo --qos-reliability reliable /fixture_qos std_msgs/msg/String"
    _ros_bg observer "ros2 topic echo --qos-durability transient_local /fixture_durability std_msgs/msg/String"
    sleep 25
    _ros mock-robot-1 "pkill -f 'topic pub'" >/dev/null 2>&1
    _ros mock-robot-2 "pkill -f 'topic pub'" >/dev/null 2>&1
    _ros observer "pkill -f 'topic echo'" >/dev/null 2>&1
    _cap_stop
}

# Two nodes on different ROS_DOMAIN_IDs announce on different port pairs and never see each
# other. The most common self-inflicted "they cannot find each other" there is.
#
# Domains 42 and 77, neither of which the fleet uses, so the two populations are the only
# things in their port ranges and a reader can separate them without knowing the fleet's
# own layout. Domain N's SPDP port is 7400 + 250*N, giving 17900 and 26650.
rec_domain_mismatch() {
    _need_fleet cyclone
    local cfg=/tmp/fixture-domain.xml
    docker exec observer sh -c "cat > $cfg <<'EOF'
<CycloneDDS><Domain id=\"any\">
  <General>
    <AllowMulticast>true</AllowMulticast>
    <Interfaces><NetworkInterface name=\"eth0\"/></Interfaces>
  </General>
</Domain></CycloneDDS>
EOF"
    _cap_start domain-mismatch
    _say "a talker on domain 42 and a listener on domain 77, and nothing else"
    # Exactly one participant per domain. A first recording put a talker AND a listener on
    # 77, which discovered each other perfectly and announced their endpoints, so the file
    # showed a healthy pair beside a lone talker rather than two sides failing to meet.
    # With one participant each, neither ever gets a peer, so both announce themselves
    # forever and no endpoint discovery follows.
    _ros_bg observer "CYCLONEDDS_URI=file://$cfg ROS_DOMAIN_ID=42 \
        ros2 topic pub -r 5 /fixture_domain std_msgs/msg/String '{data: d42}'"
    _ros_bg observer "CYCLONEDDS_URI=file://$cfg ROS_DOMAIN_ID=77 \
        ros2 topic echo /fixture_domain std_msgs/msg/String"
    sleep 30
    _ros observer "pkill -f 'topic pub'; pkill -f 'topic echo'" >/dev/null 2>&1
    _cap_stop
}

# The fleet runs AllowMulticast=false with static peers, so it puts nothing on
# 239.255.0.1 at all. A storm needs a multicast-enabled config, which is why this uses
# simple-multicast.xml rather than a netem trick.
rec_multicast_storm() {
    _need_fleet cyclone
    local cfg=/tmp/fixture-mcast-storm.xml
    docker exec observer sh -c "cat > $cfg <<'EOF'
<CycloneDDS><Domain id=\"any\">
  <General><AllowMulticast>true</AllowMulticast></General>
  <Discovery>
    <SPDPInterval>200ms</SPDPInterval>
    <ParticipantIndex>auto</ParticipantIndex>
    <MaxAutoParticipantIndex>120</MaxAutoParticipantIndex>
  </Discovery>
</Domain></CycloneDDS>
EOF"
    # Scope the capture to multicast. The storm is a question about announcement volume on
    # the discovery group, and 25000 frames of the fleet's camera stream around it pushed the
    # trimmed file to 776 KB while adding nothing a reader would look at.
    _cap_start multicast-storm -f "ip multicast"
    _say "12 participants announcing every 200ms onto 239.255.0.1"
    local i
    for i in $(seq 1 12); do
        _ros_bg observer "CYCLONEDDS_URI=file://$cfg RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
            ros2 topic pub -r 1 /fixture_storm_$i std_msgs/msg/String '{data: storm}'"
    done
    sleep 25
    _ros observer "pkill -f 'topic pub'" >/dev/null 2>&1
    _cap_stop
}

# A node that is up and publishing, with nothing on the fleet bus, because the traffic
# never left the host. First thing to rule out and the easiest to misread as a fault.
# Bind Cyclone to loopback rather than using ROS_LOCALHOST_ONLY, which Jazzy deprecated in
# favour of ROS_AUTOMATIC_DISCOVERY_RANGE and which measurably did not hold here: a first
# recording put 56 announcements of the topic on the bus it was supposed to stay off.
# An explicit interface binding is not advisory.
rec_nothing_on_wire() {
    _need_fleet cyclone
    local cfg=/tmp/fixture-loopback.xml
    docker exec observer sh -c "cat > $cfg <<'EOF'
<CycloneDDS><Domain id=\"any\">
  <General>
    <AllowMulticast>false</AllowMulticast>
    <Interfaces><NetworkInterface address=\"127.0.0.1\"/></Interfaces>
  </General>
  <Discovery><Peers><Peer address=\"localhost\"/></Peers></Discovery>
</Domain></CycloneDDS>
EOF"
    _cap_start nothing-on-wire
    _say "a loopback-bound talker: healthy node, and a busy bus it never reaches"
    _ros_bg observer "CYCLONEDDS_URI=file://$cfg \
        ros2 topic pub -r 10 /fixture_localhost std_msgs/msg/String '{data: invisible}'"
    _ros_bg observer "CYCLONEDDS_URI=file://$cfg \
        ros2 topic echo /fixture_localhost std_msgs/msg/String"
    sleep 25
    _ros observer "pkill -f 'topic pub'; pkill -f 'topic echo'" >/dev/null 2>&1
    _cap_stop
}

# ---------------------------------------------------------------- scenarios, group A ---

# Pull the camera stream to the observer so it crosses the impaired link. The publisher
# runs regardless, but without a subscriber the samples never leave the robot.
_sub_camera() {  # _sub_camera <robot-index> [extra ros2 args]
    local i="$1"; shift
    _ros_bg observer "ros2 topic echo ${*:-} \
        /robot_${i}/sensor_0/camera/image_raw sensor_msgs/msg/Image >/dev/null 2>&1"
}

# The trim window for an impaired fixture has to start where the impairment does. Left to
# the window filter it starts at the first match instead, which for fragment-loss is during
# the clean warm-up: 25000 frames of a camera stream is about one second, so the whole
# trimmed file landed before netem was ever applied.
_impair() {  # _impair <profile>
    local i ri
    date +%s.%N > "$RAW/${CAP_NAME}.impaired-at"
    for i in 1 2 3; do
        ri="$(_dds_iface "mock-robot-${i}")"
        bash "$NETEM" "$1" "mock-robot-${i}" "$ri" >/dev/null 2>&1
        # netem_profile.sh reports success on a qdisc it did not actually install, so read
        # the qdisc back. scripts/workshop does the same check for the same reason.
        docker exec "mock-robot-${i}" tc qdisc show dev "$ri" 2>/dev/null | grep -q netem \
            || echo "    WARNING: netem did not take on mock-robot-${i} (${ri})" >&2
    done
}
_unimpair() {
    local i; for i in 1 2 3; do
        bash "$NETEM" clear "mock-robot-${i}" "$(_dds_iface "mock-robot-${i}")" >/dev/null 2>&1
    done
}

# A raw camera frame is far larger than the MTU, so every sample arrives as a train of
# DATA_FRAG submessages and every one of them has to land. sparse's steady 0.05% drop
# is chosen for exactly this: near-clean for small messages, ruinous for large ones.
rec_fragment_loss() {
    _need_fleet cyclone
    _cap_start fragment-loss
    _say "subscribing to the raw camera stream on a clean link"
    _sub_camera 1
    _sub_camera 2
    sleep 15
    _say "applying sparse, so the same stream now loses fragments"
    _impair sparse
    sleep 40
    _unimpair
    _ros observer "pkill -f 'topic echo'" >/dev/null 2>&1
    _cap_stop
}

# The camera publishes RELIABLE and exposes no QoS parameter, so the best-effort side needs a
# republisher. Both run off the same source frames at the same rate under one impairment, so
# the contrast is a property of the capture rather than of two runs taken on trust.
rec_reliable_vs_besteffort() {
    _need_fleet cyclone
    docker exec mock-robot-1 sh -c "cat > /tmp/fixture_relay.py <<'EOF'
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from sensor_msgs.msg import Image

# One subscription, two publishers differing only in reliability, so a reader comparing the
# two topics in the capture is comparing the setting and nothing else.
class Relay(Node):
    def __init__(self):
        super().__init__('fixture_relay')
        depth = QoSProfile(depth=5, history=QoSHistoryPolicy.KEEP_LAST)
        rel = QoSProfile(depth=5, history=QoSHistoryPolicy.KEEP_LAST,
                         reliability=QoSReliabilityPolicy.RELIABLE)
        be  = QoSProfile(depth=5, history=QoSHistoryPolicy.KEEP_LAST,
                         reliability=QoSReliabilityPolicy.BEST_EFFORT)
        self.p_rel = self.create_publisher(Image, '/fixture_img_reliable', rel)
        self.p_be  = self.create_publisher(Image, '/fixture_img_besteffort', be)
        self.create_subscription(Image, '/robot_1/sensor_0/camera/image_raw',
                                 self.cb, depth)
    def cb(self, msg):
        self.p_rel.publish(msg)
        self.p_be.publish(msg)

rclpy.init()
rclpy.spin(Relay())
EOF"
    _cap_start reliable-vs-besteffort
    _say "relaying the camera onto a reliable and a best-effort topic"
    _ros_bg mock-robot-1 "python3 /tmp/fixture_relay.py"
    _await_topic /fixture_img_reliable 40 || return 1
    _await_topic /fixture_img_besteffort 40 || return 1
    _ros_bg observer "ros2 topic echo --qos-reliability reliable /fixture_img_reliable sensor_msgs/msg/Image >/dev/null 2>&1"
    _ros_bg observer "ros2 topic echo --qos-reliability best_effort /fixture_img_besteffort sensor_msgs/msg/Image >/dev/null 2>&1"
    sleep 15
    _say "applying heavy to both at once"
    _impair heavy
    sleep 40
    _unimpair
    _ros mock-robot-1 "pkill -f fixture_relay" >/dev/null 2>&1
    _ros observer "pkill -f 'topic echo'" >/dev/null 2>&1
    _cap_stop
}

# Two participants stop at different moments while a third keeps going. Neither says goodbye:
# measured on a first recording, `docker stop -t 20` produced no dispose and no unregister, so
# a SIGTERM'd containerised ROS stack leaves exactly as abruptly as a SIGKILL'd one. That is
# the lesson rather than the clean-versus-hard contrast originally planned: a peer learns a
# node is gone only from the silence, and how long that takes is the lease, not a message.
#
# No camera subscription. Without one the image stream stays on the robot, so the capture is
# discovery only and a 25000-frame window spans all three events instead of half a second.
rec_node_death() {
    _need_fleet cyclone
    _cap_start node-death
    _say "steady state, all three robots up"
    sleep 15
    _say "mock-robot-2: SIGTERM, a clean shutdown"
    docker stop -t 20 mock-robot-2 >/dev/null 2>&1
    sleep 20
    _say "mock-robot-3: SIGKILL, a hard kill with no goodbye"
    docker kill mock-robot-3 >/dev/null 2>&1
    sleep 30
    _ros observer "pkill -f 'topic echo'" >/dev/null 2>&1
    _cap_stop
    _say "restarting the two robots this scenario took down"
    docker start mock-robot-2 mock-robot-3 >/dev/null 2>&1
}

# Guide 5.3's broken shape: a node announcing to the discovery group and nothing ever coming
# back. The guide says in print that inducing this "did not succeed", because the fleet runs
# AllowMulticast=false with static peers and so puts nothing on 239.255.0.1 at all. Multicast
# has to be turned on first; only then is there anything to block.
#
# Dropped with tc rather than iptables, which is not installed in these containers. The drop
# is on robot-2's egress, so from the capture vantage robot-1 announces into a group nobody
# answers, which is exactly what an operator sees when a switch or an AP eats multicast.
rec_multicast_blocked() {
    _need_fleet cyclone
    local cfg=/tmp/fixture-mcast.xml i
    for i in 1 2; do
        docker exec "mock-robot-${i}" sh -c "cat > $cfg <<'EOF'
<CycloneDDS><Domain id=\"any\">
  <General><AllowMulticast>true</AllowMulticast></General>
  <Discovery><SPDPInterval>500ms</SPDPInterval></Discovery>
</Domain></CycloneDDS>
EOF"
    done
    local ri2 ip2; ri2="$(_dds_iface mock-robot-2)"; ip2="$(_dds_ip mock-robot-2)"
    [[ -n "$ip2" ]] || _die "cannot resolve mock-robot-2's own address on $DDS_SUBNET"
    FIXTURES=("${FIXTURES[@]/__MCAST_BLOCKED_IP__/$ip2}")
    docker exec mock-robot-2 sh -c "
        tc qdisc del dev $ri2 root 2>/dev/null
        tc qdisc add dev $ri2 root handle 1: prio
        tc filter add dev $ri2 parent 1: protocol ip u32 \
            match ip dst 239.255.0.1/32 action drop" >/dev/null 2>&1

    _cap_start multicast-blocked -f "ip multicast"
    _say "robot-1 and robot-2 both multicast; robot-2's announcements are dropped on egress"
    for i in 1 2; do
        _ros_bg "mock-robot-${i}" "CYCLONEDDS_URI=file://$cfg RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
            ros2 topic pub -r 2 /fixture_mcast_${i} std_msgs/msg/String '{data: hello}'"
    done
    sleep 35
    for i in 1 2; do _ros "mock-robot-${i}" "pkill -f 'topic pub'" >/dev/null 2>&1; done
    _cap_stop
    docker exec mock-robot-2 sh -c "tc qdisc del dev $ri2 root" >/dev/null 2>&1
}

# ---------------------------------------------------------------- scenarios, group C ---

# Zenoh's answer to "two nodes never find each other". rmw_zenoh dials a router rather than
# discovering peers, and the lab profiles disable multicast scouting, so a node pointed at a
# port nobody listens on retries the TCP connect forever and never gets a session.
#
# The dead endpoint is robot-1's address, not the observer's. Dialling the capture host's
# own IP sends the retries over loopback, where the fleet-bus capture never sees them: a first
# recording held 33985 frames and not one SYN. A real host on a dead port keeps the attempt on
# the wire, and each try draws a RST, which is what a wrong port or a stopped router looks like.
rec_zenoh_no_router() {
    _need_fleet zenoh
    # Written on the host and copied in, because the nested quoting in a docker-exec heredoc
    # broke this JSON silently. Note the plain path below: ZENOH_SESSION_CONFIG_URI does not
    # take a file:// URI despite the name, and flat.yml passes bare paths. With the prefix,
    # zenoh reports "No such file or directory" for a file that is plainly there, and the node
    # aborts at rcl init without putting a packet on the wire.
    local cfg=/tmp/fixture-zenoh-dead.json5
    cat > "$RAW/.zenoh-dead.json5" <<'EOF'
{
  mode: "client",
  connect: { endpoints: ["tcp/mock-robot-1:7999"] },
  scouting: { multicast: { enabled: false } },
  timestamping: { enabled: true },
}
EOF
    docker cp "$RAW/.zenoh-dead.json5" "observer:$cfg" >/dev/null 2>&1
    docker exec observer test -s "$cfg" || _die "could not place the Zenoh config"

    _cap_start zenoh-no-router
    _say "a client dialling tcp/mock-robot-1:7999, where nothing listens"
    # In a loop, because rmw_zenoh does not retry: it makes one connection attempt and the
    # node aborts at rcl init, so a single run leaves exactly one SYN on the wire. Anything
    # supervising that node restarts it, and the repeated attempt is what an operator
    # actually sees while they work out that the router address is wrong.
    _ros_bg observer "for i in 1 2 3 4 5 6 7 8; do \
        ZENOH_SESSION_CONFIG_URI=$cfg RMW_IMPLEMENTATION=rmw_zenoh_cpp \
        ros2 topic pub -r 2 /fixture_zenoh std_msgs/msg/String '{data: nobody home}' \
        >/dev/null 2>&1; sleep 3; done"
    sleep 45
    _ros observer "pkill -f 'topic pub'" >/dev/null 2>&1
    _cap_stop
}

# The router is the single point every client depends on, so taking it away mid-run is the
# most informative thing that can happen to a Zenoh capture: sessions close, then retry.
rec_zenoh_router_killed() {
    _need_fleet zenoh
    _cap_start zenoh-router-killed
    _say "steady state with the router up"
    sleep 15
    _say "killing rmw_zenohd on the observer"
    date +%s.%N > "$RAW/${CAP_NAME}.impaired-at"
    docker exec observer pkill -f rmw_zenohd >/dev/null 2>&1
    sleep 25
    _say "restarting it, so the capture also holds the reconnect"
    docker exec -d observer bash -lc \
        "source /opt/ros/jazzy/setup.bash; exec ros2 run rmw_zenoh_cpp rmw_zenohd" >/dev/null 2>&1
    sleep 20
    _cap_stop
}

# ------------------------------------------------------------------------- dispatch ---

cmd_list() {
    printf '%-24s %-8s %s\n' FIXTURE RMW DESCRIPTION
    local row; for row in "${FIXTURES[@]}"; do
        printf '%-24s %-8s %s\n' "$(echo "$row" | cut -d';' -f1)" \
            "$(echo "$row" | cut -d';' -f2)" "$(echo "$row" | cut -d';' -f5)"
    done
}

# An imported baseline just needs its source in place; trim does the rest, so it goes
# through exactly the same window-filter check as a recorded fixture.
_import_baseline() {  # _import_baseline <name>
    local row src
    for row in "${BASELINE_SRC[@]}"; do
        [[ "${row%%;*}" == "$1" ]] && src="${row#*;}"
    done
    [[ -z "${src:-}" ]] && { echo "    no source recorded for $1" >&2; return 1; }
    [[ -f "$LAB2/captures/$src" ]] || { echo "    source missing: captures/$src" >&2; return 1; }
    cp "$LAB2/captures/$src" "$RAW/${1}.pcap"
}

cmd_record() {
    local want="${1:-}"; [[ -z "$want" ]] && _die "usage: $0 record <name|all>"
    mkdir -p "$RAW"
    _check_ifb
    local names; if [[ "$want" == all ]]; then mapfile -t names < <(_fx_names); else names=("$want"); fi
    local n fn
    for n in "${names[@]}"; do
        if [[ "$(_fx_field "$n" 2)" == import ]]; then
            _say "importing $n"
            _import_baseline "$n" || { echo "FAILED $n" >&2; continue; }
            _report "$n" "$RAW" "${n}.pcap"; continue
        fi
        fn="rec_${n//-/_}"
        declare -F "$fn" >/dev/null || { echo "SKIP $n (not implemented yet)"; continue; }
        _say "recording $n"
        "$fn" || { echo "FAILED $n" >&2; continue; }
        _report "$n" "$RAW" "${n}.pcap"
    done
}

# A recording that produced the wrong thing has to say so here, not at the workshop. Both
# halves are checked: the evidence is present, and any silence the fixture claims is real.
_report() {  # _report <name> <dir> <file>
    local n="$1" dir="$2" f="$3" ok=1
    local win; win="$(_fx_field "$n" 3)"
    local absent; absent="$(_fx_field "$n" 4)"
    local total; total="$(_tshark "$dir" -r "/d/$f" -T fields -e frame.number 2>/dev/null | grep -c .)"
    local got; got="$(_count "$dir" "$f" "$win")"
    echo "    $f: ${total} frames, ${got} matching '${win}'"
    if [[ "$got" -eq 0 ]]; then
        echo "    FAIL: the window filter matches nothing, so this fixture shows nothing." >&2; ok=0
    fi
    if [[ -n "$absent" ]]; then
        local bad; bad="$(_count "$dir" "$f" "$absent")"
        if [[ "$bad" -eq 0 ]]; then
            echo "    absence confirmed: 0 matching '${absent}'"
        else
            echo "    FAIL: expected silence, got ${bad} matching '${absent}'." >&2; ok=0
        fi
    fi
    return $(( ok ? 0 : 1 ))
}

# Ceiling on the trim, not a target. The window runs from the first match to the last, so
# a fixture keeps the whole symptom rather than a slice of it: at 5000 frames qos-mismatch
# kept 1 of its 33 announcements, because 5000 frames of a fleet streaming camera data is
# about two seconds. This only bites when a fixture's matches span a very long capture.
TRIM_FRAMES=25000

# Content-directed, never a frame range picked by eye. Measured on the capture this library
# replaces: SEDP lived at frames 40260-45051 of 50k, so `editcap -r 1-4000` produced a file
# with zero SEDP in it, named for SEDP. The re-check after cutting is the whole point.
# Endpoint discovery happens once, near the start. The symptom can be most of a million
# frames later: reliable-vs-besteffort's impairment landed at frame 577134, and a trim of
# just that window carried the traffic but no announcement saying which topic was which.
#
# The head slice is content-selected rather than a frame range. A range does not work here:
# 2500 frames of two image streams is about seven hundredths of a second, so it lands long
# before the relay ever announced itself. Announcements are few, so keeping all of them
# costs almost nothing and makes every topic in the file identifiable.
#
# Only the most recent announcements, not every one in the capture. Keeping all of them made
# reliable-vs-besteffort 930 KB, most of it head, and the shrink loop could not recover
# because it only shortens the body. Cyclone re-announces periodically, so the last few
# hundred still name every topic that is live when the symptom starts.
DISCOVERY='rtps.param.topicName || zenoh.body.frame.payload.body.declare.body.declare_key_expr.wire_expr'
_cut() {  # _cut <name> <from> <to>
    local n="$1" from="$2" to="$3"
    # A fixture may name its own head filter. Cyclone announces an endpoint once, when it is
    # created, and does not repeat on a timer, so "the last N announcements before the window"
    # does not find them: reliable-vs-besteffort's two topics were announced around frame
    # 100000 and never again, half a million frames before the symptom.
    local head; head="$(_fx_field "$n" 6)"
    [[ -z "$head" ]] && head="$DISCOVERY"
    _tshark "$RAW" -r "/d/${n}.pcap" -w "/d/${n}.head.pcap" \
        -Y "($head) && frame.number < $from" >/dev/null 2>&1
    _tshark "$RAW" -r "/d/${n}.pcap" -w "/d/${n}.body.pcap" \
        -Y "frame.number >= $from && frame.number <= $to" >/dev/null 2>&1
    if [[ -s "$RAW/${n}.head.pcap" ]]; then
        docker run --rm -v "$RAW":/d --entrypoint mergecap "$IMAGE" \
            -F pcap -w "/d/${n}.trim.pcap" "/d/${n}.head.pcap" "/d/${n}.body.pcap" >/dev/null 2>&1
    else
        mv "$RAW/${n}.body.pcap" "$RAW/${n}.trim.pcap"
    fi
    rm -f "$RAW/${n}.head.pcap" "$RAW/${n}.body.pcap"
}

cmd_trim() {
    local want="${1:-}"; [[ -z "$want" ]] && _die "usage: $0 trim <name|all>"
    mkdir -p "$OUT"
    local names; if [[ "$want" == all ]]; then mapfile -t names < <(_fx_names); else names=("$want"); fi
    local n
    for n in "${names[@]}"; do
        local src="$RAW/${n}.pcap"
        [[ -f "$src" ]] || { echo "SKIP $n (not recorded)"; continue; }
        local win; win="$(_fx_field "$n" 3)"

        local before; before="$(_count "$RAW" "${n}.pcap" "$win")" || { echo "FAILED $n" >&2; continue; }
        local first last
        first=$(_tshark "$RAW" -r "/d/${n}.pcap" -Y "$win" -T fields -e frame.number 2>/dev/null | head -1)
        last=$(_tshark  "$RAW" -r "/d/${n}.pcap" -Y "$win" -T fields -e frame.number 2>/dev/null | tail -1)
        [[ -z "$first" ]] && { echo "FAILED $n: window filter matches nothing in the raw capture" >&2; continue; }
        # Start a little before the first match so the file does not open mid-exchange.
        local from=$(( first > 200 ? first - 200 : 1 ))
        # An impaired fixture starts at the impairment, not at the first match.
        if [[ -f "$RAW/${n}.impaired-at" ]]; then
            local at; at="$(cat "$RAW/${n}.impaired-at")"
            local mark
            mark=$(_tshark "$RAW" -r "/d/${n}.pcap" -Y "frame.time_epoch >= $at" \
                   -T fields -e frame.number 2>/dev/null | head -1)
            [[ -n "$mark" ]] && from=$(( mark > 200 ? mark - 200 : 1 ))
        fi
        local to="$last"
        [[ $(( to - from )) -gt "$TRIM_FRAMES" ]] && to=$(( from + TRIM_FRAMES ))

        _cut "$n" "$from" "$to"
        local after; after="$(_count "$RAW" "${n}.trim.pcap" "$win")" || { echo "FAILED $n" >&2; continue; }
        if [[ "$after" -eq 0 ]]; then
            echo "FAILED $n: the trim removed every frame the fixture is named for (${before} -> 0)" >&2
            rm -f "$RAW/${n}.trim.pcap"; continue
        fi

        # Shrink until it fits rather than warning and shipping it anyway. A dense fixture
        # keeps far more of its symptom than a reader needs: fragment-loss held 7730 fragment
        # submessages at 637 KB, against the 2706 the guide's reference capture quotes.
        local span=$(( to - from )) kb
        while :; do
            gzip -9 -c "$RAW/${n}.trim.pcap" > "$OUT/${n}.pcap.gz"
            kb=$(( ( $(stat -c%s "$OUT/${n}.pcap.gz") + 1023 ) / 1024 ))
            [[ "$kb" -le "$MAX_FILE_KB" || "$span" -le 2000 ]] && break
            span=$(( span / 2 )); to=$(( from + span ))
            _cut "$n" "$from" "$to"
            after="$(_count "$RAW" "${n}.trim.pcap" "$win")"
        done
        rm -f "$RAW/${n}.trim.pcap"
        printf '    %-24s frames %s-%s, %s of %s matches kept, %s KB\n' "$n" "$from" "$to" "$after" "$before" "$kb"
        [[ "$kb" -gt "$MAX_FILE_KB" ]] && echo "    WARNING: still over ${MAX_FILE_KB} KB at the minimum span" >&2
    done
    local total; total=$(( $(du -sk "$OUT" 2>/dev/null | cut -f1) ))
    echo "[+] fixtures/ total ${total} KB (budget ${MAX_TOTAL_KB} KB)"
    [[ "$total" -gt "$MAX_TOTAL_KB" ]] && echo "WARNING: over the total budget" >&2
    return 0
}

# The guide quotes about twenty counts off these files. Generate them rather than copying
# them by hand, so a re-record that shifts a number is caught by regenerating and diffing.
cmd_manifest() {
    local m="$OUT/manifest.tsv"
    local ifb; ifb="$(cat "$RAW/.ifb-state" 2>/dev/null || echo unknown)"
    {
        echo "# Generated by record-fixtures.sh. Do not edit by hand."
        echo "# netem impairment for this batch: ${ifb}"
        printf 'fixture\tframes\tseconds\tmatches\twindow_filter\tsha256\n'
    } > "$m"
    local n
    for n in $(_fx_names); do
        local f="$OUT/${n}.pcap.gz"; [[ -f "$f" ]] || continue
        local win; win="$(_fx_field "$n" 3)"
        local frames dur matches sha
        frames=$(_tshark "$OUT" -r "/d/${n}.pcap.gz" -T fields -e frame.number 2>/dev/null | grep -c .)
        dur=$(_tshark "$OUT" -r "/d/${n}.pcap.gz" -T fields -e frame.time_relative 2>/dev/null | tail -1)
        matches=$(_count "$OUT" "${n}.pcap.gz" "$win")
        sha=$(sha256sum "$f" | cut -c1-16)
        printf '%s\t%s\t%.1f\t%s\t%s\t%s\n' "$n" "$frames" "${dur:-0}" "$matches" "$win" "$sha" >> "$m"
    done
    column -t -s$'\t' "$m" | sed 's/^/    /'
    echo "[+] wrote $m"
}

# Re-derive every number in the manifest from the committed files. A fixture that drifted,
# or a manifest edited by hand, fails here rather than at the workshop.
cmd_verify() {
    local m="$OUT/manifest.tsv"; [[ -f "$m" ]] || _die "no manifest. Run: $0 manifest"
    local bad=0 n frames matches win rest
    while IFS=$'\t' read -r n frames _ matches win rest; do
        [[ "$n" == \#* || "$n" == fixture ]] && continue
        local f="$OUT/${n}.pcap.gz"
        [[ -f "$f" ]] || { echo "  MISSING  $n"; bad=$((bad+1)); continue; }
        local got_f got_m
        got_f=$(_tshark "$OUT" -r "/d/${n}.pcap.gz" -T fields -e frame.number 2>/dev/null | grep -c .)
        got_m=$(_count "$OUT" "${n}.pcap.gz" "$win")
        if [[ "$got_f" == "$frames" && "$got_m" == "$matches" ]]; then
            printf '  ok    %-24s %s frames, %s matches\n' "$n" "$got_f" "$got_m"
        else
            printf '  FAIL  %-24s manifest says %s/%s, file has %s/%s\n' "$n" "$frames" "$matches" "$got_f" "$got_m"
            bad=$((bad+1))
        fi
    done < "$m"
    [[ "$bad" -eq 0 ]] && echo "[+] every fixture matches the manifest" || { echo "[!] ${bad} mismatched" >&2; return 1; }
}

case "${1:-}" in
    list)     cmd_list ;;
    record)   shift; cmd_record "$@" ;;
    trim)     shift; cmd_trim "$@" ;;
    manifest) cmd_manifest ;;
    verify)   cmd_verify ;;
    *) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
