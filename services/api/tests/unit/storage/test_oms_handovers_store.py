"""The hand-over store without a database (E29-T06 #914 PR 1; 21 Sec.3.3.12): the entry's refusals
before any statement, every statement scoped to its account, and the store's append, reads,
decision and prune against a recording fake unit of work. Real SQL: the revision suite
(`tests/unit/migrations/test_oms_handovers_revision.py`) and the `migrations` CI job."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.engine import Dialect, make_url
from sqlalchemy.sql.elements import TextClause

from candleviewer.db import models
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories import oms_handovers_sqlalchemy as mod
from candleviewer.storage.repositories.oms_handovers import (
    HANDOVER_KINDS,
    HANDOVER_SOURCES,
    MAX_HANDOVERS_PER_ACCOUNT,
    HandoverRow,
    HandoverStoreFull,
    NewHandover,
)

_ASYNCPG: Dialect = make_url("postgresql+asyncpg://").get_dialect()()
_T = datetime(2026, 10, 30, 9, tzinfo=UTC)
_ACCOUNT, _OTHER = uuid.UUID(int=0x4001), uuid.UUID(int=0x4002)


def _sql(stmt: Any) -> str:
    text = str(stmt.compile(dialect=_ASYNCPG, compile_kwargs={"render_postcompile": True}))
    return " ".join(text.split())


def _order(**over: Any) -> NewHandover:
    record = {"account_id": str(_ACCOUNT), "exchange_order_id": "x9", "symbol": "BTCUSDT"}
    values: dict[str, Any] = {
        "exchange_account_id": _ACCOUNT, "kind": "order", "exchange_order_id": "x9",
        "source": "rest", "record": record,
    }  # fmt: skip
    return NewHandover(**(values | over))


_FILL_RECORD: dict[str, str] = {
    "account_id": str(_ACCOUNT), "exchange_order_id": "x9", "exec_id": "e1",
}  # fmt: skip


def _fill(**over: Any) -> NewHandover:
    record = dict(_FILL_RECORD)
    values: dict[str, Any] = {
        "exchange_account_id": _ACCOUNT, "kind": "execution", "exchange_order_id": "x9",
        "exec_id": "e1", "source": "ws_private", "record": record,
    }  # fmt: skip
    return NewHandover(**(values | over))


def test_the_vocabularies_are_the_tables() -> None:
    assert HANDOVER_KINDS == frozenset({"order", "execution"})
    assert HANDOVER_SOURCES == frozenset({"ws_private", "rest", "reconcile"})
    assert MAX_HANDOVERS_PER_ACCOUNT == 1_000


@pytest.mark.parametrize(
    ("make", "over", "rule"),
    [
        (_order, {"kind": "position"}, "kind"),
        (_order, {"source": "local"}, "source"),
        (_order, {"exec_id": "e1"}, "exec_id"),
        (_fill, {"exec_id": None}, "exec_id"),
        (_order, {"exchange_order_id": ""}, "exchange_order_id"),
        (_order, {"exchange_order_id": "x" * 65}, "exchange_order_id"),
        (_order, {"exchange_order_id": "x\x00"}, "exchange_order_id"),
        (_fill, {"exec_id": "e\n1"}, "exec_id"),
        (_order, {"record": {"account_id": str(_OTHER), "exchange_order_id": "x9"}}, "record"),
        (_order, {"record": {"account_id": str(_ACCOUNT), "exchange_order_id": "x8"}}, "record"),
        (_fill, {"record": _FILL_RECORD | {"exec_id": "e2"}}, "record"),
        (_order, {"record": ["not", "an", "object"]}, "record"),
        (_order, {"payload": ["not", "an", "object"]}, "payload"),
        (_order, {"empty_read": True}, "empty_read"),
    ],
)  # fmt: skip
def test_an_entry_the_table_would_refuse_is_refused_before_any_statement(
    make: Any, over: dict[str, Any], rule: str
) -> None:
    """`oh_kind`, `oh_source`, `oh_exec`, `oh_ids` and `oh_record` (C-2.11, SR-E29-03), checked
    on the entry, so a refusal costs no round trip and names no value."""
    with pytest.raises(ValueError, match=rule) as refused:
        make(**over)
    assert "BTCUSDT" not in str(refused.value)


def test_an_entry_is_frozen_and_its_record_and_payload_are_copied() -> None:
    record = {"account_id": str(_ACCOUNT), "exchange_order_id": "x9"}
    entry = _order(record=record, payload={"retCode": 0})
    record["exchange_order_id"] = "x8"  # the caller's dict changes; the entry's does not
    assert entry.record["exchange_order_id"] == "x9" and entry.payload == {"retCode": 0}
    with pytest.raises(FrozenInstanceError):
        entry.kind = "execution"  # type: ignore[misc]  # the assignment under test


def test_the_row_is_every_column_in_table_order() -> None:
    assert [f.name for f in fields(HandoverRow)] == [c.name for c in models.oms_handovers.columns]


def test_every_statement_but_the_insert_names_the_account() -> None:
    """C-12.4: a hand-over is read, decided or pruned only for the account the caller names."""
    statements = {
        "held_statement": mod.held_statement(_order()),
        "count_read_statement": mod.count_read_statement(_fill()),
        "size_statement": mod.size_statement(_ACCOUNT),
        "pending_statement": mod.pending_statement(_ACCOUNT, "execution"),
        "decide_statement": mod.decide_statement(_ACCOUNT, "e1"),
        "prune_statement": mod.prune_statement(_ACCOUNT, [3, 1]),
    }
    assert mod.UNSCOPED == frozenset({"insert_statement"})
    for name, stmt in statements.items():
        assert "oms_handovers.exchange_account_id = $" in _sql(stmt), name


def test_the_lock_is_the_accounts_own() -> None:
    assert isinstance(mod.LOCK, TextClause)
    assert "pg_advisory_xact_lock(hashtextextended('cv.oms_handovers:'" in str(mod.LOCK)


def test_an_empty_read_counts_one_more_and_stamps_only_the_first() -> None:
    sql = _sql(mod.count_read_statement(_fill(empty_read=True)))
    assert sql.startswith("UPDATE oms_handovers SET empty_reads=(oms_handovers.empty_reads + $")
    assert "first_empty_read_at=coalesce(oms_handovers.first_empty_read_at, now())" in sql
    assert "oms_handovers.kind = $" in sql and "oms_handovers.exec_id = $" in sql
    assert sql.endswith("RETURNING oms_handovers.id")


def test_the_insert_is_idempotent_and_counts_a_first_empty_read() -> None:
    plain, empty = (
        _sql(mod.insert_statement(_fill())),
        _sql(mod.insert_statement(_fill(empty_read=True))),
    )
    for sql in (plain, empty):
        assert "ON CONFLICT DO NOTHING RETURNING oms_handovers.id" in sql
    params = mod.insert_statement(_fill(empty_read=True)).compile(dialect=_ASYNCPG).params
    assert params["empty_reads"] == 1 and "now()" in empty
    assert mod.insert_statement(_fill()).compile(dialect=_ASYNCPG).params["empty_reads"] == 0


def test_the_pass_reads_one_kind_in_append_order_at_most_the_bound() -> None:
    sql = _sql(mod.pending_statement(_ACCOUNT, "order"))
    assert sql.endswith("ORDER BY oms_handovers.id LIMIT $3::INTEGER")
    params = mod.pending_statement(_ACCOUNT, "order").compile(dialect=_ASYNCPG).params
    assert params["param_1"] == MAX_HANDOVERS_PER_ACCOUNT


def test_a_decision_is_stamped_once_on_an_execution() -> None:
    sql = _sql(mod.decide_statement(_ACCOUNT, "e1"))
    assert "SET decided_at=now()" in sql and "oms_handovers.decided_at IS NULL" in sql


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        (row,) = self._rows
        return next(iter(row.values()))

    def mappings(self) -> _Result:
        return self

    def all(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _Rel:
    """A recording relational repository: each non-text statement takes the script's next rows
    (or raises its error); the statement cap and the lock are recorded by kind."""

    def __init__(self, *script: list[dict[str, Any]] | BaseException) -> None:
        self.script = list(script)
        self.log: list[str] = []
        self.locks: list[dict[str, Any]] = []
        self.commits = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        rel = self

        class _Session:
            async def execute(self, stmt: Any, params: Any = None) -> Any:
                if stmt is mod.LOCK:
                    rel.log.append("lock")
                    rel.locks.append(dict(params))
                    return _Result([])
                if isinstance(stmt, TextClause):  # the statement cap
                    return _Result([])
                rel.log.append(type(stmt).__name__.lower())
                item = rel.script.pop(0)
                if isinstance(item, BaseException):
                    raise item
                return _Result(item)

        class _Uow:
            session = _Session()

            async def commit(self) -> None:
                rel.log.append("commit")
                rel.commits += 1

        yield _Uow()


def _store(rel: _Rel) -> mod.SqlAlchemyHandoverStore:
    return mod.SqlAlchemyHandoverStore(cast(Any, rel))  # structural fake


async def test_a_new_entry_is_added_under_the_accounts_lock_below_the_bound() -> None:
    rel = _Rel([], [{"n": 3}], [{"id": 7}])
    assert await _store(rel).append(_order()) == "added"
    assert rel.log == ["lock", "select", "select", "insert", "commit"]
    assert rel.locks == [{"account": str(_ACCOUNT)}]


async def test_an_entry_already_held_is_left_as_it_was_even_at_the_bound() -> None:
    """Idempotent on (account, orderId) and (account, exec_id): a repeat adds nothing, so the
    bound never refuses it."""
    rel = _Rel([{"id": 7}])
    assert await _store(rel).append(_order()) == "held"
    assert rel.log == ["lock", "select"] and rel.commits == 0


async def test_an_empty_read_is_counted_on_the_entry_held() -> None:
    rel = _Rel([{"id": 7}])
    assert await _store(rel).append(_fill(empty_read=True)) == "counted"
    assert rel.log == ["lock", "update", "commit"]


async def test_a_first_empty_read_adds_the_entry_with_its_count() -> None:
    rel = _Rel([], [{"n": 0}], [{"id": 8}])
    assert await _store(rel).append(_fill(empty_read=True)) == "added"
    assert rel.log == ["lock", "update", "select", "insert", "commit"]


async def test_an_append_past_the_bound_is_refused_with_nothing_written() -> None:
    """21 Sec.3.3.12's overflow policy: refused, never dropped silently, and nothing committed."""
    rel = _Rel([], [{"n": MAX_HANDOVERS_PER_ACCOUNT}])
    with pytest.raises(HandoverStoreFull) as full:
        await _store(rel).append(_order())
    assert str(_ACCOUNT) not in str(full.value)
    assert rel.log == ["lock", "select", "select"] and rel.commits == 0


async def test_an_outage_leaves_the_store_as_storage_tier_unavailable() -> None:
    rel = _Rel(OSError("connection reset"))
    with pytest.raises(StorageTierUnavailable):
        await _store(rel).append(_order())


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": 7, "exchange_account_id": _ACCOUNT, "kind": "execution", "exchange_order_id": "x9",
        "exec_id": "e1", "source": "ws_private",
        "record": {"account_id": str(_ACCOUNT), "exchange_order_id": "x9", "exec_id": "e1"},
        "payload": {}, "empty_reads": 1, "first_empty_read_at": _T, "decided_at": None,
        "created_at": _T,
    }  # fmt: skip
    return row | over


async def test_the_pass_reads_its_accounts_entries_as_rows() -> None:
    rel = _Rel([_row(), _row(id=9, exec_id="e2")])
    rows = await _store(rel).pending(_ACCOUNT, "execution")
    assert [(r.id, r.exec_id, r.empty_reads) for r in rows] == [(7, "e1", 1), (9, "e2", 1)]
    assert rows[0].first_empty_read_at == _T and rows[0].decided_at is None
    assert rel.commits == 0


async def test_a_decision_and_a_prune_answer_what_they_changed() -> None:
    rel = _Rel([{"id": 7}], [], [{"id": 7}, {"id": 9}])
    store = _store(rel)
    assert await store.decide(_ACCOUNT, "e1") is True
    assert await store.decide(_ACCOUNT, "e1") is False  # decided already: stamped once
    assert await store.prune(_ACCOUNT, [9, 7, 9]) == 2
    assert await store.prune(_ACCOUNT, []) == 0  # nothing to prune: no statement
    assert rel.log == ["update", "commit", "update", "delete", "commit"]
