"""The audit export's signer and signing-key directory, as `audit` sees them (#889 S6b; ADR-0039
decisions 3 and 4). `audit` owns these ports and never imports `secrets` (C-3.2): M2 implements
both, `admin.wiring` mints them and maps M2's refusals, and S10 injects them into the export job.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol
from uuid import UUID

from candleviewer.audit.errors import AuditError

#: The `Job.error` codes a signer failure fails an `audit_export` job with (22 `Job.error`).
SIGNING_FAILURES: Final = frozenset(
    {"signing_key_rotated", "signing_unavailable", "audit_unavailable", "internal_error"}
)


class ExportSigningFailed(AuditError):
    """The signer returned no signature (ADR-0039 decision 3), and the job fails with `code`:
    `signing_key_rotated` (the header's key is no longer the active one), `audit_unavailable`
    (its write-ahead record could not be written), `signing_unavailable` (no KEK, no usable key,
    or the signing failed) or `internal_error` (a request the signer refused as malformed)."""

    def __init__(self, code: str) -> None:
        if code not in SIGNING_FAILURES:
            raise ValueError("not an audit export signing failure code")
        super().__init__(f"the audit export was not signed ({code})")
        self.code = code


@dataclass(frozen=True, slots=True)
class SigningKey:
    """The environment's active export signing key, public material only: no seed, no wrap."""

    key_id: str
    public_key: bytes
    fingerprint_sha256: str


class Signer(Protocol):
    async def sign_audit_export(
        self, key_id: str, digest: bytes, job_id: UUID, actor_user_id: UUID
    ) -> bytes:
        """The 64-byte Ed25519 signature over `cv.audit.export.v1:` and the hex of `digest`, the
        file's SHA-256, with the active key `key_id`, recorded ahead; else `ExportSigningFailed`,
        an `AuditError` that S10's job catches before any handler of a refused audit write."""
        ...


class SigningKeyDirectory(Protocol):
    async def active(self) -> SigningKey | None:
        """The active key's public material, or None while export is unavailable: no seed."""
        ...
