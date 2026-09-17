#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORKSHOP="$ROOT/docker/scripts/workshop"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

run_case() {
    local name="$1" addresses="$2" expected_status="$3"
    local tmp status=0
    tmp="$(mktemp -d)"
    mkdir -p "$tmp/bin"

    cat >"$tmp/bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "compose" ]]; then
    exit 0
fi
if [[ "${1:-}" == "exec" && "${2:-}" == "wifi-ap" ]]; then
    printf '%s\n' "${TEST_AP_ADDRESSES:-}"
    exit 0
fi
if [[ "${1:-}" == "logs" ]]; then
    echo "fake AP log"
    exit 0
fi
exit 0
EOF
    chmod +x "$tmp/bin/docker"

    PATH="$tmp/bin:$PATH" \
        TEST_AP_ADDRESSES="$addresses" \
        WORKSHOP_AP_READY_TIMEOUT=1 \
        WORKSHOP_AP_EXEC_TIMEOUT=1 \
        WORKSHOP_AP_RETRY_INTERVAL=0.05 \
        WORKSHOP_SKIP_LICHTBLICK=1 \
        bash "$WORKSHOP" routed 2 >"$tmp/output" 2>&1 || status=$?

    if [[ "$status" -ne "$expected_status" ]]; then
        cat "$tmp/output" >&2
        rm -rf "$tmp"
        fail "$name returned $status, expected $expected_status"
    fi
    CASE_OUTPUT="$tmp/output"
    CASE_TMP="$tmp"
}

run_case complete $'1: eth0 inet 172.40.1.2/24\n2: eth1 inet 172.40.2.2/24\n3: eth2 inet 172.40.100.2/24' 0
grep -q "AP ready with 3/3 routed interfaces" "$CASE_OUTPUT" || fail "complete case did not report readiness"
rm -rf "$CASE_TMP"

run_case partial $'1: eth0 inet 172.40.1.2/24\n2: eth1 inet 172.40.100.2/24' 1
grep -q "timed out waiting for wifi-ap" "$CASE_OUTPUT" || fail "partial case did not report timeout"
grep -q "2/3 routed interfaces" "$CASE_OUTPUT" || fail "partial case did not report observed interface count"
rm -rf "$CASE_TMP"

echo "PASS: routed AP readiness"
