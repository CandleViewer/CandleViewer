"""Postgres adapter for `IdempotencyAnchorStore` (E29-T04 #913; M10).

SQLAlchemy Core over `db.models.idempotency_anchors` (revision `0043_order_submission`,
21-database-schema.md Sec.3.3.10): every value is a bound parameter, and reads select the
allow-list `ANCHOR_COLUMNS`, every column but `client_ref` and `request_sha256`, which no
statement returns (SR-E29-07). `find_statement` matches (`created_by`, `operation`, `client_ref`)
and answers whether the stored fingerprint equals the one given; the `sha256_hex` domain is
compared as text (SQLAlchemy has no operator class for a DOMAIN).

`insert_anchor_statement` is the first persist's (`submissions_sqlalchemy.py`): `ON CONFLICT
(created_by, operation, client_ref) DO NOTHING RETURNING id`, so a key the principal already holds,
or one a concurrent first persist holds, writes nothing and returns no row, and the persist rolls
back as a repeat (`AnchorTakenError`). `record_outcome_statement` is the compare-and-set from NULL;
it is keyed by the anchor's id alone (`BY_ID`), a server-minted id the OMS read through `find` or
wrote itself, never a client value.

The store is a `CappedStore`: each unit of work caps its statements at `statement_timeout`, and
a failure leaves as `OrderConstraintError(name)`, `StorageQueryFailed(sqlstate)` or
`StorageTierUnavailable`, unchained and with no value (C-12.6).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from candleviewer.db.models import idempotency_anchors
from candleviewer.storage.repositories.idempotency_anchors import (
    AnchorOperation,
    AnchorOutcome,
    AnchorRow,
    NewAnchor,
    require_client_ref,
    require_fingerprint,
)
from candleviewer.storage.repositories.orders_sqlalchemy import CappedStore

__all__ = [
    "ANCHOR_COLUMNS", "ANCHOR_FIELDS", "BY_ID", "SqlAlchemyIdempotencyAnchorStore",
    "find_statement", "insert_anchor_statement", "record_outcome_statement",
]  # fmt: skip

_A = idempotency_anchors.c
#: `AnchorRow`'s columns, in table order: every column but the key and the fingerprint.
ANCHOR_FIELDS: Final = tuple(f.name for f in fields(AnchorRow) if f.name != "body_matches")
ANCHOR_COLUMNS: Final = tuple(_A[name] for name in ANCHOR_FIELDS)
#: Statements keyed by the anchor's id alone, not by its principal (a unit test pins the set).
BY_ID: Final = frozenset({"record_outcome_statement"})


def find_statement(
    created_by: UUID, operation: AnchorOperation, client_ref: str, request_sha256: str
) -> sa.Select[Any]:
    matches = sa.type_coerce(_A.request_sha256, sa.Text) == request_sha256
    return sa.select(*ANCHOR_COLUMNS, matches.label("body_matches")).where(
        _A.created_by == created_by, _A.operation == operation, _A.client_ref == client_ref
    )


def insert_anchor_statement(anchor: NewAnchor) -> sa.Insert:
    """Writes nothing, and returns no row, when the principal's key is held already."""
    values = {f.name: getattr(anchor, f.name) for f in fields(anchor)}
    stmt = pg_insert(idempotency_anchors).values(values)
    stmt = stmt.on_conflict_do_nothing(index_elements=[_A.created_by, _A.operation, _A.client_ref])
    return stmt.returning(_A.id)


def record_outcome_statement(anchor_id: UUID, outcome: AnchorOutcome) -> sa.Update:
    """The compare-and-set: the outcome is written only while none is."""
    stmt = sa.update(idempotency_anchors).where(_A.id == anchor_id, _A.outcome_status.is_(None))
    values = {
        "outcome_status": outcome.status,
        "outcome_code": outcome.code,
        "outcome_ret_code": outcome.ret_code,
        "decided_at": outcome.decided_at,
    }
    return stmt.values(values).returning(_A.id)


def _anchor_row(m: Mapping[Any, Any]) -> AnchorRow:
    values: dict[str, Any] = {name: m[name] for name in ANCHOR_FIELDS}
    for name in ("id", "created_by", "trade_group_id", "order_id"):
        values[name] = None if values[name] is None else UUID(str(values[name]))
    return AnchorRow(**values, body_matches=bool(m["body_matches"]))


class SqlAlchemyIdempotencyAnchorStore(CappedStore):
    """`IdempotencyAnchorStore` over one relational repository (asyncpg)."""

    async def find(
        self,
        created_by: UUID,
        operation: AnchorOperation,
        client_ref: str,
        request_sha256: str,
    ) -> AnchorRow | None:
        require_client_ref(client_ref)
        require_fingerprint(request_sha256)
        stmt = find_statement(created_by, operation, client_ref, request_sha256)
        async with self._unit_of_work() as uow:
            m = (await uow.session.execute(stmt)).mappings().first()
        return None if m is None else _anchor_row(m)

    async def record_outcome(self, anchor_id: UUID, outcome: AnchorOutcome) -> bool:
        async with self._unit_of_work() as uow:
            done = (await uow.session.execute(record_outcome_statement(anchor_id, outcome))).first()
            await uow.commit()
        return done is not None
