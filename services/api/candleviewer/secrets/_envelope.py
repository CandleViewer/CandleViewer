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
- audit export key (#889, ADR-0039): the seed's seal ``cv-export-seed-v1`` (`_export_key.py`) and
  its DEK's wrap ``cv-export-dek-v1 | environment | key_id | kek_version`` (`export_dek_aad`).

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


def export_seed_aad(env: str, key_id: str, public_key: bytes) -> bytes:
    """Audit export seed seal under the row's DEK (#889, ADR-0039 decisions 2 and 4):
    ``cv-export-seed-v1 | environment | key_id | public_key (32 raw bytes)``. No KEK version, as
    in `cred_aad`: the DEK's own wrap binds it (`_export_key.py`)."""
    if env not in ENVIRONMENTS or len(public_key) != 32:
        raise ValueError("unknown environment or export public key length")
    return aad(b"cv-export-seed-v1", env.encode(), key_id.encode(), bytes(public_key))


def export_dek_aad(env: str, key_id: str, kek_version: int) -> bytes:
    """Audit export DEK wrap under the KEK (#889 S6, ADR-0039 decision 2): its own label, so
    neither a credential wrap (`cv-dek-v2`) nor an auth key wrap opens as a signing key's DEK."""
    if env not in ENVIRONMENTS or type(kek_version) is not int or kek_version < 1:
        raise ValueError("unknown environment, or kek_version not a positive int")
    return aad(b"cv-export-dek-v1", env.encode(), key_id.encode(), str(kek_version).encode())


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
