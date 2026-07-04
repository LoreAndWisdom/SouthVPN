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

At the end of the install, OpenVPN is **already running and enabled at boot**.
You do not need to start it manually. Confirm with:

```bash
sudo systemctl status openvpn-server@server
# Should show: Active: active (running)
```

See the [Managing the VPN Server](#managing-the-vpn-server) section below for
start/stop/restart commands and log access.

### 1. Configure your router

Before clients can connect from outside your home network, you must forward
UDP port 1194 to the server. See [Router Configuration](#router-configuration)
below — do this before testing any client connections.

### 2. Add your first VPN user

```bash
sudo bash scripts/add_user.sh alice
```

> **Note:** This must be run directly on the server (local terminal or
> non-VPN SSH). It cannot be run from inside a VPN session.

### 3. Generate a client config

```bash
sudo bash scripts/gen_client_config.sh alice /tmp/
```

Transfer `/tmp/alice.ovpn` to the user via a secure channel (encrypted email,
Signal, USB stick, etc.). See [User Management](USER_MANAGEMENT.md) and
[Client Setup](CLIENT_SETUP.md) for the full workflow.

### 4. Verify the IP updater is working

```bash
cat /var/lib/southvpn/current_ip.txt
# IP: 203.0.113.42
# Last updated: 2026-04-10T10:00:00Z

sudo journalctl -u southvpn-ip-updater.service --no-pager
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

## Managing the VPN Server

### How OpenVPN is run

SouthVPN runs as a systemd service named `openvpn-server@server`. The
installer (Step 3) enables it so it **starts automatically on every boot**.

```
/etc/openvpn/server/server.conf   ← config written by installer
/etc/pam.d/openvpn                ← PAM stack (password + TOTP)
```

### Starting the server after installation or a reboot

On a standard Linux server **you don't need to start anything manually**.
Both components are enabled as systemd units and start automatically at
every boot:

| Component | systemd unit | Started by |
|---|---|---|
| VPN server | `openvpn-server@server.service` | boot (enabled in install Step 3) |
| IP updater | `southvpn-ip-updater.timer` | boot (enabled in install Step 5), fires every 5 min |

When you log in (any session — local or SSH), just verify they are up:

```bash
systemctl is-active openvpn-server@server     # → active
systemctl is-active southvpn-ip-updater.timer # → active
```

If either prints `inactive` or `failed`, start it:

```bash
sudo systemctl start openvpn-server@server
sudo systemctl start southvpn-ip-updater.timer
```

And if it doesn't come back after the next reboot, re-enable autostart:

```bash
sudo systemctl enable --now openvpn-server@server
sudo systemctl enable --now southvpn-ip-updater.timer
```

### Running under WSL (Windows Subsystem for Linux)

WSL behaves differently from a normal Linux server in two important ways:

**1. systemd is disabled by default.** Without it, none of the units above
run and `systemctl` fails with *"System has not been booted with systemd"*.
Enable it once:

```bash
# Inside WSL:
sudo tee /etc/wsl.conf > /dev/null << 'EOF'
[boot]
systemd=true
EOF
```

Then from Windows PowerShell:

```powershell
wsl --shutdown
```

Reopen the WSL terminal — `systemctl status openvpn-server@server` should
now work, and the units start automatically whenever the WSL distro starts.

**2. WSL only runs while a session is open.** The WSL virtual machine shuts
down shortly after you close the last terminal window, taking the VPN server
down with it. To keep the server alive, keep a WSL terminal open, or start
the distro headless from Windows at logon:

```powershell
wsl --exec dbus-launch true
```

> **Note:** WSL is fine for testing the install and Drive sync flows, but as
> a permanent VPN server it also needs Windows-side port proxying for
> UDP 1194 and firewall rules on the Windows host. A dedicated Linux
> machine (or VM with bridged networking) is strongly recommended for
> production use.

### Common commands

```bash
# Check if OpenVPN is running right now
sudo systemctl status openvpn-server@server

# Start the server (needed only if it was stopped manually)
sudo systemctl start openvpn-server@server

# Stop the server
sudo systemctl stop openvpn-server@server

# Restart (e.g. after config changes or to kick out all connected clients)
sudo systemctl restart openvpn-server@server

# View recent logs (show last 50 lines)
sudo journalctl -u openvpn-server@server -n 50 --no-pager

# Follow logs in real time (useful when a client is connecting)
sudo journalctl -u openvpn-server@server -f
```

### What healthy output looks like

```
$ sudo systemctl status openvpn-server@server
● openvpn-server@server.service - OpenVPN service for server
     Loaded: loaded (/lib/systemd/system/openvpn-server@.service; enabled)
     Active: active (running) since ...
```

`Active: active (running)` with `enabled` in the Loaded line means OpenVPN is
up and will restart automatically after a reboot.

If the status shows `failed` or `inactive`, run:

```bash
sudo journalctl -u openvpn-server@server -n 30 --no-pager
```

Common causes and fixes:

| Log message | Fix |
|---|---|
| `Cannot open TUN/TAP dev` | Reboot or run `sudo modprobe tun` |
| `openvpn-plugin-auth-pam.so not found` | Re-run `sudo bash install/03_configure_openvpn.sh` |
| `Cannot read key file` | Check `/etc/openvpn/server/` permissions |
| `Options error: You must define DH` | Re-run `sudo bash install/03_configure_openvpn.sh` |

---

## Router Configuration

The server listens on **UDP port 1194**. Because it sits behind your home
router (NAT), the router must forward incoming connections on that port to
the server's LAN IP address. Without this, clients on the internet cannot
reach the VPN.

### Step 1 — Find the server's LAN IP

Run this on the server:

```bash
ip addr show | grep 'inet ' | grep -v '127.0.0.1'
# Example output:
#   inet 192.168.1.42/24 brd 192.168.1.255 scope global eth0
```

Or more concisely:

```bash
hostname -I | awk '{print $1}'
# Example: 192.168.1.42
```

Note this address — you'll need it for the port forwarding rule.

### Step 2 — Reserve that LAN IP (important)

By default, home routers assign LAN IPs via DHCP, so your server's LAN IP
could change after a reboot. If that happens, the port forwarding rule breaks
and clients can no longer connect.

Fix this by creating a **DHCP reservation** (sometimes called a "static DHCP"
or "address reservation") in your router's admin panel:

1. Find the server's MAC address:
   ```bash
   ip link show | grep -A1 'eth0\|ens\|enp' | grep 'link/ether' | awk '{print $2}' | head -1
   # Example: aa:bb:cc:dd:ee:ff
   ```
2. In the router admin panel, go to **DHCP** → **Address Reservation** (or
   **Static Leases** in DD-WRT / OpenWRT)
3. Add a reservation: bind the MAC address to the current LAN IP (e.g. `192.168.1.42`)
4. Save and apply

From this point on, the server always gets the same LAN IP on every boot.

### Step 3 — Set up port forwarding

Log in to your router's admin panel. The address is usually
`http://192.168.1.1` or `http://192.168.0.1` — check the label on your router.

Look for a section called **Port Forwarding**, **Virtual Server**, or
**NAT** (exact name varies by router brand):

| Router brand | Menu path |
|---|---|
| ASUS | **WAN → Virtual Server / Port Forwarding** |
| Netgear | **Advanced → Advanced Setup → Port Forwarding / Port Triggering** |
| TP-Link | **Advanced → NAT Forwarding → Virtual Servers** |
| D-Link | **Advanced → Port Forwarding** |
| Fritz!Box | **Internet → Permit Access → Port Sharing** |
| DD-WRT | **NAT / QoS → Port Forwarding** |
| OpenWRT | **Network → Firewall → Port Forwards** |

Create a new port forwarding rule with these exact values:

| Field | Value |
|---|---|
| Name / Description | `SouthVPN` (anything) |
| Protocol | **UDP** |
| External port (WAN) | **1194** |
| Internal IP / Destination | The server's LAN IP (e.g. `192.168.1.42`) |
| Internal port (LAN) | **1194** |

Save and apply. Some routers require a reboot to activate the rule.

### Step 4 — Verify the port is reachable from the internet

From a device on a **different network** (e.g. mobile data), test that port
1194/UDP is reachable. The easiest way is to attempt a VPN connection with a
client; a successful tunnel confirms the port is open.

Alternatively, from the server itself:

```bash
# Check the server is listening on 1194/UDP
sudo ss -ulnp | grep 1194
# Should show: udp  UNCONN  0  0  0.0.0.0:1194  ...  users:(("openvpn",...))
```

Then from an external machine (not on your LAN):

```bash
# Try to reach the port (requires netcat with UDP support)
nc -zvu <public_ip> 1194
```

Or use an online UDP port checker (search "check UDP port open" — several free
tools exist). Note that UDP port checks are less reliable than TCP; a failed
result doesn't always mean the port is blocked. The definitive test is a
successful VPN client connection.

---

## Verify Everything Works

```bash
# OpenVPN running and enabled at boot?
sudo systemctl status openvpn-server@server

# Server listening on UDP 1194?
sudo ss -ulnp | grep 1194

# IP updater timer active?
systemctl list-timers | grep southvpn

# Current public IP recorded?
cat /var/lib/southvpn/current_ip.txt

# Drive sync logs (if configured)
sudo journalctl -u southvpn-ip-updater.service --no-pager

# Firewall rules (port 1194/UDP should be listed)
sudo ufw status verbose
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| OpenVPN fails to start | `sudo journalctl -u openvpn-server@server -n 30 --no-pager` |
| Client gets `AUTH_FAILED` | Same log — look for PAM errors; verify username/password/TOTP |
| Client times out / can't reach server | Verify port 1194/UDP forwarding at the router; check `sudo ufw status` |
| IP file not updating | `sudo journalctl -u southvpn-ip-updater.service` |
| Drive IP sync not working | Check `service_account.json` and `file_id` in config; verify file is shared with service account email |
| `.ovpn` not uploaded to Drive | Check `ovpn_folder_id` in config; verify folder is shared with service account email; check `/var/lib/southvpn/ovpn_file_ids.ini` |
| Server stops after reboot | `sudo systemctl enable openvpn-server@server` — re-enables autostart |
