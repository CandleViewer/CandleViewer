"""Single-use recovery codes: generation, keyed hashing, formatting (E09-S02).

Ticket "Technical notes": "Codes are generated from secrets.token_bytes
with an unambiguous alphabet (no 0/O/1/l) and are grouped for readability."

Entropy (PR #1618 security review, blocking 1): each code is 28 symbols
drawn uniformly by `secrets.choice` from a 31-symbol alphabet, i.e.
log2(31) * 28 = 4.954 * 28 ~= 138.7 bits (31**28 > 2**128), grouped as
seven groups of four (`XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX`) so it stays
human-typeable.

Storage: `recovery_codes.code_hash` holds HMAC-SHA256(key, normalized code)
as hex (same 64-hex `sha256_hex` column domain), never a plain SHA-256.
The HMAC key is a server-side secret supplied by the composition root
(`AuthService`, same boundary as `TotpEncryptor`'s key — M18 may not import
`candleviewer.secrets`, see `envelope.py`); a database dump alone therefore
cannot be used to verify guesses offline. The HMAC is deterministic so the
existing equality-indexed lookup and single-use conditional UPDATE keep
working; the final comparison of digests uses `hmac.compare_digest`.
"""

from __future__ import annotations

import hmac
import math
import secrets
from hashlib import sha256

#: Ticket: "no 0/O/1/l" (unambiguous when read aloud or handwritten).
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

#: Ticket "Scope / Deliverables": "10 single-use codes generated at enrolment".
RECOVERY_CODE_COUNT = 10

_GROUP_LEN = 4
_GROUPS = 7  # 28 alphabet characters total -> ~138.7 bits
CODE_LENGTH = _GROUP_LEN * _GROUPS

#: Entropy of one generated code, in bits (asserted >= 128 by the tests).
ENTROPY_BITS = CODE_LENGTH * math.log2(len(_ALPHABET))

#: Minimum HMAC key length (bytes).
MIN_KEY_LEN = 32


def generate_recovery_code() -> str:
    """One human-typeable, grouped recovery code (7 groups of 4)."""
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[i : i + _GROUP_LEN] for i in range(0, len(raw), _GROUP_LEN))


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    return [generate_recovery_code() for _ in range(count)]


def normalize_recovery_code(code: str) -> str:
    """Case/whitespace/dash-insensitive canonical form used for hashing."""
    return code.strip().upper().replace("-", "").replace(" ", "")


def hash_recovery_code(code: str, *, key: bytes) -> str:
    """HMAC-SHA256 (hex) of the normalized code under the server-side `key`.
    Never logs or returns the key."""
    if len(key) < MIN_KEY_LEN:
        raise ValueError("recovery-code HMAC key must be at least 32 bytes")
    normalized = normalize_recovery_code(code)
    return hmac.new(key, normalized.encode("utf-8"), sha256).hexdigest()


def recovery_code_matches(code: str, stored_hash: str, *, key: bytes) -> bool:
    """Constant-time check of `code` against a stored keyed hash."""
    return hmac.compare_digest(hash_recovery_code(code, key=key), stored_hash)
