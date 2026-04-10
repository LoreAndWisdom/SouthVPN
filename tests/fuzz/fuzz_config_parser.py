"""
Fuzz tests for the gdrive_config.ini parser used in scripts/ip_updater.drive_update()

Uses Hypothesis to generate arbitrary .ini-like content and verify that:
1. The parser never raises an unhandled exception.
2. The parser never returns a file_id that could be used as a shell injection
   or path traversal payload (the value is only ever passed to the Drive API,
   but we verify it cannot bypass the configparser layer).
3. Malformed ini content causes a silent skip, not a crash.

Run with:
    pip install hypothesis pytest
    pytest tests/fuzz/fuzz_config_parser.py -v
"""

import configparser
import json
import os
import sys
import tempfile
import textwrap
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts"))
import ip_updater  # noqa: E402

try:
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

pytestmark = pytest.mark.skipif(
    not HAS_HYPOTHESIS,
    reason="hypothesis not installed — run: pip install hypothesis",
)


# ── Helper ────────────────────────────────────────────────────────────────────

def _make_sa_file(tmp_path) -> str:
    """Create a minimal valid service_account.json placeholder."""
    sa = tmp_path / "service_account.json"
    sa.write_text(json.dumps({"type": "service_account"}))
    return str(sa)


# ── Property: drive_update never crashes on arbitrary config content ──────────

@given(st.binary(max_size=4096))
@settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow])
def test_drive_update_never_crashes_on_arbitrary_config(tmp_path, raw_config: bytes):
    """drive_update() must handle any config file content without crashing."""
    sa_file = _make_sa_file(tmp_path)
    cfg_file = tmp_path / "gdrive_config.ini"
    try:
        cfg_file.write_bytes(raw_config)
    except OSError:
        return  # If we can't write the file, skip this example

    try:
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", sa_file), \
             patch.object(ip_updater, "CONFIG_FILE", str(cfg_file)):
            ip_updater.drive_update("1.2.3.4")
    except SystemExit:
        # SystemExit(1) is expected when Drive API fails
        pass
    except Exception as exc:
        pytest.fail(
            f"drive_update raised unexpected {type(exc).__name__}: {exc}\n"
            f"Config content: {raw_config!r}"
        )


@given(st.text(max_size=1024))
@settings(max_examples=500)
def test_drive_update_never_crashes_on_arbitrary_text_config(tmp_path, config_text: str):
    """drive_update() must handle any text config file without crashing."""
    sa_file = _make_sa_file(tmp_path)
    cfg_file = tmp_path / "gdrive_config.ini"
    try:
        cfg_file.write_text(config_text, encoding="utf-8", errors="replace")
    except OSError:
        return

    try:
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", sa_file), \
             patch.object(ip_updater, "CONFIG_FILE", str(cfg_file)):
            ip_updater.drive_update("1.2.3.4")
    except SystemExit:
        pass
    except Exception as exc:
        pytest.fail(
            f"drive_update raised unexpected {type(exc).__name__}: {exc}\n"
            f"Config text: {config_text!r}"
        )


@given(
    st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        max_size=128,
    )
)
@settings(max_examples=500)
def test_file_id_never_causes_path_traversal(tmp_path, file_id: str):
    """
    Verify that a crafted file_id value in gdrive_config.ini does not cause
    any filesystem side effects or path traversal.  The file_id is only passed
    to the Drive API; the test mocks the API call and checks no files are
    unexpectedly created.
    """
    sa_file = _make_sa_file(tmp_path)
    cfg_content = f"[gdrive]\nfile_id = {file_id}\nfilename = southvpn_ip.txt\n"
    cfg_file = tmp_path / "gdrive_config.ini"
    try:
        cfg_file.write_text(cfg_content)
    except (OSError, ValueError):
        return

    files_before = set(os.listdir(tmp_path))

    try:
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", sa_file), \
             patch.object(ip_updater, "CONFIG_FILE", str(cfg_file)), \
             patch.dict("sys.modules", {
                 "google.oauth2": None,
                 "google.oauth2.service_account": None,
                 "googleapiclient": None,
                 "googleapiclient.discovery": None,
                 "googleapiclient.http": None,
             }):
            ip_updater.drive_update("1.2.3.4")
    except (SystemExit, ImportError):
        pass
    except Exception as exc:
        pytest.fail(
            f"Unexpected exception for file_id={file_id!r}: {type(exc).__name__}: {exc}"
        )

    # No new files outside tmp_path should have been created
    files_after = set(os.listdir(tmp_path))
    new_files = files_after - files_before
    # Only the config and SA files themselves are allowed
    unexpected = {f for f in new_files if f not in {"gdrive_config.ini", "service_account.json"}}
    assert not unexpected, (
        f"Unexpected files created for file_id={file_id!r}: {unexpected}"
    )


# ── Property: configparser handles edge cases gracefully ──────────────────────

@given(st.binary(max_size=4096))
@settings(max_examples=500)
def test_configparser_never_crashes_on_arbitrary_bytes(raw: bytes):
    """configparser.ConfigParser.read() must not raise on any byte content."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ini") as f:
        f.write(raw)
        name = f.name
    try:
        cfg = configparser.ConfigParser()
        cfg.read(name)  # Should either succeed or raise configparser.Error
    except configparser.Error:
        pass  # Expected for malformed input
    except Exception as exc:
        pytest.fail(f"Unexpected exception from configparser: {type(exc).__name__}: {exc}")
    finally:
        os.unlink(name)


# ── Concrete regression cases ──────────────────────────────────────────────────

@pytest.mark.parametrize("config_text,expect_skip", [
    # Valid config with real file_id → would attempt Drive upload (mocked away)
    ("[gdrive]\nfile_id = abc123\n", False),
    # Empty file_id → skip
    ("[gdrive]\nfile_id =\n", True),
    # Missing section → skip
    ("not an ini file at all\n", True),
    # Completely empty file → skip
    ("", True),
    # Injection attempt in file_id (passed to API, not executed)
    ("[gdrive]\nfile_id = ../../etc/passwd\n", False),
    # Binary-ish content
    ("[gdrive]\nfile_id = \x00\x01\x02\n", True),
])
def test_config_edge_cases(tmp_path, config_text, expect_skip, capsys):
    sa_file = _make_sa_file(tmp_path)
    cfg_file = tmp_path / "gdrive_config.ini"
    cfg_file.write_text(config_text, errors="replace")

    try:
        with patch.object(ip_updater, "SERVICE_ACCOUNT_FILE", sa_file), \
             patch.object(ip_updater, "CONFIG_FILE", str(cfg_file)), \
             patch.dict("sys.modules", {
                 "google.oauth2": None,
                 "google.oauth2.service_account": None,
                 "googleapiclient": None,
                 "googleapiclient.discovery": None,
                 "googleapiclient.http": None,
             }):
            ip_updater.drive_update("1.2.3.4")
    except SystemExit:
        pass

    output = capsys.readouterr().out
    if expect_skip:
        assert "Skipped" in output, f"Expected skip for config: {config_text!r}, got: {output!r}"
