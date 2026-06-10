"""
Fuzz tests for scripts/ip_updater.parse_ip_response()

Uses the Hypothesis library for property-based testing.
Verifies that parse_ip_response() never raises an exception and
never returns a string that isn't a valid IPv4 address.

Run with:
    pip install hypothesis pytest
    pytest tests/fuzz/fuzz_ip_parser.py -v

For deeper fuzzing (more examples):
    pytest tests/fuzz/fuzz_ip_parser.py -v --hypothesis-seed=0 \
        -p no:randomly -x

For corpus-guided fuzzing with atheris (optional, requires clang):
    pip install atheris
    python tests/fuzz/fuzz_ip_parser.py  # runs atheris main
"""

import os
import re
import sys

import pytest

# Import the module under test
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts"))
from ip_updater import IPV4_RE, parse_ip_response  # noqa: E402

# Skip the whole file at collection time if hypothesis is missing —
# module-level @given decorators would otherwise raise NameError.
pytest.importorskip("hypothesis", reason="hypothesis not installed — run: pip install hypothesis")
from hypothesis import given, settings, HealthCheck  # noqa: E402
from hypothesis import strategies as st  # noqa: E402


# ── Property: parse_ip_response never raises ──────────────────────────────────

@given(st.binary(max_size=8192))
@settings(max_examples=2000, suppress_health_check=[HealthCheck.too_slow])
def test_parse_ip_response_never_raises(raw_bytes: bytes):
    """No input should ever cause an unhandled exception."""
    try:
        result = parse_ip_response(raw_bytes)
    except Exception as exc:
        pytest.fail(
            f"parse_ip_response raised {type(exc).__name__}: {exc}\n"
            f"Input: {raw_bytes!r}"
        )
    # If a result is returned, it must be a valid IPv4
    if result is not None:
        assert isinstance(result, str), f"Result must be str, got {type(result)}"
        assert IPV4_RE.match(result), f"Result is not a valid IPv4: {result!r}"


@given(st.text(max_size=256))
@settings(max_examples=1000)
def test_parse_ip_response_never_raises_on_text(text: str):
    """parse_ip_response should also handle encoded text without crashing."""
    try:
        result = parse_ip_response(text.encode("utf-8", errors="replace"))
    except Exception as exc:
        pytest.fail(
            f"parse_ip_response raised {type(exc).__name__}: {exc}\n"
            f"Input text: {text!r}"
        )
    if result is not None:
        assert IPV4_RE.match(result)


@given(st.binary(min_size=0, max_size=65536))
@settings(max_examples=500)
def test_parse_ip_response_rejects_large_inputs(raw_bytes: bytes):
    """Even very large inputs must not cause a crash or return garbage."""
    result = parse_ip_response(raw_bytes)
    if result is not None:
        assert len(result) <= 15, f"Returned value too long to be IPv4: {result!r}"
        assert IPV4_RE.match(result)


# ── Property: only genuine IPv4 addresses are accepted ────────────────────────

@given(st.from_regex(r"^\d{1,5}\.\d{1,5}\.\d{1,5}\.\d{1,5}$", fullmatch=True).map(str.encode))
@settings(max_examples=500)
def test_ip_like_strings_only_accepted_when_valid(ip_like: bytes):
    """Strings that look like IPs but have out-of-range octets must be rejected."""
    result = parse_ip_response(ip_like)
    if result is not None:
        # Verify each octet is 0–255
        parts = result.split(".")
        assert len(parts) == 4
        for part in parts:
            octet = int(part)
            assert 0 <= octet <= 255, f"Out-of-range octet {octet} accepted: {result!r}"


# ── Concrete regression cases ─────────────────────────────────────────────────

@pytest.mark.parametrize("payload,expected", [
    (b"1.2.3.4",                    "1.2.3.4"),
    (b"255.255.255.255",             "255.255.255.255"),
    (b"0.0.0.0",                    "0.0.0.0"),
    (b"1.2.3.4\n",                  "1.2.3.4"),
    (b"  203.0.113.42  ",           "203.0.113.42"),
    (b"256.1.1.1",                   None),
    (b"01.2.3.4",                    None),
    (b"1.2.3",                       None),
    (b"1.2.3.4.5",                   None),
    (b"",                            None),
    (b"not.an.ip.addr",              None),
    (b"<html>1.2.3.4</html>",        None),
    (b'{"ip":"1.2.3.4"}',            None),
    (b"\xff\xfe",                    None),
    (b"::1",                         None),   # IPv6 — not accepted
    (b"2001:db8::1",                 None),   # IPv6 — not accepted
])
def test_parse_ip_response_concrete_cases(payload, expected):
    assert parse_ip_response(payload) == expected


# ── Optional: atheris corpus-guided fuzzing entry point ───────────────────────

def _atheris_main():
    """Entry point for atheris fuzzing: python tests/fuzz/fuzz_ip_parser.py"""
    try:
        import atheris
    except ImportError:
        print("atheris not installed. Run: pip install atheris")
        sys.exit(1)

    @atheris.instrument_func
    def fuzz_target(data: bytes):
        result = parse_ip_response(data)
        if result is not None:
            assert IPV4_RE.match(result), f"Invalid IP returned: {result!r}"

    atheris.Setup(sys.argv, fuzz_target)
    atheris.Fuzz()


if __name__ == "__main__":
    _atheris_main()
