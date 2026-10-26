"""#913 S4-S-d (24 Sec.9.3.6, 29 CV-C13): `ServedTierRequests`, the lane's fire-and-forget ask for
a symbol's missing tiers. Each request lands on the serving loop by `call_soon_threadsafe`, is
never awaited, waits at most `TIER_REQUESTS_PENDING_MAX` symbols deep, and a full or stopped one
is dropped and counted; the composition binds it, or the no-op where no catalogue is composed.
Each wait is a bound on the test, never a time it expects."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from structlog.testing import capture_logs

from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.ports import NO_TIER_REQUESTS
from candleviewer.oms_lane import NOTICES_FAILED, Serving
from candleviewer.oms_wiring import (
    TIER_REQUESTS_DROPPED,
    TIER_REQUESTS_PENDING_MAX,
    ServedTierRequests,
)
from tests.unit.ingestion.test_instruments_risk_limits import _catalogue, _Clock, _Fetch, _Repo
from tests.unit.oms.test_oms_runtime import World, started


class Catalogue:
    """The catalogue's side: each request by its symbol and thread, answered `drop`."""

    def __init__(self, drop: Any = None) -> None:
        self.calls: list[tuple[str, threading.Thread]] = []
        self.drop, self.landed = drop, threading.Event()

    def snapshot(self) -> None:
        return None

    def request_tiers(self, symbol: str) -> Any:
        self.calls.append((symbol, threading.current_thread()))
        self.landed.set()
        if self.drop == "raise":
            raise RuntimeError("catalogue fault")
        return self.drop


def _dropped(metrics: Metrics, reason: str) -> float:
    labels = {"env": "demo", "reason": reason}
    return metrics.registry.get_sample_value(TIER_REQUESTS_DROPPED, labels) or 0.0


def _bridge(
    catalogue: Any, loop: asyncio.AbstractEventLoop, metrics: Metrics
) -> ServedTierRequests:
    return ServedTierRequests(catalogue, Serving(loop, metrics), metrics)


def _lost(metrics: Metrics) -> float:
    labels = {"env": "demo", "reason": "lost"}
    return metrics.registry.get_sample_value(NOTICES_FAILED, labels) or 0.0


async def _turned() -> None:
    for _ in range(8):
        await asyncio.sleep(0)


async def test_a_request_from_another_thread_lands_on_the_serving_loop() -> None:
    catalogue, metrics = Catalogue(), Metrics("demo")
    bridge = _bridge(catalogue, asyncio.get_running_loop(), metrics)
    await asyncio.to_thread(bridge.request_tiers, "BTCUSDT")
    await _turned()
    assert catalogue.calls == [("BTCUSDT", threading.current_thread())]
    assert bridge._pending == set()


async def test_the_caller_never_waits_while_the_fetch_hangs() -> None:
    fetch = _Fetch()
    sched = InstrumentsRefreshScheduler(
        fetch_instruments_info=_catalogue, repository=_Repo(), now_us=_Clock(),
        fetch_risk_limits=fetch, on_demand_timeout_s=60.0,
    )  # fmt: skip
    await sched.refresh_now()
    fetch.hang = True
    bridge = _bridge(sched, asyncio.get_running_loop(), Metrics("demo"))
    async with asyncio.timeout(5):  # a guard only: the call returns with the fetch still hung
        await asyncio.to_thread(bridge.request_tiers, "BTCUSDT")
    await _turned()
    assert fetch.calls == ["BTCUSDT"] and len(sched._tier_kicks) == 1
    await sched.stop()


def test_the_pending_cap_drops_further_requests_and_counts_them() -> None:
    loop, metrics, catalogue = asyncio.new_event_loop(), Metrics("demo"), Catalogue()
    try:  # a loop not running: nothing lands, so every request waits
        bridge = _bridge(catalogue, loop, metrics)
        for n in range(TIER_REQUESTS_PENDING_MAX):
            bridge.request_tiers(f"S{n}USDT")
        bridge.request_tiers("S0USDT")  # already waiting: adds nothing, drops nothing
        assert _dropped(metrics, "full") == 0
        bridge.request_tiers("LATEUSDT")
        assert _dropped(metrics, "full") == 1
        assert len(bridge._pending) == TIER_REQUESTS_PENDING_MAX
    finally:
        loop.close()
    assert catalogue.calls == []


async def test_the_cap_holds_across_threads_and_counts_each_extra() -> None:
    loop, metrics, catalogue = asyncio.new_event_loop(), Metrics("demo"), Catalogue()
    try:  # a loop not running: nothing lands, so every distinct request waits
        bridge = _bridge(catalogue, loop, metrics)
        async with asyncio.timeout(10):  # a guard only
            await asyncio.gather(
                *(
                    asyncio.to_thread(bridge.request_tiers, f"S{n}USDT")
                    for n in range(2 * TIER_REQUESTS_PENDING_MAX)
                )
            )
        assert len(bridge._pending) == TIER_REQUESTS_PENDING_MAX == 100
        assert _dropped(metrics, "full") == 100
    finally:
        loop.close()


def test_a_closed_serving_loop_is_counted_by_the_serving_bridge_and_never_raises() -> None:
    loop, metrics, catalogue = asyncio.new_event_loop(), Metrics("demo"), Catalogue()
    bridge = _bridge(catalogue, loop, metrics)
    loop.close()
    bridge.request_tiers("BTCUSDT")  # never raises into its caller
    assert _lost(metrics) == 1 and _dropped(metrics, "stopped") == 0
    assert catalogue.calls == []


async def test_close_clears_the_symbols_still_waiting() -> None:
    loop, metrics = asyncio.new_event_loop(), Metrics("demo")
    try:
        bridge = _bridge(Catalogue(), loop, metrics)
        bridge.request_tiers("BTCUSDT")
        assert bridge._pending == {"BTCUSDT"}
        await bridge.close()
        assert bridge._pending == set()
    finally:
        loop.close()


async def test_the_catalogues_own_drop_is_counted_and_its_fault_logged() -> None:
    metrics, loop = Metrics("demo"), asyncio.get_running_loop()
    for drop in ("full", "stopped"):
        _bridge(Catalogue(drop), loop, metrics).request_tiers("BTCUSDT")
    with capture_logs() as logs:
        _bridge(Catalogue("raise"), loop, metrics).request_tiers("BTCUSDT")
        await _turned()
    assert (_dropped(metrics, "full"), _dropped(metrics, "stopped")) == (1, 1)
    failed = [e["error"] for e in logs if e["event"] == "oms_tier_request_failed"]
    assert failed == ["RuntimeError"]


async def test_no_catalogue_composed_binds_the_no_op() -> None:
    world = World()  # the ingestion of a process with no exchange feed: no catalogue
    async with started(world.runtime()) as runtime:
        deps = runtime._composed().submission._deps
        assert deps.tier_requests is NO_TIER_REQUESTS
        assert deps.tier_requests.request_tiers("BTCUSDT") is None


async def test_the_composition_hands_the_bridge_to_the_runtime() -> None:
    world, catalogue = World(), Catalogue()
    world.ingestion.instruments = catalogue
    async with started(world.runtime()) as runtime:
        bridge = runtime._composed().submission._deps.tier_requests
        assert isinstance(bridge, ServedTierRequests)
        bridge.request_tiers("ETHUSDT")
        await _turned()
    assert [symbol for symbol, _ in catalogue.calls] == ["ETHUSDT"]
