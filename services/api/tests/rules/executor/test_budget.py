"""E35-T10 (#5002) slice 2f: the SR-104 order budget and its circuit breaker (24 §11.7; BQ-6..8).

The budget counts each order a rule's actions hand to the OMS (one per OMS call per resolved
account, for the nine `counts_orders` types), at check 7, before the records written ahead; an
order counts whatever the OMS answers, and an order a check refuses never counts. Its two windows
slide on the wall clock. A rule's counts are rebuilt at its first order action after a start; while
that read fails its order actions are refused, and that never trips the breaker. Only a spent
budget trips it: the rest of the fire is `circuit_breaker`, the rule's waiting fires are dropped,
it is paged and counted, and B9 `KILL_SWITCH` moves it, so only a human re-arm with step-up leaves
it; a fire offered before the trip is refused at dispatch even after that re-arm. Executor tests
drive `Gated` (`test_gates.py`); the B9 move and its record run on the real manager and charts.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from dataclasses import replace
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.rules import manager as manager_module
from candleviewer.rules.executor import budget as budget_module
from candleviewer.rules.executor import dispatch
from candleviewer.rules.executor.budget import DAY_S, CircuitBreaker, OrderBudget
from candleviewer.rules.executor.gates import Halts
from candleviewer.rules.executor.handlers import HANDLERS, HandlerAnswer
from candleviewer.rules.executor.results import BLOCKED_DETAIL, BUDGET_UNREAD
from candleviewer.rules.ir.models import MAX_ACTIONS
from candleviewer.rules.manager import Actor, RuleError
from candleviewer.rules.scope import ScopeInstanceRef
from tests.rules.executor.test_dispatch import _fire, _Held, _never_refused, _none
from tests.rules.executor.test_gates import (
    ARMER,
    REFUSED,
    RULE,
    RUN,
    TYPES,
    A,
    B,
    C,
    Gated,
    Rebuilt,
    _Stops,
    action,
    per_account,
)
from tests.rules.executor.test_kill_hook import _World

T0 = 1_798_761_600.0  # 2027-01-01T00:00:00Z, a whole minute
NO_ANSWER = HandlerAnswer("no_answer", error_code="timeout")


def _run(n: int) -> uuid.UUID:
    return uuid.UUID(int=0x1000 + n)


async def _order(gated: Gated, n: int, at: float, *, rule_id: str = RULE, **over: Any) -> None:
    """One fire of one `place_order`, `o<n>`, at wall time `at`, offered a second after the last
    on the executor's clock, so never at a trip time (a fire offered at it is refused whole)."""
    gated.wall, gated.now = at, gated.now + 1.0
    await gated.run(action(f"o{n}", rule_id=rule_id, run_id=_run(n), **over), rule_id=rule_id,
                    run_id=_run(n))  # fmt: skip


def _outcomes(gated: Gated) -> list[tuple[str, str, str | None]]:
    return [(node, outcome, why) for node, _, outcome, why in per_account(gated)]


async def _armed_world() -> tuple[_World, str]:
    """A real manager and an armed rule that has met its simulation requirement."""
    w = _World()
    rid = await w.rule("armed")
    row = await w.row(rid)
    row.simulated_hashes, row.simulation_fires = {row.versions[0].ir_hash}, 5
    return w, rid


async def test_a_rules_order_budget_is_enforced_at_dispatch() -> None:
    """Scenario: A rule's order budget is enforced at dispatch (parent Gherkin 3). At the default
    of 10 a minute, the eleventh order within 60 s is refused before the handler with
    `order_budget`; the rule moves to `kill_switched` through B9 `KILL_SWITCH`, `rule.kill_switched`
    is recorded with the reason `order_budget`, and a P1 page names the rule."""
    w, rid = await _armed_world()
    gated = Gated(moving=w.mgr.trip_breaker)
    for n in range(11):
        await _order(gated, n, T0 + n, rule_id=rid)
    assert _outcomes(gated) == [(f"o{n}", "ok", None) for n in range(10)] + [
        ("o10", "blocked", "order_budget")
    ]
    assert len(gated.sent) == 10 and ("o10", str(A)) not in gated.sent
    assert w.mgr.lifecycle.leaf(rid) == "kill_switched"
    row = await w.row(rid)
    assert (row.mode, row.disabled_reason) == ("disabled", "kill_switched")
    (record,) = [p for event, p in w.audits if event == "rule.kill_switched"]
    assert (record["reason"], record["b9_event"], "actor" in record) == (
        "order_budget", "KILL_SWITCH", False,
    )  # fmt: skip
    assert gated.alerts.pages == [("tripped", rid, _run(10), "o10")]
    assert gated.counted.of("rule_circuit_breaker_trips_total") == {(): 1}


async def test_the_201st_order_in_24_hours_is_refused() -> None:
    """24 §11.7: 200 orders a day at the default; the 201st within 24 h is spent, and once the
    first has left the day's window the next is admitted."""
    budget = OrderBudget(rebuild=Rebuilt())
    for n in range(200):  # one every 7 s: never ten within a minute
        assert await budget.admit(RULE, T0 + n * 7.0) == "ok"
    assert await budget.admit(RULE, T0 + 1400.0) == "spent"
    assert await budget.admit(RULE, T0 + DAY_S + 0.5) == "ok"


async def test_budget_window_slides() -> None:
    """The minute's window slides: ten orders at 50 to 59 s leave no room at 61 s, where a fixed
    minute would have started over, nor at 109.5 s; at 110 s the first has slid out."""
    budget = OrderBudget(rebuild=Rebuilt())
    for n in range(10):
        assert await budget.admit(RULE, T0 + 50 + n) == "ok"
    assert await budget.admit(RULE, T0 + 61) == "spent"
    assert await budget.admit(RULE, T0 + 109.5) == "spent"
    assert await budget.admit(RULE, T0 + 110) == "ok"


async def test_budget_counts_across_instances_and_accounts() -> None:
    """BQ-6: one count per OMS call that hands an order, per resolved account, per rule across its
    scope instances: A's instance, B's instance and an `all_accounts` action on A, B and C make
    five; at five a minute the next order, on any instance, is refused."""
    gated = Gated()
    gated.budget.per_minute = 5
    on_b = ScopeInstanceRef(f"BTCUSDT@{B}", "BTCUSDT", B)
    gated.wall = T0
    await gated.run(
        action("a1", on_error="continue"), action("a2", instance=on_b, on_error="continue"),
        action("a3", targets="all_accounts"),
    )  # fmt: skip
    assert len(gated.sent) == 5 and {o for _, o, _ in _outcomes(gated)} == {"ok"}
    await gated.run(action("a4", instance=on_b, run_id=_run(2)), run_id=_run(2))
    assert _outcomes(gated)[-1] == ("a4", "blocked", "order_budget")


async def test_amends_cancels_and_engine_actions_are_never_counted() -> None:
    """BQ-6: only the nine types that hand an order count; amends, cancels, the stop moves,
    lockouts, leverage and the engine's own actions never do, so a budget of one a minute still
    admits an order after all of them."""
    counted = {t for t, spec in HANDLERS.items() if spec.counts_orders}
    assert counted == {
        "place_order", "scale_in", "scale_out", "flatten_position", "flatten_all_positions",
        "reverse_position", "arm_chase_limit", "start_iceberg_slice", "start_twap",
    }  # fmt: skip
    gated = Gated(stop=_Stops({A}))
    gated.budget.per_minute = 1
    others = [t for t in TYPES if t not in counted and t != "widen_stop"]
    gated.wall = T0
    for first in range(0, len(others), MAX_ACTIONS):  # a rule holds at most `MAX_ACTIONS`
        run = _run(first + 1)
        await gated.run(
            *(action(f"n{n}", others[n], on_error="continue", run_id=run)
              for n in range(first, min(first + MAX_ACTIONS, len(others)))),
            run_id=run,
        )  # fmt: skip
    last = _run(len(others) + 1)
    await gated.run(
        action("p1", on_error="continue", run_id=last), action("p2", run_id=last), run_id=last
    )
    assert {o for node, o, _ in _outcomes(gated) if node.startswith("n")} == {"ok"}
    assert _outcomes(gated)[-2:] == [("p1", "ok", None), ("p2", "blocked", "order_budget")]


async def test_a_refused_order_is_never_counted() -> None:
    """BQ-6: an order a check refuses is never counted, the budget's own refusal included; an
    order the OMS refuses is, as it was handed to it."""
    gated = Gated()
    gated.principals.missing.add(ARMER)
    for n in range(10):  # refused at check 5, before the budget
        await _order(gated, n, T0 + n)
    gated.principals.missing.clear()
    for n in range(10, 20):
        await _order(gated, n, T0 + n)
    await _order(gated, 20, T0 + 30)  # spent: refused, and not counted
    await _order(gated, 21, T0 + 70.5)  # nine of the ten admitted are still in its minute
    outcomes = [o for _, o, why in _outcomes(gated)]
    assert outcomes == ["blocked"] * 10 + ["ok"] * 10 + ["blocked", "ok"]
    oms = Gated(answers={"place_order": REFUSED})
    for n in range(11):
        await _order(oms, n, T0 + n)
    assert [o for _, o, _ in _outcomes(oms)] == ["failed"] * 10 + ["blocked"]


async def test_a_retry_rechecks_the_budget_without_counting_again() -> None:
    """24 §11.9: before `retry_once`'s retry check 7 only asks whether the rule tripped, so the
    order is counted once: at two a minute, the retried order and one more are admitted."""
    gated = Gated(answers={"place_order": [NO_ANSWER, HandlerAnswer("accepted")]})
    gated.budget.per_minute = 2
    await _order(gated, 1, T0, on_error="retry_once")
    await _order(gated, 2, T0 + 1)
    await _order(gated, 3, T0 + 2)
    assert [node for node, _ in gated.sent] == ["o1", "o1", "o2"]  # the retry sent it again
    assert _outcomes(gated) == [
        ("o1", "ok", None),
        ("o2", "ok", None),
        ("o3", "blocked", "order_budget"),
    ]


async def test_a_retry_after_the_rule_tripped_sends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """24 §11.9: the rule's breaker trips while its fire's first call waits; check 7 refuses that
    fire's retry, counting nothing, and the first call's result stands (`unknown` after no
    answer)."""
    gated = Gated(answers={"place_order": [NO_ANSWER, HandlerAnswer("accepted")]})
    double = gated.executor._handlers["place_order"].handler
    assert double is not None
    send = double.send

    async def tripping(prep: Any, *, client_ref: str) -> HandlerAnswer:
        gated.halts.tripped[RULE] = gated.now + 1.0  # after the fire's offer time
        return await send(prep, client_ref=client_ref)

    monkeypatch.setattr(double, "send", tripping)
    await _order(gated, 1, T0, on_error="retry_once")
    assert [node for node, _ in gated.sent] == ["o1"]  # the retry sent nothing
    assert _outcomes(gated) == [("o1", "unknown", None)]


async def test_budget_is_rebuilt_after_a_restart_from_the_write_ahead_records() -> None:
    """Scenario: The budget survives a restart (edge case): the counts are rebuilt at the rule's
    first order action after a start, from its counted orders of the last 24 h, once: nine in the
    last minute leave room for one more."""
    rebuilt = Rebuilt([1.0, 5.0, 9.0, 13.0, 17.0, 21.0, 25.0, 29.0, 33.0])
    gated = Gated(rebuilt=rebuilt)
    await _order(gated, 1, T0)
    await _order(gated, 2, T0 + 1)
    assert _outcomes(gated) == [("o1", "ok", None), ("o2", "blocked", "order_budget")]
    assert rebuilt.asked == [RULE]  # read once, at the first order action after the start


@pytest.mark.parametrize("failure", ["raises", "late"])
async def test_order_actions_are_blocked_while_the_budget_cannot_be_rebuilt(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario: The budget survives a restart (edge case): while the rebuild read fails or runs
    past its bound, order actions are refused `order_budget`, with the detail of a count not
    confirmed; an action that hands no order never waits for it; the next order action reads
    again, and once it answers orders are admitted."""
    gated = Gated()
    if failure == "raises":
        gated.rebuilt.failing = True
    else:
        monkeypatch.setattr(budget_module, "REBUILD_TIMEOUT_S", 0.0)
        hang, read = asyncio.Event(), gated.rebuilt.order_ages

        async def stalled(rule_id: str, *, limit: int) -> list[float]:
            await hang.wait()
            return await read(rule_id, limit=limit)

        gated.rebuilt.order_ages = stalled  # type: ignore[method-assign]  # it never answers
    gated.wall = T0
    await gated.run(action("a1", on_error="continue"), action("a2", "send_notification"))
    assert _outcomes(gated) == [("a1", "blocked", "order_budget"), ("a2", "ok", None)]
    details = [
        e.payload["blocked_detail"] for _, e in gated.records.events if e.kind == "action_fail"
    ]
    assert details == [BLOCKED_DETAIL[BUDGET_UNREAD]]
    gated.rebuilt.failing = False
    if failure == "late":
        monkeypatch.setattr(budget_module, "REBUILD_TIMEOUT_S", 2.0)
        hang.set()
    await _order(gated, 3, T0 + 1)
    assert _outcomes(gated)[-1] == ("o3", "ok", None)


async def test_an_unrebuilt_budget_never_trips_the_breaker() -> None:
    """24 §11.7: counts that cannot be rebuilt block, record and count, and never trip it: no
    trip time, no drop, no page, no move."""
    gated = Gated()
    gated.rebuilt.failing = True
    for n in range(3):
        await _order(gated, n, T0 + n)
    assert {why for _, _, why in _outcomes(gated)} == {"order_budget"}
    assert (gated.halts.tripped, gated.dropped, gated.alerts.pages, gated.moves) == ({}, [], [], [])
    assert gated.counted.of("rule_circuit_breaker_trips_total") == {}


async def test_a_tripped_rule_needs_a_human_rearm_with_step_up() -> None:
    """Scenario: A rule's order budget is enforced at dispatch (parent Gherkin 3): re-arming the
    tripped rule needs a human with step-up (INV-B9-d): refused without one, the rule stays
    `kill_switched`; with one, the B9 `HUMAN_REARM` arms it again."""
    w, rid = await _armed_world()
    assert await w.mgr.trip_breaker(rid) is True and w.mgr.lifecycle.leaf(rid) == "kill_switched"

    async def no_step_up() -> bool:
        raise RuleError(403, "step_up_required", "A fresh step-up is needed.")

    used: list[bool] = []

    async def step_up() -> bool:
        used.append(True)
        return True

    owner = Actor(str(uuid.UUID(int=0xA1)), "s1", frozenset({"rules:arm_live"}), is_owner=True)
    with pytest.raises(RuleError) as refused:
        await w.mgr.set_mode(rid, "armed", replace(owner, consume_step_up=no_step_up), "k1")
    assert refused.value.code == "step_up_required" and w.mgr.lifecycle.leaf(rid) == "kill_switched"
    await w.mgr.set_mode(rid, "armed", replace(owner, consume_step_up=step_up), "k2")
    assert used == [True] and w.mgr.lifecycle.leaf(rid) == "armed"
    (armed,) = [p for event, p in w.audits if event == "rule.armed"]
    assert armed["b9_event"] == "HUMAN_REARM"


async def test_max_fire_rate_auto_disables() -> None:
    """RE-D6 (AC-04): a rule that fires every second at its maximum rate is stopped by its own
    budget: the eleventh order trips the breaker, B9 moves the rule out of `armed`, and its next
    fires end at check 1, sending nothing more."""
    w, rid = await _armed_world()
    gated = Gated(moving=w.mgr.trip_breaker, rows=w.mgr)
    for n in range(14):
        await _order(gated, n, T0 + n, rule_id=rid)
    outcomes = [(o, why) for _, o, why in _outcomes(gated)]
    assert (
        outcomes
        == [("ok", None)] * 10 + [("blocked", "order_budget")] + [("skipped", "mode_changed")] * 3
    )
    assert len(gated.sent) == 10 and (await w.row(rid)).mode == "disabled"


async def test_breaker_drops_queued_fires_of_the_rule() -> None:
    """24 §11.7 (BQ-8): the trip takes the rule's waiting fires out of its lane before the B9 move
    and again after it, for a fire offered meanwhile; never the fire that runs, nor another
    rule's."""
    other = str(uuid.UUID(int=9))
    held = _Held(RULE)
    fires = dispatch.FireDispatch(_never_refused, held)
    fires.start()
    for fire in (_fire(1, "a1", emit=_none), _fire(2, "a1", emit=_none),
                 _fire(3, "a1", emit=_none), _fire(4, "b1", emit=_none, rule=other)):  # fmt: skip
        assert fires.offer(fire)
    async with asyncio.timeout(5):
        await held.running.wait()
    dropped: list[tuple[int, str]] = []
    in_move, moving = asyncio.Event(), asyncio.Event()

    def drop(rule_id: str, why: Any) -> None:
        dropped.extend((f.run_id.int, why) for f in fires.drop(rule_id))

    async def move(rule_id: str) -> bool:
        assert fires.offer(_fire(5, "a1", emit=_none))  # offered while the rule moves
        in_move.set()
        await moving.wait()
        return True

    trip = asyncio.create_task(
        CircuitBreaker(Halts(), move=move, drop=drop).trip(RULE, uuid.UUID(int=1), "a1")
    )
    async with asyncio.timeout(5):
        await in_move.wait()
    assert dropped == [(2, "circuit_breaker"), (3, "circuit_breaker")]  # before the move
    moving.set()
    await trip
    assert dropped == [(2, "circuit_breaker"), (3, "circuit_breaker"), (5, "circuit_breaker")]
    held.held[RULE].set()
    async with asyncio.timeout(5):
        await fires.idle()
    await fires.stop(0.0)
    assert sorted(held.ran) == sorted([(RULE, 1), (other, 4)])


async def test_the_rest_of_the_tripping_fire_is_blocked_as_circuit_breaker() -> None:
    """BQ-8: the action whose order the budget refuses is `order_budget`, and everything after it
    in its fire, every account of every later action, is `circuit_breaker`, whatever `on_error`
    says."""
    gated = Gated()
    gated.budget.per_minute = 1
    await _order(gated, 0, T0)
    gated.wall = T0 + 1
    await gated.run(
        action("a1", on_error="continue"), action("a2", "send_notification", on_error="continue"),
        action("a3", targets="all_accounts", on_error="continue"), run_id=_run(1),
    )  # fmt: skip
    assert per_account(gated)[1:] == [
        ("a1", str(A), "blocked", "order_budget"), ("a2", None, "blocked", "circuit_breaker"),
        ("a3", str(A), "blocked", "circuit_breaker"), ("a3", str(B), "blocked", "circuit_breaker"),
        ("a3", str(C), "blocked", "circuit_breaker"),
    ]  # fmt: skip
    assert gated.sent == [("o0", str(A))] and gated.moves == [RULE]


async def test_a_fire_offered_before_the_trip_is_blocked_at_dispatch_even_after_a_rearm() -> None:
    """24 §11.5 (BQ-8, the carry from #5153): a fire offered before its rule's trip time is
    refused whole at dispatch (`circuit_breaker`), before check 1, though the rule was re-armed to
    the same version meanwhile; one offered after the trip runs its checks."""
    gated = Gated()
    gated.halts.tripped[RULE] = 50.0
    await gated.run(action("a1", on_error="continue"), action("a2"), offered_at=40.0)
    assert _outcomes(gated) == [
        ("a1", "blocked", "circuit_breaker"),
        ("a2", "blocked", "circuit_breaker"),
    ]
    assert gated.checked == [] and gated.records.closed[RUN][0] == "aborted"
    assert gated.counted.blocked() == {"circuit_breaker": 2}  # recorded and counted (R1C2-05)
    await gated.run(action("a3", run_id=_run(3)), run_id=_run(3), offered_at=60.0)
    assert _outcomes(gated)[-1] == ("a3", "ok", None)


@pytest.mark.parametrize("halt", ["tripped", "killed"])
def test_a_fire_offered_at_the_halt_time_is_refused_as_one_offered_before_it(halt: str) -> None:
    """24 §11.5 (R1S-04): a fire offered at its rule's trip or kill time is refused whole, as the
    retry's check 7 reads the trip time (`>=`); one offered the least time after it is not."""
    halts = Halts()
    getattr(halts, halt)[RULE] = 50.0
    blocked = "circuit_breaker" if halt == "tripped" else "kill_switch"
    assert halts.block(RULE, 50.0) == blocked
    assert halts.block(RULE, math.nextafter(50.0, math.inf)) is None


async def test_a_breaker_move_that_finds_the_rule_disarmed_has_landed() -> None:
    """24 §11.7 (R1C2-03): the rule is disarmed before its breaker's move reads it. Nothing is
    left to stop, so the move has landed and the rule is not left unmoved: after a human re-arm
    its first order is admitted, and no second move is sent."""
    w, rid = await _armed_world()
    gated = Gated(moving=w.mgr.trip_breaker, rows=w.mgr)

    async def step_up() -> bool:
        return True

    owner = Actor(str(uuid.UUID(int=0xA1)), "s1", frozenset({"rules:arm_live"}), is_owner=True,
                  consume_step_up=step_up)  # fmt: skip
    await w.mgr.set_mode(rid, "disabled", owner, "disarm")
    await gated.executor._breaker.trip(rid, _run(1), "o1")
    assert not gated.executor._breaker.unmoved(rid) and gated.alerts.rows[-1][3] is True
    await w.mgr.set_mode(rid, "armed", owner, "rearm")
    await _order(gated, 2, T0 + 1, rule_id=rid)
    assert _outcomes(gated) == [("o2", "ok", None)] and gated.moves == [rid]
    assert w.mgr.lifecycle.leaf(rid) == "armed"


async def test_a_breaker_move_the_chart_refuses_is_no_landed_move() -> None:
    """24 §11.7 (R1C2-03, the other side): a row still armed whose B9 chart does not take the move
    (here the chart is already `kill_switched`) is stuck: `trip_breaker` answers false, nothing
    is recorded and the row stays armed, so the breaker keeps the rule's order actions refused."""
    w, rid = await _armed_world()
    assert await w.mgr.lifecycle.current(rid, "armed", None) == "armed"
    await w.mgr.lifecycle.send(rid, "KILL", reason="kill_switch")  # the chart alone moves
    assert await w.mgr.trip_breaker(rid) is False
    assert (await w.row(rid)).mode == "armed" and w.audits == [] and not w.mgr._stop_broadcasts


@pytest.mark.parametrize("broadcast", ["slow", "hangs", "fails"])
async def test_the_stop_broadcast_runs_beside_the_move_under_a_bound_of_its_own(
    broadcast: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """24 §11.7 (R1C2-03): the moved rule's `rules` broadcast never holds the move or its caller's
    bound: the move answers before its broadcast runs; a slow one then ends in its own time, and
    one that hangs (its own bound cut to nothing here) or fails is logged by its error's class."""
    if broadcast == "hangs":
        monkeypatch.setattr(manager_module, "STOP_TIMEOUT_S", 0.0)
    w, rid = await _armed_world()
    release = asyncio.Event()

    async def hub(message: dict[str, Any]) -> None:
        if broadcast == "fails":
            raise ConnectionError("the hub is unreachable")
        await release.wait()

    w.mgr.set_hooks(broadcast=hub)
    with capture_logs() as logs:
        async with asyncio.timeout(5):  # a guard: a move that awaited the broadcast never returns
            assert await w.mgr.trip_breaker(rid) is True
            (running,) = w.mgr._stop_broadcasts
            assert not running.done()  # the move answered before its broadcast ran
            if broadcast == "slow":
                release.set()
            await running
    assert w.mgr.lifecycle.leaf(rid) == "kill_switched" and not w.mgr._stop_broadcasts
    failed = [e["error"] for e in logs if e["event"] == "rules.stop_broadcast_failed"]
    expected = {"slow": [], "hangs": ["TimeoutError"], "fails": ["ConnectionError"]}
    assert failed == expected[broadcast]


async def test_the_breaker_pages_p1_naming_the_rule_and_counts_the_trip() -> None:
    """BQ-8: every trip pages, naming the rule, the fire and the action, with no episode dedupe,
    and counts `rule_circuit_breaker_trips_total`; its `system_events` row says it moved."""
    gated = Gated()
    gated.budget.per_minute = 1
    for n, at in enumerate((T0, T0 + 1, T0 + 2)):  # one admitted, then two trips
        await _order(gated, n, at)
    assert gated.alerts.pages == [
        ("tripped", RULE, _run(1), "o1"), ("tripped", RULE, _run(2), "o2"),
    ]  # fmt: skip
    assert gated.alerts.rows == [(RULE, _run(1), "o1", True), (RULE, _run(2), "o2", True)]
    assert gated.counted.of("rule_circuit_breaker_trips_total") == {(): 2}


async def test_a_failed_breaker_move_keeps_the_trip_and_pages() -> None:
    """BQ-8: a B9 move that fails keeps the trip time standing and pages that the rule was not
    moved; until the move lands every order action of the rule is refused, even once the window
    has slid, and each sends the move again, which is no new trip (R1S-02): the trip time, the
    trip's page and its count stay the first trip's, and each attempt writes its row."""
    gated = Gated(moving=ConnectionError("the rule store is unreachable"))
    gated.budget.per_minute = 1
    await _order(gated, 0, T0)
    await _order(gated, 1, T0 + 1)  # spent: trips, and the move fails
    tripped_at = gated.halts.tripped[RULE]
    assert gated.alerts.rows == [(RULE, _run(1), "o1", False)]
    await _order(gated, 2, T0 + 120)  # the minute is clear, but the rule was never moved
    assert _outcomes(gated)[-1] == ("o2", "blocked", "order_budget")
    assert gated.moves == [RULE, RULE] and gated.halts.tripped[RULE] == tripped_at
    assert gated.alerts.pages == [("tripped", RULE, _run(1), "o1")]
    assert gated.counted.of("rule_circuit_breaker_trips_total") == {(): 1}
    assert gated.alerts.rows[-1] == (RULE, _run(2), "o2", False)
    gated.moving = True  # the store is back: the next refusal moves it
    await _order(gated, 3, T0 + 121)
    assert gated.moves == [RULE] * 3 and gated.alerts.rows[-1][3] is True
    await _order(gated, 4, T0 + 240)
    assert _outcomes(gated)[-1] == ("o4", "ok", None)  # moved: nothing more refuses it here


async def test_a_rearm_never_resets_the_counts() -> None:
    """BQ-8: a human re-arm after the trip leaves the budget's counts as they are: the next order
    within the minute is still refused."""
    w, rid = await _armed_world()
    gated = Gated(moving=w.mgr.trip_breaker)
    gated.budget.per_minute = 2
    for n in range(3):
        await _order(gated, n, T0 + n, rule_id=rid)
    assert w.mgr.lifecycle.leaf(rid) == "kill_switched"

    async def step_up() -> bool:
        return True

    owner = Actor(str(uuid.UUID(int=0xA1)), "s1", is_owner=True, consume_step_up=step_up)
    await w.mgr.set_mode(rid, "armed", owner, "rearm")
    gated.now += 1  # offered after the trip
    await _order(gated, 3, T0 + 10, rule_id=rid)
    assert _outcomes(gated)[-1] == ("o3", "blocked", "order_budget")
