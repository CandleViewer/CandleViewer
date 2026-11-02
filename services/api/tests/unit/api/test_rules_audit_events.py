"""E35-T09 (#5000): `make_rules_audit` files each rules-manager event under its registered verb
and refuses any other event before it writes, where it used to file it under
`rules.version_create` (24 §15.5). `rule.fired` and `rule.blocked` are refused here too: they carry
a rule actor and a fire key, which only the executor's records adapter writes."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import pytest

from candleviewer.api.rules_actor import UnknownRuleAuditEvent, make_rules_audit
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.models import AuditOutcome
from candleviewer.rules import manager

#: The manager's twelve events and their verbs, as E35-S01 and E35-X02 mapped them, and E35-T10
#: the kill switch's and the circuit breaker's `rule.kill_switched`.
_VERBS = {
    "rule.armed": "rules.arm", "rule.disarmed": "rules.disarm",
    "rule.created": "rules.version_create", "rule.updated": "rules.version_create",
    "rule.deleted": "rules.delete", "rule.simulated": "rules.simulate",
    "rule.mode_refused": "rules.arm", "rule.system_rule_refused": "rules.scope_denied",
    "rule.system_rule_tampered": "rules.scope_denied", "rule.import_refused": "rules.scope_denied",
    "rule.scope_refused": "rules.scope_denied", "rule.kill_switched": "rules.disarm",
}  # fmt: skip
_REFUSALS = {k for k in _VERBS if k.endswith(("_refused", "_tampered"))}
_ACTOR = str(uuid.UUID(int=0xA1))
#: Every event literal the manager writes through its audit hook.
_WRITTEN = set(re.findall(r'"(rule\.[a-z_]+)"', Path(manager.__file__).read_text("utf-8")))


class _Emitter:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self.records.append((action, fields))


async def test_unknown_rules_audit_event_is_refused() -> None:
    """Scenario: An unknown rules audit event is refused. Nothing is written: the refusal comes
    before the emitter, so no event is filed under `rules.version_create` or any other verb."""
    emitter = _Emitter()
    audit = make_rules_audit(emitter)
    for event in ("create", "rule.fired", "rule.blocked", "rule.renamed", ""):
        with pytest.raises(UnknownRuleAuditEvent) as refused:
            await audit(event, {"rule_id": "r1", "actor": _ACTOR})
        assert refused.value.event == event
    assert emitter.records == []


async def test_every_manager_audit_event_keeps_its_verb() -> None:
    emitter = _Emitter()
    audit = make_rules_audit(emitter)
    for event in _VERBS:
        await audit(event, {"rule_id": "r1", "actor": _ACTOR, "from": "simulate"})
    assert [action for action, _ in emitter.records] == list(_VERBS.values())
    for (_, fields), event in zip(emitter.records, _VERBS, strict=True):
        denied = AuditOutcome.DENIED if event in _REFUSALS else AuditOutcome.SUCCESS
        assert (fields["outcome"], fields["after_state"]["event"]) == (denied, event)
        assert (fields["actor_user_id"], fields["before_state"]) == (_ACTOR, {"mode": "simulate"})
    assert set(_VERBS.values()) <= AUDIT_ACTIONS
    assert _WRITTEN and _WRITTEN <= set(_VERBS)  # every event the manager writes still lands


async def test_rule_kill_switched_is_filed_under_rules_disarm() -> None:
    """24 §15.5 (E35-T10): `rule.kill_switched` is filed under the registered `rules.disarm`, with
    its reason, `kill_switch` or `order_budget`, and no actor, so `system` names it."""
    emitter = _Emitter()
    audit = make_rules_audit(emitter)
    for reason in ("kill_switch", "order_budget"):
        payload = {"rule_id": "r1", "from": "armed", "b9_from": "armed", "reason": reason}
        await audit("rule.kill_switched", payload)
    assert [action for action, _ in emitter.records] == ["rules.disarm"] * 2
    for (_, fields), reason in zip(emitter.records, ("kill_switch", "order_budget"), strict=True):
        assert (fields["actor_label"], fields["actor_user_id"]) == ("system", None)
        assert fields["outcome"] == AuditOutcome.SUCCESS
        assert fields["after_state"] | {} == {
            "rule_id": "r1", "from": "armed", "b9_from": "armed", "reason": reason,
            "event": "rule.kill_switched",
        }  # fmt: skip
    assert "rules.disarm" in AUDIT_ACTIONS


async def test_a_rule_control_move_names_the_rule_as_its_actor() -> None:
    """24 §11.5 (E35-T13): `pause_rule`'s `rule.disarmed` and `enable_rule`'s `rule.simulated`
    name the acting rule as the actor, `rule:<rule_id>@v<n>`, with no user id (04 SR-062); the
    label never rides `after_state`, which keeps the two users' ids, the run and the node."""
    emitter = _Emitter()
    audit = make_rules_audit(emitter)
    armer = str(uuid.UUID(int=0xA2))
    actor = {"rule_actor": "rule:r9@v2", "actor_type": "rule", "owner_user_id": _ACTOR,
             "armed_by_user_id": armer, "run_id": "u1", "node_id": "p1"}  # fmt: skip
    for event, reason in (("rule.disarmed", "pause_rule"), ("rule.simulated", "enable_rule")):
        await audit(event, {"rule_id": "r1", "from": "armed", "reason": reason} | actor)
    assert [action for action, _ in emitter.records] == ["rules.disarm", "rules.simulate"]
    for _, fields in emitter.records:
        assert (fields["actor_label"], fields["actor_user_id"]) == ("rule:r9@v2", None)
        assert fields["object_id"] == "r1" and "rule_actor" not in fields["after_state"]
        after = fields["after_state"]
        assert (after["owner_user_id"], after["armed_by_user_id"]) == (_ACTOR, armer)
