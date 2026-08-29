#!/usr/bin/env bash
# compat-check.sh
# Can this computer run the ROSCon 2026 "Mastering the Jazzy RMW" workshop?
# Checks Docker, Docker Compose, the kernel modules the network degrading exercises require
# and free disk, then reports RAM and CPU count.
#
# It reads your system but changes nothing on your machine. Takes a few seconds.
#
# If the result looks wrong, the commands it prints at the end help confirm it.
#
#   curl -fsSLO https://raw.githubusercontent.com/clearpathrobotics/roscon2026-mastering-the-jazzy-rmw/main/compat-check.sh
#   bash compat-check.sh
#
# The last line it prints is a one-line summary.
# Paste that into the pre-workshop form so we know what to expect in the room.

set -uo pipefail

FORMAT="RMWCHECK/2"
MIN_COMPOSE="2.20"
MIN_DISK_GB=15
MIN_RAM_GB=16

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; NC=$'\033[0m'
else
    RED=''; GRN=''; YEL=''; NC=''
fi
warn_count=0
ok()   { printf '%s[+]%s %s\n' "$GRN" "$NC" "$*"; }
warn() { warn_count=$((warn_count + 1)); printf '%s[!]%s %s\n' "$YEL" "$NC" "$*"; }
bad()  { printf '%s[x]%s %s\n' "$RED" "$NC" "$*"; }
info() { printf '    %s\n' "$*"; }
head_() { printf '\n%s\n' "$*"; }

# Debian's package suffix (2.40.3-3) breaks a plain string compare.
version_ge() {
    local i h w
    local -a H W
    IFS=. read -r -a H <<<"$1"
    IFS=. read -r -a W <<<"$2"
    for i in 0 1 2; do
        h="${H[i]:-0}"; w="${W[i]:-0}"
        h="${h//[!0-9]/}"; w="${w//[!0-9]/}"
        h="${h:-0}"; w="${w:-0}"
        [ "$h" -gt "$w" ] && return 0
        [ "$h" -lt "$w" ] && return 1
    done
    return 0
}

# /proc/modules, not lsmod: minimal installs drop kmod, and a missing lsmod would look
# identical to a missing module. And never pipe into 'grep -q' here, because grep exits
# early, the writer takes SIGPIPE, and pipefail turns a loaded module into "not loaded".
MODULES=""
[ -r /proc/modules ] && MODULES="$(cat /proc/modules 2>/dev/null || true)"

mod_loaded() { [ -n "$MODULES" ] && grep -q "^$1 " <<<"$MODULES"; }
# A module built directly into the kernel never shows up in /proc/modules, modinfo,
# or as a .ko file on disk, so without this check it reads as absent when it isn't.
mod_builtin() {
    local builtin="/lib/modules/$(uname -r)/modules.builtin"
    [ -r "$builtin" ] && grep -q "/$1\.ko$" "$builtin"
}
pkg_hint() {
    local package
    package="linux-modules-extra-$(uname -r)"
    if command -v apt >/dev/null 2>&1 &&
       command -v apt-cache >/dev/null 2>&1 &&
       apt-cache show "$package" >/dev/null 2>&1; then
        printf 'sudo apt install %s' "$package"
    elif command -v dnf >/dev/null 2>&1; then
        printf 'sudo dnf install kernel-modules-extra-$(uname -r)'
    elif command -v yum >/dev/null 2>&1; then
        printf 'sudo yum install kernel-modules-extra-$(uname -r)'
    else
        printf 'check how your kernel or distro provides sch_netem, sch_htb, ifb and act_mirred'
    fi
}
# modinfo is also from kmod, so it can't be the only presence check on a kmod-less
# host; fall back to looking for the .ko file directly, which needs only coreutils.
mod_present() {
    mod_loaded "$1" && return 0
    mod_builtin "$1" && return 0
    if command -v modinfo >/dev/null 2>&1; then
        modinfo "$1" >/dev/null 2>&1 && return 0
    fi
    find "/lib/modules/$(uname -r)" -name "$1.ko*" -print -quit 2>/dev/null | grep -q .
}

OS="$(uname -s)"; ARCH="$(uname -m)"; KERNEL="$(uname -r)"
os_kind="other"; os_label="This computer"

case "$OS" in
    Darwin)
        os_kind="macos"; os_label="This Mac"
        ;;
    Linux)
        if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
            os_kind="wsl2"; os_label="This Windows (WSL2) computer"
        elif [ -f /etc/nv_tegra_release ] || grep -qi tegra <<<"$KERNEL"; then
            os_kind="jetson"; os_label="This Jetson"
        else
            os_kind="linux"; os_label="This Linux computer"
        fi
        ;;
esac

head_ "System"
ok "$os_kind / $ARCH / kernel $KERNEL"

cpus="unknown"; ram="unknown"; ram_gb=""
case "$OS" in
    Darwin)
        cpus="$(sysctl -n hw.ncpu 2>/dev/null || echo unknown)"
        membytes="$(sysctl -n hw.memsize 2>/dev/null || echo '')"
        [ -n "$membytes" ] && ram_gb="$((membytes / 1024 / 1024 / 1024))"
        ;;
    Linux)
        cpus="$(nproc 2>/dev/null || echo unknown)"
        memkb="$(awk '/^MemTotal:/{print $2}' /proc/meminfo 2>/dev/null || echo '')"
        [ -n "$memkb" ] && ram_gb="$((memkb / 1024 / 1024))"
        ;;
esac
[ -n "$ram_gb" ] && ram="${ram_gb}G"
info "CPU cores: $cpus     RAM: $ram"

# MemTotal excludes what the kernel reserves, so a 16G machine reports a bit under.
ram_note=""
if [ -n "$ram_gb" ] && [ "$ram_gb" -lt "$((MIN_RAM_GB - 1))" ]; then
    warn "The workshop asks for ${MIN_RAM_GB}G of RAM. This reports ${ram}."
    ram_note="RAM is below the ${MIN_RAM_GB}G the workshop asks for."
fi

docker_ver="none"; compose_ver="none"; docker_daemon="no"; docker_ready="no"; is_docker_desktop="no"

head_ "Docker"
if ! command -v docker >/dev/null 2>&1; then
    bad "Docker is not installed."
    info "Install Docker Engine, then run this check again. Docker Desktop is untested."
    info "https://docs.docker.com/engine/install/"
else
    docker_ver="$(docker --version 2>/dev/null | awk '{print $3}' | tr -d ',')"
    docker_ver="${docker_ver:-unknown}"
    if docker info >/dev/null 2>&1; then
        docker_daemon="yes"; docker_ready="yes"
        ok "Docker $docker_ver, daemon reachable."
        case "$(docker info --format '{{.OperatingSystem}}' 2>/dev/null)" in
            *Desktop*) is_docker_desktop="yes" ;;
        esac
    else
        # Not a pipe into grep: pipefail would return docker's failure, not grep's match.
        docker_err="$(docker info 2>&1)"
        case "$docker_err" in
            *"permission denied"*)
                bad "Docker $docker_ver is running, but this user is not allowed to reach it."
                info "Add yourself to the docker group, then log out and back in:"
                info "  sudo usermod -aG docker \$USER"
                info "Your groups are set when you log in, so this check keeps failing until"
                info "you do. Opening a new terminal is not enough. If you would rather not"
                info "log out yet, 'newgrp docker' fixes the shell you are in."
                ;;
            *)
                bad "Docker $docker_ver is installed but the daemon is not reachable."
                info "Start Docker, then run this check again."
                ;;
        esac
    fi

    raw="$(docker compose version --short 2>/dev/null || echo '')"
    if [ -z "$raw" ]; then
        bad "Docker Compose v2 not found."
        info "The workshop uses 'docker compose' (v2, a Docker plugin), not the older"
        info "'docker-compose' script. Install the compose plugin, then re-run."
        docker_ready="no"
    else
        compose_ver="${raw%%-*}"
        if version_ge "$compose_ver" "$MIN_COMPOSE"; then
            ok "Docker Compose $compose_ver."
        else
            bad "Docker Compose $compose_ver is older than the $MIN_COMPOSE the workshop needs."
            info "Update the compose plugin, then re-run."
            docker_ready="no"
        fi
    fi
fi

# On Docker Desktop the root dir is inside the VM, so fall back to $HOME.
disk="unknown"; disk_gb=""
disk_dir="$HOME"
if [ "$docker_daemon" = "yes" ]; then
    root="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || echo '')"
    [ -n "$root" ] && [ -d "$root" ] && disk_dir="$root"
fi
avail_kb="$(df -Pk "$disk_dir" 2>/dev/null | awk 'NR==2{print $4}')"

head_ "Disk"
if [ -n "$avail_kb" ]; then
    disk_gb="$((avail_kb / 1024 / 1024))"
    disk="${disk_gb}G"
    if [ "$disk_gb" -ge "$MIN_DISK_GB" ]; then
        ok "$disk free on $disk_dir."
    else
        warn "$disk free on $disk_dir. Plan for about ${MIN_DISK_GB}G."
        info "Roughly 4G of that is images, the rest is recorded data and build cache."
    fi
else
    warn "Could not read free space on $disk_dir."
fi

netem="unknown"; ifb="unknown"; shaping_note=""

head_ "Network shaping (part of Lab 3)"
case "$os_kind" in
    linux|wsl2)
        if mod_loaded sch_netem || mod_builtin sch_netem; then
            netem="yes"
        elif mod_present sch_netem; then
            netem="load"
        else
            netem="no"
        fi

        ifb="no"; ingress_unloaded=""
        if [ "$netem" != "no" ]; then
            missing=""
            for m in sch_htb ifb act_mirred; do
                if mod_present "$m"; then
                    mod_loaded "$m" || mod_builtin "$m" || ingress_unloaded="$ingress_unloaded $m"
                else
                    missing="$missing $m"
                fi
            done
            [ -z "$missing" ] && ifb="yes"
        fi

        case "$netem" in
            yes)
                ok "Available."
                if [ "$ifb" = "no" ]; then
                    warn "Full shaping is unavailable. Missing:$missing"
                    info "$(pkg_hint)"
                    info "then: sudo modprobe -a sch_netem sch_htb ifb act_mirred"
                    shaping_note="install the missing modules, then modprobe -a sch_netem sch_htb ifb act_mirred"
                elif [ -n "$ingress_unloaded" ]; then
                    warn "Bidirectional shaping needs one more step, present but not loaded:$ingress_unloaded"
                    info "sudo modprobe -a sch_netem sch_htb ifb act_mirred"
                    shaping_note="run: sudo modprobe -a sch_netem sch_htb ifb act_mirred"
                fi
                ;;
            load)
                if [ "$ifb" = "yes" ]; then
                    warn "Available, after loading the modules once:"
                    info "sudo modprobe -a sch_netem sch_htb ifb act_mirred"
                    shaping_note="run: sudo modprobe -a sch_netem sch_htb ifb act_mirred"
                else
                    warn "sch_netem is available but not loaded. Missing entirely:$missing"
                    info "$(pkg_hint)"
                    info "then: sudo modprobe -a sch_netem sch_htb ifb act_mirred"
                    shaping_note="install the missing modules, then modprobe -a sch_netem sch_htb ifb act_mirred"
                fi
                ;;
            no)
                warn "Not available on this kernel."
                if [ "$os_kind" = "wsl2" ]; then
                    info "In Windows PowerShell run 'wsl --update', then 'wsl --shutdown',"
                    info "reopen your Linux terminal, and run this check again."
                    shaping_note="run wsl --update then wsl --shutdown"
                else
                    info "Usually a minimal or cloud image, which strips these out. Try:"
                    info "$(pkg_hint)"
                    shaping_note="try installing your distro's kernel modules-extra package"
                fi
                ;;
        esac
        ;;
    jetson)
        netem="no"; ifb="no"
        warn "Not available. The stock Jetson L4T kernel ships without these modules."
        ;;
    macos)
        warn "Not available on macOS directly."
        info "Run this inside the Linux environment you will use on the day."
        ;;
    *)
        warn "Cannot be determined on this system."
        ;;
esac

if [ "$docker_ready" != "yes" ]; then
    verdict="no-docker"
elif [ "$is_docker_desktop" = "yes" ]; then
    verdict="docker-desktop"
elif [ "$os_kind" = "macos" ]; then
    verdict="untested"
elif [ "$os_kind" = "linux" ] && [ "$ARCH" != "x86_64" ]; then
    verdict="untested"
elif { [ "$netem" = "yes" ] || [ "$netem" = "load" ]; } && [ "$ifb" = "yes" ]; then
    verdict="full"
elif [ "$netem" = "yes" ] || [ "$netem" = "load" ]; then
    verdict="egress-only"
elif [ "$netem" = "no" ]; then
    verdict="no-shaping"
else
    verdict="unknown"
fi

head_ "Result"
case "$verdict" in
    docker-desktop)
        warn "Docker Desktop detected. The checks above may not reflect what containers actually get."
        info "Run the container test below to confirm directly, then paste that result in the form."
        ;;
    full)
        ok "Docker and the host network-shaping checks passed."
        if [ "$warn_count" -gt 0 ]; then
            info "Review the warnings above, then run the container test below."
        else
            info "Run the container test below to confirm it from inside a container."
        fi
        [ -n "$shaping_note" ] && warn "One setup step first: $shaping_note"
        ;;
    egress-only)
        ok "Docker checks passed."
        info "Lab 3 will run with egress-only shaping (sch_netem is available)."
        info "sch_htb, ifb and act_mirred are missing, so the return path isn't shaped."
        [ -n "$shaping_note" ] && warn "For bidirectional shaping too: $shaping_note"
        ;;
    no-shaping)
        ok "Docker checks passed."
        info "The host check could not find sch_netem. Run the container test below"
        info "before concluding that the Lab 3 network-degradation step will not run."
        [ -n "$shaping_note" ] && info "To turn it on: $shaping_note"
        ;;
    no-docker)
        bad "$os_label is not ready yet. Sort out Docker above, then run this again."
        ;;
    untested)
        warn "$os_label is not a setup we have tested."
        info "Paste the line below into the form so we know."
        ;;
    unknown)
        ok "$os_label runs everything Docker runs."
        info "Whether the network degrading exercises work depends on your Docker setup."
        ;;
esac
[ -n "$ram_note" ] && info "$ram_note"

head_ "Confirm it yourself"
info "This script reads your host system, which is a good indicator but not proof."
info "These commands are the real thing, and are worth running if anything above"
info "looks wrong or says it could not tell:"
info ""
info "  docker run --rm hello-world              # Docker really works"
info "  docker compose version                   # Compose v2, $MIN_COMPOSE or newer"
info "  lsmod | grep -E 'sch_netem|sch_htb|ifb|act_mirred'   # shaping modules, Linux and WSL2"
info "  docker run --rm --cap-add NET_ADMIN alpine sh -c '"
info "    apk add -q iproute2 || { echo \"no network from inside containers\"; exit 2; }"
info "    tc qdisc add dev lo root netem delay 1ms || { echo \"no netem\"; exit 3; }"
info "    echo \"netem works\"'"
info ""
info "This confirms one-way NetEm works inside a container, using the kernel your"
info "containers actually get rather than the one this script can see. It does not"
info "cover the two-way ifb/act_mirred modules. Alpine is not a workshop image,"
info "just a 4 MB base to run tc in."
info ""
info "It installs iproute2 inside the container, so it fails at the first line if the"
info "container cannot reach the network. Fix that first, because pulling the workshop"
info "images needs the same connection."

head_ "Paste this line into the pre-workshop form:"
printf '%s os=%s arch=%s kernel=%s cpus=%s ram=%s disk=%s docker=%s compose=%s desktop=%s netem=%s ifb=%s verdict=%s\n' \
    "$FORMAT" "$os_kind" "$ARCH" "$KERNEL" "$cpus" "$ram" "$disk" \
    "$docker_ver" "$compose_ver" "$is_docker_desktop" "$netem" "$ifb" "$verdict"
printf '\n'

# Always 0. A non-zero exit reads as "the script broke" to someone who would not know better.
exit 0
