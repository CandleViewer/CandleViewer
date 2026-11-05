"""The closed-PnL store without a database (E29-S06 #981 slice 2; 21 Sec.3.3.13): the records' ids
and refusals before any statement, a venue read's outcome, and each statement's shape and bound
parameters. Real SQL: `tests/integration/storage/test_closed_pnl_store_pg.py`."""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid5

import pytest
from sqlalchemy import TextClause
from sqlalchemy.engine import make_url

from candleviewer.db import models
from candleviewer.storage.repositories import closed_pnl_sqlalchemy as mod
from candleviewer.storage.repositories.closed_pnl import (
    CLOSED_PNL_NAMESPACE,
    ClosedPnlQuery,
    ClosedPnlRecordRow,
    ComposedRecord,
    FillKey,
    TotalsUnbounded,
    VenueRecord,
    record_id,
    require_window,
    settle_outcome,
)
from candleviewer.storage.repositories.oms_reads import Keyset

_OPENAPI = Path(__file__).resolve().parents[5] / "docs" / "plan" / "22-api-openapi.yaml"
_T, _A, _B = datetime(2026, 11, 3, 9, tzinfo=UTC), uuid.UUID(int=0x9811), uuid.UUID(int=0x9812)
_G = uuid.UUID(int=0x9813)


def _sql(stmt: Any) -> tuple[str, dict[str, Any]]:
    """The statement as asyncpg runs it, and its bound parameters."""
    dialect = make_url("postgresql+asyncpg://").get_dialect()()
    text = str(stmt.compile(dialect=dialect, compile_kwargs={"render_postcompile": True}))
    return " ".join(text.split()), dict(stmt.compile(dialect=dialect).params)


def _composed(**over: Any) -> ComposedRecord:
    values = {"exchange_account_id": _A, "exchange_order_id": "o-1", "symbol": "SOLUSDT"}
    values |= {"side": "long", "closed_at": _T, "qty": Decimal(4), "gross_pnl": Decimal("10.8")}
    return ComposedRecord(**(values | over))


def _venue(**over: Any) -> VenueRecord:
    values = {"exchange_account_id": _A, "exchange_order_id": "o-1", "symbol": "SOLUSDT"}
    values |= {"side": "long", "qty": Decimal(4), "avg_entry_price": Decimal("148.1")}
    values |= {"avg_exit_price": Decimal("150.8"), "leverage": Decimal(3), "closed_at": _T}
    return VenueRecord(**(values | {"closed_pnl": Decimal(10), "venue_created_at": _T} | over))


def _held(**over: Any) -> dict[str, Any]:
    """The row a store holds of `_venue()`'s record, settled and not final, every column named."""
    row: dict[str, Any] = dict.fromkeys(f.name for f in fields(ClosedPnlRecordRow))
    row |= {name: getattr(_venue(), name) for name in mod.VENUE_COLUMNS} | {"settled_at": _T}
    return row | over


def test_a_records_id_is_22s_uuid5_and_22s_example_holds_it() -> None:
    """24 Sec.8.13: one id from provisional to settled, and the empty-orderId rule's other name."""
    assert f'x-cv-uuid5-namespace: "{CLOSED_PNL_NAMESPACE}"' in _OPENAPI.read_text(encoding="utf-8")
    for n, order, item in (
        (1, "5a373bfe-188d-4913-9c81-d57ab5be8068", "12775541-ff9d-57c6-9658-505245e39c93"),
        (2, "7c1f2a90-3b4d-4e8f-9a61-2d5c0e9b1f47", "57b2e4d1-4ff2-540f-92af-4cdc494f0f38"),
    ):
        assert str(record_id(uuid.UUID(f"a1000000-0000-4000-8000-00000000000{n}"), order)) == item
    assert _composed().id == _venue().id == record_id(_A, "o-1")
    created = datetime(2026, 11, 3, 9, 0, 0, 123_000, tzinfo=UTC)
    orderless = _venue(exchange_order_id=None, side="short", venue_created_at=created)
    name = f"{_A}:record:SOLUSDT:short:1793696400123"
    assert orderless.id == uuid5(CLOSED_PNL_NAMESPACE, name) != replace(orderless, side="long").id


@pytest.mark.parametrize(
    ("make", "over", "rule"),
    [
        (_composed, {"exchange_order_id": ""}, "order id"), (_venue, {"side": "Sell"}, "cpr_side"),
        (_venue, {"exchange_order_id": "x" * 65}, "order id"), (_composed, {"side": "x"}, "side"),
        (_composed, {"position_idx": 3}, "cpr_posidx"), (_venue, {"qty": Decimal(0)}, "cpr_qty"),
        (_composed, {"fee_pnl": Decimal("1E-19")}, "fee_pnl"),
        (_venue, {"leverage": Decimal("3.005")}, "leverage"),
        (_venue, {"closed_pnl": Decimal("NaN")}, "closed_pnl"),
        (_composed, {"opened_at": datetime(2026, 11, 3)}, "opened_at"),
        (_venue, {"venue_created_at": datetime(2026, 11, 3)}, "venue_created_at"),
    ],
)  # fmt: skip
def test_a_record_the_table_would_refuse_is_refused_before_any_statement(
    make: Any, over: dict[str, Any], rule: str
) -> None:
    with pytest.raises(ValueError, match=rule) as refused:
        make(**over)
    assert "SOLUSDT" not in str(refused.value)
    for bad in ({"accounts": ()}, {"side": "buy"}, {"until": datetime(2026, 11, 3)}):
        with pytest.raises(ValueError):
            ClosedPnlQuery(**({"accounts": (_A,)} | bad))


@pytest.mark.parametrize(
    ("held", "read", "outcome"),
    [
        (None, {}, "inserted"), ({"settled_at": None}, {}, "settled"),
        ({}, {"qty": Decimal("4.000")}, "unchanged"),  # one value at another scale
        ({}, {"closed_at": _T + timedelta(seconds=1)}, "replaced"),
        ({"final_at": _T}, {}, "unchanged"), ({"final_at": _T}, {"qty": Decimal(9)}, "frozen"),
    ],
)  # fmt: skip
def test_a_venue_read_settles_once_replaces_until_final_then_is_frozen(
    held: dict[str, Any] | None, read: dict[str, Any], outcome: str
) -> None:
    held_row = None if held is None else ClosedPnlRecordRow(**_held(**held))
    assert settle_outcome(held_row, _venue(**read)) == outcome
    assert [f.name for f in fields(ClosedPnlRecordRow)] == list(models.closed_pnl_records.c.keys())


def test_each_statement_names_its_account_and_keeps_its_writers_and_readers_apart() -> None:
    """C-12.4 on every statement. The composition writes its figures and `trade_group_id` always
    and the provisional columns only unsettled; a venue read, the venue's columns and `settled_at`
    once, never on a final row and never the group; `finalize`, once. A page reads each account
    on its own (`LATERAL`) either way from its keyset and merges, serves an item with no figure and
    has `net_pnl` from the totals' expression; the symbol and group filters match their stored
    columns, each alternative once, and the page and the totals read the window from `since` up
    to, not at, `until`. Rows 56 and 57 write the predicates of their partial indexes
    (`ix_cpr_pending`, `ix_psnap_flat`) as literals, which a generic plan can prove, and bind the
    rest; row 58's `ix_exec_walk` is not partial. The poll is pinned whole, its inner join
    included, in the `closed_at` order alone that `ix_cpr_pending` gives, and the flats read each
    venue time once."""
    query = ClosedPnlQuery(
        accounts=(_B, _A, _A), symbols=("SOLUSDT", "BTCUSDT", "SOLUSDT"), trade_groups=(_G, _G),
        side="short", since=_T, until=_T + timedelta(days=1),
    )  # fmt: skip
    compose, settle, final, ascending, descending, totals, pending, flats, fills, first = (
        _sql(stmt) for stmt in (
            mod.compose_statement(_composed(trade_group_id=_G)), mod.settle_statement(_venue()),
            mod.finalize_statement(_A, _venue().id), mod.page_statement(query, Keyset(_T, _A), 7),
            mod.page_statement(replace(query, oldest_first=False), Keyset(_T, _A), 7),
            mod.totals_statement(query), mod.pending_statement(_A, _T, 5),
            mod.walk_flats_statement(_A, "SOLUSDT", 2, _T, 5),
            mod.walk_fills_statement(_A, "SOLUSDT", 1, FillKey(_T, "e-9"), 5),
            mod.walk_fills_statement(_A, "SOLUSDT", 1, FillKey(_T), 5),
        )
    )  # fmt: skip
    scoped = r"\b(closed_pnl_records|position_snapshots|executions)\.exchange_account_id (=|IN \()"
    statements = (compose, settle, final, ascending, totals, pending, flats, fills)
    assert all(re.search(scoped, sql) for sql, _ in statements)
    assert all(f" {name} = excluded.{name}," in compose[0] for name in mod.LOCAL)
    case = "CASE WHEN (closed_pnl_records.settled_at IS NOT NULL) THEN closed_pnl_records."
    assert all(f"{n} = {case}{n} ELSE excluded.{n} END" in compose[0] for n in mod.PROVISIONAL)
    assert not {*mod.LOCAL, *mod.PROVISIONAL} & {"leverage", "closed_pnl", "settled_at"}
    assert compose[1]["id"] == record_id(_A, "o-1") and compose[1]["trade_group_id"] == _G
    assert settle[1]["leverage"] == Decimal(3) and "trade_group_id" not in settle[0]
    assert all(f"{name} = excluded.{name}" in settle[0] for name in mod.VENUE_COLUMNS)
    assert "settled_at = coalesce(closed_pnl_records.settled_at, excluded.settled_at)" in settle[0]
    assert settle[0].endswith(
        "AND closed_pnl_records.final_at IS NULL RETURNING closed_pnl_records.id"
    )
    assert ("SET final_at=now(), updated_at=now() WHERE closed_pnl_records.exchange_account_id = "
            "$1::UUID AND closed_pnl_records.id = $2::UUID AND closed_pnl_records.final_at IS NULL "
            "AND closed_pnl_records.settled_at IS NOT NULL AND closed_pnl_records."
            "exchange_order_id IS NOT NULL") in final[0]  # fmt: skip
    net = (f"{case}closed_pnl ELSE closed_pnl_records.gross_pnl + coalesce(closed_pnl_records."
           "fee_pnl, 0) + coalesce(closed_pnl_records.funding_pnl, 0) END")  # fmt: skip
    group = "closed_pnl_records.trade_group_id IN ($"
    symbol, symbols = "closed_pnl_records.symbol IN ($", ["BTCUSDT", "SOLUSDT"]  # once, in order
    window = ("closed_pnl_records.closed_at >= ${}::TIMESTAMP WITH TIME ZONE AND "
              "closed_pnl_records.closed_at < ${}::TIMESTAMP WITH TIME ZONE")  # fmt: skip
    for (sql, params), sign, order in ((ascending, ">", ""), (descending, "<", " DESC")):
        assert sql.startswith("SELECT page.id, page.exchange_account_id, ")
        assert ("FROM (VALUES ($1::UUID), ($2::UUID)) AS accounts (account_id) JOIN LATERAL "
                "(SELECT closed_pnl_records.id AS id, ") in sql  # fmt: skip
        assert f"{net} AS net_pnl FROM closed_pnl_records WHERE closed_pnl_records." in sql
        assert "exchange_account_id = accounts.account_id AND " in sql and group in sql
        assert symbol in sql and symbols in params.values()
        assert "gross_pnl IS NOT NULL" not in sql  # an item without a figure is served
        assert sql.endswith(
            f"{window.format(4, 5)} AND (closed_pnl_records.closed_at, closed_pnl_records.id) "
            f"{sign} ($6::TIMESTAMP WITH TIME ZONE, $7::UUID) ORDER BY closed_pnl_records."
            f"closed_at{order}, closed_pnl_records.id{order} LIMIT $8::INTEGER) AS page ON true "
            f"ORDER BY page.closed_at{order}, page.id{order} LIMIT $9::INTEGER"
        )
        assert [params["param_1"], params["param_2"]] == [_A, _B] and params["side_1"] == "short"
        assert params["trade_group_id_1"] == [_G]
        assert (params["closed_at_1"], params["closed_at_2"]) == (query.since, query.until)
    assert (f"count(*) AS count, coalesce(sum({net}), 0) AS net_pnl, "
            "bool_or(closed_pnl_records.settled_at IS NULL)") in totals[0]  # fmt: skip
    assert "closed_pnl_records.exchange_account_id IN ($" in totals[0] and group in totals[0]
    assert symbol in totals[0] and symbols in totals[1].values()
    assert totals[1]["exchange_account_id_1"] == [_A, _B] and "gross_pnl IS NOT" not in totals[0]
    assert totals[0].endswith(
        f"{window.format(2, 3)} GROUP BY ROLLUP(closed_pnl_records.exchange_account_id) "
        "ORDER BY closed_pnl_records.exchange_account_id NULLS FIRST"
    )
    assert (totals[1]["closed_at_1"], totals[1]["closed_at_2"]) == (query.since, query.until)
    record = ", ".join(f"closed_pnl_records.{f.name}" for f in fields(ClosedPnlRecordRow))
    assert pending[0].removeprefix(f"SELECT {record}, ") == (
        "orders.id AS order_id, orders.state AS order_state FROM closed_pnl_records JOIN orders "
        "ON orders.exchange_account_id = closed_pnl_records.exchange_account_id AND "
        "orders.exchange_order_id = closed_pnl_records.exchange_order_id WHERE "
        "closed_pnl_records.exchange_account_id = $1::UUID AND closed_pnl_records.final_at IS "
        "NULL AND closed_pnl_records.exchange_order_id IS NOT NULL AND "
        "closed_pnl_records.closed_at >= $2::TIMESTAMP WITH TIME ZONE AND "
        "orders.exchange_order_id IS NOT NULL ORDER BY closed_pnl_records.closed_at "
        "LIMIT $3::INTEGER"
    )
    assert pending[1] == {"exchange_account_id_1": _A, "closed_at_1": _T, "param_1": 5}
    flat = "position_snapshots.size = 0 AND position_snapshots.exchange_updated_ts IS NOT NULL"
    assert flats[0].startswith("SELECT DISTINCT position_snapshots.exchange_updated_ts FROM ")
    assert flats[0].count(flat) == 2 and "position_snapshots.exchange_updated_ts < $4" in flats[0]
    assert ">= (SELECT max(position_snapshots.exchange_updated_ts)" in flats[0]
    assert "FROM executions LEFT OUTER JOIN orders ON orders.id = executions.order_id" in fills[0]
    assert "(executions.exec_ts, executions.exec_id) > ($3" in fills[0]
    assert "executions.exec_ts > $3" in first[0]
    assert "(orders.position_idx = $5::SMALLINT OR orders.id IS NULL)" in fills[0]
    assert fills[0].endswith("ORDER BY executions.exec_ts, executions.exec_id LIMIT $6::INTEGER")
    assert fills[1]["exec_type_1"] == ["Trade", "AdlTrade", "BustTrade"]


def test_the_compositions_reads_name_the_account_and_scope_the_leg_to_the_fills_own() -> None:
    """C-12.4 on rows 58, 61 and 62 (E29-S06 slice 5b): every table each reads is filtered on the
    account, and row 58's leg on the fill's own account in the join, so another account's leg
    names no group and drops no fill. Row 61 names its orders by id, venue id or both, each once
    (a `UNION` of an arm per key), reads each order's fill times in `ix_exec_order`'s order,
    correlated to that order alone, and writes the partial indexes' predicates as literals
    (`ux_orders_exch_id`, `ix_psnap_flat`, `ux_cpr_order`)."""
    fills = _sql(mod.walk_fills_statement(_A, "SOLUSDT", 1, FillKey(_T), 5))[0]
    assert (
        "trade_group_legs.trade_group_id AS order_group_id FROM executions LEFT OUTER JOIN orders "
        "ON orders.id = executions.order_id LEFT OUTER JOIN trade_group_legs ON "
        "trade_group_legs.id = orders.trade_group_leg_id AND trade_group_legs.exchange_account_id "
        "= executions.exchange_account_id WHERE executions.exchange_account_id = $1::UUID"
    ) in fills
    both, ids, venue = (
        _sql(mod.anchors_statement(_A, *named))
        for named in (([_G], ["o-1"]), ([_G, _G], []), ([], ["o-1", "o-1"]))
    )
    for sql, params in (both, ids, venue):
        for table in ("orders", "executions", "position_snapshots", "closed_pnl_records"):
            assert f"{table}.exchange_account_id = $" in sql, table
        assert {v for k, v in params.items() if k.startswith("exchange_account_id")} == {_A}
        assert (
            "position_snapshots.size = 0 AND position_snapshots.exchange_updated_ts IS NOT " in sql
        )
        assert "closed_pnl_records.exchange_order_id IS NOT NULL AND " in sql
        assert "position_snapshots.exchange_updated_ts < times.first_fill" in sql
        assert sql.count("executions.order_id = named.id") == 3 and "executions, (" not in sql
        assert sql.endswith(") AS times ON true ORDER BY named.id")
    by_id, by_venue = (
        "FROM orders WHERE orders.exchange_account_id = $3::UUID AND orders.id IN ($",
        "orders.exchange_order_id IS NOT NULL AND orders.exchange_order_id IN ($",
    )
    assert by_id in both[0] and " UNION SELECT orders.id AS id, " in both[0]
    assert by_venue in both[0] and both[0].index(by_id) < both[0].index(by_venue)
    assert by_id in ids[0] and " UNION " not in ids[0] and by_venue not in ids[0]
    assert by_venue in venue[0] and " UNION " not in venue[0] and "orders.id IN" not in venue[0]
    assert (ids[1]["id_1"], venue[1]["exchange_order_id_1"]) == ([_G], ["o-1"])  # each once
    for order in (
        "ORDER BY executions.exec_ts LIMIT $",
        "ORDER BY executions.exec_ts DESC LIMIT",
        "AND executions.closed_size > $10::INTEGER ORDER BY executions.exec_ts DESC",
    ):
        assert order in both[0], order  # fmt: skip
    assert _sql(mod.hedge_statement(_A, "SOLUSDT")) == (
        "SELECT EXISTS (SELECT * FROM positions WHERE positions.exchange_account_id = $1::UUID AND "
        "positions.symbol = $2::VARCHAR AND positions.position_idx IN ($3::SMALLINT, "
        "$4::SMALLINT)) AS hedged",
        {"exchange_account_id_1": _A, "param_1": "SOLUSDT", "position_idx_1": [1, 2]},
    )


class _NoStatement:
    """A relational repository that a refusal never reaches: any unit of work fails the test."""

    def unit_of_work(self) -> Any:
        raise AssertionError("a statement ran")


@pytest.mark.parametrize(
    "window", [{}, {"since": _T}, {"until": _T}], ids=["none", "since", "until"]
)
async def test_totals_without_both_ends_of_their_window_are_refused_before_any_statement(
    window: dict[str, Any],
) -> None:
    """22 serves totals for a window only, and a sum over the accounts' whole history is no read
    its caller bounds (C-2.18): `TotalsUnbounded`, before any unit of work."""
    store = mod.SqlAlchemyClosedPnlStore(cast(Any, _NoStatement()))  # structural fake
    with pytest.raises(TotalsUnbounded, match="since and until"):
        await store.totals(ClosedPnlQuery(accounts=(_A,), **window))
    require_window(ClosedPnlQuery(accounts=(_A,), since=_T, until=_T + timedelta(days=1)))


def _store(relational: Any) -> mod.SqlAlchemyClosedPnlStore:
    return mod.SqlAlchemyClosedPnlStore(cast(Any, relational))  # structural fake


#: Each read but the totals, called with a limit and a time to try, its other arguments valid.
_READS: dict[str, Callable[[mod.SqlAlchemyClosedPnlStore, int, datetime], Awaitable[object]]] = {
    "page": lambda s, limit, _at: s.page(ClosedPnlQuery(accounts=(_A,)), None, limit),
    "pending": lambda s, limit, at: s.pending(_A, at, limit),
    "walk_flats": lambda s, limit, at: s.walk_flats(_A, "SOLUSDT", 0, at, limit),
    "walk_fills": lambda s, limit, at: s.walk_fills(_A, "SOLUSDT", 0, FillKey(at), limit),
}


@pytest.mark.parametrize("limit", [0, True], ids=["zero", "bool"])
@pytest.mark.parametrize("read", list(_READS))
async def test_a_read_whose_limit_is_no_int_of_at_least_1_is_refused_before_any_statement(
    read: str, limit: int
) -> None:
    """C-2.18: a read's rows are bounded by an int of at least 1, and `True` is no 1. The upper
    bounds (the limit, 25 accounts, 2 to 32 groups, the symbols) are the route's, S6's."""
    with pytest.raises(ValueError, match=r"^limit must be an int of at least 1$"):
        await _READS[read](_store(_NoStatement()), limit, _T)


@pytest.mark.parametrize(
    ("read", "column"), [("pending", "reach"), ("walk_flats", "before"), ("walk_fills", "after")]
)
async def test_a_read_from_a_naive_time_is_refused_before_any_statement(
    read: str, column: str
) -> None:
    """The time a read starts from is aware, as every stored one is. The page's keyset is not
    checked here, as `oms_reads_sqlalchemy.py`'s is not (#4997)."""
    with pytest.raises(ValueError, match=f"^{column} must be a timezone-aware datetime$"):
        await _READS[read](_store(_NoStatement()), 5, _T.replace(tzinfo=None))


async def test_the_anchors_of_no_order_run_no_statement() -> None:
    assert await _store(_NoStatement()).anchors(_A, [], []) == ()


@pytest.mark.parametrize("read", list(_READS))
async def test_a_read_of_one_row_from_an_aware_time_passes_its_guards(read: str) -> None:
    """The boundary: 1 is the smallest limit, and the read reaches the statement this fake fails."""
    with pytest.raises(AssertionError, match="a statement ran"):
        await _READS[read](_store(_NoStatement()), 1, _T)


class _Rows:
    """A statement's result as the store reads it: `mappings()`, then `one()` or `first()`."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _Rows:
        return self

    def one(self) -> dict[str, Any]:
        (row,) = self._rows
        return row

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _Recorder:
    """A relational repository that runs no SQL: each statement of its units of work with its
    parameters, in the order the store ran it (`ran`), each answered from `script` but the text
    clauses (the statement cap and the lock), and the commits."""

    def __init__(self, *script: list[dict[str, Any]]) -> None:
        self.script, self.ran, self.commits = list(script), list[tuple[Any, Any]](), 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: Any = None) -> _Rows:
            self.ran.append((stmt, params))
            return _Rows([] if isinstance(stmt, TextClause) else self.script.pop(0))

        async def commit() -> None:
            self.commits += 1

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _ran(rec: _Recorder) -> list[Any]:
    """What the store ran: the cap and the account's lock by name, each other as `_sql` has it."""
    return [
        "LOCK" if stmt is mod.LOCK else "cap" if isinstance(stmt, TextClause) else _sql(stmt)
        for stmt, _ in rec.ran
    ]


def test_the_lock_is_the_accounts_transaction_scoped_advisory_lock() -> None:
    assert str(mod.LOCK) == (
        "SELECT pg_advisory_xact_lock(hashtextextended('cv.closed_pnl_records:' || "
        "CAST(:account AS text), 0))"
    )


async def test_compose_takes_the_accounts_lock_after_the_cap_and_before_its_upsert() -> None:
    """Every write of an account waits for the one before (C-2.18: the cap bounds that wait)."""
    rec, record = _Recorder([_held()]), _composed(trade_group_id=_G)
    await _store(rec).compose(record)
    assert _ran(rec) == ["cap", "LOCK", _sql(mod.compose_statement(record))]
    assert rec.ran[1] == (mod.LOCK, {"account": str(_A)}) and rec.commits == 1


async def test_settle_takes_the_accounts_lock_before_it_reads_the_row_it_decides_on() -> None:
    """A venue read's outcome is decided on the row its write meets: the lock comes before the
    read of the held row, and the write follows it."""
    rec, venue = _Recorder([], [{"id": _venue().id}]), _venue()
    assert await _store(rec).settle(venue) == "inserted"
    read, write = _sql(mod.get_statement(_A, venue.id)), _sql(mod.settle_statement(venue))
    assert _ran(rec) == ["cap", "LOCK", read, write]
    assert rec.ran[1] == (mod.LOCK, {"account": str(_A)}) and rec.commits == 1


async def test_a_settle_that_changes_nothing_reads_under_the_lock_and_commits_nothing() -> None:
    rec, venue = _Recorder([_held()]), _venue()
    assert await _store(rec).settle(venue) == "unchanged"
    assert _ran(rec) == ["cap", "LOCK", _sql(mod.get_statement(_A, venue.id))]
    assert rec.ran[1] == (mod.LOCK, {"account": str(_A)}) and rec.commits == 0


@pytest.mark.parametrize("stamps", [True, False], ids=["stamped", "nothing-to-stamp"])
async def test_finalize_takes_the_accounts_lock_before_its_update(stamps: bool) -> None:
    rec, rid = _Recorder([{"id": _venue().id}] if stamps else []), _venue().id
    assert await _store(rec).finalize(_A, rid) is stamps
    assert _ran(rec) == ["cap", "LOCK", _sql(mod.finalize_statement(_A, rid))]
    assert rec.ran[1] == (mod.LOCK, {"account": str(_A)}) and rec.commits == int(stamps)


@pytest.mark.parametrize("stamps", [True, False], ids=["written", "no-row"])
async def test_the_flag_and_its_clear_take_the_accounts_lock_before_their_update(
    stamps: bool,
) -> None:
    """E29-S06 slice 5c (24 Sec.8.13): the flag sets `divergent` with the pair its record names on
    a settled row of the account, final or not; the clear keeps the pair; each commits only when
    it met a row (`cpr_pair` is the backstop)."""
    rid, pair = _venue().id, (Decimal("-49.275"), Decimal("-47.4065323"))
    flag, clear = mod.mark_statement(_A, rid, *pair), mod.clear_statement(_A, rid)
    for kind, stmt in (("flag", flag), ("clear", clear)):
        rec = _Recorder([{"id": rid}] if stamps else [])
        store = _store(rec)
        wrote = await (
            store.mark_divergent(_A, rid, *pair)
            if kind == "flag"
            else store.clear_divergent(_A, rid)
        )
        assert wrote is stamps
        assert _ran(rec) == ["cap", "LOCK", _sql(stmt)] and rec.commits == int(stamps)
    where = (
        "WHERE closed_pnl_records.exchange_account_id = $4::UUID AND closed_pnl_records.id = "
        "$5::UUID AND closed_pnl_records.settled_at IS NOT NULL RETURNING closed_pnl_records.id"
    )
    sql, params = _sql(flag)
    assert sql.startswith("UPDATE closed_pnl_records SET divergent=$1::BOOLEAN, audited_local_net")
    assert sql.endswith(where) and "final_at" not in sql
    assert (params["audited_local_net"], params["audited_closed_pnl"]) == pair
    sql, _ = _sql(clear)
    assert "audited" not in sql and sql.endswith(
        "WHERE closed_pnl_records.exchange_account_id = $2::UUID AND closed_pnl_records.id = "
        "$3::UUID AND closed_pnl_records.divergent RETURNING closed_pnl_records.id"
    )
