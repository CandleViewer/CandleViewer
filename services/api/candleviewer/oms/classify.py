"""Classification by effect, the intent rule and the NativeStopGuard (E29-T04, #913).

SR-E29-01 (OM-S02): the server classifies an order by its effect on the exchange-truth position,
never by its label (#913 rulings R2 and R7). An order that is not reduce-only is an entry. A
reduce-only order is an entry too unless it is opposite an open position and its quantity is above
zero and within that position: anything not shown to reduce is an entry, so no stop is waived on
a guess. `effect_of` reads the position for a reduce-only order only (R7), through
`PositionTruth`, which the pipeline feeds from the trading port's positions until the private
streams feed the local position store (E29-T05, E29-T06).

`NativeStopGuard` resolves the stop through the `StopResolver` port and then judges the answer
itself, so C-2.6 holds whatever the port does (R4): an entry must carry a stop, and any stop must
be finite, above zero and on the protective side of the reference price, below it for a buy and
above it for a sell. A zero or negative stop is `native_stop_required`: Low L29 of PR #3932's
review record (issuecomment-6302240417), carried to this ticket. It never reads the profile's
native-stop flag, a constant (SR-E29-01).
Then the intent rule: an entry's intent must be an opening one (`entry`, `scale_in`), and the
intent of an order that only reduces a reducing one (`stop_loss`, `take_profit`, `scale_out`,
`flatten`); the server-assigned `reverse` and `algo_child` are refused either way. `errors[]`
lists every rule that fails, the stop's first (22-api-openapi.yaml `placeOrder`). Both rules fail
closed on the effect they are given: any effect but `OrderEffect.REDUCE` is an entry's.
`take_profit_errors` judges a take-profit the same way (S2-Q6): a finite price above zero on the
profit side of the reference price, above it for a buy and below it for a sell (#2877 ruling 2).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from candleviewer.domain.primitives import AccountId, Px, Qty, Side, Symbol

from .errors import (
    RULE_INTENT_MISMATCH,
    RULE_NATIVE_STOP_REQUIRED,
    RULE_TAKE_PROFIT_SIDE,
    FieldError,
    OrderInvalid,
    StopUnitUnsupported,
)
from .order_link import OrderPurpose
from .ports import OrderEffect, StopOffset, StopResolver

if TYPE_CHECKING:
    from candleviewer.accounts.profiles import AccountProfile
    from candleviewer.domain.events import Instrument

#: 22 `OrderIntent`: the intents that open or add, those that reduce, and those only the server
#: assigns (`reversePosition`, the emulated algos).
OPENING_INTENTS: Final[frozenset[OrderPurpose]] = frozenset({"entry", "scale_in"})
REDUCING_INTENTS: Final[frozenset[OrderPurpose]] = frozenset(
    {"stop_loss", "take_profit", "scale_out", "flatten"}
)
SERVER_ASSIGNED_INTENTS: Final[frozenset[OrderPurpose]] = frozenset({"reverse", "algo_child"})

_NO_STOP: Final = "No stop_loss supplied and the account profile defines no SL offset."
_STOP_NOT_POSITIVE: Final = "The stop-loss price must be above zero."
_STOP_WRONG_SIDE: Final = (
    "The stop-loss must be below the entry price for a buy and above it for a sell."
)
_SERVER_INTENT: Final = "This intent is assigned by the server and cannot be requested."
_REDUCING_ON_ENTRY: Final = "This order opens or adds exposure, so its intent cannot reduce."
_OPENING_ON_REDUCE: Final = "This order only reduces the position, so its intent cannot open."
_TAKE_PROFIT_NOT_POSITIVE: Final = "The take-profit price must be a finite price above zero."
_TAKE_PROFIT_WRONG_SIDE: Final = (
    "The take-profit must be above the entry price for a buy and below it for a sell."
)


@dataclass(frozen=True, slots=True)
class ExchangePosition:
    """The exchange-truth position an order acts on, for its account, symbol and position index:
    its side, `None` when flat, and its size."""

    side: Side | None
    qty: Qty


class PositionTruth(Protocol):
    """The exchange's own position the pipeline classifies a reduce-only order against (R7)."""

    async def position(
        self, account_id: AccountId, symbol: Symbol, position_idx: int
    ) -> ExchangePosition | None:
        """The position, or `None` when there is none; raises when it cannot be read, and the
        order then fails closed."""
        ...


def classify_effect(
    *, side: Side, qty: Qty, reduce_only: bool, position: ExchangePosition | None
) -> OrderEffect:
    """SR-E29-01: `REDUCE` only for a reduce-only order opposite an open position with a quantity
    above zero and within it; every other order is an `ENTRY`, a non-finite figure included."""
    if not reduce_only or position is None or position.side in (None, side):
        return OrderEffect.ENTRY
    if qty.is_finite() and position.qty.is_finite() and 0 < qty <= position.qty:
        return OrderEffect.REDUCE
    return OrderEffect.ENTRY


async def effect_of(
    *,
    account_id: AccountId,
    symbol: Symbol,
    position_idx: int,
    side: Side,
    qty: Qty,
    reduce_only: bool,
    positions: PositionTruth,
    timeout_s: float,
) -> OrderEffect:
    """The order's effect, reading its exchange-truth position only when it is reduce-only (R7),
    within `timeout_s`: a read that fails or does not answer in time raises (fail closed)."""
    effect, _position = await position_effect(
        account_id=account_id, symbol=symbol, position_idx=position_idx, side=side, qty=qty,
        reduce_only=reduce_only, positions=positions, timeout_s=timeout_s,
    )  # fmt: skip
    return effect


async def position_effect(
    *,
    account_id: AccountId,
    symbol: Symbol,
    position_idx: int,
    side: Side,
    qty: Qty,
    reduce_only: bool,
    positions: PositionTruth,
    timeout_s: float,
) -> tuple[OrderEffect, ExchangePosition | None]:
    """`effect_of`'s effect and the position it was judged on: None when the order is not
    reduce-only (nothing read) or the exchange shows none. A close the read does not show
    reducing is refused by that reading (`oms.submit`, E29-S03 BQ-7), never re-sized."""
    if not reduce_only:
        return OrderEffect.ENTRY, None
    async with asyncio.timeout(timeout_s):
        position = await positions.position(account_id, symbol, position_idx)
    return classify_effect(side=side, qty=qty, reduce_only=True, position=position), position


def stop_errors(
    *, effect: OrderEffect, side: Side, reference_price: Px, stop: Px | None
) -> list[FieldError]:
    """The native-stop rule (C-2.6; #3932 issuecomment-6302240417, Low L29): an entry, any effect
    but `REDUCE`, needs a stop, and any stop must be finite, above zero and on the protective side
    of `reference_price`."""
    if stop is None:
        if effect is not OrderEffect.REDUCE:
            return [FieldError("stop_loss", RULE_NATIVE_STOP_REQUIRED, _NO_STOP)]
        return []
    if not stop.is_finite() or stop <= 0:
        return [FieldError("stop_loss", RULE_NATIVE_STOP_REQUIRED, _STOP_NOT_POSITIVE)]
    protective = stop < reference_price if side == "buy" else stop > reference_price
    if not protective:
        return [FieldError("stop_loss", RULE_NATIVE_STOP_REQUIRED, _STOP_WRONG_SIDE)]
    return []


def take_profit_errors(
    *, side: Side, reference_price: Px, take_profit: Px | None
) -> list[FieldError]:
    """S2-Q6 and #2877 ruling 2: a take-profit, where the order names one, is a finite price above
    zero (finite first: ordering a NaN raises) on the profit side of `reference_price`."""
    if take_profit is None:
        return []
    if not take_profit.is_finite() or take_profit <= 0:
        return [FieldError("take_profit", RULE_TAKE_PROFIT_SIDE, _TAKE_PROFIT_NOT_POSITIVE)]
    profitable = take_profit > reference_price if side == "buy" else take_profit < reference_price
    if not profitable:
        return [FieldError("take_profit", RULE_TAKE_PROFIT_SIDE, _TAKE_PROFIT_WRONG_SIDE)]
    return []


def intent_errors(*, effect: OrderEffect, intent: OrderPurpose) -> list[FieldError]:
    """The intent rule (SR-E29-01): the intent must agree with the effect, never decide it; any
    effect but `REDUCE` is an entry's."""
    reduces = effect is OrderEffect.REDUCE
    allowed = REDUCING_INTENTS if reduces else OPENING_INTENTS
    if intent in allowed:
        return []
    if intent in SERVER_ASSIGNED_INTENTS:
        message = _SERVER_INTENT
    elif reduces:
        message = _OPENING_ON_REDUCE
    else:
        message = _REDUCING_ON_ENTRY
    return [FieldError("intent", RULE_INTENT_MISMATCH, message)]


class NativeStopGuard:
    """C-2.6 at the submission choke point: resolves an order's stop through `resolver` and judges
    the answer, whatever the resolver is, then the intent."""

    def __init__(self, resolver: StopResolver) -> None:
        self._resolver = resolver

    def admit(
        self,
        *,
        stop: StopOffset | None,
        side: Side,
        reference_price: Px,
        effect: OrderEffect,
        intent: OrderPurpose,
        instrument: Instrument,
        profile: AccountProfile | None,
    ) -> Px | None:
        """The stop price the order carries, `None` for an order that only reduces and has none;
        `OrderInvalid` listing every rule that fails, the stop's first, when it may not be sent."""
        if not reference_price.is_finite() or reference_price <= 0:
            raise ValueError("a stop is judged against a reference price above zero")
        resolved: Px | None = None
        try:
            resolved = self._resolver.resolve(
                stop,
                side=side,
                reference_price=reference_price,
                effect=effect,
                instrument=instrument,
                profile=profile,
            )
        except StopUnitUnsupported as unsupported:
            errors = list(unsupported.errors)
        else:
            errors = stop_errors(
                effect=effect, side=side, reference_price=reference_price, stop=resolved
            )
        errors += intent_errors(effect=effect, intent=intent)
        if errors:
            detail = errors[0].message if len(errors) == 1 else f"{len(errors)} rules failed."
            raise OrderInvalid(detail, errors=errors)
        return resolved
