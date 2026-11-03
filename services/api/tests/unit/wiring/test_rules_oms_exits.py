"""E35-T12 slice 3d: the reduce-only exits' adapter at the composition root (`rules_oms_exits`;
24 §11.5 "Exits", §11.6; the rulings of record on #5004, BQ-5 and BQ-6), unit by unit: the
parameters, the positions read in the owner's scope, the request built once, and the closes sent
in symbol order, each under an anchor of its own: every position tried, the first close that did
not take effect answering, the exit stopping early only at the account's own refusal."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from structlog.testing import capture_logs

import candleviewer.rules_oms_exits as exits_module
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.oms.errors import (
    AccountScopeDenied,
    LotSizeViolation,
    OmsNotReady,
    OrderEntryRefused,
    RateBudgetExceeded,
    TradingDisabled,
)
from candleviewer.oms.exits import ExitOutcome
from candleviewer.oms.submit import OrderRequest, SubmitContext, SubmitOutcome
from candleviewer.oms.validator import OrderPlacementRefused
from candleviewer.rules.executor.params import (
    CancelParams,
    FlattenParams,
    ScaleOutParams,
    StopMoveParams,
    exit_params,
    reduce_params,
)
from candleviewer.rules.executor.ports import STOP_ADMITTED, Loosening, PrincipalView
from candleviewer.rules.executor.results import BLOCKED_DETAIL, OMS_DETAIL, POSITION_STOP, READ_ONLY
from candleviewer.rules.ir.models import Action
from candleviewer.rules.scope import ScopeInstanceRef
from candleviewer.rules_oms_exits import (
    PreparedExit,
    RuleAmendHandler,
    RuleBreakerCancels,
    RuleCancelHandler,
    RuleReduceHandler,
    RuleStopCheck,
    StoredOpenPositions,
    exit_answer,
    owner_scope,
    stop_level,
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
    """The order port in memory: each request recorded, each answered by `answers` in turn; a
    close whose anchor is `decided` is answered without its request built, as a repeat is."""

    answers: list[SubmitOutcome | BaseException] = field(default_factory=list)
    sent: list[tuple[OrderRequest, SubmitContext]] = field(default_factory=list)
    decided: set[uuid.UUID] = field(default_factory=set)

    async def submit(self, account: Any, context: SubmitContext, request: Built) -> SubmitOutcome:
        if context.anchor_ref not in self.decided:  # a fresh key's: the port builds it
            self.sent.append((await request(), context))
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
    a close that does not take effect is the account's answer once every position was tried."""
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


def answered(status: int, code: str, **over: Any) -> SubmitOutcome:
    """A close the OMS answered without taking it: `502 exchange_error`, or `429`."""
    return SubmitOutcome(
        status=status, anchor_id=uuid.UUID(int=0xE0), order_id=uuid.UUID(int=2), code=code, **over
    )


#: Three positions, closed as BTCUSDT:1, BTCUSDT:2, ETHUSDT:0.
THREE = (
    stored(symbol="ETHUSDT", qty="1"), stored(qty="0.050", idx=2, side="Sell"),
    stored(qty="0.020", idx=1),
)  # fmt: skip
UNKNOWN = SubmitOutcome(
    status=202, anchor_id=uuid.UUID(int=0xE1), order_id=uuid.UUID(int=2), lifecycle="unknown"
)
#: The order-entry gate's refusal, CandleViewer's own text (`OrderEntryRefusal`).
GATE = OrderEntryRefusal("maintenance", "Order entry is paused for maintenance.")


@pytest.mark.parametrize(
    ("second", "expected", "sent", "missed"),
    [
        (answered(502, "exchange_error", ret_code=10001),
         ("refused", "exchange_error", None), 3, 1),
        (LotSizeViolation(), ("refused", "lot_size_violation", None), 3, 1),
        (UNKNOWN, ("in_flight", "unknown", None), 3, 1),
        (answered(429, "exchange_rate_limited", retry_after_s=1),
         ("refused", "exchange_rate_limited", "rate_limited"), 2, 2),
        (RateBudgetExceeded(retry_after_s=1),
         ("refused", "exchange_rate_limited", "rate_limited"), 2, 2),
        (SubmitCutShort(), ("in_flight", "submit_cut_short", None), 2, 2),
        (TradingDisabled(), ("refused", "trading_disabled", "kill_switch"), 2, 2),
        (OrderEntryRefused(GATE), ("refused", "trading_disabled", "order_entry"), 2, 2),
    ],
    ids=["502", "lot-step", "unknown", "429", "rate-budget", "cut-short", "kill-switch",
         "order-entry"],
)  # fmt: skip
async def test_every_position_is_tried_and_the_first_close_not_taken_answers(
    second: SubmitOutcome | BaseException, expected: tuple[str, str, str | None], sent: int,
    missed: int,
) -> None:  # fmt: skip
    """24 §11.5 "Exits": a close that does not take effect ends that position alone, so the
    positions after it are still closed, and the account's answer is the first close that did
    not take effect, its detail counting the positions not closed (never a symbol or an id); a
    refusal that belongs to the account (`rate_limited`, `kill_switch`, `order_entry`), or a
    close the runtime's stop cut short, ends the account's action there, the positions after it
    not sent."""
    orders = Orders([accepted(1), second, accepted(3)])
    exit_ = handler("flatten_all_positions", orders, THREE)
    prepared = exit_.prepare(
        exit_request("flatten_all_positions"), cr.ACCOUNT, max_notional_usd=None
    )
    answer = await exit_.send(prepared, client_ref=REF)
    assert (answer.answer, answer.error_code, answer.blocked_by) == expected
    assert len(orders.sent) == sent
    verb = "was" if missed == 1 else "were"
    assert answer.detail == f"Not done — {missed} of 3 positions {verb} not closed."
    assert "BTCUSDT" not in answer.detail and "ETHUSDT" not in answer.detail


@pytest.mark.parametrize(
    ("raised", "detail"),
    [(OrderPlacementRefused(reason_code=None, reason_text=None), OMS_DETAIL[READ_ONLY]),
     (LotSizeViolation(), None)],
    ids=["read-only", "lot-step"],
)  # fmt: skip
async def test_a_lone_position_not_closed_answers_with_its_own_detail(
    raised: Exception, detail: str | None
) -> None:
    """24 §11.5 "Exits": the count of the positions not closed is given only when there was more
    than one to close; a lone position whose close does not take effect answers with that close's
    own detail (the read-only gate's sentence, or none), never "1 of 1"."""
    orders = Orders([raised])
    exit_ = handler("flatten_position", orders, (stored(qty="0.050"),))
    prepared = exit_.prepare(exit_request("flatten_position"), cr.ACCOUNT, max_notional_usd=None)
    answer = await exit_.send(prepared, client_ref=REF)
    assert (answer.answer, answer.detail, len(orders.sent)) == ("refused", detail, 1)


async def test_the_actions_bound_cuts_an_exit_short_and_sends_no_later_close() -> None:
    """24 §11.5 "Exits": the read and every close share the action's bound; a cancel between two
    closes ends the exit there (the engine records it `unknown`), the later positions not sent."""
    orders = Orders([accepted(1), asyncio.CancelledError()])
    exit_ = handler("flatten_all_positions", orders, THREE)
    prepared = exit_.prepare(
        exit_request("flatten_all_positions"), cr.ACCOUNT, max_notional_usd=None
    )
    with pytest.raises(asyncio.CancelledError):
        await exit_.send(prepared, client_ref=REF)
    assert len(orders.sent) == 2


async def test_a_repeat_is_answered_from_its_anchor_whatever_the_position_holds_now() -> None:
    """24 §11.5 "Exits": a `scale_out` quantity is judged as its close is built, for a fresh key
    alone: a repeat whose anchor is decided is answered from it though the position is now
    smaller than the quantity, nothing built; a fresh key's quantity above the position is
    `exceeds_position`, nothing sent."""
    row, params = stored(qty="0.020"), {"order_type": "market", "qty": "0.050"}
    request = exit_request("scale_out", params)
    decided = {uuid.uuid5(uuid.UUID(REF), f"{cr.SYMBOL}:0")}
    replay = Orders([accepted(7)], decided=decided)
    exit_ = handler("scale_out", replay, (row,))
    prepared = exit_.prepare(request, cr.ACCOUNT, max_notional_usd=None)
    answer = await exit_.send(prepared, client_ref=REF)
    assert (answer.answer, answer.order_id) == ("accepted", uuid.UUID(int=7))
    assert replay.sent == [] and replay.answers == []
    fresh = Orders([accepted(8)])
    first = handler("scale_out", fresh, (row,))
    refused = await first.send(
        first.prepare(request, cr.ACCOUNT, max_notional_usd=None), client_ref=REF
    )
    assert (refused.answer, refused.error_code) == ("refused", "exceeds_position")
    assert fresh.sent == [] and len(fresh.answers) == 1


@dataclass
class Denied:
    """A position read the OMS refuses for scope: the owner may no longer read the account."""

    async def open_positions(self, owner: PrincipalView, account_id: uuid.UUID) -> Any:
        raise AccountScopeDenied


async def test_a_position_read_refused_for_scope_blocks_as_permission() -> None:
    """An owner whose grant on the account went since check 5, so the reads refuse for scope, is
    refused `permission`, as a principal gone since check 5 is, never `position_unavailable`;
    nothing is sent."""
    orders = Orders()
    exit_ = RuleReduceHandler(
        "flatten_position", cast(RuleOrders, orders), Principals(frozenset({cr.ACCOUNT})), Denied()
    )
    prepared = exit_.prepare(exit_request("flatten_position"), cr.ACCOUNT, max_notional_usd=None)
    answer = await exit_.send(prepared, client_ref=REF)
    assert (answer.answer, answer.blocked_by) == ("refused", "permission") and orders.sent == []


async def test_an_exit_with_no_account_symbol_or_position_read_sends_nothing() -> None:
    """An exit that names no account, an exit that needs the instance's symbol on an
    account-wide instance (a `scale_out`, or a `flatten_position` naming no `symbols`, though
    positions are held), and an exit whose position read is not bound each answer without
    sending: `invalid_params` for the first two, `position_unavailable` for the third."""
    orders = Orders()
    exit_ = handler("scale_out", orders)
    params = {"order_type": "market", "qty_pct": "10"}
    none = exit_.prepare(exit_request("scale_out", params), None, max_notional_usd=None)
    assert (await exit_.send(none, client_ref=REF)).error_code == "invalid_params"
    wide = ScopeInstanceRef("*@x", None, cr.ACCOUNT)
    account_wide = replace(exit_request("scale_out", params), instance=wide)
    unnamed = exit_.prepare(account_wide, cr.ACCOUNT, max_notional_usd=None)
    assert (await exit_.send(unnamed, client_ref=REF)).error_code == "invalid_params"
    flatten = handler("flatten_position", orders, (stored(),))
    unnamed = flatten.prepare(
        replace(exit_request("flatten_position"), instance=wide), cr.ACCOUNT,
        max_notional_usd=None,
    )  # fmt: skip
    assert (await flatten.send(unnamed, client_ref=REF)).error_code == "invalid_params"
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


def test_a_rule_principal_shows_nothing_of_its_users() -> None:
    """C-12.6: the principal an exit acts as names neither the owner, the armer nor the rule in
    its repr, as the prepared exit does not."""
    exit_ = handler("flatten_position", Orders())
    prepared = exit_.prepare(exit_request("flatten_position"), cr.ACCOUNT, max_notional_usd=None)
    assert isinstance(prepared, PreparedExit) and prepared.principal is not None
    shown = repr(prepared.principal)
    assert str(OWNER) not in shown and str(ARMER) not in shown and "owner" not in shown


# --- slice 3e ----------------------------------------------------------------------------------


def _move(mode: str, value: str = "100") -> StopMoveParams:
    return StopMoveParams(mode=mode, value=Decimal(value))  # type: ignore[arg-type]  # the Literal's member, as the model reads it


@pytest.mark.parametrize(
    ("mode", "kind", "side", "snapshot", "level"),
    [
        ("absolute", "stop_loss", "Buy", {}, "100"),
        ("offset_from_entry", "stop_loss", "Buy", {}, "59900"),
        ("offset_from_entry", "stop_loss", "Sell", {}, "60100"),
        ("offset_from_entry", "take_profit", "Buy", {}, "60100"),
        ("offset_from_entry", "take_profit", "Sell", {}, "59900"),
        ("offset_from_price", "stop_loss", "Buy", {"price": Decimal("61000")}, "60900"),
        ("atr", "stop_loss", "Buy", {"atr": Decimal("2")}, "59800"),
        ("atr", "take_profit", "Sell", {"atr": Decimal("2")}, "59800"),
        ("structure", "stop_loss", "Buy", {"swing_low": Decimal("59000")}, "58900"),
        ("structure", "stop_loss", "Sell", {"swing_high": Decimal("61000")}, "61100"),
        ("structure", "take_profit", "Buy", {"swing_high": Decimal("61000")}, "60900"),
        ("structure", "take_profit", "Sell", {"swing_low": Decimal("59000")}, "59100"),
    ],
)
def test_stop_level_sets_each_mode_on_its_protective_or_profitable_side(
    mode: str, kind: Any, side: Any, snapshot: dict[str, Any], level: str
) -> None:
    """BQ-9 (24 §11.5 "Exits"): each mode's level from the order's price (60000) or the fire's
    snapshot, a stop on the protective side, a take-profit on the profitable one."""
    got = stop_level(_move(mode), kind=kind, side=side, price=Decimal("60000"), snapshot=snapshot)
    assert got == Decimal(level)


@pytest.mark.parametrize("mode", ["offset_from_price", "atr", "structure"])
def test_a_level_the_snapshot_cannot_give_is_none(mode: str) -> None:
    """A snapshot without the metric, or with one that is no finite decimal, gives no level, so
    the amend fails `metric_unavailable`; an entry with no price gives no offset from it."""
    for snapshot in ({}, {"price": None, "atr": "2", "swing_low": Decimal("NaN")}):
        assert (
            stop_level(
                _move(mode), kind="stop_loss", side="Buy", price=Decimal(1), snapshot=snapshot
            )
            is None
        )
    assert (
        stop_level(
            _move("offset_from_entry"), kind="stop_loss", side="Buy", price=None, snapshot={}
        )
        is None
    )


def test_exit_answer_maps_the_exit_services_answers() -> None:
    """24 §11.5, §11.9: taken is `accepted` with its order; not known `in_flight`, never sent
    again; a refusal that sent nothing `pre_anchor`; a rate limit `rate_limited`; the amend
    ratchet's `risk_limit_breached`, the writer's refusal of a looser stop, `native_sl`."""
    order = uuid.UUID(int=0xE1)
    cases = [
        (ExitOutcome(kind="accepted", status=202), ("accepted", None, None)),
        (ExitOutcome(kind="unknown", status=202, unknown_reason="timeout"),
         ("in_flight", "timeout", None)),
        (ExitOutcome(kind="refused", status=503, code="store_unavailable"),
         ("pre_anchor", "store_unavailable", None)),
        (ExitOutcome(kind="refused", status=429, code="exchange_rate_limited"),
         ("refused", "exchange_rate_limited", "rate_limited")),
        (ExitOutcome(kind="refused", status=403, code="risk_limit_breached"),
         ("refused", "risk_limit_breached", "native_sl")),
        (ExitOutcome(kind="refused", status=409, code="conflict"), ("refused", "conflict", None)),
    ]  # fmt: skip
    for outcome, expected in cases:
        answer = exit_answer(outcome, order)
        assert (answer.answer, answer.error_code, answer.blocked_by) == expected
        assert answer.order_id == order


@dataclass
class Reading:
    """`RuleEntries` answering fixed rows; each call recorded."""

    rows: tuple[Any, ...] = ()
    calls: list[tuple[uuid.UUID, Any, Any]] = field(default_factory=list)
    limits: list[int] = field(default_factory=list)

    async def rule_resting_entries(
        self, rule_id: uuid.UUID, environment: Any, *, account_id: Any = None,
        symbol: Any = None, limit: int,
    ) -> tuple[Any, ...]:  # fmt: skip
        self.calls.append((rule_id, account_id, symbol))
        self.limits.append(limit)
        return self.rows


def _entry(**over: Any) -> Any:
    """A resting limit buy entry as the read returns it, its stop at 58000."""
    base = replace(
        cast(Any, cr.new_order(seq=over.pop("seq", 1))), lifecycle_state="submitted",
        state="accepted",
    )  # fmt: skip
    return SimpleNamespace(**{**{f: getattr(base, f) for f in base.__dataclass_fields__}, **over})


async def test_the_stop_check_judges_each_exit_as_check_8_says() -> None:
    """24 §11.5 check 8 (BQ-2, BQ-4): a cancel naming a stop-loss is `native_sl`, any other
    admitted; a type the port does not know `native_sl`; an amend whose parameters do not parse
    admitted (the handler fails it); `only_tighten: false` `native_sl` with its loosening; no
    target `unavailable`, its detail the position's, a partly filled or a market entry being no
    target (BQ-9: an amend moves a resting limit entry); a take-profit move with a target
    admitted."""
    held = Held((stored(),))
    check = RuleStopCheck(Principals(frozenset({cr.ACCOUNT})), Reading(), held, "demo")

    async def judge(action_type: str, params: dict[str, Any]) -> Any:
        return await check.judge(exit_request(action_type, params), cr.ACCOUNT)

    assert (await judge("cancel_order", {"purpose": "stop_loss"})).refused == "native_sl"
    assert await judge("cancel_all_orders", {"purpose": "entry"}) == STOP_ADMITTED
    assert (await judge("flatten_position", {})).refused == "native_sl"
    assert await judge("modify_stop_loss", {"mode": "nearest"}) == STOP_ADMITTED
    loose = await judge("tighten_stop", {"mode": "absolute", "value": 1, "only_tighten": False})
    assert (loose.refused, loose.loosening) == ("native_sl", Loosening(symbol=cr.SYMBOL))
    none = await judge("modify_take_profit", {"mode": "absolute", "value": 63000})
    assert (none.refused, none.detail) == ("unavailable", POSITION_STOP)
    unmoved = (
        _entry(lifecycle_state="partially_filled", state="partially_filled"),
        _entry(seq=2, order_type="Market"),
    )
    check = RuleStopCheck(Principals(frozenset({cr.ACCOUNT})), Reading(unmoved), held, "demo")
    moved = await judge("modify_stop_loss", {"mode": "absolute", "value": 58600})
    assert (moved.refused, moved.detail) == ("unavailable", POSITION_STOP)
    check = RuleStopCheck(Principals(frozenset({cr.ACCOUNT})), Reading((_entry(),)), held, "demo")
    assert await judge("modify_take_profit", {"mode": "absolute", "value": 63000}) == STOP_ADMITTED


async def test_the_stop_check_compares_with_the_orders_stop_and_the_positions() -> None:
    """The amend writer's comparison (`stop_ratchet`): a level looser than the order's own stop,
    or than its position's stop at the venue on the same side, is `native_sl` with the stop it
    would loosen and the level asked; a tighter one admitted; a level the snapshot cannot give is
    left to the handler; a read that raises reaches the executor's bound (fail closed)."""
    entry = _entry()
    reading = Reading((entry,))
    held = Held((stored(stop=Decimal("58500")),))
    check = RuleStopCheck(Principals(frozenset({cr.ACCOUNT})), reading, held, "demo")

    async def judge(value: str, **params: Any) -> Any:
        move = {"mode": "absolute", "value": value} | params
        return await check.judge(exit_request("modify_stop_loss", move), cr.ACCOUNT)

    order_loose = await judge("57000")
    assert order_loose.loosening == Loosening(
        order_id=entry.id, symbol=cr.SYMBOL, before=Decimal("58000"), after=Decimal("57000")
    )
    position_loose = await judge("58200")  # tighter than the order's, looser than the position's
    assert (position_loose.refused, position_loose.loosening.before) == (
        "native_sl", Decimal("58500"),
    )  # fmt: skip
    assert await judge("58600") == STOP_ADMITTED
    assert await judge("100", mode="atr") == STOP_ADMITTED  # no `atr` in the snapshot
    for mode in ("Partial", None):  # only a Full-mode stop covers the whole position
        held.rows = (replace(stored(stop=Decimal("58500")), tpsl_mode=mode),)
        assert await judge("58200") == STOP_ADMITTED, mode
    reading.rows = ()
    check._entries = None
    with pytest.raises(LookupError):
        await judge("58600")


@dataclass
class Exits:
    """The exit service as the breaker drives it: each cancel answered by `answers` in turn."""

    answers: list[Any] = field(default_factory=list)
    cancelled: list[tuple[uuid.UUID, str, Any, Any]] = field(default_factory=list)

    async def cancel_admitted(
        self, row: Any, *, actor: Any, reason: Any, request_id: Any, origin: Any = None
    ) -> ExitOutcome:
        self.cancelled.append((row.id, reason, actor, origin))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, asyncio.Event):
            await answer.wait()
        return cast(ExitOutcome, answer)


@dataclass
class Alerts:
    counted: list[tuple[str, int, int | None]] = field(default_factory=list)

    async def breaker_cancels(
        self, rule_id: str, run_id: uuid.UUID, node_id: str, *, sent: int, not_done: int | None
    ) -> None:
        self.counted.append((node_id, sent, not_done))


class Composed:
    def __init__(self, exits: Exits) -> None:
        self.exits = exits


async def test_the_breaker_cancels_count_the_ones_not_done(monkeypatch: pytest.MonkeyPatch) -> None:
    """BQ-10: the tripped rule's resting entries are cancelled, each with the reason
    `rule_circuit_breaker` as the owner, every account read (no account named); a refusal, a
    raise and a wait past the bound are each counted not done; a read that fails is reported
    unread; the origin names the tripped rule, `circuit_breaker` in place of a node id the
    origin refuses, and the report names the node as the origin does; with no owner view read,
    the role is `unknown`."""
    monkeypatch.setattr(exits_module, "BREAKER_CANCEL_TIMEOUT_S", 0.0)
    rows = tuple(_entry(seq=n) for n in range(4))
    exits = Exits([
        ExitOutcome(kind="accepted", status=202), ExitOutcome(kind="refused", status=409),
        ConnectionError("lost"), asyncio.Event(),
    ])  # fmt: skip
    alerts, reading = Alerts(), Reading(rows)
    principals = Principals(frozenset({cr.ACCOUNT}))
    breaker = RuleBreakerCancels(
        lambda: cast(Any, Composed(exits)), principals, reading, "demo", alerts
    )
    await breaker.cancel_resting(exit_request("scale_out", node="x9"))
    assert alerts.counted == [("x9", 4, 3)] and reading.calls[0][1:] == (None, None)
    assert {reason for _, reason, _, _ in exits.cancelled} == {"rule_circuit_breaker"}
    _id, _reason, actor, origin = exits.cancelled[0]
    assert (actor.user_id, actor.role, origin.node_id, origin.version) == (OWNER, "owner", "x9", 1)
    assert (origin.armed_by, origin.armed_by_role) == (ARMER, "owner")  # the closed role set
    principals.missing, alerts.counted = {OWNER, ARMER}, []
    odd = replace(
        exit_request("scale_out"),
        payload=Action.model_construct(
            **(exit_request("scale_out").payload.model_dump() | {"node_id": "no such node"})
        ),
    )
    once = Exits([ExitOutcome(kind="accepted", status=202)])
    single = RuleBreakerCancels(
        lambda: cast(Any, Composed(once)), principals, Reading(rows[:1]), "demo", alerts
    )
    await single.cancel_resting(odd)
    [(_, _, actor, origin)] = once.cancelled
    assert (actor.role, origin.node_id, origin.armed_by) == ("unknown", "circuit_breaker", None)
    assert alerts.counted == [("circuit_breaker", 1, 0)]  # the node as the origin names it
    unread = RuleBreakerCancels(
        lambda: cast(Any, Composed(Exits())), principals, None, "demo", alerts
    )
    await unread.cancel_resting(exit_request("scale_out", node="x8"))
    assert alerts.counted[-1] == ("x8", 0, None)


async def test_a_rule_cancel_tries_every_order_and_answers_the_first_not_taken() -> None:
    """A cancel tries each selected order, even past one not taken (a cancel adds no exposure),
    and answers the first that was not; an unread read is `pre_anchor` (`store_unavailable`),
    which `retry_once` may retry; no runtime is `pre_anchor` (`oms_not_ready`)."""
    rows = (_entry(seq=1), _entry(seq=2), _entry(seq=3))
    exits = Exits([
        ExitOutcome(kind="accepted", status=202),
        ExitOutcome(kind="refused", status=429, code="exchange_rate_limited"),
        ExitOutcome(kind="accepted", status=202),
    ])  # fmt: skip
    principals = Principals(frozenset({cr.ACCOUNT}))
    cancel = RuleCancelHandler(
        "cancel_all_orders", lambda: cast(Any, Composed(exits)), principals, Reading(rows), "demo"
    )
    prepared = cancel.prepare(exit_request("cancel_all_orders"), cr.ACCOUNT, max_notional_usd=None)
    answer = await cancel.send(prepared, client_ref=REF)
    assert (answer.answer, answer.blocked_by, answer.order_id) == (
        "refused", "rate_limited", rows[1].id,
    )  # fmt: skip
    assert [i for i, *_ in exits.cancelled] == [r.id for r in rows]
    assert {reason for _, reason, _, _ in exits.cancelled} == {"rule"}
    unread = RuleCancelHandler("cancel_order", lambda: None, principals, None, "demo")
    prepared = unread.prepare(exit_request("cancel_order"), cr.ACCOUNT, max_notional_usd=None)
    assert (await unread.send(prepared, client_ref=REF)).error_code == "store_unavailable"
    absent = RuleCancelHandler("cancel_order", lambda: None, principals, Reading(rows), "demo")
    prepared = absent.prepare(exit_request("cancel_order"), cr.ACCOUNT, max_notional_usd=None)
    assert (await absent.send(prepared, client_ref=REF)).error_code == "oms_not_ready"
    for wrong, kind in (("tighten_stop", RuleCancelHandler), ("cancel_order", RuleAmendHandler)):
        with pytest.raises(ValueError, match="is not a rule's"):
            kind(wrong, lambda: None, principals, None, "demo")


async def test_an_armers_role_outside_the_closed_role_set_is_refused_as_permission() -> None:
    """The origin carries the armer's role as one of the closed role set (`Role`, the `role_name`
    enum): a view naming any other role names no armer the OMS takes, so the exit is refused
    `permission` at `prepare`, nothing read or sent, as a view gone since check 5 is."""
    orders = Orders()
    principals = Principals(frozenset({cr.ACCOUNT}))
    principals.facts[ARMER] = (True, "auditor", False, frozenset({cr.ACCOUNT}))
    exit_ = RuleReduceHandler(
        "flatten_position", cast(RuleOrders, orders), principals, Held((stored(),))
    )
    prepared = exit_.prepare(exit_request("flatten_position"), cr.ACCOUNT, max_notional_usd=None)
    answer = await exit_.send(prepared, client_ref=REF)
    assert (answer.answer, answer.blocked_by) == ("refused", "permission") and orders.sent == []


def test_exit_params_read_the_cancels_and_the_amends_strictly() -> None:
    """24 §11.6 (E35-T12): a cancel's `purpose` is one of the intents, an amend's `mode` one of
    the five, its `value` above zero and `only_tighten` a strict boolean, on unless written off;
    anything else, or a type that is no exit, reads as nothing (`invalid_params` at `prepare`)."""
    assert exit_params("cancel_order", {"purpose": "entry"}) == CancelParams(purpose="entry")
    assert exit_params("cancel_all_orders", {}) == CancelParams()
    move = exit_params("tighten_stop", {"mode": "atr", "value": "1.5"})
    assert isinstance(move, StopMoveParams)
    assert (move.mode, move.value, move.only_tighten) == ("atr", Decimal("1.5"), True)
    refused: list[tuple[str, dict[str, Any]]] = [
        ("cancel_order", {"purpose": "hedge"}),
        ("modify_stop_loss", {"mode": "absolute", "value": "0"}),
        ("modify_stop_loss", {"mode": "absolute", "value": "1", "only_tighten": "false"}),
        ("modify_take_profit", {"mode": "nearest", "value": "1"}),
        ("place_order", {}),
    ]
    for action_type, params in refused:
        assert exit_params(action_type, params) is None, action_type


class NotReady:
    """A composed runtime whose exit service is not open yet."""

    @property
    def exits(self) -> Any:
        raise OmsNotReady()


@dataclass
class Amends:
    """The exit service as a rule's amend drives it: `scope` answers `scoped` (the exit service's
    refusal) or the order, and `amend` answers or raises each of `answers` in turn, then `answer`;
    each amend recorded."""

    scoped: ExitOutcome | None = None
    answer: Any = None
    asked: list[Any] = field(default_factory=list)
    answers: list[Any] = field(default_factory=list)

    async def scope(self, caller: Any, order_id: uuid.UUID) -> Any:
        return self.scoped if self.scoped is not None else SimpleNamespace(order_id=order_id)

    async def amend(self, scoped: Any, terms: Any, *, caller: Any, expected_seq: Any) -> Any:
        self.asked.append(terms)
        answer = self.answers.pop(0) if self.answers else self.answer
        if isinstance(answer, BaseException):
            raise answer
        return answer


async def test_a_rule_cancel_the_exit_service_does_not_take_answers_and_never_raises() -> None:
    """A cancel whose parameters do not parse is `invalid_params`, nothing read; an exit service
    not open yet, before the call or at it, is `pre_anchor` (`oms_not_ready`), which `retry_once`
    may retry; a call that fails is `no_answer`, named by no text of its error."""
    principals, reading = Principals(frozenset({cr.ACCOUNT})), Reading((_entry(),))
    odd = RuleCancelHandler("cancel_order", lambda: None, principals, reading, "demo")
    hedge = exit_request("cancel_order", {"purpose": "hedge"})
    prepared = odd.prepare(hedge, cr.ACCOUNT, max_notional_usd=None)
    assert (await odd.send(prepared, client_ref=REF)).error_code == "invalid_params"
    assert reading.calls == []

    async def send(runtime: Any) -> Any:
        cancel = RuleCancelHandler("cancel_order", lambda: runtime, principals, reading, "demo")
        prepared = cancel.prepare(exit_request("cancel_order"), cr.ACCOUNT, max_notional_usd=None)
        return await cancel.send(prepared, client_ref=REF)

    shut = await send(NotReady())
    assert (shut.answer, shut.error_code) == ("pre_anchor", "oms_not_ready")
    closing = await send(Composed(Exits([OmsNotReady()])))
    assert (closing.answer, closing.error_code) == ("pre_anchor", "oms_not_ready")
    lost = await send(Composed(Exits([ConnectionError("planted text")])))
    assert (lost.answer, lost.error_code) == ("no_answer", "internal_error")
    assert "planted" not in repr(lost)


async def test_a_rule_amend_the_exit_service_does_not_take_answers_and_never_raises() -> None:
    """An amend whose entries are not read is `pre_anchor` (`store_unavailable`); one that finds
    no resting entry by the time it is sent answers as check 8 does (`unavailable`), nothing
    sent; an exit service not open yet, before the call or at it, is `pre_anchor`
    (`oms_not_ready`); the exit service's refusal at its scope is the answer, nothing amended;
    a call that fails is `no_answer`."""
    principals, resting = Principals(frozenset({cr.ACCOUNT})), Reading((_entry(),))
    move = exit_request("modify_stop_loss", {"mode": "absolute", "value": "58600"})

    async def send(entries: Any, runtime: Any) -> Any:
        amend = RuleAmendHandler("modify_stop_loss", lambda: runtime, principals, entries, "demo")
        prepared = amend.prepare(move, cr.ACCOUNT, max_notional_usd=None)
        return await amend.send(prepared, client_ref=REF)

    assert (await send(None, None)).error_code == "store_unavailable"
    none = await send(Reading(), None)
    assert (none.answer, none.blocked_by, none.detail) == (
        "refused", "unavailable", BLOCKED_DETAIL[POSITION_STOP],
    )  # fmt: skip
    assert (await send(resting, None)).error_code == "oms_not_ready"
    assert (await send(resting, NotReady())).error_code == "oms_not_ready"
    final = Amends(scoped=ExitOutcome(kind="refused", status=409, code="order_not_amendable"))
    answer = await send(resting, Composed(cast(Any, final)))
    assert (answer.answer, answer.error_code) == ("refused", "order_not_amendable")
    assert final.asked == []
    for raised, expected in (
        (OmsNotReady(), ("pre_anchor", "oms_not_ready")),
        (ConnectionError("planted text"), ("no_answer", "internal_error")),
    ):
        failing = Amends(answer=raised)
        answer = await send(resting, Composed(cast(Any, failing)))
        assert (answer.answer, answer.error_code) == expected and len(failing.asked) == 1


async def test_the_stop_check_with_the_positions_stops_unread_raises_to_check_8() -> None:
    """A stop move's check whose positions' stops cannot be read (no read bound, or the owner's
    view gone) raises, which check 8's bound refuses `native_sl` (fail closed)."""
    principals = Principals(frozenset({cr.ACCOUNT}))
    move = exit_request("modify_stop_loss", {"mode": "absolute", "value": "58600"})
    unbound = RuleStopCheck(principals, Reading((_entry(),)), None, "demo")
    with pytest.raises(LookupError):
        await unbound.judge(move, cr.ACCOUNT)
    principals.missing = {OWNER}
    gone = RuleStopCheck(principals, Reading((_entry(),)), Held((stored(),)), "demo")
    with pytest.raises(LookupError):
        await gone.judge(move, cr.ACCOUNT)


async def test_the_breakers_origin_skips_an_unread_armer_and_refuses_a_bad_version() -> None:
    """The breaker's origin: an armer id that is no user id names no armer (its cancels still
    sent, as the owner); a rule version the origin refuses names no origin, so no cancel starts:
    the trip pages P1 once more, naming the rule, and nothing is read or sent."""
    principals = Principals(frozenset({cr.ACCOUNT}))
    once, alerts = Exits([ExitOutcome(kind="accepted", status=202)]), Alerts()
    breaker = RuleBreakerCancels(
        lambda: cast(Any, Composed(once)), principals, Reading((_entry(),)), "demo", alerts
    )
    await breaker.cancel_resting(replace(exit_request("scale_out"), armed_by="no user id"))
    [(_, reason, actor, origin)] = once.cancelled
    assert (reason, actor.user_id, origin.armed_by, origin.armed_by_role) == (
        "rule_circuit_breaker", OWNER, None, None,
    )  # fmt: skip
    assert alerts.counted == [("x1", 1, 0)]
    never = Exits()
    refusing = RuleBreakerCancels(
        lambda: cast(Any, Composed(never)), principals, Reading((_entry(),)), "demo", alerts
    )
    with capture_logs() as logs:
        await refusing.cancel_resting(replace(exit_request("scale_out"), version=0))
    [page] = [e for e in logs if e["event"] == "rules.breaker_cancels_not_started"]
    assert (page["log_level"], page["cv_page"], page["reason"]) == (
        "critical", True, "origin_refused",
    )  # fmt: skip
    assert page["rule_id"] == exit_request("scale_out").rule_id
    assert never.cancelled == [] and alerts.counted == [("x1", 1, 0)]


async def test_a_cancel_selects_by_purpose_and_never_a_stop_a_take_profit_or_an_exit() -> None:
    """24 §11.5 "Exits" and §11.6: of the rule's rows whose intents are `entry`, `scale_in`,
    `stop_loss`, `take_profit` and `flatten`, a cancel with no `purpose` cancels `entry` and
    `scale_in` alone, `purpose: scale_in` that row alone, and `purpose: take_profit` or
    `stop_loss` none: the handler's own guard keeps a stop, a take-profit and an exit out
    whatever the read hands it (C-2.6)."""
    intents = ("entry", "scale_in", "stop_loss", "take_profit", "flatten")
    rows = tuple(_entry(seq=n, intent=i) for n, i in enumerate(intents, start=1))
    by_id = {row.id: row.intent for row in rows}

    async def cancelled(params: dict[str, Any]) -> tuple[list[str], str]:
        exits = Exits([ExitOutcome(kind="accepted", status=202)] * 2)
        cancel = RuleCancelHandler(
            "cancel_all_orders", lambda: cast(Any, Composed(exits)),
            Principals(frozenset({cr.ACCOUNT})), Reading(rows), "demo",
        )  # fmt: skip
        req = exit_request("cancel_all_orders", params)
        answer = await cancel.send(
            cancel.prepare(req, cr.ACCOUNT, max_notional_usd=None), client_ref=REF
        )
        return [by_id[i] for i, *_ in exits.cancelled], answer.answer

    assert await cancelled({}) == (["entry", "scale_in"], "accepted")
    assert await cancelled({"purpose": "scale_in"}) == (["scale_in"], "accepted")
    assert await cancelled({"purpose": "take_profit"}) == ([], "done")
    assert await cancelled({"purpose": "stop_loss"}) == ([], "done")


async def test_a_selection_past_the_cap_is_never_ok_and_never_counted_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """24 §11.5 "Exits", §11.7: the read holds one row past `RULE_ENTRIES_LIMIT`, so a selection
    the cap stops is seen: `cancel_all_orders` cancels the orders within the cap and answers
    `too_many_orders`, never `ok`; the breaker counts the overflow not done, so the trip's
    incident gets its row."""
    monkeypatch.setattr(exits_module, "RULE_ENTRIES_LIMIT", 2)
    rows = tuple(_entry(seq=n) for n in (1, 2, 3))  # the cap, and one more
    principals, reading = Principals(frozenset({cr.ACCOUNT})), Reading(rows)
    exits = Exits([ExitOutcome(kind="accepted", status=202)] * 2)
    cancel = RuleCancelHandler(
        "cancel_all_orders", lambda: cast(Any, Composed(exits)), principals, reading, "demo"
    )
    prepared = cancel.prepare(exit_request("cancel_all_orders"), cr.ACCOUNT, max_notional_usd=None)
    answer = await cancel.send(prepared, client_ref=REF)
    assert (answer.answer, answer.error_code) == ("refused", "too_many_orders")
    assert [i for i, *_ in exits.cancelled] == [rows[0].id, rows[1].id] and reading.limits == [3]
    once, alerts = Exits([ExitOutcome(kind="accepted", status=202)] * 2), Alerts()
    breaker = RuleBreakerCancels(
        lambda: cast(Any, Composed(once)), principals, Reading(rows), "demo", alerts
    )
    await breaker.cancel_resting(exit_request("scale_out", node="x9"))
    assert len(once.cancelled) == 2 and alerts.counted == [("x9", 2, 1)]


async def test_the_breaker_never_cancels_a_reduce_only_exit_or_a_take_profit_it_reads() -> None:
    """24 §11.7, C-2.6: the breaker keeps a filter of its own beside the read's: a reduce-only
    close, a reduce-only order the OMS classed as an opening entry (no position shown to reduce)
    and a take-profit row the read hands it never reach `cancel_admitted`, and the rule's entry is
    cancelled."""
    entry = _entry(seq=1)
    close = _entry(seq=2, reduce_only=True, intent="flatten")
    take_profit = _entry(seq=3, intent="take_profit")
    opening = _entry(seq=4, reduce_only=True, intent="entry")
    once, alerts = Exits([ExitOutcome(kind="accepted", status=202)]), Alerts()
    breaker = RuleBreakerCancels(
        lambda: cast(Any, Composed(once)), Principals(frozenset({cr.ACCOUNT})),
        Reading((entry, close, take_profit, opening)), "demo", alerts,
    )  # fmt: skip
    await breaker.cancel_resting(exit_request("scale_out", node="x7"))
    assert [i for i, *_ in once.cancelled] == [entry.id] and alerts.counted == [("x7", 1, 0)]


async def test_a_rule_amend_tries_every_entry_and_answers_the_first_not_taken() -> None:
    """24 §11.5 "Exits": an amend, as a cancel, tries every entry it selected, even past one not
    taken (an exit only reduces risk), and answers the first that was not once all were tried;
    check 8 judged each level first, so no entry is amended unjudged (C-2.6)."""
    rows = (_entry(seq=1), _entry(seq=2), _entry(seq=3))
    amends = Amends(answers=[
        ExitOutcome(kind="accepted", status=202),
        ExitOutcome(kind="refused", status=409, code="order_not_amendable"),
        ExitOutcome(kind="accepted", status=202),
    ])  # fmt: skip
    amend = RuleAmendHandler(
        "modify_stop_loss", lambda: cast(Any, Composed(cast(Any, amends))),
        Principals(frozenset({cr.ACCOUNT})), Reading(rows), "demo",
    )  # fmt: skip
    move = exit_request("modify_stop_loss", {"mode": "absolute", "value": "58600"})
    prepared = amend.prepare(move, cr.ACCOUNT, max_notional_usd=None)
    answer = await amend.send(prepared, client_ref=REF)
    assert (answer.answer, answer.error_code, answer.order_id) == (
        "refused", "order_not_amendable", rows[1].id,
    )  # fmt: skip
    assert len(amends.asked) == 3


async def test_a_selection_of_exactly_the_cap_is_ok_and_counts_nothing_not_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """24 §11.5 "Exits", §11.7: a read that holds exactly `RULE_ENTRIES_LIMIT` rows has nothing
    past the cap: `cancel_all_orders` cancels each and is `ok`, and the breaker counts none not
    done."""
    monkeypatch.setattr(exits_module, "RULE_ENTRIES_LIMIT", 2)
    rows = (_entry(seq=1), _entry(seq=2))  # the cap, and none more
    principals = Principals(frozenset({cr.ACCOUNT}))
    exits = Exits([ExitOutcome(kind="accepted", status=202)] * 2)
    cancel = RuleCancelHandler(
        "cancel_all_orders", lambda: cast(Any, Composed(exits)), principals, Reading(rows), "demo"
    )
    prepared = cancel.prepare(exit_request("cancel_all_orders"), cr.ACCOUNT, max_notional_usd=None)
    answer = await cancel.send(prepared, client_ref=REF)
    assert (answer.answer, len(exits.cancelled)) == ("accepted", 2)
    once, alerts = Exits([ExitOutcome(kind="accepted", status=202)] * 2), Alerts()
    breaker = RuleBreakerCancels(
        lambda: cast(Any, Composed(once)), principals, Reading(rows), "demo", alerts
    )
    await breaker.cancel_resting(exit_request("scale_out", node="x9"))
    assert alerts.counted == [("x9", 2, 0)]


async def test_a_take_profit_move_with_only_tighten_off_leaves_the_orders_stop() -> None:
    """24 §11.5 check 8: `only_tighten: false` asks for a loosening on a stop move alone; a
    take-profit move with it is judged as any take-profit move (admitted, with a target), and its
    amend names the take-profit side alone, so the order's stop stays as it is."""
    principals, reading = Principals(frozenset({cr.ACCOUNT})), Reading((_entry(),))
    params = {"mode": "absolute", "value": "63000", "only_tighten": False}
    move = exit_request("modify_take_profit", params)
    check = RuleStopCheck(principals, reading, Held((stored(),)), "demo")
    assert await check.judge(move, cr.ACCOUNT) == STOP_ADMITTED
    amends = Amends(answer=ExitOutcome(kind="accepted", status=202))
    amend = RuleAmendHandler(
        "modify_take_profit", lambda: cast(Any, Composed(cast(Any, amends))), principals,
        reading, "demo",
    )  # fmt: skip
    prepared = amend.prepare(move, cr.ACCOUNT, max_notional_usd=None)
    answer = await amend.send(prepared, client_ref=REF)
    [terms] = amends.asked
    assert answer.answer == "accepted" and list(terms.sides) == ["take_profit"]


@pytest.mark.parametrize(
    ("action_type", "params"),
    [("cancel_order", {}),
     ("modify_stop_loss", {"mode": "absolute", "value": "58600"}),
     ("modify_take_profit", {"mode": "absolute", "value": "63000"}),
     ("tighten_stop", {"mode": "absolute", "value": "58600"})],
)  # fmt: skip
async def test_a_cancel_order_or_an_amend_with_no_instance_symbol_is_invalid_params(
    action_type: str, params: dict[str, Any]
) -> None:
    """24 §11.6: `cancel_order` and the three amends need the instance's symbol; on an
    account-wide instance each answers `invalid_params` with nothing read or sent, and check 8
    takes such an amend as no request, reading nothing, so the handler's answer is the action's."""
    principals, reading = Principals(frozenset({cr.ACCOUNT})), Reading((_entry(),))
    wide = ScopeInstanceRef("*@x", None, cr.ACCOUNT)
    req = replace(exit_request(action_type, params), instance=wide)
    kind = RuleCancelHandler if action_type == "cancel_order" else RuleAmendHandler
    exits = Exits()
    exit_ = kind(action_type, lambda: cast(Any, Composed(exits)), principals, reading, "demo")
    answer = await exit_.send(exit_.prepare(req, cr.ACCOUNT, max_notional_usd=None), client_ref=REF)
    assert (answer.answer, answer.error_code) == ("refused", "invalid_params")
    check = RuleStopCheck(principals, reading, Held((stored(),)), "demo")
    assert await check.judge(req, cr.ACCOUNT) == STOP_ADMITTED
    assert reading.calls == [] and exits.cancelled == []
