# SouthVPN

A private VPN server for people without a static public IP and a spare machine at home.

## Features

- **OpenVPN** server with username + password authentication
- **MFA** via Google Authenticator (TOTP) — required for every connection
- **Dynamic IP** support: automatically publishes the current public IP to a local file, with optional Google Drive sync so clients can always find the server
- **Easy setup**: single installer script, runs on Ubuntu 22.04 / Debian 11+
- **User management**: simple scripts to add/remove users with full MFA enrollment

## How it works

```
Client                          Server
──────                          ──────
OpenVPN Connect   ─── UDP 1194 ──►  OpenVPN
  username                           │
  password              PAM ◄────────┘
  OTP (Google Auth)      ├── pam_unix     (password check)
                         └── pam_google_authenticator (TOTP check)
```

The server detects its public IP every 5 minutes and writes it to
`/var/lib/southvpn/current_ip.txt`.  If Google Drive sync is configured,
the file is also kept updated on Drive so clients can always find the
current address.

## Quick Start

```bash
git clone https://github.com/loreandwisdom/southvpn
cd southvpn
sudo bash install/install_all.sh

# Add a user
sudo bash scripts/add_user.sh alice

# Generate the client .ovpn config
sudo bash scripts/gen_client_config.sh alice /tmp/
# → transfer /tmp/alice.ovpn to the user
```

> **Security:** `add_user.sh` must be run directly on the server — it cannot
> be executed from inside an active VPN session.

## Project Structure

```
install/        Installer scripts (run these once)
config/         Config file templates (OpenVPN, PAM, systemd)
scripts/        Operational scripts (user management, IP updater)
client/         Client .ovpn template
docs/           Documentation
tests/          Test suite (unit, integration, security, fuzz)
```

## Documentation

- [Installation Guide](docs/INSTALL.md)
- [User Management](docs/USER_MANAGEMENT.md)
- [Client Setup](docs/CLIENT_SETUP.md)

## Testing

```bash
# Unit + fuzz tests (no root required)
pip install pytest hypothesis pyotp
bash tests/run_tests.sh

# All tests including integration + security (requires root + full install)
sudo bash tests/run_tests.sh --all
```

## License

MIT — see [LICENSE](LICENSE).
