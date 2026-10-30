"""Integration (E29-T07 #915, PR 1): `SqlAlchemyOmsReads` on Postgres 16, as `cv_app`, over the E28
seed world (`test_trade_group_definitions_store_pg.py`'s database: the Owner, demo accounts A =
d1, B = d3, the live account f1) with a Manager granted A to view and a Viewer granted none.

It proves the SQL itself: the scope held in every statement ("Scope is enforced server-side":
B's rows reach a grant under no filter combination, a named B refuses the whole read, a foreign
id reads as missing), the environment ("Aggregate positions never mix environments": a demo
store never reads the live account, an Owner's included), the keyset over every row once, the
filters, `listClosedPnl`'s interim source, and #915's performance note: `GET /orders?open_only`
and `GET /positions` at 1,000 orders, p95 under 150 ms (the store's statements, without HTTP)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects.postgresql import psycopg as pg_psycopg

from candleviewer.oms.reads import aggregate_positions
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope
from candleviewer.storage.repositories.oms_reads import (
    ExecutionQuery,
    Keyset,
    OrderDetail,
    OrderQuery,
    PositionOutOfScope,
    PositionQuery,
)
from candleviewer.storage.repositories.oms_reads_sqlalchemy import (
    SqlAlchemyOmsReads,
    executions_statement,
    orders_statement,
)
from candleviewer.storage.repositories.orders import AccountsOutOfScope, OutOfScope
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.integration.storage import test_trade_groups_store_pg as tg
from tests.integration.storage.test_trade_group_definitions_store_pg import (
    LIVE,
    OWNER,
    A,
    bootstrapped,
    pg_dsn,
)
from tests.integration.storage.test_trade_group_definitions_store_pg import B as BULK_1
from tests.integration.storage.test_trade_group_definitions_store_pg import C as B
from tests.integration.storage.test_trade_groups_store_pg import rel

pytestmark = pytest.mark.integration
__all__ = ["bootstrapped", "pg_dsn", "rel"]

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
LEG_A = UUID("e28f0000-0000-4000-8000-0000000000e1")  # group b1's leg on A
GROUP = UUID("e28f0000-0000-4000-8000-0000000000b1")
_ORDER = (
    "INSERT INTO orders (id, exchange_account_id, order_link_id, symbol, side, intent, order_type,"
    " qty, price, state, created_ts, trade_group_leg_id) VALUES (%s, %s, %s, %s, 'Buy', %s, "
    "'Limit', 0.5, 63000, %s, %s, %s)"
)
_FILL = (
    "INSERT INTO executions (id, order_id, exchange_account_id, exec_id, symbol, side, exec_qty, "
    "exec_price, exec_value, exec_type, is_maker, exec_ts, closed_pnl) VALUES (%s, %s, %s, %s, "
    "'BTCUSDT', %s, 0.1, 63000, 6300, 'Trade', false, %s, %s)"
)
_POSITION = (
    "INSERT INTO positions (id, exchange_account_id, symbol, side, size, avg_price, stop_loss) "
    "VALUES (%s, %s, 'BTCUSDT', %s, %s, %s, 60000)"
)


def _order(dsn: str, account: UUID, n: int, **over: object) -> UUID:
    oid = uuid4()
    row = {"symbol": "BTCUSDT", "intent": "entry", "state": "accepted", "leg": None} | over
    tg._sql(
        dsn, _ORDER, oid, account, f"ext-{oid.hex}", row["symbol"], row["intent"], row["state"],
        T0 + timedelta(seconds=n), row["leg"],
    )  # fmt: skip
    return oid


@pytest.fixture(scope="module")
def world(pg_dsn: str) -> Iterator[dict[str, object]]:
    """The module's rows (module docstring): orders on A (one in group b1), B and LIVE, a fill
    with a closed PnL on each, and B's and LIVE's BTCUSDT positions beside the seed's on A."""
    manager, viewer = tg._user(pg_dsn, "manager"), tg._user(pg_dsn, "viewer")
    tg._sql(
        pg_dsn, "INSERT INTO user_account_access (user_id, exchange_account_id, can_view, "
        "can_trade) VALUES (%s, %s, true, false)", manager, A,
    )  # fmt: skip
    a1 = _order(pg_dsn, A, 1, leg=LEG_A)
    a2 = _order(pg_dsn, A, 2, state="filled", intent="scale_in")
    a3 = _order(pg_dsn, A, 3, symbol="ETHUSDT", state="held")
    b1, live = _order(pg_dsn, B, 4), _order(pg_dsn, LIVE, 5)
    for n, (order, account, side) in enumerate(
        [(a1, A, "Buy"), (a2, A, "Sell"), (b1, B, "Sell"), (live, LIVE, "Sell")]
    ):
        pnl = None if n == 0 else Decimal(n)
        tg._sql(
            pg_dsn, _FILL, uuid4(), order, account, f"E{n}", side, T0 + timedelta(minutes=n), pnl
        )
    tg._sql(pg_dsn, _POSITION, uuid4(), B, "Sell", Decimal("0.004"), Decimal("64000"))
    tg._sql(pg_dsn, _POSITION, uuid4(), LIVE, "Buy", Decimal(7), Decimal(1))
    yield {"manager": manager, "viewer": viewer, "a1": a1, "a2": a2, "a3": a3, "b1": b1,
           "live": live, "dsn": pg_dsn}  # fmt: skip


@pytest.fixture
def store(rel: SqlAlchemyRelationalRepository) -> SqlAlchemyOmsReads:
    return SqlAlchemyOmsReads(rel, statement_timeout_ms=10_000)


def _grant(world: dict[str, object]) -> GrantScope:
    manager = world["manager"]
    assert isinstance(manager, UUID)
    return GrantScope(manager, frozenset({A, B}))  # a stale snapshot naming B: SQL narrows it


async def _orders(store: SqlAlchemyOmsReads, scope: object, **query: object) -> list[UUID]:
    found = await store.orders(
        scope,
        OrderQuery(**query),
        environment="demo",
        after=None,
        limit=500,  # type: ignore[arg-type]  # a scope or filters the test names untyped
    )
    return [listed.order.id for listed in found]


async def test_scope_is_enforced_server_side_no_filter_combination_reaches_b(
    store: SqlAlchemyOmsReads, world: dict[str, object]
) -> None:
    """Gherkin "Scope is enforced server-side", in SQL: a grant on A reads A's rows only, its
    stale snapshot naming B included, under every filter combination; a named B refuses the
    whole read; another environment is never read."""
    scope = _grant(world)
    combos: list[dict[str, object]] = [
        {}, {"symbol": "BTCUSDT"}, {"states": frozenset({"accepted"})},
        {"intents": frozenset({"entry"})}, {"open_only": True}, {"trade_group_id": GROUP},
        {"since": T0, "until": T0 + timedelta(hours=1)}, {"accounts": (A,)},
    ]  # fmt: skip
    for combo in combos:
        assert world["b1"] not in await _orders(store, scope, **combo), combo
        assert world["live"] not in await _orders(store, scope, **combo), combo
    first_hour = T0 + timedelta(hours=1)  # this module's rows, not the 1,000 of the perf test
    assert set(await _orders(store, scope, until=first_hour)) == {
        world["a1"], world["a2"], world["a3"],
    }  # fmt: skip
    for named in ((B,), (A, B), (uuid4(),), (LIVE,)):
        with pytest.raises(AccountsOutOfScope):
            await _orders(store, scope, accounts=named)
    fills = await store.executions(
        scope,
        ExecutionQuery(order_id=world["b1"]),
        environment="demo",
        after=None,
        limit=50,  # type: ignore[arg-type]  # the module's order id, read untyped
    )
    assert fills == ()


async def test_a_foreign_or_other_environment_id_reads_as_missing_naming_its_holder(
    store: SqlAlchemyOmsReads, world: dict[str, object]
) -> None:
    scope = _grant(world)
    b1, a1 = world["b1"], world["a1"]
    assert isinstance(b1, UUID) and isinstance(a1, UUID)
    assert await store.order(scope, b1, environment="demo", events=True) == OutOfScope(B)
    assert await store.order(scope, uuid4(), environment="demo", events=True) == OutOfScope(None)
    owner = OwnerScope(OWNER)
    live = world["live"]
    assert isinstance(live, UUID)
    assert await store.order(owner, live, environment="demo", events=False) == OutOfScope(LIVE)
    found = await store.order(scope, a1, environment="demo", events=True)
    assert isinstance(found, OrderDetail) and found.scoped.trade_group_id == GROUP
    assert len(found.executions) == 1 and found.executions[0].trade_group_id == GROUP
    [b_position] = await store.positions(owner, PositionQuery(accounts=(B,)), environment="demo")
    assert await store.position(scope, b_position.id, environment="demo") == PositionOutOfScope(B)
    assert await store.position(owner, b_position.id, environment="demo") == b_position


async def test_aggregate_positions_never_mix_environments(
    store: SqlAlchemyOmsReads, world: dict[str, object]
) -> None:
    """Gherkin "Aggregate positions never mix environments", in SQL: an Owner's demo read holds
    A's and B's legs and never the live account's, so its aggregate sums one environment."""
    owner = OwnerScope(OWNER)
    rows = await store.positions(owner, PositionQuery(), environment="demo")
    assert {row.exchange_account_id for row in rows} == {A, B}
    [btc] = aggregate_positions(rows)
    assert {leg.account_id for leg in btc.legs} == {A, B}
    assert (btc.net_size, btc.gross_size) == (Decimal("-0.003"), Decimal("0.005"))
    live = await store.positions(owner, PositionQuery(), environment="live")
    assert {row.exchange_account_id for row in live} == {LIVE}


async def test_the_keyset_walks_every_row_once_newest_first(
    store: SqlAlchemyOmsReads, world: dict[str, object]
) -> None:
    owner, seen, after = OwnerScope(OWNER), list[UUID](), None
    query = OrderQuery(accounts=(A, B))
    while True:
        page = await store.orders(owner, query, environment="demo", after=after, limit=2)
        seen += [listed.order.id for listed in page]
        if len(page) < 2:
            break
        after = Keyset(page[-1].order.created_ts, page[-1].order.id)
    expected = [world[k] for k in ("b1", "a3", "a2", "a1")]
    assert [s for s in seen if s in expected] == expected and len(seen) == len(set(seen))


async def test_open_only_and_closed_pnl_read_their_sets(
    store: SqlAlchemyOmsReads, world: dict[str, object]
) -> None:
    scope = _grant(world)
    first_hour = T0 + timedelta(hours=1)
    open_ = await _orders(store, scope, open_only=True, until=first_hour)
    assert set(open_) == {world["a1"], world["a3"]}
    closed = await store.closed_pnl(
        scope, ExecutionQuery(), environment="demo", after=None, limit=9
    )
    assert [x.execution.closed_pnl for x in closed] == [Decimal(1)]  # A's one fill with a PnL


async def test_reads_at_a_thousand_orders_answer_within_150_ms_at_p95(
    pg_dsn: str, store: SqlAlchemyOmsReads, world: dict[str, object]
) -> None:
    """#915's performance note, the store's own time: `listOrders?open_only=true` and
    `listPositions` for an Owner and a Manager over 1,000 orders on A."""
    tg._sql(
        pg_dsn, "INSERT INTO orders (id, exchange_account_id, order_link_id, symbol, side, intent,"
        " order_type, qty, price, state, created_ts) SELECT gen_random_uuid(), %s, 'ext-' || "
        "md5(n::text), 'BTCUSDT', 'Buy', 'entry', 'Limit', 0.5, 63000, CASE WHEN n %% 3 = 0 THEN "
        "'accepted' ELSE 'filled' END::order_state, %s + n * interval '1 second' "
        "FROM generate_series(1, 1000) AS n", A, T0 + timedelta(days=1),
    )  # fmt: skip
    tg._sql(pg_dsn, "ANALYZE orders")
    timings: dict[str, list[float]] = {"orders": [], "positions": []}
    for scope, named in ((OwnerScope(OWNER), (A, B)), (_grant(world), (A,))):
        query = OrderQuery(open_only=True, accounts=named)  # not the EXPLAIN test's bulk accounts
        for _ in range(20):
            started = time.perf_counter()
            await store.orders(scope, query, environment="demo", after=None, limit=101)
            timings["orders"].append(time.perf_counter() - started)
            started = time.perf_counter()
            await store.positions(scope, PositionQuery(), environment="demo")
            timings["positions"].append(time.perf_counter() - started)
    for name, seconds in timings.items():
        p95 = sorted(seconds)[int(len(seconds) * 0.95) - 1]
        print(f"{name} p95 {p95 * 1000:.1f} ms")  # the PR's evidence (`-s`)
        assert p95 < 0.150, name


async def test_scope_is_enforced_server_side_a_forged_keyset_reaches_no_foreign_row(
    store: SqlAlchemyOmsReads, world: dict[str, object]
) -> None:
    """The cursor is no security boundary (its digest is unkeyed): a page started at B's row's
    position under a grant on A reads A's rows alone, as the scope is held in SQL (#4997)."""
    b1 = world["b1"]
    assert isinstance(b1, UUID)
    [(created,)] = tg._sql(store_dsn(world), "SELECT created_ts FROM orders WHERE id = %s", b1)
    forged = Keyset(created + timedelta(seconds=1), b1)
    found = await store.orders(
        _grant(world), OrderQuery(), environment="demo", after=forged, limit=500
    )
    assert found and {listed.order.exchange_account_id for listed in found} == {A}


def store_dsn(world: dict[str, object]) -> str:
    dsn = world["dsn"]
    assert isinstance(dsn, str)
    return dsn


BULK_2 = UUID("e28f0000-0000-4000-8000-0000000000d4")  # another seeded demo account
_BULK = 150_000  # rows per account and table: 600,000 in all
_BULK_ORDERS = (
    "INSERT INTO orders (id, exchange_account_id, order_link_id, symbol, side, intent, order_type,"
    " qty, price, state, created_ts) SELECT gen_random_uuid(), a.id, "
    "'ext-' || md5(a.id::text || n), 'BTCUSDT', 'Buy', 'entry', 'Limit', 0.5, 63000, "
    "CASE WHEN n %% 3 = 0 THEN 'accepted' ELSE 'filled' END::order_state, "
    "%s + n * interval '1 second' FROM unnest(%s::uuid[]) AS a(id), "
    "generate_series(1, %s) AS n"
)
_BULK_FILLS = (
    "INSERT INTO executions (id, exchange_account_id, exec_id, symbol, side, exec_qty, exec_price,"
    " exec_value, exec_type, is_maker, exec_ts) SELECT gen_random_uuid(), a.id, 'B' || n, "
    "'BTCUSDT', 'Buy', 0.1, 63000, 6300, 'Trade', false, %s + n * interval '1 second' "
    "FROM unnest(%s::uuid[]) AS a(id), generate_series(1, %s) AS n"
)


def _plan(dsn: str, stmt: object) -> tuple[list[dict[str, object]], str]:
    """`stmt`'s executed plan (`EXPLAIN ANALYZE`): its nodes, and its text for the PR."""
    compiled = stmt.compile(  # type: ignore[attr-defined]  # a `Select`, passed as `object`
        dialect=pg_psycopg.dialect(), compile_kwargs={"render_postcompile": True}
    )
    with tg._conn(dsn) as c:
        [(plan,)] = c.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + str(compiled), compiled.params)
        text = c.execute(
            "EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF, SUMMARY OFF) " + str(compiled),
            compiled.params,
        ).fetchall()
    nodes: list[dict[str, object]] = []
    pending = [plan[0]["Plan"]]
    while pending:
        node = pending.pop()
        nodes.append(node)
        pending += node.get("Plans", [])
    return nodes, "\n".join(row[0] for row in text)


def _assert_indexed(nodes: list[dict[str, object]], index: str, accounts: int, limit: int) -> None:
    """Index scans of `index` only, each stopping near `limit` rows a loop; no sort of more than
    one page per account."""
    tables = {"orders", "executions"}
    assert not [
        n for n in nodes if n["Node Type"] == "Seq Scan" and n.get("Relation Name") in tables
    ]
    scans = [n for n in nodes if n.get("Index Name") == index]
    assert scans and all(n["Node Type"] in ("Index Scan", "Index Only Scan") for n in scans)
    assert all(int(n["Actual Rows"]) <= limit + 2 for n in scans)  # type: ignore[call-overload]  # JSON
    for sort in (n for n in nodes if n["Node Type"] == "Sort"):
        [child] = sort["Plans"]  # type: ignore[misc]  # the plan's JSON, untyped
        fed = int(child["Actual Rows"]) * int(child["Actual Loops"])
        assert fed <= accounts * limit, sort


async def test_pages_read_their_index_in_order_and_never_sort_every_row(
    pg_dsn: str, world: dict[str, object]
) -> None:
    """#4997: at 150,000 orders and 150,000 fills on each of two accounts, a single-account page,
    a two-account page and a page deep in the history each read `ix_orders_recent` /
    `ix_exec_acct_time` from the cursor's place, per account, and sort at most a page per
    account; never a sequential scan or a sort of every matching row."""
    bulk, start = [BULK_1, BULK_2], T0 + timedelta(days=30)
    tg._sql(pg_dsn, _BULK_ORDERS, start, bulk, _BULK)
    tg._sql(pg_dsn, _BULK_FILLS, start, bulk, _BULK)
    tg._sql(pg_dsn, "ANALYZE orders")
    tg._sql(pg_dsn, "ANALYZE executions")
    manager = world["manager"]
    assert isinstance(manager, UUID)
    tg._sql(
        pg_dsn, "INSERT INTO user_account_access (user_id, exchange_account_id, can_view) "
        "VALUES (%s, %s, true)", manager, BULK_1,
    )  # fmt: skip
    deep = Keyset(start + timedelta(seconds=1_000), uuid4())  # 149,000 rows down each account
    limit, owner, grant = 101, OwnerScope(OWNER), GrantScope(manager, frozenset({BULK_1}))
    cases = [
        ("grant, one account", grant, [BULK_1], None),
        ("owner, two accounts", owner, bulk, None),
        ("owner, two accounts, deep", owner, bulk, deep),
    ]
    for name, scope, accounts, after in cases:
        for index, stmt in (
            ("ix_orders_recent", orders_statement(
                scope, OrderQuery(accounts=tuple(accounts)), "demo", accounts, after, limit
            )),
            ("ix_exec_acct_time", executions_statement(
                scope, ExecutionQuery(accounts=tuple(accounts)), "demo", accounts, after, limit
            )),
        ):  # fmt: skip
            nodes, text = _plan(pg_dsn, stmt)
            print(f"\n--- {name}: {index}\n{text}")  # the PR's evidence (`-s`)
            _assert_indexed(nodes, index, len(accounts), limit)
