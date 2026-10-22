"""Classification by effect, the intent rule and the NativeStopGuard (E29-T04, #913).

SR-E29-01 / OM-S02: an order is classified by its effect on the exchange-truth position, never by
its label. Rulings R2 and R7: a reduce-only order whose quantity exceeds the position is an entry,
and the position is read for a reduce-only order only. A zero or negative stop is
`native_stop_required` (Low L29 of PR #3932's review record, issuecomment-6302240417). R4: C-2.6
holds whatever the stop resolver returns. `errors[]` lists every rule that fails, the stop's first
(22-api-openapi.yaml `placeOrder`), each with its fixed sentence. Both rules fail closed: any
effect but `REDUCE` is an entry's. The property test drives (reduce_only, quantity, position,
intent, stop) against an oracle written from the rule's text, with its boundaries as explicit
examples.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args
from uuid import UUID

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from candleviewer.accounts.profiles import AccountProfile
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Px, Side
from candleviewer.oms.classify import (
    OPENING_INTENTS,
    REDUCING_INTENTS,
    SERVER_ASSIGNED_INTENTS,
    ExchangePosition,
    NativeStopGuard,
    classify_effect,
    effect_of,
    intent_errors,
    stop_errors,
)
from candleviewer.oms.errors import (
    RULE_INTENT_MISMATCH,
    RULE_NATIVE_STOP_REQUIRED,
    RULE_STOP_UNIT_UNSUPPORTED,
    OrderInvalid,
    StopUnitUnsupported,
)
from candleviewer.oms.order_link import OrderPurpose
from candleviewer.oms.ports import InterimStopResolver, OrderEffect, StopOffset

ENTRY, REDUCE = OrderEffect.ENTRY, OrderEffect.REDUCE
ACCOUNT = AccountId(UUID("7d3c9a10-28a1-4c1e-9e01-0000000000a2"))
REF = Decimal("100")
INTENTS: tuple[OrderPurpose, ...] = get_args(OrderPurpose)
_PROFILES = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"


def _instrument() -> Instrument:
    return Instrument.model_validate(
        {
            "symbol": "BTCUSDT",
            "base_coin": "BTC",
            "quote_coin": "USDT",
            "settle_coin": "USDT",
            "status": "trading",
            "contract_type": "linear_perpetual",
            "launch_time": 0,
            "tick_size": "0.1",
            "price_scale": 1,
            "min_price": "0.1",
            "max_price": "999999",
            "qty_step": "0.001",
            "min_order_qty": "0.001",
            "max_order_qty": "100",
            "max_mkt_order_qty": "50",
            "min_notional": "5",
            "max_leverage": "100",
            "min_leverage": "1",
            "leverage_step": "0.01",
            "funding_interval_min": 480,
            "upper_funding_rate": "0.00375",
            "lower_funding_rate": "-0.00375",
            "copy_trading": False,
            "metadata_version": 1,
            "fetched_at": 0,
        }
    )


INSTRUMENT = _instrument()


def _profile(mode: str = "fixed_qty", **changes: Any) -> AccountProfile:
    raw = json.loads((_PROFILES / f"{mode}.json").read_text(encoding="utf-8"))
    return AccountProfile.model_validate({**raw, **changes})


class _Echo:
    """A stop resolver that returns one fixed answer, whatever it is asked: the guard must judge
    that answer on its own (R4)."""

    def __init__(self, stop: Px | None) -> None:
        self.stop = stop
        self.calls = 0

    def resolve(self, stop: StopOffset | None, **_: object) -> Px | None:
        self.calls += 1
        return self.stop


class _Raises:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def resolve(self, stop: StopOffset | None, **_: object) -> Px | None:
        raise self.error


def _admit(
    guard: NativeStopGuard,
    *,
    effect: OrderEffect = ENTRY,
    intent: OrderPurpose = "entry",
    side: Side = "buy",
    stop: StopOffset | None = None,
    profile: AccountProfile | None = None,
) -> Px | None:
    return guard.admit(
        stop=stop,
        side=side,
        reference_price=REF,
        effect=effect,
        intent=intent,
        instrument=INSTRUMENT,
        profile=profile,
    )


def _rules(refused: OrderInvalid) -> list[tuple[str, str]]:
    return [(e.field, e.rule) for e in refused.errors]


# --- classification by effect (SR-E29-01, R7) ----------------------------------------------------


def _pos(side: Side | None, qty: str) -> ExchangePosition:
    return ExchangePosition(side=side, qty=Decimal(qty))


@pytest.mark.parametrize(
    ("reduce_only", "qty", "position", "effect"),
    [
        (False, "1", None, ENTRY),
        (False, "1", _pos("sell", "5"), ENTRY),  # not reduce-only: an entry, whatever it meets
        (True, "1", None, ENTRY),  # flat: nothing to reduce
        (True, "1", _pos(None, "0"), ENTRY),
        (True, "1", _pos("buy", "5"), ENTRY),  # same side: it would add, not reduce
        (True, "1", _pos("sell", "5"), REDUCE),
        (True, "5", _pos("sell", "5"), REDUCE),  # the whole position
        (True, "5.001", _pos("sell", "5"), ENTRY),  # R7: more than the position reduces
        (True, "0", _pos("sell", "5"), ENTRY),  # a quantity that reduces nothing
        (True, "-1", _pos("sell", "5"), ENTRY),
    ],
)
def test_classify_effect_is_the_effect_on_the_exchange_truth_position(
    reduce_only: bool, qty: str, position: ExchangePosition | None, effect: OrderEffect
) -> None:
    got = classify_effect(side="buy", qty=Decimal(qty), reduce_only=reduce_only, position=position)
    assert got is effect


@pytest.mark.parametrize(
    ("qty", "position_qty"),
    [("NaN", "5"), ("Infinity", "5"), ("1", "NaN"), ("1", "Infinity"), ("sNaN", "5")],
)
def test_classify_effect_reads_a_non_finite_figure_as_an_entry(qty: str, position_qty: str) -> None:
    position = ExchangePosition(side="sell", qty=Decimal(position_qty))
    got = classify_effect(side="buy", qty=Decimal(qty), reduce_only=True, position=position)
    assert got is ENTRY


class _Positions:
    """`PositionTruth` double: answers one position and records each read."""

    def __init__(self, answer: ExchangePosition | None = None) -> None:
        self.answer = answer
        self.reads: list[tuple[AccountId, str, int]] = []

    async def position(
        self, account_id: AccountId, symbol: str, position_idx: int
    ) -> ExchangePosition | None:
        self.reads.append((account_id, symbol, position_idx))
        return self.answer


async def _effect(
    positions: Any, *, reduce_only: bool, qty: str = "1", timeout_s: float = 5.0
) -> OrderEffect:
    return await effect_of(
        account_id=ACCOUNT,
        symbol="BTCUSDT",
        position_idx=0,
        side="sell",
        qty=Decimal(qty),
        reduce_only=reduce_only,
        positions=positions,
        timeout_s=timeout_s,
    )


async def test_effect_of_an_order_that_is_not_reduce_only_reads_no_position() -> None:
    positions = _Positions(_pos("buy", "5"))
    assert await _effect(positions, reduce_only=False) is ENTRY
    assert positions.reads == []


async def test_effect_of_a_reduce_only_order_reads_its_position_once() -> None:
    positions = _Positions(_pos("buy", "5"))
    assert await _effect(positions, reduce_only=True) is REDUCE
    assert positions.reads == [(ACCOUNT, "BTCUSDT", 0)]


async def test_effect_of_a_reduce_only_order_above_the_position_is_an_entry() -> None:
    assert await _effect(_Positions(_pos("buy", "5")), reduce_only=True, qty="6") is ENTRY


async def test_effect_of_a_failed_position_read_fails_closed() -> None:
    class _Down:
        async def position(self, *_: object) -> ExchangePosition | None:
            raise ConnectionError("positions unreadable")

    with pytest.raises(ConnectionError):
        await _effect(_Down(), reduce_only=True)


async def test_effect_of_a_position_read_that_never_answers_times_out() -> None:
    class _Silent:
        async def position(self, *_: object) -> ExchangePosition | None:
            await asyncio.Event().wait()
            return None

    with pytest.raises(TimeoutError):
        await _effect(_Silent(), reduce_only=True, timeout_s=0)


# --- the stop rules (C-2.6; #3932 issuecomment-6302240417, Low L29) ------------------------------


def test_stop_errors_entry_without_a_stop_is_native_stop_required() -> None:
    [error] = stop_errors(effect=ENTRY, side="buy", reference_price=REF, stop=None)
    assert (error.field, error.rule) == ("stop_loss", RULE_NATIVE_STOP_REQUIRED)
    assert error.message == "No stop_loss supplied and the account profile defines no SL offset."


def test_stop_errors_an_order_that_only_reduces_needs_no_stop() -> None:
    assert stop_errors(effect=REDUCE, side="buy", reference_price=REF, stop=None) == []


@pytest.mark.parametrize("effect", ["entry", "bogus"])
def test_stop_errors_any_effect_but_reduce_needs_a_stop(effect: Any) -> None:
    """Fail closed: an effect that is not the `REDUCE` member is an entry's, a string too."""
    [error] = stop_errors(effect=effect, side="buy", reference_price=REF, stop=None)
    assert (error.field, error.rule) == ("stop_loss", RULE_NATIVE_STOP_REQUIRED)


@pytest.mark.parametrize("effect", [ENTRY, REDUCE])
@pytest.mark.parametrize(
    "stop", ["0", "-0", "-0.1", "-63000", "NaN", "sNaN", "Infinity", "-Infinity"]
)
def test_stop_errors_a_stop_not_above_zero_is_native_stop_required(
    effect: OrderEffect, stop: str
) -> None:
    [error] = stop_errors(effect=effect, side="sell", reference_price=REF, stop=Decimal(stop))
    assert (error.field, error.rule) == ("stop_loss", RULE_NATIVE_STOP_REQUIRED)
    assert error.message == "The stop-loss price must be above zero."


_WRONG_SIDE = (
    RULE_NATIVE_STOP_REQUIRED,
    "The stop-loss must be below the entry price for a buy and above it for a sell.",
)


@pytest.mark.parametrize(
    ("side", "stop", "protective"),
    [
        ("buy", "99.9", True),
        ("buy", "100", False),  # no distance: no protection
        ("buy", "100.1", False),
        ("sell", "100.1", True),
        ("sell", "100", False),
        ("sell", "99.9", False),
    ],
)
@pytest.mark.parametrize("effect", [ENTRY, REDUCE])
def test_stop_errors_a_stop_must_sit_on_the_protective_side(
    side: Side, stop: str, protective: bool, effect: OrderEffect
) -> None:
    errors = stop_errors(effect=effect, side=side, reference_price=REF, stop=Decimal(stop))
    assert [(e.rule, e.message) for e in errors] == ([] if protective else [_WRONG_SIDE])


# --- the intent rule (SR-E29-01) -----------------------------------------------------------------


def test_the_intent_sets_cover_every_intent_once() -> None:
    sets = (OPENING_INTENTS, REDUCING_INTENTS, SERVER_ASSIGNED_INTENTS)
    assert sorted(i for s in sets for i in s) == sorted(INTENTS)
    assert OPENING_INTENTS == {"entry", "scale_in"}
    assert SERVER_ASSIGNED_INTENTS == {"reverse", "algo_child"}


@pytest.mark.parametrize("intent", INTENTS)
@pytest.mark.parametrize("effect", [ENTRY, REDUCE])
def test_intent_errors_the_intent_must_agree_with_the_effect(
    intent: OrderPurpose, effect: OrderEffect
) -> None:
    agrees = intent in (OPENING_INTENTS if effect is ENTRY else REDUCING_INTENTS)
    errors = intent_errors(effect=effect, intent=intent)
    assert [(e.field, e.rule) for e in errors] == (
        [] if agrees else [("intent", RULE_INTENT_MISMATCH)]
    )


_ON_ENTRY = "This order opens or adds exposure, so its intent cannot reduce."
_ON_REDUCE = "This order only reduces the position, so its intent cannot open."


@pytest.mark.parametrize(
    ("effect", "intent", "message"),
    [
        (ENTRY, "stop_loss", _ON_ENTRY),
        (ENTRY, "take_profit", _ON_ENTRY),
        (ENTRY, "scale_out", _ON_ENTRY),
        (ENTRY, "flatten", _ON_ENTRY),
        (REDUCE, "entry", _ON_REDUCE),
        (REDUCE, "scale_in", _ON_REDUCE),
    ],
)
def test_intent_errors_say_which_way_the_intent_disagrees(
    effect: OrderEffect, intent: OrderPurpose, message: str
) -> None:
    [error] = intent_errors(effect=effect, intent=intent)
    assert (error.field, error.rule, error.message) == ("intent", RULE_INTENT_MISMATCH, message)


@pytest.mark.parametrize("intent", ["reverse", "algo_child"])
@pytest.mark.parametrize("effect", [ENTRY, REDUCE])
def test_intent_errors_a_server_assigned_intent_is_refused_on_either_effect(
    intent: OrderPurpose, effect: OrderEffect
) -> None:
    [error] = intent_errors(effect=effect, intent=intent)
    assert error.message == "This intent is assigned by the server and cannot be requested."


@pytest.mark.parametrize("effect", ["entry", "bogus"])
def test_intent_errors_hold_any_effect_but_reduce_to_an_opening_intent(effect: Any) -> None:
    """Fail closed: an effect that is not the `REDUCE` member is an entry's, a string too."""
    assert intent_errors(effect=effect, intent="entry") == []
    [error] = intent_errors(effect=effect, intent="scale_out")
    assert (error.rule, error.message) == (RULE_INTENT_MISMATCH, _ON_ENTRY)


def test_intent_errors_an_unknown_intent_is_refused() -> None:
    unknown: Any = "liquidate"
    assert [e.rule for e in intent_errors(effect=REDUCE, intent=unknown)] == [RULE_INTENT_MISMATCH]


# --- the guard ------------------------------------------------------------------------------------


def test_entry_without_a_stop_is_refused_before_any_exchange_call() -> None:
    """Scenario "Entry without a stop is refused": no stop_loss and no profile SL offset."""
    with pytest.raises(OrderInvalid) as refused:
        _admit(NativeStopGuard(InterimStopResolver()), profile=None)
    assert _rules(refused.value) == [("stop_loss", RULE_NATIVE_STOP_REQUIRED)]
    assert refused.value.detail == refused.value.errors[0].message


def test_guard_applies_the_profile_offset_to_an_entry_without_a_stop() -> None:
    admitted = _admit(NativeStopGuard(InterimStopResolver()), profile=_profile("fixed_qty"))
    assert admitted == Decimal("99.0")  # the fixture's 1 % below the reference


def test_guard_a_mislabelled_opening_order_with_no_stop_carries_both_rules_stop_first() -> None:
    """22 `placeOrder`: "a mislabelled opening order with no stop to apply carries both"."""
    for intent in ("take_profit", "stop_loss", "flatten", "scale_out"):
        with pytest.raises(OrderInvalid) as refused:
            _admit(NativeStopGuard(InterimStopResolver()), intent=intent)
        assert _rules(refused.value) == [
            ("stop_loss", RULE_NATIVE_STOP_REQUIRED),
            ("intent", RULE_INTENT_MISMATCH),
        ]
        assert refused.value.detail == "2 rules failed."


def test_guard_an_unsupported_stop_unit_is_listed_with_the_intent_rule() -> None:
    with pytest.raises(OrderInvalid) as refused:
        _admit(
            NativeStopGuard(InterimStopResolver()),
            intent="reverse",
            stop=StopOffset(unit="atr", value=Decimal("1.5")),
        )
    assert _rules(refused.value) == [
        ("stop_loss", RULE_STOP_UNIT_UNSUPPORTED),
        ("intent", RULE_INTENT_MISMATCH),
    ]
    assert not isinstance(refused.value, StopUnitUnsupported)  # one refusal for both rules


def test_guard_admits_an_order_that_only_reduces_without_a_stop() -> None:
    guard = NativeStopGuard(InterimStopResolver())
    assert _admit(guard, effect=REDUCE, intent="scale_out", side="sell") is None


def test_guard_admits_an_entry_with_a_protective_stop_and_returns_it() -> None:
    stop = StopOffset(unit="ticks", value=Decimal("20"))
    assert _admit(NativeStopGuard(InterimStopResolver()), stop=stop) == Decimal("98.0")


@pytest.mark.parametrize("answer", [None, Decimal("0"), Decimal("-1"), REF, Decimal("100.5")])
def test_guard_c26_holds_whatever_the_stop_resolver_returns(answer: Px | None) -> None:
    """R4: a resolver that answers no stop, a zero, a negative or a wrong-side one for an entry
    never gets it admitted."""
    echo = _Echo(answer)
    with pytest.raises(OrderInvalid) as refused:
        _admit(NativeStopGuard(echo))
    assert _rules(refused.value) == [("stop_loss", RULE_NATIVE_STOP_REQUIRED)]
    assert echo.calls == 1


def test_guard_never_turns_a_resolver_fault_into_an_admission() -> None:
    with pytest.raises(ArithmeticError):
        _admit(NativeStopGuard(_Raises(ArithmeticError("resolver fault"))))


@pytest.mark.parametrize("reference", ["0", "-1", "NaN", "Infinity"])
def test_guard_refuses_to_judge_against_a_reference_price_that_is_not_positive(
    reference: str,
) -> None:
    guard = NativeStopGuard(_Echo(Decimal("1")))
    with pytest.raises(ValueError, match="reference price"):
        guard.admit(
            stop=None,
            side="buy",
            reference_price=Decimal(reference),
            effect=ENTRY,
            intent="entry",
            instrument=INSTRUMENT,
            profile=None,
        )


# --- the property (SR-E29-01, C-2.6; the zero stop of #3932's Low L29) --------------------------

_SIDES: tuple[Side, ...] = ("buy", "sell")
_qty = st.decimals(min_value=Decimal("-1"), max_value=Decimal("50"), places=3)
_positions = st.none() | st.builds(
    ExchangePosition,
    side=st.sampled_from(["buy", "sell", None]),
    qty=st.decimals(min_value=Decimal("0"), max_value=Decimal("50"), places=3),
)
_stops = st.none() | st.decimals(min_value=Decimal("-50"), max_value=Decimal("250"), places=1)
_SHORT = ExchangePosition(side="sell", qty=Decimal("5"))


def _case(**changes: Any) -> dict[str, Any]:
    """One explicit example of the property: a buy entry of 1 with a stop, unless changed."""
    base: dict[str, Any] = {
        "reduce_only": False,
        "side": "buy",
        "qty": Decimal("1"),
        "position": None,
        "intent": "entry",
        "stop": Decimal("99.9"),
    }
    return {**base, **changes}


def _reduce(**changes: Any) -> dict[str, Any]:
    """A reduce-only buy of 1 with no stop against a short of 5, unless changed."""
    reduce: dict[str, Any] = {"reduce_only": True, "position": _SHORT, "intent": "scale_out"}
    return _case(**{**reduce, "stop": None, **changes})


# The rule's boundaries run on every pass, whatever Hypothesis draws: a stop at the reference and
# a tick either side of it, a zero and a non-finite stop, and a reduce-only order at the edges of
# the position it reduces.
@given(
    reduce_only=st.booleans(),
    side=st.sampled_from(_SIDES),
    qty=_qty,
    position=_positions,
    intent=st.sampled_from(INTENTS),
    stop=_stops,
)
@example(**_case(stop=REF))  # a buy's stop at the reference protects nothing
@example(**_case(side="sell", stop=REF))
@example(**_case(stop=Decimal("99.9")))  # a tick to the protective side
@example(**_case(side="sell", stop=Decimal("100.1")))
@example(**_case(stop=Decimal("0")))
@example(**_case(side="sell", stop=Decimal("Infinity")))
@example(**_case(stop=Decimal("NaN")))
@example(**_reduce(qty=Decimal("5")))  # the whole position: it reduces
@example(**_reduce(qty=Decimal("0")))  # reduces nothing: an entry
@example(**_reduce(qty=Decimal("5.001")))  # R7: more than the position: an entry
@example(**_reduce(position=ExchangePosition(side=None, qty=Decimal("5"))))  # flat, sized
@example(**_reduce(position=ExchangePosition(side="buy", qty=Decimal("5"))))  # same side
def test_property_the_effect_decides_the_stop_and_the_intent_never_the_label(
    reduce_only: bool,
    side: Side,
    qty: Decimal,
    position: ExchangePosition | None,
    intent: OrderPurpose,
    stop: Decimal | None,
) -> None:
    effect = classify_effect(side=side, qty=qty, reduce_only=reduce_only, position=position)
    reduces = (
        reduce_only
        and position is not None
        and position.side not in (None, side)
        and Decimal(0) < qty <= position.qty
    )
    assert effect is (REDUCE if reduces else ENTRY)

    protective = (
        stop is not None
        and stop.is_finite()
        and stop > 0
        and (stop < REF if side == "buy" else stop > REF)
    )
    stop_ok = protective or (stop is None and effect is REDUCE)
    intent_ok = intent in (OPENING_INTENTS if effect is ENTRY else REDUCING_INTENTS)
    expected = ([RULE_NATIVE_STOP_REQUIRED] if not stop_ok else []) + (
        [RULE_INTENT_MISMATCH] if not intent_ok else []
    )
    try:
        admitted = _admit(NativeStopGuard(_Echo(stop)), effect=effect, intent=intent, side=side)
    except OrderInvalid as refused:
        assert [e.rule for e in refused.errors] == expected != []
    else:
        assert expected == [] and admitted == stop
        if effect is ENTRY:  # C-2.6: no entry is ever admitted without a protective stop
            assert admitted is not None and protective
