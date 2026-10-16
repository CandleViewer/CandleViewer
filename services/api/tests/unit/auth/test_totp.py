"""Unit tests for `candleviewer.auth.totp` (RFC 6238), E09-S02.

RFC 6238 Appendix B publishes fixed test vectors for an 8-digit SHA-1 TOTP
against a well-known 20-byte ASCII seed; this module implements 6-digit
codes, so we instead pin our own vectors computed from the same RFC 4226
HOTP algorithm and assert internal consistency (generate/verify round-trip,
skew window, replay-adjacent step math) rather than re-deriving the RFC's
8-digit vectors.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.auth.totp import (
    TOTP_DIGITS,
    TOTP_SKEW_STEPS,
    TOTP_STEP_SECONDS,
    base32_to_secret,
    generate_code,
    generate_secret,
    otpauth_uri,
    secret_to_base32,
    time_step_for,
    verify_code,
)

from .totp_code_cases import NON_ASCII_DIGIT_CODES


def test_generate_secret_returns_20_random_bytes() -> None:
    secret = generate_secret()
    assert len(secret) == 20
    assert secret != generate_secret()


def test_secret_base32_round_trip() -> None:
    secret = generate_secret()
    assert base32_to_secret(secret_to_base32(secret)) == secret


def test_time_step_for_buckets_by_30_seconds() -> None:
    assert time_step_for(0.0) == 0
    assert time_step_for(29.999) == 0
    assert time_step_for(30.0) == 1
    assert time_step_for(59.999) == 1
    assert time_step_for(60.0) == 2


def test_generate_code_is_deterministic_and_six_digits() -> None:
    secret = b"0" * 20
    code_a = generate_code(secret, 1)
    code_b = generate_code(secret, 1)
    assert code_a == code_b
    assert len(code_a) == 6
    assert code_a.isdigit()


def test_generate_code_changes_per_step() -> None:
    secret = generate_secret()
    assert generate_code(secret, 1) != generate_code(secret, 2)


def test_verify_code_accepts_current_step() -> None:
    secret = generate_secret()
    now = 1_700_000_000.0
    step = time_step_for(now)
    code = generate_code(secret, step)
    assert verify_code(secret, code, unix_time=now) == step


def test_verify_code_tolerates_one_step_of_clock_drift() -> None:
    """Ticket: "Clock drift within one step is tolerated"."""
    secret = generate_secret()
    now = 1_700_000_000.0
    current_step = time_step_for(now)
    previous_code = generate_code(secret, current_step - 1)
    next_code = generate_code(secret, current_step + 1)
    assert verify_code(secret, previous_code, unix_time=now) == current_step - 1
    assert verify_code(secret, next_code, unix_time=now) == current_step + 1


def test_verify_code_rejects_beyond_skew_window() -> None:
    secret = generate_secret()
    now = 1_700_000_000.0
    current_step = time_step_for(now)
    far_code = generate_code(secret, current_step - 2)
    assert verify_code(secret, far_code, unix_time=now) is None


def test_verify_code_rejects_wrong_code() -> None:
    secret = generate_secret()
    assert verify_code(secret, "000000", unix_time=1_700_000_000.0) is None


def test_verify_code_rejects_non_digit_or_wrong_length() -> None:
    secret = generate_secret()
    assert verify_code(secret, "12345", unix_time=0.0) is None
    assert verify_code(secret, "abcdef", unix_time=0.0) is None
    assert verify_code(secret, "1234567", unix_time=0.0) is None


@pytest.mark.parametrize("code", NON_ASCII_DIGIT_CODES)
def test_verify_code_refuses_non_ascii_digits_instead_of_raising(code: str) -> None:
    """#2605: `str.isdigit()` admits other scripts' digits and `hmac.compare_digest(str, str)`
    then raises `TypeError`; such a code is refused like any other wrong one."""
    # Each case passed the old guard: `isdigit()` and six characters.
    assert code.isdigit() and len(code) == TOTP_DIGITS and not code.isascii()
    assert verify_code(generate_secret(), code, unix_time=1_700_000_000.0) is None


class _NeverScanned(str):
    """A `str` that fails the test if anything scans its characters: only `len()` may look at it."""

    def isascii(self) -> bool:
        raise AssertionError("scanned the characters of a code of the wrong length")

    def isdigit(self) -> bool:
        raise AssertionError("scanned the characters of a code of the wrong length")


@pytest.mark.parametrize("length", [0, TOTP_DIGITS - 1, TOTP_DIGITS + 1, 100_000])
def test_verify_code_checks_the_length_before_scanning_the_characters(length: int) -> None:
    """The bounded check comes first, so a string of any other length costs `len()` and no scan."""
    code = _NeverScanned("1" * length)
    assert verify_code(generate_secret(), code, unix_time=0.0) is None


_FIXED_SECRET = b"\x07" * 20
_FIXED_TIME = 1_700_000_000.0
_NON_ASCII_DECIMAL = st.characters(categories=["Nd"], min_codepoint=0x80)


def _window_steps() -> dict[str, int]:
    """Every code the authenticator can show inside the accepted window, with the step
    `verify_code` must report for it (the first one tried, should two steps ever share a code)."""
    current_step = time_step_for(_FIXED_TIME)
    steps: dict[str, int] = {}
    for step in range(current_step - TOTP_SKEW_STEPS, current_step + TOTP_SKEW_STEPS + 1):
        steps.setdefault(generate_code(_FIXED_SECRET, step), step)
    return steps


def _respell(code: str, zero: int) -> str:
    """`code` written with the decimal digits of the script whose zero is code point *zero*."""
    return "".join(chr(zero + int(digit)) for digit in code)


_WINDOW_STEPS = _window_steps()
_WINDOW_CODES = st.sampled_from(list(_WINDOW_STEPS))
#: A right code written in Arabic-Indic or fullwidth digits. It is refused too: a fix that
#: normalised instead of refusing (NFKC turns fullwidth digits into ASCII ones) would accept it.
_WINDOW_CODES_IN_OTHER_DIGITS = st.builds(
    _respell, _WINDOW_CODES, st.sampled_from([0x0660, 0xFF10])
)


@given(
    code=st.one_of(
        st.text(),
        st.text(alphabet=_NON_ASCII_DECIMAL, min_size=TOTP_DIGITS, max_size=TOTP_DIGITS),
        st.text(alphabet=st.characters(categories=["Nd"]), max_size=2 * TOTP_DIGITS),
        _WINDOW_CODES,  # the accepting side: without it the property would only see refusals
        _WINDOW_CODES_IN_OTHER_DIGITS,
    )
)
def test_verify_code_never_raises_and_accepts_exactly_the_window_codes(code: str) -> None:
    assert verify_code(_FIXED_SECRET, code, unix_time=_FIXED_TIME) == _WINDOW_STEPS.get(code)


def test_verify_code_never_tries_a_negative_time_step() -> None:
    secret = generate_secret()
    # Near unix epoch: current_step is 0, so `-1` would be negative and must
    # be skipped rather than wrapping/crashing.
    assert verify_code(secret, "000000", unix_time=0.0, skew_steps=1) in (None, 0)


def test_otpauth_uri_contains_expected_fields() -> None:
    secret = generate_secret()
    uri = otpauth_uri(secret=secret, account_name="alice", issuer="CandleViewer")
    assert uri.startswith("otpauth://totp/CandleViewer:alice?")
    assert "algorithm=SHA1" in uri
    assert "digits=6" in uri
    assert f"period={TOTP_STEP_SECONDS}" in uri
    assert secret_to_base32(secret) in uri
