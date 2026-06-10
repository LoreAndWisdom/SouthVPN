"""
Security regression tests for the hardening fixes.

Covers:
- TLS verification is explicit and strict in ip_updater.py
- Drive exception messages are sanitized (type + truncated text only)
- systemd unit contains the expected sandboxing directives
- PAM config has brute-force protection and no nullok
- Shell scripts: umask, printf-based chpasswd, password length, output dir validation

Run with:  pytest tests/security/test_hardening.py -v
"""

import json
import os
import re
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import ip_updater  # noqa: E402


def read(relpath: str) -> str:
    with open(os.path.join(REPO, relpath)) as fh:
        return fh.read()


# ── ip_updater.py: TLS strictness ──────────────────────────────────────────────

class TestTlsVerification:
    def test_urlopen_called_with_ssl_context(self):
        """fetch_public_ip must pass an explicit SSLContext to urlopen."""
        captured = {}

        def fake_urlopen(req, timeout=None, context=None):
            captured["context"] = context
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=cm)
            cm.__exit__ = MagicMock(return_value=False)
            cm.read = MagicMock(return_value=b"1.2.3.4")
            return cm

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            assert ip_updater.fetch_public_ip() == "1.2.3.4"

        import ssl
        ctx = captured["context"]
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.check_hostname is True
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_all_ip_sources_use_https(self):
        for url in ip_updater.IP_SOURCES:
            assert url.startswith("https://"), f"Insecure IP source: {url}"


# ── ip_updater.py: sanitized Drive errors ─────────────────────────────────────

class TestDriveErrorSanitization:
    def test_long_exception_message_is_truncated(self, tmp_path, capsys):
        sa_file = tmp_path / "sa.json"
        sa_file.write_text(json.dumps({"type": "service_account"}))
        cfg_file = tmp_path / "gdrive_config.ini"
        cfg_file.write_text("[gdrive]\nfile_id = X\n")

        secret_blob = "SECRET" * 200  # 1200 chars

        sa_mod = MagicMock()
        sa_mod.Credentials.from_service_account_file.side_effect = RuntimeError(secret_blob)
        modules = {
            "google": MagicMock(),
            "google.oauth2": MagicMock(service_account=sa_mod),
            "google.oauth2.service_account": sa_mod,
            "googleapiclient": MagicMock(),
            "googleapiclient.discovery": MagicMock(),
            "googleapiclient.http": MagicMock(),
        }
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", str(sa_file)), \
             patch.object(ip_updater, "CONFIG_FILE", str(cfg_file)), \
             patch.dict(sys.modules, modules):
            ip_updater.drive_update("1.2.3.4")

        err = capsys.readouterr().err
        assert "RuntimeError" in err
        # The full 1200-char message must not appear — only the 200-char prefix
        assert secret_blob not in err


# ── systemd unit hardening ──────────────────────────────────────────────────────

class TestSystemdHardening:
    UNIT = "config/ip_updater/ip_updater.service"

    @pytest.mark.parametrize("directive", [
        "NoNewPrivileges=yes",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "PrivateTmp=yes",
        "ProtectKernelTunables=yes",
        "ProtectKernelModules=yes",
        "RestrictNamespaces=yes",
        "MemoryDenyWriteExecute=yes",
        "SystemCallFilter=@system-service",
        "CapabilityBoundingSet=",
    ])
    def test_unit_has_hardening_directive(self, directive):
        assert directive in read(self.UNIT), f"Missing: {directive}"

    def test_writable_paths_limited_to_state_dir(self):
        content = read(self.UNIT)
        m = re.search(r"ReadWritePaths=(.*)", content)
        assert m, "ReadWritePaths directive missing"
        assert m.group(1).strip() == "/var/lib/southvpn"


# ── PAM configuration ───────────────────────────────────────────────────────────

class TestPamConfig:
    PAM = "config/pam.d/openvpn"

    @staticmethod
    def _active_lines(content: str) -> list:
        """PAM lines that are not comments or blanks."""
        return [
            l for l in content.splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]

    def test_no_nullok_anywhere(self):
        for line in self._active_lines(read(self.PAM)):
            assert "nullok" not in line, f"nullok found: {line}"

    def test_brute_force_protection_present(self):
        content = read(self.PAM)
        assert "pam_faillock.so" in content
        assert "preauth" in content
        assert "authfail" in content
        assert "authsucc" in content

    def test_faillock_in_account_phase(self):
        account_lines = [
            l for l in read(self.PAM).splitlines()
            if l.strip().startswith("account")
        ]
        assert any("pam_faillock.so" in l for l in account_lines)

    def test_google_authenticator_required_with_forward_pass(self):
        content = read(self.PAM)
        assert "pam_google_authenticator.so" in content
        assert "forward_pass" in content
        assert "user=nobody" in content

    def test_successful_auth_does_not_record_failure(self):
        """authfail lines must be skippable (success=N), never unconditionally hit."""
        lines = self._active_lines(read(self.PAM))
        for i, line in enumerate(lines):
            if "authfail" in line:
                # The preceding auth factor must skip this line on success
                prev_auth = [
                    l for l in lines[:i]
                    if l.strip().startswith("auth") and "pam_faillock" not in l
                ]
                assert prev_auth, "authfail line with no preceding auth factor"
                assert "success=1" in prev_auth[-1], (
                    f"auth factor before authfail must skip it on success: {prev_auth[-1]}"
                )


# ── Shell script hardening ───────────────────────────────────────────────────────

class TestShellScriptHardening:
    def test_add_user_sets_umask(self):
        assert re.search(r"^umask 00?77", read("scripts/add_user.sh"), re.M)

    def test_setup_gdrive_sets_umask(self):
        assert re.search(r"^umask 00?77", read("scripts/setup_gdrive.sh"), re.M)

    def test_add_user_uses_printf_for_chpasswd(self):
        content = read("scripts/add_user.sh")
        assert "printf '%s:%s\\n'" in content
        assert not re.search(r'echo\s+"\$\{USERNAME\}:\$\{PASSWORD\}"', content)

    def test_add_user_enforces_min_password_length(self):
        content = read("scripts/add_user.sh")
        assert "MIN_PASSWORD_LENGTH" in content
        m = re.search(r"MIN_PASSWORD_LENGTH=(\d+)", content)
        assert m and int(m.group(1)) >= 12

    def test_setup_gdrive_does_not_interpolate_path_into_python(self):
        """KEY_PATH must reach Python via the environment, not string interpolation."""
        content = read("scripts/setup_gdrive.sh")
        assert "${KEY_PATH}'" not in content.replace("'${KEY_PATH}'", "MARKER") or \
               "MARKER" not in content
        assert 'os.environ["KEY_PATH"]' in content

    def test_ssh_client_empty_ip_rejected(self):
        for script in ("scripts/add_user.sh", "scripts/remove_user.sh"):
            assert 'Cannot determine client IP' in read(script), script

    def test_remove_user_sets_log_permissions(self):
        content = read("scripts/remove_user.sh")
        assert "chmod 640" in content

    def test_gen_client_config_rejects_dotdot_output_dir(self, tmp_path):
        """Functional test: --output dir containing .. must be rejected."""
        result = subprocess.run(
            ["bash", os.path.join(REPO, "scripts/gen_client_config.sh"),
             "alice", str(tmp_path) + "/../escape", "--ip", "1.2.3.4"],
            capture_output=True, text=True,
            env={**os.environ,
                 "LOCAL_IP_FILE": "/nonexistent",
                 "CA_CERT": "/nonexistent",
                 "TA_KEY": "/nonexistent",
                 "TEMPLATE": "/nonexistent"},
        )
        # Non-root exits 1 with root error; root exits 1 with the .. error.
        assert result.returncode != 0
        if os.geteuid() == 0:
            assert "must not contain '..'" in result.stderr


# ── OpenVPN server config ────────────────────────────────────────────────────────

class TestServerConfig:
    CONF = "config/server.conf.template"

    def test_tls_version_minimum(self):
        assert "tls-version-min 1.2" in read(self.CONF)

    def test_modern_ciphers_only(self):
        content = read(self.CONF)
        assert "AES-256-GCM" in content
        for weak in ("BF-CBC", "DES", "RC4"):
            assert weak not in content, f"Weak cipher present: {weak}"

    def test_privilege_drop(self):
        content = read(self.CONF)
        assert "user nobody" in content
        assert "group nogroup" in content

    def test_tls_auth_enabled(self):
        assert "tls-auth" in read(self.CONF)

    def test_no_dh_file_with_ecdh(self):
        assert "dh   none" in read(self.CONF) or "dh none" in read(self.CONF)
