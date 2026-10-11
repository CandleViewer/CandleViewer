"""AES-256-GCM envelope primitives (ADR-0009 item 2, e27-kek.md §5 SR-003). Private to M2.

Data layer: credential ciphertext under the per-row DEK,
AAD = `cv-cred-v1|account_id|credential_id|field`. Wrap layer: DEK under the KEK,
AAD = `cv-dek-v1|credential_id|kek_version` (binds the wrap to its row and KEK version).
Every encryption draws a fresh 12-byte nonce from `os.urandom`; it is never reused.
"""

from __future__ import annotations

import os
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_LEN = 12
KEY_LEN = 32


def new_dek() -> bytearray:
    return bytearray(os.urandom(KEY_LEN))


def new_nonce() -> bytes:
    return os.urandom(NONCE_LEN)


def cred_aad(account_id: UUID, credential_id: UUID, field: str) -> bytes:
    return b"|".join((b"cv-cred-v1", account_id.bytes, credential_id.bytes, field.encode()))


def dek_aad(credential_id: UUID, kek_version: int) -> bytes:
    return b"|".join((b"cv-dek-v1", credential_id.bytes, str(kek_version).encode()))


def seal(key: bytes | bytearray, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes]:
    """Return `(nonce, ciphertext||tag)` under a fresh nonce."""
    nonce = new_nonce()
    return nonce, AESGCM(bytes(key)).encrypt(nonce, plaintext, aad)


def open_(key: bytes | bytearray, nonce: bytes, sealed: bytes, aad: bytes) -> bytes:
    """Decrypt; raises `cryptography.exceptions.InvalidTag` on any tamper/wrong key."""
    return AESGCM(bytes(key)).decrypt(nonce, sealed, aad)


def zero(buf: bytearray) -> None:
    """Best-effort wipe (CPython may hold other copies; SR-009 residual)."""
    for i in range(len(buf)):
        buf[i] = 0
