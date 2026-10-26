"""An in-memory `PurgeAnchorStore` for the purge route's tests (E16-T06 #490).

It keeps rows as `idempotency_anchors` would (`ux_ia_principal_ref`: one row per principal and
key), compares the fingerprint and never returns it. It outlives any one router built over it, so
a test models a restart by building a fresh router (a fresh job store and lock) over the same
instance, the durable store.
"""

from __future__ import annotations

from uuid import UUID

from candleviewer.storage.repositories.idempotency_anchors import (
    require_client_ref,
    require_fingerprint,
)
from candleviewer.storage.repositories.purge_anchors import NewPurgeAnchor, PurgeAnchor


class InMemoryPurgeAnchors:
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, str], NewPurgeAnchor] = {}
        self.creates = 0
        #: When set, `find` and `create` raise it, as a storage outage would.
        self.fail: Exception | None = None

    async def find(
        self, created_by: UUID, client_ref: str, request_sha256: str
    ) -> PurgeAnchor | None:
        if self.fail is not None:
            raise self.fail
        require_client_ref(client_ref)
        require_fingerprint(request_sha256)
        row = self.rows.get((created_by, client_ref))
        if row is None:
            return None
        return PurgeAnchor(
            id=row.id, before_us=row.before_us, body_matches=row.request_sha256 == request_sha256
        )

    async def create(self, anchor: NewPurgeAnchor) -> bool:
        if self.fail is not None:
            raise self.fail
        self.creates += 1
        key = (anchor.created_by, anchor.client_ref)
        if key in self.rows:
            return False
        self.rows[key] = anchor
        return True
