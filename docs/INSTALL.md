# SouthVPN — Installation Guide

## Prerequisites

- Ubuntu 22.04+ or Debian 11+
- Root access to the server
- A router/NAT that forwards UDP port 1194 to the server's LAN IP
- (Optional) A Google Cloud account for Drive sync

---

## Quick Install

```bash
git clone https://github.com/loreandwisdom/southvpn
cd southvpn
sudo bash install/install_all.sh
```

The installer runs all five steps automatically and takes 2–5 minutes.

---

## Step-by-Step Install

### Step 1 — Install packages

```bash
sudo bash install/01_install_packages.sh
```

Installs: `openvpn`, `easy-rsa`, `libpam-google-authenticator`, `pamtester`,
`ufw`, `python3`, `python3-googleapi`, `python3-google-auth`, `qrencode`.

### Step 2 — Generate PKI (CA + server certificate)

```bash
sudo bash install/02_setup_pki.sh
```

Creates `/etc/openvpn/easy-rsa/` with a Certificate Authority and server
certificate using ECDH (prime256v1 curve). No slow DH parameter generation
is required.

If the PKI already exists (e.g. after a reinstall):

```bash
sudo bash install/install_all.sh --skip-pki
```

### Step 3 — Configure OpenVPN

```bash
sudo bash install/03_configure_openvpn.sh
```

- Writes `/etc/openvpn/server/server.conf` (detects plugin path automatically)
- Installs `/etc/pam.d/openvpn` (PAM stack: brute-force protection + password + TOTP)
- Starts `openvpn-server@server.service`

### Step 4 — Configure network and firewall

```bash
sudo bash install/04_configure_network.sh
```

- Enables IPv4 forwarding
- Adds UFW rules for port 1194/UDP and 22/TCP
- Adds POSTROUTING NAT masquerade rule to `/etc/ufw/before.rules`

### Step 5 — Install IP updater

```bash
sudo bash install/05_setup_ip_updater.sh
```

- Copies `scripts/ip_updater.py` to `/usr/local/bin/southvpn-ip-updater.py`
- Copies `client/client.conf.template` to `/etc/southvpn/client.conf.template`
- Creates `/etc/southvpn/` with placeholder config files:
  - `service_account.json` — placeholder, replaced during Drive setup
  - `gdrive_config.ini` — Drive file and folder IDs (disabled by default)
- Creates `/var/lib/southvpn/` for runtime state
- Installs and enables `southvpn-ip-updater.timer` (runs every 5 minutes)
- Runs the updater immediately; current IP appears in `/var/lib/southvpn/current_ip.txt`

---

## After Installation

### 1. Add your first VPN user

```bash
sudo bash scripts/add_user.sh alice
```

> **Note:** This must be run directly on the server (local terminal or
> non-VPN SSH). It cannot be run from inside a VPN session.

### 2. Generate a client config

```bash
sudo bash scripts/gen_client_config.sh alice /tmp/
```

Transfer `/tmp/alice.ovpn` to the user via a secure channel (encrypted email,
Signal, USB stick, etc.). See [User Management](USER_MANAGEMENT.md) and
[Client Setup](CLIENT_SETUP.md) for the full workflow.

### 3. Verify the IP updater is working

```bash
cat /var/lib/southvpn/current_ip.txt
# IP: 203.0.113.42
# Last updated: 2026-04-10T10:00:00Z

journalctl -u southvpn-ip-updater.service --no-pager
```

---

## Google Drive Setup (Optional)

Without this step, the current IP is only available locally in
`/var/lib/southvpn/current_ip.txt`. Configure Drive sync to:

- Keep a `southvpn_ip.txt` file on Drive updated with the current IP so
  clients can always find the server, and/or
- Automatically upload updated per-user `.ovpn` configs whenever the IP
  changes so users can re-download without manual edits.

Run the interactive setup wizard:

```bash
sudo bash scripts/setup_gdrive.sh
```

The wizard walks through four steps:

---

### Step 1/4 — Service account JSON key

You need a Google Cloud service account with Drive API access.

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project (e.g. `SouthVPN`) and enable the **Google Drive API**
   (APIs & Services → Enable APIs → Google Drive API)
3. Go to **IAM & Admin → Service Accounts → Create Service Account**
4. Name it (e.g. `southvpn-ip-updater`), click **Create and Continue → Done**
5. Click the service account → **Keys** tab → **Add Key → Create new key → JSON**
6. Download the JSON key file to the server

The wizard prompts for the path to the JSON file, validates it, and copies it
to `/etc/southvpn/service_account.json` (mode `600`, owned by root).

---

### Step 2/4 — Drive file ID for `southvpn_ip.txt`

1. Open [drive.google.com](https://drive.google.com)
2. Create a new plain text file named `southvpn_ip.txt`
3. Share it with the service account email
   (e.g. `southvpn-ip-updater@myproject.iam.gserviceaccount.com`)
   with **Editor** permission
4. Copy the file ID from the URL:
   `https://drive.google.com/file/d/**<FILE_ID>**/view`

The wizard saves this to `/etc/southvpn/gdrive_config.ini` as `file_id`.

Every 5 minutes (or on every IP change), `ip_updater.py` overwrites this file
with the current IP and timestamp.

---

### Step 3/4 — Drive folder for `.ovpn` configs (optional)

When the server IP changes, SouthVPN can automatically regenerate each
enrolled user's `.ovpn` file and upload it to a Google Drive folder.  Users
can then re-download the updated config without any manual edits.

To skip this step, press **Enter** — `.ovpn` auto-upload is disabled.

To enable it:

1. Create a new folder on Google Drive (e.g. `SouthVPN Clients`)
2. Share it with the service account email (Editor permission)
3. Copy the folder ID from the URL:
   `https://drive.google.com/drive/folders/**<FOLDER_ID>**`

The wizard saves this to `/etc/southvpn/gdrive_config.ini` as `ovpn_folder_id`.

On every IP change, `ip_updater.py`:
1. Reads the CA cert and TA key from `/etc/openvpn/server/`
2. Reads the client template from `/etc/southvpn/client.conf.template`
3. Builds a `.ovpn` file for each user found in `/etc/openvpn/server/auth/`
4. Uploads each file to the Drive folder
5. Saves the per-user Drive file IDs to `/var/lib/southvpn/ovpn_file_ids.ini`
   so subsequent IP changes update the same files in-place

> **Note:** The first upload for a user creates a new file in the folder.
> Subsequent IP changes update the same file. To force a fresh file (e.g.
> after deleting it from Drive), remove the user's entry from
> `/var/lib/southvpn/ovpn_file_ids.ini`.

---

### Step 4/4 — Test sync

The wizard runs `ip_updater.py` immediately to verify the Drive connection.
On success, `southvpn_ip.txt` on Drive will contain the current IP.

---

### Resulting config file

After the wizard, `/etc/southvpn/gdrive_config.ini` looks like:

```ini
[gdrive]
file_id = 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs
filename = southvpn_ip.txt
ovpn_folder_id = 1Fz3kGd9HJ2mNpQrStUvWx4YzAbCdEfGh
```

Leave `ovpn_folder_id` empty to disable `.ovpn` auto-upload.

### Manual config alternative

If you prefer to edit the config by hand instead of using the wizard:

```bash
# Copy the service account JSON key
sudo cp ~/Downloads/myproject-xxxx.json /etc/southvpn/service_account.json
sudo chmod 600 /etc/southvpn/service_account.json

# Edit the config
sudo nano /etc/southvpn/gdrive_config.ini
# Set file_id and/or ovpn_folder_id

# Test immediately
sudo systemctl start southvpn-ip-updater.service
sudo journalctl -u southvpn-ip-updater.service --no-pager
```

---

## Router Configuration

Forward UDP port **1194** on your router to the server's LAN IP address.
The exact steps depend on your router model; look for "Port Forwarding" or
"Virtual Server" in the admin panel.

---

## Verify Everything Works

```bash
# Check OpenVPN is running
systemctl status openvpn-server@server

# Check the IP updater timer
systemctl list-timers | grep southvpn

# Check the current public IP
cat /var/lib/southvpn/current_ip.txt

# Check Drive sync (if configured)
journalctl -u southvpn-ip-updater.service --no-pager

# Check firewall rules
sudo ufw status verbose
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| OpenVPN fails to start | `journalctl -u openvpn-server@server` |
| Client gets `AUTH_FAILED` | `journalctl -u openvpn-server@server` — check PAM errors |
| IP file not updating | `journalctl -u southvpn-ip-updater.service` |
| Drive IP sync not working | Check `service_account.json` and `file_id` in config; verify file is shared with SA email |
| `.ovpn` not uploaded to Drive | Check `ovpn_folder_id` in config; verify folder is shared with SA email; check `/var/lib/southvpn/ovpn_file_ids.ini` |
| Client cannot reach VPN | Verify port 1194/UDP is forwarded at the router |
