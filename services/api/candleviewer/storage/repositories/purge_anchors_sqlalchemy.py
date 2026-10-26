"""Postgres adapter for `PurgeAnchorStore` (E16-T06 #490; M10).

SQLAlchemy Core over `db.models.idempotency_anchors` (21-database-schema.md Sec.3.3.10, revision
`0052_ia_purge_anchor`): every value is a bound parameter, every statement is pinned to the
operation `purgeRecordedData`, and no statement returns `client_ref` or `request_sha256`
(SR-E29-07's rule, kept for this operation too). `find_statement` matches (`created_by`, operation,
`client_ref`) and answers whether the stored fingerprint equals the one given; the `sha256_hex`
domain is compared as text. `create_statement` is `ON CONFLICT (created_by, operation,
client_ref) DO NOTHING RETURNING id`, so a key the principal already holds writes nothing.

The store is a `CappedStore`: each unit of work caps its statements at `statement_timeout`, and a
failure leaves as a typed storage error, unchained and with no value (C-12.6).
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from candleviewer.db.models import idempotency_anchors
from candleviewer.storage.repositories.idempotency_anchors import (
    require_client_ref,
    require_fingerprint,
)
from candleviewer.storage.repositories.orders_sqlalchemy import CappedStore
from candleviewer.storage.repositories.purge_anchors import (
    PURGE_OPERATION,
    NewPurgeAnchor,
    PurgeAnchor,
)

__all__ = ["PURGE_COLUMNS", "SqlAlchemyPurgeAnchorStore", "create_statement", "find_statement"]

_A = idempotency_anchors.c
#: The columns `find` reads: never the key or the fingerprint.
PURGE_COLUMNS: Final = (_A.id, _A.before_us)


def find_statement(created_by: UUID, client_ref: str, request_sha256: str) -> sa.Select[Any]:
    matches = sa.type_coerce(_A.request_sha256, sa.Text) == request_sha256
    return sa.select(*PURGE_COLUMNS, matches.label("body_matches")).where(
        _A.created_by == created_by,
        _A.operation == PURGE_OPERATION,
        _A.client_ref == client_ref,
    )


def create_statement(anchor: NewPurgeAnchor) -> sa.Insert:
    """Writes nothing, and returns no row, when the principal's key is held already."""
    stmt = pg_insert(idempotency_anchors).values(
        id=anchor.id,
        created_by=anchor.created_by,
        operation=PURGE_OPERATION,
        client_ref=anchor.client_ref,
        request_sha256=anchor.request_sha256,
        before_us=anchor.before_us,
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=[_A.created_by, _A.operation, _A.client_ref])
    return stmt.returning(_A.id)


class SqlAlchemyPurgeAnchorStore(CappedStore):
    """`PurgeAnchorStore` over one relational repository (asyncpg)."""

    async def find(
        self, created_by: UUID, client_ref: str, request_sha256: str
    ) -> PurgeAnchor | None:
        require_client_ref(client_ref)
        require_fingerprint(request_sha256)
        stmt = find_statement(created_by, client_ref, request_sha256)
        async with self._unit_of_work() as uow:
            m = (await uow.session.execute(stmt)).mappings().first()
        if m is None:
            return None
        return PurgeAnchor(
            id=UUID(str(m["id"])),
            before_us=int(m["before_us"]),
            body_matches=bool(m["body_matches"]),
        )

    async def create(self, anchor: NewPurgeAnchor) -> bool:
        async with self._unit_of_work() as uow:
            done = (await uow.session.execute(create_statement(anchor))).first()
            await uow.commit()
        return done is not None
