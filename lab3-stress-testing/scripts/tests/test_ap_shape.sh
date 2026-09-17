#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCRIPT="$ROOT/lab3-stress-testing/scripts/ap_shape.sh"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"

cat >"$tmp/bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%q ' "$@" >>"$TEST_DOCKER_LOG"
printf '\n' >>"$TEST_DOCKER_LOG"

if [[ "${TEST_DOCKER_MODE:-}" == "hang" ]]; then
    sleep 5
    exit 0
fi

args="$*"
if [[ "$args" == *"ip -o -4 addr show"* ]]; then
    printf '1: eth0 inet 172.40.1.2/24\n2: eth1 inet 172.40.100.2/24\n'
    exit 0
fi
if [[ "$args" == *"ip link add shapechk"* ]]; then
    exit 0
fi
if [[ "$args" == *"tc class add dev ifb0"* ]]; then
    exit 42
fi
exit 0
EOF
chmod +x "$tmp/bin/docker"

status=0
PATH="$tmp/bin:$PATH" TEST_DOCKER_LOG="$tmp/hang.log" TEST_DOCKER_MODE=hang \
    AP_EXEC_TIMEOUT=0.1 bash "$SCRIPT" status >"$tmp/hang.out" 2>&1 || status=$?
[[ "$status" -eq 124 ]] || { cat "$tmp/hang.out" >&2; fail "unresponsive AP returned $status, expected 124"; }
grep -q "timed out" "$tmp/hang.out" || fail "unresponsive AP did not report a timeout"

status=0
: >"$tmp/failure.log"
PATH="$tmp/bin:$PATH" TEST_DOCKER_LOG="$tmp/failure.log" \
    AP_EXEC_TIMEOUT=1 bash "$SCRIPT" good >"$tmp/failure.out" 2>&1 || status=$?
[[ "$status" -eq 42 ]] || { cat "$tmp/failure.out" >&2; fail "partial install returned $status, expected 42"; }
grep -q "failed to apply.*cleaned partial shaping state" "$tmp/failure.out" || fail "partial install did not report cleanup"
grep -q 'qdisc.*ingress' "$tmp/failure.log" || fail "partial install did not clean ingress state"
grep -q 'link.*del.*ifb0' "$tmp/failure.log" || fail "partial install did not remove ifb0"
if grep -q "capacity_mbps=%s" "$tmp/failure.log"; then
    fail "partial install wrote successful profile metadata"
fi

echo "PASS: AP shaping failure handling"