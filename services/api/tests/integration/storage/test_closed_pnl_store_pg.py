"""Integration: the closed-PnL store on Postgres 16 (E29-S06 #981 slice 2; 21 Sec.3.3.13): it
composes, settles once, replaces until final and freezes, the group the composition's alone; it
pages each account both ways and merges, totals in SQL, both leaving out a record at the window's
end, serves and counts an item with no figure and filters on the symbol and the stored group; and
rows 55 to 59 read what 21 Sec.13.1 says through the indexes they name. The revision's own:
`test_closed_pnl_records_migration.py`, whose fixture and helpers this module shares."""

from __future__ import annotations

import random
import uuid
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

from candleviewer.storage.repositories import closed_pnl_sqlalchemy as cpr
from candleviewer.storage.repositories.closed_pnl import ClosedPnlQuery as Query
from candleviewer.storage.repositories.closed_pnl import ComposedRecord, FillKey, VenueRecord
from candleviewer.storage.repositories.oms_reads import Keyset
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.integration.storage.test_closed_pnl_records_migration import (
    _S,
    _SETTLED,
    _T0,
    _alembic,
    _conn,
    _fresh,
    _group,
    _put,
    pg_dsn,
)

pytestmark = pytest.mark.integration
__all__ = ["pg_dsn"]  # the shared module-scoped fixture


def _record(kind: type[Any], account: UUID, **over: Any) -> Any:
    """A `ComposedRecord` or a `VenueRecord` of the account's order `o-1`."""
    values: dict[str, Any] = {"exchange_account_id": account, "exchange_order_id": "o-1"}
    values |= {"symbol": "SOLUSDT", "side": "long", "closed_at": _T0, "qty": Decimal(4)}
    if kind is ComposedRecord:
        return ComposedRecord(**(values | {"gross_pnl": Decimal("10.8")} | over))
    values |= {"avg_entry_price": Decimal("148.1"), "avg_exit_price": Decimal("150.8")}
    values |= {"leverage": Decimal(3), "closed_pnl": Decimal(10), "venue_created_at": _T0}
    return VenueRecord(**(values | over))  # fmt: skip


async def test_the_store_composes_settles_once_replaces_until_final_then_freezes(
    pg_dsn: str,
) -> None:
    """`trade_group_id` is the composition's alone: settling never writes it, and a later walk
    rewrites it at any stage, the record final or not (21 Sec.3.3.13)."""
    with _conn(pg_dsn) as c:
        a, b = _put(c, "exchange_accounts"), _put(c, "exchange_accounts")
        group, regrouped = _group(c), _group(c)
    rel = SqlAlchemyRelationalRepository(pg_dsn, "closed-pnl-it")
    store, venue = cpr.SqlAlchemyClosedPnlStore(rel), _record(VenueRecord, a)
    try:
        row = await store.compose(_record(ComposedRecord, a, trade_group_id=group))
        assert (row.id, row.settled_at, row.qty, row.gross_pnl, row.trade_group_id) == (
            venue.id, None, 4, Decimal("10.8"), group,
        )  # fmt: skip
        row = await store.compose(_record(ComposedRecord, a, qty=Decimal(5)))
        assert (row.qty, row.trade_group_id) == (5, None)  # a walk naming none, or several
        assert await store.settle(venue) == "settled"
        later = _record(ComposedRecord, a, qty=Decimal(9), closed_at=_T0 + _S, fee_pnl=Decimal(-1),
                        trade_group_id=group)  # fmt: skip
        row = await store.compose(later)  # a settled row keeps the venue's columns
        assert (row.qty, row.closed_at, row.fee_pnl, row.closed_pnl) == (4, _T0, -1, 10)
        assert await store.settle(venue) == "unchanged"
        assert await store.settle(_record(VenueRecord, a, qty=Decimal(10))) == "replaced"
        assert not await store.finalize(b, venue.id) and await store.finalize(a, venue.id)
        assert not await store.finalize(a, venue.id) and await store.get(b, venue.id) is None
        assert await store.settle(_record(VenueRecord, a, closed_pnl=Decimal(11))) == "frozen"
        async with rel.unit_of_work() as uow:  # the upsert itself leaves a final row as it is
            stmt = cpr.settle_statement(_record(VenueRecord, a, qty=Decimal(1)))
            assert (await uow.session.execute(stmt)).first() is None
        final = await store.get(a, venue.id)
        assert final is not None and (final.qty, final.closed_pnl, final.fee_pnl) == (10, 10, -1)
        assert final.trade_group_id == group  # settling, replacing and finalising kept it
        final = await store.compose(replace(later, trade_group_id=regrouped))  # a later walk's
        assert final.final_at is not None and (final.qty, final.trade_group_id) == (10, regrouped)
        orderless = _record(VenueRecord, a, exchange_order_id=None)
        assert await store.settle(orderless) == "inserted"
        held = await store.get(a, orderless.id)
        assert held is not None and held.trade_group_id is None  # settling never writes it
        assert not await store.finalize(a, orderless.id)  # never final (cpr_final)
    finally:
        await rel.dispose()


async def test_the_reads_page_both_ways_total_in_sql_and_read_rows_56_to_58(pg_dsn: str) -> None:
    until = _T0 + timedelta(days=1)  # the window's end, which neither its page nor totals read
    with _conn(pg_dsn) as c:
        a, b = sorted((_put(c, "exchange_accounts"), _put(c, "exchange_accounts")))
        g1, g2 = _group(c), _group(c)

        def put(table: str, account: UUID = a, **cols: Any) -> Any:
            return _put(c, table, account, **cols)

        settled = put("closed_pnl_records", **_SETTLED | {"closed_pnl": 25, "trade_group_id": g1})
        provisional = put("closed_pnl_records", exchange_order_id="o-2", closed_at=_T0 + 60 * _S,
                          gross_pnl=Decimal("-6.2"), fee_pnl=Decimal("-0.71"),
                          trade_group_id=g2)  # fmt: skip
        bare = put("closed_pnl_records", exchange_order_id="o-3", closed_at=_T0 + 30 * _S)
        edge = put("closed_pnl_records", exchange_order_id="o-4", closed_at=until, gross_pnl=5)
        btc = put("closed_pnl_records", exchange_order_id="o-5", symbol="BTCUSDT",
                  closed_at=_T0 + 45 * _S, gross_pnl=7)  # fmt: skip
        other = put(
            "closed_pnl_records", b, **_SETTLED | {"closed_at": _T0 + _S, "trade_group_id": g1}
        )
        order = put("orders", exchange_order_id="o-2")
        filled = put("orders", exchange_order_id="o-1")
        put("closed_pnl_records", exchange_order_id="o-9", closed_at=_T0 - timedelta(days=8),
            gross_pnl=1)  # fmt: skip
        put("orders", exchange_order_id="o-9")  # past the poll's reach
        for at, size in ((_T0, 0), (_T0 + 60 * _S, 1), (_T0 + 120 * _S, 0), (None, 0)):
            put("position_snapshots", exchange_updated_ts=at, size=size)  # None: no venue time
        # a reconciliation's copy of the flat at _T0: the walk reads its venue time once
        put("position_snapshots", exchange_updated_ts=_T0, size=0, reason="rest_reconcile")
        hedge = put("orders", exchange_order_id="o-h", position_idx=1)
        put("executions", exec_id="e1", order_id=order, closed_size=1)  # at the flat: before it
        put("executions", exec_id="e2", order_id=order, exec_ts=_T0 + _S, closed_pnl=2)
        put("executions", exec_id="e3", exec_ts=_T0 + _S)  # no order row: the walk sees it
        put("executions", exec_id="e4", order_id=hedge, exec_ts=_T0 + 2 * _S)  # the other key
        put("executions", exec_id="e5", exec_ts=_T0 + 3 * _S, exec_type="Funding")
    rel = SqlAlchemyRelationalRepository(pg_dsn, "closed-pnl-reads-it")
    store = cpr.SqlAlchemyClosedPnlStore(rel)
    try:
        query = Query(accounts=(a, b), symbols=("SOLUSDT",), since=_T0, until=until)  # not btc
        page = await store.page(query, None, 2)  # each account's first two, merged
        assert [(i.row.id, i.net_pnl) for i in page] == [(settled, 25), (other, 8)]
        # the rest of the window, room to spare: not edge (at `until`), not btc (another symbol)
        rest = await store.page(query, Keyset(page[-1].row.closed_at, page[-1].row.id), 3)
        assert [(i.row.id, i.net_pnl) for i in rest] == [
            (bare, None), (provisional, Decimal("-6.91")),
        ]  # fmt: skip
        # no window and no symbol: `edge` and `btc` are stored and read, the filters leave them out
        newest = await store.page(Query(accounts=(a, b), oldest_first=False), None, 5)
        assert [i.row.id for i in newest] == [edge, provisional, btc, bare, other]
        totals = await store.totals(query)  # the item with no figure counts, provisional; not edge
        assert (totals.count, totals.net_pnl, totals.provisional) == (4, Decimal("26.09"), True)
        by_account = [(t.exchange_account_id, t.count, t.net_pnl) for t in totals.by_account]
        assert by_account == [(a, 3, Decimal("18.09")), (b, 1, 8)]
        grouped = replace(query, trade_groups=(g1,))  # a NULL group is in no group's (row 59)
        assert [i.row.id for i in await store.page(grouped, None, 5)] == [settled, other]
        both = await store.totals(replace(grouped, trade_groups=(g2, g1)))
        assert (both.count, both.net_pnl, both.provisional) == (3, Decimal("26.09"), True)
        none = await store.totals(replace(query, accounts=(a,), side="short"))
        assert (none.count, none.net_pnl, none.provisional, none.by_account) == (0, 0, False, ())
        polled = await store.pending(a, _T0 - timedelta(days=7), 10)  # not final, with a row
        assert [(p.row.id, p.order_id) for p in polled] == [(settled, filled), (provisional, order)]
        assert await store.walk_flats(a, "SOLUSDT", 0, _T0 + _S, 5) == (_T0, _T0 + 120 * _S)
        assert await store.walk_flats(a, "SOLUSDT", 0, _T0, 5) == ()  # no flat before: no walk
        fills = await store.walk_fills(a, "SOLUSDT", 0, FillKey(_T0), 5)
        assert [(f.exec_id, f.order_position_idx, f.order_exchange_id) for f in fills] == [
            ("e2", 0, "o-2"), ("e3", None, None),
        ]  # fmt: skip
        assert (fills[0].closed_pnl, fills[0].closed_size) == (2, None)
        after = await store.walk_fills(a, "SOLUSDT", 1, FillKey(_T0 + _S, "e2"), 5)
        assert [f.exec_id for f in after] == ["e3", "e4"]
    finally:
        await rel.dispose()


def test_rows_56_to_58_plan_over_the_indexes_they_name(pg_dsn: str) -> None:
    """EXPLAIN of each store read as asyncpg runs it, a prepared statement on its generic plan,
    sequential scans priced out (the `test_orders_store_pg.py` probe). Rows 55 and 59 read
    seeded, analysed records below.

    Row 56's pick of `ix_cpr_pending` over `ix_cpr_day`, which gives the poll's `closed_at` order
    too, is no cost win here: the tables are never analysed, empty when this probe runs alone and
    holding the reads test's rows after it, and there the two cost the same, or `ix_cpr_pending`
    is ahead only for being empty; a tie goes to the index the planner costs first, the one built
    later. So the probe relies on the order revision 0070 creates the indexes in and on the state
    the tables are in. It catches a dropped or renamed index, a partial predicate the planner
    cannot prove and an order the index does not give; it does not catch a regression under real
    statistics, where `ix_cpr_pending` holds the unfinished records alone."""
    a, dialect = uuid.uuid4(), make_url("postgresql+asyncpg://").get_dialect()()
    for stmt, indexes in (
        (cpr.pending_statement(a, _T0, 5), ("ix_cpr_pending", "ux_orders_exch_id")),
        (cpr.walk_flats_statement(a, "SOLUSDT", 0, _T0, 5), ("ix_psnap_flat",)),
        (cpr.walk_fills_statement(a, "SOLUSDT", 0, FillKey(_T0, "e"), 5),
         ("ix_exec_walk", "orders_pkey")),
    ):  # fmt: skip
        compiled = stmt.compile(dialect=dialect, compile_kwargs={"render_postcompile": True})
        args = sql.SQL(", ").join(
            map(sql.Literal, map(compiled.params.get, compiled.positiontup or ()))
        )
        with psycopg.connect(pg_dsn.replace("+asyncpg", "")) as c, c.transaction():
            c.execute("SET LOCAL enable_seqscan = off")
            c.execute("SET LOCAL plan_cache_mode = force_generic_plan")
            c.execute(sql.SQL("PREPARE probe AS {}").format(sql.SQL(str(compiled))))
            rows = c.execute(sql.SQL("EXPLAIN EXECUTE probe ({})").format(args)).fetchall()
            plan = "\n".join(str(row[0]) for row in rows)
        print(f"\n--- {', '.join(indexes)}\n{plan}")  # the PR's evidence (`-s`)
        assert all(index in plan for index in indexes), plan


_RECORDS, _SPREAD, _PAGE = 4_000, 300, 101  # one account's day, its groups, a route's page read


def _plan(dsn: str, stmt: Any) -> tuple[list[dict[str, Any]], str]:
    """`stmt`'s executed plan (`EXPLAIN ANALYZE`, as `test_oms_reads_pg.py` reads it, #4997): its
    nodes, and its text for the PR."""
    dialect = make_url("postgresql+psycopg://").get_dialect()()
    compiled = stmt.compile(dialect=dialect, compile_kwargs={"render_postcompile": True})
    with _conn(dsn) as c:
        [(plan,)] = c.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + str(compiled), compiled.params)
        text = c.execute(
            "EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF, SUMMARY OFF) " + str(compiled),
            compiled.params,
        ).fetchall()
    nodes: list[dict[str, Any]] = []
    pending = [plan[0]["Plan"]]
    while pending:
        nodes.append(node := pending.pop())
        pending += node.get("Plans", [])
    return nodes, "\n".join(str(row[0]) for row in text)


def test_rows_55_and_59_read_their_indexes_and_never_sort_every_record(pg_dsn: str) -> None:
    """#4997's probe on the test's own database, analysed: one account's day of 4,000 records
    over 300 groups and none, spread by a fixed seed, and two groups holding a handful. A page
    reads `ix_cpr_day` alone, in order from its place either way, and sorts at most a page per
    account (row 55); a page and the totals of the two groups read `ix_cpr_group` and sort no
    more than those groups' records (row 59), where `ix_cpr_day` read in order would walk the
    whole day (#5037)."""
    dsn = _fresh(pg_dsn)
    rng = random.Random(981)  # noqa: S311 -- a fixed seed for a reproducible population (#981)
    assert _alembic(dsn, "upgrade", "head").returncode == 0
    groups = [uuid.UUID(int=rng.getrandbits(128)) for _ in range(_SPREAD + 2)]
    probed, spread = groups[:2], groups[2:]
    picks = [None if rng.random() < 0.25 else rng.choice(spread) for _ in range(_RECORDS)]
    for n in range(6):  # three records of each probed group, across the day
        picks[(2 * n + 1) * _RECORDS // 12] = probed[n % 2]
    with _conn(dsn) as c:
        bulk, other = (_put(c, "exchange_accounts", id=uuid.UUID(int=n)) for n in (1, 2))
        user = uuid.UUID(int=3)
        c.execute(
            "INSERT INTO users (id, email, username, password_hash) VALUES (%s, %s, %s, "
            "'$argon2id$x')", (user, "probe@example.test", "u_probe"),
        )  # fmt: skip
        c.execute(
            "INSERT INTO trade_groups (id, client_group_ref, client_body_sha256, created_by, env, "
            "symbol, side) SELECT g, g::text, repeat('ab', 32), %s, 'demo', 'SOLUSDT', 'Buy' "
            "FROM unnest(%s::uuid[]) AS g", (user, groups),
        )  # fmt: skip
        c.execute(
            "INSERT INTO closed_pnl_records (id, exchange_account_id, exchange_order_id, symbol, "
            "side, closed_at, trade_group_id, qty, gross_pnl) SELECT md5('cpr' || n)::uuid, %s, "
            "'o-' || n, 'SOLUSDT', 'long', %s + n * interval '10 seconds', g, 1, 1 "
            "FROM unnest(%s::uuid[]) WITH ORDINALITY AS t(g, n)", (bulk, _T0, picks),
        )  # fmt: skip
        for n, group in enumerate((*probed, None, spread[0])):  # the other account's handful
            _put(c, "closed_pnl_records", other, id=uuid.UUID(int=n + 1), trade_group_id=group,
                 exchange_order_id=f"x-{n}", closed_at=_T0 + (997 * n + 5) * _S)  # fmt: skip
        c.execute("ANALYZE closed_pnl_records")
    until, held = _T0 + timedelta(days=1), 8  # the day's end; the probed groups' records
    accounts, mid = (bulk, other), Keyset(_T0 + _RECORDS // 2 * 10 * _S, uuid.UUID(int=0))
    day = Query(accounts=accounts, since=_T0, until=until)
    grouped = replace(day, trade_groups=tuple(probed))
    newest = replace(day, since=None, until=None, oldest_first=False)
    for name, stmt, index, most in (
        ("a window's page", cpr.page_statement(day, None, _PAGE), "ix_cpr_day", 2 * _PAGE),
        ("newest first from mid-day", cpr.page_statement(newest, mid, _PAGE), "ix_cpr_day",
         2 * _PAGE),
        ("two groups' page", cpr.page_statement(grouped, None, _PAGE), "ix_cpr_group", held),
        ("two groups' totals", cpr.totals_statement(grouped), "ix_cpr_group", held),
    ):  # fmt: skip
        nodes, text = _plan(dsn, stmt)
        print(f"\n--- {name}: {index}\n{text}")  # the PR's evidence (`-s`)
        assert {n["Index Name"] for n in nodes if "Index Name" in n} == {index}, text
        assert not [n for n in nodes if n["Node Type"] == "Seq Scan"], text
        scans = [n for n in nodes if n.get("Index Name") == index]
        if index == "ix_cpr_day":  # in order, each loop stopping near a page
            assert all(n["Node Type"] in ("Index Scan", "Index Only Scan") for n in scans), text
            assert all(int(n["Actual Rows"]) <= _PAGE + 2 for n in scans), text
        else:  # the two groups' records alone
            assert sum(int(n["Actual Rows"]) * int(n["Actual Loops"]) for n in scans) <= held, text
        for sort in (n for n in nodes if n["Node Type"] in ("Sort", "Incremental Sort")):
            [child] = sort["Plans"]
            assert int(child["Actual Rows"]) * int(child["Actual Loops"]) <= most, text
