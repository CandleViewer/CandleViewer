"""The ports the submission pipeline consumes and their interim implementations (E29-T04, #913).

Ruling R4: the sizer serves `fixed_qty` only, refusing another mode with
`sizing_mode_unsupported`; the stop resolver serves `price`, `ticks` and `percent` stops and the
profile's offset, refusing `atr` and `r_multiple` with `stop_unit_unsupported`; the risk gate
admits demo and refuses live; `NoArmRecords` refuses every live order. Each interim port logs once
at startup and is counted in `oms_interim_ports{port}`. A `SizedOrder` is as strict as
`classify.stop_errors`: an entry carries a stop, and any stop is finite, above zero and on the
protective side of its reference price (C-2.6); its effect is an `OrderEffect`, and any effect but
`REDUCE` is an entry's (fail closed). The arm token travels masked (C-12.6) and compares in
constant time (SR-043).
"""

from __future__ import annotations

import dataclasses
import hmac
import inspect
import json
import time
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Final, get_args, get_type_hints
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.accounts.profiles import AccountProfile
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Environment, Side
from candleviewer.exchange.base.models import AccountRef
from candleviewer.ingestion.clock import ClockGuard
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.observability.secret_type import Secret
from candleviewer.oms.errors import (
    RULE_STOP_UNIT_UNSUPPORTED,
    FieldError,
    OrderInvalid,
    StopUnitUnsupported,
)
from candleviewer.oms.fakes import FakeClockHealth
from candleviewer.oms.ports import (
    FAILED,
    INTERIM_PORTS_METRIC,
    PASSED,
    PORT_NAMES,
    ArmToken,
    ClockHealth,
    FixedQtySizer,
    Interim,
    InterimRiskGate,
    InterimStopResolver,
    NoArmRecords,
    OrderEffect,
    SizedOrder,
    SizingRequest,
    StopOffset,
    SubmissionPorts,
    TradingAccounts,
    Verdict,
    announce_interim_ports,
)
from candleviewer.risk.models import RiskDecision, RiskRefusal
from candleviewer.statechart.bindings import b01_order

ACCOUNT = AccountId(UUID("7d3c9a10-28a1-4c1e-9e01-0000000000a2"))
SESSION = UUID("5e551011-0000-4000-8000-000000000001")
NOW = datetime(2026, 10, 21, 9, 30, tzinfo=UTC)
#: An arm value as a session would present it: never logged, never admitting a live order here.
_ISSUED = "an-issued-arm-value"
#: Another session's arm value: it never equals `_ISSUED`.
_ANOTHER = "another-issued-arm-value"
_PROFILES = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"


def _instrument(**overrides: object) -> Instrument:
    base: dict[str, object] = {
        "symbol": "BTCUSDT",
        "base_coin": "BTC",
        "quote_coin": "USDT",
        "settle_coin": "USDT",
        "status": "trading",
        "contract_type": "linear_perpetual",
        "launch_time": 0,
        "tick_size": Decimal("0.1"),
        "price_scale": 1,
        "min_price": Decimal("0.1"),
        "max_price": Decimal("999999"),
        "qty_step": Decimal("0.001"),
        "min_order_qty": Decimal("0.001"),
        "max_order_qty": Decimal("100"),
        "max_mkt_order_qty": Decimal("50"),
        "min_notional": Decimal("5"),
        "max_leverage": Decimal("100"),
        "min_leverage": Decimal("1"),
        "leverage_step": Decimal("0.01"),
        "funding_interval_min": 480,
        "upper_funding_rate": Decimal("0.00375"),
        "lower_funding_rate": Decimal("-0.00375"),
        "copy_trading": False,
        "metadata_version": 1,
        "fetched_at": 0,
    }
    base.update(overrides)
    return Instrument.model_validate(base)


INSTRUMENT = _instrument()


def _profile(mode: str = "fixed_qty", **changes: Any) -> AccountProfile:
    raw = json.loads((_PROFILES / f"{mode}.json").read_text(encoding="utf-8"))
    return AccountProfile.model_validate({**raw, **changes})


def _order(environment: Environment, **changes: Any) -> SizedOrder:
    base: dict[str, Any] = {
        "account_id": ACCOUNT,
        "environment": environment,
        "symbol": "BTCUSDT",
        "side": "buy",
        "order_type": "limit",
        "qty": Decimal("0.250"),
        "price": Decimal("63100.0"),
        "trigger_price": None,
        "reference_price": Decimal("63100.0"),
        "reduce_only": False,
        "intent": "entry",
        "effect": OrderEffect.ENTRY,
        "stop_loss": Decimal("62900.0"),
    }
    return SizedOrder(**{**base, **changes})


# --- the vocabulary -----------------------------------------------------------------------------


def test_verdicts_are_b1s_gate_values() -> None:
    assert (PASSED, FAILED) == (b01_order.PASSED, b01_order.FAILED)
    assert get_args(Verdict) == (b01_order.PASSED, b01_order.FAILED)


def test_order_effect_values_are_the_two_effects_of_sr_e29_01() -> None:
    assert [e.value for e in OrderEffect] == ["entry", "reduce"]


# --- SizedOrder: the invariants every later check relies on (C-2.6, SR-E29-01) ------------------


def test_sized_order_builds_an_entry_with_its_stop_and_a_reduce_order_without_one() -> None:
    assert _order("demo").stop_loss == Decimal("62900.0")
    reduce = _order("demo", reduce_only=True, effect=OrderEffect.REDUCE, stop_loss=None)
    assert reduce.stop_loss is None


def test_sized_order_builds_a_reduce_only_order_that_is_an_entry_with_its_stop() -> None:
    """R7: a reduce-only order above its position is an entry, and it carries a stop."""
    assert _order("demo", reduce_only=True).effect is OrderEffect.ENTRY


def test_sized_order_refuses_an_entry_without_a_stop() -> None:
    with pytest.raises(ValueError, match=r"an entry carries a stop_loss \(C-2\.6\)"):
        _order("demo", stop_loss=None)


@pytest.mark.parametrize("effect", [OrderEffect.ENTRY, OrderEffect.REDUCE])
@pytest.mark.parametrize("stop", ["0", "-0.1", "NaN", "sNaN", "Infinity", "-Infinity"])
def test_sized_order_refuses_a_stop_that_is_not_finite_and_above_zero(
    stop: str, effect: OrderEffect
) -> None:
    """Whatever the effect, as `classify.stop_errors` judges any stop."""
    with pytest.raises(ValueError, match=r"a stop_loss is finite and above zero \(C-2\.6\)"):
        _order("demo", reduce_only=True, effect=effect, stop_loss=Decimal(stop))


_WRONG_SIDE = r"a stop_loss is below a buy's reference_price, above a sell's \(C-2\.6\)"


@pytest.mark.parametrize(
    ("side", "stop"),
    [
        ("buy", "63100.0"),  # at the reference: no distance, no protection
        ("buy", "63100.1"),
        ("sell", "63100.0"),
        ("sell", "63099.9"),
    ],
)
@pytest.mark.parametrize("effect", [OrderEffect.ENTRY, OrderEffect.REDUCE])
def test_sized_order_refuses_a_stop_off_the_protective_side(
    side: Side, stop: str, effect: OrderEffect
) -> None:
    """Below a buy's reference price and above a sell's, as `classify.stop_errors` judges any
    stop, using the order's own side and reference price (63100.0)."""
    with pytest.raises(ValueError, match=_WRONG_SIDE):
        _order("demo", side=side, reduce_only=True, effect=effect, stop_loss=Decimal(stop))


@pytest.mark.parametrize(("side", "stop"), [("buy", "63099.9"), ("sell", "63100.1")])
@pytest.mark.parametrize("effect", [OrderEffect.ENTRY, OrderEffect.REDUCE])
def test_sized_order_builds_with_a_stop_a_tick_to_the_protective_side(
    side: Side, stop: str, effect: OrderEffect
) -> None:
    order = _order("demo", side=side, reduce_only=True, effect=effect, stop_loss=Decimal(stop))
    assert order.stop_loss == Decimal(stop)


@pytest.mark.parametrize("reference", ["0", "-1", "NaN", "sNaN", "Infinity", "-Infinity"])
def test_sized_order_refuses_a_stop_judged_against_a_reference_price_not_above_zero(
    reference: str,
) -> None:
    """As `NativeStopGuard.admit` refuses to judge one; compared, a NaN would raise."""
    with pytest.raises(ValueError, match="a stop_loss is judged against a reference_price above"):
        _order("demo", reference_price=Decimal(reference))


def test_sized_order_refuses_an_order_that_only_reduces_but_is_not_reduce_only() -> None:
    with pytest.raises(ValueError, match="an order that only reduces is reduce_only"):
        _order("demo", effect=OrderEffect.REDUCE, intent="scale_out", stop_loss=None)


def test_sized_order_takes_an_effect_string_as_its_member() -> None:
    """The effect is coerced, so every `is` comparison downstream holds."""
    assert _order("demo", effect="entry").effect is OrderEffect.ENTRY
    reduce = _order("demo", effect="reduce", reduce_only=True, stop_loss=None)
    assert reduce.effect is OrderEffect.REDUCE


def test_sized_order_holds_an_entry_string_to_the_stop_an_entry_needs() -> None:
    with pytest.raises(ValueError, match="an entry carries a stop_loss"):
        _order("demo", effect="entry", stop_loss=None)


@pytest.mark.parametrize("effect", ["bogus", "ENTRY", "", None])
def test_sized_order_refuses_an_effect_that_names_no_order_effect(effect: object) -> None:
    with pytest.raises(ValueError, match="is not a valid OrderEffect"):
        _order("demo", effect=effect)


# --- FixedQtySizer (R4: fixed_qty only) ----------------------------------------------------------


def test_fixed_qty_sizer_floors_the_quantity_to_the_lot_step() -> None:
    sized = FixedQtySizer().size(SizingRequest(mode="fixed_qty", qty=Decimal("0.0019")), INSTRUMENT)
    assert sized == Decimal("0.001")


def test_fixed_qty_sizer_without_round_to_lot_keeps_the_quantity_for_the_validator() -> None:
    sizing = SizingRequest(mode="fixed_qty", qty=Decimal("0.0019"), round_to_lot=False)
    assert FixedQtySizer().size(sizing, INSTRUMENT) == Decimal("0.0019")


def test_fixed_qty_sizer_needs_a_quantity() -> None:
    with pytest.raises(OrderInvalid) as refused:
        FixedQtySizer().size(SizingRequest(mode="fixed_qty"), INSTRUMENT)
    assert refused.value.errors == (
        FieldError("sizing.qty", "required", "fixed_qty sizing needs a qty."),
    )


@pytest.mark.parametrize("qty", ["NaN", "Infinity", "-Infinity"])
def test_fixed_qty_sizer_refuses_a_quantity_that_is_not_finite(qty: str) -> None:
    with pytest.raises(OrderInvalid) as refused:
        FixedQtySizer().size(SizingRequest(mode="fixed_qty", qty=Decimal(qty)), INSTRUMENT)
    assert refused.value.detail == "The quantity must be a finite number."


@pytest.mark.parametrize(
    "mode", ["fixed_notional", "pct_equity", "risk_based", "pct_position", "profile"]
)
def test_fixed_qty_sizer_refuses_every_other_sizing_mode(mode: Any) -> None:
    """R4 as 22 `placeOrder` words it: `validation_failed` / `sizing_mode_unsupported`."""
    with pytest.raises(OrderInvalid) as refused:
        FixedQtySizer().size(SizingRequest(mode=mode, qty=Decimal("1")), INSTRUMENT)
    only = "Only fixed_qty sizing is available yet."
    assert refused.value.errors == (FieldError("sizing.mode", "sizing_mode_unsupported", only),)
    assert refused.value.detail == only


# --- InterimStopResolver (R4: price, ticks, percent and the profile's offset) --------------------


def _resolve(
    stop: StopOffset | None,
    *,
    side: Side = "buy",
    reference: str = "63100",
    effect: OrderEffect = OrderEffect.ENTRY,
    profile: AccountProfile | None = None,
) -> Decimal | None:
    return InterimStopResolver().resolve(
        stop,
        side=side,
        reference_price=Decimal(reference),
        effect=effect,
        instrument=INSTRUMENT,
        profile=profile,
    )


@pytest.mark.parametrize(
    ("side", "unit", "value", "expected"),
    [
        ("buy", "price", "63099.85", "63099.8"),  # off-tick: rounded away from the entry
        ("sell", "price", "63100.05", "63100.1"),
        ("buy", "price", "63050", "63050"),
        ("buy", "ticks", "200", "63080.0"),
        ("sell", "ticks", "200", "63120.0"),
        ("buy", "percent", "0.4", "62847.6"),  # 0.4 % as a client writes it
        ("sell", "percent", "0.4", "63352.4"),
        ("buy", "percent", "0.33", "62891.7"),  # 62891.77 floored to the tick
        ("sell", "percent", "0.33", "63308.3"),  # 63308.23 ceiled to the tick
    ],
)
def test_interim_stop_resolver_resolves_a_request_stop_conservatively(
    side: Side, unit: Any, value: str, expected: str
) -> None:
    stop = StopOffset(unit=unit, value=Decimal(value))
    assert _resolve(stop, side=side) == Decimal(expected)


@pytest.mark.parametrize("unit", ["atr", "r_multiple"])
@pytest.mark.parametrize("effect", [OrderEffect.ENTRY, OrderEffect.REDUCE])
def test_interim_stop_resolver_refuses_atr_and_r_multiple_stops(
    unit: Any, effect: OrderEffect
) -> None:
    with pytest.raises(StopUnitUnsupported) as refused:
        _resolve(StopOffset(unit=unit, value=Decimal("1.5")), effect=effect)
    message = "Stops in atr or r_multiple units are not available yet."
    assert refused.value.errors == (FieldError("stop_loss", RULE_STOP_UNIT_UNSUPPORTED, message),)


def test_a_request_percent_is_a_percent_and_a_profile_percent_a_fraction() -> None:
    """22 `Offset`: `"1"` percent is 1 %; `AccountProfile` keeps 1 % as `0.01` (24 Sec.9.2)."""
    request = _resolve(StopOffset(unit="percent", value=Decimal("1")), reference="100")
    profile = _resolve(None, reference="100", profile=_profile("fixed_qty"))
    assert request == profile == Decimal("99.0")


@pytest.mark.parametrize(
    ("mode", "side", "expected"),
    [
        ("fixed_qty", "buy", "62469.0"),  # 1 % below 63100
        ("fixed_qty", "sell", "63731.0"),
        ("fixed_notional", "buy", "63095.0"),  # 50 ticks of 0.1 below
        ("risk_based", "sell", "63102.0"),  # 20 ticks above
    ],
)
def test_interim_stop_resolver_applies_the_profile_offset_to_an_entry_without_a_stop(
    mode: str, side: Side, expected: str
) -> None:
    assert _resolve(None, side=side, profile=_profile(mode)) == Decimal(expected)


def test_interim_stop_resolver_refuses_a_profile_offset_in_atr() -> None:
    with pytest.raises(StopUnitUnsupported):
        _resolve(None, profile=_profile("pct_equity"))  # 1.5 x ATR(14)


def test_interim_stop_resolver_gives_no_stop_to_an_order_that_only_reduces() -> None:
    assert _resolve(None, effect=OrderEffect.REDUCE, profile=_profile("fixed_qty")) is None


@pytest.mark.parametrize("effect", ["entry", "bogus"])
def test_interim_stop_resolver_gives_any_effect_but_reduce_the_profile_offset(effect: Any) -> None:
    """Fail closed: an effect that is not the `REDUCE` member is an entry's, a string too."""
    assert _resolve(None, effect=effect, profile=_profile("fixed_qty")) == Decimal("62469.0")


def test_interim_stop_resolver_gives_no_stop_to_an_entry_without_profile_or_stop() -> None:
    assert _resolve(None) is None  # NativeStopGuard then refuses it (C-2.6)


@given(
    side=st.sampled_from(["buy", "sell"]),
    unit=st.sampled_from(["ticks", "percent"]),
    value=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("90"), places=2),
    reference=st.decimals(min_value=Decimal("1"), max_value=Decimal("100000"), places=1),
)
def test_property_a_resolved_stop_is_on_tick_and_never_closer_than_its_offset(
    side: Side, unit: Any, value: Decimal, reference: Decimal
) -> None:
    resolved = _resolve(StopOffset(unit=unit, value=value), side=side, reference=str(reference))
    assert resolved is not None
    tick = INSTRUMENT.tick_size
    distance = value * tick if unit == "ticks" else reference * value / 100
    exact = reference - distance if side == "buy" else reference + distance
    assert resolved % tick == 0
    if side == "buy":
        assert resolved <= exact and resolved == (exact / tick).quantize(1, ROUND_FLOOR) * tick
    else:
        assert resolved >= exact and resolved == (exact / tick).quantize(1, ROUND_CEILING) * tick


# --- InterimRiskGate (R4: admits demo, refuses live) ---------------------------------------------


def test_interim_risk_gate_admits_a_demo_order_without_evaluating_it() -> None:
    decision = InterimRiskGate(now=lambda: NOW).check(_order("demo"), profile=_profile())
    assert decision == RiskDecision(allowed=True, evaluated_at=NOW)


@pytest.mark.parametrize("environment", ["live", "testnet"])
def test_interim_risk_gate_refuses_every_order_outside_demo(environment: Environment) -> None:
    decision = InterimRiskGate(now=lambda: NOW).check(_order(environment), profile=_profile())
    assert not decision.allowed
    assert decision.code is RiskRefusal.RISK_STATE_UNAVAILABLE
    assert decision.message == "No risk evaluation is available for this environment yet."
    assert decision.evaluated_at == NOW and decision.cap is None


def test_interim_risk_gate_refuses_a_live_reduce_only_order_too() -> None:
    order = _order("live", reduce_only=True, effect=OrderEffect.REDUCE, intent="scale_out")
    assert not InterimRiskGate(now=lambda: NOW).check(order, profile=None).allowed


# --- NoArmRecords (R4: refuses every live order) -------------------------------------------------


def test_an_arm_token_never_shows_its_value() -> None:
    """C-12.6: its `str`, `repr` and format are masked, and as a `Secret` the redaction filter
    writes it as `***` under any key; `reveal()` alone gives the value back."""
    held = ArmToken(_ISSUED)
    assert isinstance(held, Secret)
    assert _ISSUED not in f"{held} {held!r} {held:>40}"
    assert held.reveal() == _ISSUED


def test_arm_tokens_are_equal_when_their_values_are() -> None:
    held = ArmToken(_ISSUED)
    assert held == ArmToken(_ISSUED)
    assert held != ArmToken(_ANOTHER)
    assert held != ArmToken("")


def test_an_arm_token_never_equals_a_plain_string_or_another_kind_of_secret() -> None:
    """Neither comparison would be constant time: a `Secret`'s `==` is the strings' own."""
    held = ArmToken(_ISSUED)
    assert held != _ISSUED
    assert held != Secret(_ISSUED)
    assert Secret(_ISSUED) != held


def test_arm_tokens_compare_in_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """SR-043: through `hmac.compare_digest` over the encoded values, never `==` on the strings,
    so the time a comparison takes tells nothing of how much of a presented token matches."""
    compared: list[tuple[object, object]] = []
    compare_digest = hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        compared.append((a, b))
        return compare_digest(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    assert ArmToken(_ISSUED) != ArmToken(_ANOTHER)
    assert compared == [(_ISSUED.encode(), _ANOTHER.encode())]


def test_every_arm_token_hashes_alike() -> None:
    """Equal tokens hash alike, and the hash carries nothing of the token."""
    assert hash(ArmToken(_ISSUED)) == hash(ArmToken(_ANOTHER)) == hash(ArmToken(""))
    assert len({ArmToken(_ISSUED), ArmToken(_ISSUED), ArmToken(_ANOTHER)}) == 2


def test_no_arm_records_refuses_every_live_order_whatever_the_token() -> None:
    arm = NoArmRecords()
    for issued in (None, ArmToken(""), ArmToken(_ISSUED)):
        assert arm.check(session_id=SESSION, environment="live", token=issued) == FAILED


@pytest.mark.parametrize("environment", ["demo", "testnet"])
def test_no_arm_records_needs_no_token_outside_live(environment: Environment) -> None:
    assert NoArmRecords().check(session_id=SESSION, environment=environment, token=None) == PASSED


def test_no_arm_records_never_logs_the_token() -> None:
    with capture_logs() as logs:
        NoArmRecords().check(session_id=SESSION, environment="live", token=ArmToken(_ISSUED))
    assert _ISSUED not in repr(logs)


def test_the_interim_ports_refuse_every_live_order() -> None:
    """R4, fail closed on live: the bundle never admits a live order, reduce-only included."""
    ports = SubmissionPorts.interim(now=lambda: NOW)
    for order in (_order("live"), _order("live", reduce_only=True, effect=OrderEffect.REDUCE)):
        assert not ports.risk_gate.check(order, profile=_profile()).allowed
        held = ArmToken(_ISSUED)
        verdict = ports.arm_records.check(session_id=SESSION, environment="live", token=held)
        assert verdict == FAILED


# --- the startup announcement and oms_interim_ports ----------------------------------------------


def test_submission_ports_name_their_fields_after_the_port_names() -> None:
    assert tuple(f.name for f in dataclasses.fields(SubmissionPorts)) == PORT_NAMES


def test_submission_ports_interim_wires_one_interim_port_per_slot() -> None:
    ports = SubmissionPorts.interim(now=lambda: NOW)
    for name in PORT_NAMES:
        port = getattr(ports, name)
        assert isinstance(port, Interim) and port.port == name


def _gauge(metrics: Metrics, port: str) -> float | None:
    labels = {"env": metrics.env, "port": port}
    return metrics.registry.get_sample_value(INTERIM_PORTS_METRIC, labels)


def test_announce_logs_each_interim_port_once_and_counts_it() -> None:
    metrics = Metrics("demo")
    with capture_logs() as logs:
        announced = announce_interim_ports(
            SubmissionPorts.interim(now=lambda: NOW), metrics=metrics
        )
    assert announced == PORT_NAMES
    assert [(log["event"], log["log_level"], log["port"]) for log in logs] == [
        ("oms_interim_port", "warning", name) for name in PORT_NAMES
    ]
    assert all(log["replaced_by"] and log["serves"] for log in logs)
    assert [_gauge(metrics, name) for name in PORT_NAMES] == [1.0] * 4


def test_announce_counts_a_real_port_as_zero_and_logs_nothing_for_it() -> None:
    class _RealRiskGate:
        def check(self, order: SizedOrder, *, profile: AccountProfile | None) -> RiskDecision:
            return RiskDecision(allowed=True, evaluated_at=NOW)

    ports = dataclasses.replace(SubmissionPorts.interim(now=lambda: NOW), risk_gate=_RealRiskGate())
    metrics = Metrics("live")
    with capture_logs() as logs:
        announced = announce_interim_ports(ports, metrics=metrics)
    assert announced == ("sizer", "stop_resolver", "arm_records")
    assert [log["port"] for log in logs] == list(announced)
    assert _gauge(metrics, "risk_gate") == 0.0
    assert _gauge(metrics, "arm_records") == 1.0


def test_announce_registers_the_gauge_from_its_catalogue_entry() -> None:
    [spec] = [s for s in CATALOGUE if s.name == INTERIM_PORTS_METRIC]
    assert (spec.kind, spec.labels, spec.max_series) == ("gauge", ("port",), len(PORT_NAMES))
    assert (spec.status, spec.owner_epic) == ("planned", "E29")
    metrics = Metrics("demo")
    announce_interim_ports(SubmissionPorts.interim(now=lambda: NOW), metrics=metrics)
    gauge = metrics.get(INTERIM_PORTS_METRIC)
    assert gauge.series_count == len(PORT_NAMES) and not gauge.breached
    [family] = [f for f in metrics.registry.collect() if f.name == INTERIM_PORTS_METRIC]
    assert family.documentation == spec.help


# -- slice 2b: the clock and account ports --------------------------------------------------------

_CLOCK_MEMBERS: Final = ("assert_healthy", "offset_age_s", "resync_after_signature_failure")


async def _server_time() -> tuple[int, float, float]:
    return 0, 0.0, 0.0


def test_the_clock_guard_as_it_stands_and_the_fake_are_clock_healths() -> None:
    """Slice 3 wires `ingestion.clock.ClockGuard` with no adapter, as mypy reads the list below,
    and the fake answers alike: each member as the port declares it, sync or async, its
    parameters of the same kinds, any other with a default. `oms` itself never imports
    `ingestion` (C-3.4, `.importlinter`'s forbidden-M14)."""
    clocks: list[ClockHealth] = [ClockGuard(_server_time), FakeClockHealth(time.monotonic)]
    for clock in clocks:
        for name in _CLOCK_MEMBERS:
            port, member = getattr(ClockHealth, name), getattr(type(clock), name)
            assert inspect.iscoroutinefunction(member) == inspect.iscoroutinefunction(port)
            wanted = inspect.signature(port).parameters
            offered = inspect.signature(member).parameters
            assert set(wanted) <= set(offered)
            assert all(offered[n].kind == p.kind for n, p in wanted.items())
            assert all(p.default is not p.empty for n, p in offered.items() if n not in wanted)


def test_trading_accounts_takes_the_account_id_alone() -> None:
    """SR-E27-21: the key comes only from the account the OMS scope-checked, so the port takes
    nothing a request could use to select one, and answers the trading port's `AccountRef`."""
    member = TradingAccounts.trading_account
    assert inspect.iscoroutinefunction(member)
    assert list(inspect.signature(member).parameters) == ["self", "account_id"]
    hints = get_type_hints(member)
    assert (hints["account_id"], hints["return"]) == (AccountId, AccountRef)
