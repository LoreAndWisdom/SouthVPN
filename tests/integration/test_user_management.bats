#!/usr/bin/env bats
# tests/integration/test_user_management.bats
#
# Integration tests for add_user.sh and remove_user.sh.
# Requires root and a working OpenVPN auth directory setup.
#
# Run with:  sudo bats tests/integration/test_user_management.bats

REPO_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
ADD_SCRIPT="${REPO_DIR}/scripts/add_user.sh"
REMOVE_SCRIPT="${REPO_DIR}/scripts/remove_user.sh"
AUTH_DIR="/etc/openvpn/server/auth"
TEST_USER="svpn_mgmt_$$"
TEST_PASS="M@nagementT3st!"

setup() {
    if [[ "$(id -u)" -ne 0 ]]; then
        skip "requires root"
    fi
    for cmd in google-authenticator pamtester; do
        command -v "$cmd" &>/dev/null || skip "required tool not found: $cmd"
    done
    # Ensure the auth directory exists
    mkdir -p "$AUTH_DIR"
    chown nobody:nogroup "$AUTH_DIR"
    chmod 700 "$AUTH_DIR"
}

teardown() {
    if [[ "$(id -u)" -ne 0 ]]; then return; fi
    # Best-effort cleanup of any user created during the test
    userdel "$TEST_USER" 2>/dev/null || true
    rm -rf "${AUTH_DIR:?}/${TEST_USER}" 2>/dev/null || true
    # Clean up any injection-target names that may have been created
    for bad_name in "testuser" "inject_test"; do
        userdel "$bad_name" 2>/dev/null || true
        rm -rf "${AUTH_DIR:?}/${bad_name}" 2>/dev/null || true
    done
}

# ── add_user.sh positive tests ────────────────────────────────────────────────

@test "add_user creates a Linux system user with nologin shell" {
    bash "$ADD_SCRIPT" "$TEST_USER" --password "$TEST_PASS"
    # User must exist
    id "$TEST_USER"
    # Shell must be nologin (no interactive login)
    local shell
    shell=$(getent passwd "$TEST_USER" | cut -d: -f7)
    [[ "$shell" == */nologin ]]
}

@test "add_user creates the TOTP secret file owned by nobody" {
    bash "$ADD_SCRIPT" "$TEST_USER" --password "$TEST_PASS"
    local secret_file="${AUTH_DIR}/${TEST_USER}/.google_authenticator"
    [ -f "$secret_file" ]
    local owner
    owner=$(stat -c '%U' "$secret_file")
    [ "$owner" = "nobody" ]
}

@test "add_user secret directory has mode 700 owned by nobody" {
    bash "$ADD_SCRIPT" "$TEST_USER" --password "$TEST_PASS"
    local dir="${AUTH_DIR}/${TEST_USER}"
    local owner mode
    owner=$(stat -c '%U' "$dir")
    mode=$(stat -c '%a' "$dir")
    [ "$owner" = "nobody" ]
    [ "$mode" = "700" ]
}

# ── add_user.sh security tests ────────────────────────────────────────────────

@test "add_user rejects username with path traversal (../../etc/passwd)" {
    run bash "$ADD_SCRIPT" "../../etc/passwd" --password "x"
    [ "$status" -ne 0 ]
    [[ "$output" =~ [Ii]nvalid ]]
}

@test "add_user rejects username with shell metacharacters" {
    run bash "$ADD_SCRIPT" 'user; rm -rf /' --password "x"
    [ "$status" -ne 0 ]
}

@test "add_user rejects username with backtick injection" {
    run bash "$ADD_SCRIPT" '`id`' --password "x"
    [ "$status" -ne 0 ]
}

@test "add_user rejects empty username" {
    run bash "$ADD_SCRIPT" "" --password "x"
    [ "$status" -ne 0 ]
}

@test "add_user rejects username longer than 31 characters" {
    local long_name
    long_name=$(python3 -c "print('a' * 32)")
    run bash "$ADD_SCRIPT" "$long_name" --password "x"
    [ "$status" -ne 0 ]
}

@test "add_user rejects uppercase username" {
    run bash "$ADD_SCRIPT" "UpperCase" --password "x"
    [ "$status" -ne 0 ]
}

@test "add_user rejects duplicate enrollment of existing user" {
    bash "$ADD_SCRIPT" "$TEST_USER" --password "$TEST_PASS"
    # Second invocation must fail
    run bash "$ADD_SCRIPT" "$TEST_USER" --password "$TEST_PASS"
    [ "$status" -ne 0 ]
    [[ "$output" =~ [Aa]lready|[Ee]xists ]]
}

@test "add_user does not create files when username is invalid" {
    local bad="../../malicious"
    run bash "$ADD_SCRIPT" "$bad" --password "x"
    [ "$status" -ne 0 ]
    # No files must have been created
    [ ! -e "${AUTH_DIR}/${bad}" ]
    [ ! -e "/etc/passwd_malicious" ]
}

# ── remove_user.sh tests ──────────────────────────────────────────────────────

@test "remove_user locks the account" {
    bash "$ADD_SCRIPT" "$TEST_USER" --password "$TEST_PASS"
    bash "$REMOVE_SCRIPT" "$TEST_USER"
    # Locked accounts have a '!' prefix in /etc/shadow
    local shadow_entry
    shadow_entry=$(grep "^${TEST_USER}:" /etc/shadow | cut -d: -f2)
    [[ "$shadow_entry" == '!'* ]]
}

@test "remove_user deletes the TOTP secret directory" {
    bash "$ADD_SCRIPT" "$TEST_USER" --password "$TEST_PASS"
    bash "$REMOVE_SCRIPT" "$TEST_USER"
    [ ! -d "${AUTH_DIR}/${TEST_USER}" ]
}

@test "remove_user --delete fully removes the system user" {
    bash "$ADD_SCRIPT" "$TEST_USER" --password "$TEST_PASS"
    bash "$REMOVE_SCRIPT" "$TEST_USER" --delete
    run id "$TEST_USER"
    [ "$status" -ne 0 ]
}

@test "remove_user rejects non-existent user" {
    run bash "$REMOVE_SCRIPT" "doesnotexist_$$"
    [ "$status" -ne 0 ]
}
