"""Integration: the order stores and the M14 repositories on real Postgres 16 (E29-T01 #845 S2).

`testcontainers` in CI; run locally on a scratch PostgreSQL 16.2 (no docker on the laptop). What
only a database proves: the one-statement create and its atomicity, `ux_orders_link` surfacing as
`DuplicateOrderLinkId`, numeric(38,18) through asyncpg with no float, the named constraints the
store reports, account scoping, a dense `seq` under concurrent appends and a redacted payload at
rest. The DDL itself is `test_oms_core_migration.py`'s.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from candleviewer.domain.primitives import AccountId, GroupId
from candleviewer.oms import DuplicateOrderLinkId, OrderEventRepository, OrderRepository
from candleviewer.oms.order_link import OrderLinkIdParts
from candleviewer.storage.repositories.orders import (
    NewOrder,
    NewOrderEvent,
    OrderConstraintError,
    OrderNotFoundError,
)
from candleviewer.storage.repositories.orders_sqlalchemy import SqlAlchemyOrderStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_GHERKIN = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # the #845 Gherkin id (24 Sec.8.3)
_T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
_KEY = "DUMMYKEY_" + "Q3w9" * 5  # synthetic credential shapes, built at run time (SR-145)
_MAC = hashlib.sha256(b"cv-test-vector").hexdigest()


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg"),
            },
            check=True,
        )
        yield dsn


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
    return NewOrderEvent(**({"kind": "local_create", "source": "local", "event_ts": _T0} | over))


@pytest_asyncio.fixture
async def stores(pg_dsn: str) -> AsyncIterator[tuple[OrderRepository, OrderEventRepository]]:
    rel = SqlAlchemyRelationalRepository(pg_dsn, "orders-it")
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
    """The ticket's fixture shapes, appended as the raw exchange message of an ack: nothing of
    the key, the MAC or the recv window reaches the table (SR-E29-08)."""
    orders, events = stores
    new = _order(_account(pg_dsn))
    await orders.create(new, _event())
    headers = {"X-BAPI-API-KEY": _KEY, "X-BAPI-SIGN": _MAC, "X-BAPI-RECV-WINDOW": "5000"}
    frame = {"op": "auth", "args": [_KEY, 1760630405000, _MAC]}
    raw: dict[str, object] = {"headers": headers, "auth": frame, **headers}
    raw["url"] = f"wss://ws.example/v5/private?api_key={_KEY}&signature={_MAC}"
    raw["note"] = "NUL \x00 and a lone \ud800"  # text jsonb refuses: replaced, so the insert holds
    event = await events.append(new.exchange_account_id, new.id, _event(kind="ack", payload=raw))
    stored = _sql(pg_dsn, "SELECT payload::text FROM order_events WHERE id = %s", event.id)[0][0]
    assert _KEY not in stored and _MAC not in stored and "5000" not in stored
    assert event.payload["note"] == "[redacted]"
