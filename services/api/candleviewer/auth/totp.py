"""RFC 6238 TOTP: pure math, no I/O, no storage (E09-S02).

Deliberately dependency-free (stdlib `hmac`/`hashlib`/`struct` only) rather
than pulling in `pyotp` — the algorithm is ~20 lines of RFC 4226/6238 and a
new runtime dependency for it is not justified (`50-security.md` "new deps
need justification"). SHA-1, 6 digits, 30 s step (ticket "Verification").

Replay protection is NOT this module's job: `record_time_step` in
`auth/mfa_repository.py` owns "reject any step <= the last accepted one"
(ticket "Technical notes"). This module only computes/verifies codes.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import struct
from base64 import b32decode, b32encode

#: Ticket: "RFC 6238, SHA-1, 6 digits, 30 s step, +/-1 step skew".
TOTP_DIGITS = 6
TOTP_STEP_SECONDS = 30
TOTP_SKEW_STEPS = 1
#: How far (steps either side of now) `detect_skew` looks for a rejected code: a diagnostic reach,
#: never an acceptance window (SR-021 stays at `TOTP_SKEW_STEPS`). A random wrong code matches one
#: of the 18 steps in between with probability about 1.8e-5.
TOTP_SKEW_DIAGNOSTIC_STEPS = 10

#: Base32 alphabet minus padding, used for the raw seed (20 bytes / 160 bit,
#: matching Google Authenticator's and most authenticator apps' default).
SEED_BYTES = 20


def generate_secret() -> bytes:
    """A fresh random TOTP seed (160-bit, `secrets`-sourced)."""
    return secrets.token_bytes(SEED_BYTES)


def secret_to_base32(secret: bytes) -> str:
    """The displayable/`otpauth://` text form of a raw seed."""
    return b32encode(secret).decode("ascii").rstrip("=")


def base32_to_secret(encoded: str) -> bytes:
    padded = encoded + "=" * (-len(encoded) % 8)
    return b32decode(padded.upper())


def time_step_for(unix_time: float, *, step_seconds: int = TOTP_STEP_SECONDS) -> int:
    return int(unix_time // step_seconds)


def generate_code(secret: bytes, time_step: int, *, digits: int = TOTP_DIGITS) -> str:
    """RFC 4226 HOTP over `time_step` as the 8-byte big-endian counter,
    truncated per RFC 4226 section 5.3."""
    counter = struct.pack(">Q", time_step)
    digest = hmac.new(secret, counter, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10**digits)).zfill(digits)


def verify_code(
    secret: bytes,
    code: str,
    *,
    unix_time: float,
    skew_steps: int = TOTP_SKEW_STEPS,
    step_seconds: int = TOTP_STEP_SECONDS,
) -> int | None:
    """Return the accepted `time_step` if `code` matches within
    `+/-skew_steps` of `unix_time`'s own step, else `None`.

    The caller (`MfaService`) is responsible for replay-rejecting the
    returned step via `MfaMethodRecord`'s persisted last-accepted step —
    this function is stateless and would happily accept the same code
    twice on its own.
    """
    # `str.isdigit()` is true for other scripts' digits too (for example Arabic-Indic), and
    # `hmac.compare_digest(str, str)` raises `TypeError` on non-ASCII text: refuse those like any
    # other wrong code instead of crashing the caller (#2605).
    if not code.isascii() or not code.isdigit() or len(code) != TOTP_DIGITS:
        return None
    current_step = time_step_for(unix_time, step_seconds=step_seconds)
    for delta in range(-skew_steps, skew_steps + 1):
        candidate_step = current_step + delta
        if candidate_step < 0:
            continue
        expected = generate_code(secret, candidate_step)
        if hmac.compare_digest(expected, code):
            return candidate_step
    return None


def detect_skew(
    secret: bytes, code: str, *, unix_time: float, floor: int | None = None
) -> int | None:
    """Diagnostics for a code `verify_code` refused: the signed step offset (matched step minus
    `unix_time`'s own step) at which `code` is the right code for `secret`, when that step lies
    beyond the accepted `TOTP_SKEW_STEPS` but within `TOTP_SKEW_DIAGNOSTIC_STEPS`; else `None`.
    Negative: the authenticator's clock is behind the server's; positive: ahead.

    `floor` is the method's last accepted step: a code for a step at or below it is a replay that
    `record_time_step` refuses whatever the clock says, so it never matches. Never accepts anything
    and a caller must answer a skewed code like any other wrong one. The whole window is always
    scanned, so timing hides the match."""
    if not code.isascii() or not code.isdigit() or len(code) != TOTP_DIGITS:
        return None  # compare_digest raises on non-ASCII text
    current_step = time_step_for(unix_time)
    found: int | None = None
    for distance in range(TOTP_SKEW_STEPS + 1, TOTP_SKEW_DIAGNOSTIC_STEPS + 1):
        for delta in (-distance, distance):
            step = current_step + delta
            if step < 0:
                continue
            matched = hmac.compare_digest(generate_code(secret, step), code)
            if matched and found is None and (floor is None or step > floor):
                found = delta
    return found


def otpauth_uri(*, secret: bytes, account_name: str, issuer: str = "CandleViewer") -> str:
    """`otpauth://totp/...` provisioning URI (ticket "Enrolment": "returning
    the otpauth:// URI and a displayable text secret")."""
    b32 = secret_to_base32(secret)
    label = f"{issuer}:{account_name}"
    return (
        f"otpauth://totp/{label}?secret={b32}&issuer={issuer}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_STEP_SECONDS}"
    )
