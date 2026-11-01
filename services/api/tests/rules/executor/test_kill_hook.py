"""E35-T10 (#5002) slice 2e: the kill switch's `disarm_rules` hook (24 §11.7; BQ-9, BQ-6 of #863).

`RulesManager.kill_all(scope, reason)` sends B9 `KILL` to every armed rule in the switch's scope,
each recorded `rule.kill_switched` (reason `kill_switch`, no actor) under its own bound, so only a
human re-arm leaves it (INV-B9-d); the service's hook drops each moved rule's waiting fires from its
lane, recorded refused whole (`kill_switch`), and stamps the rule's kill time, which blocks at
dispatch a fire offered before it. Nothing calls the hook yet: E39-S03 binds it, and the suite runs
again against #956. The rules run on the real manager, store and B9 charts.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.rules import manager as manager_module
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleRow, RulesManager
from candleviewer.rules.vocabulary import default_registry
from tests.rules.executor.request_builders import Switches
from tests.rules.executor.test_dispatch import DispatchRig, _actions, rig, start
from tests.rules.executor.test_gates import RULE, Gated, action
from tests.rules.test_scope_wiring import OWNER, A, B

__all__ = ["rig", "start"]  # the fixtures, imported
FIXTURE = Path(__file__).parents[2] / "fixtures/rule_ir/form_simple_0.json"
ACTOR = Actor(str(OWNER), "s1", frozenset({"rules:arm_live"}), is_owner=True, step_up_fresh=True)


class _World:
    """A manager over an in-memory store whose audit records every write, or fails one action."""

    def __init__(self, *, failing: str | None = None) -> None:
        self.store, self.audits = InMemoryRuleStore(), list[tuple[str, dict[str, Any]]]()
        self.stopped: list[tuple[str, str]] = []
        self.failing = failing
        self.mgr = RulesManager(self.store, default_registry(), audit=self.audit)
        self.mgr.set_hooks(rule_stopped=lambda rid, why: self.stopped.append((rid, why)))

    async def audit(self, event: str, payload: dict[str, Any]) -> None:
        if event == self.failing:
            raise ConnectionError("the audit writer is unreachable")
        self.audits.append((event, payload))

    async def rule(
        self, mode: str, accounts: tuple[uuid.UUID, ...] = (A,), *, targets: str | None = None
    ) -> str:
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        raw["name"] = f"rule-{len(await self.store.all())}"
        raw["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
        if targets is not None:
            raw["actions"][0]["targets"] = targets
        raw["scope"] = {"level": "account", "account_ids": [str(a) for a in accounts]}
        rid = str((await self.mgr.create(raw, ACTOR))["id"])
        row = await self.row(rid)
        row.mode, row.armed_by = mode, (str(OWNER) if mode == "armed" else None)
        self.audits.clear()
        return rid

    async def row(self, rid: str) -> RuleRow:
        row = await self.store.get(rid)
        assert row is not None
        return row


async def test_kill_all_hook_moves_every_armed_rule_to_kill_switched_and_audits() -> None:
    """Every armed rule moves to B9 `kill_switched` (its row `disabled`, `kill_switched`), each
    recorded `rule.kill_switched` with the reason and no actor; a rule that is not armed stays."""
    w = _World()
    first, second = await w.rule("armed"), await w.rule("armed", (B,))
    simulating = await w.rule("simulate")
    assert await w.mgr.kill_all("global", "kill_switch") == (first, second)
    for rid in (first, second):
        row = await w.row(rid)
        assert (row.mode, row.disabled_reason, row.armed_by) == ("disabled", "kill_switched", None)
        assert w.mgr.lifecycle.leaf(rid) == "kill_switched"
    assert (await w.row(simulating)).mode == "simulate"
    assert [(event, p["rule_id"]) for event, p in w.audits] == [
        ("rule.kill_switched", first), ("rule.kill_switched", second),
    ]  # fmt: skip
    for _, payload in w.audits:
        assert "actor" not in payload  # no actor: `system` files it
        assert (payload["reason"], payload["b9_event"], payload["b9_from"], payload["b9_to"]) == (
            "kill_switch", "KILL", "armed", "kill_switched",
        )  # fmt: skip
    assert w.stopped == [(first, "kill_switch"), (second, "kill_switch")]
    assert await w.mgr.kill_all("global", "kill_switch") == ()  # none armed is left


async def test_kill_all_reaches_every_rule_that_can_act_on_an_engaged_account() -> None:
    """BQ-9: a switch engaged on A reaches a rule whose scope names A, one whose scope names no
    account, and one with an action targeting `all_accounts`; never one that can only act on B."""
    w = _World()
    on_a, on_b, anywhere = (
        await w.rule("armed"),
        await w.rule("armed", (B,)),
        await w.rule("armed", ()),
    )
    wide = await w.rule("armed", (B,), targets="all_accounts")
    moved = await w.mgr.kill_all(frozenset({A}), "kill_switch")
    assert set(moved) == {on_a, anywhere, wide}
    assert (await w.row(on_b)).mode == "armed"


async def test_kill_all_drops_the_rules_queued_fires_as_kill_switch(rig: DispatchRig) -> None:
    """The moved rule's waiting fires leave its lane at once, each recorded refused whole through
    the audit queue: its run row closed `aborted`, and per action `action_fail` and `rules.blocked`
    with `kill_switch`. The fire that runs is never touched (its next action finds the row no
    longer armed), nor another rule's lane."""
    rid = await rig.add("armed", actions=_actions("a1", "a2"))
    other = await rig.add("armed", accounts=(B,), actions=_actions("b1"))
    rig.sink.gate(rid)
    for _ in range(3):
        await rig.fire()  # the rule's first fire is held in the sink; its next two wait
    await rig.sink.until(lambda: any(r.rule_id == rid for r in rig.sink.entered))
    assert rig.dispatch.queued >= 2
    assert await rig.mgr.kill_all(frozenset({A}), "kill_switch") == (rid,)
    assert not rig.dispatch._lanes.get(rid)  # at once, while the rule's first fire still runs
    rig.sink.release(rid)
    await rig.settle()
    runs = {r: [e for run, e in rig.records.events if run == r] for r in rig.records.runs}
    dropped = [run for run, events in runs.items() if events and all(
        e.payload.get("blocked_by") == "kill_switch" for e in events)]  # fmt: skip
    assert len(dropped) == 2
    for run in dropped:
        assert rig.records.closed[run][0] == "aborted"
        assert [e.payload["node_id"] for e in runs[run]] == ["a1", "a2"]
    blocked = [
        (f.run_id, f.blocked_by) for verb, f in rig.records.audits if verb == "rules.blocked"
    ]
    assert [why for run, why in blocked if run in dropped] == ["kill_switch"] * 4
    held = [r for r in rig.sink.entered if r.rule_id == rid]
    assert [r.payload.node_id for r in held] == ["a1"]  # the running fire's a2 met the moved row
    assert rig.counted.blocked()["kill_switch"] == 4
    assert {r.rule_id for r in rig.sink.left} >= {other}  # the other rule's lane ran on
    assert (await rig.row(other)).mode == "armed"


async def test_a_fire_offered_before_the_kill_is_blocked_at_dispatch() -> None:
    """24 §11.5: a fire offered before its rule's kill time is refused whole at dispatch
    (`kill_switch`), its run row closed `aborted`, even if the rule was re-armed meanwhile; one
    offered after runs its checks."""
    gated = Gated()
    gated.halts.killed[RULE] = 50.0
    await gated.run(action("a1", on_error="continue"), action("a2"), offered_at=40.0)
    assert gated.results() == [("a1", "blocked", "kill_switch"), ("a2", "blocked", "kill_switch")]
    assert gated.checked == [] and gated.sent == []
    assert next(iter(gated.records.closed.values()))[0] == "aborted"
    assert gated.counted.blocked() == {"kill_switch": 2}  # recorded and counted (R1C2-05)
    later = Gated()
    later.halts.killed[RULE] = 50.0
    await later.run(action("a1"), offered_at=60.0)
    assert later.results() == [("a1", "ok", None)]


async def test_a_failed_kill_move_leaves_the_rule_blocked_by_check_three() -> None:
    """A move that fails (its record cannot be written) is logged and counted, and the rule stays
    armed with no fire dropped; while the switch is engaged, check 3 blocks each of its actions."""
    w = _World(failing="rule.kill_switched")
    rid = await w.rule("armed")
    with capture_logs() as logs:
        assert await w.mgr.kill_all("global", "kill_switch") == ()
    assert w.mgr.kill_moves_failed_total == 1 and w.stopped == []
    assert [(e["event"], e["rule_id"], e["error"]) for e in logs if e["log_level"] == "error"] == [
        ("rules.kill_move_failed", rid, "ConnectionError")
    ]
    assert (await w.row(rid)).mode == "armed"
    gated = Gated(Switches(engaged={None}))
    await gated.run(action("a1", on_error="continue"), action("a2", "send_notification"))
    assert gated.results() == [("a1", "blocked", "kill_switch"), ("a2", "blocked", "kill_switch")]
    assert gated.sent == []


async def test_kill_all_reads_the_rules_under_the_bound_of_each_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """24 §11.7 (R1C2-07): the hook reads the rules under the same bound as each move: a read
    that hangs raises `TimeoutError` to its caller, and no rule is moved; check 3 holds them."""
    monkeypatch.setattr(manager_module, "STOP_TIMEOUT_S", 0.0)
    w = _World()
    rid = await w.rule("armed")
    never = asyncio.Event()

    async def hanging() -> list[RuleRow]:
        await never.wait()
        return []

    monkeypatch.setattr(w.store, "all", hanging)
    async with asyncio.timeout(5):  # a guard: an unbounded read never returns
        with pytest.raises(TimeoutError):
            await w.mgr.kill_all("global", "kill_switch")
    assert (await w.row(rid)).mode == "armed" and w.stopped == [] and w.audits == []


@pytest.mark.parametrize("scope", ["global", frozenset({B})])
async def test_kill_all_moves_no_rule_that_is_not_armed(scope: Any) -> None:
    w = _World()
    rid = await w.rule("simulate", (B,))
    assert await w.mgr.kill_all(scope, "kill_switch") == () and w.audits == []
    assert (await w.row(rid)).mode == "simulate"
