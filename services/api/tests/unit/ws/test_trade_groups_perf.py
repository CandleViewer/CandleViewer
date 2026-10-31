"""E28-T05 (#909, slice S4b) perf (C-13.9; the ticket's WS perf AC): the `trade_groups` topic, as
the composition root wires it, with 50 open groups of 5 legs on a real hub, each group changing one
leg every 100 ms for 10 s, 5 000 changes in all. Each change's delta is rendered and handed to its
subscriber within SCR-062's 4 ms frame budget, and carries that one leg, never the group re-sent
(a plain `TopicEmitter` sink, no pacing window, so no window holds a frame). `perf`-marked, so
the unit lane deselects it and `py-perf` runs it without coverage; as `test_machines_perf`, GC is
off and the fastest round's p95 counts."""

from __future__ import annotations

import gc
import time
from decimal import Decimal
from uuid import UUID

import pytest

from tests.unit.accounts.test_trade_group_topic import _leg, _stored
from tests.unit.ws import _seq_support
from tests.unit.ws.test_trade_groups_scope import _conn, _entry, _wired

pytestmark = pytest.mark.perf

GROUPS, LEGS, STEPS, ROUNDS = 50, 5, 100, 3  # 100 steps of 100 ms: 10 s
#: SCR-062: the trade-group manager's 4 ms scripting per frame, applied to the server's frame.
BUDGET_NS = 4_000_000


def test_a_leg_delta_renders_within_scr_062s_frame_budget_and_carries_one_leg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_seq_support, "validate", lambda frame: None)  # frames: checked elsewhere
    accounts = [UUID(int=0xA0 + n) for n in range(LEGS)]
    hub, topic, _, router = _wired(*(_stored(n, *accounts) for n in range(1, GROUPS + 1)))
    conn = _conn(hub, router, *accounts)
    conn.sub(_entry(*accounts))
    conn.take()
    best, gc_was_on = 0, gc.isenabled()
    gc.collect()
    gc.disable()  # a collection inside one timed call would skew the sample
    try:
        for _ in range(ROUNDS):
            samples: list[int] = []
            for step in range(STEPS):
                conn.clock.now += 0.1
                seq, filled = step % LEGS, Decimal(step % 10) / 1000
                for n in range(1, GROUPS + 1):
                    leg = _leg(n, seq, accounts[seq], filled_qty=filled)
                    started = time.perf_counter_ns()
                    topic.leg_changed(leg)
                    samples.append(time.perf_counter_ns() - started)
                frames = conn.take()
                assert [len(f["p"]["trade_groups"][0]["legs"]) for f in frames] == [1] * GROUPS
            p95 = sorted(samples)[int(0.95 * (len(samples) - 1))]
            best = p95 if best == 0 else min(best, p95)
    finally:
        if gc_was_on:
            gc.enable()
    assert 0 < best <= BUDGET_NS, f"p95 {best / 1e3:.0f} us over its budget"
