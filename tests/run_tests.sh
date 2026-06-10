#!/usr/bin/env bash
# tests/run_tests.sh — Run the SouthVPN test suite.
#
# Usage:
#   bash tests/run_tests.sh            # unit + fuzz tests (no root needed)
#   sudo bash tests/run_tests.sh --all # all tests including integration + security

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ALL=false
[[ "${1:-}" == "--all" ]] && RUN_ALL=true

PASS_SUITES=0
FAIL_SUITES=0

run_suite() {
    local name="$1"
    shift
    echo ""
    echo "══════════════════════════════════════════"
    echo "  ${name}"
    echo "══════════════════════════════════════════"
    # Note: $((...)) assignment, not ((var++)) — the latter returns exit
    # status 1 when the variable is 0, which kills the script under set -e.
    if "$@"; then
        PASS_SUITES=$((PASS_SUITES + 1))
        echo "  ✓ ${name}: PASSED"
    else
        FAIL_SUITES=$((FAIL_SUITES + 1))
        echo "  ✗ ${name}: FAILED"
    fi
}

# ── Dependency check ──────────────────────────────────────────────────────────
echo "Checking dependencies..."
MISSING_DEPS=()
command -v python3 &>/dev/null || MISSING_DEPS+=("python3")
python3 -m pytest --version &>/dev/null || MISSING_DEPS+=("pytest (pip install pytest)")

if [[ ${#MISSING_DEPS[@]} -gt 0 ]]; then
    echo "ERROR: Missing dependencies: ${MISSING_DEPS[*]}" >&2
    exit 1
fi

cd "$REPO_DIR"

# ── Unit tests (no root, no network) ─────────────────────────────────────────
run_suite "Unit: ip_updater.py" \
    python3 -m pytest tests/unit/test_ip_updater.py tests/unit/test_ip_updater_drive.py -v

run_suite "Unit: gen_client_config.sh" \
    python3 -m pytest tests/unit/test_gen_client_config.py -v

# ── Fuzz / property-based tests (no root, no network) ────────────────────────
run_suite "Fuzz: IP parser" \
    python3 -m pytest tests/fuzz/fuzz_ip_parser.py -v

run_suite "Fuzz: config parser" \
    python3 -m pytest tests/fuzz/fuzz_config_parser.py -v

# ── Security tests (no root, no network) ──────────────────────────────────────
run_suite "Security: TOTP replay prevention" \
    python3 -m pytest tests/security/test_totp_replay.py -v

run_suite "Security: hardening regressions" \
    python3 -m pytest tests/security/test_hardening.py -v

# ── Integration + security tests (require root) ───────────────────────────────
if [[ "$RUN_ALL" == "true" ]]; then
    if [[ "$(id -u)" -ne 0 ]]; then
        echo ""
        echo "WARNING: --all was requested but not running as root."
        echo "         Integration and security shell tests will be skipped."
        echo "         Re-run with: sudo bash tests/run_tests.sh --all"
    else
        if command -v bats &>/dev/null; then
            run_suite "Integration: auth flow (PAM)" \
                bats tests/integration/test_auth_flow.bats

            run_suite "Integration: user management" \
                bats tests/integration/test_user_management.bats
        else
            echo ""
            echo "INFO: bats-core not found — skipping integration tests."
            echo "      Install: apt-get install bats"
        fi

        run_suite "Security: username injection" \
            bash tests/security/test_username_injection.sh
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
echo "  Test Summary"
echo "══════════════════════════════════════════"
echo "  Suites passed: ${PASS_SUITES}"
echo "  Suites failed: ${FAIL_SUITES}"
echo ""

if [[ "$FAIL_SUITES" -gt 0 ]]; then
    echo "  OVERALL: FAILED"
    exit 1
else
    echo "  OVERALL: PASSED"
fi
