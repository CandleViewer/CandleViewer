"""Integration: the OMS stores and the M14 repositories on real Postgres 16 (E29-T01 #845).

The database (`testcontainers`) is set up like production (`pg_bootstrap.sql`'s roles, the
migrations as `cv_owner`) and the stores run as `cv_app`. What only a database proves: the
one-statement create and its atomicity, `ux_orders_link` surfacing as `DuplicateOrderLinkId`,
numeric(38,18) through asyncpg with no float, the named constraints the store reports, account
scoping, a dense `seq` under concurrent appends, `list_open` planned over `ix_orders_open`, the
store's statement cap on a lock wait, and a redacted payload, `ret_code` and `ret_msg` at rest;
for fills and positions, one row per fill whatever reports it, the account-scoped order link of a
fill, the position upsert with a cleared stop, a stale position write that leaves the newer row, a
future-dated position time refused and a future-dated row healed, and `list_unprotected` planned
over `ix_pos_no_sl`. The DDL itself is `test_oms_core_migration.py`'s.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from sqlalchemy.engine import Dialect, make_url
from testcontainers.postgres import PostgresContainer

from candleviewer.domain.primitives import AccountId, GroupId
from candleviewer.oms import (
    DuplicateOrderLinkId,
    ExecutionRepository,
    OrderEventRepository,
    OrderRepository,
    PositionRepository,
    PositionSnapshotRepository,
)
from candleviewer.oms.order_link import OrderLinkIdParts
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.executions import NewExecution
from candleviewer.storage.repositories.executions_sqlalchemy import SqlAlchemyExecutionStore
from candleviewer.storage.repositories.orders import (
    NewOrder,
    NewOrderEvent,
    OrderConstraintError,
    OrderNotFoundError,
)
from candleviewer.storage.repositories.orders_sqlalchemy import (
    SqlAlchemyOrderStore,
    list_open_statement,
)
from candleviewer.storage.repositories.positions import (
    FutureDatedPositionError,
    NewPositionSnapshot,
    PositionState,
)
from candleviewer.storage.repositories.positions_sqlalchemy import (
    SqlAlchemyPositionStore,
    list_unprotected_statement,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_GHERKIN = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # the #845 Gherkin id (24 Sec.8.3)
_T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
_KEY = "DUMMYKEY_" + "Q3w9" * 5  # synthetic credential shapes, built at run time (SR-145)
_MAC = hashlib.sha256(b"cv-test-vector").hexdigest()
_BOOTSTRAP = _ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql"
_ASYNCPG: Dialect = make_url("postgresql+asyncpg://").get_dialect()()


def _login(dsn: str, role: str) -> str:
    return re.sub(r"://[^@]+@", f"://{role}:{role}_test_pw@", dsn)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Superuser DSN of a database set up like production: `pg_bootstrap.sql` first, then the
    migrations as `cv_owner` (the CI `migrations` order), so the default privileges apply."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        info = psycopg.conninfo.conninfo_to_dict(dsn.replace("postgresql+asyncpg", "postgresql"))
        psql = shutil.which("psql")
        assert psql is not None, "the CI integration and migrations jobs have postgresql-client"
        subprocess.run(  # noqa: S603 -- resolved absolute path, fixed argv, no shell (#845)
            [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
             "-d", "candleviewer", "-v", "ON_ERROR_STOP=1", "-v", "owner_pw=cv_owner_test_pw",
             "-v", "app_pw=cv_app_test_pw", "-v", "ro_pw=cv_ro_test_pw", "-f", str(_BOOTSTRAP)],
            check=True, capture_output=True,
            env={**os.environ, "PGPASSWORD": str(info["password"])},
        )  # fmt: skip
        owner = _login(dsn, "cv_owner").replace("postgresql+asyncpg", "postgresql+psycopg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={**os.environ, "CV_PG_DSN": owner},
            check=True,
        )
        yield dsn


@pytest.fixture(scope="module")
def app_dsn(pg_dsn: str) -> str:
    """The production role: no DDL, and no UPDATE, DELETE or TRUNCATE on `order_events`."""
    return _login(pg_dsn, "cv_app")


def _sql(dsn: str, query: str, *args: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        cursor = c.execute(query, args)
        return cursor.fetchall() if cursor.description else []


def _account(dsn: str) -> uuid.UUID:
    account = uuid.uuid4()
    _sql(
        dsn,
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'demo', 'main', %s, %s)",
        account, str(account.int % 10**15), f"acct {account.hex[:8]}",
    )  # fmt: skip
    return account


def _link(account: uuid.UUID, seq: int = 0) -> str:
    return OrderLinkIdParts.generate(
        mode="exchange", environment="demo", group_id=GroupId(uuid.uuid4()),
        account_id=AccountId(account), seq=seq, purpose="entry",
    ).value  # fmt: skip


def _order(account: uuid.UUID, **over: Any) -> NewOrder:
    base: dict[str, Any] = {
        "id": uuid.uuid4(), "exchange_account_id": account, "order_link_id": _link(account),
        "symbol": "BTCUSDT", "side": "Buy", "intent": "entry", "order_type": "Market",
        "qty": Decimal("0.010"), "stop_loss": Decimal("62000"), "state": "pending_submit",
    }  # fmt: skip
    return NewOrder(**(base | over))


def _event(**over: Any) -> NewOrderEvent:
    base: dict[str, Any] = {"kind": "local_create", "source": "local", "event_ts": _T0}
    return NewOrderEvent(**(base | over))


@pytest_asyncio.fixture
async def stores(app_dsn: str) -> AsyncIterator[tuple[OrderRepository, OrderEventRepository]]:
    rel = SqlAlchemyRelationalRepository(app_dsn, "orders-it")
    store = SqlAlchemyOrderStore(rel)
    try:
        yield OrderRepository(store), OrderEventRepository(store)
    finally:
        await rel.dispose()


Repos = tuple[OrderRepository, OrderEventRepository]


async def test_idempotency_is_enforced_by_the_database(stores: Repos, pg_dsn: str) -> None:
    """Gherkin "Idempotency is enforced by the database": the second insert under the scenario's
    id is refused by `ux_orders_link`, the repository raises `DuplicateOrderLinkId`, and neither
    the second order nor its first event is stored."""
    orders, _ = stores
    first = await orders.create(_order(_account(pg_dsn), order_link_id=_GHERKIN), _event())
    second = _order(_account(pg_dsn), order_link_id=_GHERKIN, state="new")
    with pytest.raises(DuplicateOrderLinkId) as err:
        await orders.create(second, _event())
    assert err.value.order_link_id == _GHERKIN
    rows = _sql(pg_dsn, "SELECT id FROM orders WHERE order_link_id = %s", _GHERKIN)
    assert rows == [(first.id,)]
    assert _sql(pg_dsn, "SELECT count(*) FROM order_events WHERE order_id = %s", second.id) == [
        (0,)
    ]


async def test_monetary_precision_is_preserved(stores: Repos, pg_dsn: str) -> None:
    """Gherkin "Monetary precision is preserved": Decimal in, Decimal out through asyncpg, digit
    for digit at the column's scale 18; `leaves_qty` (generated) too."""
    orders, _ = stores
    qty, price = Decimal("0.000000000000000001"), Decimal("63099.80")
    new = _order(_account(pg_dsn), order_type="Limit", qty=qty, price=price)
    created = await orders.create(new, _event())
    read = await orders.get(new.exchange_account_id, new.id)
    scale = Decimal(10) ** -18
    for row in (created, read):
        assert row is not None
        for got, want in ((row.qty, qty), (row.price, price), (row.leaves_qty, qty)):
            assert type(got) is Decimal and got == want
            assert got.as_tuple() == want.quantize(scale).as_tuple()


async def test_the_native_stop_fields_round_trip(stores: Repos, pg_dsn: str) -> None:
    """C-2.6: the TP/SL attached on create is stored on the row and read back exactly."""
    orders, _ = stores
    new = _order(
        _account(pg_dsn), take_profit=Decimal("64000.5"),
        stop_loss=Decimal("0.000000000000000001"), tpsl_mode="Partial",
    )  # fmt: skip
    await orders.create(new, _event())
    read = await orders.get_by_link_id(new.exchange_account_id, new.order_link_id)
    assert read is not None
    assert (read.take_profit, read.stop_loss, read.tpsl_mode) == (
        Decimal("64000.5"), Decimal("0.000000000000000001"), "Partial",
    )  # fmt: skip


async def test_create_stores_the_first_event_with_a_redacted_payload(
    stores: Repos, pg_dsn: str
) -> None:
    orders, events = stores
    new = _order(_account(pg_dsn))
    raw = {"headers": {"X-BAPI-API-KEY": _KEY, "X-BAPI-SIGN": _MAC, "X-BAPI-RECV-WINDOW": "5000"}}
    await orders.create(new, _event(payload=raw | {"body": {"symbol": "BTCUSDT"}}))
    (first,) = await events.list_for_order(new.exchange_account_id, new.id)
    assert (first.seq, first.kind, first.from_state, first.to_state) == (
        0, "local_create", None, "pending_submit",
    )  # fmt: skip
    assert first.order_link_id == new.order_link_id
    stored = _sql(pg_dsn, "SELECT payload::text FROM order_events WHERE id = %s", first.id)
    assert _KEY not in stored[0][0] and _MAC not in stored[0][0] and "5000" not in stored[0][0]
    assert first.payload == {"headers": "[redacted]", "body": {"symbol": "BTCUSDT"}}


async def test_a_refused_first_event_leaves_no_order(stores: Repos, pg_dsn: str) -> None:
    """One transaction: the event's CHECK failing takes the order row with it."""
    orders, _ = stores
    new = _order(_account(pg_dsn))
    with pytest.raises(OrderConstraintError) as err:
        await orders.create(new, _event(latency_ms=-1))
    assert err.value.constraint == "oe_latency"
    assert _sql(pg_dsn, "SELECT count(*) FROM orders WHERE id = %s", new.id) == [(0,)]


@pytest.mark.parametrize(
    ("over", "constraint"),
    [
        ({"qty": Decimal("-0.010")}, "ord_cum"),  # CHECKs run in name order: ord_cum first
        ({"cum_exec_qty": Decimal("0.011")}, "ord_cum"),
        ({"order_link_id": "cv-l7f3a91c2-ent-00"}, "ord_link_fmt"),
        ({"position_idx": 3}, "ord_posidx"),
        ({"time_in_force": "GTD"}, "ord_tif"),
        ({"exchange_account_id": uuid.UUID(int=5)}, "orders_exchange_account_id_fkey"),
    ],
)
async def test_an_invalid_order_is_refused_by_its_named_constraint(
    stores: Repos, pg_dsn: str, over: dict[str, Any], constraint: str
) -> None:
    orders, _ = stores
    with pytest.raises(OrderConstraintError) as err:
        await orders.create(replace(_order(_account(pg_dsn)), **over), _event())
    assert err.value.constraint == constraint


async def test_reads_and_appends_are_scoped_to_the_account(stores: Repos, pg_dsn: str) -> None:
    orders, events = stores
    new, other = _order(_account(pg_dsn)), _account(pg_dsn)
    await orders.create(new, _event())
    assert await orders.get(other, new.id) is None
    assert await orders.get_by_link_id(other, new.order_link_id) is None
    assert await orders.list_open(other) == ()
    assert await events.list_for_order(other, new.id) == ()
    with pytest.raises(OrderNotFoundError):
        await events.append(other, new.id, _event(kind="ack", source="rest"))
    assert _sql(pg_dsn, "SELECT count(*) FROM order_events WHERE order_id = %s", new.id) == [(1,)]


async def test_list_open_returns_the_open_orders_of_the_account_oldest_first(
    stores: Repos, pg_dsn: str
) -> None:
    orders, _ = stores
    account = _account(pg_dsn)
    made = []
    for state, symbol in [("pending_submit", "BTCUSDT"), ("new", "BTCUSDT"),
                          ("partially_filled", "ETHUSDT"), ("filled", "BTCUSDT"),
                          ("pending_amend", "BTCUSDT"), ("untracked", "BTCUSDT")]:  # fmt: skip
        made.append(await orders.create(_order(account, state=state, symbol=symbol), _event()))
    open_all = await orders.list_open(account)
    assert [r.id for r in open_all] == [made[0].id, made[2].id, made[4].id]
    assert [r.id for r in await orders.list_open(account, symbol="BTCUSDT")] == [
        made[0].id, made[4].id,
    ]  # fmt: skip


def _plan(dsn: str, stmt: Any) -> str:
    """EXPLAIN of a store statement as asyncpg runs it, a prepared statement, on its generic plan
    (the driver caches statements, so Postgres may switch to it), with sequential scans priced
    out. A partial index matches only a predicate written with literals there."""
    compiled = stmt.compile(dialect=_ASYNCPG, compile_kwargs={"render_postcompile": True})
    args = sql.SQL(", ").join(sql.Literal(compiled.params[n]) for n in compiled.positiontup or ())
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql")) as c, c.transaction():
        c.execute("SET LOCAL enable_seqscan = off")
        c.execute("SET LOCAL plan_cache_mode = force_generic_plan")
        c.execute(sql.SQL("PREPARE probe AS {}").format(sql.SQL(str(compiled))))
        rows = c.execute(sql.SQL("EXPLAIN EXECUTE probe ({})").format(args)).fetchall()
    return "\n".join(str(row[0]) for row in rows)


def _closed_history(dsn: str, account: uuid.UUID, n: int) -> None:
    """`n` filled orders: most of an account's rows are closed once it has traded a while."""
    _sql(
        dsn,
        "INSERT INTO orders (id, exchange_account_id, order_link_id, symbol, side, intent, "
        "order_type, qty, state) SELECT gen_random_uuid(), %s, 'ext-' || md5(%s::text || g), "
        "'BTCUSDT', 'Buy', 'entry', 'Market', 1, 'filled' FROM generate_series(1, %s) AS g",
        account, account.hex, n,
    )  # fmt: skip


@pytest.mark.parametrize("symbol", [None, "BTCUSDT"])
async def test_list_open_is_planned_over_ix_orders_open(
    stores: Repos, pg_dsn: str, symbol: str | None
) -> None:
    """#845 performance notes: the open-order lookup scans the partial index, with the symbol in
    its index condition when one is given (the open states render as literals, so the planner
    matches the index predicate). The table has the shape history gives it, mostly closed
    orders, and planner statistics as autovacuum keeps them: without any, the planner guesses."""
    orders, _ = stores
    accounts = [_account(pg_dsn), _account(pg_dsn)]
    for account in accounts:
        _closed_history(pg_dsn, account, 300)
        for state in ("pending_submit", "accepted"):
            await orders.create(_order(account, state=state), _event())
    _sql(pg_dsn, "ANALYZE orders")
    plan = _plan(pg_dsn, list_open_statement(accounts[0], symbol))
    assert "ix_orders_open" in plan, plan
    assert ("symbol" in plan.split("ix_orders_open", 1)[1]) is (symbol is not None), plan


async def test_appends_take_dense_sequence_numbers_even_concurrently(
    stores: Repos, pg_dsn: str
) -> None:
    orders, events = stores
    new = _order(_account(pg_dsn))
    await orders.create(new, _event())
    appended = await asyncio.gather(
        *(events.append(new.exchange_account_id, new.id, _event(kind="ack", source="rest"))
          for _ in range(8))
    )  # fmt: skip
    assert sorted(e.seq for e in appended) == list(range(1, 9))
    page = await events.list_for_order(new.exchange_account_id, new.id, after_seq=2, limit=3)
    assert [(e.seq, e.from_state, e.to_state) for e in page] == [(s, None, None) for s in (3, 4, 5)]


async def test_exists_sees_every_row_whatever_its_account_or_state(
    stores: Repos, pg_dsn: str
) -> None:
    orders, _ = stores
    new = _order(_account(pg_dsn), state="cancelled")
    await orders.create(new, _event())
    assert await orders.exists(new.order_link_id) is True
    assert await orders.exists(_link(new.exchange_account_id, seq=1)) is False


async def test_a_signed_create_call_is_stored_without_its_credentials(
    stores: Repos, pg_dsn: str
) -> None:
    """The ticket's fixture shapes, appended as the raw exchange message of a reject whose retMsg
    echoes the signed string: nothing of the key, the MAC or the recv window reaches the table
    (21 Sec.3.3.5; the #845 security notes)."""
    orders, events = stores
    new = _order(_account(pg_dsn))
    await orders.create(new, _event())
    headers = {"X-BAPI-API-KEY": _KEY, "X-BAPI-SIGN": _MAC, "X-BAPI-RECV-WINDOW": "5000"}
    frame = {"op": "auth", "args": [_KEY, 1760630405000, _MAC]}
    raw: dict[str, object] = {"headers": headers, "auth": frame, **headers}
    raw["url"] = f"wss://ws.example/v5/private?api_key={_KEY}&signature={_MAC}"
    raw["note"] = "NUL \x00 and a lone \ud800"  # text jsonb refuses: replaced, so the insert holds
    echo = f"error sign! origin_string[1760630400000{_KEY}5000]"
    reject = _event(kind="reject", source="rest", payload=raw, ret_code="10004", ret_msg=echo)
    event = await events.append(new.exchange_account_id, new.id, reject)
    ((payload, ret_code, ret_msg),) = _sql(
        pg_dsn, "SELECT payload::text, ret_code, ret_msg FROM order_events WHERE id = %s", event.id
    )
    for stored in (payload, ret_msg):
        assert _KEY not in stored and _MAC not in stored and "5000" not in stored
    assert (ret_code, ret_msg, event.ret_msg) == ("10004", "[redacted]", "[redacted]")
    assert event.payload["note"] == "[redacted]"


async def test_the_stores_need_no_more_than_the_cv_app_role(
    stores: Repos, pg_dsn: str, app_dsn: str
) -> None:
    """Create, append (its `FOR NO KEY UPDATE` needs UPDATE on `orders`) and read as `cv_app`,
    which may not rewrite `order_events` (C-5.7)."""
    orders, events = stores
    new = _order(_account(pg_dsn))
    await orders.create(new, _event())
    await events.append(new.exchange_account_id, new.id, _event(kind="ack", source="rest"))
    assert len(await events.list_for_order(new.exchange_account_id, new.id)) == 2
    with psycopg.connect(app_dsn.replace("postgresql+asyncpg", "postgresql")) as c:
        assert c.execute("SELECT current_user").fetchone() == ("cv_app",)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("UPDATE order_events SET ret_msg = 'x' WHERE order_id = %s", (new.id,))


async def test_a_write_blocked_by_a_row_lock_fails_within_the_store_cap(
    stores: Repos, pg_dsn: str, app_dsn: str
) -> None:
    """24 Sec.8.2 S7: an append waiting on another transaction's row lock is cancelled at the
    store's cap (100 ms here, 2000 ms by default) as `StorageQueryFailed('57014')`, instead of
    holding the order path for the repository-wide 30 s."""
    orders, _ = stores
    new = _order(_account(pg_dsn))
    await orders.create(new, _event())
    rel = SqlAlchemyRelationalRepository(app_dsn, "orders-it-cap")
    events = OrderEventRepository(SqlAlchemyOrderStore(rel, statement_timeout_ms=100))
    try:
        with psycopg.connect(pg_dsn.replace("postgresql+asyncpg", "postgresql")) as holder:
            holder.execute("SELECT id FROM orders WHERE id = %s FOR UPDATE", (new.id,))
            with pytest.raises(StorageQueryFailed) as err:
                async with asyncio.timeout(5):  # far above the cap, far below the shared 30 s
                    await events.append(new.exchange_account_id, new.id, _event(kind="ack"))
            holder.rollback()
    finally:
        await rel.dispose()
    assert err.value.sqlstate == "57014"  # query_canceled: the statement timeout
    assert _sql(pg_dsn, "SELECT count(*) FROM order_events WHERE order_id = %s", new.id) == [(1,)]


# -- executions, positions and position snapshots ----------------------------------------------

Ledger = tuple[ExecutionRepository, PositionRepository, PositionSnapshotRepository]


@pytest_asyncio.fixture
async def ledger(app_dsn: str) -> AsyncIterator[Ledger]:
    rel = SqlAlchemyRelationalRepository(app_dsn, "positions-it")
    positions = SqlAlchemyPositionStore(rel)
    try:
        yield (
            ExecutionRepository(SqlAlchemyExecutionStore(rel)),
            PositionRepository(positions),
            PositionSnapshotRepository(positions),
        )
    finally:
        await rel.dispose()


def _fill(account: uuid.UUID, **over: Any) -> NewExecution:
    base: dict[str, Any] = {
        "exchange_account_id": account, "exec_id": "E1", "symbol": "BTCUSDT", "side": "Buy",
        "exec_qty": Decimal("0.010"), "exec_price": Decimal("63099.80"),
        "exec_value": Decimal("630.998"), "exec_type": "Trade", "is_maker": False, "exec_ts": _T0,
    }  # fmt: skip
    return NewExecution(**(base | over))


def _state(account: uuid.UUID, symbol: str, **over: Any) -> PositionState:
    base: dict[str, Any] = {"exchange_account_id": account, "symbol": symbol}
    return PositionState(**(base | {"size": Decimal("0.010")} | over))


async def test_fills_deduplicate_across_sources(stores: Repos, ledger: Ledger, pg_dsn: str) -> None:
    """Gherkin "Fills deduplicate across sources": E1 of account A, from the private stream, again
    from it and from the REST backfill, is one row, and another account's E1 is its own. It is
    stored digit for digit, a Decimal (Gherkin "Monetary precision is preserved")."""
    executions = ledger[0]
    a, b = _account(pg_dsn), _account(pg_dsn)
    order = await stores[0].create(_order(a), _event())
    tiny = Decimal("0.000000000000000001")
    fill = _fill(a, order_id=order.id, order_link_id=order.order_link_id, exec_qty=tiny)
    assert [await executions.insert(fill) for _ in ("ws", "ws", "rest")] == [True, False, False]
    assert await executions.insert(_fill(b)) is True
    count = "SELECT count(*) FROM executions WHERE exchange_account_id = %s AND exec_id = 'E1'"
    assert [_sql(pg_dsn, count, account) for account in (a, b)] == [[(1,)], [(1,)]]
    stored = await executions.get(a, "E1")
    assert stored is not None and (stored.order_id, stored.recv_ts.tzinfo is not None) == (
        order.id, True,
    )  # fmt: skip
    for got, want in ((stored.exec_qty, tiny), (stored.exec_price, Decimal("63099.80"))):
        assert type(got) is Decimal and got.as_tuple() == want.quantize(tiny).as_tuple()
    assert await executions.get(b, "E2") is None


async def test_a_fill_naming_another_accounts_order_is_refused_and_not_stored(
    stores: Repos, ledger: Ledger, pg_dsn: str
) -> None:
    order = await stores[0].create(_order(_account(pg_dsn)), _event())
    other = _account(pg_dsn)
    with pytest.raises(OrderNotFoundError):
        await ledger[0].insert(_fill(other, order_id=order.id))
    count = "SELECT count(*) FROM executions WHERE exchange_account_id = %s"
    assert _sql(pg_dsn, count, other) == [(0,)]


async def test_an_open_position_whose_stop_was_cleared_is_listed_unprotected(
    ledger: Ledger, pg_dsn: str
) -> None:
    """C-2.6: the exchange reports a cleared stop as 0, which is stored as NULL, so the upserted
    row reads as unprotected; flat, protected and other accounts' positions do not."""
    positions = ledger[1]
    a, b = _account(pg_dsn), _account(pg_dsn)
    first = await positions.upsert(_state(a, "BTCUSDT", stop_loss=Decimal("62000")))
    cleared = await positions.upsert(_state(a, "BTCUSDT", stop_loss=Decimal(0), size=Decimal(2)))
    await positions.upsert(_state(a, "ETHUSDT", stop_loss=Decimal("2400")))
    await positions.upsert(_state(a, "SOLUSDT", size=Decimal(0)))
    await positions.upsert(_state(b, "XRPUSDT"))
    assert (cleared.id, cleared.size, cleared.stop_loss) == (first.id, Decimal(2), None)
    assert cleared.updated_at >= first.updated_at
    assert [p.symbol for p in await positions.list_unprotected(a)] == ["BTCUSDT"]
    assert [p.symbol for p in await positions.list_open(a)] == ["BTCUSDT", "ETHUSDT"]
    assert [p.symbol for p in await positions.list_unprotected(b)] == ["XRPUSDT"]


async def test_a_stale_position_write_leaves_the_newer_row(ledger: Ledger, pg_dsn: str) -> None:
    """C-2.6: a snapshot older than the stored row changes nothing and returns the stored row, so
    a newer push without a stop-loss stays in `list_unprotected`; an equal time applies, and so
    does a NULL time on either side."""
    positions, account, older = ledger[1], _account(pg_dsn), _T0 - timedelta(seconds=1)
    newer = await positions.upsert(_state(account, "BTCUSDT", exchange_updated_ts=_T0))
    stop = Decimal("62000")
    kept = await positions.upsert(
        _state(account, "BTCUSDT", size=Decimal(2), stop_loss=stop, exchange_updated_ts=older)
    )
    assert (kept.id, kept.size, kept.stop_loss, kept.exchange_updated_ts, kept.updated_at) == (
        newer.id, newer.size, None, _T0, newer.updated_at,
    )  # fmt: skip
    assert [p.symbol for p in await positions.list_unprotected(account)] == ["BTCUSDT"]
    times = ((3, _T0), (4, None), (5, older))  # equal; a NULL new time; over a NULL stored one
    applied = [
        await positions.upsert(_state(account, "BTCUSDT", size=Decimal(n), exchange_updated_ts=ts))
        for n, ts in times
    ]
    assert [(p.size, p.exchange_updated_ts) for p in applied] == list(times)
    size = "SELECT size FROM positions WHERE exchange_account_id = %s"
    assert _sql(pg_dsn, size, account) == [(Decimal(5),)]


async def test_a_future_dated_position_time_is_refused_and_a_stored_one_heals(
    app_dsn: str, pg_dsn: str
) -> None:
    """C-2.6: a time more than 5 s ahead of the store's clock is refused and writes nothing. A row
    stamped an hour ahead (by a store whose clock ran an hour fast) loses the guard, so the next
    write applies although its own time is older, and the cleared stop is listed; a stored time
    within the 5 s still keeps an older write out."""
    rel = SqlAlchemyRelationalRepository(app_dsn, "positions-skew-it")
    hour, account = timedelta(hours=1), _account(pg_dsn)
    on_time = PositionRepository(SqlAlchemyPositionStore(rel, clock=lambda: _T0))
    fast = PositionRepository(SqlAlchemyPositionStore(rel, clock=lambda: _T0 + hour))
    try:
        with pytest.raises(FutureDatedPositionError):
            await on_time.upsert(_state(account, "BTCUSDT", exchange_updated_ts=_T0 + hour))
        count = "SELECT count(*) FROM positions WHERE exchange_account_id = %s"
        assert _sql(pg_dsn, count, account) == [(0,)]
        stop = Decimal("62000")
        await fast.upsert(
            _state(account, "BTCUSDT", stop_loss=stop, exchange_updated_ts=_T0 + hour)
        )
        healed = await on_time.upsert(_state(account, "BTCUSDT", exchange_updated_ts=_T0))
        assert (healed.stop_loss, healed.exchange_updated_ts) == (None, _T0)
        assert [p.symbol for p in await on_time.list_unprotected(account)] == ["BTCUSDT"]
        near = _T0 + timedelta(seconds=4)
        await on_time.upsert(_state(account, "ETHUSDT", stop_loss=stop, exchange_updated_ts=near))
        kept = await on_time.upsert(_state(account, "ETHUSDT", exchange_updated_ts=_T0))
        assert (kept.stop_loss, kept.exchange_updated_ts) == (stop, near)
    finally:
        await rel.dispose()


async def test_list_unprotected_is_planned_over_ix_pos_no_sl(ledger: Ledger, pg_dsn: str) -> None:
    """#845 performance notes: the naked-position read scans the partial index. Each account holds
    many protected and flat positions, as in use, and the planner has statistics."""
    accounts = [_account(pg_dsn), _account(pg_dsn)]
    for account in accounts:
        _sql(
            pg_dsn,
            "INSERT INTO positions (id, exchange_account_id, symbol, size, stop_loss) "
            "SELECT gen_random_uuid(), %s, 'S' || g || 'USDT', g %% 2, 100 "
            "FROM generate_series(1, 300) AS g",
            account,
        )
        await ledger[1].upsert(_state(account, "BTCUSDT"))
    _sql(pg_dsn, "ANALYZE positions")
    plan = _plan(pg_dsn, list_unprotected_statement(accounts[0]))
    assert "ix_pos_no_sl" in plan, plan


async def test_a_position_snapshot_is_appended_as_given(ledger: Ledger, pg_dsn: str) -> None:
    account = _account(pg_dsn)
    equity = Decimal("12345.000000000000000001")
    snap = await ledger[2].append(
        NewPositionSnapshot(
            exchange_account_id=account, symbol="BTCUSDT", size=Decimal("0.010"),
            equity_usd=equity, reason="minute_tick",
        )
    )  # fmt: skip
    assert (snap.size, snap.equity_usd, snap.reason) == (Decimal("0.010"), equity, "minute_tick")
    count = "SELECT count(*) FROM position_snapshots WHERE exchange_account_id = %s"
    assert snap.id > 0 and _sql(pg_dsn, count, account) == [(1,)]
