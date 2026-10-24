"""The ports the submission pipeline consumes and their interim implementations (E29-T04, #913).

Ruling R4: the sizer serves `fixed_qty` only, refusing another mode with
`sizing_mode_unsupported`; the stop resolver serves `price`, `ticks` and `percent` stops and the
profile's offset, refusing `atr` and `r_multiple` with `stop_unit_unsupported`; the risk gate
admits demo and refuses live; `NoArmRecords` refuses every live order. Each interim port logs once
at startup and is counted in `oms_interim_ports{port}`. A `SizedOrder` is as strict as
`classify.stop_errors`: an entry carries a stop, and any stop is finite, above zero and on the
protective side of its reference price (C-2.6); its effect is an `OrderEffect`, and any effect but
`REDUCE` is an entry's (fail closed). The arm token travels masked (C-12.6) and compares in
constant time (SR-043). Slice 2b: the take-profit interim (S2-Q6, Q-L), an offset that is no finite
figure passed through for the guard (#2877 ruling 2), and the request's records (C-2.9). E29-T05
(#848, 24 Sec.8.12): the private-stream consumer's ports and their stand-ins.
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
from typing import Any, Final, cast, get_args, get_type_hints
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.accounts.profiles import AccountProfile
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Environment, Side
from candleviewer.exchange.base.models import PRIVATE_STREAM_REASONS, AccountRef, Execution, Order
from candleviewer.ingestion.clock import ClockGuard
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.observability.secret_type import Secret
from candleviewer.oms import order_machine
from candleviewer.oms.errors import (
    RULE_STOP_UNIT_UNSUPPORTED,
    FieldError,
    HandoverUnavailable,
    OrderInvalid,
    ProtectionReadingsUnavailable,
    ReconciliationUnavailable,
    StopUnitUnsupported,
)
from candleviewer.oms.fakes import (
    FakeClockHealth,
    InMemoryAccountNotices,
    InMemoryForeignOrderLockout,
    InMemoryReconciliationRequests,
    InMemoryStreamedAccounts,
)
from candleviewer.oms.ports import (
    FAILED,
    INTERIM_PORT_LABELS,
    INTERIM_PORTS_METRIC,
    PASSED,
    PORT_NAMES,
    AccountNoticeReason,
    AccountNotices,
    ArmToken,
    AuditOutcome,
    AuditSeverity,
    ClockHealth,
    ExecutionHandovers,
    Finding,
    FixedQtySizer,
    ForeignOrderLockout,
    Interim,
    InterimRiskGate,
    InterimStopResolver,
    KeyedRecord,
    NoArmRecords,
    NoHandoverStore,
    NoPositionProtection,
    NoReconciliation,
    OrderEffect,
    OrderHandovers,
    PositionKey,
    Profiles,
    ProtectionReading,
    ProtectionReadings,
    RateReading,
    ReconciliationRequests,
    ResyncReason,
    SizedOrder,
    SizingRequest,
    StopOffset,
    StreamedAccounts,
    SubmissionPorts,
    SubmitActor,
    TradingAccounts,
    Verdict,
    announce_interim_port,
    announce_interim_ports,
    refuse_live_without_reconciliation,
)
from candleviewer.risk.models import RiskDecision, RiskRefusal
from candleviewer.settings import Environment as ProcessEnvironment
from candleviewer.statechart.bindings import b01_order
from candleviewer.storage.errors import StorageTierUnavailable

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


@pytest.mark.parametrize("name", INTERIM_PORT_LABELS)
def test_announce_one_port_takes_every_label_of_the_closed_set(name: str) -> None:
    metrics = Metrics("demo")
    assert announce_interim_port(cast(Any, name), object(), metrics=metrics) is False
    assert _gauge(metrics, name) == 0.0


def test_announce_one_port_refuses_a_label_outside_the_closed_set_before_any_series() -> None:
    """CR-S3B2-06: `INTERIM_PORT_LABELS` is the gauge's closed set, so a mistyped label raises,
    instead of a series the cap drops without a word."""
    metrics = Metrics("demo")
    with capture_logs() as logs, pytest.raises(ValueError, match="kill_swtich"):
        announce_interim_port(cast(Any, "kill_swtich"), object(), metrics=metrics)
    assert logs == []  # no warning, and the gauge was never registered
    assert not [f for f in metrics.registry.collect() if f.name == INTERIM_PORTS_METRIC]


def test_announce_registers_the_gauge_from_its_catalogue_entry() -> None:
    [spec] = [s for s in CATALOGUE if s.name == INTERIM_PORTS_METRIC]
    assert (spec.kind, spec.labels, spec.max_series) == ("gauge", ("port",), 6)
    assert INTERIM_PORT_LABELS == (*PORT_NAMES, "kill_switch", "machine_event_sink")
    assert (spec.status, spec.owner_epic) == ("planned", "E29")
    metrics = Metrics("demo")
    announce_interim_ports(SubmissionPorts.interim(now=lambda: NOW), metrics=metrics)
    gauge = metrics.get(INTERIM_PORTS_METRIC)
    assert gauge.series_count == len(PORT_NAMES) and not gauge.breached
    [family] = [f for f in metrics.registry.collect() if f.name == INTERIM_PORTS_METRIC]
    assert family.documentation == spec.help


# -- the clock and account ports (`ClockHealth`, `TradingAccounts`) -------------------------------

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


def test_a_rate_reading_admits_with_no_delay_and_refuses_with_one() -> None:
    """24 Sec.8.7: an admission carries no `Retry-After`; a refusal carries whole seconds, 1 or
    more (429 `exchange_rate_limited`)."""
    assert RateReading(available=True).retry_after_s is None
    assert RateReading(available=False, retry_after_s=1).retry_after_s == 1
    for refused in (None, 0, -1, 1.5, True, "2"):
        with pytest.raises(ValueError, match="at least one whole second"):
            RateReading(available=False, retry_after_s=cast(Any, refused))  # each one off the type
    with pytest.raises(ValueError, match="no retry_after_s"):
        RateReading(available=True, retry_after_s=1)


# --- the command port's collaborators (`commands.OmsCommandPort`) --------------------------------


_KEY = PositionKey(AccountId(UUID(int=7)), "BTCUSDT", 0)


async def test_no_handover_store_hands_nothing_over() -> None:
    """S2-Q3's deviation until E29-T06: every hand-over is refused."""
    order = Order.model_validate(
        {
            "order_link_id": "cvl-x",
            "exchange_order_id": "x1",
            "account_id": UUID(int=7),
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "limit",
            "qty": "1",
            "price": "1",
            "state": "new",
            "filled_qty": "0",
            "leaves_qty": "1",
            "avg_fill_price": None,
            "created_at": 0,
            "terminal_at": None,
        }
    )
    with pytest.raises(HandoverUnavailable):
        await NoHandoverStore().hand_over_order(AccountId(UUID(int=7)), order)


def test_a_keyed_records_vocabulary_is_the_facades() -> None:
    """`KeyedRecord` and `OrderAuditRecord` write one M19 vocabulary of outcomes and severities."""
    assert get_args(AuditOutcome) == get_args(order_machine.Outcome)
    assert get_args(AuditSeverity) == get_args(order_machine.Severity)


async def test_the_lockout_fake_opens_once_per_finding() -> None:
    """24 Sec.8.10, S2-Q7: opening where it is open changes nothing; a finding counts once."""
    lockout: ForeignOrderLockout = InMemoryForeignOrderLockout()
    account = AccountId(UUID(int=7))
    await lockout.open(account, finding="order", key="x1")
    await lockout.open(account, finding="order", key="x1")
    await lockout.open(account, finding="execution", key="e1")
    assert isinstance(lockout, InMemoryForeignOrderLockout)
    assert lockout.findings == {account: {("order", "x1"), ("execution", "e1")}}
    assert lockout.opens == 3 and lockout.is_open(account)
    assert not lockout.is_open(AccountId(UUID(int=8)))


# --- the take-profit (S2-Q6, Q-L), and an offset that is no finite figure (#2877 ruling 2) --------


def _take_profit(
    take_profit: StopOffset | None, *, side: Side = "buy", reference: str = "63100"
) -> Decimal | None:
    return InterimStopResolver().resolve_take_profit(
        take_profit,
        side=side,
        reference_price=Decimal(reference),
        instrument=INSTRUMENT,
        profile=_profile("fixed_qty"),
    )


@pytest.mark.parametrize(
    ("side", "unit", "value", "expected"),
    [
        ("buy", "price", "64000.07", "64000.0"),  # off-tick: rounded toward the entry
        ("sell", "price", "62000.03", "62000.1"),
        ("buy", "ticks", "200", "63120.0"),
        ("sell", "ticks", "200", "63080.0"),
        ("buy", "percent", "0.4", "63352.4"),  # 0.4 % as a client writes it
        ("sell", "percent", "0.4", "62847.6"),
        ("buy", "percent", "0.33", "63308.2"),  # 63308.23 floored, toward the entry
        ("sell", "percent", "0.33", "62891.8"),  # 62891.77 ceiled, toward the entry
    ],
)
def test_the_interim_take_profit_lands_on_a_tick_rounded_toward_the_entry(
    side: Side, unit: Any, value: str, expected: str
) -> None:
    assert _take_profit(StopOffset(unit=unit, value=Decimal(value)), side=side) == Decimal(expected)


@pytest.mark.parametrize("unit", ["atr", "r_multiple"])
def test_the_interim_take_profit_refuses_atr_and_r_multiple_on_its_own_field(unit: Any) -> None:
    with pytest.raises(StopUnitUnsupported) as refused:
        _take_profit(StopOffset(unit=unit, value=Decimal("2")))
    message = "Take-profits in atr or r_multiple units are not available yet."
    errors = (FieldError("take_profit", RULE_STOP_UNIT_UNSUPPORTED, message),)
    assert refused.value.errors == errors


def test_the_interim_take_profit_is_none_unasked_whatever_the_profile_offers() -> None:
    """The profile's offset (here `r_multiple`) is not applied to an order unasked: a take-profit
    is optional, unlike the stop (C-2.6)."""
    assert _profile("fixed_qty").tp_offset_unit is not None
    assert _take_profit(None) is None


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("unit", ["price", "ticks", "percent"])
def test_an_offset_that_is_no_finite_figure_is_passed_through_unresolved(
    unit: Any, value: str
) -> None:
    """#2877 ruling 2: nothing is computed from it, a signalling NaN included, so the guard
    refuses it (`stop_errors`, `take_profit_errors`) rather than the arithmetic raising."""
    offset = StopOffset(unit=unit, value=Decimal(value))
    resolved = [_resolve(offset), _take_profit(offset)]
    assert all(r is not None and not r.is_finite() for r in resolved)


def test_sized_order_takes_a_take_profit_on_the_profit_side() -> None:
    assert _order("demo", take_profit=Decimal("63500.0")).take_profit == Decimal("63500.0")
    sell = {"side": "sell", "stop_loss": Decimal("63300.0"), "take_profit": Decimal("62800.0")}
    assert _order("demo", **sell).take_profit == Decimal("62800.0")
    assert _order("demo").take_profit is None


@pytest.mark.parametrize(
    "take_profit", ["0", "-1", "NaN", "Infinity", "63100.0", "63000.0"],
    ids=["zero", "negative", "nan", "infinite", "at_reference", "wrong_side"],
)  # fmt: skip
def test_sized_order_refuses_a_take_profit_off_the_profit_side(take_profit: str) -> None:
    with pytest.raises(ValueError, match="take_profit"):
        _order("demo", take_profit=Decimal(take_profit))


# --- the request's records (C-2.9) ----------------------------------------------------------------


_ACTOR = SubmitActor(user_id=SESSION, role="owner", session_id=SESSION, ip="100.64.0.7")


def test_a_submit_actor_never_shows_its_address() -> None:
    assert "100.64.0.7" not in repr(_ACTOR)


def test_a_keyed_records_actor_is_its_actor_user_id() -> None:
    fields: dict[str, Any] = {
        "action": "sl.attached", "name": "n", "account_id": ACCOUNT,
        "object_kind": "recorded_stop", "object_id": SESSION, "outcome": "success",
        "severity": "info", "reason": "entry_attach", "detail": {},
    }  # fmt: skip
    assert KeyedRecord(**fields, actor_user_id=SESSION, actor=_ACTOR).actor == _ACTOR
    assert KeyedRecord(**fields, actor_user_id=None).actor is None
    with pytest.raises(ValueError, match="actor"):
        KeyedRecord(**fields, actor_user_id=None, actor=_ACTOR)


def test_the_profile_cache_as_it_stands_is_a_profiles_port() -> None:
    """Slice 3 wires `EffectiveProfiles` with no adapter (mypy checks the list's type)."""
    from candleviewer.accounts.profile_cache import EffectiveProfiles

    port: type[Profiles] = EffectiveProfiles
    member = inspect.signature(port.get_effective_profile)
    assert list(member.parameters) == ["self", "account_id", "profile_id"]


# --- the private-stream consumer's collaborators (E29-T05, 24 Sec.8.12) --------------------------

_PROTOCOL = Path(__file__).resolve().parents[5] / "docs" / "plan" / "23-ws-protocol.md"
#: Each consumer port, its stand-in and its one member, and whether the member awaits.
_CONSUMER_PORTS: Final = [
    (StreamedAccounts, InMemoryStreamedAccounts, "streamed_accounts", True),
    (ReconciliationRequests, InMemoryReconciliationRequests, "request_reconciliation", True),
    (ReconciliationRequests, NoReconciliation, "request_reconciliation", True),
    (AccountNotices, InMemoryAccountNotices, "publish", False),
    (ExecutionHandovers, NoHandoverStore, "hand_over_execution", True),
    (ProtectionReadings, NoPositionProtection, "take_reading", True),
]


def _fill() -> Execution:
    return Execution.model_validate(
        {
            "exec_id": "x1", "exchange_order_id": "e1", "order_link_id": "ext-" + "0" * 32,
            "account_id": ACCOUNT, "symbol": "BTCUSDT", "side": "buy", "price": "60000",
            "qty": "1", "fee": "0.1", "fee_rate": "0.00055", "fee_currency": "USDT",
            "is_maker": False, "exec_type": "trade", "closed_pnl": None, "ts_exec": 0,
            "ts_ingest": 0, "seq": 1,
        }
    )  # fmt: skip


@pytest.mark.parametrize(
    ("port", "stand_in", "name", "awaits"),
    _CONSUMER_PORTS,
    ids=[s.__name__ for _, s, *_ in _CONSUMER_PORTS],
)
def test_each_consumer_port_and_its_stand_in_take_the_same_call(
    port: type[Any], stand_in: type[Any], name: str, awaits: bool
) -> None:
    """The member each binding implements, awaited or not as the port says (`AccountNotices`
    never awaits, as the gateway's own offer does not), its parameters of the same names and
    kinds."""
    wanted, offered = getattr(port, name), getattr(stand_in, name)
    assert inspect.iscoroutinefunction(wanted) is awaits
    assert inspect.iscoroutinefunction(offered) is awaits
    shape = [(p.name, p.kind) for p in inspect.signature(wanted).parameters.values()]
    assert shape == [(p.name, p.kind) for p in inspect.signature(offered).parameters.values()]


def test_the_streamed_accounts_read_takes_nothing_that_could_select_a_key() -> None:
    """SR-E27-21, on the port itself, so no change to it and its stand-in together passes."""
    assert list(inspect.signature(StreamedAccounts.streamed_accounts).parameters) == ["self"]


def test_the_execution_hand_over_is_a_sibling_port_never_a_widening() -> None:
    """The agreed shape (E29-T05 with E29-T04): `OrderHandovers` is left as it is."""
    assert not hasattr(OrderHandovers, "hand_over_execution")
    assert not hasattr(ExecutionHandovers, "hand_over_order")


@pytest.mark.parametrize("binding", [ExecutionHandovers, NoHandoverStore])
def test_an_execution_hand_over_counts_no_empty_read_unless_told(binding: type[Any]) -> None:
    """24 Sec.8.5 step 3d's `empty_read=True`: keyword-only, and false unless a read found none."""
    empty_read = inspect.signature(binding.hand_over_execution).parameters["empty_read"]
    assert (empty_read.kind, empty_read.default) == (inspect.Parameter.KEYWORD_ONLY, False)


async def test_no_handover_store_keeps_no_execution_either() -> None:
    """S2-Q3's deviation, for the sibling port too: every execution hand-over is refused."""
    with pytest.raises(HandoverUnavailable):
        await NoHandoverStore().hand_over_execution(ACCOUNT, _fill(), empty_read=True)


def test_a_resync_reason_is_one_of_the_resyncing_statuses_reasons() -> None:
    """A stream asks for a pass with its `resyncing` status's reason (24 Sec.14.2 rule 13)."""
    assert set(get_args(ResyncReason)) == PRIVATE_STREAM_REASONS["resyncing"]


def test_an_account_notice_reason_is_one_the_ws_contract_names() -> None:
    """23 Sec.15.9's account notices: the reasons the OMS publishes are its current values."""
    contract = _PROTOCOL.read_text(encoding="utf-8")
    paragraph = contract.split("**Account notices (SR-E29-10", 1)[1].split("\n\n", 1)[0]
    named = {w.strip("`(),.") for w in paragraph.split() if w.startswith("`oms.account_")}
    assert named == set(get_args(AccountNoticeReason))


async def test_the_streamed_accounts_stand_in_answers_its_accounts() -> None:
    accounts: StreamedAccounts = InMemoryStreamedAccounts(ACCOUNT)
    assert await accounts.streamed_accounts() == frozenset({ACCOUNT})


async def test_the_streamed_accounts_stand_in_raises_its_error_and_keeps_its_accounts() -> None:
    accounts = InMemoryStreamedAccounts(ACCOUNT)
    accounts.error = StorageTierUnavailable("down")
    with pytest.raises(StorageTierUnavailable):
        await accounts.streamed_accounts()
    assert (accounts.reads, accounts.accounts) == (1, {ACCOUNT})


async def test_the_reconciliation_stand_in_keeps_each_request_in_order() -> None:
    other = AccountId(UUID(int=8))
    requests = InMemoryReconciliationRequests()
    await requests.request_reconciliation(ACCOUNT, reason="connected")
    await requests.request_reconciliation(other, reason="rejected_frame")
    assert requests.requests == [(ACCOUNT, "connected"), (other, "rejected_frame")]


def test_the_notice_stand_in_keeps_each_notice_in_order() -> None:
    notices = InMemoryAccountNotices()
    notices.publish(ACCOUNT, reason="oms.account_resyncing")
    notices.publish(ACCOUNT, reason="oms.account_synced")
    assert notices.published == [
        (ACCOUNT, "oms.account_resyncing"),
        (ACCOUNT, "oms.account_synced"),
    ]


async def test_no_reconciliation_refuses_every_request() -> None:
    """24 Sec.8.12: no pass exists until E29-T06, so the consumer pages once per episode."""
    with pytest.raises(ReconciliationUnavailable):
        await NoReconciliation().request_reconciliation(ACCOUNT, reason="reconnected")


def test_a_live_process_refuses_to_start_with_no_reconciliation() -> None:
    """24 Sec.8.12's live start-up check (C-2.21): the exchange is truth after a reconnect."""
    with pytest.raises(ReconciliationUnavailable):
        refuse_live_without_reconciliation(ProcessEnvironment.LIVE, NoReconciliation())


@pytest.mark.parametrize("environment", [ProcessEnvironment.DEMO, ProcessEnvironment.TESTNET])
def test_demo_and_testnet_start_with_no_reconciliation(environment: ProcessEnvironment) -> None:
    refuse_live_without_reconciliation(environment, NoReconciliation())


def test_a_live_process_starts_with_any_other_reconciliation_binding() -> None:
    refuse_live_without_reconciliation(ProcessEnvironment.LIVE, InMemoryReconciliationRequests())


def test_live_as_plain_text_refuses_no_reconciliation_too() -> None:
    """The environment compares by value, so an untyped caller's `"live"` cannot slip past."""
    as_text = cast(ProcessEnvironment, "live")  # a str where mypy wants the enum, on purpose
    with pytest.raises(ReconciliationUnavailable):
        refuse_live_without_reconciliation(as_text, NoReconciliation())


async def test_no_position_protection_refuses_a_lost_stop() -> None:
    """24 Sec.8.12: until E32-T02 binds B8, a lost stop no live order protects pages (C-2.6)."""
    lost = ProtectionReading("SL_LOST", 1, None, Decimal(1))
    with pytest.raises(ProtectionReadingsUnavailable):
        await NoPositionProtection().take_reading(_KEY, lost)


async def test_no_position_protection_takes_an_observed_stop_quietly() -> None:
    seen = ProtectionReading("SL_OBSERVED", 1, Decimal(59000), Decimal(1))
    await NoPositionProtection().take_reading(_KEY, seen)


def test_a_protection_reading_carries_b1s_reading_keys() -> None:
    """24 Sec.8.12: a position row becomes B1's `_READING`, which its guards read whole."""
    keys = {field.name for field in dataclasses.fields(ProtectionReading)} - {"event"}
    assert keys == set(b01_order._READING["properties"])


def test_an_undecided_fill_is_a_finding_of_its_own() -> None:
    """24 Sec.8.12 step 4: until E29-T06 it opens the lockout, fail closed, never as `execution`,
    so its record never claims the fill has no OMS intent (Sec.15.5)."""
    assert get_args(Finding) == ("order", "execution", "undecided")


def test_the_lockout_stand_ins_record_is_a_registered_action() -> None:
    """24 Sec.8.12 and Sec.15.5, contract first: the writer refuses an action it does not list."""
    assert "oms.no_intent_detected" in AUDIT_ACTIONS
