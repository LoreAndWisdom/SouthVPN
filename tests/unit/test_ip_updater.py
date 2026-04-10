"""
Unit tests for scripts/ip_updater.py

Run with:  pytest tests/unit/test_ip_updater.py -v
No network, no root, no systemd required.
"""

import json
import os
import stat
import sys
import time
from unittest.mock import MagicMock, call, patch

import pytest

# Make the scripts directory importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts"))
import ip_updater  # noqa: E402


# ── parse_ip_response ──────────────────────────────────────────────────────────

class TestParseIpResponse:
    def test_valid_ipv4(self):
        assert ip_updater.parse_ip_response(b"1.2.3.4") == "1.2.3.4"

    def test_valid_ipv4_with_trailing_newline(self):
        assert ip_updater.parse_ip_response(b"93.184.216.34\n") == "93.184.216.34"

    def test_valid_ipv4_with_surrounding_whitespace(self):
        assert ip_updater.parse_ip_response(b"  10.20.30.40  ") == "10.20.30.40"

    def test_html_response_returns_none(self):
        assert ip_updater.parse_ip_response(b"<html><body>...</body></html>") is None

    def test_json_response_returns_none(self):
        assert ip_updater.parse_ip_response(b'{"ip": "1.2.3.4"}') is None

    def test_empty_bytes_returns_none(self):
        assert ip_updater.parse_ip_response(b"") is None

    def test_binary_garbage_returns_none(self):
        assert ip_updater.parse_ip_response(b"\xff\xfe\x00\x01") is None

    def test_too_long_input_returns_none(self):
        # Anything beyond 64 bytes is truncated; a long non-IP string → None
        assert ip_updater.parse_ip_response(b"1.2.3.4" + b"x" * 100) is None

    def test_leading_zero_octet_returns_none(self):
        # 01.2.3.4 is not a valid IP (leading zero)
        assert ip_updater.parse_ip_response(b"01.2.3.4") is None

    def test_octet_out_of_range_returns_none(self):
        assert ip_updater.parse_ip_response(b"256.1.1.1") is None

    def test_never_raises_on_arbitrary_bytes(self):
        # Basic robustness check for completely arbitrary inputs
        for payload in [b"\x00", b"\xff" * 64, b"not an ip\n", b"::1"]:
            result = ip_updater.parse_ip_response(payload)
            assert result is None or ip_updater.IPV4_RE.match(result)


# ── fetch_public_ip ────────────────────────────────────────────────────────────

class TestFetchPublicIp:
    """All tests mock urllib.request.urlopen — no real network calls."""

    def _mock_urlopen(self, body: bytes):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cm)
        cm.__exit__ = MagicMock(return_value=False)
        cm.read = MagicMock(return_value=body)
        return cm

    def test_primary_source_success(self):
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(b"1.2.3.4")):
            assert ip_updater.fetch_public_ip() == "1.2.3.4"

    def test_fallback_to_second_source_on_network_error(self):
        responses = [OSError("timeout"), self._mock_urlopen(b"5.6.7.8")]
        with patch("urllib.request.urlopen", side_effect=responses):
            assert ip_updater.fetch_public_ip() == "5.6.7.8"

    def test_fallback_to_third_source(self):
        responses = [
            OSError("timeout"),
            OSError("connection refused"),
            self._mock_urlopen(b"9.9.9.9"),
        ]
        with patch("urllib.request.urlopen", side_effect=responses):
            assert ip_updater.fetch_public_ip() == "9.9.9.9"

    def test_all_sources_fail_returns_none(self):
        with patch("urllib.request.urlopen", side_effect=OSError("all down")):
            assert ip_updater.fetch_public_ip() is None

    def test_malformed_response_triggers_fallback(self):
        responses = [
            self._mock_urlopen(b"<html>not an ip</html>"),
            self._mock_urlopen(b"203.0.113.10"),
        ]
        with patch("urllib.request.urlopen", side_effect=responses):
            assert ip_updater.fetch_public_ip() == "203.0.113.10"

    def test_exactly_three_sources_tried_when_all_fail(self):
        with patch("urllib.request.urlopen", side_effect=OSError("x")) as mock_open:
            ip_updater.fetch_public_ip()
            assert mock_open.call_count == len(ip_updater.IP_SOURCES)


# ── read_local_ip / write_local_ip ─────────────────────────────────────────────

class TestLocalIpFile:
    def test_write_then_read_roundtrip(self, tmp_path):
        ip_file = str(tmp_path / "current_ip.txt")
        with patch.object(ip_updater, "LOCAL_IP_FILE", ip_file):
            ip_updater.write_local_ip("10.20.30.40")
            assert ip_updater.read_local_ip() == "10.20.30.40"

    def test_write_produces_correct_format(self, tmp_path):
        ip_file = str(tmp_path / "current_ip.txt")
        with patch.object(ip_updater, "LOCAL_IP_FILE", ip_file):
            ip_updater.write_local_ip("1.2.3.4")
        content = open(ip_file).read()
        assert content.startswith("IP: 1.2.3.4\n")
        assert "Last updated:" in content

    def test_file_permissions_are_644(self, tmp_path):
        ip_file = str(tmp_path / "current_ip.txt")
        with patch.object(ip_updater, "LOCAL_IP_FILE", ip_file):
            ip_updater.write_local_ip("1.2.3.4")
        mode = stat.S_IMODE(os.stat(ip_file).st_mode)
        assert mode == 0o644

    def test_write_is_atomic_via_tmp_file(self, tmp_path):
        """write_local_ip uses os.replace, so a crash mid-write leaves no partial file."""
        ip_file = str(tmp_path / "current_ip.txt")
        tmp_file = ip_file + ".tmp"
        with patch.object(ip_updater, "LOCAL_IP_FILE", ip_file):
            ip_updater.write_local_ip("5.5.5.5")
        # After successful write, the .tmp file must be gone
        assert not os.path.exists(tmp_file)

    def test_read_returns_none_when_file_missing(self, tmp_path):
        ip_file = str(tmp_path / "nonexistent.txt")
        with patch.object(ip_updater, "LOCAL_IP_FILE", ip_file):
            assert ip_updater.read_local_ip() is None

    def test_read_returns_none_on_corrupt_file(self, tmp_path):
        ip_file = str(tmp_path / "current_ip.txt")
        ip_file_obj = tmp_path / "current_ip.txt"
        ip_file_obj.write_text("GARBAGE CONTENT\n")
        with patch.object(ip_updater, "LOCAL_IP_FILE", ip_file):
            assert ip_updater.read_local_ip() is None


# ── drive_update ──────────────────────────────────────────────────────────────

class TestDriveUpdate:
    def test_skipped_when_service_account_missing(self, tmp_path, capsys):
        missing = str(tmp_path / "service_account.json")
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", missing):
            ip_updater.drive_update("1.2.3.4")
        assert "Skipped" in capsys.readouterr().out

    def test_skipped_with_placeholder_json(self, tmp_path, capsys):
        sa_file = tmp_path / "service_account.json"
        sa_file.write_text("{}")
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", str(sa_file)):
            ip_updater.drive_update("1.2.3.4")
        assert "Skipped" in capsys.readouterr().out

    def test_skipped_with_non_service_account_type(self, tmp_path, capsys):
        sa_file = tmp_path / "service_account.json"
        sa_file.write_text(json.dumps({"type": "authorized_user"}))
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", str(sa_file)):
            ip_updater.drive_update("1.2.3.4")
        assert "Skipped" in capsys.readouterr().out

    def test_skipped_when_config_missing(self, tmp_path, capsys):
        sa_file = tmp_path / "service_account.json"
        sa_file.write_text(json.dumps({"type": "service_account"}))
        missing_cfg = str(tmp_path / "gdrive_config.ini")
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", str(sa_file)), \
             patch.object(ip_updater, "CONFIG_FILE", missing_cfg):
            ip_updater.drive_update("1.2.3.4")
        assert "Skipped" in capsys.readouterr().out

    def test_skipped_when_file_id_empty(self, tmp_path, capsys):
        sa_file = tmp_path / "service_account.json"
        sa_file.write_text(json.dumps({"type": "service_account"}))
        cfg_file = tmp_path / "gdrive_config.ini"
        cfg_file.write_text("[gdrive]\nfile_id =\n")
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", str(sa_file)), \
             patch.object(ip_updater, "CONFIG_FILE", str(cfg_file)):
            ip_updater.drive_update("1.2.3.4")
        assert "Skipped" in capsys.readouterr().out


# ── main() — integration of the two-level flow ────────────────────────────────

class TestMain:
    def test_no_write_when_ip_unchanged(self, tmp_path):
        """main() must not call write_local_ip when the IP hasn't changed."""
        ip_file = str(tmp_path / "current_ip.txt")
        with patch.object(ip_updater, "LOCAL_IP_FILE", ip_file), \
             patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", str(tmp_path / "sa.json")), \
             patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read = MagicMock(return_value=b"1.2.3.4")
            mock_open.return_value = mock_resp

            # First call: write the IP
            ip_updater.main()
            mtime1 = os.stat(ip_file).st_mtime
            time.sleep(0.05)

            # Second call: IP unchanged, file must NOT be rewritten
            ip_updater.main()
            mtime2 = os.stat(ip_file).st_mtime

        assert mtime1 == mtime2, "File was rewritten despite IP being unchanged"

    def test_exits_1_when_all_ip_sources_fail(self, tmp_path):
        with patch("urllib.request.urlopen", side_effect=OSError("all down")), \
             pytest.raises(SystemExit) as exc_info:
            ip_updater.main()
        assert exc_info.value.code == 1
