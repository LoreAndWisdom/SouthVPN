"""
Unit tests for the .ovpn auto-update feature in scripts/ip_updater.py.

Covers:
- _list_enrolled_users(): user discovery
- _build_ovpn(): template rendering
- _read_ovpn_file_ids() / _write_ovpn_file_ids(): persistence round-trip
- ovpn_update(): all skip paths, success (create + update), per-user errors
- main(): ovpn_update called on IP change, not called when IP unchanged

Run with:  pytest tests/unit/test_ip_updater_ovpn.py -v
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts"))
import ip_updater  # noqa: E402


VALID_SA = {"type": "service_account", "client_email": "sa@project.iam.gserviceaccount.com"}


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def auth_dir(tmp_path):
    """Auth directory with two enrolled users plus noise that must be ignored."""
    d = tmp_path / "auth"
    d.mkdir()
    (d / "alice").mkdir()
    (d / "bob").mkdir()
    (d / "NOT_VALID").mkdir()           # uppercase — ignored
    (d / "not-a-dir.txt").write_text("x")  # file, not directory — ignored
    return d


@pytest.fixture()
def template_files(tmp_path):
    """Minimal client template, CA cert, and TA key."""
    t = tmp_path / "client.conf.template"
    t.write_text(
        "remote __SERVER_IP__ 1194\n"
        "<ca>\n__CA_CERT__\n</ca>\n"
        "<tls-auth>\n__TA_KEY__\n</tls-auth>\n"
    )
    ca = tmp_path / "ca.crt"
    ca.write_text("-----BEGIN CERTIFICATE-----\nMIIDFAKE\n-----END CERTIFICATE-----")
    ta = tmp_path / "ta.key"
    ta.write_text("-----BEGIN OpenVPN Static key V1-----\nFAKEKEY\n-----END OpenVPN Static key V1-----")
    return {"template": str(t), "ca": str(ca), "ta": str(ta)}


@pytest.fixture()
def configured_env(tmp_path, template_files):
    """Full valid environment: SA, config with ovpn_folder_id, template files."""
    sa = tmp_path / "service_account.json"
    sa.write_text(json.dumps(VALID_SA))
    cfg = tmp_path / "gdrive_config.ini"
    cfg.write_text("[gdrive]\nfile_id = IPFILEID\novpn_folder_id = FOLDERID\n")
    return {
        "sa": str(sa),
        "cfg": str(cfg),
        "template": template_files["template"],
        "ca": template_files["ca"],
        "ta": template_files["ta"],
    }


def _fake_google_modules(create_return_id="NEWFILEID"):
    """Build fake google.* / googleapiclient.* modules for sys.modules patching."""
    files_resource = MagicMock(name="files_resource")
    drive_service = MagicMock(name="drive_service")
    drive_service.files.return_value = files_resource
    files_resource.create.return_value.execute.return_value = {"id": create_return_id}
    files_resource.update.return_value.execute.return_value = {}

    creds = MagicMock(name="credentials")
    service_account_mod = MagicMock(name="google.oauth2.service_account")
    service_account_mod.Credentials.from_service_account_file.return_value = creds

    oauth2_mod = MagicMock(name="google.oauth2")
    oauth2_mod.service_account = service_account_mod

    discovery_mod = MagicMock(name="googleapiclient.discovery")
    discovery_mod.build.return_value = drive_service

    http_mod = MagicMock(name="googleapiclient.http")
    media_upload_cls = MagicMock(name="MediaInMemoryUpload")
    http_mod.MediaInMemoryUpload = media_upload_cls

    googleapiclient_mod = MagicMock(name="googleapiclient")
    google_mod = MagicMock(name="google")
    google_mod.oauth2 = oauth2_mod
    googleapiclient_mod.discovery = discovery_mod
    googleapiclient_mod.http = http_mod

    modules = {
        "google": google_mod,
        "google.oauth2": oauth2_mod,
        "google.oauth2.service_account": service_account_mod,
        "googleapiclient": googleapiclient_mod,
        "googleapiclient.discovery": discovery_mod,
        "googleapiclient.http": http_mod,
    }
    mocks = {
        "files": files_resource,
        "from_sa_file": service_account_mod.Credentials.from_service_account_file,
        "build": discovery_mod.build,
        "media_upload_cls": media_upload_cls,
        "service": drive_service,
    }
    return modules, mocks


def _patch_env(configured_env, auth_dir, ids_file, extra_patches=()):
    """Convenience: return a list of patch context managers for ovpn_update tests."""
    return [
        patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", configured_env["sa"]),
        patch.object(ip_updater, "CONFIG_FILE", configured_env["cfg"]),
        patch.object(ip_updater, "AUTH_DIR", str(auth_dir)),
        patch.object(ip_updater, "CLIENT_TEMPLATE_FILE", configured_env["template"]),
        patch.object(ip_updater, "CA_CERT_FILE", configured_env["ca"]),
        patch.object(ip_updater, "TA_KEY_FILE", configured_env["ta"]),
        patch.object(ip_updater, "OVPN_FILE_IDS_FILE", str(ids_file)),
        *extra_patches,
    ]


# ── _list_enrolled_users ───────────────────────────────────────────────────────

class TestListEnrolledUsers:
    def test_returns_sorted_valid_usernames(self, auth_dir):
        with patch.object(ip_updater, "AUTH_DIR", str(auth_dir)):
            users = ip_updater._list_enrolled_users()
        assert users == ["alice", "bob"]

    def test_ignores_files_and_invalid_names(self, auth_dir):
        with patch.object(ip_updater, "AUTH_DIR", str(auth_dir)):
            users = ip_updater._list_enrolled_users()
        assert "not-a-dir.txt" not in users
        assert "NOT_VALID" not in users

    def test_returns_empty_when_auth_dir_missing(self, tmp_path):
        with patch.object(ip_updater, "AUTH_DIR", str(tmp_path / "nonexistent")):
            assert ip_updater._list_enrolled_users() == []

    def test_returns_empty_for_empty_dir(self, tmp_path):
        d = tmp_path / "empty_auth"
        d.mkdir()
        with patch.object(ip_updater, "AUTH_DIR", str(d)):
            assert ip_updater._list_enrolled_users() == []


# ── _build_ovpn ───────────────────────────────────────────────────────────────

class TestBuildOvpn:
    def test_replaces_all_placeholders(self, template_files):
        with patch.object(ip_updater, "CLIENT_TEMPLATE_FILE", template_files["template"]), \
             patch.object(ip_updater, "CA_CERT_FILE", template_files["ca"]), \
             patch.object(ip_updater, "TA_KEY_FILE", template_files["ta"]):
            result = ip_updater._build_ovpn("203.0.113.42")

        assert result is not None
        assert "203.0.113.42" in result
        assert "MIID" in result      # from CA cert
        assert "FAKEKEY" in result   # from TA key
        assert "__SERVER_IP__" not in result
        assert "__CA_CERT__" not in result
        assert "__TA_KEY__" not in result

    def test_returns_none_when_template_missing(self, tmp_path, capsys):
        with patch.object(ip_updater, "CLIENT_TEMPLATE_FILE", str(tmp_path / "missing")), \
             patch.object(ip_updater, "CA_CERT_FILE", str(tmp_path / "ca.crt")), \
             patch.object(ip_updater, "TA_KEY_FILE", str(tmp_path / "ta.key")):
            assert ip_updater._build_ovpn("1.2.3.4") is None
        assert "Cannot read config files" in capsys.readouterr().err

    def test_returns_none_when_ca_missing(self, template_files, tmp_path, capsys):
        with patch.object(ip_updater, "CLIENT_TEMPLATE_FILE", template_files["template"]), \
             patch.object(ip_updater, "CA_CERT_FILE", str(tmp_path / "missing_ca.crt")), \
             patch.object(ip_updater, "TA_KEY_FILE", template_files["ta"]):
            assert ip_updater._build_ovpn("1.2.3.4") is None


# ── _read_ovpn_file_ids / _write_ovpn_file_ids ────────────────────────────────

class TestOvpnFileIds:
    def test_roundtrip(self, tmp_path):
        ids_file = str(tmp_path / "ovpn_file_ids.ini")
        with patch.object(ip_updater, "OVPN_FILE_IDS_FILE", ids_file):
            ip_updater._write_ovpn_file_ids({"alice": "AAA111", "bob": "BBB222"})
            result = ip_updater._read_ovpn_file_ids()
        assert result == {"alice": "AAA111", "bob": "BBB222"}

    def test_read_returns_empty_when_file_missing(self, tmp_path):
        with patch.object(ip_updater, "OVPN_FILE_IDS_FILE", str(tmp_path / "no_file.ini")):
            assert ip_updater._read_ovpn_file_ids() == {}

    def test_write_is_atomic_no_tmp_left_behind(self, tmp_path):
        ids_file = str(tmp_path / "ovpn_file_ids.ini")
        with patch.object(ip_updater, "OVPN_FILE_IDS_FILE", ids_file):
            ip_updater._write_ovpn_file_ids({"alice": "ID1"})
        assert not os.path.exists(ids_file + ".tmp")
        assert os.path.exists(ids_file)


# ── ovpn_update: skip paths ────────────────────────────────────────────────────

class TestOvpnUpdateSkipPaths:
    def test_skips_when_sa_missing(self, tmp_path, capsys):
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", str(tmp_path / "missing.json")):
            ip_updater.ovpn_update("1.2.3.4")
        assert "Skipped" in capsys.readouterr().out

    def test_skips_when_sa_is_placeholder(self, tmp_path, capsys):
        sa = tmp_path / "sa.json"
        sa.write_text(json.dumps({"type": "oauth_client"}))
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", str(sa)):
            ip_updater.ovpn_update("1.2.3.4")
        assert "Skipped" in capsys.readouterr().out

    def test_skips_when_sa_is_invalid_json(self, tmp_path, capsys):
        sa = tmp_path / "sa.json"
        sa.write_text("{ not json")
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", str(sa)):
            ip_updater.ovpn_update("1.2.3.4")
        assert "Skipped" in capsys.readouterr().out

    def test_skips_when_config_missing(self, tmp_path, capsys):
        sa = tmp_path / "sa.json"
        sa.write_text(json.dumps(VALID_SA))
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", str(sa)), \
             patch.object(ip_updater, "CONFIG_FILE", str(tmp_path / "missing.ini")):
            ip_updater.ovpn_update("1.2.3.4")
        assert "Skipped" in capsys.readouterr().out

    def test_skips_when_folder_id_not_set(self, tmp_path, capsys):
        sa = tmp_path / "sa.json"
        sa.write_text(json.dumps(VALID_SA))
        cfg = tmp_path / "gdrive_config.ini"
        cfg.write_text("[gdrive]\nfile_id = XYZ\novpn_folder_id =\n")
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", str(sa)), \
             patch.object(ip_updater, "CONFIG_FILE", str(cfg)):
            ip_updater.ovpn_update("1.2.3.4")
        assert "Skipped" in capsys.readouterr().out

    def test_skips_when_no_enrolled_users(self, configured_env, tmp_path, capsys):
        empty_auth = tmp_path / "empty_auth"
        empty_auth.mkdir()
        ids_file = tmp_path / "ids.ini"
        modules, _ = _fake_google_modules()
        patches = _patch_env(configured_env, empty_auth, ids_file, [patch.dict(sys.modules, modules)])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            ip_updater.ovpn_update("1.2.3.4")
        assert "No enrolled users" in capsys.readouterr().out

    def test_skips_when_google_api_not_installed(self, configured_env, auth_dir, tmp_path, capsys):
        ids_file = tmp_path / "ids.ini"
        null_modules = {
            "google": None, "google.oauth2": None,
            "google.oauth2.service_account": None,
            "googleapiclient": None,
            "googleapiclient.discovery": None,
            "googleapiclient.http": None,
        }
        patches = _patch_env(configured_env, auth_dir, ids_file, [patch.dict(sys.modules, null_modules)])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            ip_updater.ovpn_update("1.2.3.4")
        assert "Skipped" in capsys.readouterr().out

    def test_skips_on_service_build_error(self, configured_env, auth_dir, tmp_path, capsys):
        modules, mocks = _fake_google_modules()
        mocks["from_sa_file"].side_effect = ValueError("bad key")
        ids_file = tmp_path / "ids.ini"
        patches = _patch_env(configured_env, auth_dir, ids_file, [patch.dict(sys.modules, modules)])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            ip_updater.ovpn_update("1.2.3.4")
        assert "ERROR" in capsys.readouterr().err


# ── ovpn_update: success paths ────────────────────────────────────────────────

class TestOvpnUpdateSuccess:
    def test_creates_files_for_all_users_when_no_ids_stored(
        self, configured_env, auth_dir, tmp_path, capsys
    ):
        modules, mocks = _fake_google_modules(create_return_id="NEWID")
        ids_file = tmp_path / "ids.ini"
        patches = _patch_env(configured_env, auth_dir, ids_file, [patch.dict(sys.modules, modules)])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            ip_updater.ovpn_update("203.0.113.42")

        out = capsys.readouterr().out
        assert "Created alice.ovpn" in out
        assert "Created bob.ovpn" in out
        assert mocks["files"].create.call_count == 2
        assert mocks["files"].update.call_count == 0

    def test_create_uses_correct_folder_id(self, configured_env, auth_dir, tmp_path):
        modules, mocks = _fake_google_modules()
        ids_file = tmp_path / "ids.ini"
        patches = _patch_env(configured_env, auth_dir, ids_file, [patch.dict(sys.modules, modules)])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            ip_updater.ovpn_update("203.0.113.42")

        for c in mocks["files"].create.call_args_list:
            assert "FOLDERID" in c[1]["body"]["parents"]

    def test_updates_existing_files_when_ids_stored(
        self, configured_env, auth_dir, tmp_path, capsys
    ):
        modules, mocks = _fake_google_modules()
        ids_file = tmp_path / "ids.ini"
        with patch.object(ip_updater, "OVPN_FILE_IDS_FILE", str(ids_file)):
            ip_updater._write_ovpn_file_ids({"alice": "ALICEID", "bob": "BOBID"})

        patches = _patch_env(configured_env, auth_dir, ids_file, [patch.dict(sys.modules, modules)])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            ip_updater.ovpn_update("203.0.113.42")

        out = capsys.readouterr().out
        assert "Updated alice.ovpn" in out
        assert "Updated bob.ovpn" in out
        assert mocks["files"].update.call_count == 2
        assert mocks["files"].create.call_count == 0
        used_ids = {c[1]["fileId"] for c in mocks["files"].update.call_args_list}
        assert used_ids == {"ALICEID", "BOBID"}

    def test_ovpn_content_contains_new_ip(self, configured_env, auth_dir, tmp_path):
        modules, mocks = _fake_google_modules()
        ids_file = tmp_path / "ids.ini"
        patches = _patch_env(configured_env, auth_dir, ids_file, [patch.dict(sys.modules, modules)])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            ip_updater.ovpn_update("203.0.113.42")

        for c in mocks["media_upload_cls"].call_args_list:
            body_bytes = c[0][0]
            assert b"203.0.113.42" in body_bytes

    def test_new_file_ids_are_persisted(self, configured_env, auth_dir, tmp_path):
        modules, _ = _fake_google_modules(create_return_id="PERSISTEDID")
        ids_file = tmp_path / "ids.ini"
        patches = _patch_env(configured_env, auth_dir, ids_file, [patch.dict(sys.modules, modules)])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            ip_updater.ovpn_update("1.2.3.4")

        with patch.object(ip_updater, "OVPN_FILE_IDS_FILE", str(ids_file)):
            saved = ip_updater._read_ovpn_file_ids()

        assert saved.get("alice") == "PERSISTEDID"
        assert saved.get("bob") == "PERSISTEDID"

    def test_per_user_error_does_not_abort_remaining_users(
        self, configured_env, auth_dir, tmp_path, capsys
    ):
        modules, mocks = _fake_google_modules()
        # First execute() call (alice) raises; second (bob) succeeds
        create_result = MagicMock()
        create_result.execute.side_effect = [RuntimeError("quota exceeded"), {"id": "BOBID"}]
        mocks["files"].create.return_value = create_result

        ids_file = tmp_path / "ids.ini"
        patches = _patch_env(configured_env, auth_dir, ids_file, [patch.dict(sys.modules, modules)])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            ip_updater.ovpn_update("1.2.3.4")  # must not raise

        assert "ERROR" in capsys.readouterr().err
        # Both users were attempted
        assert mocks["files"].create.call_count == 2


# ── main() integration ────────────────────────────────────────────────────────

class TestMainCallsOvpnUpdate:
    def _mock_urlopen(self, body: bytes):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cm)
        cm.__exit__ = MagicMock(return_value=False)
        cm.read = MagicMock(return_value=body)
        return cm

    def test_ovpn_update_called_on_ip_change(self, tmp_path):
        ip_file = tmp_path / "current_ip.txt"
        ip_file.write_text("IP: 198.51.100.1\nLast updated: 2026-01-01T00:00:00Z\n")
        with patch.object(ip_updater, "LOCAL_IP_FILE", str(ip_file)), \
             patch.object(ip_updater, "drive_update"), \
             patch.object(ip_updater, "ovpn_update") as mock_ovpn, \
             patch("urllib.request.urlopen", return_value=self._mock_urlopen(b"203.0.113.9")):
            ip_updater.main()

        mock_ovpn.assert_called_once_with("203.0.113.9")

    def test_ovpn_update_not_called_when_ip_unchanged(self, tmp_path):
        ip_file = tmp_path / "current_ip.txt"
        ip_file.write_text("IP: 203.0.113.9\nLast updated: 2026-01-01T00:00:00Z\n")
        with patch.object(ip_updater, "LOCAL_IP_FILE", str(ip_file)), \
             patch.object(ip_updater, "drive_update"), \
             patch.object(ip_updater, "ovpn_update") as mock_ovpn, \
             patch("urllib.request.urlopen", return_value=self._mock_urlopen(b"203.0.113.9")):
            ip_updater.main()

        mock_ovpn.assert_not_called()
