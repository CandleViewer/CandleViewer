"""Performance budget of the trade-group preview (E28-T05 S3d, #909 AC 10; SCR-061): a BTCUSDT
limit buy previewed across five demo accounts with warm caches answers within 300 ms at p95 over
200 runs. The route runs over S3c's world of fakes, but each leg's figures are peeked as the
composed OMS peeks them: `PreviewFigures`, each account resolved through the account binding (the
per-leg `AccountRef` reads of S3c's R1S-03), on a real `OrderLane` whose kept readings are warm.

`perf`-marked, so the unit lane deselects it and the `py-perf` job runs it without coverage, as it
runs `test_submit_perf.py`: GC is off around the timed rounds, each round times `RUNS` previews
after a warm-up, and the fastest round's p95 is the measure. It also reports, and does not assert,
the order lane's round trip at p95 at rest and under a storm of concurrent previews (R1S-03), as
the test's `lane_p95_ms_*` properties."""

from __future__ import annotations

import asyncio
import gc
import time
from typing import Any, cast
from uuid import UUID

import httpx
import pytest

from candleviewer.api.trade_group_preview import PREVIEW_PATH
from candleviewer.domain.primitives import AccountId
from candleviewer.oms.ports import FiguresReading
from candleviewer.oms_lane import OrderLane
from candleviewer.oms_wiring import PreviewFigures, TradingAccountsBinding
from candleviewer.storage.repositories.trading_accounts import (
    InMemoryTradingAccountReads,
    TradingAccountRow,
)
from tests.unit.api import test_trade_group_preview_route as rig
from tests.unit.oms.submit_rig import figures as known

pytestmark = pytest.mark.perf

ROUNDS = 3
RUNS = 200
#: Previews in flight at once in the storm: the per-user bucket's burst at its default rate.
STORM = 20
#: SCR-061's bound on one preview of five accounts with warm caches (p95).
BUDGET_NS = 300_000_000
E, F = AccountId(UUID(int=6)), AccountId(UUID(int=8))
FIVE = (rig.A, rig.B, rig.C, E, F)
_OWNER = {"Authorization": "Bearer owner"}


class Kept:
    """The order path's kept readings (`OrderFigures.peek`), warm for every account."""

    def peek(self, account: Any, symbols: Any, *, fallback_sl_offset_pct: Any) -> FiguresReading:
        return FiguresReading(known(), {})


class LaneWorld(rig.World):
    """S3c's world whose figures are `PreviewFigures` on `lane`, as `OnLanePreview` hops them."""

    def __init__(self, lane: OrderLane) -> None:
        super().__init__(rate=100)
        rows = (TradingAccountRow(a, "demo", "1001", False, UUID(int=99)) for a in FIVE)
        binding = TradingAccountsBinding(InMemoryTradingAccountReads(*rows), environment="demo")
        self.lane, self.on_lane = lane, PreviewFigures(binding, cast(Any, Kept()))

    async def peeked(self, symbol: str, fallbacks: Any) -> dict[UUID, Any]:
        return await self.lane.call(self.on_lane.peeked(symbol, fallbacks))


async def _round(world: LaneWorld, client: httpx.AsyncClient) -> list[int]:
    samples: list[int] = []
    for _ in range(RUNS):
        world.clock += 1.0  # the bucket refills: the budget is the preview's, not the rate's
        started = time.perf_counter_ns()
        got = await client.post(PREVIEW_PATH, json=rig.body(*FIVE), headers=_OWNER)
        samples.append(time.perf_counter_ns() - started)
        assert got.status_code == 200
    return samples


async def _nothing() -> None:
    return None


async def _trips(lane: OrderLane, until: asyncio.Event | None, count: int = RUNS) -> list[int]:
    """The lane's round trips, `count` of them, or until `until` is set."""
    trips: list[int] = []
    while (until is None and len(trips) < count) or (until is not None and not until.is_set()):
        started = time.perf_counter_ns()
        await lane.call(_nothing())
        trips.append(time.perf_counter_ns() - started)
    return trips


async def _storm(world: LaneWorld, client: httpx.AsyncClient) -> list[int]:
    """The lane's round trips while `RUNS` previews arrive `STORM` at a time."""
    over = asyncio.Event()
    probe = asyncio.ensure_future(_trips(world.lane, over))
    try:
        for _ in range(RUNS // STORM):
            world.clock += 1.0
            sent = [client.post(PREVIEW_PATH, json=rig.body(*FIVE), headers=_OWNER)
                    for _ in range(STORM)]  # fmt: skip
            assert {got.status_code for got in await asyncio.gather(*sent)} == {200}
    finally:
        over.set()
        trips = await probe
    return trips


def _p95(samples: list[int]) -> int:
    ordered = sorted(samples)
    return ordered[int(0.95 * (len(ordered) - 1))]


async def test_a_five_account_preview_fits_300_ms_at_p95(
    monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    for account, label in ((E, "E28-E"), (F, "E28-F")):
        monkeypatch.setitem(rig.LABELS, account, label)
    lane = OrderLane("preview-perf-lane")
    await lane.start()
    world, best = LaneWorld(lane), 0
    app = world.client.app
    gc.collect()
    gc.disable()  # a collection inside one timed preview would skew the sample
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://cv") as client:
            await _round(world, client)  # warm-up: imports, compiled schemas, the profile reads
            for _ in range(ROUNDS):
                p95 = _p95(await _round(world, client))
                best = p95 if best == 0 else min(best, p95)
            rest, storm = _p95(await _trips(lane, None)), _p95(await _storm(world, client))
    finally:
        gc.enable()
        await lane.stop()
    record_property("preview_p95_ms", best / 1e6)
    record_property("lane_p95_ms_at_rest", rest / 1e6)  # R1S-03: the lane's own round trip
    record_property("lane_p95_ms_in_storm", storm / 1e6)
    print(f"preview p95 {best / 1e6:.2f} ms; lane p95 {rest / 1e6:.3f} ms, {storm / 1e6:.3f} ms")
    assert best <= BUDGET_NS, f"p95 {best / 1e6:.2f} ms > {BUDGET_NS / 1e6:.0f} ms"
