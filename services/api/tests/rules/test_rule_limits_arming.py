"""#3232 slice B: a rule's action budget at arming, and rules armed above a cap before it existed.

Arming (`set_mode` to `armed`, the re-arm after a kill included) holds the active version to the
budget again, synchronously and before the B9 chart is consulted (C-2.21). A value above its
`RuleLimits` default needs the arming actor to be the Owner, whoever saved the version (decision
5: `403 forbidden`, audited ahead); a value above its hard cap is `422 rule_invalid` for every
role. A rule armed above a cap before the caps existed is never clamped: the runner skips it, and
the first time it is presented (read or evaluated) B9 disarms it with an audited reason (decision
9). The versions here are written to the store as if saved before the caps: no save path takes
them now.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.rules import manager as rules_manager
from candleviewer.rules.arming import ArmingFacts, Refusal, check_arming
from candleviewer.rules.ir import Rule, ir_hash
from candleviewer.rules.limits import BUDGET_FIELDS, LIMIT_CAPS, LIMIT_DEFAULTS
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleError, RulesManager
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_rules_routes import _Env, _ir

ACC_A = "00000000-0000-4000-8000-0000000000a1"
ACC_B = "00000000-0000-4000-8000-0000000000b2"
ON_A = {"level": "account", "account_ids": [ACC_A]}
ON_B = {"level": "account", "account_ids": [ACC_B]}
OWNER = Actor("u-owner", "s-owner", is_owner=True)
MANAGER = Actor("u-mgr", "s-mgr", frozenset({"rules:write"}), frozenset({ACC_A}))
HOUR, DAY = BUDGET_FIELDS
Audits = list[tuple[str, dict[str, Any]]]


class _Recorder:
    def __init__(self) -> None:
        self.audits: Audits = []
        self.broadcasts: list[dict[str, Any]] = []

    async def audit(self, action: str, payload: dict[str, Any]) -> None:
        self.audits.append((action, payload))

    async def broadcast(self, payload: dict[str, Any]) -> None:
        self.broadcasts.append(payload)


class _StepUps:
    """A one-shot step-up grant that counts how often an arm consumed it."""

    def __init__(self) -> None:
        self.used = 0

    async def __call__(self) -> bool:
        self.used += 1
        return True


def _mgr() -> tuple[RulesManager, _Recorder]:
    rec = _Recorder()
    store = InMemoryRuleStore()
    m = RulesManager(store, default_registry(), audit=rec.audit, broadcast=rec.broadcast)
    return m, rec


async def _seed(
    m: RulesManager,
    rec: _Recorder,
    field: str,
    value: int,
    *,
    mode: str = "simulate",
    reason: str | None = None,
    scope: dict[str, Any] = ON_A,
    name: str = "form0",
) -> str:
    """A rule saved by the Owner whose active version holds `field` at `value`, simulated on its
    `ir_hash` and left in `mode`; nothing is audited or broadcast for it."""
    rid = str((await m.create(_ir(name=name, scope=dict(scope)), OWNER))["id"])
    row = await m._s.get(rid)
    assert row is not None
    version = row.versions[0]
    version.ir["limits"][field] = value
    version.ir_hash = ir_hash(Rule.model_validate(version.ir))
    row.simulated_hashes, row.simulation_fires = {version.ir_hash}, 5
    row.mode, row.disabled_reason = mode, reason
    rec.audits.clear()
    rec.broadcasts.clear()
    return rid


def _facts(**kw: Any) -> ArmingFacts:
    base: dict[str, Any] = {
        "has_valid_active_version": True,
        "validation_errors": 0,
        "open_safety_warnings": 0,
        "simulated_on_ir_hash": True,
        "simulation_fires": 5,
        "simulation_hours": 0.0,
        "environments": ("demo",),
        "sends_orders": False,
        "has_flatten_all": False,
    }
    return ArmingFacts(**{**base, **kw})


def test_check_arming_refuses_a_raised_budget_after_the_promotion_gate_unless_owner() -> None:
    raised = {"limits_above_default": (DAY,)}
    gate = check_arming(_facts(simulation_fires=0, **raised))
    assert gate is not None and gate.code == "promotion_gate"
    assert check_arming(_facts(sends_orders=True, **raised)) == Refusal(
        "forbidden",
        403,
        "Only the Owner can arm a rule whose action budget is above the default.",
        (DAY,),
    )
    assert check_arming(_facts(is_owner=True, **raised)) is None


async def test_arm_manager_above_default_version_is_403_audited_and_chart_untouched() -> None:
    """Decision 5: the Owner saved the version, and it is the arming actor who must be the Owner."""
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_DEFAULTS[HOUR] + 1)
    with pytest.raises(RuleError) as refused:
        await m.set_mode(rid, "armed", MANAGER, "arm")
    assert (refused.value.status, refused.value.code) == (403, "forbidden")
    (error,) = refused.value.extra["errors"]
    assert (error["field"], error["rule"]) == (
        "limits.max_fires_per_hour",
        "owner_only_above_default",
    )
    record = {"rule_id": rid, "from": "simulate", "to": "armed", "code": "forbidden"}
    assert rec.audits == [("rule.mode_refused", record | {"actor": MANAGER.user_id})]
    assert m.lifecycle.leaf(rid) == "simulating" and rec.broadcasts == []
    assert (await m.get(rid, OWNER))["mode"] == "simulate"


async def test_arm_owner_above_default_version_is_armed_and_audits_the_values() -> None:
    m, rec = _mgr()
    rid = await _seed(m, rec, DAY, LIMIT_CAPS[DAY])
    assert (await m.set_mode(rid, "armed", OWNER, "arm"))["mode"] == "armed"
    assert m.lifecycle.leaf(rid) == "armed"
    (armed,) = [p for a, p in rec.audits if a == "rule.armed"]
    assert armed["limits_above_default"] == {
        DAY: {"default": LIMIT_DEFAULTS[DAY], "value": LIMIT_CAPS[DAY]}
    }
    assert "limits_above_default" not in rec.broadcasts[-1]  # the `rules` frame keeps its shape


@pytest.mark.parametrize("actor", [OWNER, MANAGER], ids=["owner", "manager"])
async def test_arm_above_cap_version_is_422_rule_invalid_for_every_role(actor: Actor) -> None:
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR] + 1)
    with pytest.raises(RuleError) as refused:
        await m.set_mode(rid, "armed", actor, "arm")
    assert (refused.value.status, refused.value.code) == (422, "rule_invalid")
    assert [(a, p["code"], p["actor"]) for a, p in rec.audits] == [
        ("rule.mode_refused", "rule_invalid", actor.user_id)
    ]
    assert m.lifecycle.leaf(rid) == "simulating"


_BOUNDS = {"default": (LIMIT_DEFAULTS, 0), "above_default": (LIMIT_DEFAULTS, 1)}
_BOUNDS |= {"cap": (LIMIT_CAPS, 0), "above_cap": (LIMIT_CAPS, 1)}


def _at(bound: str, field: str) -> int:
    base, step = _BOUNDS[bound]
    return base[field] + step


@pytest.mark.parametrize("field", BUDGET_FIELDS)
@pytest.mark.parametrize(
    ("bound", "actor"), [("default", MANAGER), ("cap", OWNER)], ids=["manager", "owner"]
)
async def test_arming_exactly_at_a_boundary_is_allowed(
    field: str, bound: str, actor: Actor
) -> None:
    m, rec = _mgr()
    rid = await _seed(m, rec, field, _at(bound, field))
    assert (await m.set_mode(rid, "armed", actor, "arm"))["mode"] == "armed"


@pytest.mark.parametrize("field", BUDGET_FIELDS)
@pytest.mark.parametrize(
    ("bound", "actor", "code"),
    [
        ("above_default", MANAGER, "forbidden"),
        ("cap", MANAGER, "forbidden"),
        ("above_cap", OWNER, "rule_invalid"),
    ],
    ids=["above_default-manager", "cap-manager", "above_cap-owner"],
)
async def test_arming_past_a_boundary_is_refused(
    field: str, bound: str, actor: Actor, code: str
) -> None:
    m, rec = _mgr()
    rid = await _seed(m, rec, field, _at(bound, field))
    with pytest.raises(RuleError) as refused:
        await m.set_mode(rid, "armed", actor, "arm")
    assert refused.value.code == code


async def test_rearm_after_a_kill_holds_the_version_to_the_budget() -> None:
    """HUMAN_REARM runs the same check: a refused re-arm spends no step-up and stays killed."""
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR], mode="disabled", reason="kill_switched")
    mine, owners = _StepUps(), _StepUps()
    manager = Actor("u-mgr", "s-mgr", MANAGER.perms, MANAGER.granted_accounts, consume_step_up=mine)
    with pytest.raises(RuleError) as refused:
        await m.set_mode(rid, "armed", manager, "rearm-1")
    assert (refused.value.status, refused.value.code) == (403, "forbidden")
    assert mine.used == 0 and m.lifecycle.leaf(rid) == "kill_switched"
    owner = Actor("u-owner", "s-owner", is_owner=True, consume_step_up=owners)
    await m.set_mode(rid, "armed", owner, "rearm-2")
    assert owners.used == 1 and m.lifecycle.leaf(rid) == "armed"
    assert [a for a, _ in rec.audits] == ["rule.mode_refused", "rule.armed"]
    armed = rec.audits[-1][1]
    assert armed["b9_event"] == "HUMAN_REARM"
    assert armed["limits_above_default"] == {
        HOUR: {"default": LIMIT_DEFAULTS[HOUR], "value": LIMIT_CAPS[HOUR]}
    }


async def test_rearm_after_a_kill_above_the_cap_is_422_and_stays_killed() -> None:
    m, rec = _mgr()
    rid = await _seed(m, rec, DAY, LIMIT_CAPS[DAY] + 1, mode="disabled", reason="kill_switched")
    owners = _StepUps()
    with pytest.raises(RuleError) as refused:
        await m.set_mode(
            rid, "armed", Actor("u-owner", "s", is_owner=True, consume_step_up=owners), "r"
        )
    assert (refused.value.status, refused.value.code) == (422, "rule_invalid")
    assert owners.used == 0 and m.lifecycle.leaf(rid) == "kill_switched"


async def test_arming_an_unseen_owner_rule_is_404_before_any_limits_refusal() -> None:
    """04 §7.3 / RE-I5: a Manager granted account A cannot arm, or learn of, a rule on B."""
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR] + 1, scope=ON_B)
    with pytest.raises(RuleError) as refused:
        await m.set_mode(rid, "armed", MANAGER, "arm")
    assert (refused.value.status, refused.value.code) == (404, "not_found")
    assert [(a, p["reason"]) for a, p in rec.audits] == [("rule.scope_refused", "rule_not_visible")]
    assert m.lifecycle.leaf(rid) is None  # the chart was never consulted


async def test_evaluable_rules_skips_and_disarms_an_armed_rule_above_the_cap() -> None:
    m, rec = _mgr()
    rid = await _seed(m, rec, DAY, LIMIT_CAPS[DAY] + 1, mode="armed")
    kept = await _seed(m, rec, DAY, LIMIT_DEFAULTS[DAY], mode="armed", name="kept")
    assert [str(r.rule_id) for r in await m.evaluable_rules()] == [kept]
    over = {DAY: {"cap": LIMIT_CAPS[DAY], "value": LIMIT_CAPS[DAY] + 1}}
    sent = {"rule_id": rid, "mode": "disabled", "from": "armed", "b9_from": "armed"}
    sent |= {"b9_event": "DISARM", "reason": "limits_above_cap"}
    assert rec.audits == [("rule.disarmed", sent | {"limits_above_cap": over, "b9_to": "disarmed"})]
    assert rec.broadcasts == [{"topic": "rules", **sent}]
    row = await m._s.get(rid)
    assert row is not None and (row.mode, row.disabled_reason) == ("disabled", "disarmed")
    assert [str(r.rule_id) for r in await m.evaluable_rules()] == [kept]
    assert len(rec.audits) == 1  # disarmed once, never clamped and re-run


async def test_reading_an_armed_rule_above_the_cap_disarms_it_once_with_its_reason() -> None:
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR] + 1, mode="armed")
    assert (await m.get(rid, OWNER))["mode"] == "disabled"
    assert [r["mode"] for r in (await m.list_rules(OWNER))["items"]] == ["disabled"]
    assert [(a, p["reason"], p["b9_to"]) for a, p in rec.audits] == [
        ("rule.disarmed", "limits_above_cap", "disarmed")
    ]
    assert rec.audits[0][1]["limits_above_cap"] == {
        HOUR: {"cap": LIMIT_CAPS[HOUR], "value": LIMIT_CAPS[HOUR] + 1}
    }
    assert m.lifecycle.leaf(rid) == "disarmed"


async def test_reading_a_corrupt_armed_rule_still_disarms_it_as_quarantined() -> None:
    """The quarantine disarm shares the helper and keeps its record: reason, no cap member."""
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR] + 1, mode="armed")
    row = await m._s.get(rid)
    assert row is not None
    row.versions[0].ir["conditions"] = {"bogus": 1}
    assert (await m.get(rid, OWNER))["quarantined"] is True
    (disarmed,) = rec.audits
    assert disarmed[0] == "rule.disarmed" and disarmed[1]["reason"] == "quarantined"
    assert "limits_above_cap" not in disarmed[1]


async def test_an_armed_rule_above_the_default_but_under_the_cap_keeps_running() -> None:
    """Decision 9's accepted residual: armed by a Manager before the caps, it runs until it is
    re-armed."""
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR], mode="armed")
    assert [str(r.rule_id) for r in await m.evaluable_rules()] == [rid]
    assert (await m.get(rid, MANAGER))["mode"] == "armed"
    assert rec.audits == []


async def test_a_disarm_that_fails_on_a_tick_still_skips_the_rule_and_is_retried() -> None:
    """Fail closed per rule: the runner never gets the rule, the loss is logged, the row stays
    armed (nothing recorded) and the next tick disarms it."""
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR] + 1, mode="armed")

    async def down(_action: str, _payload: dict[str, Any]) -> None:
        raise RuntimeError("audit down")

    m.set_hooks(audit=down)
    with capture_logs() as logs:
        assert await m.evaluable_rules() == []
    failed = [e for e in logs if e["log_level"] == "error"]
    assert [(e["event"], e["rule_id"], e["error"]) for e in failed] == [
        ("rules.limits_disarm_failed", rid, "RuntimeError")
    ]
    row = await m._s.get(rid)
    assert row is not None and row.mode == "armed" and rec.broadcasts == []
    m.set_hooks(audit=rec.audit)
    assert await m.evaluable_rules() == []
    assert row.mode == "disabled" and [a for a, _ in rec.audits] == ["rule.disarmed"]


async def _stalled(_action: str, _payload: dict[str, Any]) -> None:
    """Never answers: a bound of 0 s ends it at its first yield; unbounded, it fails the test."""
    for _ in range(100):
        await asyncio.sleep(0)
    raise AssertionError("the disarm was not bounded")


async def test_a_disarm_that_stalls_on_a_tick_is_bounded_and_the_rule_still_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stalled audit writer cannot hold the runner: the tick gives up at the bound."""
    m, rec = _mgr()
    rid = await _seed(m, rec, DAY, LIMIT_CAPS[DAY] + 1, mode="armed")
    m.set_hooks(audit=_stalled)
    monkeypatch.setattr(rules_manager, "TICK_DISARM_TIMEOUT_S", 0.0)
    with capture_logs() as logs:
        assert await m.evaluable_rules() == []
    assert [e["error"] for e in logs if e["log_level"] == "error"] == ["TimeoutError"]
    row = await m._s.get(rid)
    assert row is not None and row.mode == "armed"


def test_put_mode_armed_above_the_default_is_a_403_forbidden_problem_for_a_manager() -> None:
    owner = _Env()
    manager = _Env({"rules:read", "rules:write"}, owner=False, mgr=owner.mgr)
    rid = owner.create(limits={HOUR: LIMIT_CAPS[HOUR]})
    owner.ready(rid)
    r = manager.mode(rid, "armed", "arm")
    assert (r.status_code, r.headers["content-type"]) == (403, "application/problem+json")
    body = r.json()
    assert (body["code"], body["detail"]) == (
        "forbidden",
        "Only the Owner can arm a rule whose action budget is above the default.",
    )
    assert [(x["field"], x["rule"]) for x in body["errors"]] == [
        ("limits.max_fires_per_hour", "owner_only_above_default")
    ]
    assert owner.c.get(f"/rules/{rid}").json()["mode"] == "simulate"
    assert owner.mode(rid, "armed", "arm-owner").json()["mode"] == "armed"


def test_put_mode_armed_above_the_cap_is_a_422_rule_invalid_problem() -> None:
    e = _Env()
    rid = e.create(limits={DAY: LIMIT_CAPS[DAY]})
    e.ready(rid)
    row = e.mgr._s._rows[rid]  # type: ignore[attr-defined]  # stored before the caps existed
    row.versions[0].ir["limits"][DAY] = LIMIT_CAPS[DAY] + 1
    row.versions[0].ir_hash = ir_hash(Rule.model_validate(row.versions[0].ir))
    row.simulated_hashes.add(row.versions[0].ir_hash)
    r = e.mode(rid, "armed", "arm")
    assert (r.status_code, r.json()["code"]) == (422, "rule_invalid")
    assert e.c.get(f"/rules/{rid}").json()["mode"] == "simulate"
