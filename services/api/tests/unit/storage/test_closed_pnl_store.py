"""The closed-PnL store without a database (E29-S06 #981 slice 2; 21 Sec.3.3.13): the records' ids
and refusals before any statement, a venue read's outcome, and each statement's shape and bound
parameters. Real SQL: `tests/integration/storage/test_closed_pnl_store_pg.py`."""

from __future__ import annotations

import re
import uuid
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid5

import pytest
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
    row: dict[str, Any] = dict.fromkeys(f.name for f in fields(ClosedPnlRecordRow))
    row |= {name: getattr(_venue(), name) for name in mod.VENUE_COLUMNS} | {"settled_at": _T}
    held_row = None if held is None else ClosedPnlRecordRow(**(row | held))
    assert settle_outcome(held_row, _venue(**read)) == outcome
    assert [f.name for f in fields(ClosedPnlRecordRow)] == list(models.closed_pnl_records.c.keys())


def test_each_statement_names_its_account_and_keeps_its_writers_and_readers_apart() -> None:
    """C-12.4 on every statement. The composition writes its figures and `trade_group_id` always
    and the provisional columns only unsettled; a venue read, the venue's columns and `settled_at`
    once, never on a final row and never the group; `finalize`, once. A page reads each account
    on its own (`LATERAL`) either way from its keyset and merges, serves an item with no figure and
    has `net_pnl` from the totals' expression; the group filter matches the stored column, and the
    page and the totals read the window from `since` up to, not at, `until`. Rows 56 and 57 write
    the predicates of their partial indexes (`ix_cpr_pending`, `ix_psnap_flat`) as literals,
    which a generic plan can prove, and bind the rest; row 58's `ix_exec_walk` is not partial.
    The poll is pinned whole, its inner join included, in the `closed_at` order alone that
    `ix_cpr_pending` gives, and the flats read each venue time once."""
    query = ClosedPnlQuery(
        accounts=(_B, _A, _A), symbols=("SOLUSDT",), trade_groups=(_G, _G), side="short",
        since=_T, until=_T + timedelta(days=1),
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
    window = ("closed_pnl_records.closed_at >= ${}::TIMESTAMP WITH TIME ZONE AND "
              "closed_pnl_records.closed_at < ${}::TIMESTAMP WITH TIME ZONE")  # fmt: skip
    for (sql, params), sign, order in ((ascending, ">", ""), (descending, "<", " DESC")):
        assert sql.startswith("SELECT page.id, page.exchange_account_id, ")
        assert ("FROM (VALUES ($1::UUID), ($2::UUID)) AS accounts (account_id) JOIN LATERAL "
                "(SELECT closed_pnl_records.id AS id, ") in sql  # fmt: skip
        assert f"{net} AS net_pnl FROM closed_pnl_records WHERE closed_pnl_records." in sql
        assert "exchange_account_id = accounts.account_id AND " in sql and group in sql
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
