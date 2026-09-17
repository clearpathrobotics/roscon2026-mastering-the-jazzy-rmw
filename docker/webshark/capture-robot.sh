#!/usr/bin/env bash
# capture-robot.sh - drive a real-hardware capture through the webshark.robot.yml container.
#
# Usage:
#   ./capture-robot.sh [name] [--iface IFACE] [--host|--docker|--loopback]
#                       [--duration SECONDS] [--filter BPF]
#
# This only applies when webshark runs on the robot itself (webshark.robot.yml,
# network_mode: host). If webshark runs on your laptop with the robot as a separate
# machine, there is no container on the robot to drive here, and guide.html section 4
# covers that case instead.
#
# The script is optional. The manual command it wraps keeps working as documented:
#   docker exec webshark tshark -i <iface> -s 0 -w /captures/<name>
# It only helps pick the interface and stop cleanly.
#
# No pgrep/pkill: the webshark image installs iproute2 but not procps. tshark's own PID,
# captured via $! and written to a file, is checked and signalled with the POSIX builtins
# kill -0/-INT/-KILL. Neither needs a new image dependency.
set -uo pipefail

CONTAINER=webshark
PIDFILE=/tmp/.capture-robot.pid
PROBEFILE=/tmp/.capture-robot-probe.pcap

_die() { echo "ERROR: $*" >&2; exit 1; }
_say() { echo "$*" >&2; }

usage() {
	cat <<'EOF'
Usage: ./capture-robot.sh [name] [options]

  name                capture file name (default: robot-<timestamp>.pcap)

  --iface IFACE       skip every prompt, capture on this interface now
  --host              the robot's own network (wifi/LAN), the common case
  --docker            a docker bridge, for a ROS stack running in containers
                       on this host
  --loopback          lo only, when publisher and subscriber are both here
                       and traffic never leaves the machine
  --duration SECONDS  stop after SECONDS instead of waiting for Ctrl-C
  --filter BPF        tshark capture filter (-f), to keep the file smaller
  -h, --help          this text
EOF
}

name=""
iface=""
group=""
duration=""
bpf=""

while [[ $# -gt 0 ]]; do
	case "$1" in
	--iface)
		iface="${2:?--iface needs an interface name}"
		[[ "$iface" =~ ^[A-Za-z0-9._@-]+$ ]] || _die \
			"--iface may only contain letters, numbers, '.', '_', '-', '@' (got: $iface)"
		shift 2
		;;
	--host) group=host; shift ;;
	--docker) group=docker; shift ;;
	--loopback) group=loopback; shift ;;
	--duration)
		duration="${2:?--duration needs a number of seconds}"
		shift 2
		;;
	--filter)
		bpf="${2:?--filter needs a capture filter}"
		shift 2
		;;
	-h | --help)
		usage
		exit 0
		;;
	--*) _die "unknown option: $1 (see --help)" ;;
	*)
		[[ -n "$name" ]] && _die "unexpected argument: $1"
		name="$1"
		shift
		;;
	esac
done

[[ -z "$name" ]] && name="robot-$(date +%Y%m%dT%H%M%S).pcap"
[[ "$name" == *.pcap ]] || name="${name}.pcap"
# name and iface get dropped into single-quoted remote shell commands below. A quote or
# semicolon in either one breaks the quoting and runs as code in the container instead of
# failing cleanly.
[[ "$name" =~ ^[A-Za-z0-9._-]+\.pcap$ ]] || _die \
	"capture name may only contain letters, numbers, '.', '_', '-' (got: $name)"

# 1. container up and actually capture-capable. webshark.yml and webshark.robot.yml both
# use container_name: webshark, so "a container named webshark is running" is not enough.
# The portable (viewer-only) compose file produces one too, just without CAP_NET_ADMIN.
docker inspect -f '{{.State.Running}}' "$CONTAINER" >/dev/null 2>&1 || _die \
	"no '$CONTAINER' container running. Start it with:
    docker compose -f webshark.robot.yml up -d"

capbnd="$(docker exec "$CONTAINER" sh -c "awk '/^CapBnd:/ { print \$2 }' /proc/self/status" 2>/dev/null)"
if ((!(0x${capbnd:-0} >> 12 & 1))); then
	_die "'$CONTAINER' is running without CAP_NET_ADMIN, so it can't capture. That's the
webshark.yml (viewer-only) configuration. Bring it up with the robot compose file instead:
    docker compose -f webshark.robot.yml up -d"
fi

# CAP_NET_ADMIN on a bridge network is the quiet failure: the capture succeeds and records the
# bridge, so the file looks healthy and holds none of the robot's traffic. network_mode: host is
# what gives the container the machine's own interfaces.
netmode="$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$CONTAINER" 2>/dev/null)"
if [[ "$netmode" != host ]]; then
	_die "'$CONTAINER' is on network '$netmode' rather than network_mode: host, so it can only
see that network, not the robot's own interfaces. A capture would succeed and record the wrong
traffic. Bring it up with the robot compose file instead:
    docker compose -f webshark.robot.yml up -d"
fi

# 2. /captures writable. Compose auto-creates a missing bind mount as root, and this
# container is UID 1000, so a first run can otherwise fail on write with no clear reason.
# shellcheck disable=SC2016  # printed for the reader to run on the host, not expanded here
docker exec "$CONTAINER" sh -c '[ -w /captures ]' || _die \
	'/captures is not writable by this container. On the host:
    sudo chown -R $(id -u):$(id -g) <the directory bound to /captures>'

# 3. interface, skipped entirely by --iface.
if [[ -z "$iface" ]]; then
	if [[ -z "$group" ]]; then
		if [[ -t 0 ]]; then
			_say ""
			_say "Which traffic are you after?"
			_say "  1) host      the robot's own network (wifi/LAN), the common case"
			_say "  2) docker    a docker bridge, if your ROS stack runs in containers here"
			_say "  3) loopback  same machine only, traffic that never leaves it"
			read -r -p "> " choice
			case "$choice" in
			1 | host) group=host ;;
			2 | docker) group=docker ;;
			3 | loopback) group=loopback ;;
			*) _die "unrecognized choice: $choice" ;;
			esac
		else
			_die "no interface given and no terminal to ask. Pass --iface NAME, or one of
--host/--docker/--loopback."
		fi
	fi

	candidates=()
	while IFS= read -r line; do
		[[ -z "$line" ]] && continue
		ifname="$(awk '{print $2}' <<<"$line")"
		addr="$(awk '{print $4}' <<<"$line")"
		case "$group" in
		loopback) [[ "$ifname" == lo ]] || continue ;;
		docker) [[ "$ifname" =~ ^(docker|br-|veth) ]] || continue ;;
		host) [[ "$ifname" == lo || "$ifname" =~ ^(docker|br-|veth) ]] && continue ;;
		esac
		candidates+=("$ifname|$addr")
	done < <(docker exec "$CONTAINER" ip -o -4 addr show)

	[[ ${#candidates[@]} -eq 0 ]] && _die \
		"no interfaces matched '$group'. Run 'docker exec $CONTAINER ip -o -4 addr show'
yourself and pass --iface NAME."

	if [[ ${#candidates[@]} -eq 1 && ! -t 0 ]]; then
		iface="${candidates[0]%%|*}"
	elif [[ -t 0 ]]; then
		_say ""
		_say "Capturing ~3s on each candidate to see what's actually carrying traffic:"
		declare -A by_number
		n=0
		for c in "${candidates[@]}"; do
			ifname="${c%%|*}"
			addr="${c##*|}"
			n=$((n + 1))
			docker exec "$CONTAINER" sh -c \
				"rm -f $PROBEFILE; timeout 4 tshark -i '$ifname' -a duration:3 -w $PROBEFILE -F pcap -q" \
				>/dev/null 2>&1
			count="$(docker exec "$CONTAINER" sh -c \
				"tshark -r $PROBEFILE -T fields -e frame.number 2>/dev/null | tail -1")"
			_say "  $n) $ifname ($addr): ${count:-0} packets in 3s"
			by_number[$n]="$ifname"
		done
		docker exec "$CONTAINER" rm -f "$PROBEFILE" 2>/dev/null || true
		read -r -p "Pick a number, or type an interface name: " pick
		if [[ -n "${by_number[$pick]:-}" ]]; then
			iface="${by_number[$pick]}"
		else
			for c in "${candidates[@]}"; do
				[[ "${c%%|*}" == "$pick" ]] && iface="$pick"
			done
			[[ -z "$iface" ]] && _die "'$pick' is not one of the candidates listed above."
		fi
	else
		_die "${#candidates[@]} candidates matched '$group' and no terminal to choose
between them. Pass --iface NAME."
	fi
fi

# A second capture started against the same PIDFILE would overwrite it, and the first
# capture's Ctrl-C would then find someone else's PID (or none) and abandon its own
# tshark running, orphaned and unstoppable through this script, writing to its file
# forever. Refuse instead of clobbering.
running_pid="$(docker exec "$CONTAINER" sh -c "cat $PIDFILE 2>/dev/null")"
if [[ -n "$running_pid" ]] && docker exec "$CONTAINER" sh -c "kill -0 '$running_pid' 2>/dev/null"; then
	_die "a capture is already running in '$CONTAINER' (pid $running_pid). Stop it first
(Ctrl-C in the terminal that started it). This script tracks one capture at a time
per container."
fi

# 4-6. start, wait for Ctrl-C (or --duration), stop.
#
# The backgrounded tshark has to stay a direct child of this sh -c, not get orphaned to
# the container's PID 1, which does not reap it: an unreaped exited process stays a
# zombie, and kill -0 on a zombie PID still reports success, so a naive
# "tshark & echo $! > pidfile" here would make the wait-for-it-to-stop loop below spin
# forever once tshark's own duration limit ends it. `wait "$pid"` keeps this shell alive
# as tshark's parent so it reaps it the moment it exits, whether that's the duration
# limit or our own SIGINT/SIGKILL below.
remote_cmd="rm -f $PIDFILE; tshark -i '${iface}' -s 0 -w '/captures/${name}' -F pcap -q"
[[ -n "$duration" ]] && remote_cmd+=" -a duration:${duration}"
[[ -n "$bpf" ]] && remote_cmd+=" -f '${bpf}'"
remote_cmd+=" & pid=\$!; echo \$pid > $PIDFILE; wait \$pid"

_report() {
	local size out rc frames
	size="$(docker exec "$CONTAINER" stat -c%s "/captures/${name}" 2>/dev/null)"
	# An idle interface is a real, correctly-reported outcome (0 frames), not a failure.
	# Only tshark's own exit code says whether reading the file back actually worked.
	out="$(docker exec "$CONTAINER" sh -c "tshark -r '/captures/${name}' -T fields -e frame.number" 2>&1)"
	rc=$?
	if [[ $rc -ne 0 ]]; then
		_say "capture stopped, but reading captures/${name} back failed:"
		_say "  $(head -1 <<<"$out")"
	else
		frames="$(grep -c . <<<"$out")"
		_say "done: captures/${name} (${size:-?} bytes, ${frames} frames)"
		[[ "$frames" == 0 ]] && _say "0 frames. Check you picked the interface actually carrying traffic."
	fi
	_say "open http://localhost:8085 and pick ${name} from the file list."
	_say "first time here? guide.html section 5 indexes what to look at by symptom,"
	_say "and its section 8 exercises are the quickest way into reading a capture."
}

_cleanup() {
	trap - INT TERM
	_say ""
	_say "stopping..."
	docker exec "$CONTAINER" sh -c "
		pid=\$(cat $PIDFILE 2>/dev/null)
		if [ -n \"\$pid\" ]; then
			kill -INT \"\$pid\" 2>/dev/null
			waited=0
			while kill -0 \"\$pid\" 2>/dev/null; do
				sleep 1; waited=\$((waited + 1))
				[ \"\$waited\" -ge 8 ] && { kill -KILL \"\$pid\" 2>/dev/null; break; }
			done
		fi
		rm -f $PIDFILE
	" 2>/dev/null
	_report
	exit 0
}

# The trap has to go on before tshark starts. A Ctrl-C during the docker exec -d call or
# the startup check below would otherwise hit bash's default SIGINT handling instead of
# this script's cleanup, leaving tshark running unmanaged in the container.
trap _cleanup INT TERM
docker exec -d "$CONTAINER" sh -c "$remote_cmd"
sleep 2
docker exec "$CONTAINER" sh -c "kill -0 \"\$(cat $PIDFILE 2>/dev/null)\" 2>/dev/null" || _die \
	"tshark did not start on $iface. Check the interface name and try again."

_say ""
_say "capturing on $iface -> captures/${name}. Start or restart your ROS stack now."
if [[ -n "$duration" ]]; then
	_say "stopping on its own after ${duration}s (or Ctrl-C to stop sooner)."
	while docker exec "$CONTAINER" sh -c "kill -0 \"\$(cat $PIDFILE 2>/dev/null)\" 2>/dev/null"; do
		sleep 1
	done
	_cleanup
else
	_say "Ctrl-C to stop."
	while :; do sleep 1; done
fi
