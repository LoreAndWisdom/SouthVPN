#!/usr/bin/env python3
"""
SouthVPN IP Updater
===================
Detects the current public IP address and:

  Level 1 (always): writes /var/lib/southvpn/current_ip.txt
  Level 2 (optional): syncs to Google Drive if /etc/southvpn/service_account.json
                      contains a valid service account key and gdrive_config.ini
                      has a file_id set.

The script is designed to be called by the southvpn-ip-updater.service systemd
unit.  All output is captured by journald.
"""

import configparser
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

# ── Constants ──────────────────────────────────────────────────────────────────
LOCAL_IP_FILE = "/var/lib/southvpn/current_ip.txt"
CONFIG_FILE = "/etc/southvpn/gdrive_config.ini"
SERVICE_ACCOUNT_FILE = "/etc/southvpn/service_account.json"

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
    for url in IP_SOURCES:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "SouthVPN-IPUpdater/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
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
        print(f"[Drive] ERROR: {exc}", file=sys.stderr)


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


if __name__ == "__main__":
    main()
