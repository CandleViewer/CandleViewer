"""`oms.reads` (E29-T07 #915, PR 1): the aggregate of `listPositions?aggregate=true` in `Decimal`
(net, gross, the size-weighted entry price on one side, the PnL sum) and the read service's bound
and refusals: a named account outside the scope is `AccountScopeDenied`, a store that fails or
does not answer in time `StoreUnavailable`."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.oms.errors import AccountScopeDenied, StoreUnavailable
from candleviewer.oms.reads import OmsReads, aggregate_positions
from candleviewer.oms.submit import entry_order_id
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.accounts import OwnerScope
from candleviewer.storage.repositories.oms_reads import (
    AnchoredTarget,
    ExecutionQuery,
    OrderQuery,
    PositionQuery,
    PositionsTooMany,
)
from candleviewer.storage.repositories.orders import AccountsOutOfScope, OrderConstraintError
from tests.unit.api.oms_reads_world import ACCOUNT_A, ACCOUNT_B, MISSING, USERS, position

_OWNER = OwnerScope(USERS["owner"])


def test_one_sided_legs_net_gross_and_their_size_weighted_entry() -> None:
    [btc] = aggregate_positions([
        position(1, ACCOUNT_A, size=Decimal("0.2"), avg_price=Decimal("63000")),
        position(2, ACCOUNT_B, size=Decimal("0.3"), avg_price=Decimal("64000"),
                 unrealised_pnl=Decimal("-1.20")),
    ])  # fmt: skip
    assert (btc.net_size, btc.gross_size) == (Decimal("0.5"), Decimal("0.5"))
    assert btc.weighted_avg_price == Decimal("63600")  # (0.2*63000 + 0.3*64000) / 0.5
    assert btc.unrealised_pnl == Decimal("2.62")
    assert [(leg.account_id, leg.side) for leg in btc.legs] == [
        (ACCOUNT_A, "long"), (ACCOUNT_B, "long"),
    ]  # fmt: skip


def test_a_long_and_a_short_net_out_and_have_no_weighted_entry() -> None:
    [btc] = aggregate_positions([
        position(1, ACCOUNT_A, size=Decimal("0.2")),
        position(2, ACCOUNT_B, side="Sell", size=Decimal("0.5")),
    ])  # fmt: skip
    assert (btc.net_size, btc.gross_size) == (Decimal("-0.3"), Decimal("0.7"))
    assert btc.weighted_avg_price is None and btc.legs[1].side == "short"


def test_a_missing_price_or_pnl_is_absent_never_counted_as_zero() -> None:
    [btc] = aggregate_positions([
        position(1, ACCOUNT_A), position(2, ACCOUNT_B, avg_price=None, unrealised_pnl=None),
    ])  # fmt: skip
    assert btc.weighted_avg_price is None and btc.unrealised_pnl is None
    assert btc.legs[1].unrealised_pnl is None


def test_flat_rows_join_no_aggregate_and_symbols_come_sorted() -> None:
    found = aggregate_positions([
        position(1, ACCOUNT_A, symbol="SOLUSDT"), position(2, ACCOUNT_A, size=Decimal(0)),
        position(3, ACCOUNT_A, symbol="ETHUSDT", side="None", size=Decimal(1)),
        position(4, ACCOUNT_B, symbol="ADAUSDT"),
    ])  # fmt: skip
    assert [a.symbol for a in found] == ["ADAUSDT", "SOLUSDT"]


_SIZES = st.decimals(min_value=Decimal("0.001"), max_value=Decimal(1000), places=3)
_PRICES = st.decimals(min_value=Decimal("0.01"), max_value=Decimal(100000), places=2)


@settings(max_examples=80, deadline=None, derandomize=True)
@given(st.lists(st.tuples(st.booleans(), _SIZES, _PRICES), min_size=1, max_size=8))
def test_the_aggregate_holds_its_invariants(legs: list[tuple[bool, Decimal, Decimal]]) -> None:
    """|net| <= gross; gross is the sizes' sum; one side's weighted entry lies within its legs'."""
    rows = [
        position(n, ACCOUNT_A, side="Buy" if long else "Sell", size=size, avg_price=price)
        for n, (long, size, price) in enumerate(legs)
    ]
    [found] = aggregate_positions(rows)
    assert abs(found.net_size) <= found.gross_size == sum(size for _, size, _ in legs)
    if len({long for long, _, _ in legs}) == 1:
        prices = [price for _, _, price in legs]
        assert found.weighted_avg_price is not None
        assert min(prices) <= found.weighted_avg_price <= max(prices)
        assert isinstance(found.weighted_avg_price, Decimal)
    else:
        assert found.weighted_avg_price is None


class _Store:
    def __init__(self, error: BaseException | None = None, hold: bool = False) -> None:
        self.error, self.hold, self.seen = error, hold, list[tuple[str, Any]]()

    async def _answer(self, name: str, environment: str) -> tuple[()]:
        self.seen.append((name, environment))
        if self.hold:
            await asyncio.Event().wait()
        if self.error is not None:
            raise self.error
        return ()

    async def orders(self, *_a: Any, environment: str, **_k: Any) -> tuple[()]:
        return await self._answer("orders", environment)

    async def anchored(self, created_by: UUID, keys: frozenset[UUID]) -> tuple[()]:
        return await self._answer("anchored", str(created_by))

    async def order(self, *_a: Any, environment: str, **_k: Any) -> tuple[()]:
        return await self._answer("order", environment)

    async def executions(self, *_a: Any, environment: str, **_k: Any) -> tuple[()]:
        return await self._answer("executions", environment)

    async def closed_pnl(self, *_a: Any, environment: str, **_k: Any) -> tuple[()]:
        return await self._answer("closed_pnl", environment)

    async def positions(self, *_a: Any, environment: str, **_k: Any) -> tuple[()]:
        return await self._answer("positions", environment)

    async def position(self, *_a: Any, environment: str, **_k: Any) -> tuple[()]:
        return await self._answer("position", environment)


def _calls(reads: OmsReads) -> list[Any]:
    return [
        reads.orders(_OWNER, OrderQuery(), after=None, limit=1),
        reads.order(_OWNER, MISSING, events=False),
        reads.executions(_OWNER, ExecutionQuery(), after=None, limit=1),
        reads.closed_pnl(_OWNER, ExecutionQuery(), after=None, limit=1),
        reads.positions(_OWNER, PositionQuery()),
        reads.position(_OWNER, MISSING),
    ]


async def test_every_read_is_of_the_services_environment() -> None:
    store = _Store()
    reads = OmsReads(store, "testnet")  # type: ignore[arg-type]  # a recording port
    for call in _calls(reads):
        assert await call == ()
    assert {env for _, env in store.seen} == {"testnet"} and len(store.seen) == 6


@pytest.mark.parametrize(
    ("error", "raised"),
    [
        (AccountsOutOfScope("outside"), AccountScopeDenied),
        (StorageTierUnavailable("down"), StoreUnavailable),
        (OrderConstraintError("x"), StoreUnavailable),
        (PositionsTooMany(), StoreUnavailable),  # refused whole, never cut (#4997 m2)
    ],
)
async def test_a_refusal_or_an_outage_is_the_oms_error(
    error: BaseException, raised: type[Exception]
) -> None:
    reads = OmsReads(_Store(error), "demo")  # type: ignore[arg-type]  # a recording port
    for call in _calls(reads):
        with pytest.raises(raised):
            await call


async def test_a_read_that_does_not_answer_in_its_bound_is_store_unavailable() -> None:
    reads = OmsReads(_Store(hold=True), "demo", timeout_s=0.01)  # type: ignore[arg-type]  # a port
    with pytest.raises(StoreUnavailable):
        await reads.positions(_OWNER, PositionQuery())


@pytest.mark.parametrize("bound", [0.0, -1.0, 2.5, float("nan")])
def test_a_reads_bound_is_only_ever_tightened(bound: float) -> None:
    with pytest.raises(ValueError, match="tightened"):
        OmsReads(_Store(), "demo", timeout_s=bound)  # type: ignore[arg-type]  # a port


_KEY, _GROUP = UUID(int=0x2303), UUID(int=0x23A1)
_REDUCE = UUID(int=0x23A2)


@dataclass
class _Lookup:
    """Records the anchors asked for and the query the orders read is given (#2303)."""

    targets: tuple[AnchoredTarget, ...]
    asked: list[tuple[UUID, frozenset[UUID]]] = field(default_factory=list)
    queries: list[OrderQuery] = field(default_factory=list)

    async def anchored(self, created_by: UUID, keys: frozenset[UUID]) -> tuple[AnchoredTarget, ...]:
        self.asked.append((created_by, keys))
        return self.targets

    async def orders(self, _scope: Any, query: OrderQuery, **_k: Any) -> tuple[()]:
        self.queries.append(query)
        return ()


async def test_a_key_lookup_reads_the_callers_anchors_then_their_orders_by_id() -> None:
    """#2303: the anchors of the scope's principal alone; an entry's order named from its group
    as a repeat names it (`entry_order_id`), a reduce-only one by its own id; no key, no anchor
    read."""
    store = _Lookup((AnchoredTarget(None, _GROUP), AnchoredTarget(_REDUCE, None)))
    reads = OmsReads(store, "demo")  # type: ignore[arg-type]  # a recording port
    query = OrderQuery(idempotency_keys=frozenset({_KEY}), states=frozenset({"filled"}))
    await reads.orders(_OWNER, query, after=None, limit=5)
    assert store.asked == [(USERS["owner"], frozenset({_KEY}))]
    [read] = store.queries
    assert read.order_ids == frozenset({entry_order_id(_GROUP), _REDUCE})
    assert read.states == {"filled"} and read.idempotency_keys == {_KEY}  # the rest kept
    await reads.orders(_OWNER, OrderQuery(), after=None, limit=5)
    assert len(store.asked) == 1 and store.queries[-1].order_ids is None


async def test_keys_that_name_nothing_read_an_empty_id_set_never_every_order() -> None:
    store = _Lookup(())
    reads = OmsReads(store, "demo")  # type: ignore[arg-type]  # a recording port
    await reads.orders(_OWNER, OrderQuery(idempotency_keys=frozenset({_KEY})), after=None, limit=5)
    assert store.queries[-1].order_ids == frozenset()


async def test_a_failing_anchor_read_is_store_unavailable_and_reads_no_order() -> None:
    store = _Store(StorageTierUnavailable("down"))
    reads = OmsReads(store, "demo")  # type: ignore[arg-type]  # a recording port
    with pytest.raises(StoreUnavailable):
        await reads.orders(
            _OWNER, OrderQuery(idempotency_keys=frozenset({_KEY})), after=None, limit=5
        )
    assert [name for name, _ in store.seen] == ["anchored"]
