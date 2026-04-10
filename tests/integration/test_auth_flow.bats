#!/usr/bin/env bats
# tests/integration/test_auth_flow.bats
#
# Integration tests for the PAM authentication stack.
# Requires:
#   - root privileges
#   - openvpn + libpam-google-authenticator + pamtester installed
#   - /etc/pam.d/openvpn configured (run install/03_configure_openvpn.sh first)
#   - oathtool (from oath-toolkit) for generating valid TOTP codes
#
# Run with:  sudo bats tests/integration/test_auth_flow.bats

AUTH_DIR="/etc/openvpn/server/auth"
TEST_USER="southvpn_test_$$"
TEST_PASS="T3stP@ss!$(date +%s)"

# Helper: generate a TOTP code for a given secret (base32)
totp_code() {
    local secret="$1"
    oathtool --base32 --totp "$secret"
}

setup() {
    # Skip if not root
    if [[ "$(id -u)" -ne 0 ]]; then
        skip "requires root"
    fi

    # Skip if required tools are missing
    for cmd in pamtester oathtool google-authenticator; do
        if ! command -v "$cmd" &>/dev/null; then
            skip "required tool not found: $cmd"
        fi
    done

    # Create test system user
    useradd --system --shell /usr/sbin/nologin --no-create-home "$TEST_USER" 2>/dev/null || true
    echo "${TEST_USER}:${TEST_PASS}" | chpasswd

    # Create TOTP secret directory
    mkdir -p "${AUTH_DIR}/${TEST_USER}"
    chown nobody:nogroup "${AUTH_DIR}/${TEST_USER}"
    chmod 700 "${AUTH_DIR}/${TEST_USER}"

    # Generate TOTP secret non-interactively
    SECRET_FILE="${AUTH_DIR}/${TEST_USER}/.google_authenticator"
    sudo -u nobody google-authenticator \
        --time-based --disallow-reuse --force \
        --rate-limit=3 --rate-time=30 --window-size=3 \
        --secret="${SECRET_FILE}" \
        --label="SouthVPN:${TEST_USER}" \
        --issuer="SouthVPN" \
        --qr-mode=NONE 2>/dev/null

    # Read the generated secret (first line of the file)
    TOTP_SECRET=$(head -1 "$SECRET_FILE")
    export TOTP_SECRET TEST_USER TEST_PASS
}

teardown() {
    if [[ "$(id -u)" -ne 0 ]]; then return; fi
    # Clean up test user
    userdel "$TEST_USER" 2>/dev/null || true
    rm -rf "${AUTH_DIR:?}/${TEST_USER}" 2>/dev/null || true
}

# ── Positive tests ─────────────────────────────────────────────────────────────

@test "correct password + valid TOTP → authentication succeeds" {
    local otp
    otp=$(totp_code "$TOTP_SECRET")
    # pamtester receives "password\nOTP" as the credential (mimics static-challenge)
    printf '%s\n%s' "$TEST_PASS" "$otp" | \
        pamtester openvpn "$TEST_USER" authenticate
}

# ── Negative tests ─────────────────────────────────────────────────────────────

@test "correct password + wrong TOTP → authentication fails" {
    run bash -c "printf '%s\n%s' '$TEST_PASS' '000000' | pamtester openvpn '$TEST_USER' authenticate"
    [ "$status" -ne 0 ]
}

@test "wrong password + valid TOTP → authentication fails" {
    local otp
    otp=$(totp_code "$TOTP_SECRET")
    run bash -c "printf '%s\n%s' 'wrongpassword' '$otp' | pamtester openvpn '$TEST_USER' authenticate"
    [ "$status" -ne 0 ]
}

@test "empty password → authentication fails" {
    run bash -c "printf '\n000000' | pamtester openvpn '$TEST_USER' authenticate"
    [ "$status" -ne 0 ]
}

@test "empty OTP → authentication fails" {
    run bash -c "printf '%s\n' '$TEST_PASS' | pamtester openvpn '$TEST_USER' authenticate"
    [ "$status" -ne 0 ]
}

# ── Security tests ─────────────────────────────────────────────────────────────

@test "TOTP replay attack: same OTP used twice is rejected" {
    local otp
    otp=$(totp_code "$TOTP_SECRET")

    # First use: must succeed
    printf '%s\n%s' "$TEST_PASS" "$otp" | \
        pamtester openvpn "$TEST_USER" authenticate

    # Second use of the same OTP within the same time window: must fail
    run bash -c "printf '%s\n%s' '$TEST_PASS' '$otp' | pamtester openvpn '$TEST_USER' authenticate"
    [ "$status" -ne 0 ]
}

@test "user without .google_authenticator file is always denied (no nullok)" {
    # Create a user without a TOTP secret
    local no_mfa_user="southvpn_nomfa_$$"
    useradd --system --shell /usr/sbin/nologin --no-create-home "$no_mfa_user"
    echo "${no_mfa_user}:${TEST_PASS}" | chpasswd
    # Do NOT create a .google_authenticator file

    run bash -c "printf '%s\n000000' '$TEST_PASS' | pamtester openvpn '$no_mfa_user' authenticate"
    local exit_code="$status"

    # Cleanup
    userdel "$no_mfa_user" 2>/dev/null || true

    [ "$exit_code" -ne 0 ]
}

@test "locked user (usermod -L) is denied even with correct credentials" {
    local otp
    otp=$(totp_code "$TOTP_SECRET")

    # Lock the account
    usermod -L "$TEST_USER"

    run bash -c "printf '%s\n%s' '$TEST_PASS' '$otp' | pamtester openvpn '$TEST_USER' authenticate"
    [ "$status" -ne 0 ]

    # Restore for teardown
    usermod -U "$TEST_USER"
}

@test "rate limiting: more than 3 failed attempts in 30s are blocked" {
    # Exhaust the rate limit with wrong OTPs
    for i in 1 2 3; do
        run bash -c "printf '%s\n000000' '$TEST_PASS' | pamtester openvpn '$TEST_USER' authenticate"
        # These may succeed or fail depending on timing; we just need to saturate the counter
    done

    # The 4th attempt with a CORRECT OTP should now be rate-limited
    local otp
    otp=$(totp_code "$TOTP_SECRET")
    run bash -c "printf '%s\n%s' '$TEST_PASS' '$otp' | pamtester openvpn '$TEST_USER' authenticate"
    [ "$status" -ne 0 ]
}
