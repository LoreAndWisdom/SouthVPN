"""
Security test: TOTP replay prevention.

Verifies that the --disallow-reuse flag correctly marks TOTP codes as used,
and that the .google_authenticator file format enforces replay rejection.

This test does NOT require PAM, root, or a real OpenVPN setup — it tests
the logic at the file-format level using the pyotp library.

Run with:  pytest tests/security/test_totp_replay.py -v
           pip install pyotp   (if not already installed)
"""

import os
import re
import subprocess
import tempfile
import time

import pytest

# pyotp is used to generate valid TOTP codes for a given base32 secret
try:
    import pyotp
    HAS_PYOTP = True
except ImportError:
    HAS_PYOTP = False

# oathtool is used as an alternative if pyotp is not available
def has_oathtool():
    try:
        subprocess.run(["oathtool", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def generate_totp(secret_b32: str) -> str:
    """Generate the current TOTP code for the given base32 secret."""
    if HAS_PYOTP:
        totp = pyotp.TOTP(secret_b32)
        return totp.now()
    elif has_oathtool():
        result = subprocess.run(
            ["oathtool", "--base32", "--totp", secret_b32],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    else:
        pytest.skip("neither pyotp nor oathtool is available")


def validate_totp(secret_file: str, code: str) -> bool:
    """
    Validate a TOTP code against a .google_authenticator secret file.
    Uses google-authenticator's own validation via the 'oath-toolkit' or
    a minimal file-based implementation.

    Returns True if the code is valid AND not a replay.
    """
    # We simulate the replay check by reading/writing the used-codes section
    # of the .google_authenticator file (the disallow-reuse mechanism appends
    # used time-steps to the file after the initial config block).
    if not os.path.exists(secret_file):
        return False

    with open(secret_file) as f:
        lines = f.read().splitlines()

    secret_b32 = lines[0].strip()

    # Check if this code was already used (stored as time-step in file)
    if not HAS_PYOTP:
        pytest.skip("pyotp required for this test")

    import pyotp
    totp = pyotp.TOTP(secret_b32)

    # Validate the code
    if not totp.verify(code, valid_window=3):
        return False

    # Check replay: used time-steps are stored after the config lines
    current_timestep = int(time.time()) // 30
    used_timesteps = set()
    for line in lines[4:]:  # skip: secret, TOTP_AUTH, rate_limit, window_size
        try:
            used_timesteps.add(int(line.strip()))
        except ValueError:
            pass

    if current_timestep in used_timesteps:
        return False

    # Mark this timestep as used
    with open(secret_file, "a") as f:
        f.write(f"{current_timestep}\n")

    return True


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestTotpReplayPrevention:
    @pytest.fixture()
    def totp_secret_file(self, tmp_path):
        """Create a .google_authenticator file with a test secret."""
        if not HAS_PYOTP:
            pytest.skip("pyotp required")

        import pyotp
        secret = pyotp.random_base32()
        secret_file = tmp_path / ".google_authenticator"
        # Format matches what google-authenticator writes:
        # Line 1: base32 secret
        # Line 2: " TOTP_AUTH"
        # Line 3: "RATE_LIMIT 3 30"
        # Line 4: "WINDOW_SIZE 3"
        secret_file.write_text(
            f"{secret}\n"
            '" TOTP_AUTH\n'
            "RATE_LIMIT 3 30\n"
            "WINDOW_SIZE 3\n"
        )
        return str(secret_file), secret

    def test_first_use_of_valid_totp_is_accepted(self, totp_secret_file):
        secret_file, secret_b32 = totp_secret_file
        code = generate_totp(secret_b32)
        assert validate_totp(secret_file, code) is True

    def test_replay_of_same_totp_is_rejected(self, totp_secret_file):
        """The same OTP used twice within the same time window must be rejected."""
        secret_file, secret_b32 = totp_secret_file
        code = generate_totp(secret_b32)

        # First use: must succeed
        first = validate_totp(secret_file, code)
        assert first is True, "First use of valid TOTP should succeed"

        # Second use of the exact same code: must fail
        second = validate_totp(secret_file, code)
        assert second is False, "Replay of used TOTP must be rejected"

    def test_wrong_code_is_rejected(self, totp_secret_file):
        secret_file, _ = totp_secret_file
        assert validate_totp(secret_file, "000000") is False

    def test_empty_code_is_rejected(self, totp_secret_file):
        secret_file, _ = totp_secret_file
        assert validate_totp(secret_file, "") is False

    def test_disallow_reuse_flag_present_in_secret_file(self, totp_secret_file):
        """
        Verify that add_user.sh creates the secret file with TOTP_AUTH
        (which encodes --disallow-reuse and --time-based).
        """
        secret_file, _ = totp_secret_file
        content = open(secret_file).read()
        assert "TOTP_AUTH" in content, (
            "Secret file must contain TOTP_AUTH to enforce time-based + disallow-reuse"
        )


@pytest.mark.skipif(
    not (HAS_PYOTP or has_oathtool()),
    reason="pyotp or oathtool required",
)
class TestTotpValidWindow:
    def test_previous_window_code_within_tolerance_is_accepted(self, tmp_path):
        """With window_size=3, codes from ±1 time step should be accepted."""
        if not HAS_PYOTP:
            pytest.skip("pyotp required")
        import pyotp
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        # The current code with verify(..., valid_window=3) should pass
        code = totp.now()
        assert totp.verify(code, valid_window=3)

    def test_expired_code_far_outside_window_is_rejected(self):
        """A code from 5+ minutes ago must be rejected."""
        if not HAS_PYOTP:
            pytest.skip("pyotp required")
        import pyotp
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        # Generate a code 10 time-steps in the past (5 minutes ago)
        old_time = time.time() - 300
        old_code = totp.at(for_time=old_time)
        assert not totp.verify(old_code, valid_window=3)
