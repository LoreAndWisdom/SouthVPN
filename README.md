# SouthVPN

A private VPN server for people without a static public IP and a spare machine at home.

## Features

- **OpenVPN** server with username + password + TOTP multi-factor authentication
- **MFA** via Google Authenticator — required for every connection
- **Dynamic IP** support: automatically detects the current public IP every 5 minutes
- **Google Drive sync** (optional): publishes the IP to a Drive text file so clients can always find the server
- **Auto .ovpn updates** (optional): regenerates and uploads per-user `.ovpn` configs to Drive whenever the IP changes — clients just re-download
- **Easy setup**: single installer script, runs on Ubuntu 22.04 / Debian 11+
- **User management**: simple scripts to add/remove users with full MFA enrollment

## How it works

```
Client                          Server
──────                          ──────
OpenVPN Connect   ─── UDP 1194 ──►  OpenVPN
  username                           │
  password              PAM ◄────────┘
  OTP (Google Auth)      ├── pam_unix               (password check)
                         ├── pam_google_authenticator (TOTP check)
                         └── pam_faillock            (brute-force lockout)
```

Every 5 minutes the systemd timer runs the IP updater:

```
southvpn-ip-updater  ──► /var/lib/southvpn/current_ip.txt   (always)
                     ──► Drive: southvpn_ip.txt              (if configured)
                     ──► Drive: <user>.ovpn per user         (if configured)
```

## Quick Start

```bash
git clone https://github.com/loreandwisdom/southvpn
cd southvpn
sudo bash install/install_all.sh

# Add a user
sudo bash scripts/add_user.sh alice

# Generate and distribute the client config
sudo bash scripts/gen_client_config.sh alice /tmp/
# → transfer /tmp/alice.ovpn to alice securely
```

> **Security:** `add_user.sh` must be run directly on the server (local
> terminal or non-VPN SSH).  It cannot be executed from inside a VPN session.

The VPN server and the IP updater start automatically at the end of the
install and on every boot — no manual start needed. To check, start, or stop
them (including WSL-specific notes), see
[Managing the VPN Server](docs/INSTALL.md#managing-the-vpn-server).

### Optional: Enable Google Drive sync

```bash
sudo bash scripts/setup_gdrive.sh
```

Interactive wizard — configure IP text file sync and/or automatic `.ovpn`
upload to a Drive folder.  See [docs/INSTALL.md](docs/INSTALL.md#google-drive-setup-optional) for details.

## Project Structure

```
install/        Installer scripts (run once)
config/         Config templates (OpenVPN, PAM, systemd)
scripts/        Operational scripts (user management, IP updater, Drive setup)
client/         Client .ovpn template
docs/           Documentation
tests/          Test suite (unit, fuzz, security, integration)
```

## Documentation

- [Installation Guide](docs/INSTALL.md)
- [User Management](docs/USER_MANAGEMENT.md)
- [Client Setup Guide](docs/CLIENT_SETUP.md)

## Testing

```bash
# Unit + fuzz tests (no root required)
pip install pytest hypothesis pyotp
bash tests/run_tests.sh

# All tests including integration + security (requires root + full install)
sudo bash tests/run_tests.sh --all
```

## License

MIT © 2026 Lorenzo Pigozzo — see [LICENSE](LICENSE).
