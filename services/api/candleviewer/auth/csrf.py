"""SR-041 double-submit CSRF token codec (#2090, `22-api-openapi.yaml` info "CSRF").

Pure logic, no framework or I/O imports. The HTTP edge (`candleviewer.api.csrf`)
owns the cookie, the header and the refusal; this module only mints and checks
tokens.

Token: ``<nonce>.<mac>``, both unpadded base64url.

* ``nonce`` — 32 bytes (256 bit) from `secrets` (CSPRNG).
* ``mac`` — ``HMAC-SHA256(csrf_key, len(sid) || sid || nonce)`` where
  ``len(sid)`` is the 4-byte big-endian length of the UTF-8 session id, so no
  (sid, nonce) pair can be re-split into another.

``csrf_key`` is dedicated (never the TOTP/recovery/refresh material) and
rotatable: the codec mints with the *current* key and verifies against the
current key and any *previous* keys, so a key rotation does not strand open
tabs. Every comparison is `hmac.compare_digest`; decoding is strict
(canonical base64url, exact lengths) so a token has exactly one encoding.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import struct
from enum import StrEnum

CSRF_COOKIE = "__Host-cv_csrf"
CSRF_HEADER = "X-CSRF-Token"

NONCE_BYTES = 32
MAC_BYTES = 32
MIN_KEY_BYTES = 32
#: `components.parameters.CsrfToken.schema.maxLength`.
MAX_TOKEN_LEN = 256


class CsrfVerdict(StrEnum):
    """Outcome of `CsrfCodec.verify`; the non-OK values are audit reasons."""

    OK = "ok"
    #: Not ``<nonce>.<mac>`` in canonical base64url with the exact lengths.
    BAD_MAC = "bad_mac"
    #: Well-formed, but the MAC does not verify for this session under any key
    #: (another session's token, a tampered MAC/nonce, or a retired key).
    WRONG_SESSION = "wrong_session"


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str, expected_len: int) -> bytes | None:
    """Strict unpadded base64url decode; `None` unless canonical and exact length."""
    if not text or not text.isascii():
        return None
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        return None
    if len(raw) != expected_len or _b64e(raw) != text:
        return None
    return raw


def _message(session_id: str, nonce: bytes) -> bytes:
    sid = session_id.encode("utf-8")
    return struct.pack(">I", len(sid)) + sid + nonce


class CsrfCodec:
    """Mint / verify session-bound CSRF tokens.

    *key* mints and verifies; *previous_keys* only verify (rotation window).
    """

    def __init__(self, key: bytes, previous_keys: tuple[bytes, ...] = ()) -> None:
        for k in (key, *previous_keys):
            if len(k) < MIN_KEY_BYTES:
                raise ValueError(f"CSRF key must be at least {MIN_KEY_BYTES} bytes")
        self._key = key
        self._verify_keys = (key, *(k for k in previous_keys if k != key))

    @staticmethod
    def _mac(key: bytes, session_id: str, nonce: bytes) -> bytes:
        return hmac.new(key, _message(session_id, nonce), hashlib.sha256).digest()

    def issue(self, session_id: str, *, nonce: bytes | None = None) -> str:
        """A fresh token bound to *session_id*. *nonce* is for tests only."""
        if not session_id:
            raise ValueError("session id is required")
        n = secrets.token_bytes(NONCE_BYTES) if nonce is None else nonce
        if len(n) != NONCE_BYTES:
            raise ValueError(f"nonce must be {NONCE_BYTES} bytes")
        return f"{_b64e(n)}.{_b64e(self._mac(self._key, session_id, n))}"

    def verify(self, token: str, session_id: str) -> CsrfVerdict:
        """Check *token* against the server-resolved *session_id*."""
        if not session_id or len(token) > MAX_TOKEN_LEN or token.count(".") != 1:
            return CsrfVerdict.BAD_MAC
        nonce_txt, mac_txt = token.split(".")
        nonce = _b64d(nonce_txt, NONCE_BYTES)
        mac = _b64d(mac_txt, MAC_BYTES)
        if nonce is None or mac is None:
            return CsrfVerdict.BAD_MAC
        ok = False
        for key in self._verify_keys:  # no early exit: constant work per key set
            ok |= hmac.compare_digest(mac, self._mac(key, session_id, nonce))
        return CsrfVerdict.OK if ok else CsrfVerdict.WRONG_SESSION


def tokens_equal(a: str, b: str) -> bool:
    """Double-submit equality, constant time (non-ASCII never matches)."""
    if not a.isascii() or not b.isascii():
        return False
    return hmac.compare_digest(a.encode("ascii"), b.encode("ascii"))
