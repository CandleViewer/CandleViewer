"""Unit tests for the recorded stops' port and Postgres adapter (E29-T04 #913): the dataclass
refusals, the account scope of every statement, the settle compare-and-set, and the store against
a recording fake unit of work. Real SQL: tests/integration/storage/test_order_submission_pg.py
and the 0043 migration suite (CI only)."""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.engine import Dialect, make_url
from sqlalchemy.sql.elements import TextClause

from candleviewer.db import models
from candleviewer.oms.order_machine import Legality
from candleviewer.statechart.registry import Registry
from candleviewer.storage.errors import StorageTierUnavailable, WriteAheadTimeout
from candleviewer.storage.repositories import recorded_stops_sqlalchemy as mod
from candleviewer.storage.repositories.recorded_stops import (
    EVERY_ACCOUNT,
    LIVE_STOP_STATUSES,
    REFUSED_BY,
    REFUSED_ENTRY,
    SWEEP_REASON,
    UNSENT_ENTRY,
    WAITING_ENTRY,
    FillPosition,
    NewRecordedStop,
    RecordedStopNotBindable,
    RecordedStopRow,
    StaleRecordedStop,
    SweptStop,
    check_request,
    request_cutoff,
)

_ASYNCPG: Dialect = make_url("postgresql+asyncpg://").get_dialect()()
_T = datetime(2026, 10, 21, 9, tzinfo=UTC)
_ACCOUNT, _ORDER, _USER = (uuid.UUID(int=n) for n in (0x4001, 0x5001, 0x1001))
_SL, _TP = uuid.UUID(int=0x6002), uuid.UUID(int=0x6001)  # TP sorts first


def _sql(stmt: Any) -> str:
    text = str(stmt.compile(dialect=_ASYNCPG, compile_kwargs={"render_postcompile": True}))
    return " ".join(text.split())


def _stop(**over: Any) -> NewRecordedStop:
    values: dict[str, Any] = {
        "id": _SL, "exchange_account_id": _ACCOUNT, "symbol": "BTCUSDT", "position_idx": 0,
        "position_side": "Buy", "kind": "stop_loss", "source": "entry_attach",
        "order_id": _ORDER, "tpsl_mode": "Full", "trigger_price": Decimal("62000"),
        "size": None, "audit_record_id": uuid.UUID(int=0x7001), "actor_user_id": _USER,
    }  # fmt: skip
    return NewRecordedStop(**(values | over))


@pytest.mark.parametrize(
    ("over", "rule"),
    [
        ({"trigger_price": Decimal(0)}, "rs_px"),
        ({"trigger_price": Decimal("NaN")}, "finite"),
        ({"trigger_price": 62000.0}, "Decimal"),
        ({"trigger_price": Decimal("1E-19")}, "numeric"),
        ({"trigger_price": Decimal(10) ** 20}, "numeric"),  # 21 integral digits: numeric(38,18)
        ({"size": Decimal("0.010")}, "rs_size"),
        ({"tpsl_mode": "Partial"}, "rs_size"),
        ({"tpsl_mode": "Partial", "size": Decimal(0)}, "rs_size"),
        ({"trailing_distance": Decimal(50)}, "rs_trail"),
        ({"trailing_distance": Decimal(0), "trailing_active_price": Decimal(1)}, "rs_trail"),
        ({"trailing_distance": Decimal(50), "trailing_active_price": Decimal(0)}, "rs_trail"),
        ({"kind": "take_profit", "trailing_distance": Decimal(5),
          "trailing_active_price": Decimal(1)}, "rs_trail"),
        ({"order_id": None}, "rs_entry"),
        ({"source": "trading_stop"}, "rs_entry"),
        ({"source": "restore", "order_id": None, "kind": "take_profit"}, "rs_restore"),
        ({"position_marker": ""}, "rs_marker"),
        ({"position_marker": "m" * 65}, "rs_marker"),
    ],
)  # fmt: skip
def test_a_stop_the_table_would_refuse_is_refused_before_any_statement(
    over: dict[str, Any], rule: str
) -> None:
    with pytest.raises((ValueError, TypeError), match=rule) as exc:
        _stop(**over)
    assert "62000" not in str(exc.value)  # a price is P1 (21 Sec.12)


def test_a_partial_side_a_trail_and_a_marker_the_table_admits_pass() -> None:
    _stop(tpsl_mode="Partial", size=Decimal("0.005"), position_marker="m" * 64)
    _stop(trailing_distance=Decimal(50), trailing_active_price=Decimal(63000))
    _stop(source="restore", order_id=None)
    _stop(trigger_price=Decimal("0.5"), position_marker="m")  # a sub-unit price; one character
    _stop(trailing_distance=Decimal("0.5"), trailing_active_price=Decimal("0.8"))  # sub-unit trail


def test_a_requests_values_never_change() -> None:
    """21 Sec.3.3.11: the request's values are written once (`trg_rs_guard`); the row to insert is
    frozen as well, so nothing between its checks and its insert can change it."""
    stop = _stop()
    with pytest.raises(FrozenInstanceError):
        stop.trigger_price = Decimal(1)  # type: ignore[misc]  # the assignment under test


def test_the_row_is_every_column_in_table_order() -> None:
    assert [f.name for f in fields(RecordedStopRow)] == [
        c.name for c in models.recorded_stops.columns
    ]
    written = {f.name for f in fields(NewRecordedStop)}
    left = [c.name for c in models.recorded_stops.columns if c.name not in written]
    assert left == ["exchange_order_id", "status", "created_at", "answered_at", "in_force_at",
                    "closed_at", "released_at"]  # fmt: skip


def _built() -> dict[str, Any]:
    return {
        "insert_stops_statement": mod.insert_stops_statement([_stop()]),
        "lock_stops_statement": mod.lock_stops_statement(_ACCOUNT, [_SL, _TP]),
        "settle_statement": mod.settle_statement(_ACCOUNT, [_SL, _TP], "answered", _T),
        "for_order_statement": mod.for_order_statement(_ACCOUNT, _ORDER),
        "live_for_key_statement": mod.live_for_key_statement(_ACCOUNT, "BTCUSDT", 0),
        "for_exchange_order_statement": mod.for_exchange_order_statement(_ACCOUNT, "x-1"),
        "release_statement": mod.release_statement(_ACCOUNT, _SL, "x-1", _T),
        "bind_statement": mod.bind_statement(_ACCOUNT, _TP, "x-1", mod.stop_row(_row(_SL))),
        "void_orphans_statement": mod.void_orphans_statement(EVERY_ACCOUNT, _T),
        "waiting_for_key_statement": mod.waiting_for_key_statement(
            _ACCOUNT, "BTCUSDT", 0, now=_T, bound_s=5.0
        ),
        "waiting_keys_statement": mod.waiting_keys_statement(_ACCOUNT, now=_T, bound_s=5.0),
        "clock_statement": mod.clock_statement(),
        "lock_key_statement": mod.lock_key_statement(_ACCOUNT, "BTCUSDT", 0),
        "replace_statement": mod.replace_statement(_ACCOUNT, [_SL], _T),
        "in_force_statement": mod.in_force_statement(_ACCOUNT, _rows(_row(_SL)), _T),
        "in_force_for_key_statement": mod.in_force_for_key_statement(_ACCOUNT, "BTCUSDT", 0),
        "resolve_statement": mod.resolve_statement(_ACCOUNT, _rows(_row(_SL)), "answered", _T),
    }


def test_every_statement_but_the_insert_and_the_system_sweep_filters_the_account() -> None:
    """C-12.4 (SEC-2A-02): the sweep is built over every account here, its system form, so the
    pin sees the one unscoped read-and-write the startup wiring alone may run, beside the clock
    the startup reads, which reads no table."""
    built = _built()
    assert set(built) == {name for name in vars(mod) if name.endswith("_statement")}
    unscoped = {
        n for n, s in built.items() if "recorded_stops.exchange_account_id = " not in _sql(s)
    }
    assert unscoped == mod.UNSCOPED | mod.SYSTEM_STATEMENTS
    assert not mod.UNSCOPED & mod.SYSTEM_STATEMENTS
    assert mod.UNSCOPED == frozenset({"insert_stops_statement"})
    assert mod.SYSTEM_STATEMENTS == frozenset({"void_orphans_statement", "clock_statement"})


def test_the_clock_statement_reads_no_table() -> None:
    """S3-H's startup floor (Q7): a system statement, as it reads no row of any account."""
    assert _sql(mod.clock_statement()) == "SELECT now() AS now_1"
    assert not mod.clock_statement().get_final_froms()


def test_live_stop_statuses_are_the_ix_rs_live_predicate() -> None:
    index = next(i for i in models.recorded_stops.indexes if i.name == "ix_rs_live")
    predicate = str(index.dialect_options["postgresql"]["where"])
    assert set(LIVE_STOP_STATUSES) == set(re.findall(r"'(\w+)'", predicate))


def test_live_for_key_statement_reads_one_keys_live_statuses_as_literals_oldest_first() -> None:
    """21 Sec.13.1 row 45: the key's rows in the account whose status is `ix_rs_live`'s predicate,
    written as literals so the planner matches it; no filter on the binding or the release."""
    sql = _sql(_built()["live_for_key_statement"])
    where = sql.split(" WHERE ", 1)[1]
    for column in ("exchange_account_id", "symbol", "position_idx"):
        assert f"recorded_stops.{column} = $" in where
    assert "recorded_stops.status IN ('in_force', 'pending')" in where
    assert "exchange_order_id" not in where and "released_at" not in where
    assert sql.endswith("ORDER BY recorded_stops.created_at, recorded_stops.id")


def test_for_exchange_order_statement_reads_the_accounts_rows_for_the_id_any_status() -> None:
    """21 Sec.13.1 row 46: `ix_rs_exch_id`'s two columns, the exact id (no `LIKE`, no folding), no
    status, oldest first."""
    sql = _sql(_built()["for_exchange_order_statement"])
    where = sql.split(" WHERE ", 1)[1]
    assert where.startswith(
        "recorded_stops.exchange_account_id = $1::UUID AND recorded_stops.exchange_order_id = $2::"
    )
    assert "status" not in where and "LIKE" not in where and "lower(" not in where
    assert sql.endswith("ORDER BY recorded_stops.created_at, recorded_stops.id")


def test_release_statement_clears_the_id_the_live_row_holds_and_stamps_the_release() -> None:
    """`rs_release` wants both together; `trg_rs_guard` admits the release in any status, so the
    status is the statement's: an end keeps its id."""
    sql = _sql(_built()["release_statement"])
    assert sql.startswith("UPDATE recorded_stops SET exchange_order_id=NULL, released_at=$1::")
    assert sql.split(" WHERE ", 1)[1].split(" RETURNING ", 1)[0] == (
        "recorded_stops.exchange_account_id = $2::UUID AND recorded_stops.id = $3::UUID AND "
        "recorded_stops.exchange_order_id = $4::VARCHAR AND recorded_stops.released_at IS NULL AND "
        "recorded_stops.status IN ('in_force', 'pending')"
    )


def test_bind_statement_binds_a_later_row_of_the_same_side_while_no_row_holds_the_id() -> None:
    """`trg_rs_guard` admits that one bind; the statement names every condition: a live row that
    holds none and was never released, of the released row's side, later by `(created_at, id)`,
    and no other holder of the id."""
    sql = _sql(_built()["bind_statement"])
    assert sql.startswith("UPDATE recorded_stops SET exchange_order_id=$1::VARCHAR WHERE ")
    assert sql.split(" WHERE ", 1)[1].split(" RETURNING ", 1)[0] == (
        "recorded_stops.exchange_account_id = $2::UUID AND recorded_stops.id = $3::UUID AND "
        "recorded_stops.exchange_order_id IS NULL AND recorded_stops.released_at IS NULL AND "
        "recorded_stops.status IN ('in_force', 'pending') AND "
        "recorded_stops.symbol = $4::VARCHAR AND recorded_stops.position_idx = $5::SMALLINT AND "
        "recorded_stops.kind = $6::VARCHAR AND (recorded_stops.created_at, recorded_stops.id) > "
        "($7::TIMESTAMP WITH TIME ZONE, $8::UUID) AND NOT (EXISTS (SELECT 1 FROM recorded_stops AS "
        "held WHERE held.exchange_account_id = $9::UUID AND held.exchange_order_id = $10::VARCHAR))"
    )


_OTHER = uuid.UUID(int=0x4002)


@pytest.mark.parametrize(
    ("batch", "rule"),
    [
        ([], "at least one row"),
        ([_stop(kind="take_profit")], "stop-loss side once"),
        ([_stop(), _stop(id=_TP)], "stop-loss side once"),
        ([_stop(), _stop(id=_TP, kind="take_profit"), _stop(id=_OTHER, kind="take_profit")],
         "stop-loss side once"),
        ([_stop(), _stop(id=_TP, kind="take_profit", exchange_account_id=_OTHER)], "one position"),
        ([_stop(), _stop(id=_TP, kind="take_profit", symbol="ETHUSDT")], "one position"),
        ([_stop(), _stop(id=_TP, kind="take_profit", position_idx=1)], "one position"),
        ([_stop(), _stop(id=_TP, kind="take_profit", position_side="Sell")], "one position"),
        ([_stop(), _stop(id=_TP, kind="take_profit", order_id=_OTHER)], "one source and one order"),
        ([_stop(source="trading_stop", order_id=None), _stop(id=_TP, kind="take_profit")],
         "one source and one order"),
    ],
)  # fmt: skip
async def test_an_insert_of_anything_but_one_requests_rows_is_refused_before_any_statement(
    batch: list[NewRecordedStop], rule: str
) -> None:
    """CR-2A-03 (21 Sec.3.3.11): `ux_rs_in_flight` keys on the stop-loss row alone, so a batch
    without one, or across positions, sources or orders, would pass it."""
    rel = _Rel()
    with pytest.raises(ValueError, match=rule) as err:
        await _store(rel).insert(batch)
    assert rel.statements == [] and rel.commits == 0 and "62000" not in str(err.value)


def test_each_request_the_writers_send_is_one_requests_rows() -> None:
    """An entry's attach (its stop-loss, and its take-profit), a trading-stop call (both sides)
    and a restore (the stop-loss alone)."""
    tp = _stop(id=_TP, kind="take_profit", trigger_price=Decimal(65000))
    check_request([_stop()])
    check_request([_stop(), tp])
    check_request([_stop(source="trading_stop", order_id=None),
                   replace(tp, source="trading_stop", order_id=None)])  # fmt: skip
    check_request([_stop(source="restore", order_id=None)])


@pytest.mark.parametrize("bound", [float("nan"), float("inf"), 0, -1.0, True])
def test_the_audit_bound_is_a_finite_number_of_seconds_above_zero(bound: Any) -> None:
    """CR-2A-07: a NaN or an infinity would leave a write-ahead hook unbounded."""
    with pytest.raises(ValueError, match="finite number of seconds above zero"):
        mod.SqlAlchemyRecordedStopStore(cast(Any, _Rel()), audit_timeout_s=bound)


def test_the_lock_takes_the_rows_for_update_in_id_order() -> None:
    sql = _sql(mod.lock_stops_statement(_ACCOUNT, [_SL, _TP, _SL]))
    assert sql.endswith("ORDER BY recorded_stops.id FOR UPDATE")
    params = mod.lock_stops_statement(_ACCOUNT, [_SL, _TP]).compile(dialect=_ASYNCPG).params
    assert list(params.values())[1] == [_TP, _SL]


@pytest.mark.parametrize(
    ("outcome", "sets"),
    [
        ("answered", "answered_at=$1::TIMESTAMP WITH TIME ZONE"),
        ("refused", "status=$1::VARCHAR, answered_at=$2::TIMESTAMP WITH TIME ZONE, "
                    "closed_at=$3::TIMESTAMP WITH TIME ZONE"),
        ("not_shown", "status=$1::VARCHAR, closed_at=$2::TIMESTAMP WITH TIME ZONE"),
    ],
)  # fmt: skip
def test_a_settle_answers_only_rows_in_flight(outcome: Any, sets: str) -> None:
    sql = _sql(mod.settle_statement(_ACCOUNT, [_SL], outcome, _T))
    assert sql.startswith("UPDATE recorded_stops SET ")
    assert sql.split(" SET ", 1)[1].split(" WHERE ", 1)[0] == sets
    assert "recorded_stops.status = $" in sql and "recorded_stops.answered_at IS NULL" in sql


class _Rel:
    def __init__(self, *script: list[dict[str, Any]] | BaseException) -> None:
        self.script = list(script)
        self.statements: list[Any] = []
        self.units = 0  # every unit of work entered, the statement cap's included
        self.commits = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        self.units += 1

        async def execute(stmt: Any, params: Any = None) -> Any:
            if isinstance(stmt, TextClause):
                return None
            self.statements.append(stmt)
            item = self.script.pop(0)
            if isinstance(item, BaseException):
                raise item
            return SimpleNamespace(mappings=lambda: list(item))

        async def commit() -> None:
            self.commits += 1

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _row(record_id: uuid.UUID, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {f.name: None for f in fields(RecordedStopRow)}
    row |= {"id": str(record_id), "exchange_account_id": str(_ACCOUNT), "symbol": "BTCUSDT",
            "position_idx": 0, "position_side": "Buy", "kind": "stop_loss",
            "source": "entry_attach", "order_id": _ORDER, "tpsl_mode": "Full",
            "trigger_price": Decimal("62000"), "status": "pending",
            "audit_record_id": uuid.UUID(int=0x7001), "created_at": _T}  # fmt: skip
    return row | over


@pytest.mark.parametrize(
    ("status", "shown", "end"),
    [
        ("ended", True, "in_force"),
        ("ended", False, "answered_unread"),
        ("in_force", True, None),
        ("pending", False, None),
        ("void", False, None),
    ],
)
def test_a_row_says_how_it_ended(status: str, shown: bool, end: str | None) -> None:
    """#4010's CR-G6-R4-05 (f): an `ended` row with no `in_force_at` is an answered, unread end,
    never one a read confirmed in force."""
    row = mod.stop_row(_row(_SL, status=status, answered_at=_T, in_force_at=_T if shown else None))
    assert row.end == end


def _store(rel: _Rel) -> mod.SqlAlchemyRecordedStopStore:
    return mod.SqlAlchemyRecordedStopStore(cast(Any, rel))  # structural fake


async def test_insert_returns_the_rows_in_the_order_given() -> None:
    rel = _Rel([_row(_TP, kind="take_profit"), _row(_SL)])
    tp = _stop(id=_TP, kind="take_profit", trigger_price=Decimal(65000))
    rows = await _store(rel).insert([_stop(), tp])
    assert [row.id for row in rows] == [_SL, _TP] and rel.commits == 1
    assert isinstance(rows[0].exchange_account_id, uuid.UUID)


async def test_a_settle_locks_then_answers_every_row_of_the_request_or_none() -> None:
    rel = _Rel([], [_row(_TP, answered_at=_T), _row(_SL, answered_at=_T)])
    rows = await _store(rel).settle(_ACCOUNT, [_SL, _TP], "answered", at=_T)
    assert [row.id for row in rows] == [_SL, _TP] and rel.commits == 1
    assert "FOR UPDATE" in _sql(rel.statements[0]) and _sql(rel.statements[1]).startswith("UPDATE")
    stale = _Rel([], [_row(_SL, answered_at=_T)])
    with pytest.raises(StaleRecordedStop):
        await _store(stale).settle(_ACCOUNT, [_SL, _TP], "answered", at=_T)
    assert stale.commits == 0


@pytest.mark.parametrize(
    ("ids", "at", "reason"),
    [
        ([], _T, "names each row of the request once"),
        ([_SL, _SL], _T, "names each row of the request once"),
        ([_SL], datetime(2026, 10, 21), "timezone-aware"),
    ],
)
async def test_a_settle_refuses_a_malformed_call_before_any_statement(
    ids: list[uuid.UUID], at: datetime, reason: str
) -> None:
    """An `answered` settle needs no hook, so only the call's own shape can refuse it here
    (RC-4057-01: a void's hook check must not mask these)."""
    rel = _Rel()
    with pytest.raises(ValueError, match=reason):
        await _store(rel).settle(_ACCOUNT, ids, "answered", at=at)
    assert rel.statements == []


@pytest.mark.parametrize("outcome", ["refused", "not_shown"])
async def test_a_void_without_its_hook_is_refused_before_any_statement(outcome: Any) -> None:
    """SEC-4057-F-01 (C-2.9, 21 section 3.3.11): the store, not only the M14 facade, refuses a
    void with no write-ahead hook, so no caller voids a protective-stop record unaudited."""
    rel = _Rel()
    with pytest.raises(ValueError, match="audited write-ahead"):
        await _store(rel).settle(_ACCOUNT, [_SL], outcome, at=_T)
    assert rel.statements == []


async def test_for_order_reads_the_entry_rows_oldest_first() -> None:
    rel = _Rel([_row(_SL), _row(_TP, kind="take_profit")])
    rows = await _store(rel).for_order(_ACCOUNT, _ORDER)
    assert [row.kind for row in rows] == ["stop_loss", "take_profit"] and rel.commits == 0
    assert _sql(rel.statements[0]).endswith("ORDER BY recorded_stops.created_at, recorded_stops.id")


async def test_live_for_key_maps_rows_in_the_order_read_and_commits_nothing() -> None:
    rel = _Rel([_row(_TP, kind="take_profit"), _row(_SL, status="in_force")])
    rows = await _store(rel).live_for_key(_ACCOUNT, "BTCUSDT", 0)
    assert [(row.id, row.status) for row in rows] == [(_TP, "pending"), (_SL, "in_force")]
    assert isinstance(rows[0].exchange_account_id, uuid.UUID) and rel.commits == 0


async def test_for_exchange_order_maps_the_rows_read_and_commits_nothing() -> None:
    rel = _Rel([_row(_SL, exchange_order_id="x-1")])
    [row] = await _store(rel).for_exchange_order(_ACCOUNT, "x-1")
    assert (row.id, row.exchange_order_id, rel.commits) == (_SL, "x-1", 0)


@pytest.mark.parametrize("text", [None, "", "x" * 65], ids=["none", "empty", "overlong"])
async def test_for_exchange_order_with_an_id_no_order_can_hold_runs_no_statement(
    text: Any,
) -> None:
    rel = _Rel()
    with pytest.raises(ValueError, match="1 to 64 characters"):
        await _store(rel).for_exchange_order(_ACCOUNT, text)
    assert rel.units == 0


async def _audit(rows: tuple[RecordedStopRow, RecordedStopRow]) -> None:
    return None


async def _unaudited(rows: tuple[RecordedStopRow, RecordedStopRow]) -> None:
    raise RuntimeError("the audit trail refused the record")


async def test_a_release_and_bind_awaits_its_audit_before_the_one_commit() -> None:
    rel = _Rel([], [_row(_SL, released_at=_T)], [_row(_TP, exchange_order_id="x-1")])
    seen: list[tuple[tuple[RecordedStopRow, RecordedStopRow], int]] = []

    async def audit(rows: tuple[RecordedStopRow, RecordedStopRow]) -> None:
        seen.append((rows, rel.commits))

    pair = await _store(rel).release_and_bind(_ACCOUNT, _SL, _TP, "x-1", at=_T, write_ahead=audit)
    assert (pair[0].id, pair[1].id, rel.commits) == (_SL, _TP, 1) and seen == [(pair, 0)]
    lock, release, bind = rel.statements  # the pair locked in id order, then the two updates
    pinned = mod.lock_stops_statement(_ACCOUNT, [_TP, _SL])
    assert _sql(lock) == _sql(pinned) and lock.compile().params == pinned.compile().params
    release, bind = _sql(release), _sql(bind)
    assert release.startswith("UPDATE recorded_stops SET exchange_order_id=NULL, released_at=")
    assert bind.startswith("UPDATE recorded_stops SET exchange_order_id=$1::VARCHAR WHERE ")


@pytest.mark.parametrize(
    ("script", "statements"),
    [([[], []], 2), ([[], [_row(_SL, released_at=_T)], []], 3)],
    ids=["the_release_misses", "the_bind_misses"],
)
async def test_a_release_and_bind_where_either_update_misses_commits_nothing_and_skips_the_audit(
    script: list[list[dict[str, Any]]], statements: int
) -> None:
    rel = _Rel(*script)  # the lock first; a miss before a bind skips the bind: nothing to take
    with pytest.raises(RecordedStopNotBindable) as err:
        await _store(rel).release_and_bind(_ACCOUNT, _SL, _TP, "x-1", at=_T, write_ahead=_unaudited)
    assert (rel.commits, len(rel.statements)) == (0, statements) and "x-1" not in str(err.value)


async def test_a_release_and_bind_whose_audit_fails_or_is_late_writes_nothing() -> None:
    async def hangs(rows: tuple[RecordedStopRow, RecordedStopRow]) -> None:
        await asyncio.Event().wait()

    script: tuple[list[dict[str, Any]], ...] = ([], [_row(_SL, released_at=_T)], [_row(_TP)])
    refused, late = _Rel(*script), _Rel(*script)
    with pytest.raises(RuntimeError):
        await _store(refused).release_and_bind(
            _ACCOUNT, _SL, _TP, "x-1", at=_T, write_ahead=_unaudited
        )
    store = mod.SqlAlchemyRecordedStopStore(cast(Any, late), audit_timeout_s=0.01)
    with pytest.raises(WriteAheadTimeout):
        await store.release_and_bind(_ACCOUNT, _SL, _TP, "x-1", at=_T, write_ahead=hangs)
    assert refused.commits == late.commits == 0


@pytest.mark.parametrize(
    ("xid", "at", "hook", "reason"),
    [
        ("", _T, _audit, "1 to 64 characters"),
        ("x-1", datetime(2026, 10, 21), _audit, "timezone-aware"),
        ("x-1", _T, None, "audited write-ahead"),
    ],
)
async def test_a_release_and_bind_malformed_is_refused_before_any_statement(
    xid: str, at: datetime, hook: Any, reason: str
) -> None:
    rel = _Rel()
    with pytest.raises(ValueError, match=reason):
        await _store(rel).release_and_bind(_ACCOUNT, _SL, _TP, xid, at=at, write_ahead=hook)
    assert rel.units == 0


# -- R10: the startup sweep ----------------------------------------------------------------------


def test_the_sweep_voids_only_the_pending_entry_rows_of_an_order_never_placed() -> None:
    """It names the orders whose rows it may void, never the ones it may not (`NOT EXISTS`, the
    old shape, voided every row no listed order kept): never sent, or refused by its create."""
    stmt = mod.void_orphans_statement(_ACCOUNT, _T)
    sql = _sql(stmt)
    assert sql.startswith("UPDATE recorded_stops SET status=$1::VARCHAR, closed_at=$2::")
    where = sql.split(" WHERE ", 1)[1]
    assert "recorded_stops.source = $" in where and "recorded_stops.status = $" in where
    assert "NOT" not in where and where.count("EXISTS (SELECT ") == 2
    unplaced = where.split("EXISTS (SELECT ", 1)[1]
    assert "FROM orders WHERE orders.id = recorded_stops.order_id" in unplaced
    assert "orders.exchange_account_id = recorded_stops.exchange_account_id" in unplaced
    unsent, refused = unplaced.split(" OR ", 1)
    terms = unsent.split("AND (", 1)[1].split(" AND ")
    assert terms[0] == "orders.state IN ('killed', 'pending_submit')"  # constants, as literals
    assert [term.split(" = ")[0] for term in terms[1:]] == [
        "orders.idempotency_state", "orders.submit_attempts", "orders.cum_exec_qty"
    ]  # fmt: skip
    refusal = "FROM order_events WHERE order_events.order_id = orders.id AND "
    assert refusal + "order_events.from_state = $" in refused
    assert "order_events.to_state = $" in refused and "orders.cum_exec_qty = $" in refused
    bound = stmt.compile(dialect=_ASYNCPG).params
    unsent_binds = ("idempotency_state_1", "submit_attempts_1", "cum_exec_qty_1")
    assert [bound[name] for name in unsent_binds] == ["unsent", 0, Decimal(0)]
    assert [bound["state_1"], bound["cum_exec_qty_2"]] == list(REFUSED_ENTRY.values())
    assert (bound["from_state_1"], bound["to_state_1"]) == REFUSED_BY == ("submitted", "rejected")
    assert "answered_at" not in where  # an answered row of an entry never placed goes too
    assert sql.endswith(
        "RETURNING recorded_stops.id, recorded_stops.exchange_account_id, "
        "recorded_stops.order_id, recorded_stops.kind"
    )


def test_the_startup_sweep_over_every_account_names_none() -> None:
    every = _sql(mod.void_orphans_statement(EVERY_ACCOUNT, _T))
    assert "recorded_stops.exchange_account_id = $" not in every
    assert "recorded_stops.exchange_account_id = $" in _sql(
        mod.void_orphans_statement(_ACCOUNT, _T)
    )


def test_the_sweep_proves_an_entry_never_placed_and_nothing_else() -> None:
    """Its whole scope (the 2026-10-21 ruling, CR-2A-01, the rulings of 14:26Z): an entry never
    sent, still `pending_submit` or killed before its send, or one its create's own answer refused
    (`rejected` out of `submitting`, persisted `submitted`), nothing filled. An order killed after
    its send, one ended out of `unknown` or `held`, and a cancel or expiry the sweep cannot see
    confirmed wait for the complete read: never voided blind (C-2.6)."""
    assert dict(UNSENT_ENTRY) == {
        "state": frozenset({"pending_submit", "killed"}), "idempotency_state": "unsent",
        "submit_attempts": 0, "cum_exec_qty": Decimal(0),
    }  # fmt: skip
    assert dict(REFUSED_ENTRY) == {"state": "rejected", "cum_exec_qty": Decimal(0)}
    assert set(UNSENT_ENTRY) | set(REFUSED_ENTRY) <= set(models.orders.c.keys())
    assert REFUSED_BY == ("submitted", "rejected")
    # SEC-2A-D1-05: `submitting -> rejected` is the create's own answer only, so the sweep's proof
    # holds while B1 has no other edge into `rejected` out of `submitting`.
    edges = Legality.of(Registry().get("order")).triggers
    assert edges[("submitting", "rejected")] == {"done.invoke.place"}


_SWEPT = [{"id": str(_SL), "exchange_account_id": str(_ACCOUNT), "order_id": str(_ORDER),
           "kind": "stop_loss"}]  # fmt: skip


async def test_the_sweep_audits_what_it_voided_before_its_commit() -> None:
    seen: list[tuple[tuple[SweptStop, ...], int]] = []
    rel = _Rel(_SWEPT)

    async def audit(swept: tuple[SweptStop, ...]) -> None:
        seen.append((swept, rel.commits))

    got = await _store(rel).void_orphans(EVERY_ACCOUNT, at=_T, write_ahead=audit)
    assert got == (SweptStop(_SL, _ACCOUNT, _ORDER, "stop_loss"),)
    assert seen == [(got, 0)] and rel.commits == 1


async def test_a_sweep_that_voids_nothing_audits_nothing() -> None:
    async def audit(swept: tuple[SweptStop, ...]) -> None:
        raise AssertionError("nothing to audit")

    assert await _store(_Rel([])).void_orphans(_ACCOUNT, at=_T, write_ahead=audit) == ()


async def test_an_audit_past_its_bound_leaves_every_row_as_it_was() -> None:
    rel = _Rel(_SWEPT)

    async def hangs(swept: tuple[SweptStop, ...]) -> None:
        await asyncio.Event().wait()

    store = mod.SqlAlchemyRecordedStopStore(cast(Any, rel), audit_timeout_s=0.01)
    with pytest.raises(WriteAheadTimeout) as exc:
        await store.void_orphans(EVERY_ACCOUNT, at=_T, write_ahead=hangs)
    assert not isinstance(exc.value, StorageTierUnavailable) and rel.commits == 0


@pytest.mark.parametrize("scope", [None, "every_account", str(_ACCOUNT)])
async def test_a_sweep_covers_one_account_or_every_account_by_name(scope: Any) -> None:
    """CR-2A-07: an account a caller forgot (`None`) is refused before any statement, never read
    as every account; the audit reason the sweep's hook records is the port's."""

    async def audit(swept: tuple[SweptStop, ...]) -> None:
        raise AssertionError("no audit without a sweep")

    rel = _Rel()
    with pytest.raises(TypeError, match="EVERY_ACCOUNT"):
        await _store(rel).void_orphans(scope, at=_T, write_ahead=audit)
    assert rel.statements == [] and SWEEP_REASON == "unplaced_entry_swept"


async def test_a_settle_awaits_its_audit_with_the_settled_rows_before_its_commit() -> None:
    """SEC-2A-05 (C-2.9): the writer's audit of the answer lands in the settle's transaction."""
    voided = {"status": "void", "closed_at": _T}
    rel = _Rel([], [_row(_TP, kind="take_profit", **voided), _row(_SL, **voided)])
    seen: list[tuple[list[uuid.UUID], int]] = []

    async def audit(rows: tuple[RecordedStopRow, ...]) -> None:
        seen.append(([row.id for row in rows], rel.commits))

    rows = await _store(rel).settle(_ACCOUNT, [_SL, _TP], "not_shown", at=_T, write_ahead=audit)
    assert [row.id for row in rows] == [_SL, _TP] and seen == [([_SL, _TP], 0)]
    assert rel.commits == 1


async def test_a_settle_whose_audit_fails_or_is_late_writes_nothing() -> None:
    async def refuses(rows: tuple[RecordedStopRow, ...]) -> None:
        raise RuntimeError("the audit trail refused the record")

    async def hangs(rows: tuple[RecordedStopRow, ...]) -> None:
        await asyncio.Event().wait()

    refused = _Rel([], [_row(_SL, answered_at=_T)])
    with pytest.raises(RuntimeError):
        await _store(refused).settle(_ACCOUNT, [_SL], "answered", at=_T, write_ahead=refuses)
    late = _Rel([], [_row(_SL, answered_at=_T)])
    store = mod.SqlAlchemyRecordedStopStore(cast(Any, late), audit_timeout_s=0.01)
    with pytest.raises(WriteAheadTimeout):
        await store.settle(_ACCOUNT, [_SL], "answered", at=_T, write_ahead=hangs)
    assert refused.commits == late.commits == 0


# -- E29-T04 slice 2b: the request's audit, and the rows that hold a key --------------------------


async def test_an_insert_awaits_its_audit_with_the_rows_before_its_commit() -> None:
    """21 Sec.3.3.11 "Audit" (C-2.9): the request's record lands in the insert's transaction."""
    rel = _Rel([_row(_SL)])
    seen: list[tuple[list[uuid.UUID], int]] = []

    async def audit(rows: tuple[RecordedStopRow, ...]) -> None:
        seen.append(([row.id for row in rows], rel.commits))

    rows = await _store(rel).insert([_stop()], write_ahead=audit)
    assert [row.id for row in rows] == [_SL] and seen == [([_SL], 0)] and rel.commits == 1


async def test_an_insert_whose_audit_fails_or_is_late_commits_nothing() -> None:
    async def refuses(rows: tuple[RecordedStopRow, ...]) -> None:
        raise RuntimeError("the audit trail refused the record")

    async def hangs(rows: tuple[RecordedStopRow, ...]) -> None:
        await asyncio.Event().wait()

    refused = _Rel([_row(_SL)])
    with pytest.raises(RuntimeError):
        await _store(refused).insert([_stop()], write_ahead=refuses)
    late = _Rel([_row(_SL)])
    store = mod.SqlAlchemyRecordedStopStore(cast(Any, late), audit_timeout_s=0.01)
    with pytest.raises(WriteAheadTimeout):
        await store.insert([_stop()], write_ahead=hangs)
    assert refused.commits == late.commits == 0


def test_the_rows_that_hold_a_key_are_its_overdue_unanswered_ones_and_an_ended_entrys() -> None:
    """21 Sec.3.3.11 and the orchestrator's Q2 ruling: the key's pending rows still unanswered past
    their request's bound, of any source, and an entry's pending rows, answered or not, whose order
    of the row's account ended, or is held, with nothing filled (`WAITING_ENTRY`), whatever their
    age; in the account, oldest first."""
    stmt = mod.waiting_for_key_statement(_ACCOUNT, "BTCUSDT", 1, now=_T, bound_s=5.0)
    sql = _sql(stmt)
    where = sql.split(" WHERE ", 1)[1]
    for column in ("exchange_account_id", "symbol", "position_idx", "status"):
        assert f"recorded_stops.{column} = $" in where
    overdue, ended = where.split("(recorded_stops.answered_at IS NULL AND ", 1)[1].split(
        " OR recorded_stops.source = $", 1
    )
    assert overdue.startswith("recorded_stops.created_at <= $") and "EXISTS" not in overdue
    assert "EXISTS (SELECT " in ended and "created_at" not in ended.split(" ORDER BY ")[0]
    assert "FROM orders WHERE orders.id = recorded_stops.order_id" in ended
    assert "orders.exchange_account_id = recorded_stops.exchange_account_id" in ended
    states = "orders.state IN ('cancelled', 'expired', 'held', 'killed', 'rejected')"
    assert states in ended and "orders.cum_exec_qty = $" in ended  # the states as literals
    assert sql.endswith("ORDER BY recorded_stops.created_at, recorded_stops.id")
    bound = stmt.compile(dialect=_ASYNCPG).params
    assert (bound["status_1"], bound["source_1"], bound["cum_exec_qty_1"]) == (
        "pending",
        "entry_attach",
        Decimal(0),
    )
    assert bound["created_at_1"] == _T - timedelta(seconds=5)


_FIVE = timedelta(seconds=5)


@pytest.mark.parametrize(
    ("bound_s", "cutoff"),
    [
        (5.0, _T - _FIVE),
        (5, _T - _FIVE),
        (0.0, _T),
        (None, None),
        (float("nan"), None),
        (float("inf"), None),
        (float("-inf"), None),
        (-1.0, None),
        (1e300, None),
        (10**20, None),  # an int past what a timestamp holds
        (True, None),
        ("5", None),
    ],
)
def test_an_unanswered_row_holds_its_key_from_its_requests_bound_on(
    bound_s: Any, cutoff: datetime | None
) -> None:
    """The orchestrator's Q2 ruling: an unanswered row younger than its bound (created after
    `now - bound`) is not read, as Q4's bounded retry meets it at the insert (`ux_rs_in_flight`);
    one as old as the bound or older is (`<=` the cutoff); a bound missing or unusable reads every
    unanswered row (fail closed), with no cutoff in the statement."""
    assert request_cutoff(_T, bound_s) == cutoff
    stmt = mod.waiting_for_key_statement(_ACCOUNT, "BTCUSDT", 0, now=_T, bound_s=bound_s)
    sql, bound = _sql(stmt), stmt.compile(dialect=_ASYNCPG).params
    if cutoff is None:
        assert "created_at <=" not in sql and "created_at_1" not in bound
        assert "(recorded_stops.answered_at IS NULL OR recorded_stops.source = $" in sql
        return
    assert "(recorded_stops.answered_at IS NULL AND recorded_stops.created_at <= $" in sql
    inside, at_the_bound = cutoff + timedelta(microseconds=1), cutoff
    assert bound["created_at_1"] == cutoff
    assert not inside <= bound["created_at_1"] and at_the_bound <= bound["created_at_1"]


async def test_the_store_reads_the_waiting_rows_and_a_naive_now_runs_nothing() -> None:
    rel = _Rel([_row(_SL)])
    rows = await _store(rel).waiting_for_key(_ACCOUNT, "BTCUSDT", 0, now=_T, bound_s=5.0)
    assert [row.id for row in rows] == [_SL] and rel.commits == 0
    [stmt] = rel.statements
    assert stmt.compile(dialect=_ASYNCPG).params["created_at_1"] == _T - _FIVE
    idle = _Rel()
    with pytest.raises(ValueError, match="timezone-aware"):
        await _store(idle).waiting_for_key(
            _ACCOUNT, "BTCUSDT", 0, now=_T.replace(tzinfo=None), bound_s=5.0
        )
    assert idle.statements == []


def test_an_entry_waits_once_it_ended_with_nothing_filled() -> None:
    """The ends 21 Sec.3.3.11's table leaves waiting, held among them; no state an entry stays
    live in, and none a voiding end reaches only through the step's own settle."""
    assert dict(WAITING_ENTRY) == {
        "state": frozenset({"killed", "expired", "cancelled", "rejected", "held"}),
        "cum_exec_qty": Decimal(0),
    }
    assert set(WAITING_ENTRY) <= set(models.orders.c.keys())


# -- slice 3 (S3-H): what the complete read writes ------------------------------------------------

_STAMP = "answered_at=coalesce(recorded_stops.answered_at, $2::TIMESTAMP WITH TIME ZONE)"
_LATER, _OLD, _NEW = _T + timedelta(seconds=1), uuid.UUID(int=0x6000), uuid.UUID(int=0x6003)


def _rows(*maps: dict[str, Any]) -> list[RecordedStopRow]:
    return [mod.stop_row(m) for m in maps]


def _sets(stmt: Any) -> str:
    return _sql(stmt).split(" SET ", 1)[1].split(" WHERE ", 1)[0]


def test_the_complete_reads_statements_lock_in_id_order_and_keep_answered_at_once_set() -> None:
    lock = _sql(mod.lock_key_statement(_ACCOUNT, "BTCUSDT", 1))
    assert "recorded_stops.status IN (" in lock and "recorded_stops.position_idx = $" in lock
    assert lock.endswith("ORDER BY recorded_stops.id FOR UPDATE")
    gone = mod.replace_statement(_ACCOUNT, [_SL], _T)
    assert _sets(gone) == f"status=$1::VARCHAR, {_STAMP}, closed_at=$3::TIMESTAMP WITH TIME ZONE"
    rows = _rows(_row(_SL), _row(_TP, kind="take_profit", answered_at=_T))
    shown = mod.in_force_statement(_ACCOUNT, rows, _T)
    assert _sets(shown) == f"status=$1::VARCHAR, {_STAMP}, in_force_at=$3::TIMESTAMP WITH TIME ZONE"
    # SEC-BND-02: the in-force and resolve UPDATEs compare-and-set each row's `answered_at` as read
    assert _sql(shown).count("recorded_stops.answered_at IS NOT DISTINCT FROM ") == 2
    answer = mod.resolve_statement(_ACCOUNT, rows, "answered", _T)
    assert _sets(answer) == _STAMP.replace("$2", "$1")
    void = mod.resolve_statement(_ACCOUNT, rows, "entry_filled_stop_absent", _T)
    assert _sets(void) == "status=$1::VARCHAR, closed_at=$2::TIMESTAMP WITH TIME ZONE"
    gone = mod.resolve_statement(_ACCOUNT, rows, "replaced", _T)
    assert _sets(gone) == f"status=$1::VARCHAR, {_STAMP}, closed_at=$3::TIMESTAMP WITH TIME ZONE"
    assert _sql(void).count("recorded_stops.answered_at IS NOT DISTINCT FROM ") == 2
    # a row is compared as read on its key too, as the fake compares it
    assert _sql(void).count("recorded_stops.symbol = $") == 2
    assert _sql(void).count("recorded_stops.position_idx = $") == 2
    keys = _sql(mod.waiting_keys_statement(_ACCOUNT, now=_T, bound_s=5.0))
    assert "recorded_stops.answered_at IS NULL AND recorded_stops.created_at <= $" in keys
    assert keys.endswith("ORDER BY min(recorded_stops.created_at), recorded_stops.symbol, "
                         "recorded_stops.position_idx")  # fmt: skip


def _live(i: uuid.UUID, kind: str, status: str, answered: Any, born: datetime = _T) -> Any:
    return {"id": i, "kind": kind, "status": status, "answered_at": answered, "created_at": born}


async def test_a_put_in_force_refuses_a_malformed_call_before_any_statement() -> None:
    rel, tp = _Rel(), _row(_TP, kind="take_profit", position_idx=1)
    for rows, at, reason in (([_row(_SL)] * 2, _T, "named once"), ([_row(_SL), _row(_TP)], _T,
                             "per key and kind"), ([_row(_SL), tp], _T, "of one key"),
                             ([_row(_SL)], _T.replace(tzinfo=None), "timezone-aware")):  # fmt: skip
        with pytest.raises(ValueError, match=reason):
            await _store(rel).put_in_force(_ACCOUNT, _rows(*rows), at=at)
    assert rel.statements == []


async def test_a_put_in_force_locks_replaces_first_then_sets_audited_before_its_commit() -> None:
    """21 Sec.3.3.11: it replaces the row in force of its kind and its older answered rows; never
    a younger row, an unanswered one or one of another kind."""
    gone, shown = {"status": "replaced"}, {"status": "in_force"}
    older, unanswered = uuid.UUID(int=0x6004), uuid.UUID(int=0x6005)
    locked = [_live(_OLD, "stop_loss", "in_force", _T), _live(_SL, "stop_loss", "pending", None,
              _LATER), _live(_TP, "take_profit", "in_force", _T), _live(_NEW, "stop_loss",
              "pending", _T, _LATER + timedelta(1)), _live(older, "stop_loss", "pending", _T),
              _live(unanswered, "stop_loss", "pending", None)]  # fmt: skip
    rel = _Rel(locked, [_row(_OLD, **gone), _row(older, **gone)], [_row(_SL, **shown)])
    seen: list[tuple[list[uuid.UUID], int]] = []

    async def audit(rows: tuple[RecordedStopRow, ...]) -> None:
        seen.append(([row.id for row in rows], rel.commits))

    done = await _store(rel).put_in_force(_ACCOUNT, _rows(_row(_SL)), at=_T, write_ahead=audit)
    assert [r.id for r in done.replaced] == [_OLD, older] and [r.id for r in done.in_force] == [_SL]
    assert seen == [([_OLD, older, _SL], 0)] and rel.commits == 1
    assert [s.compile().params.get("status") for s in rel.statements] == [
        None, "replaced", "in_force"
    ]  # fmt: skip
    alone = _Rel([_live(_SL, "stop_loss", "pending", None)], [_row(_SL, **shown)])
    assert (await _store(alone).put_in_force(_ACCOUNT, _rows(_row(_SL)), at=_T)).replaced == ()
    assert len(alone.statements) == 2 and alone.commits == 1


@pytest.mark.parametrize("script", ["lost_at_the_lock", "short_update", "late_audit"])
async def test_a_put_in_force_that_loses_its_race_or_its_audit_writes_nothing(script: str) -> None:
    async def hangs(rows: tuple[RecordedStopRow, ...]) -> None:
        await asyncio.Event().wait()

    answered = _T if script == "lost_at_the_lock" else None
    shown = [] if script == "short_update" else [_row(_SL, status="in_force")]
    rel = _Rel([_live(_SL, "stop_loss", "pending", answered)], shown)
    store = mod.SqlAlchemyRecordedStopStore(cast(Any, rel), audit_timeout_s=0.01)
    raised = WriteAheadTimeout if script == "late_audit" else StaleRecordedStop
    with pytest.raises(raised):
        await store.put_in_force(_ACCOUNT, _rows(_row(_SL)), at=_T, write_ahead=hangs)
    assert rel.commits == 0


async def test_a_resolve_locks_then_sets_every_row_or_none_audited_before_its_commit() -> None:
    voided_cols = {"status": "void", "closed_at": _T}
    rel = _Rel([], [_row(_TP, kind="take_profit", **voided_cols), _row(_SL, **voided_cols)])
    seen: list[tuple[list[uuid.UUID], FillPosition | None, int]] = []

    async def audit(rows: tuple[RecordedStopRow, ...], state: FillPosition | None) -> None:
        seen.append(([row.id for row in rows], state, rel.commits))

    rows = _rows(_row(_SL), _row(_TP, kind="take_profit"))
    done = await _store(rel).resolve(_ACCOUNT, rows, "entry_filled_stop_absent", at=_T,
                                     position_state="open", write_ahead=audit)  # fmt: skip
    assert [r.id for r in done] == [_SL, _TP] and seen == [([_SL, _TP], "open", 0)]
    assert rel.commits == 1
    assert "FOR UPDATE" in _sql(rel.statements[0])
    stale = _Rel([], [_row(_SL)])
    with pytest.raises(StaleRecordedStop):
        await _store(stale).resolve(_ACCOUNT, rows, "answered", at=_T)
    refused: tuple[tuple[list[uuid.UUID], datetime, FillPosition | None, str], ...] = (
        ([_SL, _SL], _T, None, "names each row"), ([], _T, None, "names each row"),
        ([_SL], _T.replace(tzinfo=None), None, "timezone-aware"),
        ([_SL], _T, "flat", "position_state"),
    )  # fmt: skip
    for ids, at, state, reason in refused:
        with pytest.raises(ValueError, match=reason):
            await _store(stale).resolve(_ACCOUNT, _rows(*map(_row, ids)), "answered", at=at,
                                        position_state=state)  # fmt: skip
    with pytest.raises(ValueError, match="position_state"):  # refused for a replace
        await _store(stale).resolve(_ACCOUNT, rows, "replaced", at=_T, position_state="open")
    with pytest.raises(ValueError, match="position_state"):  # required for the fill void
        await _store(stale).resolve(_ACCOUNT, rows, "entry_filled_stop_absent", at=_T,
                                    write_ahead=audit)  # fmt: skip
    voided = _Rel([], [_row(_SL, **voided_cols)])
    await _store(voided).resolve(_ACCOUNT, rows[:1], "in_flight_resolved", at=_T,
                                 position_state="open", write_ahead=audit)  # fmt: skip
    assert seen[-1][:2] == ([_SL], "open") and voided.commits == 1  # optional: given to the hook
    assert stale.commits == 0 and len(stale.statements) == 2


async def test_the_store_reads_a_keys_rows_in_force_by_kind() -> None:
    rel = _Rel([_row(_SL, status="in_force"), _row(_TP, kind="take_profit", status="in_force")])
    rows = await _store(rel).in_force_for_key(_ACCOUNT, "BTCUSDT", 0)
    assert [row.kind for row in rows] == ["stop_loss", "take_profit"] and rel.commits == 0
    sql = _sql(rel.statements[0])
    assert "recorded_stops.status = $" in sql and "recorded_stops.position_idx = $" in sql
    assert sql.endswith("ORDER BY recorded_stops.kind")


async def test_the_store_reads_the_waiting_keys_and_a_naive_now_runs_nothing() -> None:
    rel = _Rel([{"symbol": "BTCUSDT", "position_idx": 0}, {"symbol": "ETHUSDT", "position_idx": 2}])
    keys = await _store(rel).waiting_keys(_ACCOUNT, now=_T, bound_s=5.0)
    assert keys == (("BTCUSDT", 0), ("ETHUSDT", 2)) and rel.commits == 0
    with pytest.raises(ValueError, match="timezone-aware"):
        await _store(rel).waiting_keys(_ACCOUNT, now=_T.replace(tzinfo=None), bound_s=5.0)
    assert len(rel.statements) == 1
