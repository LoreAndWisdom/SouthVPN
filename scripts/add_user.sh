#!/usr/bin/env bash
# add_user.sh — Enroll a new SouthVPN user with password + Google Authenticator MFA.
#
# SECURITY REQUIREMENT: This script must be run directly on the server.
#   It cannot be executed over a VPN connection (SSH from 10.8.0.x is blocked).
#   Rationale: user enrollment creates credentials and TOTP secrets; it must
#   only be performed by someone with legitimate physical or non-VPN server access.
#
# Usage:
#   sudo bash scripts/add_user.sh <username>
#   sudo bash scripts/add_user.sh <username> --password <password>

set -euo pipefail

AUTH_DIR="/etc/openvpn/server/auth"
VPN_SUBNET_PREFIX="10.8.0."

# ── Must run as root ──────────────────────────────────────────────────────────
if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: This script must be run as root." >&2
    echo "       Usage: sudo bash scripts/add_user.sh <username>" >&2
    exit 1
fi

# ── Must NOT be called from within a VPN session ─────────────────────────────
if [[ -n "${SSH_CLIENT:-}" ]]; then
    client_ip=$(echo "$SSH_CLIENT" | awk '{print $1}')
    if [[ "$client_ip" == "${VPN_SUBNET_PREFIX}"* ]]; then
        echo "ERROR: User enrollment cannot be performed over a VPN connection." >&2
        echo "       Source IP ${client_ip} is in the VPN subnet." >&2
        echo "       Connect to the server via direct SSH or local terminal." >&2
        exit 1
    fi
fi

# ── Arguments ─────────────────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <username> [--password <password>]" >&2
    exit 1
fi

USERNAME="$1"
shift

PASSWORD=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --password) PASSWORD="$2"; shift 2 ;;
        *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
    esac
done

# ── Username validation ───────────────────────────────────────────────────────
# Strict allowlist: lowercase letter start, then alphanumeric/hyphen/underscore,
# max 31 characters total.  Rejects path traversal and shell injection attempts.
if [[ -z "$USERNAME" ]]; then
    echo "ERROR: Username cannot be empty." >&2
    exit 1
fi
if [[ ${#USERNAME} -gt 31 ]]; then
    echo "ERROR: Username too long (max 31 characters)." >&2
    exit 1
fi
if [[ ! "$USERNAME" =~ ^[a-z][a-z0-9_-]*$ ]]; then
    echo "ERROR: Invalid username '${USERNAME}'." >&2
    echo "       Allowed: lowercase letters, digits, hyphens, underscores." >&2
    echo "       Must start with a letter." >&2
    exit 1
fi

# ── Check user doesn't already exist ─────────────────────────────────────────
if id "$USERNAME" &>/dev/null; then
    echo "ERROR: User '${USERNAME}' already exists." >&2
    echo "       To re-enroll, run: sudo bash scripts/remove_user.sh ${USERNAME} --delete" >&2
    exit 1
fi

echo "Enrolling user: ${USERNAME}"
echo ""

# ── [1/4] Create Linux system user ───────────────────────────────────────────
useradd --system --shell /usr/sbin/nologin --no-create-home "$USERNAME"
echo "[1/4] System user '${USERNAME}' created (no login shell, no home directory)."

# ── [2/4] Set password ────────────────────────────────────────────────────────
if [[ -z "$PASSWORD" ]]; then
    while true; do
        read -rsp "Enter VPN password for ${USERNAME}: " PASSWORD
        echo
        read -rsp "Confirm password: " PASSWORD2
        echo
        if [[ "$PASSWORD" == "$PASSWORD2" ]]; then
            break
        fi
        echo "Passwords do not match. Try again."
    done
fi

if [[ -z "$PASSWORD" ]]; then
    echo "ERROR: Password cannot be empty." >&2
    userdel "$USERNAME" 2>/dev/null || true
    exit 1
fi

echo "${USERNAME}:${PASSWORD}" | chpasswd
unset PASSWORD PASSWORD2
echo "[2/4] Password set."

# ── [3/4] Create TOTP secret directory ───────────────────────────────────────
# The directory must be owned by 'nobody' because OpenVPN drops privileges to
# 'nobody' before PAM authentication runs.
USER_AUTH_DIR="${AUTH_DIR}/${USERNAME}"
mkdir -p "$USER_AUTH_DIR"
chown nobody:nogroup "$USER_AUTH_DIR"
chmod 700 "$USER_AUTH_DIR"
echo "[3/4] Auth directory created: ${USER_AUTH_DIR}"

# ── [4/4] Google Authenticator enrollment ────────────────────────────────────
TOTP_SECRET_FILE="${USER_AUTH_DIR}/.google_authenticator"

# Run as 'nobody' so the secret file is owned by the PAM-reading UID.
# All settings are passed on the command line (fully non-interactive).
sudo -u nobody google-authenticator \
    --time-based \
    --disallow-reuse \
    --force \
    --rate-limit=3 \
    --rate-time=30 \
    --window-size=3 \
    --secret="${TOTP_SECRET_FILE}" \
    --label="SouthVPN:${USERNAME}" \
    --issuer="SouthVPN" \
    --qr-mode=UTF8

echo ""
echo "[4/4] Google Authenticator secret created."
echo ""
echo "=========================================="
echo "  User '${USERNAME}' enrolled successfully"
echo "=========================================="
echo ""
echo "  The QR code and emergency scratch codes are shown above."
echo "  Share them with the user over a secure channel."
echo ""
echo "  To generate the client .ovpn config:"
echo "    sudo bash scripts/gen_client_config.sh ${USERNAME} /tmp/"
echo ""
