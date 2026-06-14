#!/usr/bin/env python3
"""
SouthVPN IP Updater
===================
Detects the current public IP address and:

  Level 1 (always): writes /var/lib/southvpn/current_ip.txt
  Level 2 (optional): syncs to Google Drive if /etc/southvpn/service_account.json
                      contains a valid service account key and gdrive_config.ini
                      has a file_id set.
  Level 3 (optional): regenerates per-user .ovpn configs and uploads them to a
                      Google Drive folder when the IP changes, if ovpn_folder_id
                      is set in gdrive_config.ini.

The script is designed to be called by the southvpn-ip-updater.service systemd
unit.  All output is captured by journald.
"""

import configparser
import json
import os
import re
import ssl
import sys
import urllib.request
from datetime import datetime, timezone

# ── Constants ──────────────────────────────────────────────────────────────────
LOCAL_IP_FILE = "/var/lib/southvpn/current_ip.txt"
CONFIG_FILE = "/etc/southvpn/gdrive_config.ini"
SERVICE_ACCOUNT_FILE = "/etc/southvpn/service_account.json"
AUTH_DIR = "/etc/openvpn/server/auth"
CA_CERT_FILE = "/etc/openvpn/server/ca.crt"
TA_KEY_FILE = "/etc/openvpn/server/ta.key"
CLIENT_TEMPLATE_FILE = "/etc/southvpn/client.conf.template"
OVPN_FILE_IDS_FILE = "/var/lib/southvpn/ovpn_file_ids.ini"

IP_SOURCES = [
    "https://api.ipify.org",
    "https://ifconfig.me",
    "https://ipinfo.io/ip",
]

# Strict IPv4 pattern — no leading zeros, all octets 0–255
IPV4_RE = re.compile(
    r"^((25[0-5]|2[0-4]\d|1\d{2}|[1-9]\d|\d)\.){3}"
    r"(25[0-5]|2[0-4]\d|1\d{2}|[1-9]\d|\d)$"
)


# ── IP detection ───────────────────────────────────────────────────────────────

def parse_ip_response(raw_bytes: bytes) -> "str | None":
    """Parse raw HTTP response bytes into a valid IPv4 string, or return None.

    Accepts any byte input without raising exceptions — safe to fuzz.
    """
    try:
        raw = raw_bytes.decode("ascii", errors="replace").strip()[:64]
        if IPV4_RE.match(raw):
            return raw
    except Exception:
        pass
    return None


def fetch_public_ip() -> "str | None":
    """Try each IP source in order; return the first valid IPv4 address."""
    # Explicit strict TLS: hostname check + certificate verification required.
    tls_context = ssl.create_default_context()
    tls_context.check_hostname = True
    tls_context.verify_mode = ssl.CERT_REQUIRED

    for url in IP_SOURCES:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "SouthVPN-IPUpdater/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10, context=tls_context) as resp:
                raw = resp.read(64)
                ip = parse_ip_response(raw)
                if ip:
                    return ip
                print(f"[WARN] {url} returned non-IP: {raw!r}", file=sys.stderr)
        except Exception as exc:
            print(f"[WARN] {url} failed: {exc}", file=sys.stderr)
    return None


# ── Local file operations ──────────────────────────────────────────────────────

def read_local_ip() -> "str | None":
    """Return the IP stored in current_ip.txt, or None if missing/invalid."""
    try:
        with open(LOCAL_IP_FILE) as f:
            for line in f:
                m = re.match(r"IP:\s*(\S+)", line)
                if m and IPV4_RE.match(m.group(1)):
                    return m.group(1)
    except FileNotFoundError:
        pass
    return None


def write_local_ip(ip: str) -> None:
    """Write IP and UTC timestamp to current_ip.txt atomically."""
    os.makedirs(os.path.dirname(LOCAL_IP_FILE), exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    content = f"IP: {ip}\nLast updated: {ts}\n"
    tmp = LOCAL_IP_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.chmod(tmp, 0o644)
    os.replace(tmp, LOCAL_IP_FILE)
    print(f"[LOCAL] Written: {content.strip()}")


# ── Google Drive sync (optional) ───────────────────────────────────────────────

def drive_update(ip: str) -> None:
    """Sync the current IP to Google Drive if credentials are configured.

    Silently skips (with a log message) if:
    - service_account.json does not exist
    - service_account.json is a placeholder (no 'type' field or not a service_account)
    - file_id is not set in gdrive_config.ini
    - google-api-python-client is not installed

    Exits with code 1 on unexpected Drive API errors so systemd logs the failure.
    """
    # ── Check service account file ────────────────────────────────────────────
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print("[Drive] Skipped: service_account.json not found.")
        return

    try:
        with open(SERVICE_ACCOUNT_FILE) as f:
            sa = json.load(f)
        if sa.get("type") != "service_account":
            print("[Drive] Skipped: service_account.json is a placeholder (no valid 'type').")
            return
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[Drive] Skipped: cannot read service_account.json: {exc}")
        return

    # ── Read config ───────────────────────────────────────────────────────────
    if not os.path.exists(CONFIG_FILE):
        print("[Drive] Skipped: gdrive_config.ini not found.")
        return

    config = configparser.RawConfigParser()  # RawConfigParser avoids % interpolation errors
    try:
        config.read(CONFIG_FILE, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError) as exc:
        print(f"[Drive] Skipped: malformed gdrive_config.ini: {exc}")
        return

    file_id = config.get("gdrive", "file_id", fallback="").strip()
    if not file_id:
        print("[Drive] Skipped: file_id not set in gdrive_config.ini.")
        return

    # ── Upload ────────────────────────────────────────────────────────────────
    try:
        from google.oauth2 import service_account  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
        from googleapiclient.http import MediaInMemoryUpload  # type: ignore
    except ImportError:
        print("[Drive] Skipped: google-api-python-client not installed.")
        return

    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=["https://www.googleapis.com/auth/drive.file"],
        )
        service = build("drive", "v3", credentials=creds, cache_discovery=False)

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = f"IP: {ip}\nLast updated: {ts}\n".encode()
        media = MediaInMemoryUpload(body, mimetype="text/plain", resumable=False)
        service.files().update(fileId=file_id, media_body=media).execute()
        print(f"[Drive] Updated file {file_id} with IP: {ip}")

    except Exception as exc:
        # Drive is optional — log the error but do not exit with a failure code.
        # A transient network issue or misconfiguration should not mark the
        # systemd service as failed and trigger noisy restart loops.
        # Log only type + truncated message: API errors can embed request
        # details that don't belong in logs.
        print(f"[Drive] ERROR: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)


# ── .ovpn config generation and Drive upload ──────────────────────────────────

def _list_enrolled_users() -> list:
    """Return sorted list of enrolled VPN usernames (directories in AUTH_DIR)."""
    if not os.path.isdir(AUTH_DIR):
        return []
    return sorted(
        name for name in os.listdir(AUTH_DIR)
        if os.path.isdir(os.path.join(AUTH_DIR, name))
        and re.match(r"^[a-z][a-z0-9_-]*$", name)
    )


def _build_ovpn(ip: str) -> "str | None":
    """Build .ovpn file content for the given server IP. Returns None on error."""
    try:
        template = open(CLIENT_TEMPLATE_FILE).read()
        ca_cert = open(CA_CERT_FILE).read().strip()
        ta_key = open(TA_KEY_FILE).read().strip()
    except OSError as exc:
        print(f"[OVPN] Cannot read config files: {exc}", file=sys.stderr)
        return None
    result = template.replace("__SERVER_IP__", ip)
    result = result.replace("__CA_CERT__", ca_cert)
    result = result.replace("__TA_KEY__", ta_key)
    return result


def _read_ovpn_file_ids() -> dict:
    """Return {username: drive_file_id} persisted from previous uploads."""
    cfg = configparser.RawConfigParser()
    try:
        cfg.read(OVPN_FILE_IDS_FILE, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError):
        return {}
    return dict(cfg.items("ovpn_file_ids")) if cfg.has_section("ovpn_file_ids") else {}


def _write_ovpn_file_ids(file_ids: dict) -> None:
    """Persist {username: drive_file_id} atomically to OVPN_FILE_IDS_FILE."""
    cfg = configparser.RawConfigParser()
    cfg["ovpn_file_ids"] = file_ids
    os.makedirs(os.path.dirname(OVPN_FILE_IDS_FILE), exist_ok=True)
    tmp = OVPN_FILE_IDS_FILE + ".tmp"
    with open(tmp, "w") as f:
        cfg.write(f)
    os.replace(tmp, OVPN_FILE_IDS_FILE)


def ovpn_update(ip: str) -> None:
    """Regenerate per-user .ovpn configs and upload to Google Drive when IP changes.

    Silently skips if Drive is not configured or ovpn_folder_id is not set.
    Per-user Drive file IDs are persisted in OVPN_FILE_IDS_FILE so subsequent
    calls update the same file rather than creating duplicates.
    """
    # ── Check service account ─────────────────────────────────────────────────
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print("[OVPN] Skipped: service_account.json not found.")
        return

    try:
        with open(SERVICE_ACCOUNT_FILE) as f:
            sa = json.load(f)
        if sa.get("type") != "service_account":
            print("[OVPN] Skipped: service_account.json is a placeholder.")
            return
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[OVPN] Skipped: cannot read service_account.json: {exc}")
        return

    # ── Read config ───────────────────────────────────────────────────────────
    if not os.path.exists(CONFIG_FILE):
        print("[OVPN] Skipped: gdrive_config.ini not found.")
        return

    config = configparser.RawConfigParser()
    try:
        config.read(CONFIG_FILE, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError) as exc:
        print(f"[OVPN] Skipped: malformed gdrive_config.ini: {exc}")
        return

    folder_id = config.get("gdrive", "ovpn_folder_id", fallback="").strip()
    if not folder_id:
        print("[OVPN] Skipped: ovpn_folder_id not set in gdrive_config.ini.")
        return

    # ── Build .ovpn content ───────────────────────────────────────────────────
    ovpn_content = _build_ovpn(ip)
    if ovpn_content is None:
        return

    # ── Find enrolled users ───────────────────────────────────────────────────
    users = _list_enrolled_users()
    if not users:
        print("[OVPN] No enrolled users found.")
        return

    # ── Connect to Drive ──────────────────────────────────────────────────────
    try:
        from google.oauth2 import service_account  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
        from googleapiclient.http import MediaInMemoryUpload  # type: ignore
    except ImportError:
        print("[OVPN] Skipped: google-api-python-client not installed.")
        return

    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=["https://www.googleapis.com/auth/drive.file"],
        )
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as exc:
        print(
            f"[OVPN] ERROR building Drive service: {type(exc).__name__}: {str(exc)[:200]}",
            file=sys.stderr,
        )
        return

    # ── Upload per-user configs ───────────────────────────────────────────────
    file_ids = _read_ovpn_file_ids()
    updated_ids = dict(file_ids)

    for username in users:
        try:
            body_bytes = ovpn_content.encode()
            media = MediaInMemoryUpload(
                body_bytes,
                mimetype="application/x-openvpn-profile",
                resumable=False,
            )
            existing_fid = file_ids.get(username, "").strip()
            if existing_fid:
                service.files().update(
                    fileId=existing_fid,
                    media_body=media,
                ).execute()
                print(f"[OVPN] Updated {username}.ovpn (Drive id: {existing_fid})")
            else:
                result = service.files().create(
                    body={"name": f"{username}.ovpn", "parents": [folder_id]},
                    media_body=media,
                    fields="id",
                ).execute()
                new_fid = result.get("id", "")
                updated_ids[username] = new_fid
                print(f"[OVPN] Created {username}.ovpn (Drive id: {new_fid})")
        except Exception as exc:
            print(
                f"[OVPN] ERROR uploading {username}.ovpn: "
                f"{type(exc).__name__}: {str(exc)[:200]}",
                file=sys.stderr,
            )

    _write_ovpn_file_ids(updated_ids)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    ip = fetch_public_ip()
    if ip is None:
        print("ERROR: All IP sources failed.", file=sys.stderr)
        sys.exit(1)

    old_ip = read_local_ip()
    if ip == old_ip:
        print(f"[LOCAL] IP unchanged: {ip}")
        return  # Nothing to do — skip Drive update too

    if old_ip:
        print(f"[LOCAL] IP changed: {old_ip} -> {ip}")
    write_local_ip(ip)
    drive_update(ip)
    ovpn_update(ip)


if __name__ == "__main__":  # pragma: no cover
    main()
