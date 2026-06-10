#!/usr/bin/env bash
# remove_user.sh — Revoke a SouthVPN user's access.
#
# SECURITY REQUIREMENT: Must be run directly on the server (not over VPN).
#
# Usage:
#   sudo bash scripts/remove_user.sh <username>            # Lock account
#   sudo bash scripts/remove_user.sh <username> --delete   # Lock + delete system user

set -euo pipefail

AUTH_DIR="/etc/openvpn/server/auth"
LOG_FILE="/var/log/southvpn-admin.log"
VPN_SUBNET_PREFIX="10.8.0."

# ── Must run as root ──────────────────────────────────────────────────────────
if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: This script must be run as root." >&2
    exit 1
fi

# ── Must NOT be called from within a VPN session ─────────────────────────────
if [[ -n "${SSH_CLIENT:-}" ]]; then
    client_ip=$(awk '{print $1}' <<< "$SSH_CLIENT")
    if [[ -z "$client_ip" ]]; then
        echo "ERROR: Cannot determine client IP from SSH_CLIENT — refusing to proceed." >&2
        exit 1
    fi
    if [[ "$client_ip" == "${VPN_SUBNET_PREFIX}"* ]]; then
        echo "ERROR: User management cannot be performed over a VPN connection." >&2
        echo "       Source IP ${client_ip} is in the VPN subnet." >&2
        exit 1
    fi
fi

# ── Arguments ─────────────────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <username> [--delete]" >&2
    exit 1
fi

USERNAME="$1"
DELETE_USER=false
[[ "${2:-}" == "--delete" ]] && DELETE_USER=true

# ── Username validation ───────────────────────────────────────────────────────
if [[ -z "$USERNAME" ]] || [[ ! "$USERNAME" =~ ^[a-z][a-z0-9_-]*$ ]] || [[ ${#USERNAME} -gt 31 ]]; then
    echo "ERROR: Invalid username '${USERNAME}'." >&2
    exit 1
fi

if ! id "$USERNAME" &>/dev/null; then
    echo "ERROR: User '${USERNAME}' does not exist." >&2
    exit 1
fi

echo "Revoking access for user: ${USERNAME}"

# ── [1/3] Remove TOTP secret ──────────────────────────────────────────────────
USER_AUTH_DIR="${AUTH_DIR}/${USERNAME}"
if [[ -d "$USER_AUTH_DIR" ]]; then
    rm -rf "${USER_AUTH_DIR:?}"
    echo "[1/3] TOTP secret removed."
else
    echo "[1/3] TOTP secret directory not found (already removed?)."
fi

# ── [2/3] Lock account ────────────────────────────────────────────────────────
# Prevents password authentication; the user cannot connect even if they know
# the password and TOTP (pam_unix.so account check will deny locked accounts).
usermod -L "$USERNAME"
echo "[2/3] Account locked."

# ── [3/3] Optionally delete system user ──────────────────────────────────────
if [[ "$DELETE_USER" == "true" ]]; then
    userdel "$USERNAME"
    echo "[3/3] System user deleted."
else
    echo "[3/3] System user kept (locked). Use --delete to fully remove."
fi

# ── Audit log (root-only readable) ────────────────────────────────────────────
OPERATOR=$(logname 2>/dev/null || echo "unknown")
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
touch "$LOG_FILE"
chmod 640 "$LOG_FILE"
chown root:root "$LOG_FILE"
echo "${TS} REMOVED user=${USERNAME} deleted=${DELETE_USER} by=${OPERATOR}" >> "$LOG_FILE"

echo ""
echo "User '${USERNAME}' revoked. Active VPN sessions (if any) will be"
echo "disconnected at the next re-authentication cycle."
