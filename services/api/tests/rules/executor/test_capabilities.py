"""E35-T13 (#5005) slice 4b: the actions that cannot run yet (24 §11.5; BQ-10 of #5005, BQ-13 of
#863).

The validator reads each type's state from the handler table's static `waits_for` column, so the
warning is the same in every process and before any start; arming answers `safety_warning_open`
while one is open; and at dispatch check 2 blocks the type `unavailable`, no handler being bound to
a type the column names as waiting.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from candleviewer.rules.executor.gates import Gates
from candleviewer.rules.executor.handlers import (
    HANDLERS,
    Capability,
    HandlerAnswer,
    HandlerTableError,
    Prepared,
    bind_handlers,
)
from candleviewer.rules.ir.models import Rule
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleError, RulesManager
from candleviewer.rules.service import OWN_TYPES, RulesService
from candleviewer.rules.validator import validate_rule
from candleviewer.rules.vocabulary import default_registry
from tests.rules.executor.engine_rig import EngineRig, act, engine
from tests.rules.executor.request_builders import Switches

#: 24 §11.5 "Actions that cannot run yet", and what each names (BQ-10 of #5005).
WAITING = {
    "reverse_position": "a rule handler over the reverse-position operation",
    "move_to_breakeven": "the position stop-loss operation (setPositionTpSl) to be mounted",
    "halt_new_orders": "the account lockouts of E39",
    "resume_new_orders": "the account lockouts of E39",
    "reduce_leverage": "a leverage operation",
    "arm_chase_limit": "the order algorithms of E33",
    "start_iceberg_slice": "the order algorithms of E33",
    "start_twap": "the order algorithms of E33",
}
_PARAMS: dict[str, dict[str, Any]] = {
    "halt_new_orders": {"scope": "account", "until": "manual"},
    "send_notification": {"channel": "ui", "severity": "info", "template": "x"},
}
__all__ = ["engine"]  # the rig's fixture, used by name
FIXTURE = Path(__file__).parents[2] / "fixtures/rule_ir/form_simple_0.json"
OWNER = uuid.UUID(int=1)
ACTOR = Actor(str(OWNER), "s1", frozenset({"rules:arm_live", "orders:write"}), is_owner=True,
              step_up_fresh=True)  # fmt: skip


def _rule(*types: str) -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["actions"] = [
        {"node_id": f"a{n}", "type": t, "params": _PARAMS.get(t, {})} for n, t in enumerate(types)
    ]
    raw["limits"] = {"cooldown_ms": 1000}
    raw["name"] = "-".join(types)
    return raw


class _Bound:
    capability: Capability = "lockouts"

    def prepare(self, req: Any, account_id: Any, *, max_notional_usd: Any = None) -> Prepared:
        raise AssertionError("never reached")

    async def send(self, prepared: Prepared, *, client_ref: str) -> HandlerAnswer:
        raise AssertionError("never reached")


async def test_unavailable_action_blocks_arming_with_a_safety_warning() -> None:
    """Scenario: Unavailable actions are refused at arming and blocked at dispatch (BQ-13). Each
    action whose operation has not shipped raises the safety-class warning `action_unavailable`,
    which saving tolerates and arming refuses as any open safety warning (`safety_warning_open`);
    the same rule without it arms."""
    registry = default_registry()
    for action_type in WAITING:
        result = validate_rule(
            Rule.model_validate(_rule("send_notification", action_type)), registry
        )
        (warning,) = [w for w in result.warnings if w.code == "action_unavailable"]
        assert (warning.severity, warning.klass, warning.path) == (
            "warning",
            "safety",
            "actions[1].type",
        )
        assert result.valid and result.blocks_arming, action_type
    manager = RulesManager(InMemoryRuleStore(), registry)
    ready = await _simulated(manager, _rule("send_notification"))
    waiting = await _simulated(manager, _rule("send_notification", "halt_new_orders"))
    with pytest.raises(RuleError) as refused:
        await manager.set_mode(waiting, "armed", ACTOR, "k1")
    assert (refused.value.status, refused.value.code) == (422, "safety_warning_open")
    assert (await manager.set_mode(ready, "armed", ACTOR, "k2"))["mode"] == "armed"
    await manager.stop()


async def _simulated(manager: RulesManager, raw: dict[str, Any]) -> str:
    """A rule in `simulate` with its simulation evidence on its current version."""
    rid = str((await manager.create(raw, ACTOR))["id"])
    await manager.set_mode(rid, "simulate", ACTOR, f"s-{rid}")
    row = await manager._row(rid)
    row.simulated_hashes, row.simulation_fires = {row.versions[0].ir_hash}, 5
    return rid


async def test_unavailable_action_blocks_at_dispatch(engine: EngineRig) -> None:
    """Scenario: Unavailable actions are refused at arming and blocked at dispatch (BQ-13). An
    armed fire of each, through the engine's own table (the rollout port on), is blocked
    `unavailable` at check 2, none sent; and no handler binds to one, through the table or the
    service's seam, while the column says it waits."""
    actions = [
        {**act(f"a{n}", t, **_PARAMS.get(t, {})), "on_error": "continue"}
        for n, t in enumerate(WAITING)
    ]
    rid = await engine.add(actions=actions)
    await engine.fire()
    await engine.settle()
    assert engine.results(rid) == [(t, "blocked", "unavailable") for t in WAITING]
    assert engine.counted.blocked() == {"unavailable": float(len(WAITING))}
    gates = Gates(switches=Switches(rollout=True))
    for action_type in WAITING:
        spec = HANDLERS[action_type]
        assert gates.before_scope(spec, None, stand_in=True) == "unavailable"
        with pytest.raises(HandlerTableError, match=action_type):
            bind_handlers(HANDLERS, {action_type: _Bound()})
    with pytest.raises(HandlerTableError, match="halt_new_orders"):
        RulesService().bind(handlers={"halt_new_orders": _Bound()})


def test_each_unavailable_action_names_what_it_waits_for() -> None:
    """BQ-10 of #5005: the unavailable set is 24 §11.5's, each naming the missing piece in place of
    the closed #915; every other type (the engine's own, and E35-T11's and E35-T12's, which their
    slices bind) raises no warning."""
    waits = {t: spec.waits_for for t, spec in HANDLERS.items() if spec.waits_for is not None}
    assert waits == WAITING
    registry = default_registry()
    for action_type, piece in WAITING.items():
        result = validate_rule(Rule.model_validate(_rule(action_type)), registry)
        (warning,) = [w for w in result.warnings if w.code == "action_unavailable"]
        assert warning.message.endswith(f"it waits for {piece}.") and "#915" not in warning.message
    for action_type in ("place_order", "scale_out", "modify_stop_loss", "tighten_stop", *OWN_TYPES):
        assert HANDLERS[action_type].waits_for is None, action_type


def test_the_engines_own_types_are_never_bound_by_the_composition_root() -> None:
    """BQ-2 of #5005: `bind(handlers=...)` takes the types that reach past the engine; the engine
    binds its own (`OWN_TYPES`) as it starts, so a second binding of one is refused."""

    class _Signals(_Bound):
        capability: Capability = "signals"

    with pytest.raises(HandlerTableError, match="emit_signal"):
        RulesService().bind(handlers={"emit_signal": _Signals()})
    assert OWN_TYPES == {
        "emit_signal",
        "set_variable",
        "pause_rule",
        "enable_rule",
        "log_journal_tag",
    }
