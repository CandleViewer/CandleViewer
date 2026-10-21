"""Unit tests for the recorded stops' port and Postgres adapter (E29-T04 #913): the dataclass
refusals, the account scope of every statement, the settle compare-and-set, and the store against
a recording fake unit of work. Real SQL: tests/integration/storage/test_order_submission_pg.py
and the 0043 migration suite (CI only)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.engine import Dialect, make_url
from sqlalchemy.sql.elements import TextClause

from candleviewer.db import models
from candleviewer.storage.repositories import recorded_stops_sqlalchemy as mod
from candleviewer.storage.repositories.recorded_stops import (
    NewRecordedStop,
    RecordedStopRow,
    StaleRecordedStop,
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
        ({"size": Decimal("0.010")}, "rs_size"),
        ({"tpsl_mode": "Partial"}, "rs_size"),
        ({"tpsl_mode": "Partial", "size": Decimal(0)}, "rs_size"),
        ({"trailing_distance": Decimal(50)}, "rs_trail"),
        ({"trailing_distance": Decimal(0), "trailing_active_price": Decimal(1)}, "rs_trail"),
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
    }


def test_every_statement_but_the_insert_filters_the_account() -> None:
    built = _built()
    assert set(built) == {name for name in vars(mod) if name.endswith("_statement")}
    unscoped = {
        n for n, s in built.items() if "recorded_stops.exchange_account_id = " not in _sql(s)
    }
    assert unscoped == set(mod.UNSCOPED) == {"insert_stops_statement"}


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
        self.commits = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
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
    ("ids", "at"), [([], _T), ([_SL, _SL], _T), ([_SL], datetime(2026, 10, 21))]
)
async def test_a_settle_refuses_a_malformed_call_before_any_statement(
    ids: list[uuid.UUID], at: datetime
) -> None:
    rel = _Rel()
    with pytest.raises(ValueError):
        await _store(rel).settle(_ACCOUNT, ids, "refused", at=at)
    assert rel.statements == []


async def test_for_order_reads_the_entry_rows_oldest_first() -> None:
    rel = _Rel([_row(_SL), _row(_TP, kind="take_profit")])
    rows = await _store(rel).for_order(_ACCOUNT, _ORDER)
    assert [row.kind for row in rows] == ["stop_loss", "take_profit"] and rel.commits == 0
    assert _sql(rel.statements[0]).endswith("ORDER BY recorded_stops.created_at, recorded_stops.id")
