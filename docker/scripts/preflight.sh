#!/usr/bin/env bash
# preflight.sh - can this computer run the workshop, including the optional
# network-shaping steps? Checks Docker and the host plotting deps, detects what
# the kernel offers for shaping (egress and the bidirectional ifb path), then
# prints a plain-English verdict and the one next step for your system. Run from
# docker/:
#   bash scripts/preflight.sh
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib.sh"

IMG='ghcr.io/clearpathrobotics/roscon2026-mastering-the-jazzy-rmw:ubuntu-headless-latest'
# Egress: netem straight on a device. Bidirectional: what netem_profile.sh does, an ifb0
# mirror plus an ingress qdisc, which needs ifb + act_mirred + sch_ingress on the host kernel.
PROBE="docker run --rm --cap-add NET_ADMIN $IMG tc qdisc add dev lo root netem delay 1ms"
INGRESS_PROBE="docker run --rm --cap-add NET_ADMIN $IMG bash -c 'ip link add ifb0 type ifb && ip link set ifb0 up && tc qdisc add dev eth0 handle ffff: ingress && tc filter add dev eth0 parent ffff: protocol all u32 match u32 0 0 action mirred egress redirect dev ifb0 && tc qdisc add dev ifb0 root netem delay 1ms'"

# /proc/modules, not lsmod: minimal installs drop kmod, and a missing lsmod would look
# identical to a missing module. And never pipe into 'grep -q' here, because grep exits
# early, the writer takes SIGPIPE, and pipefail turns a loaded module into "not loaded".
MODULES=""
[ -r /proc/modules ] && MODULES="$(cat /proc/modules 2>/dev/null || true)"
mod_loaded() { [ -n "$MODULES" ] && grep -q "^$1 " <<<"$MODULES"; }
# A module compiled into the kernel has no .ko file on disk and never appears in
# /proc/modules, so without this it reads as absent when it isn't. modules.builtin is the
# kernel's own list of what was compiled in, still named with a .ko suffix.
mod_builtin() {
  local builtin
  builtin="/lib/modules/$(uname -r)/modules.builtin"
  [ -r "$builtin" ] && grep -q "/$1\.ko$" "$builtin"
}
have_mod() {
  mod_loaded "$1" && return 0
  mod_builtin "$1" && return 0
  modinfo "$1" >/dev/null 2>&1
}

command -v docker >/dev/null 2>&1 || die "Docker is not installed. Install Docker, then re-run."
docker info >/dev/null 2>&1 || die "Docker is installed but the daemon is not reachable. Start Docker, then re-run."
ok "Docker daemon reachable."

# docker/captures and docker/bags are bind-mounted into containers that run as
# root (ubuntu-headless, wifi-ap, ...). If they don't exist yet, Compose creates
# them on first `up` owned by root, and every later host-side `mkdir -p
# captures/<name>` (run_sweep.sh) then fails with Permission Denied. Create them
# here, as the invoking user, before Compose ever gets the chance.
CAPTURES_DIR="$SCRIPT_DIR/../captures"
BAGS_DIR="$SCRIPT_DIR/../bags"
mkdir -p "$CAPTURES_DIR" "$BAGS_DIR"
for d in "$CAPTURES_DIR" "$BAGS_DIR"; do
    [ -w "$d" ] || warn "$d is not writable by $(id -un) (likely root-owned from an earlier run). Fix with: sudo chown -R \$(id -u):\$(id -g) $d"
done
if docker compose version >/dev/null 2>&1; then ok "docker compose v2 present."; else warn "docker compose v2 not found (need v2.20+)."; fi

# Routed Lab 3 uses multiple Docker bridge networks and an AP container as the
# L3 hop between them. If bridge-netfilter is on and the host's FORWARD policy
# drops that traffic before it reaches the AP, this can happen on any Linux
# host (most commonly WSL2, but also native hosts running ufw/firewalld with a
# default-deny FORWARD chain). This is diagnostic only: host state is changed
# exclusively through host_forwarding.sh.
if [ -r /proc/sys/net/bridge/bridge-nf-call-iptables ]; then
  bridge_nf_call="$(cat /proc/sys/net/bridge/bridge-nf-call-iptables 2>/dev/null || echo '?')"
  if [ "$bridge_nf_call" = "1" ]; then
    warn "Bridge filtering is enabled (bridge-nf-call-iptables=1). If routed Lab 3 traffic is blocked, run:"
    info "  bash docker/scripts/host_forwarding.sh check"
    info "  sudo bash docker/scripts/host_forwarding.sh disable-filtering"
  else
    ok "Bridge filtering is disabled (bridge-nf-call-iptables=$bridge_nf_call)."
  fi
fi

# Plotting needs nothing on the host: matplotlib and pandas live in the webshark image and
# every chart is rendered by `docker run` inside it.

# Figure out what kind of host this is, then detect what it actually has. We do not
# assert a verdict per platform; we detect where we can and let the container probe
# decide where we cannot. os_kind drives the plain-English wording; shaping/ingress
# hold the detected result.
OS="$(uname -s)"; ARCH="$(uname -m)"
os_kind="other"; os_label="this computer"
shaping="probe"   # probe = cannot tell from here; the container check below decides
ingress="n/a"
next_step=""      # the one action for THIS host, in plain words

case "$OS" in
  Darwin)
    os_kind="macos"; os_label="this Mac"
    # We cannot read Docker's Linux VM kernel from macOS, so the container probe decides.
    if [ "$ARCH" = "arm64" ]; then
      next_step="On an Apple Silicon Mac the shaping feature is usually missing from Docker's VM. Run the check below; if it fails, do the shaping steps on a Linux computer."
    else
      next_step="On an Intel Mac shaping usually works in Docker Desktop. Run the check below to confirm."
    fi
    ;;
  Linux)
    if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
      os_kind="wsl2"; os_label="this Windows (WSL2) computer"
    elif [ -f /etc/nv_tegra_release ] || uname -r | grep -qi tegra; then
      os_kind="jetson"; os_label="this Jetson"
    else
      os_kind="linux"; os_label="this Linux computer"
    fi
    ;;
esac

# WSL2 and native Linux both run a real Linux kernel, so the same module check works.
if [ "$os_kind" = "wsl2" ] || [ "$os_kind" = "linux" ]; then
  if mod_loaded sch_netem || mod_builtin sch_netem; then
    shaping="yes"
  elif have_mod sch_netem; then
    shaping="load"   # present, just not loaded yet
  else
    shaping="no"
  fi
  # Bidirectional shaping (netem_profile.sh) also needs the inbound path: ifb + act_mirred.
  if [ "$shaping" != "no" ]; then
    ing_missing=""
    for m in ifb act_mirred; do have_mod "$m" || ing_missing+=" $m"; done
    if [ -n "$ing_missing" ]; then
      ingress="no ($ing_missing not in this kernel; add linux-modules-extra-$(uname -r))"
    elif mod_loaded ifb || mod_builtin ifb; then
      ingress="yes"
    else
      ingress="yes, after: sudo modprobe -a ifb act_mirred"
    fi
  fi
  # The next step depends on the result and the OS.
  if [ "$shaping" = "load" ]; then
    next_step="Run once: sudo modprobe -a sch_netem ifb act_mirred   (then re-run this check). The -a matters: without it the last two names are read as parameters to sch_netem."
  elif [ "$shaping" = "no" ] && [ "$os_kind" = "wsl2" ]; then
    next_step="Update WSL to get a current kernel: in Windows PowerShell run  wsl --update  then  wsl --shutdown, reopen Ubuntu, and run this check again."
  elif [ "$shaping" = "no" ]; then
    next_step="Unusual on a normal amd64 Linux box. Try: sudo apt install linux-modules-extra-\$(uname -r)   or do the shaping steps on another Linux computer."
  fi
elif [ "$os_kind" = "jetson" ]; then
  shaping="no"
  next_step="Network shaping is not available on the Jetson's stock kernel. Do the shaping steps on an amd64 Linux computer, or study the recorded capture."
fi

# ---- Plain-English verdict (the headline for a workshop attendee) ----
echo
case "$shaping" in
  yes)
    ok "Result: $os_label can run the whole workshop, including the network-shaping steps."
    ;;
  load)
    ok "Result: $os_label can run the whole workshop, including the network-shaping steps."
    info "One quick step first: $next_step"
    ;;
  no)
    warn "Result: $os_label can run the workshop, but not the optional network-shaping steps."
    info "You can still do every other part, and there is a recorded shaped run to study."
    [ -n "$next_step" ] && info "To turn shaping on: $next_step"
    ;;
  *)  # probe: macOS or an unrecognised host
    info "Result: $os_label runs everything Docker does. Whether the optional network-shaping steps work depends on your Docker setup."
    [ -n "$next_step" ] && info "$next_step"
    ;;
esac

# Fallback catalog: only when shaping is not confirmed, and only the common fixes.
if [ "$shaping" = "no" ] || [ "$shaping" = "probe" ]; then
  echo
  info "If the shaping steps do not work, the usual fix by system:"
  info "  Windows (WSL2):      wsl --update  then  wsl --shutdown, reopen Ubuntu (older kernels lacked it)"
  info "  Linux, feature off:  sudo modprobe -a sch_netem ifb act_mirred"
  info "  Minimal/cloud Linux: sudo apt install linux-modules-extra-\$(uname -r)"
  info "  Mac (Apple Silicon): use a Linux computer for the shaping steps; Intel Macs usually work"
  info "  NVIDIA Jetson:       not on the stock kernel; use another computer or the recorded capture"
fi

# ---- Technical details (for the facilitator) ----
case "$shaping" in
  yes)   egress_detail="available";;
  load)  egress_detail="available after: sudo modprobe sch_netem";;
  no)    egress_detail="not available in this kernel";;
  *)     egress_detail="decided by the container check below";;
esac
[ "$ingress" = "n/a" ] && ingress="$egress_detail"
[ "$os_kind" = "linux" ] && [ "$ARCH" != "x86_64" ] && warn "Architecture is $ARCH, not amd64. amd64 is the validated target; arm64 is not."
echo
info "Technical details (for the facilitator):"
info "  Egress shaping (netem on a device): $egress_detail"
info "  Bidirectional shaping (inbound via ifb, used by netem_profile.sh): $ingress"
info "  Definitive checks, once a workshop image is pulled:"
info "    egress:        $PROBE"
info "    bidirectional: $INGRESS_PROBE"
info "    A clean exit from each means that direction shapes in your Docker backend."
