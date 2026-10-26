"""E28-T03 (#907) observability: the leg sizer's four series, recorded beside the pure `size_leg`
(BQ-20), each with a closed label set the catalogue's `max_series` holds exactly."""

from __future__ import annotations

import ast
import copy
import inspect
from collections.abc import Callable, Iterator

import pytest

from candleviewer.accounts import sizer as sz
from candleviewer.accounts import sizer_metrics as sm
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE, SIZER_BUCKETS
from tests.unit.accounts.test_sizer import instrument, profile, sized, wallet
from tests.unit.accounts.test_sizer_caps import _LEGS, leg, run, vector
from tests.unit.accounts.test_sizer_golden import VECTORS

_NAMES = (sm.DURATION, sm.OUTCOMES, sm.CLAMPED, sm.FALLBACK)


def _metrics() -> tuple[Metrics, sm.SizerMetrics]:
    metrics = Metrics("dev")
    return metrics, sm.SizerMetrics.register(metrics)


def _value(metrics: Metrics, name: str, **labels: str) -> float:
    got = metrics.registry.get_sample_value(name, {"env": "dev", **labels})
    assert got is not None, (name, labels)
    return got


def _ticks(*readings: float) -> Callable[[], float]:
    it: Iterator[float] = iter(readings)
    return lambda: next(it)


def test_sizer_metrics_catalogue_entries_are_live_and_capped_by_their_closed_sets() -> None:
    spec = {s.name: s for s in CATALOGUE}
    got = {n: (spec[n].kind, spec[n].labels, spec[n].status, spec[n].owner_epic) for n in _NAMES}
    assert got == {
        sm.DURATION: ("histogram", (), "live", "E28"),
        sm.OUTCOMES: ("counter", ("outcome", "reason"), "live", "E28"),
        sm.CLAMPED: ("counter", ("cap",), "live", "E28"),
        sm.FALLBACK: ("counter", (), "live", "E28"),
    }
    assert spec[sm.OUTCOMES].max_series == len(sm.OUTCOME_REASONS) == len(set(sm.OUTCOME_REASONS))
    assert spec[sm.CLAMPED].max_series == len(sm.CAPS) == len(set(sm.CAPS))
    assert spec[sm.DURATION].buckets == SIZER_BUCKETS and 1e-3 in SIZER_BUCKETS  # the p95 budget


def test_sizer_metrics_outcome_reasons_are_every_enum_member_and_ok_alone() -> None:
    by = {o: {r for k, r in sm.OUTCOME_REASONS if k == o} for o in ("ok", "skip", "fail")}
    assert by == {
        "ok": {"none"},
        "skip": {r.value for r in sz.SkipReason},
        "fail": {r.value for r in sz.FailReason},
    }


def test_sizer_metrics_register_binds_every_series_at_zero_and_is_idempotent() -> None:
    metrics, _ = _metrics()
    sm.SizerMetrics.register(metrics)  # a second registration re-fetches the same metrics
    for outcome, reason in sm.OUTCOME_REASONS:
        assert _value(metrics, sm.OUTCOMES, outcome=outcome, reason=reason) == 0
    for cap in sm.CAPS:
        assert _value(metrics, sm.CLAMPED, cap=cap) == 0
    assert _value(metrics, sm.FALLBACK) == 0
    assert _value(metrics, f"{sm.DURATION}_count") == 0
    assert not any(metrics.get(n).breached for n in _NAMES)


def test_size_leg_observed_records_an_ok_leg_its_time_and_no_clamp() -> None:
    metrics, observer = _metrics()
    p = profile("P-QTY")
    it = sz.SizingIntent.model_validate(
        {"symbol": "BTCUSDT", "side": "buy", "order_type": "limit", "price": "64000.0"}
    )
    inst, market, ticks = instrument("BTCUSDT"), sz.SizingMarket(), _ticks(2, 2.5)
    got = sm.size_leg_observed(it, p, wallet(), inst, market, observer=observer, clock=ticks)
    want = sized(p)
    assert got == want and got.outcome == "ok"
    assert _value(metrics, sm.OUTCOMES, outcome="ok", reason="none") == 1
    assert _value(metrics, f"{sm.DURATION}_count") == 1
    assert _value(metrics, f"{sm.DURATION}_sum") == 0.5
    assert sum(_value(metrics, sm.CLAMPED, cap=c) for c in sm.CAPS) == 0
    assert _value(metrics, sm.FALLBACK) == 0


@pytest.mark.parametrize(
    ("name", "outcome", "reason"),
    [
        ("denied", "skip", "symbol_denied"),
        ("no-price", "fail", "no_reference_price"),
        ("room-spent", "fail", "cap_breached"),
    ],
)
def test_sizer_metrics_record_counts_skips_and_failures_by_their_reason(
    name: str, outcome: str, reason: str
) -> None:
    metrics, observer = _metrics()
    result = leg(name)
    assert (result.outcome, result.reason) == (outcome, reason)
    observer.record(result, 0.0001)
    assert _value(metrics, sm.OUTCOMES, outcome=outcome, reason=reason) == 1
    total = sum(_value(metrics, sm.OUTCOMES, outcome=o, reason=r) for o, r in sm.OUTCOME_REASONS)
    assert total == 1


def test_sizer_metrics_record_counts_each_cap_that_lowered_the_quantity() -> None:
    metrics, observer = _metrics()
    result = leg("market-at-mid")
    fired = [rule for rule in result.rules if rule in sm.CAPS]
    assert result.binding is not None and fired and fired[-1] == result.binding.cap
    observer.record(result, 0.0001)
    for cap in sm.CAPS:
        assert _value(metrics, sm.CLAMPED, cap=cap) == fired.count(cap)


def test_sizer_metrics_record_counts_the_atr_fallback() -> None:
    metrics, observer = _metrics()
    result = leg("atr-fallback")
    assert result.stop_fallback
    observer.record(result, 0.0001)
    observer.record(vector("V01"), 0.0001)  # an ok leg with no fallback adds none
    assert _value(metrics, sm.FALLBACK) == 1


def test_size_leg_stays_pure_and_records_nothing() -> None:
    metrics, _ = _metrics()
    first, second = leg("market-at-mid"), leg("market-at-mid")
    assert first == second
    assert (
        sum(_value(metrics, sm.OUTCOMES, outcome=o, reason=r) for o, r in sm.OUTCOME_REASONS) == 0
    )
    assert _value(metrics, f"{sm.DURATION}_count") == 0
    tree = ast.parse(inspect.getsource(sz))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not {m for m in imported if m and ("observability" in m or m in {"time", "logging"})}


def _total(metrics: Metrics) -> float:
    return sum(_value(metrics, sm.OUTCOMES, outcome=o, reason=r) for o, r in sm.OUTCOME_REASONS)


def test_sizer_metrics_record_accepts_every_golden_vector_and_named_leg() -> None:
    metrics, observer = _metrics()
    legs = [run(v) for v in VECTORS] + [leg(name) for name in _LEGS]
    for result in legs:
        observer.record(result, 0.0001)
    assert _total(metrics) == len(legs) > 40
    assert _value(metrics, f"{sm.DURATION}_count") == len(legs)


def test_sizer_metrics_record_never_raises_on_a_pair_outside_the_catalogue() -> None:
    metrics, observer = _metrics()
    bad = copy.copy(leg("denied"))  # skip / symbol_denied
    object.__setattr__(bad, "reason", sz.FailReason.CAP_BREACHED)  # ("skip", a fail reason)
    observer.record(bad, 0.0001)  # no KeyError, and nothing half-recorded
    assert _total(metrics) == 0
    assert _value(metrics, f"{sm.DURATION}_count") == 0
    assert _value(metrics, sm.FALLBACK) == 0


def test_size_leg_observed_propagates_a_sizing_error_and_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics, observer = _metrics()

    def boom(*_: object) -> sz.LegSizing:
        raise RuntimeError("programming error")

    monkeypatch.setattr(sm, "size_leg", boom)
    it = sz.SizingIntent.model_validate(
        {"symbol": "BTCUSDT", "side": "buy", "order_type": "limit", "price": "64000.0"}
    )
    with pytest.raises(RuntimeError, match="programming error"):
        sm.size_leg_observed(
            it,
            profile("P-QTY"),
            wallet(),
            instrument("BTCUSDT"),
            sz.SizingMarket(),
            observer=observer,
            clock=_ticks(1, 2),
        )
    assert _total(metrics) == 0
    assert _value(metrics, f"{sm.DURATION}_count") == 0


@pytest.mark.parametrize("rule", ["stop_atr", "tp_ladder"])
def test_sizer_metrics_record_counts_no_cap_for_a_non_cap_rule(rule: str) -> None:
    metrics, observer = _metrics()
    base = vector("V01")
    assert rule not in sm.CAPS
    stub = copy.copy(base)
    object.__setattr__(stub, "rules", (rule,))
    observer.record(stub, 0.0001)
    assert sum(_value(metrics, sm.CLAMPED, cap=c) for c in sm.CAPS) == 0
    assert _total(metrics) == 1
