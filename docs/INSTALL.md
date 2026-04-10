# SouthVPN — Installation Guide

## Prerequisites

- Ubuntu 22.04+ or Debian 11+
- Root access to the server
- A router/NAT that forwards UDP port 1194 to the server's LAN IP
- (Optional) A Google Cloud account for Drive IP sync

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
certificate using ECDH (prime256v1 curve).  No slow DH parameter generation
is required.

If the PKI already exists (e.g. after a reinstall), use:

```bash
sudo bash install/install_all.sh --skip-pki
```

### Step 3 — Configure OpenVPN

```bash
sudo bash install/03_configure_openvpn.sh
```

- Writes `/etc/openvpn/server/server.conf` (detects CPU architecture automatically)
- Installs `/etc/pam.d/openvpn` (PAM stack: password + TOTP)
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

- Copies `ip_updater.py` to `/usr/local/bin/southvpn-ip-updater.py`
- Creates `/etc/southvpn/` with placeholder config files
- Installs `southvpn-ip-updater.timer` (runs every 5 minutes)
- Runs the updater immediately; current IP appears in `/var/lib/southvpn/current_ip.txt`

---

## After Installation

### 1. Add your first VPN user

```bash
sudo bash scripts/add_user.sh alice
```

> **Note:** This must be run directly on the server (local terminal or
> non-VPN SSH).  It cannot be run from inside a VPN session.

### 2. Generate a client config

```bash
sudo bash scripts/gen_client_config.sh alice /tmp/
```

Transfer `/tmp/alice.ovpn` to the user via a secure channel (encrypted email,
Signal, USB stick, etc.).

### 3. Verify the IP updater is working

```bash
cat /var/lib/southvpn/current_ip.txt
# IP: 203.0.113.42
# Last updated: 2026-04-10T10:00:00Z

journalctl -u southvpn-ip-updater.service --no-pager
```

---

## Google Drive Setup (Optional)

Without this step, the server IP is only available locally in
`/var/lib/southvpn/current_ip.txt`.  Configure Drive sync if you want the IP
to be automatically accessible to clients from anywhere.

### 1. Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (e.g. `SouthVPN`)
3. Enable the **Google Drive API** (APIs & Services → Enable APIs)

### 2. Create a service account

1. Go to **IAM & Admin → Service Accounts**
2. Click **Create Service Account**
3. Name it (e.g. `southvpn-ip-updater`)
4. Click **Create and Continue** → **Done**
5. Click the service account → **Keys** tab → **Add Key → Create new key → JSON**
6. Save the downloaded JSON file

### 3. Create the Drive file

1. Open [drive.google.com](https://drive.google.com)
2. Create a new plain text file named `southvpn_ip.txt`
3. Note the **file ID** from the URL:
   `https://drive.google.com/file/d/**<FILE_ID>**/view`
4. Share the file with the service account email
   (e.g. `southvpn-ip-updater@myproject.iam.gserviceaccount.com`)
   with **Editor** permission

### 4. Configure the server

```bash
# Copy the service account JSON key
sudo cp ~/Downloads/myproject-xxxx.json /etc/southvpn/service_account.json
sudo chmod 600 /etc/southvpn/service_account.json

# Set the file ID
sudo nano /etc/southvpn/gdrive_config.ini
# → set: file_id = <your-file-id>

# Test immediately
sudo systemctl start southvpn-ip-updater.service
sudo journalctl -u southvpn-ip-updater.service --no-pager
# Should show: [Drive] Updated file <id> with IP: x.x.x.x
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

# Check firewall rules
sudo ufw status verbose

# Check the current public IP
cat /var/lib/southvpn/current_ip.txt
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| OpenVPN fails to start | `journalctl -u openvpn-server@server` |
| Client gets `AUTH_FAILED` | `journalctl -u openvpn-server@server` — check PAM errors |
| IP file not updating | `journalctl -u southvpn-ip-updater.service` |
| Drive sync not working | Check `service_account.json` and `file_id` in config |
| Client cannot reach VPN | Verify port 1194/UDP is forwarded at the router |
