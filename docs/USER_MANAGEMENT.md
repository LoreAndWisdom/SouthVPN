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

**Username rules:** lowercase letters, digits, hyphens, underscores.
Must start with a letter. Maximum 31 characters.

The script will:

1. Create a Linux system user (no login shell, no home directory) — skipped
   if the user already exists
2. Prompt for a password (minimum 12 characters, no echo) — skipped if the
   user already exists
3. Create `/etc/openvpn/server/auth/<username>/` owned by `nobody:nogroup`
4. Generate a Google Authenticator TOTP secret as user `nobody`
5. Print a QR code to the terminal and 5 one-time emergency scratch codes

### Example output

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

Communicate these items to the user **over separate secure channels**
(e.g. password via Signal, QR code via encrypted email):

1. **Username** — `alice`
2. **Password** — the password set during enrollment
3. **QR code** — to scan with Google Authenticator

> The `.ovpn` config file does **not** contain any user-specific secrets —
> it only contains the server's CA certificate and TLS auth key.

---

## Generating a Client Config

```bash
sudo bash scripts/gen_client_config.sh <username> [output_dir] [--ip <ip>]
```

The output `.ovpn` file is self-contained: it embeds the CA cert and TLS
auth key inline. All users share the same base config — authentication is
entirely via PAM (username + password + TOTP).

```bash
# Generate for alice, output to /tmp/
sudo bash scripts/gen_client_config.sh alice /tmp/

# Embed a specific IP (e.g. if the IP updater hasn't run yet)
sudo bash scripts/gen_client_config.sh alice /tmp/ --ip 203.0.113.42
```

The script reads the server IP from `/var/lib/southvpn/current_ip.txt`. The
`--ip` flag overrides this for one-off generation.

Transfer the `.ovpn` file to the user via a secure channel (encrypted email,
Signal, USB stick).

> **Note:** The `.ovpn` contains the server's TLS auth key — treat it as
> moderately sensitive. If a config file is lost or compromised, revoke the
> user and regenerate. Re-generating the TLS auth key itself would require
> issuing new configs to all users.

### Automatic .ovpn updates via Google Drive

If `ovpn_folder_id` is configured in `/etc/southvpn/gdrive_config.ini`,
the IP updater automatically regenerates and re-uploads each enrolled user's
`.ovpn` whenever the server IP changes. Users can then re-download their
config from the shared Drive folder instead of requiring admin intervention.

The first time an `.ovpn` is uploaded for a user, a new file is created in
the Drive folder. On subsequent IP changes, the same file is updated in-place.
Drive file IDs are tracked in `/var/lib/southvpn/ovpn_file_ids.ini`.

The initial `.ovpn` distribution (after `add_user.sh`) still requires the
admin to run `gen_client_config.sh` and send the file manually, since the
user needs the file to connect in the first place.

---

## Removing a User

### Lock the account (recommended — reversible)

```bash
sudo bash scripts/remove_user.sh <username>
```

This:
- Removes the TOTP secret directory (immediate effect: next auth attempt fails)
- Locks the Linux account (`usermod -L`)
- Logs the action to `/var/log/southvpn-admin.log`

The user's existing VPN session (if any) remains active until the keepalive
timeout or until they reconnect and re-authenticate. To force immediate
disconnection, restart OpenVPN:

```bash
sudo systemctl restart openvpn-server@server
```

### Delete the account (permanent)

```bash
sudo bash scripts/remove_user.sh <username> --delete
```

Removes the system user entirely in addition to the steps above.

> **Drive cleanup:** Removing a user does not delete their `.ovpn` file from
> Google Drive. If you want to remove it, delete it manually from Drive and
> remove the user's entry from `/var/lib/southvpn/ovpn_file_ids.ini`.

---

## Re-enrolling a User

To re-enroll a user (e.g. new phone or forgotten password):

```bash
sudo bash scripts/remove_user.sh alice --delete
sudo bash scripts/add_user.sh alice
sudo bash scripts/gen_client_config.sh alice /tmp/
# → send the new .ovpn to alice
```

If `.ovpn` auto-upload to Drive is enabled and the old Drive file is still
present, the IP updater will update it on the next IP change. If you deleted
the Drive file and want a fresh upload, remove alice's entry from
`/var/lib/southvpn/ovpn_file_ids.ini`:

```bash
sudo nano /var/lib/southvpn/ovpn_file_ids.ini
# Delete the alice = ... line, save, exit.
# The next IP change will create a new file in the Drive folder.
```

---

## Emergency Scratch Codes

During enrollment, 5 one-time emergency scratch codes are printed.
These can be used instead of a TOTP code if the user loses access to their
Google Authenticator (e.g. new phone).

Store these codes in a secure location (password manager, or printed and
locked away). Each code can only be used once.

If all scratch codes are exhausted, the admin must re-enroll the user.

---

## Admin Audit Log

All user removal operations are logged to `/var/log/southvpn-admin.log`:

```
2026-04-10T10:15:00Z REMOVED user=alice deleted=false by=admin
```

User additions are not currently logged to this file. Monitor
`/etc/passwd` and `/etc/openvpn/server/auth/` changes via your preferred
system auditing tool (e.g. `auditd`).
