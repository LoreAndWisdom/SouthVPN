#!/usr/bin/env bash
# install_all.sh — Master SouthVPN installer.
# Runs steps 01–05 in sequence with a pre-flight check.
#
# Usage:
#   sudo bash install/install_all.sh
#   sudo bash install/install_all.sh --skip-pki   # Skip PKI if certs already exist
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Pre-flight checks ─────────────────────────────────────────────────────────
if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: This script must be run as root." >&2
    echo "       Usage: sudo bash install/install_all.sh" >&2
    exit 1
fi

if ! command -v apt-get &>/dev/null; then
    echo "ERROR: apt-get not found. SouthVPN requires Ubuntu 22.04+ or Debian 11+." >&2
    exit 1
fi

SKIP_PKI=false
for arg in "$@"; do
    [[ "$arg" == "--skip-pki" ]] && SKIP_PKI=true
done

# ── Banner ────────────────────────────────────────────────────────────────────
echo "========================================"
echo "  SouthVPN Installer"
echo "========================================"
echo ""

# ── Step 1: Packages ──────────────────────────────────────────────────────────
echo "--- [1/5] Installing packages ---"
bash "$SCRIPT_DIR/01_install_packages.sh"
echo ""

# ── Step 2: PKI ───────────────────────────────────────────────────────────────
if [[ "$SKIP_PKI" == "false" ]]; then
    echo "--- [2/5] Setting up PKI (CA + server certificate) ---"
    bash "$SCRIPT_DIR/02_setup_pki.sh"
else
    echo "--- [2/5] Skipping PKI (--skip-pki flag set) ---"
fi
echo ""

# ── Step 3: OpenVPN ───────────────────────────────────────────────────────────
echo "--- [3/5] Configuring OpenVPN ---"
bash "$SCRIPT_DIR/03_configure_openvpn.sh"
echo ""

# ── Step 4: Network / Firewall ────────────────────────────────────────────────
echo "--- [4/5] Configuring network and firewall ---"
bash "$SCRIPT_DIR/04_configure_network.sh"
echo ""

# ── Step 5: IP Updater ────────────────────────────────────────────────────────
echo "--- [5/5] Installing IP updater ---"
bash "$SCRIPT_DIR/05_setup_ip_updater.sh"
echo ""

# ── Summary ───────────────────────────────────────────────────────────────────
echo "========================================"
echo "  Installation complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Add a VPN user:"
echo "       sudo bash scripts/add_user.sh <username>"
echo ""
echo "  2. Generate a client .ovpn config:"
echo "       sudo bash scripts/gen_client_config.sh <username> /tmp/"
echo ""
echo "  3. (Optional) Enable Google Drive sync:"
echo "       See docs/INSTALL.md — 'Google Drive Setup' section."
echo ""
echo "Current server public IP:"
cat /var/lib/southvpn/current_ip.txt 2>/dev/null \
    || echo "  Not available yet. Run: systemctl start southvpn-ip-updater.service"
echo ""
