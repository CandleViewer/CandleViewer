"""`statechart_sqlalchemy` stores with a fake unit of work (E50-T62 #3793): the statements they
build, the cap and the client deadline on every call, the bounds, the journal append's conflict
report, and failures that carry and log the SQLSTATE only. Postgres:
`tests/integration/storage/test_statechart_stores_pg.py`."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy import exc as sa_exc
from sqlalchemy.engine import Dialect, make_url
from structlog.testing import capture_logs

from candleviewer.db.models import machine_events
from candleviewer.storage.errors import (
    ChainTooLongError,
    JournalListTooLargeError,
    SnapshotListTooLargeError,
    StorageError,
    StorageQueryFailed,
    StorageTierUnavailable,
)
from candleviewer.storage.repositories import statechart_sqlalchemy as repo
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

_ASYNCPG: Dialect = make_url("postgresql+asyncpg://").get_dialect()()
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
ENTITY = "0a000000-0000-4000-8000-000000000001"
_P1 = "P1-" + "payload-value"  # a value a driver message could echo; it must never leave
SNAP = repo.SnapshotRecord(
    machine_kind="order", entity_id=ENTITY, env="demo", cv_schema_version=2, lib_snapshot_ver=3,
    machine_hash="a" * 64, snapshot={"n": _P1}, hmac_key_id="k1", hmac_tag=bytes(32),
    state_ids=("order.idle",), chain_trips=0, updated_at=NOW,
)  # fmt: skip
JOURNAL = repo.JournalRecord(
    send_id="b" * 32, lane="priority", ordinal=0, event_type="PING", payload={"n": _P1}
)
EVENT = repo.EventRecord(
    machine_kind="order", entity_id=ENTITY, env="demo", event_type="PING", payload={"n": _P1},
    from_states=("a",), to_states=("b",), actions_run=(), fault=None, occurred_at=NOW,
    phase="commit", prev_hash="0" * 64, row_hash="c" * 64,
)  # fmt: skip
_Call = Callable[[Any], Awaitable[object]]
#: Every store method, the store it belongs to, and whether it writes.
CALLS: dict[str, tuple[str, _Call, bool]] = {
    "snapshots.upsert": ("snapshots", lambda s: s.upsert(SNAP), True),
    "snapshots.get": ("snapshots", lambda s: s.get("order", ENTITY, "demo"), False),
    "snapshots.list_all": ("snapshots", lambda s: s.list_all(), False),
    "journal.append": ("journal", lambda s: s.append("order", ENTITY, "demo", [JOURNAL]), True),
    "journal.list_unreplayed": (
        "journal", lambda s: s.list_unreplayed("order", ENTITY, "demo"), False
    ),
    "journal.present": (
        "journal", lambda s: s.present("order", ENTITY, "demo", ["b" * 32]), False
    ),
    "journal.mark_replayed": (
        "journal", lambda s: s.mark_replayed("order", ENTITY, "demo", ["b" * 32]), True
    ),
    "events.insert_batch": ("events", lambda s: s.insert_batch([EVENT]), True),
    "events.head": ("events", lambda s: s.head("order", ENTITY, "demo"), False),
    "events.read_chain": ("events", lambda s: s.read_chain("order", ENTITY, "demo"), False),
}  # fmt: skip


def _inserted_all(stmt: Any, params: Any) -> list[dict[str, Any]]:
    """The default answer: a journal append inserts every row (RETURNING each `send_id`)."""
    if isinstance(stmt, sa.Insert) and stmt.table.name == "machine_drain_journal":
        return [{"send_id": row["send_id"]} for row in params]
    return []


class _Rel:
    """`events`: each unit of work's statements in order (the cap first) and its commit;
    `answer(stmt, params)` gives the rows of every other statement."""

    def __init__(
        self,
        answer: Callable[[Any, Any], list[dict[str, Any]]] = _inserted_all,
        error: BaseException | None = None,
        hang: bool = False,
    ) -> None:
        self.answer, self.error, self.hang = answer, error, hang
        self.events: list[Any] = []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: Any = None) -> Any:
            if stmt is repo._TIMEOUT:
                self.events.append(("cap", params))
                return SimpleNamespace(returns_rows=True, mappings=list)
            self.events.append((stmt, params))
            if self.hang:
                await asyncio.Event().wait()
            if self.error is not None:
                raise self.error
            rows = self.answer(stmt, params)
            return SimpleNamespace(returns_rows=isinstance(stmt, sa.Select), mappings=lambda: rows)

        async def commit() -> None:
            self.events.append("commit")

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _store(kind: str, rel: _Rel) -> Any:
    stores = {
        "snapshots": repo.SqlAlchemySnapshotStore,
        "journal": repo.SqlAlchemyJournalStore,
        "events": repo.SqlAlchemyEventStore,
    }
    return stores[kind](cast(SqlAlchemyRelationalRepository, rel))  # a duck-typed fake


def _sql(stmt: Any) -> str:
    return " ".join(str(stmt.compile(dialect=_ASYNCPG)).split())


def _params(stmt: Any) -> dict[str, Any]:
    return dict(stmt.compile(dialect=_ASYNCPG).params)


def test_the_bounds_are_the_ticket_numbers() -> None:
    assert (repo.STORE_TIMEOUT_S, repo.LIST_MAX_ROWS) == (2.0, 10_000)
    assert (repo.CHAIN_PAGE_ROWS, repo.CHAIN_MAX_ROWS) == (500, 100_000)
    assert repo.GENESIS_HASH == "0" * 64


@pytest.mark.parametrize("name", CALLS)
async def test_every_call_caps_its_statements_then_runs_one_statement(name: str) -> None:
    """One unit of work per call: the transaction-local cap (STORE_TIMEOUT_S, in ms) first, one
    statement, and a commit for a write only."""
    kind, call, writes = CALLS[name]
    rel = _Rel()
    await call(_store(kind, rel))
    assert rel.events[0] == ("cap", {"timeout": "2000"})
    assert len(rel.events) == (3 if writes else 2) and (rel.events[-1] == "commit") is writes


@pytest.mark.parametrize("name", CALLS)
async def test_every_call_runs_under_the_client_deadline(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A call that cannot finish (a hung connection) ends at the client deadline as
    `StorageTierUnavailable`, with no SQLSTATE to give."""
    kind, call, _ = CALLS[name]
    seen: list[str] = []

    def deadline() -> asyncio.Timeout:
        seen.append(name)
        return asyncio.timeout(0.01)

    monkeypatch.setattr(repo, "_client_deadline", deadline)
    with pytest.raises(StorageTierUnavailable, match=r"\(sqlstate unknown\)$") as refused:
        await call(_store(kind, _Rel(hang=True)))
    assert seen == [name] and _P1 not in str(refused.value)


async def test_the_client_deadline_is_one_second_after_the_statement_cap() -> None:
    loop = asyncio.get_running_loop()
    async with repo._client_deadline() as deadline:
        left = (deadline.when() or 0.0) - loop.time()
    assert repo.STORE_TIMEOUT_S + 1 - 0.05 < left <= repo.STORE_TIMEOUT_S + 1


class _Orig(Exception):
    """A driver error: `sqlstate`, and a message that echoes a P1 value."""

    def __init__(self, sqlstate: str | None) -> None:
        super().__init__(f"value {_P1} rejected")
        self.sqlstate = sqlstate


def _dbapi(sqlstate: str | None, *, invalidated: bool = False) -> sa_exc.DBAPIError:
    return sa_exc.DBAPIError(
        f"INSERT ... {_P1}", {"p": _P1}, _Orig(sqlstate), connection_invalidated=invalidated
    )


@pytest.mark.parametrize(
    ("error", "kind", "sqlstate"),
    [
        (OSError(f"connect to {_P1} refused"), StorageTierUnavailable, "unknown"),
        (sa_exc.TimeoutError(f"pool {_P1}"), StorageTierUnavailable, "unknown"),
        (_dbapi("08006"), StorageTierUnavailable, "08006"),
        (_dbapi("57014"), StorageTierUnavailable, "57014"),
        (_dbapi("57P01"), StorageTierUnavailable, "57P01"),
        (_dbapi(None), StorageTierUnavailable, "unknown"),
        (_dbapi("23505", invalidated=True), StorageTierUnavailable, "23505"),
        (_dbapi("23514"), StorageQueryFailed, "23514"),
        (_dbapi("42501"), StorageQueryFailed, "42501"),
        (_dbapi("22P02"), StorageQueryFailed, "22P02"),
    ],
    ids=[
        "oserror", "pool", "08006", "57014-statement-timeout", "57P01", "no-sqlstate",
        "invalidated", "23514", "42501", "22P02",
    ],
)  # fmt: skip
@pytest.mark.parametrize("name", CALLS)
async def test_a_failure_carries_the_sqlstate_only_never_chained(
    name: str, error: BaseException, kind: type[StorageError], sqlstate: str
) -> None:
    store, call, _ = CALLS[name]
    with pytest.raises(kind) as refused:
        await call(_store(store, _Rel(error=error)))
    text = str(refused.value)
    assert text.endswith(f"(sqlstate {sqlstate})") and _P1 not in text
    assert "INSERT" not in text and "SELECT" not in text
    assert refused.value.__cause__ is None and refused.value.__context__ is None


@pytest.mark.parametrize(
    ("error", "outage"), [(_dbapi("23514"), False), (_dbapi("08006"), True)], ids=["bug", "outage"]
)
async def test_a_failure_logs_the_call_the_outage_the_error_type_and_the_sqlstate_only(
    error: BaseException, outage: bool
) -> None:
    """The ticket's security notes: the stores log ids and outcomes only (C-12.6)."""
    with capture_logs() as logs, pytest.raises(StorageError):
        await _store("journal", _Rel(error=error)).append("order", ENTITY, "demo", [JOURNAL])
    state = error.orig.sqlstate  # type: ignore[attr-defined]  # _Orig carries it
    assert logs == [
        {"event": "statechart_store_failed", "log_level": "error", "op": "journal.append",
         "outage": outage, "error": "DBAPIError", "sqlstate": state}
    ]  # fmt: skip
    assert _P1 not in repr(logs)


async def test_cancellation_passes_through_unchanged() -> None:
    task = asyncio.ensure_future(_store("events", _Rel(hang=True)).head("order", ENTITY, "demo"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_the_snapshot_upsert_binds_every_value_and_updates_on_the_machine_key() -> None:
    """A later persist of the same machine replaces every column but the key."""
    stmt = repo.upsert_snapshot_statement(SNAP)
    sql, params = _sql(stmt), _params(stmt)
    assert "ON CONFLICT (machine_kind, entity_id, env) DO UPDATE SET" in sql
    updated = [c.name for c in repo.SNAPSHOT_COLUMNS[3:]]
    assert sql.endswith(", ".join(f"{name} = excluded.{name}" for name in updated))
    assert _P1 not in sql and ENTITY not in sql and "k1" not in sql
    assert ENTITY in params.values() and bytes(32) in params.values()
    assert ["order.idle"] in params.values() and {"n": _P1} in params.values()


def test_the_journal_append_does_nothing_on_a_known_send_id_and_returns_what_it_inserted() -> None:
    sql = _sql(repo.append_journal_statement())
    assert sql.startswith("INSERT INTO machine_drain_journal")
    assert sql.endswith(
        "ON CONFLICT (machine_kind, entity_id, env, send_id) DO NOTHING"
        " RETURNING machine_drain_journal.send_id"
    )


def test_a_skipped_row_is_read_for_its_stamp_and_its_payload_text_against_this_record() -> None:
    """The entry's payload binds through the column's own JSON type, as the insert binds it, so
    the two texts are equal exactly when this append would have written the stored text."""
    stmt = repo.journal_conflict_statement("order", ENTITY, "demo", JOURNAL)
    sql, params = _sql(stmt), _params(stmt)
    assert sql.startswith("SELECT machine_drain_journal.replayed_at IS NOT NULL AS stamped, ")
    assert (
        "CAST(machine_drain_journal.payload AS TEXT) = CAST($1::JSON AS TEXT) AS same_payload"
        in sql
    )
    assert ".send_id = $" in sql and _P1 not in sql
    assert JOURNAL.payload in params.values() and JOURNAL.send_id in params.values()


async def test_the_append_reports_each_skipped_send_id_and_commits() -> None:
    """One unit of work: the insert, then one read per `send_id` it skipped, then the commit; a
    skipped row the read cannot see is reported as neither stamped nor the same payload."""
    second = repo.JournalRecord(
        send_id="d" * 32, lane="inbox", ordinal=1, event_type="PING", payload={"n": 2}
    )
    third = repo.JournalRecord(
        send_id="e" * 32, lane="inbox", ordinal=2, event_type="PING", payload={"n": 3}
    )

    def answer(stmt: Any, params: Any) -> list[dict[str, Any]]:
        if isinstance(stmt, sa.Insert):
            return [{"send_id": "b" * 32}]
        named = _params(stmt)
        if "d" * 32 in named.values():
            return [{"stamped": True, "same_payload": False}]
        return []

    rel = _Rel(answer=answer)
    conflicts = await _store("journal", rel).append(
        "order", ENTITY, "demo", [JOURNAL, second, third]
    )
    assert conflicts == (
        repo.JournalConflictRecord("d" * 32, stamped=True, same_payload=False),
        repo.JournalConflictRecord("e" * 32, stamped=False, same_payload=False),
    )
    assert rel.events[0][0] == "cap" and rel.events[-1] == "commit" and len(rel.events) == 5


async def test_an_append_that_inserts_every_row_reports_no_conflict() -> None:
    rel = _Rel()
    assert await _store("journal", rel).append("order", ENTITY, "demo", [JOURNAL]) == ()
    assert len(rel.events) == 3


def test_presence_is_read_by_send_id_on_the_machine_key() -> None:
    stmt = repo.present_statement("order", ENTITY, "demo", ["b" * 32])
    sql = _sql(stmt)
    assert sql.startswith("SELECT machine_drain_journal.send_id FROM machine_drain_journal")
    assert "machine_drain_journal.send_id IN (__[POSTCOMPILE_send_id_1])" in sql


async def test_presence_returns_the_send_ids_that_have_a_row() -> None:
    rel = _Rel(answer=lambda stmt, params: [{"send_id": "b" * 32}])
    present = await _store("journal", rel).present("order", ENTITY, "demo", ["b" * 32, "f" * 32])
    assert present == frozenset({"b" * 32})
    empty = _Rel()
    assert await _store("journal", empty).present("order", ENTITY, "demo", []) == frozenset()
    assert empty.events == []


def test_the_event_insert_does_nothing_on_a_known_row_hash() -> None:
    sql = _sql(repo.insert_events_statement())
    assert sql.startswith("INSERT INTO machine_events")
    assert sql.endswith("ON CONFLICT (row_hash) DO NOTHING")


async def test_the_batch_writes_bind_each_row_in_the_order_given() -> None:
    rel = _Rel()
    second = repo.JournalRecord(
        send_id="d" * 32, lane="inbox", ordinal=1, event_type="PING", payload={}
    )
    await _store("journal", rel).append("order", ENTITY, "demo", [JOURNAL, second])
    rows = rel.events[1][1]
    assert [(r["send_id"], r["ordinal"], r["machine_kind"]) for r in rows] == [
        ("b" * 32, 0, "order"),
        ("d" * 32, 1, "order"),
    ]
    rel = _Rel()
    later = repo.EventRecord(**{**_fields(EVENT), "row_hash": "e" * 64, "prev_hash": "c" * 64})
    await _store("events", rel).insert_batch([EVENT, later])
    rows = rel.events[1][1]
    assert [r["row_hash"] for r in rows] == ["c" * 64, "e" * 64]
    assert rows[0]["from_states"] == ["a"] and "seq" not in rows[0]


async def test_no_fault_binds_none_which_the_column_stores_as_sql_null() -> None:
    """`machine_events.fault` is `JSON(none_as_null=True)` (#3857): `None` binds SQL NULL, as the
    `me_fault_phase` CHECK wants, and a fault row binds its dict, in one batch."""
    fault_type = machine_events.c.fault.type
    assert isinstance(fault_type, sa.JSON) and fault_type.none_as_null is True
    rel = _Rel()
    fault = repo.EventRecord(
        **{**_fields(EVENT), "phase": "fault", "fault": {"failed": ["x"]}, "row_hash": "f" * 64}
    )
    await _store("events", rel).insert_batch([EVENT, fault])
    rows = rel.events[1][1]
    assert [r["fault"] for r in rows] == [None, {"failed": ["x"]}]


def _fields(record: Any) -> dict[str, Any]:
    return {name: getattr(record, name) for name in record.__dataclass_fields__}


@pytest.mark.parametrize(
    ("kind", "call"),
    [
        ("journal", lambda s: s.append("order", ENTITY, "demo", [])),
        ("journal", lambda s: s.mark_replayed("order", ENTITY, "demo", [])),
        ("events", lambda s: s.insert_batch([])),
    ],
    ids=["append", "mark_replayed", "insert_batch"],
)
async def test_an_empty_write_opens_no_unit_of_work(kind: str, call: _Call) -> None:
    rel = _Rel()
    await call(_store(kind, rel))
    assert rel.events == []


def test_the_reads_and_the_stamp_filter_on_the_machine_key_and_bind_it() -> None:
    for stmt in (
        repo.get_snapshot_statement("order", ENTITY, "demo"),
        repo.list_unreplayed_statement("order", ENTITY, "demo"),
        repo.present_statement("order", ENTITY, "demo", ["b" * 32]),
        repo.journal_conflict_statement("order", ENTITY, "demo", JOURNAL),
        repo.mark_replayed_statement("order", ENTITY, "demo", ["b" * 32]),
        repo.head_statement("order", ENTITY, "demo"),
        repo.read_chain_statement("order", ENTITY, "demo", 0),
    ):
        sql, params = _sql(stmt), _params(stmt)
        bound = {value for value in params.values() if isinstance(value, str)}
        assert ENTITY not in sql and {"order", ENTITY, "demo"} <= bound
        for column in ("machine_kind", "entity_id", "env"):
            assert f".{column} = $" in sql


def test_the_unreplayed_rows_come_in_replay_order_bounded_like_the_snapshot_list() -> None:
    stmt = repo.list_unreplayed_statement("order", ENTITY, "demo")
    sql = _sql(stmt)
    assert "machine_drain_journal.replayed_at IS NULL" in sql
    assert "ORDER BY machine_drain_journal.ordinal LIMIT $" in sql
    assert repo.LIST_MAX_ROWS + 1 in _params(stmt).values()


def _journal_rows(n: int) -> list[dict[str, Any]]:
    return [{**_fields(JOURNAL), "send_id": f"{i:032x}", "ordinal": i} for i in range(n)]


async def test_the_unreplayed_rows_come_up_to_the_cap_and_are_refused_beyond_it() -> None:
    """SR2-E50T62-01: a key flooded with rows is refused, not truncated and not held whole."""
    full = _Rel(answer=lambda stmt, params: _journal_rows(repo.LIST_MAX_ROWS))
    rows = await _store("journal", full).list_unreplayed("order", ENTITY, "demo")
    assert len(rows) == repo.LIST_MAX_ROWS and rows[-1].ordinal == repo.LIST_MAX_ROWS - 1
    over = _Rel(answer=lambda stmt, params: _journal_rows(repo.LIST_MAX_ROWS + 1))
    with pytest.raises(JournalListTooLargeError, match="not truncated") as refused:
        await _store("journal", over).list_unreplayed("order", ENTITY, "demo")
    assert ENTITY not in str(refused.value) and _P1 not in str(refused.value)


def test_the_stamp_is_set_once_on_the_named_rows() -> None:
    stmt = repo.mark_replayed_statement("order", ENTITY, "demo", ["b" * 32])
    sql = _sql(stmt)
    assert sql.startswith("UPDATE machine_drain_journal SET replayed_at=now()")
    assert "machine_drain_journal.send_id IN (__[POSTCOMPILE_send_id_1])" in sql
    assert sql.endswith("AND machine_drain_journal.replayed_at IS NULL")


def test_the_chain_reads_are_keyset_pages_in_seq_order() -> None:
    sql = _sql(repo.read_chain_statement("order", ENTITY, "demo", 41))
    assert "machine_events.seq > $" in sql and "ORDER BY machine_events.seq LIMIT" in sql
    assert 41 in _params(repo.read_chain_statement("order", ENTITY, "demo", 41)).values()
    assert repo.CHAIN_PAGE_ROWS in _params(repo.read_chain_statement("o", "e", "demo", 0)).values()
    head = _sql(repo.head_statement("order", ENTITY, "demo"))
    assert (
        head.startswith("SELECT machine_events.row_hash")
        and "ORDER BY machine_events.seq DESC LIMIT $" in head
    )
    assert 1 in _params(repo.head_statement("order", ENTITY, "demo")).values()


async def test_the_head_of_an_empty_chain_is_the_genesis_hash() -> None:
    assert await _store("events", _Rel()).head("order", ENTITY, "demo") == "0" * 64
    rel = _Rel(answer=lambda stmt, params: [{"row_hash": "f" * 64}])
    assert await _store("events", rel).head("order", ENTITY, "demo") == "f" * 64


def _snapshot_rows(n: int) -> list[dict[str, Any]]:
    return [{**_fields(SNAP), "entity_id": f"e{i}", "state_ids": ["order.idle"]} for i in range(n)]


async def test_the_list_returns_up_to_the_cap_and_refuses_beyond_it() -> None:
    assert repo.LIST_MAX_ROWS + 1 in _params(repo.list_snapshots_statement()).values()
    sql = _sql(repo.list_snapshots_statement())  # CR-E50T62R2-06: a stable order for E42-T07
    assert sql.endswith(
        "ORDER BY machine_snapshots.machine_kind, machine_snapshots.entity_id,"
        " machine_snapshots.env LIMIT $1::INTEGER"
    )
    full = _Rel(answer=lambda stmt, params: _snapshot_rows(repo.LIST_MAX_ROWS))
    rows = await _store("snapshots", full).list_all()
    assert len(rows) == repo.LIST_MAX_ROWS and rows[0].state_ids == ("order.idle",)
    over = _Rel(answer=lambda stmt, params: _snapshot_rows(repo.LIST_MAX_ROWS + 1))
    with pytest.raises(SnapshotListTooLargeError, match="not truncated"):
        await _store("snapshots", over).list_all()


def _chain(total: int) -> Callable[[Any, Any], list[dict[str, Any]]]:
    """Answers `read_chain` pages from a chain of `total` rows (seq 1..total)."""

    def answer(stmt: Any, params: Any) -> list[dict[str, Any]]:
        after = next(v for k, v in _params(stmt).items() if k.startswith("seq_"))
        last = min(after + repo.CHAIN_PAGE_ROWS, total)
        return [{**_fields(EVENT), "seq": seq, "from_states": ["a"], "to_states": ["b"],
                 "actions_run": []} for seq in range(after + 1, last + 1)]  # fmt: skip

    return answer


async def test_the_whole_chain_is_read_page_by_page_up_to_the_cap() -> None:
    rel = _Rel(answer=_chain(repo.CHAIN_PAGE_ROWS * 2 + 1))
    chain = await _store("events", rel).read_whole_chain("order", ENTITY, "demo")
    assert [r.seq for r in chain] == list(range(1, repo.CHAIN_PAGE_ROWS * 2 + 2))
    assert len([e for e in rel.events if e != "commit" and e[0] != "cap"]) == 3
    exact = _Rel(answer=_chain(repo.CHAIN_MAX_ROWS))
    whole = await _store("events", exact).read_whole_chain("o", "e", "demo")
    assert len(whole) == repo.CHAIN_MAX_ROWS
    over = _Rel(answer=_chain(repo.CHAIN_MAX_ROWS + 1))
    with pytest.raises(ChainTooLongError, match="not truncated"):
        await _store("events", over).read_whole_chain("o", "e", "demo")


async def test_a_negative_page_position_is_refused_before_any_statement() -> None:
    rel = _Rel()
    with pytest.raises(ValueError, match="after_seq"):
        await _store("events", rel).read_chain("order", ENTITY, "demo", after_seq=-1)
    assert rel.events == []
