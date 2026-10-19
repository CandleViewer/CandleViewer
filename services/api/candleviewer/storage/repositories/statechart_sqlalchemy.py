"""Postgres row stores of the statechart persistence tables (E50-T62 #3793), built, not wired.

SQLAlchemy Core over `db.models.machine_snapshots`, `machine_drain_journal` and `machine_events`
(`0033_machine_persistence`, 24-internal-schemas.md Sec.17.6), typed with primitives and this
module's frozen records: M10 imports neither `statechart` nor `audit` (C-3.4), and
`candleviewer.statechart_wiring` maps the statechart's DTOs onto the records, as the composition
root does for `SqlAlchemyAuditRepository`. Every value is a bound parameter. The stores never seal
or verify: the HMAC envelope is the trust boundary, and `persistence.Restorer` checks it (CV-C53).

- Snapshots: `upsert` on the machine key; `get`; `list_all`, at most `LIST_MAX_ROWS` rows, else
  `SnapshotListTooLargeError` (a larger fleet is a finding, never a truncated list).
- Journal: `append` with `ON CONFLICT DO NOTHING` on the primary key, so a retried append is a
  no-op; `list_unreplayed` in `ordinal` order (one machine's drain, served by `ix_mdj_pending`);
  `mark_replayed` stamps each named row once.
- Events: `insert_batch` in the order given with `ON CONFLICT (row_hash) DO NOTHING`; `head`, the
  latest `row_hash` or the genesis; `read_chain`, a keyset page of `CHAIN_PAGE_ROWS` rows after a
  `seq`; `read_whole_chain`, every page up to `CHAIN_MAX_ROWS` rows, else `ChainTooLongError`.

One unit of work per call. Its statements are capped at `STORE_TIMEOUT_S` by a transaction-local
`statement_timeout` (lock waits included, as `OMS_STATEMENT_TIMEOUT_MS`), and the whole call (the
pool and the connection too) by a client deadline one second later. Errors are classed by SQLSTATE
as in `backups_sqlalchemy`: 22/23/42/XX is `StorageQueryFailed`; 08/53/57/58, none, a lost
connection, an unreachable server, the pool or the deadline is `StorageTierUnavailable`. No driver
text leaves (a `DETAIL` carries P1 payload values): the message names the call and the SQLSTATE
only, and the error is raised outside the `except`, with no cause or context. Logs carry the call,
the error type and the SQLSTATE, never a payload. Cancellation passes through.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, Final

import sqlalchemy as sa
import structlog
from sqlalchemy import exc as sa_exc
from sqlalchemy.dialects.postgresql import insert as pg_insert

from candleviewer.db.models import machine_drain_journal, machine_events, machine_snapshots
from candleviewer.storage.errors import StorageError, StorageQueryFailed, StorageTierUnavailable
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

#: Every call's bound (#3793): its statements' cap, and one second later the client deadline.
STORE_TIMEOUT_S: Final = 2.0
#: The most rows `list_all` returns; beyond it, `SnapshotListTooLargeError`.
LIST_MAX_ROWS: Final = 10_000
#: One `read_chain` page; and the most rows `read_whole_chain` returns before `ChainTooLongError`.
CHAIN_PAGE_ROWS: Final = 500
CHAIN_MAX_ROWS: Final = 100_000
#: `head` of a machine with no row: `plugins.audit.GENESIS_HASH`, which M10 may not import.
GENESIS_HASH: Final = "0" * 64
_CLIENT_GRACE_S: Final = 1.0
_TIMEOUT: Final = sa.text("SELECT set_config('statement_timeout', :timeout, true)")  # this txn
_TIMEOUT_MS: Final = str(round(STORE_TIMEOUT_S * 1000))
_SQLSTATE: Final = re.compile(r"[0-9A-Z]{5}")
#: SQLSTATE classes of a statement the server refused: data, constraint, syntax/access, internal.
_BUG_CLASSES: Final = frozenset({"22", "23", "42", "XX"})
_MS, _MDJ, _ME = machine_snapshots.c, machine_drain_journal.c, machine_events.c


class SnapshotListTooLargeError(StorageError):
    """`machine_snapshots` holds more than `LIST_MAX_ROWS` rows: the list is refused, not cut."""

    code = "STORAGE_SNAPSHOT_LIST_TOO_LARGE"


class ChainTooLongError(StorageError):
    """A machine's `machine_events` chain is longer than `CHAIN_MAX_ROWS`: refused, not cut."""

    code = "STORAGE_CHAIN_TOO_LONG"


@dataclass(frozen=True, slots=True)
class SnapshotRecord:
    """A `machine_snapshots` row."""

    machine_kind: str
    entity_id: str
    env: str
    cv_schema_version: int
    lib_snapshot_ver: int
    machine_hash: str
    snapshot: dict[str, Any]
    hmac_key_id: str
    hmac_tag: bytes
    state_ids: tuple[str, ...]
    chain_trips: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class JournalRecord:
    """A `machine_drain_journal` row of the machine a call names; `replayed_at` is the store's."""

    send_id: str
    lane: str
    ordinal: int
    event_type: str
    payload: dict[str, Any]
    receipt_error: str | None = None


@dataclass(frozen=True, slots=True)
class EventRecord:
    """A `machine_events` row; `seq` is the database's (0 until the row is stored)."""

    machine_kind: str
    entity_id: str
    env: str
    event_type: str
    payload: dict[str, Any]
    from_states: tuple[str, ...]
    to_states: tuple[str, ...]
    actions_run: tuple[str, ...]
    fault: dict[str, Any] | None
    occurred_at: datetime
    phase: str
    prev_hash: str
    row_hash: str
    seq: int = 0


SNAPSHOT_COLUMNS: Final = tuple(_MS[f.name] for f in fields(SnapshotRecord))
JOURNAL_COLUMNS: Final = tuple(_MDJ[f.name] for f in fields(JournalRecord))
EVENT_COLUMNS: Final = tuple(_ME[f.name] for f in fields(EventRecord))


def _values(record: SnapshotRecord | JournalRecord | EventRecord) -> dict[str, Any]:
    """A record's fields as bound values; a tuple binds as a list (a Postgres array)."""
    values = {f.name: getattr(record, f.name) for f in fields(record)}
    return {name: list(v) if isinstance(v, tuple) else v for name, v in values.items()}


def _key(c: Any, machine_kind: str, entity_id: str, env: str) -> sa.ColumnElement[bool]:
    return sa.and_(c.machine_kind == machine_kind, c.entity_id == entity_id, c.env == env)


def upsert_snapshot_statement(record: SnapshotRecord) -> sa.Insert:
    stmt = pg_insert(machine_snapshots).values(_values(record))
    updated = {c.name: stmt.excluded[c.name] for c in SNAPSHOT_COLUMNS[3:]}  # all but the key
    return stmt.on_conflict_do_update(
        index_elements=("machine_kind", "entity_id", "env"), set_=updated
    )


def get_snapshot_statement(machine_kind: str, entity_id: str, env: str) -> sa.Select[Any]:
    return sa.select(*SNAPSHOT_COLUMNS).where(_key(_MS, machine_kind, entity_id, env))


def list_snapshots_statement() -> sa.Select[Any]:
    order = (_MS.machine_kind, _MS.entity_id, _MS.env)
    return sa.select(*SNAPSHOT_COLUMNS).order_by(*order).limit(LIST_MAX_ROWS + 1)


def append_journal_statement() -> sa.Insert:
    primary_key = ("machine_kind", "entity_id", "env", "send_id")
    return pg_insert(machine_drain_journal).on_conflict_do_nothing(index_elements=primary_key)


def list_unreplayed_statement(machine_kind: str, entity_id: str, env: str) -> sa.Select[Any]:
    pending = sa.and_(_key(_MDJ, machine_kind, entity_id, env), _MDJ.replayed_at.is_(None))
    return sa.select(*JOURNAL_COLUMNS).where(pending).order_by(_MDJ.ordinal)


def mark_replayed_statement(
    machine_kind: str, entity_id: str, env: str, send_ids: Sequence[str]
) -> sa.Update:
    named = (_key(_MDJ, machine_kind, entity_id, env), _MDJ.send_id.in_(list(send_ids)))
    stmt = sa.update(machine_drain_journal).where(*named, _MDJ.replayed_at.is_(None))
    return stmt.values(replayed_at=sa.func.now())


def insert_events_statement() -> sa.Insert:
    return pg_insert(machine_events).on_conflict_do_nothing(index_elements=("row_hash",))


def head_statement(machine_kind: str, entity_id: str, env: str) -> sa.Select[Any]:
    latest = sa.select(_ME.row_hash).where(_key(_ME, machine_kind, entity_id, env))
    return latest.order_by(_ME.seq.desc()).limit(1)


def read_chain_statement(
    machine_kind: str, entity_id: str, env: str, after_seq: int
) -> sa.Select[Any]:
    page = sa.and_(_key(_ME, machine_kind, entity_id, env), _ME.seq > after_seq)
    return sa.select(*EVENT_COLUMNS).where(page).order_by(_ME.seq).limit(CHAIN_PAGE_ROWS)


def _client_deadline() -> asyncio.Timeout:
    """The whole call's bound, the statements' cap plus a second: a connection that never opens or
    a server that never answers ends the call as `StorageTierUnavailable`."""
    return asyncio.timeout(STORE_TIMEOUT_S + _CLIENT_GRACE_S)


def _failure(op: str, exc: Exception) -> StorageError:
    state = getattr(getattr(exc, "orig", None), "sqlstate", None)
    state = state if isinstance(state, str) and _SQLSTATE.fullmatch(state) else None
    if isinstance(exc, sa_exc.DBAPIError):  # the driver's own error: the server, or the statement
        outage = exc.connection_invalidated or (state or "")[:2] not in _BUG_CLASSES
    else:  # unreachable, the pool or the deadline; any other is a statement SQLAlchemy refused
        outage = isinstance(exc, OSError | sa_exc.TimeoutError)
    structlog.get_logger(__name__).error(
        "statechart_store_failed", op=op, outage=outage, error=type(exc).__name__, sqlstate=state
    )
    if outage:
        return StorageTierUnavailable(f"statechart {op} failed (sqlstate {state or 'unknown'})")
    return StorageQueryFailed(state)


class _Store:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._rel = relational

    async def _run(
        self, op: str, stmt: sa.Executable, rows: Sequence[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """One statement (`rows`: executed once per row) in its own capped unit of work, under the
        client deadline, committed unless it is a read; the rows it returns."""
        try:
            async with _client_deadline(), self._rel.unit_of_work() as uow:
                await uow.session.execute(_TIMEOUT, {"timeout": _TIMEOUT_MS})
                result = await uow.session.execute(stmt, rows)
                if isinstance(stmt, sa.Select):
                    return [dict(row) for row in result.mappings()]
                await uow.commit()
                return []
        except (OSError, sa_exc.SQLAlchemyError) as exc:  # the deadline's TimeoutError: an OSError
            failure = _failure(op, exc)
        raise failure  # outside the `except`: no cause and no context, so no driver text


def _snapshot(row: dict[str, Any]) -> SnapshotRecord:
    return SnapshotRecord(**{**row, "state_ids": tuple(row["state_ids"])})


def _event(row: dict[str, Any]) -> EventRecord:
    arrays = {name: tuple(row[name]) for name in ("from_states", "to_states", "actions_run")}
    return EventRecord(**{**row, **arrays})


def _event_values(record: EventRecord) -> dict[str, Any]:
    """`seq` is the database's; no `fault` is SQL NULL (the `me_fault_phase` CHECK), not JSON
    `null`, which the JSONB type would bind for `None`."""
    values = _values(record)
    del values["seq"]
    return values | ({"fault": sa.null()} if record.fault is None else {})


class SqlAlchemySnapshotStore(_Store):
    """`machine_snapshots`: one row per machine key."""

    async def upsert(self, record: SnapshotRecord) -> None:
        await self._run("snapshots.upsert", upsert_snapshot_statement(record))

    async def get(self, machine_kind: str, entity_id: str, env: str) -> SnapshotRecord | None:
        stmt = get_snapshot_statement(machine_kind, entity_id, env)
        rows = await self._run("snapshots.get", stmt)
        return _snapshot(rows[0]) if rows else None

    async def list_all(self) -> tuple[SnapshotRecord, ...]:
        rows = await self._run("snapshots.list_all", list_snapshots_statement())
        if len(rows) > LIST_MAX_ROWS:
            raise SnapshotListTooLargeError(
                f"machine_snapshots holds more than {LIST_MAX_ROWS} rows: refused, not truncated"
            )
        return tuple(_snapshot(row) for row in rows)


class SqlAlchemyJournalStore(_Store):
    """`machine_drain_journal`: one machine's drained events, each replayed once."""

    async def append(
        self, machine_kind: str, entity_id: str, env: str, records: Sequence[JournalRecord]
    ) -> None:
        if records:
            key = {"machine_kind": machine_kind, "entity_id": entity_id, "env": env}
            rows = [key | _values(record) for record in records]
            await self._run("journal.append", append_journal_statement(), rows)

    async def list_unreplayed(
        self, machine_kind: str, entity_id: str, env: str
    ) -> tuple[JournalRecord, ...]:
        stmt = list_unreplayed_statement(machine_kind, entity_id, env)
        return tuple(
            JournalRecord(**row) for row in await self._run("journal.list_unreplayed", stmt)
        )

    async def mark_replayed(
        self, machine_kind: str, entity_id: str, env: str, send_ids: Sequence[str]
    ) -> None:
        if send_ids:
            stmt = mark_replayed_statement(machine_kind, entity_id, env, send_ids)
            await self._run("journal.mark_replayed", stmt)


class SqlAlchemyEventStore(_Store):
    """`machine_events`: each machine's hash chain, in `seq` order."""

    async def insert_batch(self, records: Sequence[EventRecord]) -> None:
        if records:
            rows = [_event_values(record) for record in records]
            await self._run("events.insert_batch", insert_events_statement(), rows)

    async def head(self, machine_kind: str, entity_id: str, env: str) -> str:
        rows = await self._run("events.head", head_statement(machine_kind, entity_id, env))
        return str(rows[0]["row_hash"]) if rows else GENESIS_HASH

    async def read_chain(
        self, machine_kind: str, entity_id: str, env: str, *, after_seq: int = 0
    ) -> tuple[EventRecord, ...]:
        if after_seq < 0:
            raise ValueError("after_seq must be 0 or the last seq a page returned")
        stmt = read_chain_statement(machine_kind, entity_id, env, after_seq)
        return tuple(_event(row) for row in await self._run("events.read_chain", stmt))

    async def read_whole_chain(
        self, machine_kind: str, entity_id: str, env: str
    ) -> tuple[EventRecord, ...]:
        chain: list[EventRecord] = []
        while True:
            after = chain[-1].seq if chain else 0
            page = await self.read_chain(machine_kind, entity_id, env, after_seq=after)
            chain.extend(page)
            if len(chain) > CHAIN_MAX_ROWS:
                raise ChainTooLongError(
                    f"a machine chain holds more than {CHAIN_MAX_ROWS} rows: refused, not truncated"
                )
            if len(page) < CHAIN_PAGE_ROWS:
                return tuple(chain)
