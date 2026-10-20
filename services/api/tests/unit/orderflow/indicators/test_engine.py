"""The indicator engine's admission, reads and lifecycle (E13-T02, #426; 23 §6.1; 24 §7.3, §7.4;
E13 threat model SR-E13-01/03/04, IR-24, IR-41, IR-45). Priming, swaps and repairs are in
`test_engine_priming.py`; the memo and amended closes have their own files."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
import structlog

from candleviewer.bars.metrics import bar_emit_sink_errors_total
from candleviewer.bars.models import BarSpec
from candleviewer.bars.series_store import Hold, SeriesStore
from candleviewer.orderflow.errors import (
    InstanceCapError,
    InstanceRefusedError,
    RecomputeRefusedError,
)
from candleviewer.orderflow.indicators.engine import (
    Available,
    IndicatorEngine,
    resolve_instances,
)
from candleviewer.orderflow.indicators.kernels import AtrKernel, EmaKernel
from candleviewer.orderflow.indicators.limits import MAX_WINDOW_BARS
from candleviewer.orderflow.indicators.metrics import CAP_REJECTED
from candleviewer.orderflow.indicators.types import BarInput, Outputs, Unavailable
from tests.unit.orderflow.indicators._engine import (
    ATR14,
    EMA3,
    M1,
    SYM,
    Listener,
    admit,
    bar,
    close,
    counter,
    wave,
)

RENKO = BarSpec(kind="renko", range_ticks=10)


class _Now:
    def __init__(self) -> None:
        self.us = 0

    def __call__(self) -> int:
        return self.us


async def _engine(spec: BarSpec = M1, **kw: Any) -> tuple[SeriesStore, IndicatorEngine, Hold]:
    """A store holding the series (keep the `Hold` for the test's life) and an engine on it."""
    store = SeriesStore()
    hold = await store.ensure(SYM, spec)
    return store, IndicatorEngine(store, **kw), hold


# -- resolve_instances (23 §6.1 refusals, IR-24, IR-41) ------------------------------------------


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ([{"indicator": "nope"}], "Instance 0: no indicator has that id."),
        ([{"indicator": "macd"}], "Instance 0: macd is computed in the chart, not served here."),
        (
            [*EMA3, {"indicator": "ema", "params": {"n": 5001}}],
            "Instance 1: n must be between 1 and 5000.",
        ),
        ([{"indicator": "ema", "params": {"n": 0}}], "Instance 0: n must be between 1 and 5000."),
        ([{"indicator": "ema", "params": {"n": 2.5}}], "Instance 0: n must be a whole number."),
        ([{"indicator": "ema", "params": {"n": True}}], "Instance 0: n must be a whole number."),
        (
            [{"indicator": "ema", "params": {"evil_param": 1}}],
            "Instance 0: ema takes only these parameters: n.",
        ),
        (
            [{"indicator": "zigzag", "params": {"deviation_pct": 0.05}}],
            "Instance 0: deviation_pct must be a multiple of 0.1.",
        ),
        ([*EMA3, {"indicator": "ema", "params": {"n": 3.0}}], "Instance 1: the same instance"),
    ],
)
def test_resolve_refuses_and_never_clamps_or_echoes_an_unknown_key(
    raw: list[dict[str, Any]], message: str
) -> None:
    with pytest.raises(InstanceRefusedError) as caught:
        resolve_instances(raw, M1)
    assert str(caught.value).startswith(message)
    assert "evil_param" not in str(caught.value)
    assert caught.value.position == int(message.split()[1].rstrip(":"))


@pytest.mark.parametrize("indicator", ["vwap", "cvd"])
def test_resolve_refuses_a_session_anchor_on_renko_bars(indicator: str) -> None:
    with pytest.raises(InstanceRefusedError, match="renko bars cannot anchor"):
        resolve_instances([{"indicator": indicator}], RENKO)
    assert resolve_instances(EMA3, RENKO)  # an index-only kernel reads renko bars


def test_resolve_writes_every_param_out_and_keys_each_instance_by_its_spec_hash() -> None:
    zz, vwap = resolve_instances([{"indicator": "zigzag"}, {"indicator": "vwap"}], M1)
    assert zz.echo() == {
        "indicator": "zigzag",
        "params": {"depth": 5, "deviation_pct": 0},
        "key": zz.spec.spec_hash,
    }
    assert vwap.echo()["params"] == {"anchor": "session"}
    assert vwap.info().outputs[0] == "vwap" and vwap.info().build_version >= 1
    other = resolve_instances([{"indicator": "vwap"}], BarSpec(kind="time", interval_ms=300_000))
    assert other[0].key != vwap.key  # the bar series is part of the identity (24 §7.4)


# -- admission caps (SR-E13-03, SR-E13-04) -------------------------------------------------------


async def test_the_ninth_distinct_instance_of_a_user_is_refused_naming_the_cap() -> None:
    _, engine, _hold = await _engine()
    for n in range(2, 10):
        admit(engine, [{"indicator": "ema", "params": {"n": n}}], consumer=f"c{n}")
    refused = counter(CAP_REJECTED["user"])
    with pytest.raises(InstanceCapError) as caught:
        admit(engine, [{"indicator": "ema", "params": {"n": 10}}], consumer="c10")
    assert (caught.value.cap, caught.value.limit) == ("user", 8)
    assert str(caught.value) == "At most 8 server indicator instances per user."
    assert counter(CAP_REJECTED["user"]) - refused == 1
    assert engine.instances(SYM, M1.spec_hash) == 8  # nothing was held for the refusal
    admit(engine, [{"indicator": "ema", "params": {"n": 10}}], consumer="sys", user=None)


async def test_a_window_past_its_bound_is_refused_before_anything_is_held() -> None:
    _, engine, _hold = await _engine()
    requested = resolve_instances(ATR14, M1)
    refused = counter(CAP_REJECTED["window"])
    with pytest.raises(RecomputeRefusedError) as caught:
        engine.check(SYM, M1, requested, "u1", history=MAX_WINDOW_BARS)
    assert caught.value.cap == "window" and "250000" in str(caught.value)
    assert counter(CAP_REJECTED["window"]) - refused == 1
    assert engine.instances(SYM, M1.spec_hash) == 0


async def test_no_kernel_exists_before_validate_params_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine builds kernels from `resolve_instances` output only: a period of 5001 never
    reaches `build_kernel` (security review: the single construction site validates first)."""
    built: list[str] = []
    real = EmaKernel.__init__

    def spy(self: EmaKernel, *args: Any, **kw: Any) -> None:
        built.append("ema")
        real(self, *args, **kw)

    monkeypatch.setattr(EmaKernel, "__init__", spy)
    _, engine, _hold = await _engine()
    with pytest.raises(InstanceRefusedError):
        admit(engine, [{"indicator": "ema", "params": {"n": 5001}}])
    assert built == []


# -- reads (IR-45, SR-E13-12) ---------------------------------------------------------------------


async def test_atr14_with_10_bars_is_none_never_zero_and_its_reason_is_warmup() -> None:
    """Scenario 4: every value is None (null on the wire), never 0; `nullable_when` says why."""
    store, engine, _hold = await _engine()
    (r,) = admit(engine, ATR14)
    for k in range(10):
        await close(store, engine, wave(k))
    batch = engine.snapshot(SYM, r.key, 500)
    assert batch is not None and [p.values for p in batch.points] == [(None,)] * 10
    assert engine.read(SYM, r.key) == Unavailable("warmup")
    assert "None until n bars exist" in AtrKernel.nullable_when
    for k in range(10, 14):
        await close(store, engine, wave(k))
    got = engine.read(SYM, r.key)
    assert isinstance(got, Available) and got.index == 13 and got.value > 0


async def test_read_reasons_missing_parity_stale_and_nan() -> None:
    flagged: set[str] = set()
    store, engine, _hold = await _engine(parity_flagged=lambda _s, key: key in flagged)
    rsi, adx = admit(engine, [{"indicator": "rsi", "params": {"n": 2}}, {"indicator": "adx"}])
    assert engine.read(SYM, "0" * 64) == Unavailable("missing")
    for k in range(4):
        await close(store, engine, bar(k, 100.0))  # flat: no gain, no loss, no range
    assert engine.read(SYM, rsi.key) == Unavailable("nan")  # a zero divisor after the warmup
    assert engine.read(SYM, adx.key, "plus_di") == Unavailable("warmup")
    assert engine.read(SYM, adx.key, "no_such_output") == Unavailable("missing")
    flagged.add(rsi.key)
    assert engine.read(SYM, rsi.key) == Unavailable("parity_flagged")
    flagged.clear()
    # The series moved on 3 closes past the instance's last point (white box: no live path
    # leaves a ready instance behind, as it folds each close before the next emission).
    engine._newest[(SYM, M1.spec_hash)] = (0, 3 + 3)
    assert engine.read(SYM, rsi.key) == Unavailable("stale")
    engine._newest[(SYM, M1.spec_hash)] = (1, 3)
    assert engine.read(SYM, rsi.key) == Unavailable("stale")  # another generation


# -- leases, grace, errors and lifecycle ----------------------------------------------------------


async def test_a_released_instance_keeps_its_grace_then_goes() -> None:
    now = _Now()
    store, engine, _hold = await _engine(now_us=now)
    (r,) = admit(engine, EMA3)
    for k in range(5):
        await close(store, engine, wave(k))
    kept = engine.snapshot(SYM, r.key, 500)
    engine.release(SYM, [r.key], "c1")
    now.us = 29_999_999
    admit(engine, EMA3, consumer="c2")  # back within the grace: the same instance, its values
    assert engine.snapshot(SYM, r.key, 500) == kept
    engine.release(SYM, [r.key], "c2")  # its grace ends at 29_999_999 + 30 s
    now.us = 29_999_999 + 30_000_000 - 1
    engine.release(SYM, [], "nobody")  # a sweep
    assert engine.instances(SYM, M1.spec_hash) == 1
    now.us += 1
    engine.release(SYM, [], "nobody")
    assert engine.instances(SYM, M1.spec_hash) == 0 and engine.snapshot(SYM, r.key, 1) is None


async def test_a_replacing_admission_swaps_the_consumers_instances() -> None:
    store, engine, _hold = await _engine()
    (old,) = admit(engine, EMA3)
    for k in range(5):
        await close(store, engine, wave(k))
    new = resolve_instances([{"indicator": "sma", "params": {"n": 2}}], M1)
    engine.admit(SYM, M1, new, "c1", "u1", history=500, replacing=(old.key,))
    assert engine._leases.holders((SYM, old.key)) == 0  # in its grace, no lease left
    batch = engine.snapshot(SYM, new[0].key, 500)
    assert batch is not None and len(batch.points) == 5  # primed from the store's 5 bars


async def test_an_update_that_raises_is_contained_counted_and_re_primes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, engine, _hold = await _engine()
    listener = Listener()
    engine.listen(listener)
    atr, ema = admit(engine, [*ATR14, *EMA3])
    for k in range(3):
        await close(store, engine, wave(k))
    failures = counter(bar_emit_sink_errors_total.labels(reason="indicators"))
    real = AtrKernel.update

    def boom(self: AtrKernel, b: BarInput) -> Outputs:
        if b.t == wave(3).open_time:
            raise ZeroDivisionError
        return real(self, b)

    monkeypatch.setattr(AtrKernel, "update", boom)
    with structlog.testing.capture_logs() as logs:
        await close(store, engine, wave(3))
    # The update, then the series' re-prime, which folds bar 3 again: each counted and logged.
    assert counter(bar_emit_sink_errors_total.labels(reason="indicators")) - failures == 2
    events = [(e["event"], e["symbol"], e["spec_hash"], e["index"]) for e in logs]
    assert events == [
        ("indicator_update_failed", SYM, atr.key, 3),
        ("indicator_prime_failed", SYM, atr.key, 3),
    ]
    assert listener.events[-1] == ("resnapshot", "history_repair")
    monkeypatch.setattr(AtrKernel, "update", real)
    await close(store, engine, wave(4))  # the series goes on; the failed instance restarts
    ema_batch, atr_batch = engine.snapshot(SYM, ema.key, 500), engine.snapshot(SYM, atr.key, 500)
    assert ema_batch is not None and [p.index for p in ema_batch.points] == [0, 1, 2, 3, 4]
    assert atr_batch is not None and [p.index for p in atr_batch.points] == [4]


async def test_the_listener_is_set_once() -> None:
    _, engine, _hold = await _engine()
    engine.listen(Listener())
    with pytest.raises(RuntimeError):
        engine.listen(Listener())


async def test_a_series_no_instance_reads_costs_nothing_and_forming_bars_are_ignored() -> None:
    store, engine, _hold = await _engine()
    listener = Listener()
    engine.listen(listener)
    await close(store, engine, wave(0))  # nobody reads M1 yet
    (r,) = admit(engine, EMA3)
    other = BarSpec(kind="time", interval_ms=300_000)
    await close(store, engine, wave(1, spec=other), spec=other)
    assert listener.events == [] and engine.version(SYM, other.spec_hash) == 0
    batch = engine.snapshot(SYM, r.key, 500)
    assert batch is not None and [p.index for p in batch.points] == [0]  # from the store


async def test_a_non_finite_value_reads_as_nan(monkeypatch: pytest.MonkeyPatch) -> None:
    store, engine, _hold = await _engine()
    (r,) = admit(engine, EMA3)
    monkeypatch.setattr(EmaKernel, "update", lambda self, b: (float("inf"),))
    await close(store, engine, wave(0))
    assert engine.read(SYM, r.key) == Unavailable("nan")


def test_resolve_refuses_a_parameter_no_identity_can_hold() -> None:
    """A catalogue definition whose enum value is no lowercase token passes `validate_params`
    but cannot enter a `spec_hash` (24 §7.4): refused, not raised."""
    from candleviewer.orderflow.indicators.catalogue import (
        SERVER_DEFINITIONS,
        IndicatorCatalogue,
        ParamSpec,
    )

    vwap = SERVER_DEFINITIONS["vwap"]
    odd = ParamSpec("anchor", "Reset anchor", "string", "Session", enum=("Session",))
    catalogue = IndicatorCatalogue([dataclasses.replace(vwap, params=(odd,))])
    with pytest.raises(InstanceRefusedError, match="a parameter cannot be read"):
        resolve_instances([{"indicator": "vwap"}], M1, catalogue)


async def test_releasing_a_lease_not_held_is_logged_and_never_raises() -> None:
    """A WS subscription's `_drop` releases its other holds after this one (#2735's rule)."""
    _, engine, _hold = await _engine()
    (r,) = admit(engine, EMA3)
    with structlog.testing.capture_logs() as logs:
        engine.release(SYM, [r.key, "f" * 64], "c1")
        engine.release(SYM, [r.key], "c1")  # released already
    assert [e["event"] for e in logs] == ["indicator_lease_not_held"] * 2
    assert engine._leases.holders((SYM, r.key)) == 0
