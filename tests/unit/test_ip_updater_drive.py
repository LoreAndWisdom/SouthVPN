"""
Additional unit tests for scripts/ip_updater.py — Drive upload paths and
error branches not covered by test_ip_updater.py.

These tests mock the google-api-python-client modules so the real Drive
upload code path (credential loading, service build, files().update())
is exercised without network access or real credentials.

Run with:  pytest tests/unit/test_ip_updater_drive.py -v
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts"))
import ip_updater  # noqa: E402


VALID_SA = {"type": "service_account", "client_email": "x@y.iam.gserviceaccount.com"}


@pytest.fixture()
def configured_env(tmp_path):
    """Valid service account + config files pointing at a fake file_id."""
    sa_file = tmp_path / "service_account.json"
    sa_file.write_text(json.dumps(VALID_SA))
    cfg_file = tmp_path / "gdrive_config.ini"
    cfg_file.write_text("[gdrive]\nfile_id = FAKEID123\nfilename = southvpn_ip.txt\n")
    return {"sa": str(sa_file), "cfg": str(cfg_file)}


def _fake_google_modules():
    """Build fake google.* / googleapiclient.* modules wired into sys.modules.

    Returns (modules_dict, mocks) where mocks exposes the key call points.
    """
    creds = MagicMock(name="credentials")
    service_account_mod = MagicMock(name="google.oauth2.service_account")
    service_account_mod.Credentials.from_service_account_file.return_value = creds

    oauth2_mod = MagicMock(name="google.oauth2")
    oauth2_mod.service_account = service_account_mod

    files_resource = MagicMock(name="files_resource")
    drive_service = MagicMock(name="drive_service")
    drive_service.files.return_value = files_resource

    discovery_mod = MagicMock(name="googleapiclient.discovery")
    discovery_mod.build.return_value = drive_service

    media_upload = MagicMock(name="MediaInMemoryUpload")
    http_mod = MagicMock(name="googleapiclient.http")
    http_mod.MediaInMemoryUpload = media_upload

    googleapiclient_mod = MagicMock(name="googleapiclient")
    googleapiclient_mod.discovery = discovery_mod
    googleapiclient_mod.http = http_mod

    google_mod = MagicMock(name="google")
    google_mod.oauth2 = oauth2_mod

    modules = {
        "google": google_mod,
        "google.oauth2": oauth2_mod,
        "google.oauth2.service_account": service_account_mod,
        "googleapiclient": googleapiclient_mod,
        "googleapiclient.discovery": discovery_mod,
        "googleapiclient.http": http_mod,
    }
    mocks = {
        "from_sa_file": service_account_mod.Credentials.from_service_account_file,
        "build": discovery_mod.build,
        "files": files_resource,
        "media_upload": media_upload,
        "creds": creds,
        "service": drive_service,
    }
    return modules, mocks


# ── Drive upload success path ──────────────────────────────────────────────────

class TestDriveUploadSuccess:
    def test_upload_calls_files_update_with_file_id(self, configured_env, capsys):
        modules, mocks = _fake_google_modules()
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", configured_env["sa"]), \
             patch.object(ip_updater, "CONFIG_FILE", configured_env["cfg"]), \
             patch.dict(sys.modules, modules):
            ip_updater.drive_update("203.0.113.42")

        mocks["files"].update.assert_called_once()
        _, kwargs = mocks["files"].update.call_args
        assert kwargs["fileId"] == "FAKEID123"
        assert "Updated file FAKEID123" in capsys.readouterr().out

    def test_upload_body_contains_ip_and_timestamp(self, configured_env):
        modules, mocks = _fake_google_modules()
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", configured_env["sa"]), \
             patch.object(ip_updater, "CONFIG_FILE", configured_env["cfg"]), \
             patch.dict(sys.modules, modules):
            ip_updater.drive_update("203.0.113.42")

        body = mocks["media_upload"].call_args[0][0]
        assert b"IP: 203.0.113.42" in body
        assert b"Last updated:" in body

    def test_credentials_use_least_privilege_scope(self, configured_env):
        modules, mocks = _fake_google_modules()
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", configured_env["sa"]), \
             patch.object(ip_updater, "CONFIG_FILE", configured_env["cfg"]), \
             patch.dict(sys.modules, modules):
            ip_updater.drive_update("1.2.3.4")

        _, kwargs = mocks["from_sa_file"].call_args
        assert kwargs["scopes"] == ["https://www.googleapis.com/auth/drive.file"]

    def test_service_built_without_discovery_cache(self, configured_env):
        modules, mocks = _fake_google_modules()
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", configured_env["sa"]), \
             patch.object(ip_updater, "CONFIG_FILE", configured_env["cfg"]), \
             patch.dict(sys.modules, modules):
            ip_updater.drive_update("1.2.3.4")

        _, kwargs = mocks["build"].call_args
        assert kwargs["cache_discovery"] is False


# ── Drive upload error path (must NOT exit non-zero) ──────────────────────────

class TestDriveUploadErrors:
    def test_api_error_does_not_exit(self, configured_env, capsys):
        """Drive errors are logged but never raise SystemExit — Drive is optional."""
        modules, mocks = _fake_google_modules()
        mocks["files"].update.side_effect = RuntimeError("HttpError 404: not found")
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", configured_env["sa"]), \
             patch.object(ip_updater, "CONFIG_FILE", configured_env["cfg"]), \
             patch.dict(sys.modules, modules):
            ip_updater.drive_update("1.2.3.4")  # must not raise

        assert "ERROR" in capsys.readouterr().err

    def test_credential_error_does_not_exit(self, configured_env, capsys):
        modules, mocks = _fake_google_modules()
        mocks["from_sa_file"].side_effect = ValueError("bad key format")
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", configured_env["sa"]), \
             patch.object(ip_updater, "CONFIG_FILE", configured_env["cfg"]), \
             patch.dict(sys.modules, modules):
            ip_updater.drive_update("1.2.3.4")  # must not raise

        assert "ERROR" in capsys.readouterr().err


# ── Remaining error branches ───────────────────────────────────────────────────

class TestErrorBranches:
    def test_invalid_json_in_service_account_is_skipped(self, tmp_path, capsys):
        sa_file = tmp_path / "service_account.json"
        sa_file.write_text("{ this is not valid json")
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", str(sa_file)):
            ip_updater.drive_update("1.2.3.4")
        assert "Skipped" in capsys.readouterr().out

    def test_malformed_ini_is_skipped(self, tmp_path, capsys):
        sa_file = tmp_path / "service_account.json"
        sa_file.write_text(json.dumps(VALID_SA))
        cfg_file = tmp_path / "gdrive_config.ini"
        cfg_file.write_text("[gdrive\nfile_id = broken section header\n")
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", str(sa_file)), \
             patch.object(ip_updater, "CONFIG_FILE", str(cfg_file)):
            ip_updater.drive_update("1.2.3.4")
        assert "Skipped" in capsys.readouterr().out

    def test_non_utf8_ini_is_skipped(self, tmp_path, capsys):
        sa_file = tmp_path / "service_account.json"
        sa_file.write_text(json.dumps(VALID_SA))
        cfg_file = tmp_path / "gdrive_config.ini"
        cfg_file.write_bytes(b"\x80\x81[gdrive]\nfile_id = x\n")
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", str(sa_file)), \
             patch.object(ip_updater, "CONFIG_FILE", str(cfg_file)):
            ip_updater.drive_update("1.2.3.4")
        assert "Skipped" in capsys.readouterr().out

    def test_parse_ip_response_handles_non_bytes_input(self):
        """The except branch in parse_ip_response must swallow type errors."""
        assert ip_updater.parse_ip_response(None) is None
        assert ip_updater.parse_ip_response(12345) is None


# ── main() — IP changed path with Drive sync ──────────────────────────────────

class TestMainIpChanged:
    def _mock_urlopen(self, body: bytes):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cm)
        cm.__exit__ = MagicMock(return_value=False)
        cm.read = MagicMock(return_value=body)
        return cm

    def test_ip_change_writes_file_and_calls_drive(self, tmp_path, capsys):
        ip_file = tmp_path / "current_ip.txt"
        ip_file.write_text("IP: 198.51.100.1\nLast updated: 2026-01-01T00:00:00Z\n")

        with patch.object(ip_updater, "LOCAL_IP_FILE", str(ip_file)), \
             patch.object(ip_updater, "drive_update") as mock_drive, \
             patch("urllib.request.urlopen", return_value=self._mock_urlopen(b"203.0.113.9")):
            ip_updater.main()

        assert "IP changed: 198.51.100.1 -> 203.0.113.9" in capsys.readouterr().out
        assert "IP: 203.0.113.9" in ip_file.read_text()
        mock_drive.assert_called_once_with("203.0.113.9")
