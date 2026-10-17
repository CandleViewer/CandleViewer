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
from collections.abc import Callable, Coroutine
from dataclasses import replace
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.rules import manager as rules_manager
from candleviewer.rules.arming import ArmingFacts, Refusal, check_arming
from candleviewer.rules.ir import Rule, ir_hash
from candleviewer.rules.limits import BUDGET_FIELDS, LIMIT_CAPS, LIMIT_DEFAULTS
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleError, RuleRow, RulesManager
from candleviewer.rules.service import RulesService
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_rule_limits import DAY, HOUR, MANAGER, ON_A, ON_B, OWNER, Audits
from tests.rules.test_rules_manager import _facts
from tests.rules.test_rules_routes import _Env, _ir


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


class _HeldWriter:
    """An audit writer that holds each record until `release` is set."""

    def __init__(self, rec: _Recorder) -> None:
        self.rec = rec
        self.entered, self.release = asyncio.Event(), asyncio.Event()

    async def audit(self, action: str, payload: dict[str, Any]) -> None:
        self.entered.set()
        await self.release.wait()
        await self.rec.audit(action, payload)


def _mgr() -> tuple[RulesManager, _Recorder]:
    rec = _Recorder()
    store = InMemoryRuleStore()
    m = RulesManager(store, default_registry(), audit=rec.audit, broadcast=rec.broadcast)
    return m, rec


async def _settle(m: RulesManager) -> None:
    """Wait for the disarms the evaluator ticks handed off: they run beside the tick (#3232)."""
    await asyncio.gather(*m._tick_disarms.values())


def _tick_disarms() -> list[asyncio.Task[Any]]:
    """The tick disarms still in flight on this loop."""
    return [t for t in asyncio.all_tasks() if t.get_name() == "rule-limits-disarm"]


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


def _facts_raised(**kw: Any) -> ArmingFacts:
    """Arming facts of a version whose daily budget is above its default."""
    return _facts(limits_above_default=(DAY,), **kw)


def test_check_arming_runs_the_promotion_gate_before_the_raised_budget() -> None:
    gate = check_arming(_facts_raised(simulation_fires=0))
    assert gate is not None and gate.code == "promotion_gate"


def test_check_arming_refuses_a_non_owner_a_raised_budget_naming_its_fields() -> None:
    """Ahead of the `orders:write` check, which this rule would also fail."""
    assert check_arming(_facts_raised(sends_orders=True)) == Refusal(
        "forbidden",
        403,
        "Only the Owner can arm a rule whose action budget is above the default.",
        (DAY,),
    )


def test_check_arming_lets_the_owner_arm_a_raised_budget() -> None:
    assert check_arming(_facts_raised(is_owner=True)) is None


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


async def test_rearm_after_a_kill_refuses_a_manager_a_raised_budget_and_spends_no_step_up() -> None:
    """HUMAN_REARM runs the same check, before the chart: the refused re-arm stays killed."""
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR], mode="disabled", reason="kill_switched")
    mine = _StepUps()
    manager = Actor("u-mgr", "s-mgr", MANAGER.perms, MANAGER.granted_accounts, consume_step_up=mine)
    with pytest.raises(RuleError) as refused:
        await m.set_mode(rid, "armed", manager, "rearm")
    assert (refused.value.status, refused.value.code) == (403, "forbidden")
    assert mine.used == 0 and m.lifecycle.leaf(rid) == "kill_switched"


async def test_rearm_after_a_kill_lets_the_owner_arm_a_raised_budget_with_one_step_up() -> None:
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR], mode="disabled", reason="kill_switched")
    owners = _StepUps()
    owner = Actor("u-owner", "s-owner", is_owner=True, consume_step_up=owners)
    await m.set_mode(rid, "armed", owner, "rearm")
    assert owners.used == 1 and m.lifecycle.leaf(rid) == "armed"
    (armed,) = [p for a, p in rec.audits if a == "rule.armed"]
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


async def test_evaluable_rules_skips_an_armed_rule_above_the_cap() -> None:
    m, rec = _mgr()
    await _seed(m, rec, DAY, LIMIT_CAPS[DAY] + 1, mode="armed")
    kept = await _seed(m, rec, DAY, LIMIT_DEFAULTS[DAY], mode="armed", name="kept")
    assert [str(r.rule_id) for r in await m.evaluable_rules()] == [kept]
    await _settle(m)


async def test_evaluable_rules_disarms_an_armed_rule_above_the_cap_with_its_reason() -> None:
    m, rec = _mgr()
    rid = await _seed(m, rec, DAY, LIMIT_CAPS[DAY] + 1, mode="armed")
    await m.evaluable_rules()
    await _settle(m)
    over = {DAY: {"cap": LIMIT_CAPS[DAY], "value": LIMIT_CAPS[DAY] + 1}}
    sent = {"rule_id": rid, "mode": "disabled", "from": "armed", "b9_from": "armed"}
    sent |= {"b9_event": "DISARM", "reason": "limits_above_cap"}
    assert rec.audits == [("rule.disarmed", sent | {"limits_above_cap": over, "b9_to": "disarmed"})]
    assert rec.broadcasts == [{"topic": "rules", **sent}]
    row = await m._s.get(rid)
    assert row is not None and (row.mode, row.disabled_reason) == ("disabled", "disarmed")


async def test_evaluable_rules_disarms_an_armed_rule_above_the_cap_once() -> None:
    """Disarmed, never clamped and run again: the next tick neither runs nor records it."""
    m, rec = _mgr()
    await _seed(m, rec, DAY, LIMIT_CAPS[DAY] + 1, mode="armed")
    await m.evaluable_rules()
    await _settle(m)
    assert await m.evaluable_rules() == []
    await _settle(m)
    assert [a for a, _ in rec.audits] == ["rule.disarmed"]


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


def _presenters(m: RulesManager, rid: str, pair: str) -> list[Coroutine[Any, Any, Any]]:
    """Two of the paths that present a rule, so disarm one above a cap, started together."""
    start: dict[str, Callable[[], Coroutine[Any, Any, Any]]] = {
        "get": lambda: m.get(rid, OWNER),
        "list_rules": lambda: m.list_rules(OWNER),
        "evaluable_rules": m.evaluable_rules,
    }
    return [start[name]() for name in pair.split("+")]


async def _save_within_budget(m: RulesManager, rid: str) -> str:
    """The Owner saves the rule again within its budget, simulated on its `ir_hash`; returns the
    version id. A disabled rule activates it at once."""
    row = await m._s.get(rid)
    assert row is not None
    saved = await m.update(rid, _ir(name=row.name, scope=dict(ON_A)), row.latest_version, OWNER)
    await m.record_simulation(rid, saved["version"]["ir_hash"], 5, 0.0)
    return str(saved["version"]["id"])


def _answering(row: RuleRow) -> Callable[[str], Coroutine[Any, Any, RuleRow]]:
    """A store read that answers `row`: a copy read before a change, as a Postgres read can be."""

    async def get(_rule_id: str) -> RuleRow:
        return row

    return get


_PAIRS = pytest.mark.parametrize("pair", ["get+get", "get+evaluable_rules", "list_rules+get"])


@_PAIRS
async def test_two_presenters_at_once_record_one_disarm(pair: str) -> None:
    """Forced disarms run one at a time, and each sends DISARM only to a chart that still takes
    it: one `rule.disarmed` record for one disarm (C-2.9)."""
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR] + 1, mode="armed")
    await asyncio.gather(*_presenters(m, rid, pair))
    await _settle(m)
    assert [a for a, _ in rec.audits] == ["rule.disarmed"]


@_PAIRS
async def test_arming_after_two_presenters_disarmed_it_succeeds_first_time(pair: str) -> None:
    """No DISARM is left parked on the chart (`onUnhandled: defer`) to replay into the next arm."""
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR] + 1, mode="armed")
    await asyncio.gather(*_presenters(m, rid, pair))
    await _settle(m)
    await _save_within_budget(m, rid)
    assert (await m.set_mode(rid, "armed", OWNER, "arm"))["mode"] == "armed"
    assert m.lifecycle.leaf(rid) == "armed"


async def test_a_stale_armed_row_sends_nothing_to_a_chart_demoted_to_simulating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read while armed above the cap, presented after the Owner activated a version within the
    budget: nothing is sent, so no parked DISARM turns the next arm into a disarm."""
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR] + 1, mode="armed")
    row = await m._s.get(rid)
    assert row is not None
    stale = replace(row)
    await m.set_active_version(rid, await _save_within_budget(m, rid), "within budget", OWNER)
    rec.audits.clear()
    rec.broadcasts.clear()
    monkeypatch.setattr(m._s, "get", _answering(stale))
    await m.get(rid, OWNER)
    monkeypatch.undo()
    assert (rec.audits, rec.broadcasts, m.lifecycle.leaf(rid)) == ([], [], "simulating")
    assert (await m.set_mode(rid, "armed", OWNER, "arm"))["mode"] == "armed"
    assert [p["b9_to"] for a, p in rec.audits if a == "rule.armed"] == ["armed"]


async def test_a_stale_armed_row_sends_nothing_to_a_disarmed_chart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read while armed, presented after another read disarmed it: nothing is sent, so the first
    arm of a version within the budget succeeds."""
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR] + 1, mode="armed")
    row = await m._s.get(rid)
    assert row is not None
    stale = replace(row)
    await m.get(rid, OWNER)
    rec.audits.clear()
    rec.broadcasts.clear()
    monkeypatch.setattr(m._s, "get", _answering(stale))
    await m.get(rid, OWNER)
    monkeypatch.undo()
    assert (rec.audits, rec.broadcasts, m.lifecycle.leaf(rid)) == ([], [], "disarmed")
    await _save_within_budget(m, rid)
    assert (await m.set_mode(rid, "armed", OWNER, "arm"))["mode"] == "armed"


@pytest.mark.parametrize(("mode", "reason"), [("simulate", None), ("disabled", "disarmed")])
async def test_reading_a_rule_above_the_cap_that_is_not_armed_changes_nothing(
    mode: str, reason: str | None
) -> None:
    """Only an armed rule is disarmed when read: nothing is recorded, broadcast or sent, and its
    chart is not even built (DISARM is not handled in `simulating` or `disarmed`)."""
    m, rec = _mgr()
    rid = await _seed(m, rec, DAY, LIMIT_CAPS[DAY] + 1, mode=mode, reason=reason)
    assert (await m.get(rid, OWNER))["mode"] == mode
    assert [r["mode"] for r in (await m.list_rules(OWNER))["items"]] == [mode]
    assert (rec.audits, rec.broadcasts, m.lifecycle.leaf(rid)) == ([], [], None)


async def test_evaluable_rules_keeps_a_simulating_rule_above_the_cap() -> None:
    """A simulation sends nothing, so a rule above a cap still simulates; arming it is refused."""
    m, rec = _mgr()
    rid = await _seed(m, rec, DAY, LIMIT_CAPS[DAY] + 1, mode="simulate")
    assert [str(r.rule_id) for r in await m.evaluable_rules()] == [rid]
    assert (rec.audits, _tick_disarms(), m.lifecycle.leaf(rid)) == ([], [], None)


async def test_a_forced_disarm_the_chart_does_not_take_is_neither_recorded_nor_broadcast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR] + 1, mode="armed")

    async def refused(_rule_id: str, _event: str, **_payload: Any) -> tuple[str, str]:
        return "armed", "armed"  # leaf before == leaf after: the chart did not move

    monkeypatch.setattr(m.lifecycle, "send", refused)
    assert (await m.get(rid, OWNER))["mode"] == "armed"
    assert (rec.audits, rec.broadcasts) == ([], [])


async def test_an_armed_rule_above_the_default_but_under_the_cap_keeps_running() -> None:
    """Decision 9's accepted residual: armed by a Manager before the caps, it runs until it is
    re-armed."""
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR], mode="armed")
    assert [str(r.rule_id) for r in await m.evaluable_rules()] == [rid]
    assert (await m.get(rid, MANAGER))["mode"] == "armed"
    assert rec.audits == []


async def test_a_protected_system_rule_above_the_cap_is_disarmed_then_reported_tampered() -> None:
    """Built-ins get no exemption from the caps (RE-E10): E35-T05 seeds them within the caps.
    One found armed above a cap, which only an out-of-band write can cause, is disarmed like any
    rule, and the start-up check reports it as tampered."""
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR] + 1, mode="armed")
    row = await m._s.get(rid)
    assert row is not None
    row.name = row.versions[0].ir["name"] = "sys.native_sl_watchdog"
    assert await m.evaluable_rules() == []
    await _settle(m)
    assert await m.verify_system_rules() == ["sys.native_sl_watchdog"]
    assert [a for a, _ in rec.audits] == ["rule.disarmed", "rule.system_rule_tampered"]


async def _down(_action: str, _payload: dict[str, Any]) -> None:
    raise RuntimeError("audit down")


async def test_a_disarm_that_fails_beside_a_tick_is_logged_and_leaves_the_rule_armed() -> None:
    """Fail closed per rule: the runner never gets the rule, the loss is logged, and nothing is
    recorded or broadcast."""
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR] + 1, mode="armed")
    m.set_hooks(audit=_down)
    with capture_logs() as logs:
        assert await m.evaluable_rules() == []
        await _settle(m)
    failed = [(e["event"], e["rule_id"], e["error"]) for e in logs if e["log_level"] == "error"]
    assert failed == [("rules.limits_disarm_failed", rid, "RuntimeError")]
    row = await m._s.get(rid)
    assert row is not None and row.mode == "armed" and rec.broadcasts == []


async def test_a_failed_disarm_is_tried_again_on_the_next_tick() -> None:
    m, rec = _mgr()
    rid = await _seed(m, rec, HOUR, LIMIT_CAPS[HOUR] + 1, mode="armed")
    m.set_hooks(audit=_down)
    await m.evaluable_rules()
    await _settle(m)
    m.set_hooks(audit=rec.audit)
    assert await m.evaluable_rules() == []
    await _settle(m)
    row = await m._s.get(rid)
    assert row is not None and row.mode == "disabled"
    assert [a for a, _ in rec.audits] == ["rule.disarmed"]


async def _stalled(_action: str, _payload: dict[str, Any]) -> None:
    """Never answers: a bound of 0 s ends it at its first yield; unbounded, it fails the test."""
    for _ in range(100):
        await asyncio.sleep(0)
    raise AssertionError("the disarm was not bounded")


async def test_a_disarm_that_outlasts_its_bound_is_logged_and_leaves_the_rule_armed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m, rec = _mgr()
    rid = await _seed(m, rec, DAY, LIMIT_CAPS[DAY] + 1, mode="armed")
    m.set_hooks(audit=_stalled)
    monkeypatch.setattr(rules_manager, "TICK_DISARM_TIMEOUT_S", 0.0)
    with capture_logs() as logs:
        assert await m.evaluable_rules() == []
        await _settle(m)
    assert [e["error"] for e in logs if e["log_level"] == "error"] == ["TimeoutError"]
    row = await m._s.get(rid)
    assert row is not None and row.mode == "armed"


async def test_a_tick_returns_while_its_disarm_is_held_by_the_audit_writer() -> None:
    """The rule is skipped before it is disarmed, so the tick never waits for the disarm: a
    stalled writer delays no other rule's evaluation."""
    m, rec = _mgr()
    await _seed(m, rec, DAY, LIMIT_CAPS[DAY] + 1, mode="armed")
    writer = _HeldWriter(rec)
    m.set_hooks(audit=writer.audit)
    assert await m.evaluable_rules() == []
    await writer.entered.wait()
    assert rec.audits == [] and len(_tick_disarms()) == 1
    writer.release.set()
    await _settle(m)
    assert [a for a, _ in rec.audits] == ["rule.disarmed"]


async def test_a_tick_starts_no_second_disarm_while_one_is_in_flight() -> None:
    m, rec = _mgr()
    await _seed(m, rec, DAY, LIMIT_CAPS[DAY] + 1, mode="armed")
    writer = _HeldWriter(rec)
    m.set_hooks(audit=writer.audit)
    await m.evaluable_rules()
    await writer.entered.wait()
    assert await m.evaluable_rules() == []
    assert len(_tick_disarms()) == 1
    writer.release.set()
    await _settle(m)


async def test_stop_cancels_a_disarm_in_flight_and_leaves_the_rule_armed() -> None:
    m, rec = _mgr()
    rid = await _seed(m, rec, DAY, LIMIT_CAPS[DAY] + 1, mode="armed")
    writer = _HeldWriter(rec)
    m.set_hooks(audit=writer.audit)
    await m.evaluable_rules()
    await writer.entered.wait()
    await m.stop()
    row = await m._s.get(rid)
    assert row is not None and (row.mode, rec.audits, _tick_disarms()) == ("armed", [], [])


async def test_stopping_the_rules_service_cancels_a_disarm_in_flight() -> None:
    rec = _Recorder()
    svc = RulesService()
    svc.bind(audit=rec.audit, broadcast=rec.broadcast)
    await svc.start(None)  # type: ignore[arg-type]  # no AppContext: the evaluator stays off
    m = svc.manager()
    assert m is not None
    await _seed(m, rec, DAY, LIMIT_CAPS[DAY] + 1, mode="armed")
    writer = _HeldWriter(rec)
    m.set_hooks(audit=writer.audit)
    await m.evaluable_rules()
    await writer.entered.wait()
    await svc.stop(1.0)
    assert (rec.audits, _tick_disarms()) == ([], [])


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
