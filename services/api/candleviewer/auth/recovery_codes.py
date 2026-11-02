"""Single-use recovery codes: generation, normalisation, formatting (E09-S02).

Ticket "Technical notes": "Codes are generated from secrets.token_bytes
with an unambiguous alphabet (no 0/O/1/l) and are grouped for readability."

Entropy (PR #1618 security review, blocking 1): each code is 28 symbols
drawn uniformly by `secrets.choice` from a 31-symbol alphabet, i.e.
log2(31) * 28 = 4.954 * 28 ~= 138.7 bits (31**28 > 2**128), grouped as
seven groups of four (`XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX`) so it stays
human-typeable.

Storage: `recovery_codes.code_hash` holds a keyed HMAC-SHA256 digest as hex (the
64-hex `sha256_hex` column domain), never a plain SHA-256. Since #2152 the key is
M2's recovery key, which never leaves `secrets`: MFA gets a code's digests through
its `MfaKeyring` and break-glass through M2's digest session, so a database dump
alone cannot be used to verify guesses offline (`21-database-schema.md` §3.1.5a).
"""

from __future__ import annotations

import math
import secrets

#: Ticket: "no 0/O/1/l" (unambiguous when read aloud or handwritten).
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

#: Ticket "Scope / Deliverables": "10 single-use codes generated at enrolment".
RECOVERY_CODE_COUNT = 10

_GROUP_LEN = 4
_GROUPS = 7  # 28 alphabet characters total -> ~138.7 bits
CODE_LENGTH = _GROUP_LEN * _GROUPS

#: Entropy of one generated code, in bits (asserted >= 128 by the tests).
ENTROPY_BITS = CODE_LENGTH * math.log2(len(_ALPHABET))


def generate_recovery_code() -> str:
    """One human-typeable, grouped recovery code (7 groups of 4)."""
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[i : i + _GROUP_LEN] for i in range(0, len(raw), _GROUP_LEN))


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    return [generate_recovery_code() for _ in range(count)]


def normalize_recovery_code(code: str) -> str:
    """Case/whitespace/dash-insensitive canonical form a digest is made of (M2 keeps its own
    copy, `_auth_keyring.normalise_code`, as M2 cannot import M18)."""
    return code.strip().upper().replace("-", "").replace(" ", "")
