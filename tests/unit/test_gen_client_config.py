"""
Unit tests for scripts/gen_client_config.sh

Calls the shell script as a subprocess to verify its behaviour.
Requires root to read /etc/openvpn/server/ta.key; tests that need root
are skipped automatically when not running as root.

Run with:  pytest tests/unit/test_gen_client_config.py -v
"""

import os
import stat
import subprocess
import sys
import tempfile
import textwrap

import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "../../scripts/gen_client_config.sh")

# Fixtures that create fake PKI files so we don't need a real OpenVPN installation
CA_CERT_CONTENT = textwrap.dedent("""\
    -----BEGIN CERTIFICATE-----
    MIIFAKECA_CERT_PLACEHOLDER
    -----END CERTIFICATE-----
""")

TA_KEY_CONTENT = textwrap.dedent("""\
    #
    # 2048 bit OpenVPN static key
    #
    -----BEGIN OpenVPN Static key V1-----
    TAAUTHKEYPLACEHOLDER
    -----END OpenVPN Static key V1-----
""")


@pytest.fixture()
def fake_pki(tmp_path):
    """Create a temporary PKI directory with fake cert/key files."""
    ca = tmp_path / "ca.crt"
    ta = tmp_path / "ta.key"
    ca.write_text(CA_CERT_CONTENT)
    ta.write_text(TA_KEY_CONTENT)
    ta.chmod(0o600)
    return {"ca": str(ca), "ta": str(ta), "dir": tmp_path}


@pytest.fixture()
def fake_ip_file(tmp_path):
    ip_file = tmp_path / "current_ip.txt"
    ip_file.write_text("IP: 203.0.113.42\nLast updated: 2026-04-10T10:00:00Z\n")
    return str(ip_file)


@pytest.fixture()
def template_file():
    """Return the path to the real client.conf.template."""
    path = os.path.join(os.path.dirname(__file__), "../../client/client.conf.template")
    assert os.path.exists(path), f"Template not found: {path}"
    return path


def run_script(args, env=None):
    """Run gen_client_config.sh with given args under sudo (needed for root check bypass in tests)."""
    base_env = {**os.environ}
    if env:
        base_env.update(env)
    return subprocess.run(
        ["bash", SCRIPT, *args],
        capture_output=True,
        text=True,
        env=base_env,
    )


@pytest.mark.skipif(os.getuid() != 0, reason="requires root")
class TestGenClientConfigRoot:
    def test_generates_ovpn_file(self, fake_pki, fake_ip_file, template_file, tmp_path):
        # Patch paths via environment — the script reads LOCAL_IP_FILE, CA_CERT, TA_KEY
        result = run_script(
            ["alice", str(tmp_path), "--ip", "203.0.113.42"],
            env={
                "LOCAL_IP_FILE": fake_ip_file,
                "CA_CERT": fake_pki["ca"],
                "TA_KEY": fake_pki["ta"],
                "TEMPLATE": template_file,
            },
        )
        assert result.returncode == 0, result.stderr
        out_file = tmp_path / "alice.ovpn"
        assert out_file.exists(), "Output .ovpn file was not created"

    def test_output_file_permissions_are_600(self, fake_pki, fake_ip_file, template_file, tmp_path):
        run_script(
            ["alice", str(tmp_path), "--ip", "1.2.3.4"],
            env={
                "LOCAL_IP_FILE": fake_ip_file,
                "CA_CERT": fake_pki["ca"],
                "TA_KEY": fake_pki["ta"],
                "TEMPLATE": template_file,
            },
        )
        out_file = tmp_path / "alice.ovpn"
        mode = stat.S_IMODE(os.stat(str(out_file)).st_mode)
        assert mode == 0o600, f"Expected 0o600 but got {oct(mode)}"

    def test_server_ip_embedded(self, fake_pki, fake_ip_file, template_file, tmp_path):
        run_script(
            ["alice", str(tmp_path), "--ip", "203.0.113.99"],
            env={
                "LOCAL_IP_FILE": fake_ip_file,
                "CA_CERT": fake_pki["ca"],
                "TA_KEY": fake_pki["ta"],
                "TEMPLATE": template_file,
            },
        )
        content = (tmp_path / "alice.ovpn").read_text()
        assert "remote 203.0.113.99 1194" in content

    def test_ca_cert_embedded_inline(self, fake_pki, fake_ip_file, template_file, tmp_path):
        run_script(
            ["alice", str(tmp_path), "--ip", "1.2.3.4"],
            env={
                "LOCAL_IP_FILE": fake_ip_file,
                "CA_CERT": fake_pki["ca"],
                "TA_KEY": fake_pki["ta"],
                "TEMPLATE": template_file,
            },
        )
        content = (tmp_path / "alice.ovpn").read_text()
        assert "<ca>" in content
        assert "MIIFAKECA_CERT_PLACEHOLDER" in content
        assert "</ca>" in content

    def test_ip_read_from_local_file_when_no_override(
        self, fake_pki, fake_ip_file, template_file, tmp_path
    ):
        run_script(
            ["alice", str(tmp_path)],
            env={
                "LOCAL_IP_FILE": fake_ip_file,
                "CA_CERT": fake_pki["ca"],
                "TA_KEY": fake_pki["ta"],
                "TEMPLATE": template_file,
            },
        )
        content = (tmp_path / "alice.ovpn").read_text()
        assert "remote 203.0.113.42 1194" in content


class TestGenClientConfigNonRoot:
    def test_fails_without_root(self, tmp_path):
        if os.getuid() == 0:
            pytest.skip("already root")
        result = run_script(["alice", str(tmp_path), "--ip", "1.2.3.4"])
        assert result.returncode != 0
        assert "root" in result.stderr.lower()

    def test_invalid_username_rejected(self):
        for bad in ["../../etc/passwd", "root; id", "", "AB_UPPER", "a" * 32]:
            result = subprocess.run(
                ["bash", SCRIPT, bad, "/tmp", "--ip", "1.2.3.4"],
                capture_output=True, text=True,
            )
            assert result.returncode != 0, f"Expected failure for username: {bad!r}"

    def test_missing_ip_file_causes_failure(self, tmp_path):
        if os.getuid() != 0:
            pytest.skip("requires root to reach the IP-lookup code path")
        result = run_script(
            ["alice", str(tmp_path)],
            env={"LOCAL_IP_FILE": str(tmp_path / "nonexistent.txt")},
        )
        assert result.returncode != 0
        assert "IP" in result.stderr
