# SouthVPN — Client Setup Guide

Share this guide with users who need to connect to SouthVPN.

---

## What you need

1. The `.ovpn` config file (provided by your admin)
2. Your VPN username and password (provided by your admin)
3. Your Google Authenticator QR code or secret key (provided by your admin)

---

## Step 1 — Install Google Authenticator

- **Android:** [Google Authenticator on Play Store](https://play.google.com/store/apps/details?id=com.google.android.apps.authenticator2)
- **iOS:** [Google Authenticator on App Store](https://apps.apple.com/app/google-authenticator/id388497605)

## Step 2 — Add the VPN account to Google Authenticator

Your admin will provide a QR code (shown in the terminal or sent securely).

Open Google Authenticator → tap **+** → **Scan a QR code**.

After scanning, you'll see a 6-digit code labeled **SouthVPN:<username>** that
refreshes every 30 seconds. You'll need this code every time you connect.

## Step 3 — Install an OpenVPN client

### Windows / macOS / iOS / Android

Download **OpenVPN Connect** from [openvpn.net/client](https://openvpn.net/client/).

### macOS (alternative)

**Tunnelblick** supports `static-challenge` well: [tunnelblick.net](https://tunnelblick.net)

### Linux

```bash
# Ubuntu/Debian
sudo apt install openvpn3
```

## Step 4 — Import the `.ovpn` config

### OpenVPN Connect (Windows / macOS / iOS / Android)

1. Open OpenVPN Connect
2. Tap/click **+** → **Upload File** (or **Import from file**)
3. Select the `.ovpn` file your admin sent you

### Tunnelblick (macOS)

Double-click the `.ovpn` file — it is imported automatically.

### Linux (openvpn3)

```bash
openvpn3 config-import --config alice.ovpn --name southvpn
```

---

## Step 5 — Connect

When connecting, the client will ask for three things:

| Field | What to enter |
|---|---|
| **Username** | Your VPN username (e.g. `alice`) |
| **Password** | Your VPN password |
| **Google Authenticator OTP** | The current 6-digit code from the app |

> On OpenVPN Connect, the OTP field appears as **"Enter Google Authenticator OTP:"**
> after you enter your username and password.

> **Important:** The OTP code changes every 30 seconds. If authentication
> fails, wait for a fresh code and try again. Make sure your phone's clock
> is accurate (Settings → Date & Time → Set automatically).

---

## When the server IP changes

SouthVPN runs on a dynamic IP. If you can't connect, the server's IP address
may have changed. There are two ways the admin can keep your config current:

---

### Option A — Auto-updated `.ovpn` on Google Drive (easiest)

If your admin has configured Drive `.ovpn` sync, a new `.ovpn` file is
automatically uploaded to Google Drive whenever the server IP changes.
Your admin will share the Drive folder or a direct link to your file.

To apply the update:

1. Download your updated `.ovpn` from the shared Drive link or folder
2. Re-import it into your OpenVPN client (same steps as Step 4 above)

On **OpenVPN Connect**, you can replace an existing profile:
- Go to the profile list → swipe left on the old profile (iOS) or right-click (desktop) → Delete
- Import the new `.ovpn`

On **Linux (openvpn3)**:
```bash
openvpn3 config-remove --name southvpn
openvpn3 config-import --config alice.ovpn --name southvpn
```

Your username, password, and Google Authenticator account **do not change** —
only the server IP embedded in the `.ovpn` file is updated.

---

### Option B — Update the IP manually

If your admin provides the new IP (from `southvpn_ip.txt` on Drive or by
direct message), update your `.ovpn` file by editing the `remote` line:

```
remote <new_ip_address> 1194
```

Then re-import the updated file (same steps as Step 4 above).

On **Linux (openvpn3)**, you can do this in one command:

```bash
sed -i "s/^remote .*/remote <new_ip> 1194/" alice.ovpn
openvpn3 config-remove --name southvpn
openvpn3 config-import --config alice.ovpn --name southvpn
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `AUTH_FAILED` | Wrong password or OTP. Check both. Wait for a fresh OTP code (30-second cycle). |
| Can't connect at all | The server IP may have changed — get the updated `.ovpn` (see above). |
| OTP not accepted | Check phone time sync (Settings → Date & Time → Set automatically). |
| Lost Google Authenticator | Ask your admin for an emergency scratch code. |
| `.ovpn` file lost or stolen | Notify your admin immediately to revoke your account. |
| Still can't connect after IP update | Ask your admin to verify port 1194/UDP is reachable. |

---

## Security tips

- Keep your `.ovpn` file private — treat it like a password.
- Never share your TOTP codes or password with anyone, including your admin.
- Store your emergency scratch codes in a secure place (password manager).
- If you suspect your credentials are compromised, contact your admin to
  revoke and re-enroll your account immediately.
