"""The indicator engine's admission, reads and lifecycle (E13-T02, #426; 23 §6.1; 24 §7.3, §7.4;
E13 threat model SR-E13-01/03/04, IR-24, IR-41, IR-45). Priming, swaps and repairs are in
`test_engine_priming.py`; the memo and amended closes have their own files."""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import structlog

from candleviewer.bars.metrics import bar_emit_sink_errors_total
from candleviewer.bars.models import BarSpec
from candleviewer.bars.series_store import Hold, SeriesStore
from candleviewer.orderflow.errors import (
    InstanceCapError,
    InstanceChurnError,
    InstanceRefusedError,
    RecomputeRefusedError,
)
from candleviewer.orderflow.indicators import engine as engine_module
from candleviewer.orderflow.indicators.engine import (
    Available,
    IndicatorEngine,
    resolve_instances,
)
from candleviewer.orderflow.indicators.kernels import AtrKernel, EmaKernel, build_kernel
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
    holders,
    instances,
    wave,
)

RENKO = BarSpec(kind="renko", range_ticks=10)
_API_ROOT = Path(__file__).resolve().parents[4]


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
    assert instances(engine) == 8  # nothing was held for the refusal
    admit(engine, [{"indicator": "ema", "params": {"n": 10}}], consumer="sys", user=None)


async def test_a_window_past_its_bound_is_refused_before_anything_is_held() -> None:
    _, engine, _hold = await _engine()
    requested = resolve_instances(ATR14, M1)
    refused = counter(CAP_REJECTED["window"])
    with pytest.raises(RecomputeRefusedError) as caught:
        engine.check(SYM, M1, requested, "u1", history=MAX_WINDOW_BARS)
    assert caught.value.cap == "window" and "250000" in str(caught.value)
    assert counter(CAP_REJECTED["window"]) - refused == 1
    assert instances(engine) == 0


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
    assert instances(engine) == 1
    now.us += 1
    engine.release(SYM, [], "nobody")
    assert instances(engine) == 0 and engine.snapshot(SYM, r.key, 1) is None


async def test_a_replacing_admission_swaps_the_consumers_instances() -> None:
    """A WS `ctl` (security review of the WS delivery, IR-31): a replaced instance the consumer
    alone held is forgotten at once, with no grace and nothing charged to its user; one another
    consumer holds runs on for that consumer."""
    store, engine, _hold = await _engine()
    old, shared = admit(engine, [*EMA3, {"indicator": "sma", "params": {"n": 3}}])
    admit(engine, [{"indicator": "sma", "params": {"n": 3}}], consumer="c2", user="u2")
    for k in range(5):
        await close(store, engine, wave(k))
    new = resolve_instances([{"indicator": "sma", "params": {"n": 2}}], M1)
    engine.admit(SYM, M1, new, "c1", "u1", history=500, replacing=(old.key, shared.key))
    assert (SYM, old.key) not in engine._leases._held  # no grace
    assert engine.snapshot(SYM, old.key, 500) is None and instances(engine) == 2
    assert holders(engine._leases, (SYM, shared.key)) == 1  # c2's
    batch = engine.snapshot(SYM, new[0].key, 500)
    assert batch is not None and len(batch.points) == 5  # primed from the store's 5 bars


async def test_retunes_at_the_user_cap_leave_nothing_in_a_grace() -> None:
    """IR-31 (security review of the WS delivery): a `ctl` that swaps all eight instances of a
    user at the cap leaves none of the old ones running in a grace (8 held and 8 released for
    30 s, before), so the user retunes again at once, as often as the rebuild budget allows."""
    _, engine, _hold = await _engine(now_us=_Now())
    eights = [[{"indicator": "ema", "params": {"n": n}} for n in range(k, k + 8)] for k in (2, 20)]
    held = [r.key for r in admit(engine, eights[0])]
    for turn in range(4):
        new = resolve_instances(eights[(turn + 1) % 2], M1)
        engine.admit(
            SYM, M1, new, "c1", "u1", history=500, replacing=tuple(held), reason="param_change"
        )
        held = [r.key for r in new]
        assert set(engine._leases._held) == {(SYM, k) for k in held}
        assert instances(engine) == 8


async def test_a_retune_on_a_symbol_at_its_cap_is_admitted_and_keeps_it_there() -> None:
    """SR-E13-03 (review of the WS delivery, round 5): the instances a `ctl` alone held and
    replaces are forgotten once the new ones are held, so they do not count toward the symbol
    cap: on a symbol running 32, eight of them one subscription's, it retunes to eight others,
    and the symbol runs 32 after."""
    _, engine, _hold = await _engine()
    for u in range(3):
        emas = [{"indicator": "ema", "params": {"n": n}} for n in range(2 + 8 * u, 10 + 8 * u)]
        admit(engine, emas, consumer=f"c{u}", user=f"u{u}")
    smas = [[{"indicator": "sma", "params": {"n": n}} for n in range(k, k + 8)] for k in (2, 20)]
    mine = admit(engine, smas[0], consumer="ctl", user="u9")
    new = resolve_instances(smas[1], M1)
    engine.admit(SYM, M1, new, "ctl", "u9", history=500, replacing=tuple(r.key for r in mine))
    assert instances(engine) == 32 and all(holders(engine._leases, (SYM, r.key)) for r in new)


THREE = [{"indicator": name} for name in ("volume", "vwap", "cvd")]


async def test_a_flip_of_three_indicators_every_5_s_is_admitted_for_good() -> None:
    """IR-31 (code review of the WS delivery): a user with volume, vwap and cvd on a chart flips
    it to the next symbol every 5 s on fake time, unsubscribing the old chart first. Each flip
    starts three new instances and leaves three in their grace: at most six releases of three in
    a grace, with three held, is 21, under the churn cap for good. Nothing is refused, and no
    refusal names a cap the user is not at."""
    now = _Now()
    _, engine, _hold = await _engine(now_us=now)
    refused = counter(CAP_REJECTED["user"])
    keys = [r.key for r in resolve_instances(THREE, M1)]
    for flip in range(13):  # a minute of flips
        if flip:
            engine.release(f"FLIP{flip - 1}USDT", keys, "chart")
        engine.admit(
            f"FLIP{flip}USDT", M1, resolve_instances(THREE, M1), "chart", "u1", history=500
        )
        now.us += 5_000_000
    assert counter(CAP_REJECTED["user"]) == refused


async def test_churn_past_its_cap_is_refused_with_its_own_retryable_message() -> None:
    """IR-31: flipping eight instances every 5 s, a user holds 8 and has released 16 by the third
    flip (24). The fourth is refused, saying the released ones still count until they expire (a
    retryable `subscription_limit` on the WS), and counted as `user`; once the first release's
    grace ends, it is admitted."""
    now = _Now()
    _, engine, _hold = await _engine(now_us=now)
    eight = [{"indicator": "ema", "params": {"n": n}} for n in range(2, 10)]
    keys = [r.key for r in resolve_instances(eight, M1)]
    for flip in range(3):
        if flip:
            engine.release(f"S{flip - 1}USDT", keys, "chart")
        engine.admit(f"S{flip}USDT", M1, resolve_instances(eight, M1), "chart", "u1", history=500)
        now.us += 5_000_000
    engine.release("S2USDT", keys, "chart")  # at 15 s: 24 released, none held
    refused = counter(CAP_REJECTED["user"])
    with pytest.raises(InstanceChurnError, match="released in the last 30 s still count"):
        engine.admit("S3USDT", M1, resolve_instances(eight, M1), "chart", "u1", history=500)
    assert counter(CAP_REJECTED["user"]) - refused == 1
    now.us = 35_000_000  # the release at 5 s is out of its grace
    engine.admit("S3USDT", M1, resolve_instances(eight, M1), "chart", "u1", history=500)


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


async def test_a_close_stops_at_an_instance_that_fails_since_the_series_re_primes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review of the WS delivery, round 5: once an instance cannot take a close (here ATR's
    kernel raises on it), the series re-primes, so the instances after it do not fold the close
    first, work the re-prime would discard: EMA's kernel folds bars 0..3 in its re-prime, and
    nothing before it."""
    store, engine, _hold = await _engine()
    admit(engine, [*ATR14, *EMA3])  # ATR first: the series' first instance
    for k in range(3):
        await close(store, engine, wave(k))
    real_atr, real_ema = AtrKernel.update, EmaKernel.update
    folded: list[int] = []

    def boom(self: AtrKernel, b: BarInput) -> Outputs:
        if b.t == wave(3).open_time:
            raise ZeroDivisionError
        return real_atr(self, b)

    def counting(self: EmaKernel, b: BarInput) -> Outputs:
        folded.append(b.t)
        return real_ema(self, b)

    monkeypatch.setattr(AtrKernel, "update", boom)
    monkeypatch.setattr(EmaKernel, "update", counting)
    await close(store, engine, wave(3))
    assert folded == [wave(k).open_time for k in range(4)]


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
    assert holders(engine._leases, (SYM, r.key)) == 0


async def test_an_admission_that_raises_after_its_checks_holds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SR-E13-03 bookkeeping fails closed (security review of the WS delivery): a kernel that
    cannot be built after the leases are taken undoes the admission whole: the instances it
    started and the leases it took, a join's included, with no grace and no cap left held."""
    store, engine, _hold = await _engine()
    (running,) = admit(engine, EMA3, consumer="first")

    def failing(indicator: str, *args: Any, **kw: Any) -> Any:
        if indicator == "rsi":
            raise RuntimeError("kernel")
        return build_kernel(indicator, *args, **kw)

    monkeypatch.setattr(engine_module, "build_kernel", failing)
    # A join of the running instance, a start, and a start whose kernel fails.
    raw: list[dict[str, Any]] = [*EMA3, {"indicator": "sma"}, {"indicator": "rsi"}]
    with pytest.raises(RuntimeError, match="kernel"):
        admit(engine, raw, consumer="second", user="u2")
    assert set(engine._leases._held) == {(SYM, running.key)}  # the first consumer's alone
    assert holders(engine._leases, (SYM, running.key)) == 1 and instances(engine) == 1
    monkeypatch.setattr(engine_module, "build_kernel", build_kernel)
    refused = counter(CAP_REJECTED["user"])
    eight = [{"indicator": "ema", "params": {"n": n}} for n in range(2, 10)]
    admit(engine, eight, consumer="third", user="u2")  # nothing of the failed one counts
    assert counter(CAP_REJECTED["user"]) == refused
    await close(store, engine, wave(0))
    assert engine.read(SYM, running.key) == Unavailable("warmup")  # the join's instance runs on


async def test_an_unheld_instance_stops_folding_within_a_second_of_its_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The release grace bounds work too (review of the WS delivery): with no admission or
    release anywhere, the emit path removes an instance whose grace has ended, at most a second
    after it, so it folds nothing more."""
    now = _Now()
    store, engine, _hold = await _engine(now_us=now)
    (r,) = admit(engine, EMA3)
    engine.release(SYM, [r.key], "c1")
    folds: list[int] = []
    real = EmaKernel.update

    def counting(self: EmaKernel, b: BarInput) -> Outputs:
        folds.append(b.t)
        return real(self, b)

    monkeypatch.setattr(EmaKernel, "update", counting)
    now.us = 30_000_000 - 1  # in its grace: it still folds each close
    await close(store, engine, wave(0))
    assert folds == [wave(0).open_time] and instances(engine) == 1
    now.us = 30_000_000 + 1_000_000  # its grace ended a second ago: the next close removes it
    await close(store, engine, wave(1))
    assert folds == [wave(0).open_time] and instances(engine) == 0


def test_importing_the_indicators_package_loads_no_bars_module() -> None:
    """M15 `rules` imports the catalogue through `candleviewer.orderflow.indicators` and may not
    reach M8 `bars` (import-linter counts indirect imports): a fresh interpreter proves the
    package's `__init__` loads none, the engine being imported from its own module only."""
    probe = (
        "import sys, candleviewer.orderflow.indicators as p; "
        "print(sorted(m for m in sys.modules if m.startswith('candleviewer.bars')), "
        "'candleviewer.orderflow.indicators.engine' in sys.modules)"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(_API_ROOT)
    done = subprocess.run(  # noqa: S603 -- fixed argv: this interpreter and a literal probe
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=_API_ROOT,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[] False"
