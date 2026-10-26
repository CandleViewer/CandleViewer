"""Performance budget of the order submission pipeline (E29-T04 #913; the plan's C5 perf test):
one `placeOrder` request through `OrderSubmission`, its first persist, `SEND`, the create on a
zero-latency `FakeTradingPort` and its answer, within 50 ms at p95, the backend's share of budget
#4 before any network or database time.

`perf`-marked, so the unit lane deselects it and the `py-perf` job runs it without coverage. It is
calibrated for shared runners as the other perf tests are (#1943): GC is off around the timed
rounds, each round times `REQUESTS` requests after a warm-up, and the fastest round's p95 is the
measure (host load only ever adds time). Each sample is one `submit` call, from its first step to
its answer; the facade's turns after it are settled untimed."""

from __future__ import annotations

import gc
import time
from collections import OrderedDict
from uuid import uuid4

import pytest

from candleviewer.oms.ports import SizingRequest
from candleviewer.oms.submit import OrderRequest
from candleviewer.statechart.bindings import b01_order as b01
from tests.unit.oms.submit_rig import SubmitRig, build_rig, context, entry

pytestmark = pytest.mark.perf

ROUNDS = 3
REQUESTS = 20
#: The plan's bound on one request's backend work, with zero-latency fakes (p95).
BUDGET_NS = 50_000_000


async def _round(rig: SubmitRig, request: OrderRequest) -> list[int]:
    samples: list[int] = []
    for _ in range(REQUESTS):
        started = time.perf_counter_ns()
        outcome = await rig.submit(request, context(client_ref=uuid4()))
        samples.append(time.perf_counter_ns() - started)
        assert outcome.status == 202
        await rig.quiet()  # untimed: the facade's turns settle, final machines leave
    return samples


def _p95(samples: list[int]) -> int:
    ordered = sorted(samples)
    return ordered[int(0.95 * (len(ordered) - 1))]


async def _best_p95(monkeypatch: pytest.MonkeyPatch, request: OrderRequest) -> int:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    rig = build_rig()
    best = 0
    gc.collect()
    gc.disable()  # a collection inside one timed call would skew the sample
    try:
        await _round(rig, request)  # warm-up: imports, compiled schemas, the first machines
        for _ in range(ROUNDS):
            p95 = _p95(await _round(rig, request))
            best = p95 if best == 0 else min(best, p95)
    finally:
        gc.enable()
        await rig.machines.stop()
    return best


async def test_a_submission_fits_50_ms_at_p95(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `fixed_qty` request overlaid on the profile: sized twice and judged (#913 S4-S)."""
    best = await _best_p95(monkeypatch, entry())
    assert best <= BUDGET_NS, f"p95 {best / 1e6:.2f} ms > {BUDGET_NS / 1e6:.0f} ms"


async def test_a_profile_sized_submission_fits_50_ms_at_p95(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An entry sized by its profile alone, its figures read warm (the venue's reads mocked)."""
    request = entry(sizing=SizingRequest(mode="profile"), stop_loss=None, take_profit=None)
    best = await _best_p95(monkeypatch, request)
    assert best <= BUDGET_NS, f"p95 {best / 1e6:.2f} ms > {BUDGET_NS / 1e6:.0f} ms"
