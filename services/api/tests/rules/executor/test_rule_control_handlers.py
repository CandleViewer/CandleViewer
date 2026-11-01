"""E35-T13 (#5005) slice 4b: `pause_rule` and `enable_rule` (24 §11.5 "Rule control"; RE-E7,
E35-FR-17; BQ-7 of #5005, BQ-13 of #863).

Each runs through `EngineRig`: an armed rule's fire, the real executor and checks, the engine's own
`RuleControlHandler` and the manager's system path, B9 itself deciding which state takes which
event (no B9 change). A target the move does not reach is `skipped`, its `blocked_detail` the
reason; a move is recorded under the acting rule as its actor. No action here names an account,
sends an order or reaches a stop: the runs hold no order and the stop check is never asked.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from candleviewer.rules.executor import control as control_module
from candleviewer.rules.executor.control import (
    CONTROL_DETAIL,
    ControlRequest,
    ControlSkip,
    RuleControlHandler,
)
from candleviewer.rules.executor.results import BLOCKED_DETAIL
from candleviewer.rules.ir.models import Action, Rule, RuleScope
from candleviewer.rules.manager import _CONTROL_MOVES
from candleviewer.rules.scope import ScopeInstanceRef
from candleviewer.rules.validator import validate_rule
from candleviewer.rules.vocabulary import default_registry
from tests.rules.executor.engine_rig import OTHER, EngineRig, act, engine, set_var
from tests.rules.executor.request_builders import action_request
from tests.rules.test_scope_wiring import OWNER

__all__ = ["engine"]  # the rig's fixture, used by name


def _detail(skip: ControlSkip) -> str:
    return CONTROL_DETAIL[skip]


async def _target(engine: EngineRig, mode: str, *, owner: uuid.UUID = OWNER, **over: Any) -> str:
    """A rule to act on, its row in `mode`; `disabled_reason` (`draft` when absent) and the B9
    leaf as the row projects them."""
    rid = await engine.add(mode, actions=[set_var("t1", "x")], owner=owner)
    row = await engine.row(rid)
    for name, value in over.items():
        setattr(row, name, value)
    return rid


async def _leaf(engine: EngineRig, rid: str) -> str:
    row = await engine.row(rid)
    return await engine.mgr.lifecycle.current(rid, row.mode, row.disabled_reason)


def _moves(engine: EngineRig) -> list[tuple[str, str, str]]:
    """`(event, target, reason)` of each move the manager recorded."""
    return [(e, p["rule_id"], p["reason"]) for e, p in engine.audits if "rule_actor" in p]


async def test_pause_rule_may_pause_itself(engine: EngineRig) -> None:
    """Scenario: pause_rule disarms through B9 or is skipped (BQ-13). A rule pauses itself: B9
    `DISARM` from `armed`, recorded `rule.disarmed` with the reason `pause_rule` under the actor
    `rule:<rule_id>@v1`, before its row; the rest of its fire then finds the row no longer armed
    and is skipped. A pause touches no position: no order, no stop asked."""
    rid = await engine.add(
        actions=[act("p1", "pause_rule", rule_id="placeholder"), set_var("v1", "after")]
    )
    (await engine.row(rid)).versions[0].ir["actions"][0]["params"] = {"rule_id": rid}
    await engine.fire()
    await engine.settle()
    row = await engine.row(rid)
    assert (row.mode, row.disabled_reason, row.armed_by) == ("disabled", "disarmed", None)
    assert engine.mgr.lifecycle.leaf(rid) == "disarmed"
    assert engine.results(rid) == [
        ("pause_rule", "ok", None), ("set_variable", "skipped", "mode_changed"),
    ]  # fmt: skip
    ((event, payload),) = [(e, p) for e, p in engine.audits if "rule_actor" in p]
    assert (event, payload["reason"], payload["b9_event"]) == (
        "rule.disarmed",
        "pause_rule",
        "DISARM",
    )
    assert (payload["rule_actor"], payload["actor_type"]) == (f"rule:{rid}@v1", "rule")
    assert (payload["owner_user_id"], payload["armed_by_user_id"]) == (str(OWNER), str(OWNER))
    assert {payload["run_id"], payload["node_id"]} == {str(next(iter(engine.records.runs))), "p1"}
    assert "actor" not in payload  # never a user id
    assert engine.stops.asked == [] and engine.outbox.writes == 0  # no stop asked, nothing sent
    assert all(e.payload["action_type"] in ("pause_rule", "set_variable")
               for _, e in engine.records.events)  # fmt: skip


async def test_pause_rule_disarms_another_rule_from_each_state_that_takes_disarm(
    engine: EngineRig,
) -> None:
    """B9 takes `DISARM` from `armed`, `cooling_down` and `paused_degraded`: a same-owner target in
    `armed` and one in `paused_degraded` (its feed degraded) are both disarmed."""
    assert _CONTROL_MOVES["pause_rule"][:2] == (
        "DISARM", frozenset({"armed", "cooling_down", "paused_degraded"}),
    )  # fmt: skip
    armed = await _target(engine, "armed")
    degraded = await _target(engine, "armed")
    await _leaf(engine, degraded)
    await engine.mgr.lifecycle.send(degraded, "FEED_DEGRADED")
    assert engine.mgr.lifecycle.leaf(degraded) == "paused_degraded"
    pauser = await engine.add(
        actions=[act("p1", "pause_rule", rule_id=armed), act("p2", "pause_rule", rule_id=degraded)]
    )
    await engine.fire()
    await engine.settle()
    assert engine.results(pauser) == [("pause_rule", "ok", None)] * 2
    for rid in (armed, degraded):
        assert (await engine.row(rid)).mode == "disabled"
        assert engine.mgr.lifecycle.leaf(rid) == "disarmed"
    assert _moves(engine) == [
        ("rule.disarmed", armed, "pause_rule"), ("rule.disarmed", degraded, "pause_rule"),
    ]  # fmt: skip


async def test_pause_rule_from_a_state_without_disarm_is_skipped_with_its_reason(
    engine: EngineRig,
) -> None:
    """Scenario: pause_rule disarms through B9 or is skipped (BQ-13). A target in any other state
    (`simulating`, `draft`, `disarmed`, `kill_switched`) is recorded `skipped` with its reason and
    keeps its state: no B9 event, no record."""
    targets = [
        await _target(engine, "simulate"),
        await _target(engine, "disabled"),
        await _target(engine, "disabled", disabled_reason="disarmed"),
        await _target(engine, "disabled", disabled_reason="kill_switched"),
    ]
    before = [await _leaf(engine, rid) for rid in targets]
    assert before == ["simulating", "draft", "disarmed", "kill_switched"]
    pauser = await engine.add(
        actions=[act(f"p{n}", "pause_rule", rule_id=rid) for n, rid in enumerate(targets)]
    )
    await engine.fire()
    await engine.settle()
    assert engine.results(pauser) == [("pause_rule", "skipped", None)] * len(targets)
    details = [
        e.payload["blocked_detail"] for _, e in engine.records.events if e.kind == "action_fail"
    ]
    assert details == [_detail("control_state")] * len(targets)
    assert [await _leaf(engine, rid) for rid in targets] == before and _moves(engine) == []
    assert engine.records.closed[next(iter(engine.records.runs))][0] == "aborted"


async def test_pause_rule_never_reaches_another_owners_rule(engine: EngineRig) -> None:
    """The cross-owner case (C-12.4): another owner's armed rule and a rule id that names no rule
    are skipped alike (`control_not_found`), so the answer never tells them apart; the other
    owner's rule stays armed."""
    theirs = await _target(engine, "armed", owner=OTHER)
    pauser = await engine.add(
        actions=[act("p1", "pause_rule", rule_id=theirs),
                 act("p2", "pause_rule", rule_id=str(uuid.UUID(int=0xDEAD)))]
    )  # fmt: skip
    await engine.fire()
    await engine.settle()
    assert engine.results(pauser) == [("pause_rule", "skipped", None)] * 2
    details = {
        e.payload["blocked_detail"] for _, e in engine.records.events if e.kind == "action_fail"
    }
    assert details == {_detail("control_not_found")}
    assert (await engine.row(theirs)).mode == "armed" and _moves(engine) == []


async def test_pause_rule_never_pauses_a_protected_system_rule(engine: EngineRig) -> None:
    """24 §11.8: `sys.native_sl_watchdog` and `sys.clock_drift_block` cannot be disabled, by a
    rule of their own owner either: skipped (`control_protected`), still armed."""
    watchdog = await _target(engine, "armed", name="sys.native_sl_watchdog")
    drift = await _target(engine, "armed", name="sys.clock_drift_block")
    pauser = await engine.add(
        actions=[act("p1", "pause_rule", rule_id=watchdog), act("p2", "pause_rule", rule_id=drift)]
    )
    await engine.fire()
    await engine.settle()
    assert engine.results(pauser) == [("pause_rule", "skipped", None)] * 2
    for rid in (watchdog, drift):
        assert (await engine.row(rid)).mode == "armed"
    assert _moves(engine) == []
    details = {
        e.payload["blocked_detail"] for _, e in engine.records.events if e.kind == "action_fail"
    }
    assert details == {_detail("control_protected")}


async def test_enable_rule_cannot_arm(engine: EngineRig) -> None:
    """Scenario: enable_rule can never arm (RE-E7, failure case). A same-owner `draft` target
    moves toward `simulate` (B9 `SAVE`), recorded `rule.simulated` with the reason `enable_rule`;
    a target in any other state is skipped (`control_state`) and keeps it; no target is ever
    `armed` after."""
    assert _CONTROL_MOVES["enable_rule"][:3] == ("SAVE", frozenset({"draft"}), "simulate")
    draft = await _target(engine, "disabled")
    others = [
        await _target(engine, "simulate"),
        await _target(engine, "armed"),
        await _target(engine, "disabled", disabled_reason="disarmed"),
        await _target(engine, "disabled", disabled_reason="kill_switched"),
    ]
    targets = [draft, *others]
    enabler = await engine.add(
        actions=[act(f"e{n}", "enable_rule", rule_id=rid) for n, rid in enumerate(targets)]
    )
    before = {rid: (await engine.row(rid)).mode for rid in others}
    await engine.fire()
    await engine.settle()
    assert engine.results(enabler) == [("enable_rule", "ok", None)] + [
        ("enable_rule", "skipped", None)
    ] * len(others)
    assert (await engine.row(draft)).mode == "simulate" and await _leaf(
        engine, draft
    ) == "simulating"
    assert {rid: (await engine.row(rid)).mode for rid in others} == before
    assert _moves(engine) == [("rule.simulated", draft, "enable_rule")]
    armed = [rid for rid in targets if (await engine.row(rid)).mode == "armed"]
    assert armed == [others[1]]  # the one that was armed already, never one enable_rule moved


async def test_enable_rule_self_target_rejected(engine: EngineRig) -> None:
    """Scenario: enable_rule can never arm (RE-E7, failure case); E35-FR-17. A rule naming itself
    is refused at save (`feedback_loop`); one stored past that check is skipped at execution
    (`control_self`), before the manager is asked."""
    rid = await engine.add(actions=[act("e1", "enable_rule", rule_id="placeholder")])
    stored = (await engine.row(rid)).versions[0].ir
    stored["actions"][0]["params"] = {"rule_id": rid}
    issues = validate_rule(Rule.model_validate({**stored, "rule_id": rid}), default_registry())
    assert [i.code for i in issues.errors] == ["feedback_loop"]
    await engine.fire()
    await engine.settle()
    assert engine.results(rid) == [("enable_rule", "skipped", None)]
    (event,) = [e for _, e in engine.records.events if e.kind == "action_fail"]
    assert event.payload["blocked_detail"] == _detail("control_self")
    assert (await engine.row(rid)).mode == "armed" and _moves(engine) == []


async def test_enable_rule_never_crosses_owners(engine: EngineRig) -> None:
    """Scenario: enable_rule can never arm (RE-E7, failure case). The cross-owner case: another
    owner's draft is skipped (`control_not_found`) and stays a draft."""
    theirs = await _target(engine, "disabled", owner=OTHER)
    enabler = await engine.add(actions=[act("e1", "enable_rule", rule_id=theirs)])
    await engine.fire()
    await engine.settle()
    assert engine.results(enabler) == [("enable_rule", "skipped", None)]
    assert await _leaf(engine, theirs) == "draft" and _moves(engine) == []


async def test_enable_rule_of_an_unreadable_draft_is_skipped(engine: EngineRig) -> None:
    """A draft whose active version the engine cannot read is skipped (`control_unreadable`)."""
    draft = await _target(engine, "disabled")
    (await engine.row(draft)).versions[0].ir["conditions"] = {"op": "teleport"}
    enabler = await engine.add(actions=[act("e1", "enable_rule", rule_id=draft)])
    await engine.fire()
    await engine.settle()
    (event,) = [e for _, e in engine.records.events if e.kind == "action_fail"]
    assert event.payload["blocked_detail"] == _detail("control_unreadable")
    assert engine.results(enabler) == [("enable_rule", "skipped", None)]


@pytest.mark.parametrize("disabled", [OWNER, "armer"], ids=["owner-disabled", "armer-disabled"])
async def test_a_control_action_of_a_rule_whose_owner_or_armer_is_disabled_is_blocked(
    engine: EngineRig, disabled: object
) -> None:
    """The forbidden-role case (C-12.4): an action that names no account needs both users active
    (check 5), so a rule whose owner or armer is disabled is blocked (`permission`) before any
    control action: its target never moves, and nothing is recorded as a move."""
    armer = uuid.UUID(int=0xA2)
    target = await _target(engine, "armed")
    pauser = await engine.add(actions=[act("p1", "pause_rule", rule_id=target)])
    (await engine.row(pauser)).armed_by = str(armer)
    user = OWNER if disabled == OWNER else armer
    engine.principals.facts[user] = (False, "manager", False, frozenset())
    await engine.fire()
    await engine.settle()
    assert engine.results(pauser) == [("pause_rule", "blocked", "permission")]
    assert (await engine.row(target)).mode == "armed" and _moves(engine) == []


class _Hanging:
    """A manager whose move never ends: the handler's bound decides."""

    async def control_rule(self, request: ControlRequest) -> ControlSkip | None:
        await asyncio.Event().wait()
        return None


def _control_request(**params: Any) -> Any:
    action = Action.model_validate({"node_id": "p1", "type": "pause_rule", "params": params})
    return action_request(
        RuleScope(level="account"), OWNER, ScopeInstanceRef("*@*", None, None),
        action_type="pause_rule", payload=action,
    )  # fmt: skip


async def test_a_control_move_that_does_not_end_in_its_bound_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The move's bound (2 s; here 0): no answer, `unknown` (`timeout`), the row the truth."""
    monkeypatch.setattr(control_module, "CONTROL_TIMEOUT_S", 0.0)
    handler = RuleControlHandler("pause_rule", _Hanging())
    prepared = handler.prepare(_control_request(rule_id="r2"), None, max_notional_usd=None)
    answer = await handler.send(prepared, client_ref="k")
    assert (answer.answer, answer.error_code) == ("no_answer", "timeout")
    missing = handler.prepare(_control_request(), None, max_notional_usd=None)
    refused = await handler.send(missing, client_ref="k")
    assert (refused.answer, refused.error_code) == ("refused", "invalid_params")


def test_the_control_details_follow_the_blocked_detail_register() -> None:
    """E35-D03's register, as `BLOCKED_DETAIL`'s: one sentence, at most 80 characters, naming the
    condition and never data, and none the same as another's."""
    sentences = list(CONTROL_DETAIL.values())
    for sentence in sentences:
        assert sentence.startswith("Not done — ") and len(sentence) <= 80
        assert sentence.endswith(".") and sentence.count(".") == 1
        assert not any(c.isdigit() for c in sentence)
    assert len(set(sentences)) == len(sentences) and not set(sentences) & set(
        BLOCKED_DETAIL.values()
    )
