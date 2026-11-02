"""E35-T10 (#5002) slice 2f: repeated scope refusals auto-disarm the rule (24 §11.5; RE-E1, BQ-10).

Per rule and account (none for an action that names none), the service counts an armed rule's
consecutive `scope` or `permission` refusals at dispatch and the tick's scope-skipped evaluations,
one each; a pass of check 5 on the account clears the count, the rule's leaving `armed` by any
move and a tick that evaluates it in another mode drop its counts, and the fifth (interim, pending
the owner's ratification, #2701) disarms the rule: B9 `DISARM`, `rule.disarmed` with the reason
`scope_denied`, beside the tick and never awaited on it, counted in `rule_autodisarm_total`. The
rig is K1b's dispatch rig: a `RulesService` over an in-memory store, its evaluator on and its
clocks frozen.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from candleviewer.rules import manager as manager_module
from candleviewer.rules.limits import SCOPE_DENIALS_BEFORE_DISARM
from candleviewer.rules.service import RulesService
from tests.rules.executor import test_gates as gates_rig
from tests.rules.executor.request_builders import Principals
from tests.rules.executor.test_dispatch import GUARD_S, DispatchRig, rig, start
from tests.rules.executor.test_mode_split import ACTOR
from tests.rules.test_scope_wiring import OWNER, A, B

__all__ = ["rig", "start"]  # the fixtures, imported


@pytest.fixture(autouse=True)
def _disarm_bound_lifted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The disarm's own bound (`TICK_DISARM_TIMEOUT_S`, 2 s) lifted, so a slow run never cuts a
    disarm short and only a test's hold delays one."""
    monkeypatch.setattr(manager_module, "TICK_DISARM_TIMEOUT_S", 60 * GUARD_S)


def _principals(rig: DispatchRig) -> Principals:
    principals = rig.svc._principal
    assert isinstance(principals, Principals)
    return principals


async def _ticks(rig: DispatchRig, n: int) -> None:
    for _ in range(n):
        async with asyncio.timeout(GUARD_S):  # a tick that awaited the disarm would never return
            await rig.fire()
        await rig.settle()


async def _disarms(rig: DispatchRig) -> None:
    async with asyncio.timeout(GUARD_S):
        await asyncio.gather(*rig.mgr._tick_disarms.values())


def _recording(rig: DispatchRig, hold: asyncio.Event | None = None) -> list[tuple[str, Any]]:
    """The manager's audit records from here on; `hold` holds a `rule.disarmed` write."""
    audits: list[tuple[str, Any]] = []

    async def audit(event: str, payload: dict[str, Any]) -> None:
        if event == "rule.disarmed" and hold is not None:
            await hold.wait()
        audits.append((event, payload))

    rig.mgr.set_hooks(audit=audit)
    return audits


async def test_repeated_scope_refusals_auto_disarm_the_rule(rig: DispatchRig) -> None:
    """RE-E1 (AC-01): the armer is disabled after arming; each fire's action is refused
    `permission` at dispatch, recorded `rules.blocked`, and the fifth consecutive refusal disarms
    the rule: B9 `DISARM`, `rule.disarmed` with `scope_denied` and no actor, counted once."""
    assert SCOPE_DENIALS_BEFORE_DISARM == 5
    rid = await rig.add("armed")
    audits = _recording(rig)
    _principals(rig).facts[OWNER] = (False, "owner", True, frozenset())  # disabled
    await _ticks(rig, 4)
    assert (await rig.row(rid)).mode == "armed" and rig.mgr._tick_disarms == {}
    await _ticks(rig, 1)
    await _disarms(rig)
    row = await rig.row(rid)
    assert (row.mode, row.disabled_reason) == ("disabled", "disarmed")
    assert rig.mgr.lifecycle.leaf(rid) == "disarmed"
    (disarmed,) = [p for event, p in audits if event == "rule.disarmed"]
    assert (disarmed["reason"], disarmed["b9_event"], "actor" in disarmed) == (
        "scope_denied", "DISARM", False,
    )  # fmt: skip
    assert rig.counted.of("rule_autodisarm_total") == {(): 1}
    assert rig.counted.blocked()["permission"] == 5 and rig.executor == []
    assert rig.svc._strikes == {}  # the landed disarm drops the rule's counts (R1C2-05)
    row.mode = "armed"  # armed again: its count starts from none, so four refusals disarm nothing
    await _ticks(rig, 4)
    assert rig.svc._strikes == {rid: {None: 4}} and rig.mgr._tick_disarms == {}


async def test_a_passing_action_resets_the_accounts_refusal_count(rig: DispatchRig) -> None:
    """Only consecutive refusals count: four, a pass of check 5, then four more leave the rule
    armed; a fifth in a row disarms it."""
    rid = await rig.add("armed")
    principals = _principals(rig)
    principals.facts[OWNER] = (False, "owner", True, frozenset())
    await _ticks(rig, 4)
    del principals.facts[OWNER]  # active again: the next action passes check 5
    await _ticks(rig, 1)
    principals.facts[OWNER] = (False, "owner", True, frozenset())
    await _ticks(rig, 4)
    assert (await rig.row(rid)).mode == "armed" and rig.mgr._tick_disarms == {}
    assert len(rig.executor) == 1  # the one that passed went on
    await _ticks(rig, 1)
    await _disarms(rig)
    assert (await rig.row(rid)).mode == "disabled"


async def test_an_account_less_pass_never_clears_an_accounts_refusal_count() -> None:
    """R1C2-01: each fire's order on A is refused `permission` (the armer admits no account), and
    its notification then passes under `continue`; the pass counts under no account, so the
    order's refusals on A run on to five."""
    gated = gates_rig.Gated()
    gated.principals.facts[gates_rig.ARMER] = (True, "manager", False, frozenset())
    svc = RulesService()
    gated.executor._on_scope = svc._scope_outcome
    for _ in range(SCOPE_DENIALS_BEFORE_DISARM):
        await gated.run(
            gates_rig.action("a1", on_error="continue"),
            gates_rig.action("a2", "send_notification"),
        )
    assert gated.results()[-2:] == [("a1", "blocked", "permission"), ("a2", "ok", None)]
    assert svc._strikes == {gates_rig.RULE: {gates_rig.A: SCOPE_DENIALS_BEFORE_DISARM}}


async def test_only_an_armed_rules_refusals_count_and_another_mode_drops_them(
    rig: DispatchRig,
) -> None:
    """R1C2-02: a simulate rule's scope-skipped evaluations count nothing; an armed rule's four
    counts are dropped by one tick that evaluates it in simulate, so once armed again it needs
    five new refusals."""
    simulating, rid = await rig.add("simulate"), await rig.add("armed")
    rig.source.grants = [(B, True, False)]  # A withdrawn: each tick skips both rules' evaluations
    await _ticks(rig, 4)
    assert rig.svc._strikes == {rid: {A: 4}} and rig.mgr._tick_disarms == {}
    row = await rig.row(rid)
    row.mode = "simulate"
    await _ticks(rig, 1)
    assert rig.svc._strikes == {}
    row.mode = "armed"
    await _ticks(rig, 4)
    assert rig.svc._strikes == {rid: {A: 4}} and rig.mgr._tick_disarms == {}
    await _ticks(rig, 1)
    await _disarms(rig)
    assert (row.mode, (await rig.row(simulating)).mode) == ("disabled", "simulate")


@pytest.mark.parametrize("move", ["disarm", "simulate", "kill", "breaker", "auto_disarm"])
async def test_the_counts_go_when_the_rule_leaves_armed_so_a_rearm_starts_at_none(
    rig: DispatchRig, move: str
) -> None:
    """24 §11.5 (the lane's ruling under R1C2-02): the rule holds counts on A (scope-skipped
    evaluations) and on no account (refused notifications). The moment its row leaves `armed`, by
    a human disarm or mode change, the kill switch's or the breaker's move, or the auto-disarm
    itself, with no tick in between, its counts are gone: armed again, its first refusal counts
    one, not the old count plus one."""
    rid = await rig.add("armed")
    rig.source.grants = [(B, True, False)]  # A withdrawn: each tick skips the evaluation on A
    await _ticks(rig, 2)
    _principals(rig).facts[OWNER] = (False, "owner", True, frozenset())  # check 5 refuses
    rig.source.grants = [(A, True, False), (B, True, False)]  # A back: the notification goes on
    await _ticks(rig, SCOPE_DENIALS_BEFORE_DISARM if move == "auto_disarm" else 2)
    if move == "auto_disarm":
        await _disarms(rig)
    else:
        assert rig.svc._strikes == {rid: {A: 2, None: 2}}
        if move in ("disarm", "simulate"):
            await rig.mgr.set_mode(rid, "disabled" if move == "disarm" else "simulate", ACTOR, move)
        elif move == "kill":
            assert await rig.mgr.kill_all("global", "kill_switch") == (rid,)
        else:
            assert await rig.mgr.trip_breaker(rid) is True
    row = await rig.row(rid)
    assert row.mode != "armed" and rig.svc._strikes == {}
    row.mode, row.armed_by = "armed", str(OWNER)  # armed again, as the rig arms a rule
    rig.source.grants = [(B, True, False)]
    await _ticks(rig, 1)
    assert rig.svc._strikes == {rid: {A: 1}}


async def test_scope_skipped_evaluations_count_toward_the_auto_disarm(rig: DispatchRig) -> None:
    """The owner's grant on the rule's account is withdrawn: the tick's scope gate skips each
    evaluation, counted once each, synchronously, and the fifth disarms the rule."""
    rid = await rig.add("armed")
    audits = _recording(rig)
    rig.source.grants = [(B, True, False)]  # A withdrawn: the next tick's refresh reads it
    await _ticks(rig, 5)
    await _disarms(rig)
    assert (await rig.row(rid)).mode == "disabled" and rig.executor == []
    assert [p["reason"] for event, p in audits if event == "rule.disarmed"] == ["scope_denied"]
    assert rig.counted.blocked()["scope"] == 5  # each skipped evaluation's action, once


async def test_the_tick_never_awaits_the_auto_disarm(rig: DispatchRig) -> None:
    """C-2.20: the fifth count, on the tick, starts the disarm beside it; while its record is held
    (its own bound lifted, so the hold alone ends it) the tick returns, and the next one does too,
    the same disarm still in flight; the rule is disarmed once the record lands."""
    rid = await rig.add("armed")
    hold = asyncio.Event()
    _recording(rig, hold)
    rig.source.grants = [(B, True, False)]
    await _ticks(rig, 5)
    disarm = rig.mgr._tick_disarms[rid]
    assert (await rig.row(rid)).mode == "armed"
    await _ticks(rig, 1)  # the disarm still waits: this tick returns all the same
    assert rig.mgr._tick_disarms.get(rid) is disarm and not disarm.done()
    hold.set()
    await _disarms(rig)
    assert (await rig.row(rid)).mode == "disabled"
