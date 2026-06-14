#!/usr/bin/env bash
# setup_gdrive.sh — Interactive Google Drive sync setup for SouthVPN.
#
# Guides the operator through:
#   1. Copying the service account JSON key to /etc/southvpn/
#   2. Setting the Drive file ID in gdrive_config.ini
#   3. Running a test sync to verify everything works
#
# Usage:
#   sudo bash scripts/setup_gdrive.sh
#
# Prerequisites (do these in the browser first):
#   a) console.cloud.google.com → new project → enable Google Drive API
#   b) IAM & Admin → Service Accounts → Create → download JSON key
#   c) drive.google.com → create a plain-text file named southvpn_ip.txt
#      → share it with the service account email (Editor permission)

set -euo pipefail
umask 0077  # the key copy must never be group/world readable, even transiently

CONFIG_DIR="/etc/southvpn"
SA_FILE="${CONFIG_DIR}/service_account.json"
CFG_FILE="${CONFIG_DIR}/gdrive_config.ini"
UPDATER="/usr/local/bin/southvpn-ip-updater.py"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'

# ── Root check ────────────────────────────────────────────────────────────────
if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: Run as root: sudo bash scripts/setup_gdrive.sh" >&2
    exit 1
fi

echo ""
echo -e "${BOLD}══════════════════════════════════════════${NC}"
echo -e "${BOLD}  SouthVPN — Google Drive Sync Setup${NC}"
echo -e "${BOLD}══════════════════════════════════════════${NC}"
echo ""
echo "This script links SouthVPN to a Google Drive file so that your"
echo "current public IP is automatically kept up to date there."
echo ""
echo -e "${YELLOW}Before continuing, make sure you have:${NC}"
echo "  1. A Google Cloud project with the Drive API enabled"
echo "  2. A service account JSON key file downloaded to this machine"
echo "  3. A plain-text file named 'southvpn_ip.txt' on Google Drive"
echo "     shared with the service account email (Editor permission)"
echo "  4. (Optional) A Google Drive folder for per-user .ovpn configs"
echo "     shared with the service account email (Editor permission)"
echo ""
echo "Full instructions: docs/INSTALL.md → 'Google Drive Setup'"
echo ""
read -rp "Press Enter to continue, or Ctrl+C to abort..."
echo ""

# ── Step 1: Service account JSON key ─────────────────────────────────────────
echo -e "${BOLD}[Step 1/4] Service account JSON key${NC}"
echo ""
echo "You downloaded a JSON key file when you created the service account."
echo "Example filename: myproject-a1b2c3d4e5f6.json"
echo ""

while true; do
    read -rp "Full path to the JSON key file: " KEY_PATH
    KEY_PATH="${KEY_PATH/#\~/$HOME}"  # expand leading ~

    if [[ ! -f "$KEY_PATH" ]]; then
        echo -e "${RED}File not found: ${KEY_PATH}${NC}"
        continue
    fi

    # Validate it looks like a service account JSON.
    # KEY_PATH is passed via environment, never interpolated into Python code.
    if ! KEY_PATH="$KEY_PATH" python3 - << 'PYEOF' 2>/dev/null
import json, os, sys
try:
    d = json.load(open(os.environ["KEY_PATH"]))
    if d.get("type") != "service_account":
        sys.exit(1)
    print("Service account email:", d.get("client_email", "(unknown)"))
except Exception as e:
    print("ERROR:", e, file=sys.stderr)
    sys.exit(1)
PYEOF
    then
        echo -e "${RED}This does not look like a valid service account key.${NC}"
        echo "Make sure you downloaded the JSON key (not a p12 or OAuth token)."
        echo "The file should contain: \"type\": \"service_account\""
        KEY_PATH="$KEY_PATH" python3 - << 'PYEOF'
import json, os
try:
    d = json.load(open(os.environ["KEY_PATH"]))
    print("  File type field:", repr(d.get("type", "(missing)")))
except Exception as e:
    print("  Parse error:", e)
PYEOF
        continue
    fi

    break
done

cp "$KEY_PATH" "$SA_FILE"
chmod 600 "$SA_FILE"
chown root:root "$SA_FILE"
echo -e "${GREEN}✓ Key copied to ${SA_FILE}${NC}"
echo ""

# ── Step 2: Drive file ID ─────────────────────────────────────────────────────
echo -e "${BOLD}[Step 2/4] Google Drive file ID (for southvpn_ip.txt)${NC}"
echo ""
echo "Open the 'southvpn_ip.txt' file in Google Drive and look at the URL:"
echo ""
echo -e "  ${YELLOW}https://drive.google.com/file/d/${BOLD}<FILE_ID>${NC}${YELLOW}/view${NC}"
echo ""
echo "The FILE_ID is the long string of letters, numbers and underscores"
echo "between /d/ and /view.  Example: 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs"
echo ""

while true; do
    read -rp "Paste the file ID here: " FILE_ID
    FILE_ID="${FILE_ID// /}"  # strip accidental spaces

    if [[ -z "$FILE_ID" ]]; then
        echo "File ID cannot be empty."
        continue
    fi

    # Basic sanity: only allow chars found in Drive file IDs
    if [[ ! "$FILE_ID" =~ ^[A-Za-z0-9_-]+$ ]]; then
        echo -e "${RED}That doesn't look like a valid file ID (unexpected characters).${NC}"
        echo "Copy only the ID portion, not the full URL."
        continue
    fi

    break
done

# ── Step 3: Drive folder for .ovpn files (optional) ──────────────────────────
echo -e "${BOLD}[Step 3/4] Google Drive folder for .ovpn client configs (optional)${NC}"
echo ""
echo "When the server IP changes, SouthVPN can automatically regenerate each"
echo "user's .ovpn file and upload it to a Google Drive folder."
echo ""
echo "To enable this feature:"
echo "  a) Create a folder on Google Drive (e.g. 'SouthVPN Clients')"
echo "  b) Share it with the service account email (Editor permission)"
echo "  c) Copy the folder ID from the URL:"
echo ""
echo -e "     ${YELLOW}https://drive.google.com/drive/folders/${BOLD}<FOLDER_ID>${NC}"
echo ""
echo "Press Enter to skip this step and keep automatic .ovpn upload disabled."
echo ""

FOLDER_ID=""
while true; do
    read -rp "Paste the folder ID here (or press Enter to skip): " FOLDER_ID
    FOLDER_ID="${FOLDER_ID// /}"  # strip accidental spaces

    if [[ -z "$FOLDER_ID" ]]; then
        echo "  (Skipped — .ovpn auto-upload disabled)"
        break
    fi

    if [[ ! "$FOLDER_ID" =~ ^[A-Za-z0-9_-]+$ ]]; then
        echo -e "${RED}That doesn't look like a valid folder ID (unexpected characters).${NC}"
        echo "Copy only the ID portion from the URL, not the full URL."
        continue
    fi

    echo -e "${GREEN}✓ Folder ID accepted.${NC}"
    break
done
echo ""

# Write the config file (both file_id and ovpn_folder_id)
cat > "$CFG_FILE" << EOF
[gdrive]
# Google Drive file ID — do not change this line by hand, use setup_gdrive.sh
file_id = ${FILE_ID}
filename = southvpn_ip.txt
# Google Drive folder ID for per-user .ovpn files (leave empty to disable)
ovpn_folder_id = ${FOLDER_ID}
EOF
chmod 640 "$CFG_FILE"
echo -e "${GREEN}✓ Config saved to ${CFG_FILE}${NC}"
echo ""

# ── Step 4: Test sync ─────────────────────────────────────────────────────────
echo -e "${BOLD}[Step 4/4] Test sync${NC}"
echo ""
echo "Running the IP updater now to verify the Drive connection..."
echo ""

if python3 "$UPDATER"; then
    echo ""
    echo -e "${GREEN}✓ Drive sync succeeded!${NC}"
    echo ""
    echo "Check your Google Drive — 'southvpn_ip.txt' should now contain:"
    cat /var/lib/southvpn/current_ip.txt 2>/dev/null || echo "  (IP file not yet written)"
else
    echo ""
    echo -e "${RED}✗ IP updater exited with an error.${NC}"
    echo ""
    echo "Common causes:"
    echo "  • The Drive file was not shared with the service account email"
    echo "  • The file ID is wrong"
    echo "  • The Google Drive API is not enabled on the Cloud project"
    echo ""
    echo "Re-run this script once you've fixed the issue:"
    echo "  sudo bash scripts/setup_gdrive.sh"
    exit 1
fi

echo ""
echo -e "${BOLD}══════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  Google Drive sync is now active!${NC}"
echo -e "${BOLD}══════════════════════════════════════════${NC}"
echo ""
echo "The IP updater runs every 5 minutes via systemd timer."
echo "To check it manually at any time:"
echo ""
echo "  sudo systemctl start southvpn-ip-updater.service"
echo "  journalctl -u southvpn-ip-updater.service --no-pager"
echo ""
