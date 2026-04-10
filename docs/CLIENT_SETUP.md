# SouthVPN — Client Setup Guide

Share this guide with users who need to connect to SouthVPN.

---

## What you need

1. The `.ovpn` config file (provided by your server admin)
2. The username and initial password (provided by your server admin)
3. Google Authenticator app installed on your phone

---

## Step 1: Install Google Authenticator

- **Android:** [Google Authenticator on Play Store](https://play.google.com/store/apps/details?id=com.google.android.apps.authenticator2)
- **iOS:** [Google Authenticator on App Store](https://apps.apple.com/app/google-authenticator/id388497605)

## Step 2: Scan the QR code

Your admin will provide a QR code (displayed in the terminal or sent securely).
Open Google Authenticator → tap **+** → **Scan a QR code**.

After scanning, you'll see a 6-digit code labeled **SouthVPN** that refreshes
every 30 seconds.

## Step 3: Install an OpenVPN client

### Windows / macOS / iOS / Android
Download **OpenVPN Connect** from [openvpn.net/client](https://openvpn.net/client/).

### macOS (alternative)
**Tunnelblick** supports `static-challenge` well:
[tunnelblick.net](https://tunnelblick.net)

### Linux
```bash
# Ubuntu/Debian
sudo apt install openvpn3

# Import config
openvpn3 config-import --config alice.ovpn --name southvpn
```

## Step 4: Import the .ovpn config

### OpenVPN Connect (all platforms)
1. Open OpenVPN Connect
2. Tap/click **+** → **Upload File** (or **Import from file**)
3. Select the `.ovpn` file provided by your admin

### Tunnelblick (macOS)
Double-click the `.ovpn` file — it will be imported automatically.

### Linux (openvpn3)
```bash
openvpn3 config-import --config alice.ovpn --name southvpn
```

---

## Step 5: Connect

When you connect, the client will ask for three things:

| Field | What to enter |
|---|---|
| **Username** | Your VPN username (e.g. `alice`) |
| **Password** | Your VPN password |
| **Google Authenticator OTP** | The 6-digit code from the app |

> On OpenVPN Connect, the OTP field appears as **"Enter Google Authenticator OTP:"**
> after you submit the username and password.

---

## Keeping the server IP up to date

The server does not have a static IP.  When you can't connect, the IP may
have changed.  Ask your admin for the current IP, or if the admin has set up
Google Drive sync, the current IP is in the shared `southvpn_ip.txt` file.

### Update the server IP in your config

Open the `.ovpn` file in a text editor and change the `remote` line:

```
remote <new_ip_address> 1194
```

Re-import the updated file into your OpenVPN client.

### Linux (openvpn3) — update IP without re-importing

```bash
# Remove old config
openvpn3 config-remove --name southvpn

# Edit the file to update the IP, then re-import
sed -i "s/^remote .*/remote <new_ip> 1194/" alice.ovpn
openvpn3 config-import --config alice.ovpn --name southvpn
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `AUTH_FAILED` | Wrong password or OTP — check both. Make sure your phone clock is accurate. |
| Can't connect at all | The server IP may have changed. Ask your admin. |
| OTP not accepted | Check phone time sync. Use NTP. Don't enter expired codes. |
| Lost Google Authenticator | Ask admin for an emergency scratch code. |
| Config lost/stolen | Notify admin immediately to revoke your user. |

---

## Security tips

- Keep your `.ovpn` file private — treat it like a password.
- Never share your TOTP codes with anyone.
- If you suspect your credentials are compromised, contact your admin to revoke and re-enroll.
