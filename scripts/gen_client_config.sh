#!/usr/bin/env bash
# gen_client_config.sh — Generate a self-contained .ovpn client config file.
#
# Since verify-client-cert=none is used, all users share the same CA cert and
# TLS auth key.  Authentication is entirely via PAM (password + TOTP).
#
# Usage:
#   sudo bash scripts/gen_client_config.sh <username> [output_dir] [--ip <ip>]
#
# Examples:
#   sudo bash scripts/gen_client_config.sh alice /tmp/
#   sudo bash scripts/gen_client_config.sh alice /tmp/ --ip 203.0.113.5

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
# Allow env var overrides for testing; production defaults otherwise.
LOCAL_IP_FILE="${LOCAL_IP_FILE:-/var/lib/southvpn/current_ip.txt}"
CA_CERT="${CA_CERT:-/etc/openvpn/server/ca.crt}"
TA_KEY="${TA_KEY:-/etc/openvpn/server/ta.key}"
TEMPLATE="${TEMPLATE:-${REPO_DIR}/client/client.conf.template}"

# ── Must run as root (reads /etc/openvpn/server/ta.key, mode 600) ─────────────
if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: This script must be run as root." >&2
    exit 1
fi

# ── Arguments ─────────────────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <username> [output_dir] [--ip <ip>]" >&2
    exit 1
fi

USERNAME="$1"
OUTPUT_DIR="${2:-/tmp}"
SERVER_IP=""

# Parse remaining flags
shift 2 2>/dev/null || shift "$#"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --ip) SERVER_IP="$2"; shift 2 ;;
        *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
    esac
done

# ── Username validation ───────────────────────────────────────────────────────
if [[ -z "$USERNAME" ]] || [[ ! "$USERNAME" =~ ^[a-z][a-z0-9_-]*$ ]] || [[ ${#USERNAME} -gt 31 ]]; then
    echo "ERROR: Invalid username '${USERNAME}'." >&2
    exit 1
fi

# ── Resolve server IP ─────────────────────────────────────────────────────────
if [[ -z "$SERVER_IP" ]]; then
    if [[ -f "$LOCAL_IP_FILE" ]]; then
        SERVER_IP=$(grep -oP '(?<=IP: )\S+' "$LOCAL_IP_FILE" | head -1 || true)
    fi
    if [[ -z "$SERVER_IP" ]]; then
        echo "ERROR: Cannot determine server IP." >&2
        echo "       Run the IP updater first: systemctl start southvpn-ip-updater.service" >&2
        echo "       Or pass the IP explicitly: --ip <ip_address>" >&2
        exit 1
    fi
fi

# ── Verify required files exist ───────────────────────────────────────────────
for f in "$CA_CERT" "$TA_KEY" "$TEMPLATE"; do
    if [[ ! -f "$f" ]]; then
        echo "ERROR: Required file not found: ${f}" >&2
        echo "       Run install/install_all.sh first." >&2
        exit 1
    fi
done

# ── Generate .ovpn using Python (handles multi-line cert content correctly) ───
mkdir -p "$OUTPUT_DIR"
OUTPUT_FILE="${OUTPUT_DIR}/${USERNAME}.ovpn"

TEMPLATE="$TEMPLATE" CA_CERT="$CA_CERT" TA_KEY="$TA_KEY" \
SERVER_IP="$SERVER_IP" OUTPUT_FILE="$OUTPUT_FILE" \
python3 - << 'PYEOF'
import os

template = open(os.environ["TEMPLATE"]).read()
ca_cert  = open(os.environ["CA_CERT"]).read().strip()
ta_key   = open(os.environ["TA_KEY"]).read().strip()

result = template.replace("__SERVER_IP__", os.environ["SERVER_IP"])
result = result.replace("__CA_CERT__",  ca_cert)
result = result.replace("__TA_KEY__",   ta_key)

out_path = os.environ["OUTPUT_FILE"]
with open(out_path, "w") as f:
    f.write(result)
os.chmod(out_path, 0o600)
PYEOF

echo "Client config written to: ${OUTPUT_FILE}"
echo "Server IP embedded:        ${SERVER_IP}"
echo ""
echo "Transfer this file securely to the user (encrypted email, Signal, etc.)."
echo "The user imports it into their OpenVPN client."
echo ""
echo "When connecting, the client will prompt for:"
echo "  Username  — the VPN username (${USERNAME})"
echo "  Password  — the VPN password"
echo "  OTP       — 6-digit code from Google Authenticator"
