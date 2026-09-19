#!/usr/bin/env bash
# run_observer.sh [keepalive|bridge|capture ...] - the ONE observer entrypoint
# for every topology (star, flat, routed). Runs inside the container.
#
# The observer is a persistent vantage: by default it sets up routing (and, for
# star, builds the workspace once) and then IDLES. Tools run on demand, each
# driven by `workshop observer <...>` which execs back into this script:
#   bridge                       the Foxglove bridge (+ fleet_map for routed)
#   capture start|stop|bounce    tshark on the observer's interface, for webshark
#
# Env switches:
#   AP_GW + REMOTE_SUBNETS   routed: route every robot subnet via the AP first
#   MOCK_BUILD=true          star: build the editable /ws once at startup
#                            (else use the image's prebuilt /mock_robot_ws)
#   FLEET_MAP=true           routed: `bridge` also runs fleet_map.py
#   HOST_UID + HOST_GID      capture: own the pcaps as the host user so webshark
#                            (a non-root uid) can read the still-growing file
set -uo pipefail
set +u; source /opt/ros/jazzy/setup.bash; set -u

# routed: route robot subnets through the AP (idempotent) so exec'd tools reach them.
add_routes() {
    [[ -n "${AP_GW:-}" ]] || return 0
    for net in ${REMOTE_SUBNETS:-}; do ip route replace "$net" via "$AP_GW"; done
}

# star builds the editable workspace once (keepalive); `bridge` only sources it.
build_workspace() {
    cd /ws
    colcon build --symlink-install --packages-select \
        mock_sensor_tools mock_robot_description mock_robot_bringup \
        mock_robot_viz urdf_raycast_sensors dynamic_image_publisher
}
source_workspace() {
    set +u
    if [[ "${MOCK_BUILD:-false}" == "true" ]]; then
        [ -f /ws/install/setup.bash ] && source /ws/install/setup.bash
    else
        [ -f /mock_robot_ws/install/setup.bash ] && source /mock_robot_ws/install/setup.bash
    fi
    set -u
}

start_bridge() {
    echo "run_observer: bridge :8765 fleet_map=${FLEET_MAP:-false} rmw=${RMW_IMPLEMENTATION:-?}"
    # routed: one top-down image of the whole fleet on /fleet_map/image_raw.
    if [[ "${FLEET_MAP:-false}" == "true" ]]; then
        python3 /scripts/lab3/fleet_map.py \
            --anchor "${FLEET_MAP_ANCHOR:-odom}" \
            --model "${MOCK_ROBOT_MODEL:-a300}" &
        trap 'kill $! 2>/dev/null || true' EXIT
    fi
    # mock_robot_viz is only present when the workspace was built with it (star's
    # runtime build); otherwise fall back to the raw foxglove_bridge launch.
    if ros2 pkg prefix mock_robot_viz >/dev/null 2>&1; then
        exec ros2 launch mock_robot_viz foxglove_bridge.launch.py
    fi
    exec ros2 launch foxglove_bridge foxglove_bridge_launch.xml port:=8765
}

# --- capture ----------------------------------------------------------------
# tshark captures on the observer's fleet-side interface (a flat observer is
# single-homed on the fleet's network), which carries the DDS or zenoh traffic.
# dumpcap writes its files mode 600 as root, unreadable by the webshark
# container's non-root uid, so a background watcher relaxes each file to the host
# user continuously - that is what lets webshark read a capture WHILE it grows.
CAPTURES=/lab2-captures
SUBSCRIBER_PROBE=/lab2-scripts/rmw_subscriber_probe.py
# The processes this capture started, one "<role> <pid> <comm>" line each, so
# `capture stop` signals precisely those. Container-local, rewritten on each start.
CAPTURE_PIDFILE=/tmp/observer_capture.pids
# Serializes start/stop so concurrent lifecycle operations cannot corrupt the pidfile.
CAPTURE_LOCK=/tmp/observer_capture.lock

# The observer's fleet-side interface: resolved as its one non-loopback link
# rather than assuming `eth0`, since Docker's interface naming is not guaranteed.
capture_iface() {
    ip -o -4 addr show 2>/dev/null | awk '$2 != "lo" { print $2; exit }'
}

# The fleet's RMW, read from this container's own environment (the source of
# truth), so a capture is always labelled for the RMW actually on the wire.
capture_rmw_label() {
    case "${RMW_IMPLEMENTATION:-}" in
        rmw_cyclonedds_cpp) echo cyclone ;;
        rmw_fastrtps_cpp)   echo fast ;;
        rmw_zenoh_cpp)      echo zenoh ;;
        *) echo "run_observer: capture: unknown RMW_IMPLEMENTATION='${RMW_IMPLEMENTATION:-}'" >&2; return 1 ;;
    esac
}

# tshark is alive AND at least one target file has bytes in it.
tshark_capturing() {  # <pcap glob>
    pgrep -x tshark >/dev/null 2>&1 || return 1
    local f
    for f in $1; do [ -s "$f" ] && return 0; done
    return 1
}

# Every robot is delivering both of its topics right now: the probe writes one
# CSV row per (robot, topic) arrival; count distinct pairs seen in the last 3s
# (not over the whole file, which could pass on a burst from while another robot
# was still starting).
arrivals_flowing() {
    local csv="$1" n="$2" topics_per_robot=2
    [ -s "$csv" ] || return 1
    awk -F, -v want="$(( n * topics_per_robot ))" -v cut="$(( $(date +%s) - 3 ))" '
        NR > 1 && $1 >= cut { seen[$2 "," $3] = 1 }
        END { c = 0; for (k in seen) c++; exit !(c >= want) }' "$csv"
}

wait_until() {  # <label> <timeout_s> <predicate> [args...]
    local label="$1" timeout="$2"; shift 2
    local waited=0
    until "$@" >/dev/null 2>&1; do
        sleep 1; waited=$((waited + 1))
        if (( waited >= timeout )); then
            echo "run_observer: WARNING: $label not ready after ${timeout}s; continuing" >&2
            return 1
        fi
    done
    echo "run_observer: [ok] $label (${waited}s)"
}

# A throwaway subscriber joins the graph so the discovery burst - which goes
# quiet once the fleet has formed - crosses the wire again into the open capture.
# One mechanism for every RMW: a new DDS participant triggers each robot's SEDP
# replay, and a new zenoh session makes the robots' routers re-declare their key
# expressions. Neither disturbs any robot's own process.
capture_retrigger() {
    timeout 3 ros2 topic echo --once --qos-reliability best_effort \
        /robot_1/odometry/filtered >/dev/null 2>&1 || true
}

# Continuously hand the growing pcaps to the host user. capture_start runs this as
# a detached re-invocation of the script and records its pid for capture_stop.
perms_watch() {  # <rmw label>
    local label="$1"
    while :; do
        chmod 664 "$CAPTURES/live_${label}"_*.pcap "$CAPTURES/stream_${label}.pcap" 2>/dev/null || true
        #chown "${HOST_UID}:${HOST_GID:-$HOST_UID}" \
        #    "$CAPTURES/live_${label}"_*.pcap "$CAPTURES/stream_${label}.pcap" 2>/dev/null || true
        sleep 2
    done
}

capture_finalize_perms() {  # <rmw label>: one last ownership pass after the watcher stops
    local label="$1"
    [[ -n "${HOST_UID:-}" ]] || return 0
    chmod 664 "$CAPTURES/live_${label}"_*.pcap "$CAPTURES/stream_${label}.pcap" 2>/dev/null || true
    #chown "${HOST_UID}:${HOST_GID:-$HOST_UID}" \
    #    "$CAPTURES/live_${label}"_*.pcap "$CAPTURES/stream_${label}.pcap" 2>/dev/null || true
}

# Signal a recorded pid only if it is still the program we started (its comm still
# matches), so a pid reused by an unrelated process after ours exited is never hit.
capture_kill() {  # <pid> <comm> [signal=TERM]
    local pid="$1" comm="$2" sig="${3:-TERM}" now
    [[ -n "$pid" ]] || return 0
    now="$(cat "/proc/$pid/comm" 2>/dev/null)" || return 0
    [[ "$now" == "$comm" ]] && kill "-$sig" "$pid" 2>/dev/null || true
}

# Basename of the ring/stream file being written right now (newest by mtime: the
# ring reuses low slot numbers after it wraps, so the highest number is not it).
capture_current_file() {  # <rmw label>
    ls -t "$CAPTURES/live_$1"_*.pcap "$CAPTURES/stream_$1.pcap" 2>/dev/null | head -1 | sed 's|.*/||'
}

# Ties the probe and perms-watch to tshark's life: when tshark exits for ANY reason
# (native autostop, a crash, or the SIGINT from `capture stop`), stop its siblings
# and do a final ownership pass, so an autostopped capture leaves nothing running.
capture_supervise() {
    local tshark_pid="$1" perms_pid="$2" probe_pid="$3" label="$4"
    while kill -0 "$tshark_pid" 2>/dev/null; do sleep 2; done
    exec 200>"$CAPTURE_LOCK"; flock 200
    capture_kill "$perms_pid" bash TERM
    capture_kill "$probe_pid" python3 TERM
    rm -f "$CAPTURE_PIDFILE"
    flock -u 200
    capture_finalize_perms "$label"
}

wait_pid_exit() {  # <pid> [max_s=5]: wait for the pid to exit, then SIGKILL it
    local pid="$1" max="${2:-5}" w=0
    [[ -n "$pid" ]] || return 0
    while kill -0 "$pid" 2>/dev/null; do
        sleep 1; w=$((w + 1))
        (( w >= max )) && { kill -KILL "$pid" 2>/dev/null || true; break; }
    done
}

# Signal every recorded process (comm-checked) and remove the pidfile. Prints the
# tshark pid it SIGINT'd, if any, so the caller can wait for it to finalize. Holds
# no lock and does no waiting - the caller owns both.
capture_teardown() {
    local role pid comm tshark_pid=""
    [[ -f "$CAPTURE_PIDFILE" ]] || return 0
    while read -r role pid comm; do
        [[ -n "$pid" ]] || continue
        if [[ "$role" == tshark ]]; then
            capture_kill "$pid" "$comm" INT   # SIGINT lets tshark finalize its file
            tshark_pid="$pid"
        else
            capture_kill "$pid" "$comm" TERM
        fi
    done < "$CAPTURE_PIDFILE"
    rm -f "$CAPTURE_PIDFILE"
    echo "$tshark_pid"
}

capture_stop() {
    local tshark_pid
    exec 200>"$CAPTURE_LOCK"; flock 200
    tshark_pid="$(capture_teardown)"
    flock -u 200
    # Wait for tshark to exit (outside the lock, so a stop never blocks a start) so
    # the last window is written out in full before anyone reads it.
    wait_pid_exit "$tshark_pid"
    local label; label="$(capture_rmw_label 2>/dev/null)" || label='*'
    capture_finalize_perms "$label"
    echo "run_observer: capture stopped (last window remains in captures/)"
}

capture_bounce() {
    local label; label="$(capture_rmw_label)" || return 1
    # Gate on a LIVE tshark, not just a pcap on disk: a leftover pcap from an
    # earlier run would otherwise fool this into "bouncing" into no open capture.
    local pcaps="$CAPTURES/live_${label}_*.pcap $CAPTURES/stream_${label}.pcap"
    if ! tshark_capturing "$pcaps"; then
        echo "run_observer: no active capture to bounce - start one first" >&2
        return 1
    fi
    local before after
    before="$(capture_current_file "$label")"
    capture_retrigger
    after="$(capture_current_file "$label")"
    echo "run_observer: discovery re-triggered; click Refresh in webshark, then open:"
    if [[ -n "$after" && "$before" != "$after" ]]; then
        echo "  the ring rotated mid-bounce, so the burst is split: ${before} and ${after}"
    else
        echo "  ${after:-$before}"
    fi
}

capture_start() {
    local mode=rotating
    case "${1:-}" in rotating|streaming) mode="$1"; shift ;; esac
    local n="${1:-3}" rotate="${2:-30}"
    local retention="${RETENTION:-6}" max_seconds="${LIVE_MAX_SECONDS:-1800}" max_mb="${LIVE_MAX_MB:-2000}"

    local label; label="$(capture_rmw_label)" || return 1
    local iface; iface="$(capture_iface)"
    [[ -n "$iface" ]] || { echo "run_observer: capture: no fleet interface found" >&2; return 1; }
    # zenoh rides tcp/7447 between the robots' routers and the observer peer, so
    # scope the capture to it; DDS is captured whole (SPDP/SEDP + user data).
    local cfilter=()
    [[ "$label" == zenoh ]] && cfilter=(-f "tcp port 7447")

    local pcaps="$CAPTURES/live_${label}_*.pcap"
    [[ "$mode" == streaming ]] && pcaps="$CAPTURES/stream_${label}.pcap"

    # Serialize the whole setup against any other start/stop, and wait for a prior
    # capture's tshark to finish before reusing the ring files. Released before the
    # readiness wait below, so a `stop` is never blocked by a slow warmup.
    exec 200>"$CAPTURE_LOCK"; flock 200
    wait_pid_exit "$(capture_teardown)"
    : > "$CAPTURE_PIDFILE"

    # DISCOVERY-FIRST: tshark is up before the probe joins, so the SEDP/Declare
    # burst that join triggers lands in the capture. Native tshark ring (-b) and
    # autostop (-a): one long-lived process, no restart loop. nohup so each stays
    # up after this `docker exec ... capture start` returns; its pid is recorded.
    # tshark's -b/-a filesize is in kB; convert the MB budget once instead of inline.
    local max_kb=$(( max_mb * 1000 ))
    local tshark_pid
    if [[ "$mode" == rotating ]]; then
        nohup tshark -i "$iface" "${cfilter[@]}" \
            -b duration:"$rotate" -b filesize:$(( max_kb / retention )) -b files:"$retention" \
            -w "$CAPTURES/live_${label}.pcap" -F pcap -q >/dev/null 2>&1 &
    else
        nohup tshark -i "$iface" "${cfilter[@]}" \
            -a duration:"$max_seconds" -a filesize:"$max_kb" \
            -w "$CAPTURES/stream_${label}.pcap" -F pcap -q >/dev/null 2>&1 &
    fi
    tshark_pid=$!
    echo "tshark $tshark_pid tshark" >> "$CAPTURE_PIDFILE"

    # Hard gate: if the recorder never actually captures, this is not a capture -
    # tear down what we started and fail, rather than reporting a false success.
    if ! wait_until "tshark capturing" 15 tshark_capturing "$pcaps"; then
        capture_kill "$tshark_pid" tshark KILL
        rm -f "$CAPTURE_PIDFILE"
        flock -u 200
        echo "run_observer: ERROR: tshark did not start capturing on ${iface}" >&2
        return 1
    fi

    local perms_pid=""
    if [[ -n "${HOST_UID:-}" ]]; then
        nohup bash "$0" _perms_watch "$label" >/dev/null 2>&1 &
        perms_pid=$!
        echo "perms $perms_pid bash" >> "$CAPTURE_PIDFILE"
    fi

    capture_retrigger

    # Sustained subscriber wakes the lazy JPEG republishers so egress actually
    # flows, and records per-robot arrivals for the readiness gate below.
    nohup python3 "$SUBSCRIBER_PROBE" "$n" "$CAPTURES/live_${label}.arrivals.csv" >/dev/null 2>&1 &
    local probe_pid=$!
    echo "probe $probe_pid python3" >> "$CAPTURE_PIDFILE"

    # Tie the probe + perms-watch to tshark's life so an autostop/crash cleans up.
    nohup bash "$0" _capture_supervise "$tshark_pid" "$perms_pid" "$probe_pid" "$label" >/dev/null 2>&1 &
    echo "supervisor $! bash" >> "$CAPTURE_PIDFILE"
    flock -u 200   # setup done; the readiness wait below must not block a stop

    # Delivery is a diagnostic, not a hard gate: an intentionally impaired capture
    # (or one taken before every publisher is up) is still a valid recording.
    wait_until "all $n robots delivering both topics" 60 \
        arrivals_flowing "$CAPTURES/live_${label}.arrivals.csv" "$n" || true

    if [[ "$mode" == rotating ]]; then
        echo "run_observer: rotating capture on ${iface} (rmw=$label, rotate=${rotate}s, ring=${retention} files, ${max_mb}MB total)"
    else
        echo "run_observer: streaming capture on ${iface} (rmw=$label, autostop=${max_seconds}s or ${max_mb}MB)"
    fi
}

add_routes
case "${1:-keepalive}" in
    keepalive)
        [[ "${MOCK_BUILD:-false}" == "true" ]] && build_workspace
        echo "run_observer: keep-alive; start tools with 'workshop observer bridge' or 'docker exec observer ...'"
        exec sleep infinity
        ;;
    bridge)
        source_workspace
        start_bridge
        ;;
    capture)
        shift
        case "${1:-}" in
            start)  shift; capture_start "$@" ;;
            stop)   capture_stop ;;
            bounce) capture_bounce ;;
            *) echo "run_observer: usage: capture <start|stop|bounce>" >&2; exit 2 ;;
        esac
        ;;
    _perms_watch)
        shift
        perms_watch "${1:?_perms_watch needs an rmw label}"
        ;;
    _capture_supervise)
        shift
        capture_supervise "$@"
        ;;
    *)
        echo "run_observer: unknown command '${1:-}' (keepalive|bridge|capture)" >&2; exit 2 ;;
esac
