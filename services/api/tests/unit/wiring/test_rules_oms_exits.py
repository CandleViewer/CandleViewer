"""E35-T12 slice 3d: the reduce-only exits' adapter at the composition root (`rules_oms_exits`;
24 §11.5 "Exits", §11.6; the rulings of record on #5004, BQ-5 and BQ-6), unit by unit: the
parameters, the positions read in the owner's scope, the request built once, and the closes sent
in symbol order, each under an anchor of its own, the first that does not take effect ending the
account's action."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, cast

import pytest

from candleviewer.oms.errors import RateBudgetExceeded
from candleviewer.oms.submit import OrderRequest, SubmitContext, SubmitOutcome
from candleviewer.rules.executor.params import FlattenParams, ScaleOutParams, reduce_params
from candleviewer.rules.executor.ports import PrincipalView
from candleviewer.rules.scope import ScopeInstanceRef
from candleviewer.rules_oms_exits import (
    PreparedExit,
    RuleReduceHandler,
    StoredOpenPositions,
    owner_scope,
)
from candleviewer.rules_oms_orders import RuleOrders, SubmitCutShort
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope
from tests.rules.executor.request_builders import Facts, Principals
from tests.rules.executor.test_order_handlers import ARMER, OWNER
from tests.rules.executor.test_reduce_only_handlers import exit_request, stored
from tests.unit.oms import command_rig as cr

OTHER = uuid.UUID("9e1d2c3b-4a59-4e68-8f7a-9b0c1d2e3f40")
#: The action's `client_ref`, as the executor derives one from a fire key (`keys.client_ref`).
REF = str(uuid.uuid5(uuid.UUID(int=0x5F6E), "a fire key"))


def view(*, owner: bool) -> PrincipalView:
    return PrincipalView(
        user_id=OWNER, active=True, role="owner" if owner else "manager", is_owner=owner,
        trade_accounts=frozenset({cr.ACCOUNT}), read_at=0.0,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("params", "typed"),
    [
        ({"order_type": "market", "qty_pct": "50"}, True),
        ({"order_type": "market", "qty": 0.5}, True),  # a float as its shortest repr
        ({"order_type": "market", "qty_pct": "100.0001"}, False),
        ({"order_type": "market", "qty_pct": "50", "qty": "1"}, False),  # not both
        ({"order_type": "market"}, False),  # one of the two
        ({"order_type": "limit", "qty_pct": "50"}, False),  # a reduce-only exit is a market one
        ({"order_type": "market", "qty_pct": "50", "price": "1"}, False),  # undeclared
        ({"order_type": "market", "qty": True}, False),  # a boolean is no number
    ],
)
def test_scale_out_params_are_read_strictly(params: dict[str, Any], typed: bool) -> None:
    """24 §11.6 "The exits' parameters": a percent above 100 or a set that does not parse is no
    request, so the handler answers `invalid_params`; a decimal is read from its canonical text."""
    read = reduce_params("scale_out", params)
    assert (read is not None) == typed
    if read is not None:
        assert isinstance(read, ScaleOutParams)
        assert all(not isinstance(v, float) for v in read.model_dump().values())


def test_flatten_params_name_symbol_codes_only() -> None:
    assert reduce_params("flatten_position", {}) == FlattenParams()
    named = reduce_params("flatten_all_positions", {"symbols": ["ETHUSDT", "BTCUSDT"]})
    assert isinstance(named, FlattenParams) and named.symbols == ("ETHUSDT", "BTCUSDT")
    for odd in (["btcusdt"], [], ["BTC"], "BTCUSDT"):
        assert reduce_params("flatten_position", {"symbols": odd}) is None
    assert reduce_params("place_order", {}) is None  # not an exit


@dataclass
class Reads:
    """`OmsReads.positions` in memory, each scope it is asked in recorded."""

    rows: tuple[Any, ...] = ()
    scopes: list[Any] = field(default_factory=list)

    async def positions(self, scope: Any, query: Any) -> tuple[Any, ...]:
        self.scopes.append((scope, query))
        return self.rows


async def test_open_positions_are_read_in_the_owners_scope() -> None:
    """The owner reads as the order route's reads take it: every account for an Owner, the
    action's account alone for anyone else, which the read re-checks; and a row of another
    account is never taken for the action's."""
    reads = Reads(rows=(stored(cr.ACCOUNT), stored(OTHER)))
    port = StoredOpenPositions(reads)
    assert [
        r.exchange_account_id for r in await port.open_positions(view(owner=True), cr.ACCOUNT)
    ] == [cr.ACCOUNT]
    await port.open_positions(view(owner=False), cr.ACCOUNT)
    (owner_read, query), (granted, _) = reads.scopes
    assert owner_read == OwnerScope(OWNER) and granted == GrantScope(OWNER, frozenset({cr.ACCOUNT}))
    assert (query.accounts, query.open_only) == ((cr.ACCOUNT,), True)
    assert owner_scope(view(owner=False), OTHER) == GrantScope(OWNER, frozenset({OTHER}))


#: The request `RuleOrders.submit` builds for a fresh key (`RequestBuilder`).
Built = Callable[[], Awaitable[OrderRequest]]


@dataclass
class Orders:
    """The order port in memory: each request recorded, each answered by `answers` in turn."""

    answers: list[SubmitOutcome | BaseException] = field(default_factory=list)
    sent: list[tuple[OrderRequest, SubmitContext]] = field(default_factory=list)

    async def submit(self, account: Any, context: SubmitContext, request: Built) -> SubmitOutcome:
        self.sent.append((await request(), context))  # a fresh key's: the port builds it
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def accepted(order: int) -> SubmitOutcome:
    return SubmitOutcome(
        status=202, anchor_id=uuid.UUID(int=order + 100), order_id=uuid.UUID(int=order),
        lifecycle="submitted",
    )  # fmt: skip


@dataclass
class Held:
    rows: tuple[Any, ...] = ()

    async def open_positions(self, owner: PrincipalView, account_id: uuid.UUID) -> Any:
        return self.rows


def handler(action_type: str, orders: Orders, rows: tuple[Any, ...] = ()) -> RuleReduceHandler:
    port = cast(RuleOrders, orders)
    return RuleReduceHandler(action_type, port, Principals(frozenset({cr.ACCOUNT})), Held(rows))


async def test_a_flatten_closes_in_symbol_order_each_under_its_own_anchor() -> None:
    """Each position is closed in symbol order, then by its index, under an anchor of its own
    (`uuid5` of the action's `client_ref` and the position's key) and the action's fingerprint;
    the first close that does not take effect ends the account's action, nothing more sent."""
    rows = (
        stored(symbol="ETHUSDT", qty="1"), stored(qty="0.050", idx=2, side="Sell"),
        stored(qty="0.020", idx=1),
    )  # fmt: skip
    orders = Orders([accepted(1), accepted(2), RateBudgetExceeded(retry_after_s=1)])
    exit_ = handler("flatten_all_positions", orders, rows)
    prepared = exit_.prepare(
        exit_request("flatten_all_positions"), cr.ACCOUNT, max_notional_usd=None
    )
    answer = await exit_.send(prepared, client_ref=REF)
    assert (answer.answer, answer.blocked_by) == ("refused", "rate_limited")
    keys = [(r.symbol, r.position_idx) for r, _ in orders.sent]
    assert keys == [("BTCUSDT", 1), ("BTCUSDT", 2), ("ETHUSDT", 0)]
    anchors = [c.anchor_ref for _, c in orders.sent]
    assert anchors == [uuid.uuid5(uuid.UUID(REF), f"{s}:{i}") for s, i in keys]
    assert {(c.client_ref, c.request_sha256) for _, c in orders.sent} == {
        (uuid.UUID(REF), prepared.request_sha256)
    }
    taken = Orders([accepted(1), accepted(2)])
    done = await handler("flatten_all_positions", taken, rows[1:]).send(prepared, client_ref=REF)
    assert (done.answer, done.order_id) == ("accepted", uuid.UUID(int=1))  # the first close's


async def test_a_close_cut_short_is_in_flight_and_a_failure_no_answer() -> None:
    """A close the OMS runtime's stop cut short is `in_flight` (`unknown`), never sent again; a
    call that got no answer is `no_answer`, which `retry_once` may retry under the same key."""
    rows = (stored(qty="0.050"),)
    for raised, expected in ((SubmitCutShort(), "in_flight"), (TimeoutError(), "no_answer")):
        exit_ = handler("flatten_position", Orders([raised]), rows)
        prepared = exit_.prepare(
            exit_request("flatten_position"), cr.ACCOUNT, max_notional_usd=None
        )
        assert (await exit_.send(prepared, client_ref=REF)).answer == expected


async def test_an_exit_with_no_account_symbol_or_position_read_sends_nothing() -> None:
    """An exit that names no account, a `scale_out` with no instance symbol, and an exit whose
    position read is not bound each answer without sending: `invalid_params` for the first two,
    `position_unavailable` for the third."""
    orders = Orders()
    exit_ = handler("scale_out", orders)
    params = {"order_type": "market", "qty_pct": "10"}
    none = exit_.prepare(exit_request("scale_out", params), None, max_notional_usd=None)
    assert (await exit_.send(none, client_ref=REF)).error_code == "invalid_params"
    account_wide = replace(
        exit_request("scale_out", params), instance=ScopeInstanceRef("*@x", None, cr.ACCOUNT)
    )
    unnamed = exit_.prepare(account_wide, cr.ACCOUNT, max_notional_usd=None)
    assert (await exit_.send(unnamed, client_ref=REF)).error_code == "invalid_params"
    unbound = RuleReduceHandler(
        "flatten_position", cast(RuleOrders, orders), Principals(frozenset({cr.ACCOUNT})), None
    )
    prepared = unbound.prepare(exit_request("flatten_position"), cr.ACCOUNT, max_notional_usd=None)
    assert (await unbound.send(prepared, client_ref=REF)).error_code == "position_unavailable"
    assert orders.sent == []


async def test_a_principal_gone_since_check_5_blocks_as_permission() -> None:
    """The owner's or the armer's view gone between check 5 and `prepare` (inactive, or unread)
    refuses the exit `permission`, nothing sent, as the entries' handlers refuse an entry."""
    orders = Orders()
    principals = Principals(frozenset({cr.ACCOUNT}))
    exit_ = RuleReduceHandler(
        "flatten_position", cast(RuleOrders, orders), principals, Held((stored(),))
    )
    inactive: list[dict[uuid.UUID, Facts]] = [
        {ARMER: (False, "manager", False, frozenset())},
        {OWNER: (False, None, False, frozenset())},
    ]
    for gone in inactive:
        principals.facts = dict(gone)
        prepared = exit_.prepare(
            exit_request("flatten_position"), cr.ACCOUNT, max_notional_usd=None
        )
        answer = await exit_.send(prepared, client_ref=REF)
        assert (answer.answer, answer.blocked_by) == ("refused", "permission")
    principals.facts, principals.missing = {}, {ARMER}
    prepared = exit_.prepare(exit_request("flatten_position"), cr.ACCOUNT, max_notional_usd=None)
    assert (await exit_.send(prepared, client_ref=REF)).blocked_by == "permission"
    assert orders.sent == []


def test_a_prepared_exit_shows_nothing_of_its_request() -> None:
    """C-12.6: the prepared request's repr names neither its parameters, its account nor its
    principal; a handler of another type is refused at construction."""
    exit_ = handler("scale_out", Orders())
    prepared = exit_.prepare(
        exit_request("scale_out", {"order_type": "market", "qty": "0.012"}), cr.ACCOUNT,
        max_notional_usd=None,
    )  # fmt: skip
    assert isinstance(prepared, PreparedExit)
    shown = repr(prepared)
    assert "0.012" not in shown and str(cr.ACCOUNT) not in shown and str(OWNER) not in shown
    with pytest.raises(ValueError, match="not a reduce-only exit"):
        RuleReduceHandler("place_order", cast(RuleOrders, Orders()), Principals(), Held())
    assert isinstance(prepared.params, ScaleOutParams) and prepared.params.qty == Decimal("0.012")
