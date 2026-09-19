#!/usr/bin/env bash
# Shared, topology-aware preflight for scripts/workshop.
# shellcheck disable=SC1091

# The topology compose files currently all use the same observer port and mock
# robot image, but those values are resolved from the selected compose project
# at runtime rather than copied from Lab 2's stacks.

_preflight_module_loaded() {
    local modules=""
    [ -r /proc/modules ] && modules="$(cat /proc/modules 2>/dev/null || true)"
    [ -n "$modules" ] && grep -q "^$1 " <<<"$modules"
}

_preflight_module_builtin() {
    local builtin
    builtin="/lib/modules/$(uname -r)/modules.builtin"
    [ -r "$builtin" ] && grep -q "/$1\.ko$" "$builtin"
}

_preflight_module_available() {
    _preflight_module_loaded "$1" && return 0
    _preflight_module_builtin "$1" && return 0
    modinfo "$1" >/dev/null 2>&1
}

_preflight_compose() {
    local topology="$1"
    local -a compose_args=()
    [[ -f "$DOCKER_ROOT/.env" ]] && compose_args+=(--env-file "$DOCKER_ROOT/.env")
    [[ -f "$DOCKER_ROOT/.env.local" ]] && compose_args+=(--env-file "$DOCKER_ROOT/.env.local")
    docker compose "${compose_args[@]}" -f "$COMPOSE_DIR/$topology.yml" \
        --profile "${TOPO_PROFILE[$topology]}" "${@:2}"
}

_preflight_ports() {
    local topology="$1" port="${FOXGLOVE_BRIDGE_PORT:-8765}" observer_id

    if ! (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
        ok "port $port (observer Foxglove bridge) free"
        return 0
    fi

    observer_id="$(_preflight_compose "$topology" ps -q observer 2>/dev/null)"
    if [[ -n "$observer_id" ]]; then
        info "port $port already served by this $topology topology"
    else
        fail "port $port (observer Foxglove bridge) is taken outside this project"
        return 1
    fi
}

_preflight_images() {
    local topology="$1" image rc=0
    local robot_image

    while IFS= read -r image; do
        [[ -z "$image" ]] && continue
        if docker image inspect "$image" >/dev/null 2>&1; then
            ok "image present: $image"
        else
            warn "image missing: $image (the first up pulls or builds it)"
        fi
    done < <(_preflight_compose "$topology" config --images 2>/dev/null | sort -u)

    robot_image="$(_preflight_compose "$topology" config --images mock-robot-1 2>/dev/null | head -1)"
    if [[ -z "$robot_image" ]] || ! docker image inspect "$robot_image" >/dev/null 2>&1; then
        warn "container shaping not probed: mock-robot-1 image is not available yet"
        return 0
    fi

    if docker run --rm --cap-add NET_ADMIN "$robot_image" \
            tc qdisc add dev lo root netem delay 1ms >/dev/null 2>&1; then
        ok "egress shaping works for $topology (netem applies in a container)"
    else
        fail "egress shaping does not apply in a $topology container"
        info "  Network impairment commands for this topology will not work."
        rc=1
    fi
    return "$rc"
}

_preflight_routed_modules() {
    local rc=0

    case "$(uname -s)" in
        Linux)
            if _preflight_module_available sch_htb; then
                ok "routed shaping module available: sch_htb"
            else
                fail "routed shaping module unavailable: sch_htb"
                info "  Fix: install the kernel's extra modules or use a kernel that provides sch_htb."
                rc=1
            fi
            ;;
        *)
            warn "cannot inspect sch_htb on $(uname -s); routed Docker kernel will decide"
            ;;
    esac

    return "$rc"
}

# lab2 captures + lab4 bags/captures must be writable by the container that captures into
# them; a dir left root-owned by an earlier run blocks that and the harness cannot chmod it
# without sudo. Warn (don't block) with the exact fix.
_preflight_capture_dirs() {
    local d
    for d in "$REPO_ROOT/lab2-on-the-wire/captures" "$DOCKER_ROOT/bags" "$DOCKER_ROOT/captures"; do
        [[ -d "$d" && ! -O "$d" && ! -w "$d" ]] && \
            warn "capture dir $d is owned by another user; captures/bags may fail - run: sudo chmod 1777 $d"
    done
    return 0
}

workshop_preflight() {
    local topology="$1" rc=0

    _check_topo "$topology" || return 2
    info "Running common host-capability checks"
    bash "$DOCKER_ROOT/scripts/preflight.sh" || rc=1

    echo
    info "$topology deployment checks:"
    if [[ ! -f "$COMPOSE_DIR/$topology.yml" ]]; then
        fail "missing $COMPOSE_DIR/$topology.yml; run 'scripts/workshop -t $topology up' once to generate it"
        return 1
    fi
    if _preflight_compose "$topology" config -q; then
        ok "$topology compose parses"
    else
        fail "$topology compose does not parse"
        rc=1
    fi
    _preflight_ports "$topology" || rc=1
    _preflight_images "$topology" || rc=1
    _preflight_capture_dirs
    if [[ "$topology" == routed ]]; then
        _preflight_routed_modules || rc=1
    fi

    echo
    if [[ "$rc" == 0 ]]; then
        ok "preflight: no checks block the $topology topology."
    else
        fail "preflight: fix the [x] lines above first."
    fi
    return "$rc"
}
