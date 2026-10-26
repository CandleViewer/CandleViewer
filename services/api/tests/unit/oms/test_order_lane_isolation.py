"""#913 slice 3 L2, the binding stall test (29 CV-C13; the S3-H plan's section 4): while a platform
task blocks the serving loop with `time.sleep(1.0)` for 3 s, the order lane takes 100 order turns,
an `EXEC` of each of 50 hydrated orders and an abandon of each of 50 `validated` ones, neither of
which calls the venue, each timed from its send to its committed step, its `machine_events` rows
(the lane's own WAL sink, fsync'd) and its audit record (the lane's own `AuditWriter`, its WAL
fsync'd) included: at most 100 ms at p95, BENCH-1's bar
(`docs/research/xstate/13-reeval-0.8.0-bench.md`), and none past 1 s, the first sent and
committed inside the first sleep. The control run takes the same turns with the OMS on the serving
loop (`InlineLane`), which shows the stall: a turn the platform task's sleep caught waited it
out.

`perf`-marked, so the unit lane deselects it and CI's `py-perf` job owns its timing, without
coverage tracing; `test_order_lane`'s companion proves the same isolation with no clock."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from candleviewer.admin.wiring import build_lane_audit_writer, build_machine_event_sink
from candleviewer.audit.repository import AuditRepository
from candleviewer.oms_lane import OrderLane
from candleviewer.oms_wiring import OmsStores, lane_audit_wal
from candleviewer.settings import Settings
from candleviewer.statechart.plugins.audit import GENESIS_HASH
from tests.unit.oms.test_oms_runtime import World, started
from tests.unit.oms.test_order_lane import hydrating, turns, validated

pytestmark = pytest.mark.perf

#: The hydrated orders, each an `EXEC`, and as many `validated` ones, each an abandon: 100 turns.
ORDERS = 50
#: The platform task's three blocking sleeps on the serving loop: the 3 s stall.
STALL_S = (1.0, 1.0, 1.0)
#: The bounds on the lane's turns: BENCH-1's p95, and the most any one may take.
P95_BUDGET_S = 0.100
MAX_S = 1.0
#: A bound on each of the test's waits, never a time it expects.
BOUND_S = 120.0


class Rows:
    """`audit_log` in memory, as the lane's writer's flusher inserts into it."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def insert(self, record: dict[str, Any]) -> None:
        self.rows.append(record)


class Events:
    """`machine_events` in memory, as the lane's sink's flusher inserts into it."""

    async def insert_batch(self, frames: Sequence[Mapping[str, Any]]) -> None:
        return None

    async def head(self, machine_kind: str, entity_id: str, env: str) -> str:
        return GENESIS_HASH


def _real(world: World, wal_dir: Path) -> Callable[[], OmsStores]:
    """The world's stores with the lane's real audit writer and WAL sink, each built where the
    runtime builds them (on its lane), their WAL files in `wal_dir`."""
    settings = Settings(audit_wal_path=str(wal_dir / "audit.wal"))
    rows, events, sink_wal = Rows(), Events(), str(wal_dir / "machine_events.wal")

    def stores() -> OmsStores:
        return replace(
            world.stores(),
            audit=lambda alarm: build_lane_audit_writer(
                cast(AuditRepository, rows), lane_audit_wal(settings), on_alarm=alarm
            ),
            sink=lambda _wal: build_machine_event_sink(settings, events, wal_path=sink_wal),
        )

    return stores


def _hog(seconds: float) -> None:
    """The platform task's blocking call: it holds the serving loop's thread."""
    time.sleep(seconds)


async def _platform(stalling: threading.Event) -> tuple[float, float]:
    """A platform task that blocks the serving loop for `STALL_S`, turning it between its sleeps:
    when its first sleep began and ended, on `time.perf_counter`."""
    began = time.perf_counter()
    stalling.set()
    _hog(STALL_S[0])
    first = (began, time.perf_counter())
    await asyncio.sleep(0)
    for seconds in STALL_S[1:]:
        _hog(seconds)
        await asyncio.sleep(0)
    return first


async def _on_the_lane(wal_dir: Path) -> tuple[list[tuple[float, float]], tuple[float, float]]:
    """The turns on the order lane during the stall, each sent and committed, and when the stall's
    first sleep began and ended."""
    world = World()
    exits = await hydrating(world, ORDERS)
    for flag in world.flags:
        flag.read()
    runtime = world.runtime(lane=OrderLane, stores=_real(world, wal_dir))
    async with asyncio.timeout(BOUND_S), started(runtime):
        await runtime.wait_ready()
        parts = runtime._composed()
        entries = await parts.lane.call(validated(parts.machines, ORDERS))
        stalling = threading.Event()

        async def driven() -> list[tuple[float, float]]:
            assert await asyncio.to_thread(stalling.wait, BOUND_S)
            return await turns(parts.machines, exits, entries, time.perf_counter)

        on_lane = parts.lane.call(driven())
        first = await _platform(stalling)
        spans = await on_lane
    return spans, first


async def _on_the_serving_loop(wal_dir: Path) -> list[tuple[float, float]]:
    """The control: the same turns with the OMS on the serving loop, the stall begun once the
    first is under way."""
    world = World()
    exits = await hydrating(world, ORDERS)
    for flag in world.flags:
        flag.read()
    runtime = world.runtime(stores=_real(world, wal_dir))  # its default lane: this loop's
    async with asyncio.timeout(BOUND_S), started(runtime):
        await runtime.wait_ready()
        parts = runtime._composed()
        entries = await validated(parts.machines, ORDERS)
        driver = asyncio.ensure_future(turns(parts.machines, exits, entries, time.perf_counter))
        await asyncio.sleep(0)  # its first turn is under way when the platform task blocks
        await _platform(threading.Event())
        return await driver


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[int(0.95 * (len(ordered) - 1))]


async def test_order_turns_on_the_lane_ride_out_a_3_s_stall_of_the_serving_loop(
    tmp_path: Path,
) -> None:
    spans, (stall_began, stall_ended) = await _on_the_lane(tmp_path / "lane")
    control = [end - sent for sent, end in await _on_the_serving_loop(tmp_path / "control")]
    taken = [end - sent for sent, end in spans]
    p95, worst, stalled = _p95(taken), max(taken), max(control)
    during = sum(1 for sent, end in spans if stall_began <= sent and end <= stall_ended)
    numbers = (
        f"lane p95 {p95 * 1e3:.1f} ms, max {worst * 1e3:.1f} ms, {during} turns inside the first "
        f"sleep; control max {stalled:.2f} s"
    )
    assert len(taken) == len(control) == 2 * ORDERS, numbers
    assert during >= 1, numbers  # the lane's turns ran while the serving loop slept
    assert p95 <= P95_BUDGET_S and worst < MAX_S, numbers
    assert stalled >= 0.9 * STALL_S[0], numbers  # on the serving loop, a turn waited out a sleep
