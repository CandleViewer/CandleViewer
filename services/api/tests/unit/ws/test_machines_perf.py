"""E17-T08 perf (ticket label `perf`, C-13.9): what a machine's transition pays for its feed, for
E29-T04 (B1's own budget is 5 ms p95 a step, `test_order_machine_perf`). The registry checks, copies
and fans a payload out inside the step; at a window's leading edge, the dearest case, that is a
fixed cost plus a cost for each subscription of the entity. 40 is the most there can be: one
owner's connections (8 a user) and a few managers'. `perf`-marked, so the unit lane deselects it
and `py-perf` runs it without coverage; as there, GC is off and the fastest round's p95 counts."""

from __future__ import annotations

import gc
import time
from typing import Any

import pytest

from candleviewer.ws.machines import MachineEntity, MachineStateRegistry
from candleviewer.ws.sequencing import SequencingHub
from tests.unit.ws import _seq_support
from tests.unit.ws._seq_support import Clock, Conn, Source
from tests.unit.ws.test_machines import OID, ON_A, _attach

pytestmark = pytest.mark.perf

ROUNDS, PUBLISHES = 3, 200
#: p95 in ns by subscriptions. Measured on the loaded dev VPS: 60 us with none, 416 us with 40.
BUDGET_NS = {0: 500_000, 40: 2_000_000}


def _payload(n: int) -> dict[str, Any]:
    """B1's, the widest: `regions`, tags and a summary."""
    state = ("submitted", "partially_filled", "filled")[n % 3]
    return {
        "machine_kind": "order",
        "state": state,
        "regions": {"lifecycle": state, "protection": "sl_present"},
        "tags": ["protected"],
        "degraded": False,
        "machine_hash": "0" * 64,
        "environment": "demo",
        "updated_at_ms": 1_789_132_262_000 + n,
        "context_summary": {"symbol": "BTCUSDT", "halted_by_kill": False, "recon_misses": 0},
    }


@pytest.mark.parametrize("subscriptions", sorted(BUDGET_NS))
def test_a_leading_edge_publish_fits_its_budget(
    subscriptions: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_seq_support, "validate", lambda frame: None)  # frames: checked elsewhere
    clock, hub = Clock(), SequencingHub()
    registry, order = MachineStateRegistry(hub=hub, clock=clock), MachineEntity("order", OID, ON_A)
    registry.publish(order, _payload(0))
    conns: list[Conn] = []
    for _ in range(subscriptions):
        conn = Conn(Source(), services=conns[0].authz.services if conns else None)
        _attach(conn, registry, hub)
        conn.sub(order.ch)
        conns.append(conn)
    best, gc_was_on = 0, gc.isenabled()
    gc.collect()
    gc.disable()  # a collection inside one timed call would skew the sample
    try:
        for _ in range(ROUNDS):
            samples: list[int] = []
            for n in range(PUBLISHES):
                clock.now += 1.0  # a quiet window: this publish is a leading edge
                payload = _payload(n)
                started = time.perf_counter_ns()
                assert registry.publish(order, payload)
                samples.append(time.perf_counter_ns() - started)
                for conn in conns:
                    conn.out.clear()
            p95 = sorted(samples)[int(0.95 * (len(samples) - 1))]
            best = p95 if best == 0 else min(best, p95)
    finally:
        if gc_was_on:
            gc.enable()
    assert 0 < best <= BUDGET_NS[subscriptions], f"p95 {best / 1e3:.0f} us over its budget"
