"""AES-256-GCM envelope primitives (ADR-0009 item 2, e27-kek.md §5 SR-003). Private to M2.

One storage layout for every sealed field: ``nonce(12) || ciphertext || tag(16)``
(`21-database-schema.md` §3.2.3a). A fresh nonce is drawn from `os.urandom` for every
encryption and never reused. AADs are length-prefixed (u16 big-endian per part) so no
concatenation is ambiguous:
- data layer (SR-003): ``cv-cred-v2 | environment | account_id | credential_id | field``
- wrap layer (#2338): ``cv-dek-v2 | environment | credential_id | kek_version``; the environment
  is the one the KEK was loaded for, so a KEK never opens another environment's wrap. The
  environment-free ``cv-dek-v1`` wrap is refused, never opened.
- auth keyring (#2152, ADR-0009 Amendment 4): wrap ``cv-akey-v1``, TOTP seal ``cv-totp-v1`` and
  the ``cv-rc-v2`` recovery-code digest preimage (`21-database-schema.md` §3.1.5a).

SR-003 `key_version`: there is no separate key-version column — every exchange key rotation
inserts a new `api_keys` row (`api_key_rotations` links old→new), so `credential_id` already
identifies the key version uniquely (recorded deviation, 21-database-schema.md §3.2.3a).

SR-009 residual (accepted, runbook): `AESGCM(bytes(key))` and decrypted `bytes` are immutable
copies `zero()` cannot wipe; zeroisation is best effort on our own `bytearray`s only.
"""

from __future__ import annotations

import os
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_LEN = 12
TAG_LEN = 16
KEY_LEN = 32


def new_dek() -> bytearray:
    return bytearray(os.urandom(KEY_LEN))


def new_nonce() -> bytes:
    return os.urandom(NONCE_LEN)


def aad(*parts: bytes) -> bytes:
    return b"".join(len(p).to_bytes(2, "big") + p for p in parts)


ENVIRONMENTS = frozenset({"live", "demo", "testnet"})


def cred_aad(env: str, account_id: UUID, credential_id: UUID, field: str) -> bytes:
    if env not in ENVIRONMENTS:
        raise ValueError("unknown environment")
    return aad(b"cv-cred-v2", env.encode(), account_id.bytes, credential_id.bytes, field.encode())


def dek_aad(env: str, credential_id: UUID, kek_version: int) -> bytes:
    if env not in ENVIRONMENTS:
        raise ValueError("unknown environment")
    return aad(b"cv-dek-v2", env.encode(), credential_id.bytes, str(kek_version).encode())


#: `auth_keys.purpose` (#2152, `21-database-schema.md` §3.1.5a): the auth keyring's two keys.
AUTH_PURPOSES = ("totp_seal", "recovery_hmac")


def akey_aad(env: str, purpose: str, key_id: UUID, kek_version: int) -> bytes:
    """Auth key wrap (#2152): ``cv-akey-v1 | environment | purpose | id | kek_version``."""
    if env not in ENVIRONMENTS or purpose not in AUTH_PURPOSES:
        raise ValueError("unknown environment or auth key purpose")
    if type(kek_version) is not int or kek_version < 1:
        raise ValueError("kek_version must be a positive int")
    return aad(
        b"cv-akey-v1", env.encode(), purpose.encode(), key_id.bytes, str(kek_version).encode()
    )


def totp_aad(env: str, user_id: UUID) -> bytes:
    """TOTP seed seal (#2152): ``cv-totp-v1 | environment | user_id``."""
    if env not in ENVIRONMENTS:
        raise ValueError("unknown environment")
    return aad(b"cv-totp-v1", env.encode(), user_id.bytes)


def rc_preimage(user_id: UUID, normalised: bytes) -> bytes:
    """Recovery-code digest preimage (#2152): ``cv-rc-v2 | user_id | normalised code``."""
    return aad(b"cv-rc-v2", user_id.bytes, normalised)


def seal(key: bytes | bytearray, plaintext: bytes | bytearray, aad_: bytes) -> bytes:
    """Return ``nonce || ciphertext || tag`` under a fresh nonce."""
    nonce = new_nonce()
    return nonce + AESGCM(bytes(key)).encrypt(nonce, bytes(plaintext), aad_)


def open_(key: bytes | bytearray, blob: bytes, aad_: bytes) -> bytearray:
    """Decrypt a sealed blob. `ValueError` on bad shape; `InvalidTag` on any tamper/wrong key."""
    if len(blob) < NONCE_LEN + TAG_LEN:
        raise ValueError("sealed blob too short")
    return bytearray(AESGCM(bytes(key)).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], aad_))


def zero(buf: bytearray) -> None:
    """Best-effort wipe of a mutable buffer (see SR-009 residual above)."""
    for i in range(len(buf)):
        buf[i] = 0
