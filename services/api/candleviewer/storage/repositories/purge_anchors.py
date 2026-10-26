"""Driver-free port for a purge's durable idempotency anchor (E16-T06 #490; 21-database-schema.md
Sec.3.3.10, revisions `0043_order_submission` and `0052_ia_purge_anchor`, M10).

`purgeRecordedData` (`22-api-openapi.yaml`) anchors its `Idempotency-Key` for its caller in
`idempotency_anchors`, operation `purgeRecordedData`, with the request's fingerprint and the
window's exclusive upper bound `before_us`, so the key outlives the process's job store and a
restart. The anchor's id is the purge's job id. `find` matches (`created_by`, operation,
`client_ref`), so another principal's key reads as missing, and compares the fingerprint in SQL,
answering only whether it matches; the key and the fingerprint are never read back (class P1,
21 Sec.12). `create` inserts once: a key the caller already holds writes nothing.

Stdlib only (ADR-0003); `purge_anchors_sqlalchemy.py` is the Postgres implementation. Every value
a writer gives is refused, before any statement, by the rule the table would refuse it with
(`ia_ref_fmt`, the `sha256_hex` domain, `ia_bound`), and no error names a value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Protocol
from uuid import UUID

from candleviewer.storage.repositories.idempotency_anchors import (
    require_client_ref,
    require_fingerprint,
)

__all__ = [
    "MAX_BEFORE_US",
    "PURGE_OPERATION",
    "NewPurgeAnchor",
    "PurgeAnchor",
    "PurgeAnchorStore",
    "require_bound",
]

#: `ia_operation`'s value for a purge anchor.
PURGE_OPERATION: Final = "purgeRecordedData"
#: `before_us` is a Postgres `bigint`.
MAX_BEFORE_US: Final = 2**63 - 1


def require_bound(before_us: int) -> None:
    """`ia_bound`: microseconds since the epoch, UTC, never negative, a `bigint`."""
    if isinstance(before_us, bool) or not isinstance(before_us, int):
        raise ValueError("before_us must be an integer (ia_bound)")
    if not 0 <= before_us <= MAX_BEFORE_US:
        raise ValueError("before_us must be a non-negative bigint (ia_bound)")


@dataclass(frozen=True, slots=True, kw_only=True)
class NewPurgeAnchor:
    """A purge anchor to insert. `id` is the server's (the job's id); `created_by` is the
    authenticated principal's id, never a client value."""

    id: UUID
    created_by: UUID
    client_ref: str = field(repr=False)
    request_sha256: str = field(repr=False)
    before_us: int

    def __post_init__(self) -> None:
        require_client_ref(self.client_ref)
        require_fingerprint(self.request_sha256)
        require_bound(self.before_us)


@dataclass(frozen=True, slots=True, kw_only=True)
class PurgeAnchor:
    """A purge anchor as `find` reads it: its id (the job's), its bound, and whether the stored
    fingerprint equals the one given."""

    id: UUID
    before_us: int
    body_matches: bool


class PurgeAnchorStore(Protocol):
    """The caller's purge anchors: a principal-scoped read and a one-time insert."""

    async def find(
        self, created_by: UUID, client_ref: str, request_sha256: str
    ) -> PurgeAnchor | None:
        """This principal's purge anchor of the key, and whether its fingerprint is
        `request_sha256`; `None` when there is none (another principal's key reads as missing).
        `ValueError` for a key or fingerprint the table could not hold, before any statement."""
        ...

    async def create(self, anchor: NewPurgeAnchor) -> bool:
        """Insert the anchor: True when this call wrote it, False when the principal holds the
        key already (nothing written)."""
        ...
