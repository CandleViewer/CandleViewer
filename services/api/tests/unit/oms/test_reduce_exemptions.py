"""E28-T04 (#908): the declared reduce-only exemption matrix (`oms.reduce_exemptions`; 24 Sec.8.4
"The reduce-only exemption matrix"; C-2.6, SR-E28-24, SR-E28-30).

The registry fails when a gate is added without a row; the matrix is driven through the real
pipeline, gate by gate, for an entry and for an order that only reduces; a property holds that the
exemption never admits an order whose effect is not `REDUCE`; and an entry never passes as one
that reduces, keeping its native stop (C-2.6)."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.exchange.base.models import PlaceOrderRequest
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.oms.errors import OmsError, OmsNotReady, RiskRefused, TradingDisabled
from candleviewer.oms.ports import OrderEffect, SizedOrder
from candleviewer.oms.reduce_exemptions import (
    EXEMPTIONS,
    Exemption,
    GuardGate,
    RefusalGate,
    exempt,
    refusal_gate,
)
from candleviewer.statechart.bindings import b01_order as b01
from tests.unit.oms import command_rig as cr
from tests.unit.oms.submit_rig import (
    SYMBOL,
    SubmitRig,
    build_rig,
    context,
    entry,
    flatten,
    instrument,
    profile,
)


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[SubmitRig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    built = build_rig()
    yield built
    await built.machines.stop()


def _held(rig: SubmitRig, **over: Any) -> None:
    rig.profiles.held[(cr.ACCOUNT, None)] = profile(**over)


def _live(rig: SubmitRig) -> None:
    rig.profiles.held[(cr.LIVE_ACCOUNT, None)] = profile(cr.LIVE_ACCOUNT)


#: How each gate is tripped on the rig. The risk gate's is the interim gate on a live account.
_TRIPS: dict[GuardGate, Callable[[SubmitRig], None]] = {
    GuardGate.CLOCK: lambda r: r.port.health.measure(offset_ms=5_000),
    GuardGate.READ_ONLY: lambda r: setattr(r.read_only, "is_read_only", True),
    GuardGate.PROFILE: lambda r: _held(r, trading_enabled=False),
    GuardGate.SYMBOL: lambda r: _held(r, allowed_symbols=["ETHUSDT"]),
    GuardGate.LEVERAGE: lambda r: r.instruments.listed.update(
        {SYMBOL: instrument(max_leverage=Decimal("2"))}
    ),
    GuardGate.CAPS: lambda r: _held(r, max_position_notional="50"),
    GuardGate.RISK_GATE: _live,
    GuardGate.SWITCHES: lambda r: r.port.switches.refusals.update({cr.ACCOUNT: TradingDisabled()}),
    GuardGate.FENCE: lambda r: r.port.switches.refusals.update(
        {cr.ACCOUNT: cast(Any, OmsNotReady())}
    ),
}


def test_every_gate_is_in_the_exemption_matrix() -> None:
    """The registry: one row per gate, and one way to trip each in the matrix test below, so a
    gate added without its row (or its test) fails here. It checks only that the enum, the
    matrix and the trips name the same gates; the 9x2 pipeline test
    (`test_reduce_exemption_matrix`) is what catches a gate whose behaviour drifts from its row."""
    assert set(EXEMPTIONS) == set(GuardGate) == set(_TRIPS)
    assert all(isinstance(rule, Exemption) for rule in EXEMPTIONS.values())


def test_the_refusal_classes_bound_the_refusal_counter() -> None:
    """`cv_risk_guard_refusals_total{gate}` is bounded by the closed class set (PF-I07)."""
    (spec,) = [s for s in CATALOGUE if s.name == "cv_risk_guard_refusals_total"]
    assert (spec.labels, spec.max_series) == (("gate",), len(RefusalGate))


@pytest.mark.parametrize(
    ("rule", "step", "expected"),
    [
        ("symbol_not_allowed", "validate", RefusalGate.SYMBOL),
        ("symbol_denied", "classify", RefusalGate.SYMBOL),
        ("profile_disabled", "validate", RefusalGate.PROFILE),
        (None, "persist", RefusalGate.PROFILE),
        ("max_position_notional", "classify", RefusalGate.CAPS),
        ("insufficient_margin", "classify", RefusalGate.CAPS),
        (None, "risk", RefusalGate.RISK_GATE),
        ("max_open_positions", "risk", RefusalGate.RISK_GATE),
    ],
)
def test_a_guard_refusal_is_classed_by_its_step_then_its_rule(
    rule: str | None, step: str, expected: RefusalGate
) -> None:
    assert refusal_gate(rule, step) is expected


def _creates(rig: SubmitRig) -> list[PlaceOrderRequest]:
    calls = (*rig.port.demo.calls, *rig.port.live.calls)
    return [cast(PlaceOrderRequest, c.request) for c in calls if c.method == "place_order"]


@pytest.mark.parametrize("effect", ["entry", "reduce"])
@pytest.mark.parametrize("gate", list(GuardGate), ids=str)
async def test_reduce_exemption_matrix(rig: SubmitRig, gate: GuardGate, effect: str) -> None:
    """Each gate, tripped alone: an entry is refused with nothing sent; an order that only
    reduces (a flatten of a seeded long, marked protective where the row needs it) is refused
    unless its row exempts it, and is then sent, reduce-only and with no stop of its own."""
    account = cr.LIVE_ACCOUNT if gate is GuardGate.RISK_GATE else cr.ACCOUNT
    venue = rig.port.live if account == cr.LIVE_ACCOUNT else rig.port.demo
    venue.seed_position(cr.position(account, qty="0.050"))
    _TRIPS[gate](rig)
    reduces = effect == "reduce"
    protective = reduces and EXEMPTIONS[gate] is Exemption.PROTECTIVE
    request = (flatten if reduces else entry)(account_id=account)
    ctx = context(client_ref=uuid4(), protective=protective)
    admitted = reduces and exempt(gate, OrderEffect.REDUCE, protective=protective)
    if admitted:
        outcome = await rig.submit(request, ctx)
        assert outcome.status == 202
        [create] = _creates(rig)
        assert (create.reduce_only, create.stop_loss) == (True, None)
    else:
        with pytest.raises(OmsError):
            await rig.submit(request, ctx)
        assert _creates(rig) == []


async def test_the_switches_exempt_a_reduce_only_order_only_when_marked_protective(
    rig: SubmitRig,
) -> None:
    """The `protective` row: the same flatten, unmarked, is refused (24 Sec.8.10)."""
    rig.port.demo.seed_position(cr.position(qty="0.050"))
    _TRIPS[GuardGate.SWITCHES](rig)
    with pytest.raises(TradingDisabled):
        await rig.submit(flatten(), context(protective=False))
    assert not exempt(GuardGate.SWITCHES, OrderEffect.REDUCE, protective=False)


@given(
    gate=st.sampled_from(list(GuardGate)),
    effect=st.sampled_from([*OrderEffect, "reduce", "REDUCE", "", None, 0]),
    protective=st.booleans(),
)
def test_property_the_exemption_never_admits_an_order_whose_effect_is_not_reduce(
    gate: GuardGate, effect: Any, protective: bool
) -> None:
    """By identity with the member, so a look-alike string or any other value fails closed."""
    if exempt(gate, effect, protective=protective):
        assert effect is OrderEffect.REDUCE
        assert EXEMPTIONS[gate] is not Exemption.NONE


async def test_an_entry_never_passes_as_reduce_and_keeps_its_native_stop(rig: SubmitRig) -> None:
    """C-2.6: no gate exempts an entry; an entry cannot be built without its stop; a reduce-only
    request the venue's read does not show reducing is no exempt order (refused, nothing sent);
    and an entry the gates admit is sent with its native stop."""
    assert not any(exempt(g, OrderEffect.ENTRY, protective=True) for g in GuardGate)
    with pytest.raises(ValueError, match=r"C-2\.6"):
        SizedOrder(
            account_id=cr.ACCOUNT, environment="demo", symbol=SYMBOL, side="buy",
            order_type="market", qty=Decimal("0.010"), price=None, trigger_price=None,
            reference_price=Decimal("60000"), reduce_only=True, intent="flatten",
            effect=OrderEffect.ENTRY, stop_loss=None,
        )  # fmt: skip
    _TRIPS[GuardGate.SYMBOL](rig)  # no position seeded: the flatten reduces nothing
    with pytest.raises(OmsError):
        await rig.submit(flatten(), context(protective=True))
    assert _creates(rig) == []
    _held(rig)
    outcome = await rig.submit(entry(), context(client_ref=uuid4()))
    [create] = _creates(rig)
    assert outcome.status == 202 and not create.reduce_only and create.stop_loss is not None


def test_refused_entries_raise_the_refusal_of_their_gate() -> None:
    """A guard refusal keeps its gate in process (`RiskRefused.cap`) for the record."""
    refused = RiskRefused(cap="max_open_positions", limit=Decimal(3), observed=Decimal(3))
    assert (refused.cap, refused.limit, refused.observed) == (
        "max_open_positions", Decimal(3), Decimal(3),
    )  # fmt: skip
