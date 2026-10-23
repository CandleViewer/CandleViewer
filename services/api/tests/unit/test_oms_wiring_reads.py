"""E29-T04 (#913) slice 3C, the reads: `oms_wiring.TradingAccountsBinding` over the account read,
`list_unfinished` on the in-memory order store, and that both order stores fill `UnfinishedOrders`.
The order route's trading principal is `tests/unit/api/test_order_principal.py`'s and the Postgres
reads are `tests/integration/storage/test_oms_reads_pg.py`'s."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from types import SimpleNamespace
from typing import Any, cast, get_args

import pytest

from candleviewer.accounts.order_gate import AccountHealthCheck, KeyStanding
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.exchange.base.models import AccountRef
from candleviewer.oms.errors import AccountScopeDenied, OrderEntryRefused, StoreUnavailable
from candleviewer.oms.fakes import InMemoryOrderStore
from candleviewer.oms.ports import TradingAccounts
from candleviewer.oms_wiring import NO_ACTIVE_KEY, TradingAccountsBinding
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories import orders as port
from candleviewer.storage.repositories.orders_sqlalchemy import SqlAlchemyOrderStore
from candleviewer.storage.repositories.trading_accounts import (
    InMemoryTradingAccountReads,
    TradingAccountRow,
)
from candleviewer.storage.repositories.trading_accounts_sqlalchemy import TRADING_ACCOUNT_SQL

DEMO, KEY, LIVE, GONE, NEVER = (uuid.UUID(int=n) for n in range(1, 6))
T0 = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def _row(**over: Any) -> TradingAccountRow:
    base: dict[str, Any] = {
        "account_id": DEMO, "environment": "demo", "exchange_uid": "1234567", "deleted": False,
        "active_key_id": KEY,
    }  # fmt: skip
    return TradingAccountRow(**(base | over))


def test_the_account_read_takes_only_the_active_unrevoked_keys_id() -> None:
    """The Postgres tests run the read; this pins in the unit lane that it reads no key column."""
    sql = TRADING_ACCOUNT_SQL.text
    assert "(SELECT k.id FROM api_keys k WHERE" in sql and "_enc" not in sql
    assert "k.status = 'active' AND k.revoked_at IS NULL" in sql


def _binding(*rows: TradingAccountRow) -> TradingAccountsBinding:
    return TradingAccountsBinding(InMemoryTradingAccountReads(*rows), environment="demo")


async def test_a_live_account_resolves_to_its_uid_and_active_key() -> None:
    binding, demo = _binding(_row()), AccountId(DEMO)
    port: TradingAccounts = binding  # `mypy --strict` proves the binding fills the OMS port
    ref = AccountRef(account_id=demo, uid="1234567", environment="demo", key_ref=str(KEY))
    assert await port.trading_account(demo) == ref
    assert await binding.environment_of(demo) == "demo"


@pytest.mark.parametrize("call", ["trading_account", "environment_of"])
@pytest.mark.parametrize(
    "rows",
    [(), (_row(environment="live"),), (_row(deleted=True),)],
    ids=["unknown", "live", "deleted"],
)
async def test_an_unknown_foreign_or_deleted_account_is_one_scope_refusal(
    call: str, rows: tuple[TradingAccountRow, ...]
) -> None:
    with pytest.raises(AccountScopeDenied) as raised:
        await getattr(_binding(*rows), call)(AccountId(DEMO))
    assert (type(raised.value), raised.value.detail) == (  # no oracle: the three alike
        AccountScopeDenied, AccountScopeDenied.default_detail
    )  # fmt: skip


async def test_a_keyless_account_passes_the_existence_step_and_is_the_gates_no_active_key() -> None:
    binding = _binding(_row(active_key_id=None))
    assert await binding.environment_of(AccountId(DEMO)) == "demo"
    with pytest.raises(OrderEntryRefused) as raised:
        await binding.trading_account(AccountId(DEMO))
    keyless = SimpleNamespace(standing=lambda _: KeyStanding(False), current=lambda _: None)
    reads = cast(Any, SimpleNamespace(risk_sizing_available=lambda _: None, **vars(keyless)))
    assert NO_ACTIVE_KEY == AccountHealthCheck(reads, reads, reads).refusal(DEMO)  # the gate's
    assert (raised.value.reason, raised.value.detail) == ("no_active_key", NO_ACTIVE_KEY.detail)


class _Failing:
    """An account read that raises `error`, or with none never answers."""

    def __init__(self, error: BaseException | None) -> None:
        self.error = error

    async def read_account(self, account_id: uuid.UUID) -> TradingAccountRow | None:
        if self.error is not None:
            raise self.error
        await asyncio.Event().wait()
        return None


@pytest.mark.parametrize("error", [StorageTierUnavailable("x"), None], ids=["store", "no-answer"])
async def test_an_account_read_that_fails_is_the_stores_unavailability(
    error: BaseException | None,
) -> None:
    binding = TradingAccountsBinding(_Failing(error), environment="demo", timeout_s=0)
    with pytest.raises(StoreUnavailable):
        await binding.trading_account(AccountId(DEMO))


SEEDED: tuple[tuple[uuid.UUID, Environment], ...] = ((DEMO, "demo"), (LIVE, "live"), (GONE, "demo"))


async def _store(*orders: tuple[uuid.UUID, port.OrderState]) -> InMemoryOrderStore:
    """Orders created in this order, on DEMO, LIVE, GONE (soft-deleted) or NEVER (never seeded)."""
    ticks = count()
    store = InMemoryOrderStore(clock=lambda: T0 + timedelta(seconds=next(ticks)))
    for account, env in SEEDED:
        ref = AccountRef(account_id=AccountId(account), uid="1", environment=env, key_ref="k")
        store.submissions.seed_account(ref)
    store.submissions.refuse(GONE, "account_not_live")
    for account, state in orders:
        order_id = uuid.uuid4()
        new = port.NewOrder(
            id=order_id, exchange_account_id=account, order_link_id=f"ext-{order_id.hex}",
            symbol="BTCUSDT", side="Buy", intent="entry", order_type="Market",
            qty=Decimal("0.01"), state=state,
        )  # fmt: skip
        await store.create(
            new, port.NewOrderEvent(kind="local_create", source="local", event_ts=T0)
        )
    return store


async def test_list_unfinished_lists_every_state_that_is_not_final_but_new() -> None:
    states = get_args(port.OrderState)
    rows = await (await _store(*((DEMO, s) for s in states))).list_unfinished("demo", limit=100)
    assert [row.state for row in rows] == [s for s in states if s in port.UNFINISHED_STATES]
    finals = {"filled", "cancelled", "rejected", "expired", "killed"}
    assert set(port.ORDER_STATE_OF.values()) - port.UNFINISHED_STATES == finals | {"new"}


async def test_list_unfinished_takes_the_environments_accounts_oldest_first_at_most_limit() -> None:
    store = await _store(
        (DEMO, "held"), (LIVE, "unknown"), (GONE, "quarantined"), (NEVER, "held"),
        (DEMO, "submitted"),
    )  # fmt: skip
    demo = [(r.exchange_account_id, r.state) for r in await store.list_unfinished("demo", limit=9)]
    assert demo == [(DEMO, "held"), (GONE, "quarantined"), (DEMO, "submitted")]
    two = await store.list_unfinished("demo", limit=2)
    assert [r.state for r in two] == ["held", "quarantined"]
    assert [r.exchange_account_id for r in await store.list_unfinished("live", limit=9)] == [LIVE]
    for limit in (0, True):
        with pytest.raises(ValueError, match="limit"):
            await store.list_unfinished("demo", limit=limit)


def test_both_order_stores_fill_the_unfinished_orders_port() -> None:
    """`mypy --strict` checks these assignments, so a drift of either store fails here."""
    postgres: port.UnfinishedOrders = SqlAlchemyOrderStore(cast(Any, object()))  # no database
    fake: port.UnfinishedOrders = InMemoryOrderStore()
    for store in (postgres, fake):
        assert inspect.iscoroutinefunction(store.list_unfinished)  # the runtime awaits it
