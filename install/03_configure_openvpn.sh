#!/usr/bin/env bash
# 03_configure_openvpn.sh — Write server.conf and PAM config, start OpenVPN.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SERVER_DIR="/etc/openvpn/server"

# ── Detect plugin path by CPU architecture ────────────────────────────────────
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  PLUGIN_PATH="/usr/lib/x86_64-linux-gnu/openvpn/plugins/openvpn-plugin-auth-pam.so" ;;
    aarch64) PLUGIN_PATH="/usr/lib/aarch64-linux-gnu/openvpn/plugins/openvpn-plugin-auth-pam.so" ;;
    armv7l)  PLUGIN_PATH="/usr/lib/arm-linux-gnueabihf/openvpn/plugins/openvpn-plugin-auth-pam.so" ;;
    *)
        PLUGIN_PATH=""
        ;;
esac

# Fall back to a filesystem search if the arch-specific path doesn't exist.
if [[ -z "$PLUGIN_PATH" || ! -f "$PLUGIN_PATH" ]]; then
    PLUGIN_PATH=$(find /usr/lib -name openvpn-plugin-auth-pam.so 2>/dev/null | head -1)
fi

if [[ -z "$PLUGIN_PATH" || ! -f "$PLUGIN_PATH" ]]; then
    echo "ERROR: openvpn-plugin-auth-pam.so not found anywhere under /usr/lib." >&2
    echo "       Install the openvpn package first." >&2
    exit 1
fi
echo "PAM plugin: ${PLUGIN_PATH}"

# ── Write server.conf from template ──────────────────────────────────────────
echo "Writing /etc/openvpn/server/server.conf..."
sed "s|__PLUGIN_PATH__|${PLUGIN_PATH}|g" \
    "$REPO_DIR/config/server.conf.template" \
    > /etc/openvpn/server/server.conf

# ── Install PAM service file ──────────────────────────────────────────────────
echo "Installing /etc/pam.d/openvpn..."
cp "$REPO_DIR/config/pam.d/openvpn" /etc/pam.d/openvpn

# ── Create auth and CCD directories ──────────────────────────────────────────
mkdir -p "$SERVER_DIR/auth"
chown nobody:nogroup "$SERVER_DIR/auth"
chmod 700 "$SERVER_DIR/auth"

mkdir -p "$SERVER_DIR/ccd"

# ── Log directory ─────────────────────────────────────────────────────────────
mkdir -p /var/log/openvpn

# ── Enable and (re)start OpenVPN ──────────────────────────────────────────────
systemctl enable openvpn-server@server
systemctl restart openvpn-server@server

echo "[OK] OpenVPN configured and started."
systemctl --no-pager status openvpn-server@server || true
