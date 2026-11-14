"""E35-T15 PR 2 (#5745): the bar side of the metric producers (`rules_producers_wiring.py`).

Unit tests on fakes: `timeframe_spec`, the `BarFieldProducer` bar sink (pushes, ticks, the
never-yielding `emit`), its lease keeper over a fake builder set, and the `wire_bars` splice.
No sleeps: the keeper's timer never fires, its passes are driven by hand.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer import rules_producers_wiring as wiring
from candleviewer.app import build_app_context
from candleviewer.bars.emit import BarEmission, WriterSink
from candleviewer.bars.errors import BarsError, SpecCapExceeded
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.spec import from_wire
from candleviewer.bars_wiring import wire_bars
from candleviewer.rules.evaluator.snapshot import MetricValue
from candleviewer.rules.ir.models import Rule
from candleviewer.rules.manager import EvaluableRule
from candleviewer.rules_producers_wiring import (
    LEASE_CONSUMER,
    BarFieldProducer,
    timeframe_spec,
)
from candleviewer.settings import Environment, Settings
from tests.rules.test_instance_binding import ref, rule
from tests.rules.test_producers import Rig

M1 = BarSpec(kind="time", interval_ms=60_000)
M5 = BarSpec(kind="time", interval_ms=300_000)
CLOSE_US = 1_700_000_040_000_000
STEP = Decimal("0.001")


async def _never(_s: float) -> None:
    await asyncio.Event().wait()


class Leases:
    """A recording `LeaseHolder`; `refuse` is raised by every registration."""

    def __init__(self, refuse: Exception | None = None) -> None:
        self.refuse = refuse
        self.registered: list[tuple[str, str, str, str | None]] = []
        self.released: list[tuple[str, str, str]] = []

    async def register(
        self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
    ) -> None:
        if self.refuse is not None:
            raise self.refuse
        self.registered.append((spec.spec_hash, symbol, consumer, user))

    def release(self, spec_hash: str, symbol: str, consumer: str) -> None:
        self.released.append((spec_hash, symbol, consumer))


class Mono:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _live_now() -> int:
    """The bars' wall clock 1 s after `CLOSE_US`: a close at `CLOSE_US` is a live one."""
    return CLOSE_US + 1_000_000


def _producer(
    leases: Leases | None = None, step: Decimal | None = STEP, clock: Mono | None = None
) -> BarFieldProducer:
    return BarFieldProducer(
        lambda: leases, lambda _s: step, now_us=_live_now, clock=clock or Mono(), sleep=_never
    )


def _bar_rule(
    metric: str = "delta", tf: str = "1m", symbols: tuple[str, ...] = ("BTCUSDT",), rid: int = 7
) -> Rule:
    base = rule(
        {"metric": metric, "timeframe": tf}, symbols=symbols,
        trigger={"type": "on_bar_close", "timeframe": tf}, rid=rid,
    ).model_dump(mode="json")  # fmt: skip
    base["conditions"]["right"] = {"const": 0}
    return Rule.model_validate(base)


def _bar(
    *, symbol: str = "BTCUSDT", spec: BarSpec = M1, delta: str = "12.5", sell: str = "4",
    synthetic: bool = False, close_us: int = CLOSE_US,
) -> Bar:  # fmt: skip
    return Bar(
        spec_hash=spec.spec_hash, symbol=symbol, index=1,
        open_time=close_us - (spec.interval_ms or 0) * 1000, close_time=close_us,
        open=Decimal(100), high=Decimal(101), low=Decimal(99), close=Decimal(100),
        volume=Decimal(20), buy_volume=Decimal(16), sell_volume=Decimal(sell),
        delta=Decimal(delta), min_delta=Decimal(-3), max_delta=Decimal(14), trade_count=9,
        turnover=Decimal(2000), vwap=Decimal(100), closed=True, partial=False, gap_before=False,
        synthetic=synthetic,
    )  # fmt: skip


def _close(bar: Bar, *, kind: str = "close", amended: bool = False, spec: BarSpec = M1) -> Any:
    return BarEmission(spec, 1, (BarUpdate(kind=kind, bar=bar, amended=amended),))  # type: ignore[arg-type]  # kind is a Literal


def _read(rig: Rig, metric: str, symbol: str = "BTCUSDT", tf: str = "1m") -> MetricValue:
    return rig.source.read(ref(metric, symbol=symbol, timeframe=tf))


# --- timeframe_spec ------------------------------------------------------------------------------


@pytest.mark.parametrize(("tf", "code"), [("1m", "1"), ("4h", "240"), ("1d", "D"), ("15m", "15")])
def test_timeframe_spec_ir_timeframe_hashes_as_the_charts_series(tf: str, code: str) -> None:
    spec = timeframe_spec(tf)
    assert spec is not None and spec.spec_hash == from_wire("time", code).spec_hash


@pytest.mark.parametrize("tf", [None, "", "0m", "01m", "1M", "1w", "2d", "1h30m", "m", "1x"])
def test_timeframe_spec_unmappable_string_is_none(tf: str | None) -> None:
    assert timeframe_spec(tf) is None


@pytest.mark.parametrize("tf", ["30s", "7s", "11s", "7m", "13m", "3h", "90m", "1440s"])
def test_timeframe_spec_interval_outside_the_charts_table_is_never_leasable(tf: str) -> None:
    """Arbitrary rule timeframes would cold-build series under the shared bar caps."""
    assert timeframe_spec(tf) is None


@pytest.mark.parametrize(("tf", "ms"), [("60m", 3_600_000), ("24h", 86_400_000)])
def test_timeframe_spec_another_spelling_of_a_chart_interval_maps(tf: str, ms: int) -> None:
    assert timeframe_spec(tf) == BarSpec(kind="time", interval_ms=ms)


# --- the bar sink --------------------------------------------------------------------------------


async def test_bar_sink_emit_completes_without_yielding() -> None:
    producer = _producer()
    async with Rig([_bar_rule()], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        coro = producer.emit(_close(_bar()))
        with pytest.raises(StopIteration):
            coro.send(None)  # the first step finishes it: no await reached the loop
        assert _read(rig, "delta").value == Decimal("12.5") and len(rig.ticks) == 1


async def test_bar_sink_pushes_every_bar_field_with_the_bar_interval() -> None:
    rules = [_bar_rule(m) for m in ("bar_volume", "min_delta", "max_delta", "buy_sell_ratio")]
    producer = _producer()
    async with Rig(rules, producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.emit(_close(_bar(sell="4")))
        got = {m: _read(rig, m).value for m in ("bar_volume", "min_delta", "max_delta")}
        assert got == {"bar_volume": 20, "min_delta": -3, "max_delta": 14}
        assert _read(rig, "buy_sell_ratio") == MetricValue(Decimal(4), CLOSE_US // 1000, 60_000)
        assert rig.ticks == [("on_bar_close", "BTCUSDT", "1m")]  # one tick per emission


async def test_bar_sink_buy_sell_ratio_floors_sell_volume_at_the_qty_step() -> None:
    producer = _producer(step=Decimal("0.5"))
    async with Rig([_bar_rule("buy_sell_ratio")], producer) as rig:  # type: ignore[arg-type]
        await producer.emit(_close(_bar(sell="0")))
        assert _read(rig, "buy_sell_ratio").value == Decimal(32)


async def test_bar_sink_unlisted_symbol_step_leaves_buy_sell_ratio_warmup() -> None:
    producer = _producer(step=None)
    async with Rig([_bar_rule("buy_sell_ratio")], producer) as rig:  # type: ignore[arg-type]
        await producer.emit(_close(_bar()))
        assert _read(rig, "buy_sell_ratio") == MetricValue(None, 0, 0, "warmup")


async def test_bar_sink_amended_close_pushes_and_submits_no_tick() -> None:
    producer = _producer()
    async with Rig([_bar_rule()], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.emit(_close(_bar(delta="7"), amended=True))
        assert _read(rig, "delta").value == Decimal(7)
        assert rig.ticks == []


@pytest.mark.parametrize(
    ("emission", "why"),
    [
        (_close(_bar(), kind="update"), "not a close"),
        (_close(_bar(synthetic=True)), "a synthetic filler"),
        (_close(_bar(symbol="ETHUSDT")), "an undemanded symbol"),
        (_close(_bar(spec=M5), spec=M5), "an undemanded timeframe"),
    ],
)
async def test_bar_sink_bar_outside_the_demand_pushes_nothing_and_no_tick(
    emission: BarEmission, why: str
) -> None:
    producer = _producer()
    async with Rig([_bar_rule()], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.emit(emission)
        assert _read(rig, "delta").reason == "warmup", why
        assert rig.ticks == [], why


async def test_bar_sink_before_attach_and_after_detach_does_nothing() -> None:
    producer = _producer()
    await producer.emit(_close(_bar()))  # not attached: a no-op
    rig = Rig([_bar_rule()], producer)  # type: ignore[arg-type]  # a MetricProducer
    async with rig:
        pass
    await producer.emit(_close(_bar()))
    assert rig.ticks == [] and _read(rig, "delta").reason == "warmup"


async def test_bar_sink_raising_callback_is_isolated_and_counted() -> None:
    def _boom(_s: str) -> Decimal:
        raise RuntimeError("boom")

    producer = BarFieldProducer(lambda: None, _boom, now_us=_live_now, sleep=_never)
    async with Rig([_bar_rule()], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.emit(_close(_bar()))  # never raises into the emit path
        assert rig.sample("rule_metric_producer_errors_total", producer="bar_fields") == 1
        assert rig.ticks == []


# --- the leases ----------------------------------------------------------------------------------


async def test_bar_leases_follow_the_demand_as_a_system_consumer() -> None:
    leases = Leases()
    producer = _producer(leases)
    async with Rig([_bar_rule(symbols=("BTCUSDT", "ETHUSDT"))], producer) as rig:  # type: ignore[arg-type]
        await producer.sync()
        await producer.sync()  # idempotent: one lease per (symbol, spec)
        assert sorted(leases.registered) == [
            (M1.spec_hash, "BTCUSDT", LEASE_CONSUMER, None),
            (M1.spec_hash, "ETHUSDT", LEASE_CONSUMER, None),
        ]
        rig.items = [EvaluableRule(_bar_rule(), "simulate", None, "v2", "h")]
        await rig.bridge.refresh()
        await producer.sync()
        assert leases.released == [(M1.spec_hash, "ETHUSDT", LEASE_CONSUMER)]
    assert sorted(leases.released) == [
        (M1.spec_hash, "BTCUSDT", LEASE_CONSUMER), (M1.spec_hash, "ETHUSDT", LEASE_CONSUMER),
    ]  # fmt: skip


async def test_bar_leases_refused_lease_stays_warmup_and_is_counted() -> None:
    leases = Leases(refuse=SpecCapExceeded("per-symbol", 8, 8))
    producer = _producer(leases)
    async with Rig([_bar_rule()], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.sync()
        await producer.sync()  # not retried until the demand changes
        assert rig.refused("lease") == 1
        assert producer.held == frozenset()
        assert _read(rig, "delta") == MetricValue(None, 0, 0, "warmup")


async def test_bar_leases_many_odd_timeframes_are_refused_and_counted() -> None:
    leases = Leases()
    producer = _producer(leases)
    rules = [_bar_rule(tf=tf) for tf in ("7s", "11s", "13s", "7m", "1m")]
    async with Rig(rules, producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.sync()
        await producer.sync()  # counted once per demand
        assert leases.registered == [(M1.spec_hash, "BTCUSDT", LEASE_CONSUMER, None)]
        assert rig.refused("lease") == 4


async def test_bar_leases_past_the_rules_budget_are_refused_and_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wiring, "MAX_RULE_LEASES", 2)
    leases = Leases()
    producer = _producer(leases)
    rules = [_bar_rule(symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"))]
    async with Rig(rules, producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.sync()
        await producer.sync()
        assert len(leases.registered) == 2 and len(producer.held) == 2
        assert rig.refused("lease") == 1


async def test_bar_sink_nothing_pushed_submits_no_tick() -> None:
    producer = _producer(step=None)  # buy_sell_ratio alone, never computable: nothing lands
    async with Rig([_bar_rule("buy_sell_ratio")], producer) as rig:  # type: ignore[arg-type]
        await producer.emit(_close(_bar()))
        assert rig.ticks == []


async def test_bar_leases_rule_without_symbols_or_timeframe_leases_nothing() -> None:
    leases = Leases()
    producer = _producer(leases)
    rules = [_bar_rule(symbols=()), _bar_rule(tf="1w")]
    async with Rig(rules, producer):  # type: ignore[arg-type]  # a MetricProducer
        await producer.sync()
    assert leases.registered == [] and leases.released == []


# --- wire_bars -----------------------------------------------------------------------------------


def test_wire_bars_extra_sinks_run_after_the_engine_and_before_the_writer(tmp_path: Path) -> None:
    ctx = build_app_context(
        Settings(
            environment=Environment.DEMO,
            git_sha="deadbeef",
            version="9.9.9",
            bars_state_root=str(tmp_path / "bars"),
            metrics_enabled=False,
        )
    )
    producer = _producer()
    runtime = wire_bars(ctx, now_us=lambda: CLOSE_US, extra_sinks=(producer,))
    sinks = runtime.builder_set._router._sinks
    assert sinks[-2] is producer and isinstance(sinks[-1], WriterSink)


async def test_bar_leases_keeper_survives_a_failing_pass() -> None:
    passes: list[int] = []
    gate = asyncio.Event()

    async def tick(_s: float) -> None:
        if len(passes) >= 2:
            gate.set()
            await asyncio.Event().wait()
        passes.append(1)

    async def broken() -> None:
        raise RuntimeError("store down")

    producer = BarFieldProducer(lambda: Leases(), lambda _s: STEP, sleep=tick)
    producer.sync = broken  # type: ignore[method-assign]  # every pass raises
    async with Rig([_bar_rule()], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await gate.wait()
        assert rig.sample("rule_metric_producer_errors_total", producer="bar_fields") == 2


async def test_bar_leases_detached_during_a_registration_gives_the_lease_back() -> None:
    producer: BarFieldProducer

    class Detaching(Leases):
        async def register(
            self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
        ) -> None:
            await super().register(spec, symbol, consumer, user)
            producer._sink = None  # the bridge detached while the cold build ran

    leases = Detaching()
    producer = _producer(leases)
    async with Rig([_bar_rule(symbols=("BTCUSDT", "ETHUSDT"))], producer):  # type: ignore[arg-type]
        await producer.sync()
        assert len(leases.registered) == 1 and producer.held == frozenset()
        assert leases.released == [(M1.spec_hash, leases.registered[0][1], LEASE_CONSUMER)]


async def test_bar_leases_without_a_builder_set_do_nothing() -> None:
    producer = _producer(None)
    async with Rig([_bar_rule()], producer):  # type: ignore[arg-type]  # a MetricProducer
        await producer.sync()
        assert producer.held == frozenset()


# --- slice review fold (#5745 PR 2c) -----------------------------------------------------------


async def test_bar_sink_close_older_than_one_interval_pushes_and_ticks_nothing() -> None:
    producer = _producer()
    async with Rig([_bar_rule()], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.emit(_close(_bar(close_us=CLOSE_US - 60_000_000)))  # one interval old
        assert rig.ticks == [] and _read(rig, "delta").reason == "warmup"


async def test_bar_sink_catch_up_burst_then_the_live_close_ticks_exactly_once() -> None:
    """A restored series replays its closes since the watermark through the emit path
    (`bars/builder_set._catch_up`): none is pushed or ticked; the live close ticks once."""
    producer = _producer()
    replayed = tuple(
        BarUpdate(kind="close", bar=_bar(delta=str(k), close_us=CLOSE_US - k * 60_000_000))
        for k in range(30, 0, -1)
    )  # fmt: skip
    async with Rig([_bar_rule()], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.emit(BarEmission(M1, 1, replayed))
        assert rig.ticks == [] and _read(rig, "delta").reason == "warmup"
        await producer.emit(_close(_bar(delta="12.5")))
        assert rig.ticks == [("on_bar_close", "BTCUSDT", "1m")]
        assert _read(rig, "delta").value == Decimal("12.5")


async def test_bar_leases_are_shared_round_robin_so_one_rule_never_takes_the_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wiring, "MAX_RULE_LEASES", 2)
    monkeypatch.setattr(wiring, "MAX_RULE_LEASES_PER_RULE", 2)
    leases = Leases()
    producer = _producer(leases)
    flood = _bar_rule(symbols=tuple(f"S{i}USDT" for i in range(6)))  # rule 7: six series
    other = Rule.model_validate(
        _bar_rule(symbols=("BTCUSDT",)).model_dump(mode="json") | {"rule_id": str(uuid.UUID(int=8))}
    )
    async with Rig([flood, other], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.sync()
        assert sorted(s for _, s, _, _ in leases.registered) == ["BTCUSDT", "S0USDT"]  # 1 each
        assert rig.refused("lease") == 5
        monkeypatch.setattr(wiring, "MAX_RULE_LEASES", 64)
        await producer.sync()
        assert len(producer.held) == 3  # the flood stops at its share of 2


async def test_bar_leases_refused_lease_is_retried_after_the_backoff() -> None:
    leases, clock = Leases(refuse=SpecCapExceeded("per-symbol", 32, 32)), Mono()
    producer = _producer(leases, clock=clock)
    async with Rig([_bar_rule()], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.sync()
        leases.refuse = None  # the chart users released their series
        clock.t += wiring.LEASE_RETRY_S - 1
        await producer.sync()
        assert producer.held == frozenset()  # not hot
        clock.t += 1
        await producer.sync()  # same demand: retried after the backoff
        assert producer.held == {("BTCUSDT", M1.spec_hash)} and rig.refused("lease") == 1


async def test_bar_leases_a_release_that_raises_never_strands_the_others() -> None:
    class Unknown(Leases):
        def release(self, spec_hash: str, symbol: str, consumer: str) -> None:
            if symbol == "BTCUSDT":
                raise BarsError("lease not held")
            super().release(spec_hash, symbol, consumer)

    leases = Unknown()
    producer = _producer(leases)
    async with Rig([_bar_rule(symbols=("BTCUSDT", "ETHUSDT"))], producer):  # type: ignore[arg-type]
        await producer.sync()
        assert len(producer.held) == 2
    assert leases.released == [(M1.spec_hash, "ETHUSDT", LEASE_CONSUMER)]


async def test_bar_leases_one_slow_registration_never_holds_back_the_others() -> None:
    class Slow(Leases):
        def __init__(self) -> None:
            super().__init__()
            self.eth = asyncio.Event()

        async def register(
            self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
        ) -> None:
            if symbol == "BTCUSDT":
                await self.eth.wait()  # a long cold build, until ETHUSDT's lease is in
            await super().register(spec, symbol, consumer, user)
            if symbol == "ETHUSDT":
                self.eth.set()

    leases = Slow()
    producer = _producer(leases)
    async with Rig([_bar_rule(symbols=("BTCUSDT", "ETHUSDT"))], producer):  # type: ignore[arg-type]
        async with asyncio.timeout(5):  # serial registration would wait the 30 s bound
            await producer.sync()
        assert [s for _, s, _, _ in leases.registered] == ["ETHUSDT", "BTCUSDT"]


# --- final fold (#5745 PR 2c) ------------------------------------------------------------------

H1 = BarSpec(kind="time", interval_ms=3_600_000)
D1 = BarSpec(kind="time", interval_ms=86_400_000)


@pytest.mark.parametrize(("spec", "tf"), [(H1, "1h"), (D1, "1d")])
async def test_bar_sink_long_interval_close_five_minutes_late_pushes_and_ticks_nothing(
    spec: BarSpec, tf: str
) -> None:
    """A catch-up replay of a 60 or D close minutes later is history, not a live close."""
    producer = _producer()
    late = _live_now() - 300_000_000  # 5 min before the bars' clock, within one interval
    async with Rig([_bar_rule(tf=tf)], producer) as rig:  # type: ignore[arg-type]
        await producer.emit(_close(_bar(spec=spec, close_us=late), spec=spec))
        assert rig.ticks == [] and _read(rig, "delta", tf=tf).reason == "warmup"


async def test_bar_sink_one_minute_close_59_s_late_still_ticks() -> None:
    producer = _producer()
    late = _live_now() - 59_000_000
    async with Rig([_bar_rule()], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.emit(_close(_bar(close_us=late)))
        assert rig.ticks == [("on_bar_close", "BTCUSDT", "1m")]


async def test_bar_sink_repeated_close_never_ticks_twice() -> None:
    """A close emitted again (a restored series' catch-up inside the grace) never ticks twice,
    and an older close never writes over the newer one's values."""
    producer = _producer()
    async with Rig([_bar_rule()], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.emit(_close(_bar(delta="12.5")))
        await producer.emit(_close(_bar(delta="12.5")))
        assert rig.ticks == [("on_bar_close", "BTCUSDT", "1m")]
        await producer.emit(_close(_bar(delta="3", close_us=CLOSE_US - 500_000)))
        assert rig.ticks == [("on_bar_close", "BTCUSDT", "1m")]
        assert _read(rig, "delta").value == Decimal("12.5")


async def test_bar_sink_ticked_closes_are_bounded_by_the_demand_and_the_series_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wiring, "MAX_TICKED_SERIES", 2)
    producer = _producer()
    rules = [_bar_rule(symbols=("AUSDT", "BUSDT", "CUSDT"))]
    async with Rig(rules, producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        for symbol in ("AUSDT", "BUSDT", "CUSDT"):
            await producer.emit(_close(_bar(symbol=symbol)))
        assert len(rig.ticks) == 3 and len(producer._ticked) == 2  # AUSDT, least recent, went
        rig.items = []
        await rig.bridge.refresh()
        await producer.emit(_close(_bar(symbol="CUSDT")))
        assert producer._ticked == {}  # its timeframe is no longer demanded


async def test_bar_leases_registrations_in_flight_are_bounded() -> None:
    class Gated(Leases):
        def __init__(self) -> None:
            super().__init__()
            self.open, self.full, self.in_flight, self.peak = asyncio.Event(), asyncio.Event(), 0, 0

        async def register(
            self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
        ) -> None:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            if self.in_flight == wiring.LEASE_CONCURRENCY:
                self.full.set()
            try:
                await self.open.wait()
            finally:
                self.in_flight -= 1
            await super().register(spec, symbol, consumer, user)

    leases = Gated()
    producer = _producer(leases)
    symbols = tuple(f"S{i}USDT" for i in range(wiring.LEASE_CONCURRENCY * 2))
    async with Rig([_bar_rule(symbols=symbols)], producer):  # type: ignore[arg-type]
        async with asyncio.timeout(5):
            passing = asyncio.create_task(producer.sync())
            await leases.full.wait()
            for _ in range(5):
                await asyncio.sleep(0)  # room for a ninth, were it allowed in
            assert leases.peak == wiring.LEASE_CONCURRENCY
            leases.open.set()
            await passing
        assert len(producer.held) == len(symbols)


# --- orchestrator review fold (#5745 PR 2c) ----------------------------------------------------


class _Building(Leases):
    """A registration that runs until `done` is set, then raises `fail` or holds; counts the
    starts and the cancellations."""

    def __init__(self, fail: Exception | None = None) -> None:
        super().__init__()
        self.done, self.fail, self.starts, self.cancelled = asyncio.Event(), fail, 0, 0

    async def register(
        self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
    ) -> None:
        self.starts += 1
        try:
            await self.done.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        if self.fail is not None:
            raise self.fail
        await super().register(spec, symbol, consumer, user)


async def _settled(producer: BarFieldProducer) -> None:
    """Wait for the registrations in flight; each one's outcome is taken as it ends."""
    if pending := list(producer._pending.values()):
        async with asyncio.timeout(5):
            await asyncio.wait(pending)
    assert producer._pending == {}


async def test_bar_leases_timed_out_registration_runs_on_and_is_never_restarted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wiring, "LEASE_TIMEOUT_S", 0.0)  # every registration outruns the bound
    leases, clock = _Building(), Mono()
    producer = _producer(leases, clock=clock)
    async with Rig([_bar_rule()], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        for _ in range(4):
            await producer.sync()
            clock.t += wiring.LEASE_BACKOFF_MAX_S  # past every retry period and backoff
        assert (leases.starts, leases.cancelled) == (1, 0)
        assert rig.refused("lease_timeout") == 1 and rig.refused("lease") == 0
        leases.done.set()
        await _settled(producer)
        assert producer.held == {("BTCUSDT", M1.spec_hash)}  # adopted when it ended
    assert leases.cancelled == 0 and len(leases.released) == 1


async def test_bar_leases_timed_out_then_failed_key_backs_off_exponentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wiring, "LEASE_TIMEOUT_S", 0.0)
    leases, clock = _Building(fail=SpecCapExceeded("per-symbol", 32, 32)), Mono()
    producer = _producer(leases, clock=clock)
    key = ("BTCUSDT", M1.spec_hash)
    async with Rig([_bar_rule()], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.sync()
        leases.done.set()
        await _settled(producer)  # it failed after its bound: counted once, as the timeout
        assert rig.refused("lease_timeout") == 1 and rig.refused("lease") == 0
        assert producer.retry_s(key) == 2 * wiring.LEASE_RETRY_S
        clock.t += wiring.LEASE_RETRY_S
        await producer.sync()
        assert leases.starts == 1  # one retry period is not enough after a timeout
        clock.t += wiring.LEASE_RETRY_S
        await producer.sync()
        assert leases.starts == 2
        await _settled(producer)
        for _ in range(8):
            producer._timeouts[key] = producer._timeouts.get(key, 0) + 1
        assert producer.retry_s(key) == wiring.LEASE_BACKOFF_MAX_S


async def test_bar_leases_refusal_is_logged_once_per_key_until_held_or_dropped() -> None:
    leases, clock = Leases(refuse=SpecCapExceeded("per-symbol", 32, 32)), Mono()
    producer = _producer(leases, clock=clock)
    async with Rig([_bar_rule()], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        with capture_logs() as logs:
            for _ in range(4):
                await producer.sync()
                clock.t += wiring.LEASE_RETRY_S
            rig.items = [
                EvaluableRule(_bar_rule(), "simulate", None, "v1", "h"),
                EvaluableRule(_bar_rule("bar_volume", rid=9), "simulate", None, "v2", "h"),
            ]
            await rig.bridge.refresh()  # a demand change retries at once, logs nothing new
            await producer.sync()
        assert [e["event"] for e in logs] == ["rules.bar_lease_refused"]
        assert rig.refused("lease") == 5
        leases.refuse = None
        clock.t += wiring.LEASE_RETRY_S
        await producer.sync()
        assert producer.held and producer._logged == set()  # held: the next refusal logs again
        leases.refuse = SpecCapExceeded("per-symbol", 32, 32)
        rig.items = []
        await rig.bridge.refresh()
        await producer.sync()  # dropped
        rig.items = [EvaluableRule(_bar_rule(), "simulate", None, "v3", "h")]
        await rig.bridge.refresh()
        with capture_logs() as logs:
            await producer.sync()
        assert [e["event"] for e in logs] == ["rules.bar_lease_refused"]


async def test_bar_leases_detach_stops_a_registration_still_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wiring, "LEASE_TIMEOUT_S", 0.0)
    leases = _Building()
    producer = _producer(leases)
    async with Rig([_bar_rule()], producer):  # type: ignore[arg-type]  # a MetricProducer
        await producer.sync()
        assert leases.starts == 1 and producer._pending
    assert leases.cancelled == 1 and producer._pending == {} and producer.held == frozenset()


async def test_bar_sink_zero_qty_step_leaves_buy_sell_ratio_warmup_and_pushes_the_rest() -> None:
    producer = _producer(step=Decimal(0))
    rules = [_bar_rule("buy_sell_ratio"), _bar_rule("delta", symbols=("BTCUSDT",))]
    async with Rig(rules, producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.emit(_close(_bar(sell="0")))  # 0 / max(0, 0) would raise in the guard
        assert _read(rig, "buy_sell_ratio").reason == "warmup"
        assert _read(rig, "delta").value == Decimal("12.5")
        assert rig.sample("rule_metric_producer_errors_total", producer="bar_fields") == 0


async def test_bar_sink_close_exactly_one_interval_late_is_history() -> None:
    producer = _producer()
    late = _live_now() - 60_000_000  # the 1 m grace exactly: the boundary is history
    async with Rig([_bar_rule()], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        await producer.emit(_close(_bar(close_us=late)))
        assert rig.ticks == [] and _read(rig, "delta").reason == "warmup"


async def test_bar_leases_queued_registration_is_not_timed_out_before_it_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound runs from when a registration takes its slot (`LEASE_CONCURRENCY` at once):
    with eight slow builds running, a ninth still queued is not counted ``lease_timeout``."""

    class PerSymbol(Leases):
        def __init__(self) -> None:
            super().__init__()
            self.gates: dict[str, asyncio.Event] = {}
            self.starts: list[str] = []
            self.started = asyncio.Event()

        async def register(
            self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
        ) -> None:
            self.starts.append(symbol)
            self.started.set()
            await self.gates.setdefault(symbol, asyncio.Event()).wait()
            await super().register(spec, symbol, consumer, user)

    monkeypatch.setattr(wiring, "LEASE_TIMEOUT_S", 0.0)  # every build that runs outruns it
    leases = PerSymbol()
    producer = _producer(leases)
    symbols = tuple(f"S{i}USDT" for i in range(wiring.LEASE_CONCURRENCY + 1))
    async with Rig([_bar_rule(symbols=symbols)], producer) as rig:  # type: ignore[arg-type]
        await producer.sync()
        for _ in range(5):
            await asyncio.sleep(0)  # the running builds' bounds expire
        assert len(leases.starts) == wiring.LEASE_CONCURRENCY
        (queued,) = set(symbols) - set(leases.starts)
        assert rig.refused("lease_timeout") == wiring.LEASE_CONCURRENCY
        assert (queued, M1.spec_hash) not in producer._late
        leases.started.clear()
        leases.gates[leases.starts[0]].set()  # a slot frees: the ninth starts, its bound with it
        async with asyncio.timeout(5):
            await leases.started.wait()
        assert leases.starts[-1] == queued
        for _ in range(5):
            await asyncio.sleep(0)
        assert rig.refused("lease_timeout") == wiring.LEASE_CONCURRENCY + 1
