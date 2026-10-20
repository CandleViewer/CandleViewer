"""Performance budget of a B1 transition (E29-T03 #847, the ticket's performance notes): one step
of an order through the OMS facade, its write-ahead row included, within 5 ms at p95, so it fits
the backend portion of budget #4.

`perf`-marked, so the unit lane deselects it and the `py-perf` job runs it without coverage. It is
calibrated for shared runners as the other perf tests are (#1943): GC is off around the timed
rounds, each round times every transition of `ORDERS` orders after a warm-up order, and the fastest
round's p95 is the measure (host load only ever adds time). Each sample is one facade call: a
command or a push, its step written through the step writer to the in-memory store, and the turn
that settles it (a first fill's `FIRST_FILL` included). Building an order's machine is not a
transition and is not timed. The Postgres share of the write is not measured here (there is no
database in the unit lanes); budget #4 end to end is E29-Q03's."""

from __future__ import annotations

import gc
import time
from collections import OrderedDict
from collections.abc import Awaitable

import pytest

from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.registry import Registry
from tests.unit.oms.order_rig import ACCOUNT, Rig, build_rig, fill_of, order_of

pytestmark = pytest.mark.perf

REGISTRY = Registry()
ROUNDS = 3
ORDERS = 20
#: The ticket's bound on one transition, its event write included (p95).
BUDGET_NS = 5_000_000


async def _timed(samples: list[int], step: Awaitable[object], rig: Rig) -> None:
    started = time.perf_counter_ns()
    await step
    samples.append(time.perf_counter_ns() - started)
    await rig.quiet()  # untimed: the invokes answer and their steps commit


async def _round(rig: Rig, first: int) -> list[int]:
    """Every timed transition of `ORDERS` orders: sent, filled twice, amended and cancelled."""
    samples: list[int] = []
    facade = rig.facade
    for n in range(first, first + ORDERS):
        order = order_of(n)
        await rig.start(order)
        await rig.quiet()
        await _timed(samples, facade.command(ACCOUNT, order.id, "SEND", actor="user"), rig)
        for exec_id in (f"a{n}", f"b{n}"):
            fill = fill_of(order, exec_id, "0.2")
            await _timed(samples, facade.push(ACCOUNT, order.id, "EXEC", fill), rig)
        amend = facade.command(ACCOUNT, order.id, "AMEND", {"price": "64000"}, actor="user")
        await _timed(samples, amend, rig)
        await _timed(samples, facade.command(ACCOUNT, order.id, "CANCEL", actor="user"), rig)
    return samples


def _p95(samples: list[int]) -> int:
    ordered = sorted(samples)
    return ordered[int(0.95 * (len(ordered) - 1))]


async def test_a_transition_with_its_write_fits_5_ms_at_p95(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ticket's performance note: a transition, its event write included, at or under 5 ms
    p95; one machine per order behind its own lock, no global one."""
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    rig = build_rig(registry=REGISTRY)
    best = 0
    gc.collect()
    gc.disable()  # a collection inside one timed call would skew the sample
    try:
        await _round(rig, 1)  # warm-up: imports, compiled schemas, the first machines
        for index in range(ROUNDS):
            p95 = _p95(await _round(rig, 1 + ORDERS * (index + 1)))  # orders 21 to 80
            best = p95 if best == 0 else min(best, p95)
    finally:
        gc.enable()
        await rig.facade.stop()
    assert 0 < best <= BUDGET_NS, f"p95 {best / 1e6:.3f} ms over the 5 ms budget"
