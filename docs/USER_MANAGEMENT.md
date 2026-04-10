# SouthVPN — User Management

## Security Requirement

All user management operations (`add_user.sh`, `remove_user.sh`) **must be
run directly on the server** — via local terminal or a non-VPN SSH session.
Running these scripts from within an active VPN connection is blocked.

This prevents a scenario where a VPN client (potentially compromised) could
enroll new users or revoke others.

---

## Adding a User

```bash
sudo bash scripts/add_user.sh <username>
```

The script will:
1. Prompt for a password (or use `--password <password>` for non-interactive use)
2. Create a Linux system user (no login shell, no home directory)
3. Generate a Google Authenticator TOTP secret
4. Print a QR code to the terminal and 5 emergency scratch codes

**Username rules:** lowercase letters, digits, hyphens, underscores.
Must start with a letter. Maximum 31 characters.

### Example

```
$ sudo bash scripts/add_user.sh alice
Enrolling user: alice

[1/4] System user 'alice' created.
Enter VPN password for alice: ••••••••
Confirm password:             ••••••••
[2/4] Password set.
[3/4] Auth directory created.

Your new secret key is: JBSWY3DPEHPK3PXP
...
[QR CODE displayed here]
...
Your emergency scratch codes are:
  12345678
  87654321
  ...

[4/4] Google Authenticator secret created.

==========================================
  User 'alice' enrolled successfully
==========================================

  The QR code and emergency scratch codes are shown above.
  Share them with the user over a secure channel.

  To generate the client .ovpn config:
    sudo bash scripts/gen_client_config.sh alice /tmp/
```

### Distributing credentials to the user

Communicate these three pieces of information to the user **over separate
secure channels** (e.g. password via Signal, QR code via encrypted email):

1. **Username** — `alice`
2. **Password** — the password set during enrollment
3. **QR code** — to scan with Google Authenticator (or the `otpauth://` URI
   for manual entry)

> The `.ovpn` config file does **not** contain any user-specific secrets —
> it only contains the server's CA certificate and TLS auth key.

---

## Generating a Client Config

```bash
sudo bash scripts/gen_client_config.sh <username> [output_dir] [--ip <ip>]
```

The output `.ovpn` file is self-contained: it includes the CA cert and TLS
auth key inline.  All users share the same base config — authentication is
entirely via PAM (username + password + TOTP).

```bash
# Generate for alice, output to /tmp/
sudo bash scripts/gen_client_config.sh alice /tmp/

# Embed a specific IP (e.g. if ip_updater hasn't run yet)
sudo bash scripts/gen_client_config.sh alice /tmp/ --ip 203.0.113.42
```

Transfer the `.ovpn` file to the user via a secure channel.

> **Note:** The `.ovpn` contains the server's TLS auth key — treat it as
> moderately sensitive.  If a config file is lost or compromised, revoke
> the user and regenerate their config.  Re-generating the TLS auth key
> would require distributing new configs to all users.

---

## Removing a User

### Lock the account (recommended — reversible)

```bash
sudo bash scripts/remove_user.sh <username>
```

This:
- Removes the TOTP secret (immediate effect: next connection attempt fails)
- Locks the Linux account (`usermod -L`)
- Logs the action to `/var/log/southvpn-admin.log`

The user's existing VPN session (if any) will remain active until the
keepalive timeout or until they reconnect and re-authenticate.
To force immediate disconnection, restart OpenVPN:

```bash
sudo systemctl restart openvpn-server@server
```

### Delete the account (permanent)

```bash
sudo bash scripts/remove_user.sh <username> --delete
```

Removes the system user entirely in addition to the steps above.

---

## Re-enrolling a User

To re-enroll a user (e.g. if they got a new phone):

```bash
sudo bash scripts/remove_user.sh alice --delete
sudo bash scripts/add_user.sh alice
sudo bash scripts/gen_client_config.sh alice /tmp/
```

---

## Emergency Scratch Codes

During enrollment, 5 one-time emergency scratch codes are printed.
These can be used instead of a TOTP code if the user loses access to Google
Authenticator (e.g. phone reset).

Store these codes in a secure location (password manager, printed and locked
away).  Each code can only be used once.

---

## Admin Audit Log

All user removal operations are logged to `/var/log/southvpn-admin.log`:

```
2026-04-10T10:15:00Z REMOVED user=alice deleted=false by=admin
```

There is currently no audit log for user additions — monitor
`/etc/passwd` and `/etc/openvpn/server/auth/` changes via your preferred
system auditing tool (e.g. `auditd`).
