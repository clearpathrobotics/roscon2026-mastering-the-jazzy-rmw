#!/usr/bin/env bash
# gen_topology.sh <star|flat|routed> [N] [rmw] - the ONE topology generator.
#
# Emits a self-contained compose file at docker/compose/<topology>.yml whose
# robots/observer reuse the canonical definitions (robot.yml, observer.yml) via
# `extends`, parameterized by N (link count) and RMW. Every topology is
# generated the same way; there are no hand-maintained topology compose files.
#
#   star   3 pinned robots + observer on a shared bus + per-robot spokes
#   flat   1 scalable robot + observer on a single bridge (bring up --scale N)
#   routed N robots + observer + wifi-ap, each on its own /24 behind the AP
#
# All robots run docker/scripts/run_mock_robot.sh and the observer runs
# docker/scripts/run_observer.sh; behaviour is env-selected (see those scripts).
#
# TODO: relocate the remaining container leaf scripts (ap_entrypoint.sh, pilot.py,
# play_bag.sh, fleet_map.py, and the routed_common/*_entrypoint.sh helpers) from
# lab3-stress-testing/scripts/ into docker/scripts/ (they're mounted at /scripts/lab3
# for now), and update their external references. Deferred: needs a running ROS
# stack to validate, so it's out of scope for the compose-generation change.
#
# Usage (from anywhere):
#   scripts/gen_topology.sh star
#   scripts/gen_topology.sh flat  6
#   scripts/gen_topology.sh routed 15 rmw_zenoh_cpp
#
# PARTIAL_GEN=1 emits address placeholders (MOCK_ROBOT_<k>_IP, OBSERVER_IP,
# OBSERVER_IP_BR<k>) into the RMW configs instead of real IPs (see below).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"      # <repo>/scripts
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"                       # <repo>
DOCKER_ROOT="$REPO_ROOT/docker"
COMPOSE_DIR="$DOCKER_ROOT/compose"
LAB3_SCRIPTS="$REPO_ROOT/lab3-stress-testing/scripts"
TEMPLATES_DIR="$LAB3_SCRIPTS/templates"

TOPO="${1:?usage: gen_topology.sh <star|flat|routed> [N] [rmw]}"
N="${2:-}"
RMW="${3:-rmw_cyclonedds_cpp}"
NMAX=25

# Normalize friendly RMW names (and capture labels) to the rmw_*_cpp impl string
# that ROS expects, so 'fast' never leaks through as RMW_IMPLEMENTATION=fast.
case "$RMW" in
    cyclone|cyclonedds|rmw_cyclonedds_cpp)       RMW="rmw_cyclonedds_cpp" ;;
    fast|fastdds|fastrtps|rmw_fastrtps_cpp)      RMW="rmw_fastrtps_cpp" ;;
    zenoh|rmw_zenoh_cpp)                         RMW="rmw_zenoh_cpp" ;;
    *) echo "rmw must be cyclone|fastdds|zenoh (or an rmw_*_cpp impl), got '$RMW'" >&2; exit 2 ;;
esac
case "$RMW" in
    rmw_cyclonedds_cpp) RMW_DIRNAME=cyclone ;;
    rmw_fastrtps_cpp)   RMW_DIRNAME=fast ;;
    rmw_zenoh_cpp)      RMW_DIRNAME=zenoh ;;
esac

# --rmw-directory (scripts/workshop up): use a pre-built config directory for the
# selected RMW instead of generating it - the caller's fixture, not ours. Only the
# selected RMW's directory is affected; the other two still generate normally
# (only the RMW named by RMW_IMPLEMENTATION is ever active at runtime). Only the
# topology/RMW combinations an exercise actually needs are wired up below
# (flat+cyclone for Lab 3 Ex1's mixed-config fleet, routed+zenoh for Ex4's
# gossip/multicast A/B) - extend the per-topology generators as new needs arise.
RMW_OVERRIDE_DIR="${RMW_OVERRIDE_DIR:-}"
if [[ -n "$RMW_OVERRIDE_DIR" ]]; then
    RMW_OVERRIDE_DIR="$(cd "$RMW_OVERRIDE_DIR" 2>/dev/null && pwd)" || {
        echo "--rmw-directory: '$RMW_OVERRIDE_DIR' does not exist" >&2; exit 2; }
    case "$TOPO:$RMW_DIRNAME" in
        star:cyclone|star:fast|star:zenoh|flat:cyclone|flat:fast|flat:zenoh|routed:cyclone|routed:fast|routed:zenoh) ;;
        *) echo "--rmw-directory is not wired up for $TOPO+$RMW_DIRNAME yet" >&2
           exit 2 ;;
    esac
fi

# override_active <rmw-dirname>  - true when an override applies to the RMW a
# generator is about to write config for.
override_active() { [[ -n "$RMW_OVERRIDE_DIR" && "$RMW_DIRNAME" == "$1" ]]; }

# install_rmw_override <dest-dir> <required-file>...  - replace dest-dir's
# contents with the override directory's files, failing loudly if any required
# file is missing rather than silently falling back to generated config.
install_rmw_override() {
    local dest="$1"; shift
    local f
    for f in "$@"; do
        [[ -f "$RMW_OVERRIDE_DIR/$f" ]] || {
            echo "--rmw-directory: missing required file '$f' in $RMW_OVERRIDE_DIR" >&2
            exit 2
        }
    done
    rm -f "${dest:?}"/*
    for f in "$@"; do cp "$RMW_OVERRIDE_DIR/$f" "$dest/$f"; done
}

# Per-topology default link count (kept as-is); the max is 25 everywhere.
case "$TOPO" in
    star)   N="${N:-3}" ;;
    flat)   N="${N:-3}" ;;
    routed) N="${N:-15}" ;;
    *) echo "topology must be star|flat|routed, got '$TOPO'" >&2; exit 2 ;;
esac
[[ "$N" =~ ^[0-9]+$ && "$N" -ge 1 && "$N" -le "$NMAX" ]] || { echo "N must be 1..$NMAX" >&2; exit 2; }

CONSOLE_IDX=100   # routed: stable observer subnet (172.40.100.0/24), independent of N

# --partial-gen (scripts/workshop up --partial-gen, or PARTIAL_GEN=1): emit editable
# address placeholders (MOCK_ROBOT_<k>_IP, OBSERVER_IP, OBSERVER_IP_BR<k>) into the
# RMW configs instead of real IPs, so attendees fill them in by hand. The same
# address always maps to the same token wherever it appears; compose files keep
# real IPs so the correct values are still discoverable. flat has no per-node
# addresses (pure multicast), so --partial-gen is a no-op there.
PARTIAL_GEN="${PARTIAL_GEN:-}"

# addr <real-ip> <placeholder> - the placeholder under --partial-gen, else the IP.
addr() { if [[ -n "$PARTIAL_GEN" ]]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }

# ---------------------------------------------------------------------------
# Per-node RMW config writers. Each topology generates one config per RMW per
# container under docker/rmw_configuration/<topo>/{cyclone,fast,zenoh}/.
# ---------------------------------------------------------------------------
# write_cyclone <file> <allow_multicast true|false> <iface ""|auto|IP> <peers_xml>
write_cyclone() {
    local f="$1" mc="$2" iface="$3" peers="$4"
    {
        echo '<CycloneDDS>'
        echo '  <Domain id="any">'
        echo '    <General>'
        echo "      <AllowMulticast>$mc</AllowMulticast>"
        if [[ "$iface" == "auto" ]]; then
            echo '      <Interfaces>'
            echo '        <NetworkInterface autodetermine="true"/>'
            echo '      </Interfaces>'
        elif [[ -n "$iface" ]]; then
            echo '      <Interfaces>'
            local _ip; IFS=',' read -ra _ifaces <<< "$iface"
            for _ip in "${_ifaces[@]}"; do
                echo "        <NetworkInterface address=\"$_ip\"/>"
            done
            echo '      </Interfaces>'
        fi
        echo '    </General>'
        echo '    <Discovery>'
        echo '      <ParticipantIndex>auto</ParticipantIndex>'
        echo '      <MaxAutoParticipantIndex>120</MaxAutoParticipantIndex>'
        if [[ -n "$peers" ]]; then
            echo '      <Peers>'
            printf '%s\n' "$peers"
            echo '      </Peers>'
        fi
        echo '    </Discovery>'
        echo '  </Domain>'
        echo '</CycloneDDS>'
    } > "$f"
}

# write_fast <file> <iface ""|IP(whitelist)> <peers_locators "">
write_fast() {
    local f="$1" iface="$2" peers="$3"
    {
        echo '<?xml version="1.0" encoding="UTF-8" ?>'
        echo '<profiles xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">'
        if [[ -n "$iface" ]]; then
            echo '  <transport_descriptors>'
            echo '    <transport_descriptor>'
            echo '      <transport_id>udp_pin</transport_id>'
            echo '      <type>UDPv4</type>'
            echo '      <interfaceWhiteList>'
            local _ip; IFS=',' read -ra _ifaces <<< "$iface"
            for _ip in "${_ifaces[@]}"; do
                echo "        <address>$_ip</address>"
            done
            echo '      </interfaceWhiteList>'
            echo '    </transport_descriptor>'
            echo '  </transport_descriptors>'
        fi
        echo '  <participant profile_name="default_participant" is_default_profile="true">'
        echo '    <rtps>'
        if [[ -n "$iface" ]]; then
            echo '      <userTransports>'
            echo '        <transport_id>udp_pin</transport_id>'
            echo '      </userTransports>'
            echo '      <useBuiltinTransports>false</useBuiltinTransports>'
        fi
        echo '      <builtin>'
        if [[ -n "$peers" ]]; then
            echo '        <initialPeersList>'
            printf '%s\n' "$peers"
            echo '        </initialPeersList>'
        fi
        echo '        <discovery_config>'
        echo '          <discoveryProtocol>SIMPLE</discoveryProtocol>'
        echo '          <EDP>SIMPLE</EDP>'
        echo '          <leaseDuration>'
        echo '            <sec>DURATION_INFINITY</sec>'
        echo '          </leaseDuration>'
        echo '        </discovery_config>'
        echo '      </builtin>'
        echo '    </rtps>'
        echo '  </participant>'
        echo '</profiles>'
    } > "$f"
}

# write_zenoh <file> <mode peer|client> <ifaces ""|IP[,IP...]> <connect ""|ep[,ep...]> [multicast true|false] [listen_port]
# ifaces drive the tcp listen endpoints (one per IP). In peer mode a non-empty
# connect makes this node dial the hub explicitly (used by the star spokes, where
# multicast is off because each spoke is its own /24 with no shared L2).
write_zenoh() {
    local f="$1" mode="$2" ifaces="$3" connect="$4" multicast="${5:-true}" lport="${6:-0}"
    local ip ep first
    {
        echo '{'
        echo "  mode: \"$mode\","
        if [[ "$mode" == "client" ]]; then
            echo "  connect: { endpoints: [\"$connect\"] },"
            echo '  timestamping: { enabled: true },'
        else
            echo '  scouting: {'
            echo '    multicast: {'
            echo "      enabled: $multicast,"
            if [[ "$multicast" == "true" && -n "$ifaces" && "$ifaces" != *,* ]]; then
                echo "      interface: \"$ifaces\","
            fi
            echo '      autoconnect: { router: ["router", "peer"], peer: ["router", "peer"] },'
            echo '    },'
            echo '    gossip: {'
            echo '      enabled: true,'
            echo '      autoconnect: { router: ["router", "peer"], peer: ["router", "peer"] },'
            echo '    },'
            echo '  },'
            if [[ -n "$connect" ]]; then
                first=1; printf '  connect: { endpoints: ['
                IFS=',' read -ra _eps <<< "$connect"
                for ep in "${_eps[@]}"; do
                    [[ -n "$first" ]] || printf ', '; printf '"%s"' "$ep"; first=""
                done
                printf '] },\n'
            fi
            if [[ -n "$ifaces" ]]; then
                first=1; printf '  listen: { endpoints: ['
                IFS=',' read -ra _ifs <<< "$ifaces"
                for ip in "${_ifs[@]}"; do
                    [[ -n "$first" ]] || printf ', '; printf '"tcp/%s:%s"' "$ip" "$lport"; first=""
                done
                printf '] },\n'
            fi
        fi
        echo '  transport: { shared_memory: { enabled: false } },'
        echo '}'
    } > "$f"
}

# write_zenoh_router <file> <connect ""|ep[,ep...]> [multicast true|false]
# rmw_zenohd config: a real per-robot router its own nodes are clients of, so the
# robot keeps working even if the uplink (observer/AP) drops. Listens on all
# interfaces so local clients (tcp/localhost:7447) and the observer can attach.
write_zenoh_router() {
    local f="$1" connect="$2" multicast="${3:-true}"
    local ep first
    {
        echo '{'
        echo '  mode: "router",'
        echo '  listen: { endpoints: ["tcp/0.0.0.0:7447"] },'
        echo '  scouting: {'
        echo "    multicast: { enabled: $multicast, autoconnect: { router: [\"router\", \"peer\"], peer: [\"router\", \"peer\"] } },"
        echo '    gossip: { enabled: true, autoconnect: { router: ["router", "peer"], peer: ["router", "peer"] } },'
        echo '  },'
        if [[ -n "$connect" ]]; then
            first=1; printf '  connect: { endpoints: ['
            IFS=',' read -ra _eps <<< "$connect"
            for ep in "${_eps[@]}"; do
                [[ -n "$first" ]] || printf ', '; printf '"%s"' "$ep"; first=""
            done
            printf '] },\n'
        fi
        echo '  transport: { shared_memory: { enabled: false } },'
        echo '}'
    } > "$f"
}

# ---------------------------------------------------------------------------
# star: shared bus (mock-b0) + one private spoke (mock-b{k}) per robot.
# ---------------------------------------------------------------------------
gen_star() {
    local out="$COMPOSE_DIR/star.yml" rdir="$DOCKER_ROOT/rmw_configuration/star" k model mecanum robot_ip obs_ip obs_ifaces obs_peers obs_zrouters
    rm -rf "$rdir"
    mkdir -p "$rdir/cyclone" "$rdir/fast" "$rdir/zenoh"

    # Per-node configs: a true hub-and-spoke. There is NO shared bus - each robot
    # sits alone on its private /24 spoke (mock-b{k}) with the observer, so robots
    # are mutually isolated at the network layer. Multicast is off; the observer
    # binds every spoke interface and peers each robot on its spoke, and each robot
    # peers only the observer's address on that same spoke.
    obs_ifaces=""; obs_peers=""; obs_zrouters=""
    for k in $(seq 1 "$N"); do
        obs_ifaces+="$(addr "172.30.$((10 + k)).20" "OBSERVER_IP_BR$k"),"
        obs_peers+="        <Peer address=\"$(addr "172.30.$((10 + k)).$((10 + k))" "MOCK_ROBOT_${k}_IP")\"/>"$'\n'
        obs_zrouters+="tcp/$(addr "172.30.$((10 + k)).$((10 + k))" "MOCK_ROBOT_${k}_IP"):7447,"
    done
    obs_ifaces="${obs_ifaces%,}"
    obs_zrouters="${obs_zrouters%,}"
    # Per-node full-set override (like routed): for the active RMW, skip the generated
    # writes and install the fixture's numbered files after the loop below.
    local cyc_override_files=(observer.xml) fast_override_files=(observer.xml) zenoh_override_files=(observer.json5)
    override_active cyclone || write_cyclone "$rdir/cyclone/observer.xml" false "$obs_ifaces" \
        "        <Peer address=\"localhost\"/>"$'\n'"${obs_peers%$'\n'}"
    override_active fast || write_fast  "$rdir/fast/observer.xml" "$obs_ifaces" ""
    # Spokes are isolated with multicast off, so the observer explicitly dials every
    # robot's local rmw_zenohd router to discover the whole fleet.
    override_active zenoh || write_zenoh "$rdir/zenoh/observer.json5" peer "$obs_ifaces" "$obs_zrouters" false 7447
    for k in $(seq 1 "$N"); do
        robot_ip="$(addr "172.30.$((10 + k)).$((10 + k))" "MOCK_ROBOT_${k}_IP")"
        obs_ip="$(addr "172.30.$((10 + k)).20" "OBSERVER_IP_BR$k")"
        override_active cyclone || write_cyclone "$rdir/cyclone/mock-robot-$k.xml" false "$robot_ip" \
            "        <Peer address=\"localhost\"/>"$'\n'"        <Peer address=\"$obs_ip\"/>"
        override_active fast || write_fast  "$rdir/fast/mock-robot-$k.xml" "$robot_ip" ""
        # Robot nodes are clients of the robot's OWN local router; the observer
        # (configured separately) dials each robot router on its spoke IP.
        if ! override_active zenoh; then
            write_zenoh        "$rdir/zenoh/mock-robot-$k.json5" client "" "tcp/localhost:7447"
            write_zenoh_router "$rdir/zenoh/mock-robot-$k-router.json5" "" false
        fi
        cyc_override_files+=("mock-robot-$k.xml")
        fast_override_files+=("mock-robot-$k.xml")
        zenoh_override_files+=("mock-robot-$k.json5" "mock-robot-$k-router.json5")
    done
    if override_active cyclone; then install_rmw_override "$rdir/cyclone" "${cyc_override_files[@]}"; fi
    if override_active fast;    then install_rmw_override "$rdir/fast"    "${fast_override_files[@]}"; fi
    if override_active zenoh;   then install_rmw_override "$rdir/zenoh"   "${zenoh_override_files[@]}"; fi

    {
    cat <<EOF
# GENERATED by scripts/gen_topology.sh star $N $RMW - do not edit by hand.
# Star topology: $N robots + observer in a true hub-and-spoke. Each robot shares a
# private spoke (mock-b{k}, its own /24) with the observer only; there is NO shared
# bus, so robots are mutually isolated. Bring up:
#   docker compose -f docker/compose/star.yml --profile mock up -d
name: roscon2026-jazzy-rmw

services:
EOF
    for k in $(seq 1 "$N"); do
        case "$k" in
            1) model=a300; mecanum=false ;;
            2) model=r100; mecanum=true  ;;
            3) model=j100; mecanum=false ;;
            *) model=a300; mecanum=false ;;
        esac
        cat <<EOF
  mock-robot-$k:
    extends: {file: robot.yml, service: mock-robot}
    container_name: mock-robot-$k
    hostname: mock-robot-$k
    profiles: [mock]
    networks:
      mock-b$k: {ipv4_address: 172.30.$((10 + k)).$((10 + k))}
    environment:
      ROS_DOMAIN_ID: "\${ROS_DOMAIN_ID:-25}"
      RMW_IMPLEMENTATION: \${RMW_IMPLEMENTATION:-$RMW}
      CYCLONEDDS_URI: file:///rmw_configuration/star/cyclone/mock-robot-$k.xml
      FASTRTPS_DEFAULT_PROFILES_FILE: /rmw_configuration/star/fast/mock-robot-$k.xml
      ZENOH_SESSION_CONFIG_URI: /rmw_configuration/star/zenoh/mock-robot-$k.json5
      ZENOH_ROUTER_CONFIG_URI: /rmw_configuration/star/zenoh/mock-robot-$k-router.json5
      MOCK_BUILD: "\${MOCK_BUILD:-false}"
      ROBOT_NS: robot_$k
      MOCK_FRAME_ID: robot$k
      MOCK_ROBOT_MODEL: \${MOCK_ROBOT_${k}_MODEL:-\${MOCK_ROBOT_MODEL:-$model}}
      MOCK_SENSOR_TOPICS: \${MOCK_SENSOR_TOPICS:-/camera/image_raw,/scan}
      MOCK_SENSOR_COUNT: \${MOCK_SENSOR_COUNT:-1}
      HALF_SCAN: "\${HALF_SCAN:-0}"
      MOCK_USE_MECANUM: \${MOCK_ROBOT_${k}_USE_MECANUM:-$mecanum}
      MOCK_USE_NAV2: \${MOCK_ROBOT_${k}_USE_NAV2:-\${MOCK_USE_NAV2:-false}}
      MOCK_NAV2_SLAM: \${MOCK_ROBOT_${k}_NAV2_SLAM:-\${MOCK_NAV2_SLAM:-true}}
      MOCK_RUN_PILOT: "\${MOCK_RUN_PILOT:-true}"
      WORKLOAD: \${WORKLOAD:-mock}
    command: ["bash", "/scripts/run_mock_robot.sh"]
EOF
    done
    # Observer sits on every spoke (one leg per robot), the hub of the star.
    cat <<EOF
  observer:
    extends: {file: observer.yml, service: observer}
    container_name: observer
    hostname: observer
    profiles: [mock]
    networks:
EOF
    for k in $(seq 1 "$N"); do
        echo "      mock-b$k: {ipv4_address: 172.30.$((10 + k)).20}"
    done
    cat <<EOF
    environment:
      ROS_DOMAIN_ID: "\${ROS_DOMAIN_ID:-25}"
      RMW_IMPLEMENTATION: \${OBSERVER_RMW_IMPLEMENTATION:-$RMW}
      CYCLONEDDS_URI: \${OBSERVER_CYCLONEDDS_URI:-file:///rmw_configuration/star/cyclone/observer.xml}
      FASTRTPS_DEFAULT_PROFILES_FILE: \${OBSERVER_FASTRTPS_DEFAULT_PROFILES_FILE:-/rmw_configuration/star/fast/observer.xml}
      ZENOH_SESSION_CONFIG_URI: \${OBSERVER_ZENOH_SESSION_CONFIG_URI:-/rmw_configuration/star/zenoh/observer.json5}
      MOCK_BUILD: "\${MOCK_BUILD:-false}"
    command: ["bash", "/scripts/run_observer.sh"]

networks:
EOF
    for k in $(seq 1 "$N"); do
        cat <<EOF
  mock-b$k:
    driver: bridge
    ipam: {config: [{subnet: 172.30.$((10 + k)).0/24}]}
EOF
    done
    } > "$out"
    echo "generated $out (star, $N robots)"
}

# ---------------------------------------------------------------------------
# flat: N robots + observer on a single bridge (flat-net), plain multicast.
# Robots are enumerated (mock-robot-1..N) so each gets a stable ROBOT_NS.
# ---------------------------------------------------------------------------
gen_flat() {
    local out="$COMPOSE_DIR/flat.yml" rdir="$DOCKER_ROOT/rmw_configuration/flat" k node
    mkdir -p "$rdir/cyclone" "$rdir/fast" "$rdir/zenoh"

    # Cyclone: normally every robot shares one file (plain multicast, no per-robot
    # distinction). Lab 3 Ex1's mixed-config fleet needs some robots on a different
    # config than others, which a shared file can't express - when overridden, every
    # robot gets its own numbered file from the caller's fixture instead.
    local flat_cyclone_per_robot=false
    if override_active cyclone; then
        flat_cyclone_per_robot=true
        local files=(observer.xml) k
        for k in $(seq 1 "$N"); do files+=("mock-robot-$k.xml"); done
        install_rmw_override "$rdir/cyclone" "${files[@]}"
    else
        write_cyclone "$rdir/cyclone/mock-robot.xml" true "" ""
        write_cyclone "$rdir/cyclone/observer.xml" true "" ""
    fi
    # Fast/Zenoh share one config across all scaled robots (no per-robot distinction on
    # the flat bus), so an override replaces those shared files directly - the compose
    # env already points every robot at them.
    if override_active fast; then
        install_rmw_override "$rdir/fast" mock-robot.xml observer.xml
    else
        write_fast "$rdir/fast/mock-robot.xml" "" ""
        write_fast "$rdir/fast/observer.xml" "" ""
    fi
    # Each robot is a client of its OWN local rmw_zenohd router (multicast lets the
    # routers find each other on the flat bus); the observer keeps its peer session.
    if override_active zenoh; then
        install_rmw_override "$rdir/zenoh" mock-robot.json5 mock-robot-router.json5 observer.json5
    else
        write_zenoh        "$rdir/zenoh/mock-robot.json5" client "" "tcp/localhost:7447"
        write_zenoh_router "$rdir/zenoh/mock-robot-router.json5" "" true
        write_zenoh        "$rdir/zenoh/observer.json5" peer "" ""
    fi

    {
    cat <<EOF
# GENERATED by scripts/gen_topology.sh flat $N $RMW - do not edit by hand.
# Flat topology: $N robots + observer on a single bridge (flat-net), plain
# multicast discovery. Bring up:
#   docker compose -f docker/compose/flat.yml --profile mock up -d
name: roscon2026-jazzy-rmw

services:
EOF
    local cyclone_uri
    for k in $(seq 1 "$N"); do
        if [[ "$flat_cyclone_per_robot" == true ]]; then
            cyclone_uri="file:///rmw_configuration/flat/cyclone/mock-robot-$k.xml"
        else
            cyclone_uri="file:///rmw_configuration/flat/cyclone/mock-robot.xml"
        fi
        cat <<EOF
  mock-robot-$k:
    extends: {file: robot.yml, service: mock-robot}
    container_name: mock-robot-$k
    hostname: mock-robot-$k
    profiles: [mock]
    networks: [flat-net]
    environment:
      ROS_DOMAIN_ID: "\${ROS_DOMAIN_ID:-25}"
      RMW_IMPLEMENTATION: \${RMW_IMPLEMENTATION:-$RMW}
      CYCLONEDDS_URI: $cyclone_uri
      FASTRTPS_DEFAULT_PROFILES_FILE: /rmw_configuration/flat/fast/mock-robot.xml
      ZENOH_SESSION_CONFIG_URI: /rmw_configuration/flat/zenoh/mock-robot.json5
      ZENOH_ROUTER_CONFIG_URI: /rmw_configuration/flat/zenoh/mock-robot-router.json5
      MOCK_BUILD: "\${MOCK_BUILD:-false}"
      ROBOT_NS: robot_$k
      MOCK_ROBOT_MODEL: \${MOCK_ROBOT_${k}_MODEL:-\${MOCK_ROBOT_MODEL:-\${DEFAULT_GROUP_MODEL:-a300}}}
      MOCK_SENSOR_TOPICS: \${MOCK_SENSOR_TOPICS:-/camera/image_raw,/scan}
      MOCK_SENSOR_COUNT: \${MOCK_SENSOR_COUNT:-1}
      HALF_SCAN: "\${HALF_SCAN:-0}"
      MOCK_USE_MECANUM: \${DEFAULT_GROUP_USE_MECANUM:-false}
      MOCK_RUN_PILOT: "\${MOCK_RUN_PILOT:-true}"
      MOCK_START_DELAY: "\${MOCK_START_DELAY:-0}"
      WORKLOAD: \${WORKLOAD:-mock}
    command: ["bash", "/scripts/run_mock_robot.sh"]
EOF
    done
    cat <<EOF
  observer:
    extends: {file: observer.yml, service: observer}
    container_name: observer
    hostname: observer
    profiles: [mock]
    networks: [flat-net]
    environment:
      ROS_DOMAIN_ID: "\${ROS_DOMAIN_ID:-25}"
      RMW_IMPLEMENTATION: \${OBSERVER_RMW_IMPLEMENTATION:-$RMW}
      CYCLONEDDS_URI: \${OBSERVER_CYCLONEDDS_URI:-file:///rmw_configuration/flat/cyclone/observer.xml}
      FASTRTPS_DEFAULT_PROFILES_FILE: \${OBSERVER_FASTRTPS_DEFAULT_PROFILES_FILE:-/rmw_configuration/flat/fast/observer.xml}
      ZENOH_SESSION_CONFIG_URI: \${OBSERVER_ZENOH_SESSION_CONFIG_URI:-/rmw_configuration/flat/zenoh/observer.json5}
      MOCK_BUILD: "\${MOCK_BUILD:-false}"
    command: ["bash", "/scripts/run_observer.sh"]

networks:
  flat-net:
    driver: bridge
    ipam: {config: [{subnet: 172.31.0.0/24}]}
EOF
    } > "$out"
    echo "generated $out (flat, $N robots)"
}

# ---------------------------------------------------------------------------
# routed: every robot + observer on its own /24, the wifi-ap the only path
# between them. Also generates per-node unicast RMW configs (DDS peer lists +
# Zenoh router-client), since multicast can't cross the AP.
# ---------------------------------------------------------------------------
all_robot_subnets() { local k; for k in $(seq 1 "$N"); do printf '172.40.%s.0/24 ' "$k"; done; }

gen_routed() {
    local out="$COMPOSE_DIR/routed.yml" rdir="$DOCKER_ROOT/rmw_configuration/routed"
    local k remote node cyc_peers fast_peers obs_zrouters
    mkdir -p "$rdir/cyclone" "$rdir/fast" "$rdir/zenoh"

    # Unicast peer list = every robot (.10 on its /24) + the observer; identical
    # for every node (self-listing is a harmless no-op). Zenoh = router client.
    cyc_peers="        <Peer address=\"localhost\"/>"$'\n'
    fast_peers=""
    for k in $(seq 1 "$N"); do
        cyc_peers+="        <Peer address=\"$(addr "172.40.$k.10" "MOCK_ROBOT_${k}_IP")\"/>   <!-- mock-robot-$k -->"$'\n'
        fast_peers+="          <locator><udpv4><address>$(addr "172.40.$k.10" "MOCK_ROBOT_${k}_IP")</address></udpv4></locator>  <!-- mock-robot-$k -->"$'\n'
    done
    cyc_peers+="        <Peer address=\"$(addr "172.40.$CONSOLE_IDX.10" "OBSERVER_IP")\"/>   <!-- observer -->"
    fast_peers+="          <locator><udpv4><address>$(addr "172.40.$CONSOLE_IDX.10" "OBSERVER_IP")</address></udpv4></locator>  <!-- observer -->"
    obs_zrouters=""
    local zenoh_override_files=(observer.json5)
    local cyc_override_files=(observer.xml) fast_override_files=(observer.xml)
    for k in $(seq 1 "$N"); do
        node="mock-robot-$k"
        # Each RMW's per-robot file is generated unless a --rmw-directory override for
        # that RMW is active, in which case install_rmw_override drops the fixture's file
        # in instead. The numbered per-robot naming already matches what a fixture must
        # provide (e.g. Lab 3 Ex4's zenoh gossip/multicast A/B fixture).
        override_active cyclone || write_cyclone "$rdir/cyclone/$node.xml" false auto "$cyc_peers"
        override_active fast    || write_fast    "$rdir/fast/$node.xml" "" "$fast_peers"
        cyc_override_files+=("$node.xml")
        fast_override_files+=("$node.xml")
        # Robot nodes are clients of the robot's OWN router; the router just listens
        # (the observer dials it across the AP), so the robot keeps running locally
        # even if the AP hop drops - no dependency on a hub daemon on the wifi-ap.
        if ! override_active zenoh; then
            write_zenoh        "$rdir/zenoh/$node.json5" client "" "tcp/localhost:7447"
            write_zenoh_router "$rdir/zenoh/$node-router.json5" "" false
        fi
        zenoh_override_files+=("$node.json5" "$node-router.json5")
        obs_zrouters+="tcp/$(addr "172.40.$k.10" "MOCK_ROBOT_${k}_IP"):7447,"
    done
    obs_zrouters="${obs_zrouters%,}"
    # Observer reaches every robot's router across the AP (L3), discovering the
    # whole fleet without depending on a Zenoh hub daemon on the wifi-ap.
    if override_active cyclone; then
        install_rmw_override "$rdir/cyclone" "${cyc_override_files[@]}"
    else
        write_cyclone "$rdir/cyclone/observer.xml" false auto "$cyc_peers"
    fi
    if override_active fast; then
        install_rmw_override "$rdir/fast" "${fast_override_files[@]}"
    else
        write_fast "$rdir/fast/observer.xml" "" "$fast_peers"
    fi
    if override_active zenoh; then
        install_rmw_override "$rdir/zenoh" "${zenoh_override_files[@]}"
    else
        write_zenoh "$rdir/zenoh/observer.json5" peer "" "$obs_zrouters" false
    fi

    {
    cat <<EOF
# GENERATED by scripts/gen_topology.sh routed $N $RMW - do not edit by hand.
# Routed shared-medium topology: every robot and the observer on its own /24, the
# wifi-ap the only path between them, so ALL peer traffic crosses the shaped AP.
# Shape it with lab3-stress-testing/scripts/ap_shape.sh. Bring up:
#   docker compose -f docker/compose/routed.yml --profile routed up -d
name: roscon2026-jazzy-rmw

services:
  wifi-ap:
    extends: {file: robot.yml, service: mock-robot}
    container_name: wifi-ap
    hostname: wifi-ap
    profiles: [routed]
    sysctls:
      - net.ipv4.ip_forward=1
    environment:
      ROS_DOMAIN_ID: "\${ROS_DOMAIN_ID:-25}"
      RMW_IMPLEMENTATION: \${RMW_IMPLEMENTATION:-$RMW}
    networks:
EOF
    for k in $(seq 1 "$N"); do
        echo "      mock-robot-$k-net: {ipv4_address: 172.40.$k.2}"
    done
    echo "      observer-net: {ipv4_address: 172.40.$CONSOLE_IDX.2}"
    echo '    command: ["bash", "/scripts/lab3/ap_entrypoint.sh"]'

    for k in $(seq 1 "$N"); do
        remote="$(all_robot_subnets | sed "s#172.40.$k.0/24 ##") 172.40.$CONSOLE_IDX.0/24"
        remote="$(echo "$remote" | xargs)"
        cat <<EOF
  mock-robot-$k:
    extends: {file: robot.yml, service: mock-robot}
    container_name: mock-robot-$k
    hostname: mock-robot-$k
    profiles: [routed]
    networks:
      mock-robot-$k-net: {ipv4_address: 172.40.$k.10}
    environment:
      ROS_DOMAIN_ID: "\${ROS_DOMAIN_ID:-25}"
      RMW_IMPLEMENTATION: \${RMW_IMPLEMENTATION:-$RMW}
      CYCLONEDDS_URI: file:///rmw_configuration/routed/cyclone/mock-robot-$k.xml
      FASTRTPS_DEFAULT_PROFILES_FILE: /rmw_configuration/routed/fast/mock-robot-$k.xml
      ZENOH_SESSION_CONFIG_URI: /rmw_configuration/routed/zenoh/mock-robot-$k.json5
      ZENOH_ROUTER_CONFIG_URI: /rmw_configuration/routed/zenoh/mock-robot-$k-router.json5
      MOCK_BUILD: "\${MOCK_BUILD:-false}"
      AP_GW: "172.40.$k.2"
      REMOTE_SUBNETS: "$remote"
      ROBOT_NS: robot_$k
      WORKLOAD: \${WORKLOAD:-mock}
      MOCK_RUN_PILOT: "\${MOCK_RUN_PILOT:-true}"
      MOCK_ROBOT_MODEL: \${MOCK_ROBOT_${k}_MODEL:-\${MOCK_ROBOT_MODEL:-a300}}
      MOCK_PILOT_RATE: \${MOCK_PILOT_RATE:-10}
      MOCK_SENSOR_QOS_FILE: \${MOCK_SENSOR_QOS_FILE:-/scripts/lab3/qos/sensor_qos.yaml}
      # Nothing subscribes to the camera by default and compositing it is the largest
      # CPU cost per robot; set MOCK_SENSOR_COUNT=1 for the saturation exercise.
      MOCK_SENSOR_COUNT: \${MOCK_SENSOR_COUNT:-0}
      HALF_SCAN: "\${HALF_SCAN:-0}"
    command: ["bash", "/scripts/run_mock_robot.sh"]
EOF
    done

    cat <<EOF
  observer:
    extends: {file: observer.yml, service: observer}
    container_name: observer
    hostname: observer
    profiles: [routed]
    networks:
      observer-net: {ipv4_address: 172.40.$CONSOLE_IDX.10}
    environment:
      ROS_DOMAIN_ID: "\${ROS_DOMAIN_ID:-25}"
      RMW_IMPLEMENTATION: \${OBSERVER_RMW_IMPLEMENTATION:-$RMW}
      CYCLONEDDS_URI: \${OBSERVER_CYCLONEDDS_URI:-file:///rmw_configuration/routed/cyclone/observer.xml}
      FASTRTPS_DEFAULT_PROFILES_FILE: \${OBSERVER_FASTRTPS_DEFAULT_PROFILES_FILE:-/rmw_configuration/routed/fast/observer.xml}
      ZENOH_SESSION_CONFIG_URI: \${OBSERVER_ZENOH_SESSION_CONFIG_URI:-/rmw_configuration/routed/zenoh/observer.json5}
      MOCK_BUILD: "\${MOCK_BUILD:-false}"
      AP_GW: "172.40.$CONSOLE_IDX.2"
      REMOTE_SUBNETS: "$(all_robot_subnets | xargs)"
      FLEET_MAP: "true"
      MOCK_ROBOT_MODEL: \${MOCK_ROBOT_MODEL:-a300}
    command: ["bash", "/scripts/run_observer.sh"]

networks:
EOF
    for k in $(seq 1 "$N"); do
        cat <<EOF
  mock-robot-$k-net:
    driver: bridge
    driver_opts: {com.docker.network.driver.mtu: "\${LINK_MTU:-1500}"}
    ipam: {config: [{subnet: 172.40.$k.0/24}]}
EOF
    done
    cat <<EOF
  observer-net:
    driver: bridge
    driver_opts: {com.docker.network.driver.mtu: "\${LINK_MTU:-1500}"}
    ipam: {config: [{subnet: 172.40.$CONSOLE_IDX.0/24}]}
EOF
    } > "$out"
    echo "generated $out + rmw_configuration/routed/ (routed, $N robots)"
}

case "$TOPO" in
    star)   gen_star ;;
    flat)   gen_flat ;;
    routed) gen_routed ;;
esac
