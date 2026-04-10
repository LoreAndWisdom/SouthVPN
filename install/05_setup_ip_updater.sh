#!/usr/bin/env bash
# 05_setup_ip_updater.sh — Install ip_updater.py and the systemd timer.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# ── Install Python script ─────────────────────────────────────────────────────
install -m 755 "$REPO_DIR/scripts/ip_updater.py" /usr/local/bin/southvpn-ip-updater.py

# ── Configuration directory ───────────────────────────────────────────────────
mkdir -p /etc/southvpn
chmod 750 /etc/southvpn

# ── State directory (readable by all: clients read the IP file) ───────────────
mkdir -p /var/lib/southvpn
chmod 755 /var/lib/southvpn

# ── Default gdrive_config.ini (placeholder, Drive is optional) ───────────────
if [[ ! -f /etc/southvpn/gdrive_config.ini ]]; then
    cat > /etc/southvpn/gdrive_config.ini << 'EOF'
[gdrive]
# Google Drive file ID (from the file URL: drive.google.com/file/d/<FILE_ID>/view)
# Leave empty to disable Drive sync.
file_id =
filename = southvpn_ip.txt
EOF
    chmod 640 /etc/southvpn/gdrive_config.ini
    echo "Created /etc/southvpn/gdrive_config.ini (Drive sync disabled by default)."
fi

# ── Placeholder service account JSON ─────────────────────────────────────────
if [[ ! -f /etc/southvpn/service_account.json ]]; then
    echo '{}' > /etc/southvpn/service_account.json
    chmod 600 /etc/southvpn/service_account.json
    echo "Created placeholder /etc/southvpn/service_account.json."
    echo "  Replace it with a real Google Service Account key to enable Drive sync."
    echo "  See docs/INSTALL.md for instructions."
fi

# ── Install systemd units ─────────────────────────────────────────────────────
install -m 644 "$REPO_DIR/config/ip_updater/ip_updater.service" \
    /etc/systemd/system/southvpn-ip-updater.service
install -m 644 "$REPO_DIR/config/ip_updater/ip_updater.timer" \
    /etc/systemd/system/southvpn-ip-updater.timer

systemctl daemon-reload
systemctl enable southvpn-ip-updater.timer
systemctl start  southvpn-ip-updater.timer

# ── Run once immediately so current_ip.txt is populated right away ────────────
echo "Running IP updater now..."
systemctl start southvpn-ip-updater.service || true

echo ""
echo "[OK] IP updater installed and scheduled (every 5 minutes)."
echo "Current IP:"
cat /var/lib/southvpn/current_ip.txt 2>/dev/null || echo "  (not yet available — check: journalctl -u southvpn-ip-updater.service)"
