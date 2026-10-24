"""Postgres adapter for `RecordedStopStore` (E29-T04 #913; M10).

SQLAlchemy Core over `db.models.recorded_stops` (revision `0043_order_submission`,
21-database-schema.md Sec.3.3.11): every value is a bound parameter, and reads select the
allow-list `STOP_COLUMNS`, every column in table order. Every statement filters on
`recorded_stops.exchange_account_id` (C-12.4) but the one in `UNSCOPED`, the insert, which writes
the account each row names, and the two in `SYSTEM_STATEMENTS`, reached only at startup: the sweep,
which covers every account when it is asked to (`EVERY_ACCOUNT`), and the database's clock, which
reads no table; a unit test pins both sets, as `orders_sqlalchemy.UNSCOPED` and
`trade_groups_sqlalchemy.SYSTEM_STATEMENTS` are pinned.

`insert_stops_statement` writes one request's rows in one statement, once `check_request` found
them one request's; the first persist of an entry (`submissions_sqlalchemy.py`) runs it in its own
transaction, with the order, and `insert` in one of its own, awaiting the writer's write-ahead audit
of the request, when given, bounded, before the commit (C-2.9). `settle` locks the request's rows
`FOR UPDATE` in id order, so two writers of one request never deadlock, then runs the
compare-and-set: each row must still be in flight (`pending`, `answered_at` NULL), or nothing is
written (`StaleRecordedStop`). An answer sets `answered_at`; a refusal or a read that does not show
the stop makes the row `void` and stamps `closed_at` (`rs_times`). The writer's write-ahead audit,
when given, is awaited, bounded, before the commit (C-2.9). `waiting_for_key_statement` reads a
key's rows that hold it until the complete read (`RecordedStopStore.waiting_for_key`): the
unanswered ones past their request's bound (`request_cutoff`; every unanswered one when the bound
is missing or unusable), and an entry's pending rows whose order of the row's account
`WAITING_ENTRY` holds.

Slice 3's complete read (S3-H): `put_in_force` locks the key's live rows in id order, compares,
then replaces before it sets, so `ux_rs_in_force` never holds two; `resolve` locks as `settle` does
and compares-and-sets in its UPDATE (each row's key and `answered_at` as read);
`waiting_keys_statement` shares `_waits` with the key's read. An order step that settles its
entry's rows (`orders_sqlalchemy.settle_entry_stops_statement`) locks them in its UPDATE's scan
order, not in id order: a step and a read meeting on an entry's two rows can deadlock, which
Postgres breaks by failing one of the two transactions, nothing written by it (the step's write
or the read's, which the next request reads again). Ordering that lock, with a race test on
Postgres, is left to H3: it is `orders_sqlalchemy.py`'s.

`release_and_bind` locks its pair `FOR UPDATE` in id order first, as `settle` and `put_in_force`
lock theirs, so none of them deadlock; it then releases and binds in one unit of work and awaits
the writer's write-ahead audit, bounded, before the one commit (C-2.9): a miss on either update,
or an audit that fails or is late, writes nothing.

`void_orphans_statement` is R10's startup sweep (`RecordedStopStore.void_orphans`): one UPDATE that
voids the pending entry-attach rows of an order of their account that was never placed (never sent,
`UNSENT_ENTRY`; or refused by its create's own answer, `REFUSED_ENTRY` with the `REFUSED_BY` event),
returning ids and kinds for the caller's write-ahead audit, which is awaited, bounded, before the
commit. It names the rows it may void, never the ones it may not, so a row of any other order
(killed after its send, ended out of `unknown`, or with an end the exchange did not confirm
unfilled) is left for the complete read (21 Sec.3.3.11). Slice 3's startup wiring must run it before
the order machines hydrate and before order entry opens: a sweep later than that could void the rows
of an entry between its first persist and its send.

The store is a `CappedStore`: each unit of work caps its statements at `statement_timeout`, and
a failure leaves as `OrderConstraintError(name)` (`ux_rs_in_flight` among them),
`StorageQueryFailed(sqlstate)` or `StorageTierUnavailable`, unchained and with no value (C-12.6).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa

from candleviewer.db.models import order_events, orders, recorded_stops
from candleviewer.storage.repositories.orders import (
    require_aware,
    require_exchange_order_id,
    typed_fields,
)
from candleviewer.storage.repositories.orders_sqlalchemy import (
    OMS_STATEMENT_TIMEOUT_MS,
    CappedStore,
    require_audit_bound,
)
from candleviewer.storage.repositories.recorded_stops import (
    EVERY_ACCOUNT,
    LIVE_STOP_STATUSES,
    REFUSED_BY,
    REFUSED_ENTRY,
    STOP_AUDIT_TIMEOUT_S,
    UNSENT_ENTRY,
    WAITING_ENTRY,
    FillPosition,
    InForce,
    InForceWriteAhead,
    InsertWriteAhead,
    NewRecordedStop,
    RecordedStopNotBindable,
    RecordedStopRow,
    ReleaseWriteAhead,
    ResolveOutcome,
    ResolveWriteAhead,
    SettleWriteAhead,
    StaleRecordedStop,
    StopOutcome,
    SweepScope,
    SweepWriteAhead,
    SweptStop,
    check_in_force,
    check_request,
    check_resolve,
    request_cutoff,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import bounded_write_ahead

__all__ = [
    "STOP_COLUMNS", "STOP_FIELDS", "SYSTEM_STATEMENTS", "UNSCOPED", "SqlAlchemyRecordedStopStore",
    "bind_statement", "clock_statement", "for_exchange_order_statement", "for_order_statement",
    "in_force_for_key_statement", "in_force_statement", "in_given_order", "insert_stops_statement",
    "live_for_key_statement", "lock_key_statement", "lock_stops_statement", "release_statement",
    "replace_statement", "resolve_statement", "settle_statement", "stop_row", "to_replace",
    "void_orphans_statement", "waiting_for_key_statement", "waiting_keys_statement",
]  # fmt: skip

_S = recorded_stops.c
STOP_FIELDS: Final = tuple(f.name for f in fields(RecordedStopRow))
STOP_COLUMNS: Final = tuple(_S[name] for name in STOP_FIELDS)
#: Statements without a `recorded_stops.exchange_account_id` filter (module docstring); tested.
UNSCOPED: Final = frozenset({"insert_stops_statement"})
#: Statements that may cover every account, reached only at startup (SEC-2A-02): the sweep, and
#: `clock_statement`, which reads no table: the database clock for the startup floor, 21 Sec.3.3.11.
SYSTEM_STATEMENTS: Final = frozenset({"void_orphans_statement", "clock_statement"})
_UUIDS: Final = typed_fields(RecordedStopRow, UUID)


def clock_statement() -> sa.Select[Any]:
    """The database's clock, the startup floor's start (S3-H's Q7): it reads no table."""
    return sa.select(sa.func.now())


def insert_stops_statement(stops: Sequence[NewRecordedStop]) -> sa.Insert:
    """One request's rows in one multi-row INSERT; `ValueError` unless they are one request's."""
    check_request(stops)
    rows = [{f.name: getattr(stop, f.name) for f in fields(stop)} for stop in stops]
    return sa.insert(recorded_stops).values(rows).returning(*STOP_COLUMNS)


def lock_stops_statement(account_id: UUID, record_ids: Sequence[UUID]) -> sa.Select[Any]:
    """The account's rows among `record_ids`, `FOR UPDATE` in id order."""
    stmt = sa.select(_S.id).where(
        _S.exchange_account_id == account_id, _S.id.in_(sorted(set(record_ids)))
    )
    return stmt.order_by(_S.id).with_for_update()


def settle_statement(
    account_id: UUID, record_ids: Sequence[UUID], outcome: StopOutcome, at: datetime
) -> sa.Update:
    """The answer of the request in flight (module docstring), only while each row is."""
    values: dict[str, Any]
    if outcome == "answered":
        values = {"answered_at": at}
    elif outcome == "refused":
        values = {"status": "void", "answered_at": at, "closed_at": at}
    else:  # not_shown: the exchange never answered, a complete read decided it
        values = {"status": "void", "closed_at": at}
    stmt = sa.update(recorded_stops).where(
        _S.exchange_account_id == account_id,
        _S.id.in_(sorted(set(record_ids))),
        _S.status == "pending",
        _S.answered_at.is_(None),
    )
    return stmt.values(values).returning(*STOP_COLUMNS)


def for_order_statement(account_id: UUID, order_id: UUID) -> sa.Select[Any]:
    stmt = sa.select(*STOP_COLUMNS).where(
        _S.exchange_account_id == account_id, _S.order_id == order_id
    )
    return stmt.order_by(_S.created_at, _S.id)


def for_exchange_order_statement(account_id: UUID, exchange_order_id: str) -> sa.Select[Any]:
    """21 Sec.13.1 row 46: the account's rows bound to the id, any status, oldest first; the
    partial `ix_rs_exch_id` serves it."""
    stmt = sa.select(*STOP_COLUMNS).where(
        _S.exchange_account_id == account_id, _S.exchange_order_id == exchange_order_id
    )
    return stmt.order_by(_S.created_at, _S.id)


def release_statement(
    account_id: UUID, record_id: UUID, exchange_order_id: str, at: datetime
) -> sa.Update:
    """24 Sec.8.3 rule 7's release (`rs_release`). `trg_rs_guard` admits it in any status, so the
    status is checked here: an end keeps its id."""
    stmt = sa.update(recorded_stops).where(
        _S.exchange_account_id == account_id,
        _S.id == record_id,
        _S.exchange_order_id == exchange_order_id,
        _S.released_at.is_(None),
        _holds(_S.status, LIVE_STOP_STATUSES),
    )
    return stmt.values(exchange_order_id=sa.null(), released_at=at).returning(*STOP_COLUMNS)


def bind_statement(
    account_id: UUID, record_id: UUID, exchange_order_id: str, released: RecordedStopRow
) -> sa.Update:
    """The successor's bind (`trg_rs_guard` admits that one bind), run after the release of
    `released`: a live row that holds none and was never released, a later row (`created_at`, then
    `id`) of `released`'s side (symbol, `position_idx`, kind), while no row of the account holds
    the id (one holder, never two)."""
    other = recorded_stops.alias("held")
    held: sa.Select[Any] = sa.select(sa.literal_column("1")).where(
        other.c.exchange_account_id == account_id, other.c.exchange_order_id == exchange_order_id
    )
    stmt = sa.update(recorded_stops).where(
        _S.exchange_account_id == account_id,
        _S.id == record_id,
        _S.exchange_order_id.is_(None),
        _S.released_at.is_(None),
        _holds(_S.status, LIVE_STOP_STATUSES),
        sa.type_coerce(_S.symbol, sa.Text) == released.symbol,  # no DOMAIN operator class
        _S.position_idx == released.position_idx,
        _S.kind == released.kind,
        sa.tuple_(_S.created_at, _S.id) > (released.created_at, released.id),
        ~sa.exists(held),
    )
    return stmt.values(exchange_order_id=exchange_order_id).returning(*STOP_COLUMNS)


def live_for_key_statement(account_id: UUID, symbol: str, position_idx: int) -> sa.Select[Any]:
    """21 Sec.13.1 row 45: the key's live rows, oldest first; `ix_rs_live` serves it. The statuses
    render as literals, so the planner matches the partial index's predicate (as `_holds`)."""
    live: sa.BindParameter[Any] = sa.bindparam(
        "live", sorted(LIVE_STOP_STATUSES), expanding=True, literal_execute=True
    )
    stmt = sa.select(*STOP_COLUMNS).where(
        _S.exchange_account_id == account_id,
        sa.type_coerce(_S.symbol, sa.Text) == symbol,  # SQLAlchemy has no DOMAIN operator class
        _S.position_idx == position_idx,
        _S.status.in_(live),
    )
    return stmt.order_by(_S.created_at, _S.id)


def waiting_for_key_statement(
    account_id: UUID, symbol: str, position_idx: int, *, now: datetime, bound_s: float | None
) -> sa.Select[Any]:
    """The key's pending rows that hold it until the complete read, in the account, oldest first:
    the unanswered ones created at or before `request_cutoff(now, bound_s)`, every unanswered one
    when that is None (fail closed), and an entry's rows, answered or not, whose order, of the
    row's account, `WAITING_ENTRY` holds (`ix_rs_live` serves the key). `ValueError` for a naive
    `now`, before any statement."""
    stmt = sa.select(*STOP_COLUMNS).where(
        _S.exchange_account_id == account_id,
        sa.type_coerce(_S.symbol, sa.Text) == symbol,  # SQLAlchemy has no DOMAIN operator class
        _S.position_idx == position_idx,
        _waits(now, bound_s),
    )
    return stmt.order_by(_S.created_at, _S.id)


def waiting_keys_statement(
    account_id: UUID, *, now: datetime, bound_s: float | None
) -> sa.Select[Any]:
    """The account's keys with a row `waiting_for_key_statement` lists, the oldest row's first."""
    stmt = sa.select(_S.symbol, _S.position_idx).where(
        _S.exchange_account_id == account_id, _waits(now, bound_s)
    )
    stmt = stmt.group_by(_S.symbol, _S.position_idx)
    return stmt.order_by(sa.func.min(_S.created_at), _S.symbol, _S.position_idx)


def _waits(now: datetime, bound_s: float | None) -> sa.ColumnElement[bool]:
    cutoff = request_cutoff(now, bound_s)
    unanswered: sa.ColumnElement[bool] = _S.answered_at.is_(None)
    if cutoff is not None:
        unanswered = sa.and_(unanswered, _S.created_at <= cutoff)
    o = orders.c
    ended = sa.select(sa.literal(1)).where(
        o.id == _S.order_id,
        o.exchange_account_id == _S.exchange_account_id,
        *(_holds(o[name], value) for name, value in WAITING_ENTRY.items()),
    )
    entry = sa.and_(_S.source == "entry_attach", sa.exists(ended))
    return sa.and_(_S.status == "pending", sa.or_(unanswered, entry))


def lock_key_statement(account_id: UUID, symbol: str, position_idx: int) -> sa.Select[Any]:
    """The key's live rows (`ix_rs_live`), `FOR UPDATE` in id order."""
    stmt = sa.select(_S.id, _S.kind, _S.status, _S.answered_at, _S.created_at).where(
        _S.exchange_account_id == account_id,
        sa.type_coerce(_S.symbol, sa.Text) == symbol,
        _S.position_idx == position_idx,
        _S.status.in_(("pending", "in_force")),
    )
    return stmt.order_by(_S.id).with_for_update()


def in_force_for_key_statement(account_id: UUID, symbol: str, position_idx: int) -> sa.Select[Any]:
    stmt = sa.select(*STOP_COLUMNS).where(
        _S.exchange_account_id == account_id,
        sa.type_coerce(_S.symbol, sa.Text) == symbol,
        _S.position_idx == position_idx,
        _S.status == "in_force",
    )
    return stmt.order_by(_S.kind)


def to_replace(
    locked: Sequence[Mapping[Any, Any]], rows: Sequence[RecordedStopRow]
) -> tuple[UUID, ...] | None:
    """Per kind, the row in force and older answered rows; None if a row is not locked as read."""
    by_id = {UUID(str(m["id"])): m for m in locked}
    read = {row.id: (row.kind, "pending", row.answered_at) for row in rows}
    held = {i: (m["kind"], m["status"], m["answered_at"]) for i, m in by_id.items()}
    if any(held.get(i) != as_read for i, as_read in read.items()):
        return None
    born = {row.kind: by_id[row.id]["created_at"] for row in rows}

    def replaced(m: Mapping[Any, Any]) -> bool:
        if m["kind"] not in born:
            return False
        older = m["answered_at"] is not None and m["created_at"] < born[m["kind"]]
        return bool(m["status"] == "in_force" or older)

    return tuple(i for i, m in sorted(by_id.items()) if i not in read and replaced(m))


def replace_statement(account_id: UUID, record_ids: Sequence[UUID], at: datetime) -> sa.Update:
    stmt = sa.update(recorded_stops).where(
        _S.exchange_account_id == account_id,
        _S.id.in_(sorted(set(record_ids))),
        _S.status.in_(("pending", "in_force")),
    )
    values = {"status": "replaced", "answered_at": _stamped(at), "closed_at": at}
    return stmt.values(values).returning(*STOP_COLUMNS)


def in_force_statement(
    account_id: UUID, rows: Sequence[RecordedStopRow], at: datetime
) -> sa.Update:
    stmt = sa.update(recorded_stops).where(
        _S.exchange_account_id == account_id, _S.status == "pending", _as_read(rows)
    )
    values = {"status": "in_force", "answered_at": _stamped(at), "in_force_at": at}
    return stmt.values(values).returning(*STOP_COLUMNS)


def resolve_statement(
    account_id: UUID, rows: Sequence[RecordedStopRow], outcome: ResolveOutcome, at: datetime
) -> sa.Update:
    stmt = sa.update(recorded_stops).where(
        _S.exchange_account_id == account_id, _S.status == "pending", _as_read(rows)
    )
    values: dict[str, Any] = {"answered_at": _stamped(at)}
    if outcome == "replaced":  # as `put_in_force` replaces
        values = {"status": "replaced", "answered_at": _stamped(at), "closed_at": at}
    elif outcome != "answered":
        values = {"status": "void", "closed_at": at}
    return stmt.values(values).returning(*STOP_COLUMNS)


def _as_read(rows: Sequence[RecordedStopRow]) -> sa.ColumnElement[bool]:
    """SEC-BND-02: each of `rows` only on the key and with the `answered_at` it was read with."""
    return sa.or_(
        *(
            sa.and_(
                _S.id == r.id,
                sa.type_coerce(_S.symbol, sa.Text) == r.symbol,
                _S.position_idx == r.position_idx,
                _S.answered_at.is_not_distinct_from(r.answered_at),
            )
            for r in rows
        )
    )


def _stamped(at: datetime) -> sa.ColumnElement[Any]:
    """`answered_at` kept once set (`trg_rs_guard`), else `at`."""
    return sa.func.coalesce(_S.answered_at, at)


def void_orphans_statement(scope: UUID | SweepScope, at: datetime) -> sa.Update:
    """Pending entry-attach rows whose order, of their account, was never placed (module
    docstring): the `scope` account's, or for `EVERY_ACCOUNT` every account's, the sweep at
    startup. Any other scope, a forgotten account (`None`) among them, is a `TypeError`."""
    o, rs, e = orders.c, recorded_stops.c, order_events.c
    unsent = sa.and_(*(_holds(o[name], value) for name, value in UNSENT_ENTRY.items()))
    refusal = sa.select(sa.literal(1)).where(
        e.order_id == o.id, e.from_state == REFUSED_BY[0], e.to_state == REFUSED_BY[1]
    )
    refused = sa.and_(*(_holds(o[name], value) for name, value in REFUSED_ENTRY.items()))
    unplaced = sa.select(sa.literal(1)).where(
        o.id == rs.order_id,
        o.exchange_account_id == rs.exchange_account_id,
        sa.or_(unsent, sa.and_(refused, sa.exists(refusal))),
    )
    stmt = sa.update(recorded_stops).where(
        rs.source == "entry_attach", rs.status == "pending", sa.exists(unplaced)
    )
    if isinstance(scope, UUID):
        stmt = stmt.where(rs.exchange_account_id == scope)
    elif scope is not EVERY_ACCOUNT:
        raise TypeError("the sweep covers one account, or EVERY_ACCOUNT")
    stmt = stmt.values(status="void", closed_at=at)
    return stmt.returning(rs.id, rs.exchange_account_id, rs.order_id, rs.kind)


def _holds(column: sa.ColumnElement[Any], value: object) -> sa.ColumnElement[bool]:
    """A sweep's proof on one `orders` column: its value, or any of a set of them. A set binds as
    literals: they are the module's constants, never a caller's value."""
    if isinstance(value, frozenset):
        many: sa.BindParameter[Any] = sa.bindparam(
            None, sorted(value), expanding=True, literal_execute=True
        )
        return column.in_(many)
    return column == value


def stop_row(m: Mapping[Any, Any]) -> RecordedStopRow:
    values: dict[str, Any] = {name: m[name] for name in STOP_FIELDS}
    for name in _UUIDS:
        values[name] = None if values[name] is None else UUID(str(values[name]))
    return RecordedStopRow(**values)


def in_given_order(
    rows: Sequence[Mapping[Any, Any]], ids: Sequence[UUID]
) -> tuple[RecordedStopRow, ...]:
    """The rows a statement returned, in the order their ids were given."""
    by_id = {row.id: row for row in map(stop_row, rows)}
    return tuple(by_id[i] for i in ids if i in by_id)


class SqlAlchemyRecordedStopStore(CappedStore):
    """`RecordedStopStore` over one relational repository (asyncpg)."""

    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        statement_timeout_ms: int = OMS_STATEMENT_TIMEOUT_MS,
        audit_timeout_s: float = STOP_AUDIT_TIMEOUT_S,
    ) -> None:
        super().__init__(relational, statement_timeout_ms=statement_timeout_ms)
        self._audit_timeout_s = require_audit_bound(audit_timeout_s)

    async def insert(
        self, stops: Sequence[NewRecordedStop], *, write_ahead: InsertWriteAhead | None = None
    ) -> tuple[RecordedStopRow, ...]:
        stmt = insert_stops_statement(stops)
        async with self._unit_of_work() as uow:
            inserted = list((await uow.session.execute(stmt)).mappings())
            rows = in_given_order(inserted, [stop.id for stop in stops])
            if write_ahead is not None:
                await bounded_write_ahead(write_ahead(rows), self._audit_timeout_s)
            await uow.commit()
        return rows

    async def settle(
        self,
        account_id: UUID,
        record_ids: Sequence[UUID],
        outcome: StopOutcome,
        *,
        at: datetime,
        write_ahead: SettleWriteAhead | None = None,
    ) -> tuple[RecordedStopRow, ...]:
        ids = tuple(record_ids)
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("a settle names each row of the request once")
        require_aware("at", at)
        if outcome != "answered" and write_ahead is None:  # 21 Sec.3.3.11: no void unaudited
            raise ValueError("a void is audited write-ahead (C-2.9): no hook was given")
        async with self._unit_of_work() as uow:
            await uow.session.execute(lock_stops_statement(account_id, ids))
            stmt = settle_statement(account_id, ids, outcome, at)
            rows = list((await uow.session.execute(stmt)).mappings())
            if len(rows) != len(ids):
                raise StaleRecordedStop
            settled = in_given_order(rows, ids)
            if write_ahead is not None:
                await bounded_write_ahead(write_ahead(settled), self._audit_timeout_s)
            await uow.commit()
        return settled

    async def for_order(self, account_id: UUID, order_id: UUID) -> tuple[RecordedStopRow, ...]:
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(for_order_statement(account_id, order_id))
            return tuple(stop_row(m) for m in result.mappings())

    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        stmt = live_for_key_statement(account_id, symbol, position_idx)
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(stmt)
            return tuple(stop_row(m) for m in result.mappings())

    async def for_exchange_order(
        self, account_id: UUID, exchange_order_id: str
    ) -> tuple[RecordedStopRow, ...]:
        require_exchange_order_id(exchange_order_id)
        stmt = for_exchange_order_statement(account_id, exchange_order_id)
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(stmt)
            return tuple(stop_row(m) for m in result.mappings())

    async def release_and_bind(
        self,
        account_id: UUID,
        predecessor_id: UUID,
        successor_id: UUID,
        exchange_order_id: str,
        *,
        at: datetime,
        write_ahead: ReleaseWriteAhead,
    ) -> tuple[RecordedStopRow, RecordedStopRow]:
        require_exchange_order_id(exchange_order_id)
        require_aware("at", at)
        if write_ahead is None:  # 21 Sec.3.3.11: no release unaudited
            raise ValueError("a release is audited write-ahead (C-2.9): no hook was given")
        release = release_statement(account_id, predecessor_id, exchange_order_id, at)
        async with self._unit_of_work() as uow:  # a refusal raised in here rolls both updates back
            pair = (predecessor_id, successor_id)  # locked in id order, as `settle` locks its rows
            await uow.session.execute(lock_stops_statement(account_id, pair))
            freed = list((await uow.session.execute(release)).mappings())
            if not freed:
                raise RecordedStopNotBindable
            old = stop_row(freed[0])
            take = bind_statement(account_id, successor_id, exchange_order_id, old)
            taken = list((await uow.session.execute(take)).mappings())
            if not taken:
                raise RecordedStopNotBindable
            rows = (old, stop_row(taken[0]))
            await bounded_write_ahead(write_ahead(rows), self._audit_timeout_s)
            await uow.commit()
        return rows

    async def waiting_for_key(
        self,
        account_id: UUID,
        symbol: str,
        position_idx: int,
        *,
        now: datetime,
        bound_s: float | None,
    ) -> tuple[RecordedStopRow, ...]:
        # a naive `now` is refused here, before any transaction opens
        stmt = waiting_for_key_statement(account_id, symbol, position_idx, now=now, bound_s=bound_s)
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(stmt)
            return tuple(stop_row(m) for m in result.mappings())

    async def void_orphans(
        self, scope: UUID | SweepScope, *, at: datetime, write_ahead: SweepWriteAhead
    ) -> tuple[SweptStop, ...]:
        require_aware("at", at)
        stmt = void_orphans_statement(scope, at)  # a scope it refuses opens no transaction
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(stmt)
            swept = tuple(
                SweptStop(
                    id=UUID(str(m["id"])),
                    exchange_account_id=UUID(str(m["exchange_account_id"])),
                    order_id=UUID(str(m["order_id"])),
                    kind=m["kind"],
                )
                for m in result.mappings()
            )
            if swept:
                await bounded_write_ahead(write_ahead(swept), self._audit_timeout_s)
            await uow.commit()
        return swept

    async def waiting_keys(
        self, account_id: UUID, *, now: datetime, bound_s: float | None
    ) -> tuple[tuple[str, int], ...]:
        stmt = waiting_keys_statement(account_id, now=now, bound_s=bound_s)  # a naive `now` first
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(stmt)
            return tuple((m["symbol"], m["position_idx"]) for m in result.mappings())

    async def in_force_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(
                in_force_for_key_statement(account_id, symbol, position_idx)
            )
            return tuple(stop_row(m) for m in result.mappings())

    async def database_now(self) -> datetime:
        async with self._unit_of_work() as uow:
            now: datetime = (await uow.session.execute(clock_statement())).scalar_one()
            return now

    async def put_in_force(
        self,
        account_id: UUID,
        rows: Sequence[RecordedStopRow],
        *,
        at: datetime,
        write_ahead: InForceWriteAhead | None = None,
    ) -> InForce:
        check_in_force(account_id, rows)
        require_aware("at", at)
        ids = [row.id for row in rows]
        async with self._unit_of_work() as uow:
            lock = lock_key_statement(account_id, rows[0].symbol, rows[0].position_idx)
            old = to_replace(list((await uow.session.execute(lock)).mappings()), rows)
            if old is None:
                raise StaleRecordedStop
            replaced: tuple[RecordedStopRow, ...] = ()
            if old:  # first: `ux_rs_in_force` admits one row in force per key and kind
                done = await uow.session.execute(replace_statement(account_id, old, at))
                replaced = in_given_order(list(done.mappings()), old)
            done = await uow.session.execute(in_force_statement(account_id, rows, at))
            shown = in_given_order(list(done.mappings()), ids)
            if len(replaced) != len(old) or len(shown) != len(ids):
                raise StaleRecordedStop  # the locks rule it out; never commit half
            if write_ahead is not None:
                await bounded_write_ahead(write_ahead((*replaced, *shown)), self._audit_timeout_s)
            await uow.commit()
        return InForce(replaced=replaced, in_force=shown)

    async def resolve(
        self,
        account_id: UUID,
        rows: Sequence[RecordedStopRow],
        outcome: ResolveOutcome,
        *,
        at: datetime,
        position_state: FillPosition | None = None,
        write_ahead: ResolveWriteAhead | None = None,
    ) -> tuple[RecordedStopRow, ...]:
        check_resolve(rows, outcome, at, position_state, write_ahead)
        ids = [row.id for row in rows]
        async with self._unit_of_work() as uow:
            await uow.session.execute(lock_stops_statement(account_id, ids))
            done = await uow.session.execute(resolve_statement(account_id, rows, outcome, at))
            resolved = in_given_order(list(done.mappings()), ids)
            if len(resolved) != len(ids):
                raise StaleRecordedStop
            if write_ahead is not None:
                hook = write_ahead(resolved, position_state)
                await bounded_write_ahead(hook, self._audit_timeout_s)
            await uow.commit()
        return resolved
