#!/usr/bin/env bash
# tests/security/test_username_injection.sh
#
# Security tests: verify that add_user.sh and gen_client_config.sh correctly
# reject malicious username inputs (path traversal, shell injection, etc.).
#
# Must be run as root (add_user.sh requires root).
# Safe to run: no actual users are created on failure inputs.
#
# Usage:  sudo bash tests/security/test_username_injection.sh
#         Returns exit code 0 if all tests pass, 1 if any fail.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ADD_SCRIPT="${REPO_DIR}/scripts/add_user.sh"
GEN_SCRIPT="${REPO_DIR}/scripts/gen_client_config.sh"
AUTH_DIR="/etc/openvpn/server/auth"

PASS=0
FAIL=0

# Colour output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

pass() { echo -e "${GREEN}PASS${NC} $1"; ((PASS++)); }
fail() { echo -e "${RED}FAIL${NC} $1"; ((FAIL++)); }

assert_rejected() {
    local description="$1"
    local username="$2"
    local script="$3"

    # Run the script; it must exit non-zero
    if bash "$script" "$username" --password "irrelevant" 2>/dev/null; then
        fail "${description}: expected rejection but script succeeded"
        # Attempt cleanup if a user was accidentally created
        id "$username" &>/dev/null && userdel "$username" 2>/dev/null || true
        rm -rf "${AUTH_DIR:?}/${username}" 2>/dev/null || true
    else
        pass "${description}"
    fi

    # Regardless of exit code: verify no side effects on the filesystem
    if [[ -e "${AUTH_DIR}/${username}" ]]; then
        fail "${description}: auth directory was created despite rejection!"
        rm -rf "${AUTH_DIR:?}/${username}" 2>/dev/null || true
        ((FAIL++))
    fi
    if id "$username" &>/dev/null 2>&1; then
        fail "${description}: system user was created despite rejection!"
        userdel "$username" 2>/dev/null || true
        ((FAIL++))
    fi
}

# ── Pre-flight ─────────────────────────────────────────────────────────────────
if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: This script must be run as root." >&2
    exit 1
fi

echo "=== SouthVPN Username Injection Tests ==="
echo ""

# ── Path traversal attacks ────────────────────────────────────────────────────
echo "--- Path traversal ---"
assert_rejected "path traversal ../../etc/passwd"      "../../etc/passwd"         "$ADD_SCRIPT"
assert_rejected "path traversal ../auth/"              "../auth/"                 "$ADD_SCRIPT"
assert_rejected "path traversal /etc/passwd (absolute)" "/etc/passwd"             "$ADD_SCRIPT"
assert_rejected "path traversal with dot-dot"          "foo/../bar"               "$ADD_SCRIPT"

# ── Shell injection attacks ───────────────────────────────────────────────────
echo ""
echo "--- Shell injection ---"
assert_rejected "semicolon injection"                  "user; rm -rf /"           "$ADD_SCRIPT"
assert_rejected "backtick injection"                   '`id`'                     "$ADD_SCRIPT"
assert_rejected "dollar-paren injection"               '$(whoami)'                "$ADD_SCRIPT"
assert_rejected "pipe injection"                       "user|cat /etc/shadow"     "$ADD_SCRIPT"
assert_rejected "ampersand injection"                  "user&ls"                  "$ADD_SCRIPT"
assert_rejected "redirect injection"                   "user>outfile"             "$ADD_SCRIPT"
assert_rejected "single quote injection"               "user'injection"           "$ADD_SCRIPT"
assert_rejected "double quote injection"               'user"injection'           "$ADD_SCRIPT"

# ── Null bytes and special characters ────────────────────────────────────────
echo ""
echo "--- Special characters ---"
assert_rejected "null byte in username"                "$(printf 'user\x00name')" "$ADD_SCRIPT"
assert_rejected "space in username"                    "user name"                "$ADD_SCRIPT"
assert_rejected "newline in username"                  "$(printf 'user\nname')"   "$ADD_SCRIPT"
assert_rejected "tab in username"                      "$(printf 'user\tname')"   "$ADD_SCRIPT"
assert_rejected "at sign in username"                  "user@host"                "$ADD_SCRIPT"
assert_rejected "colon in username"                    "user:colon"               "$ADD_SCRIPT"

# ── Length and format violations ──────────────────────────────────────────────
echo ""
echo "--- Length and format ---"
assert_rejected "empty username"                       ""                         "$ADD_SCRIPT"
assert_rejected "username too long (32 chars)"         "$(python3 -c 'print(\"a\"*32)')" "$ADD_SCRIPT"
assert_rejected "username starts with digit"           "1user"                    "$ADD_SCRIPT"
assert_rejected "username starts with hyphen"          "-user"                    "$ADD_SCRIPT"
assert_rejected "uppercase username"                   "UserName"                 "$ADD_SCRIPT"
assert_rejected "username with spaces only"            "   "                      "$ADD_SCRIPT"

# ── gen_client_config.sh injection tests (no root required for rejection) ────
echo ""
echo "--- gen_client_config.sh username validation ---"
for bad in "../../etc/passwd" "; rm -rf /" '`id`' "" "$(python3 -c 'print("a"*32)')"; do
    if bash "$GEN_SCRIPT" "$bad" /tmp --ip 1.2.3.4 2>/dev/null; then
        fail "gen_client_config: expected rejection for: ${bad@Q}"
    else
        pass "gen_client_config rejects: ${bad@Q}"
    fi
    # Verify no .ovpn file was created
    if [[ -f "/tmp/${bad}.ovpn" ]]; then
        fail "gen_client_config: .ovpn file was created for malicious input!"
        rm -f "/tmp/${bad}.ovpn"
    fi
done

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "==================================="
echo "Results: ${PASS} passed, ${FAIL} failed"
echo "==================================="

[[ "$FAIL" -eq 0 ]]
