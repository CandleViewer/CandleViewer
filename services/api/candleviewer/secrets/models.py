"""Domain models for the secrets module (M2). Metadata only — no key material."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class StoredCredential:
    """Coarse result of `store()`; the only key-derived value is `key_id_last4`."""

    key_id: UUID
    account_id: UUID
    label: str
    key_id_last4: str
    kek_version: int


@dataclass(frozen=True)
class KekCheckResult:
    version: int | None
    kcv_ok: bool
    reason: str | None


@dataclass(frozen=True)
class RewrapReport:
    from_version: int
    to_version: int
    rewrapped: int
    remaining: int
    failed: tuple[UUID, ...] = ()


@dataclass
class CredentialRow:
    """`api_keys` envelope columns (21-database-schema.md §3.2.2/§3.2.3a). Internal to M2.

    `key_id_enc` and `secret_enc` are both ``nonce || ct || tag``; `enc_nonce` duplicates the
    nonce of `secret_enc` (the 0017 column is NOT NULL with a 12-byte CHECK) and is verified
    equal on read.
    """

    id: UUID
    exchange_account_id: UUID
    env: str
    label: str
    key_id_enc: bytes
    key_id_last4: str
    secret_enc: bytes
    enc_nonce: bytes
    dek_ref: str
    kek_version: int
    permission_snapshot: dict[str, Any] = field(default_factory=dict)
    enc_alg: str = "AES-256-GCM"
    status: str = "pending"
    revoked: bool = False

    def to_record(self) -> dict[str, Any]:
        return asdict(self)
