"""#3232 slice A: a rule's action budget at save (SR-104; 04 §7.2.2 row 26).

`max_fires_per_hour` and `max_fires_per_day` above their `RuleLimits` defaults need the Owner role
(`403 forbidden`, audited as a scope refusal); above the hard caps of `rules.limits` they are
refused for every role (`422 rule_ir_invalid`). Values are compared with the default and the cap,
never with an earlier version (decision 4). Arming re-checks them in slice B.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.alerts.compiler import AlertCompiler
from candleviewer.rules.ir import Rule, RuleLimits
from candleviewer.rules.limits import BUDGET_FIELDS, LIMIT_CAPS, LIMIT_DEFAULTS
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleError, RulesManager
from candleviewer.rules.validator import validate_rule
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_rules_routes import _ir

ACC_A = "00000000-0000-4000-8000-0000000000a1"
ACC_B = "00000000-0000-4000-8000-0000000000b2"
ON_A = {"level": "account", "account_ids": [ACC_A]}
ON_B = {"level": "account", "account_ids": [ACC_B]}
OWNER = Actor("u-owner", "s-owner", is_owner=True)
MANAGER = Actor("u-mgr", "s-mgr", frozenset({"rules:write"}), frozenset({ACC_A}))
HOUR, DAY = BUDGET_FIELDS
Audits = list[tuple[str, dict[str, Any]]]


def _mgr() -> tuple[RulesManager, Audits]:
    audits: Audits = []

    async def audit(action: str, payload: dict[str, Any]) -> None:
        audits.append((action, payload))

    return RulesManager(InMemoryRuleStore(), default_registry(), audit=audit), audits


def _limited(field: str, value: int, scope: Mapping[str, Any] = ON_A) -> dict[str, Any]:
    return _ir(limits={field: value}, scope=dict(scope))


def _refusals(audits: Audits) -> list[tuple[str, str]]:
    return [(p["op"], p["reason"]) for a, p in audits if a == "rule.scope_refused"]


def _band(lo: Mapping[str, int], hi: Mapping[str, int]) -> st.SearchStrategy[tuple[str, int]]:
    """A budget field and a value in `lo[field]..hi[field]`."""
    return st.sampled_from(BUDGET_FIELDS).flatmap(
        lambda f: st.tuples(st.just(f), st.integers(lo[f], hi[f]))
    )


_ONE = dict.fromkeys(BUDGET_FIELDS, 1)
_ABOVE_DEFAULT = {f: d + 1 for f, d in LIMIT_DEFAULTS.items()}
_ABOVE_CAP = {f: c + 1 for f, c in LIMIT_CAPS.items()}
_FAR_ABOVE_CAP = {f: 10 * c for f, c in LIMIT_CAPS.items()}


_ROLES = pytest.mark.parametrize("actor", [OWNER, MANAGER], ids=["owner", "manager"])


@_ROLES
@given(case=_band(_ONE, LIMIT_DEFAULTS))
async def test_rule_limits_at_or_below_default_pass_for_every_role(
    actor: Actor, case: tuple[str, int]
) -> None:
    m, audits = _mgr()
    await m.create(_limited(*case), actor)
    assert [a for a, _ in audits] == ["rule.created"]
    assert "limits_above_default" not in audits[0][1]


@given(case=_band(_ABOVE_DEFAULT, LIMIT_CAPS))
async def test_rule_limits_between_default_and_cap_need_the_owner(case: tuple[str, int]) -> None:
    field, value = case
    m, audits = _mgr()
    with pytest.raises(RuleError) as refused:
        await m.create(_limited(field, value), MANAGER)
    assert (refused.value.status, refused.value.code) == (403, "forbidden")
    assert _refusals(audits) == [("create", "limits_owner_only")]
    assert (await m.list_rules(OWNER))["items"] == []
    await m.create(_limited(field, value), OWNER)
    created = audits[-1][1]["limits_above_default"]
    assert created == {field: {"default": LIMIT_DEFAULTS[field], "value": value}}


@_ROLES
@given(case=_band(_ABOVE_CAP, _FAR_ABOVE_CAP))
async def test_rule_limits_above_cap_fail_for_every_role(
    actor: Actor, case: tuple[str, int]
) -> None:
    m, audits = _mgr()
    with pytest.raises(RuleError) as refused:
        await m.create(_limited(*case), actor)
    assert (refused.value.status, refused.value.code) == (422, "rule_ir_invalid")
    assert audits == [] and (await m.list_rules(OWNER))["items"] == []


async def test_create_manager_limits_above_default_is_403_audited_and_stores_nothing() -> None:
    m, audits = _mgr()
    with pytest.raises(RuleError) as refused:
        await m.create(_limited(HOUR, LIMIT_DEFAULTS[HOUR] + 1), MANAGER)
    (error,) = refused.value.extra["errors"]
    assert (error["field"], error["rule"]) == (
        "limits.max_fires_per_hour",
        "owner_only_above_default",
    )
    assert (
        error["message"]
        == f"Fires per hour above the default of {LIMIT_DEFAULTS[HOUR]} needs the Owner."
    )
    assert [a for a, _ in audits] == ["rule.scope_refused"]
    assert _refusals(audits) == [("create", "limits_owner_only")]
    assert audits[0][1]["actor"] == MANAGER.user_id
    assert (await m.list_rules(OWNER))["items"] == []


async def test_update_manager_limits_above_default_is_403_audited_and_adds_no_version() -> None:
    m, audits = _mgr()
    rid = (await m.create(_limited(DAY, LIMIT_DEFAULTS[DAY]), MANAGER))["id"]
    with pytest.raises(RuleError) as refused:
        await m.update(rid, _limited(DAY, LIMIT_DEFAULTS[DAY] + 1), 1, MANAGER)
    assert (refused.value.status, refused.value.code) == (403, "forbidden")
    assert [e["field"] for e in refused.value.extra["errors"]] == ["limits.max_fires_per_day"]
    assert _refusals(audits) == [("update", "limits_owner_only")]
    assert [v["version"] for v in await m.versions(rid)] == [1]


async def test_update_manager_resaving_the_owners_raised_version_is_refused() -> None:
    """Decision 4: a save that matches the Owner's raised version adds no version, and is still
    refused rather than answered `created: false`."""
    m, audits = _mgr()
    raised = _limited(HOUR, 2 * LIMIT_DEFAULTS[HOUR])
    rid = (await m.create(_limited(HOUR, LIMIT_DEFAULTS[HOUR]), MANAGER))["id"]
    await m.update(rid, raised, 1, OWNER)  # the Owner raises the Manager's rule: version 2
    with pytest.raises(RuleError) as refused:
        await m.update(rid, raised, 2, MANAGER)
    assert refused.value.status == 403
    assert _refusals(audits) == [("update", "limits_owner_only")]


async def _two_versions(m: RulesManager) -> tuple[str, str, str]:
    """The Manager's rule: version 1 at the default, then (saved by the Owner) version 2 at the
    cap; 1 is active."""
    rid = (await m.create(_limited(HOUR, LIMIT_DEFAULTS[HOUR]), MANAGER))["id"]
    await m.update(rid, _limited(HOUR, LIMIT_CAPS[HOUR]), 1, OWNER)
    first, raised = (v["id"] for v in reversed(await m.versions(rid)))
    await m.set_active_version(rid, first, "default", OWNER)
    return rid, first, raised


async def test_set_active_version_manager_activating_a_raised_version_is_403_audited() -> None:
    m, audits = _mgr()
    rid, first, raised = await _two_versions(m)
    with pytest.raises(RuleError) as refused:
        await m.set_active_version(rid, raised, "raise", MANAGER)
    assert (refused.value.status, refused.value.code) == (403, "forbidden")
    assert _refusals(audits) == [("set_active_version", "limits_owner_only")]
    assert (await m.get(rid, OWNER))["active_version_id"] == first


async def test_set_active_version_owner_activating_a_raised_version_audits_the_values() -> None:
    m, audits = _mgr()
    rid, _first, raised = await _two_versions(m)
    assert (await m.set_active_version(rid, raised, "raise", OWNER))["active_version_id"] == raised
    activated = audits[-1][1]
    assert activated["activated"] is True
    assert activated["limits_above_default"] == {
        HOUR: {"default": LIMIT_DEFAULTS[HOUR], "value": LIMIT_CAPS[HOUR]}
    }


async def test_create_owner_limits_between_default_and_cap_are_accepted_and_audited() -> None:
    m, audits = _mgr()
    out = await m.create(_limited(DAY, LIMIT_CAPS[DAY]), OWNER)
    assert out["version"]["version"] == 1
    assert audits[-1][0] == "rule.created"
    assert audits[-1][1]["limits_above_default"] == {
        DAY: {"default": LIMIT_DEFAULTS[DAY], "value": LIMIT_CAPS[DAY]}
    }


async def test_update_owner_limits_between_default_and_cap_are_accepted_and_audited() -> None:
    m, audits = _mgr()
    rid = (await m.create(_limited(HOUR, LIMIT_DEFAULTS[HOUR]), OWNER))["id"]
    out = await m.update(rid, _limited(HOUR, LIMIT_DEFAULTS[HOUR] + 1), 1, OWNER)
    assert out["created"] is True and audits[-1][0] == "rule.updated"
    assert audits[-1][1]["limits_above_default"] == {
        HOUR: {"default": LIMIT_DEFAULTS[HOUR], "value": LIMIT_DEFAULTS[HOUR] + 1}
    }


Save = Callable[[RulesManager, str, dict[str, Any], Actor], Awaitable[Any]]
_SAVES: dict[str, Save] = {
    "create": lambda m, _rid, ir, actor: m.create({**ir, "name": "second"}, actor),
    "update": lambda m, rid, ir, actor: m.update(rid, ir, 1, actor),
    "import": lambda m, _rid, ir, actor: m.import_rule({"ir": {**ir, "name": "second"}}, actor),
}


@_ROLES
@pytest.mark.parametrize("path", list(_SAVES))
async def test_save_limits_above_cap_is_422_for_owner_and_manager(path: str, actor: Actor) -> None:
    m, audits = _mgr()
    rid = (await m.create(_limited(HOUR, 1), actor))["id"]
    audits.clear()
    with pytest.raises(RuleError) as refused:
        await _SAVES[path](m, rid, _limited(HOUR, LIMIT_CAPS[HOUR] + 1), actor)
    assert (refused.value.status, refused.value.code) == (422, "rule_ir_invalid")
    (issue,) = refused.value.extra["issues"]
    assert (issue["path"], issue["code"], issue["class"]) == (
        "limits.max_fires_per_hour",
        "schema_error",
        "safety",
    )
    assert audits == [] and len((await m.list_rules(OWNER))["items"]) == 1
    assert [v["version"] for v in await m.versions(rid)] == [1]


async def test_import_manager_limits_above_default_is_403_audited_and_stores_nothing() -> None:
    m, audits = _mgr()
    with pytest.raises(RuleError) as refused:
        await m.import_rule({"ir": _limited(DAY, LIMIT_DEFAULTS[DAY] + 1)}, MANAGER)
    assert (refused.value.status, refused.value.code) == (403, "forbidden")
    assert _refusals(audits) == [("create", "limits_owner_only")]
    assert (await m.list_rules(OWNER))["items"] == []


@pytest.mark.parametrize("field", BUDGET_FIELDS)
async def test_limits_exactly_at_the_default_are_saved_for_a_manager(field: str) -> None:
    m, audits = _mgr()
    assert (await m.create(_limited(field, LIMIT_DEFAULTS[field]), MANAGER))["version"]
    assert _refusals(audits) == []


@pytest.mark.parametrize("field", BUDGET_FIELDS)
async def test_limits_exactly_at_the_cap_are_saved_for_the_owner_only(field: str) -> None:
    m, audits = _mgr()
    assert (await m.create(_limited(field, LIMIT_CAPS[field]), OWNER))["version"]
    with pytest.raises(RuleError) as refused:
        await m.create({**_limited(field, LIMIT_CAPS[field]), "name": "second"}, MANAGER)
    assert refused.value.status == 403
    assert _refusals(audits) == [("create", "limits_owner_only")]


async def test_create_manager_on_an_ungranted_account_is_refused_by_scope_before_limits() -> None:
    m, audits = _mgr()
    with pytest.raises(RuleError) as refused:
        await m.create(_limited(HOUR, LIMIT_CAPS[HOUR], ON_B), MANAGER)
    assert refused.value.status == 403
    assert _refusals(audits) == [("create", "account_not_granted")]


async def test_owner_rule_on_an_ungranted_account_is_404_to_a_manager_before_limits() -> None:
    """04 §7.3 / RE-I5: on a rule the Manager cannot see, update and activate answer the 404 of
    a missing rule, never a limits refusal that would confirm the rule exists."""
    m, audits = _mgr()
    rid = (await m.create(_limited(HOUR, LIMIT_CAPS[HOUR], ON_B), OWNER))["id"]
    vid = (await m.versions(rid))[0]["id"]
    with pytest.raises(RuleError) as on_update:
        await m.update(rid, _limited(HOUR, LIMIT_CAPS[HOUR], ON_B), 1, MANAGER)
    with pytest.raises(RuleError) as on_activate:
        await m.set_active_version(rid, vid, "raise", MANAGER)
    assert on_update.value.status == on_activate.value.status == 404
    assert _refusals(audits) == [
        ("update", "rule_not_visible"),
        ("set_active_version", "rule_not_visible"),
    ]


def test_validator_holds_a_rule_to_the_caps_only_when_asked() -> None:
    rule = Rule.model_validate(_limited(DAY, LIMIT_CAPS[DAY] + 1))
    assert validate_rule(rule, default_registry()).valid
    (issue,) = validate_rule(rule, default_registry(), limit_caps=True).errors
    assert issue.to_dict() == {
        "path": "limits.max_fires_per_day",
        "code": "schema_error",
        "message": f"Fires per day can be at most {LIMIT_CAPS[DAY]}, the hard cap for every rule.",
        "severity": "error",
        "class": "safety",
    }


def test_alert_compile_is_unaffected_by_rule_limit_caps() -> None:
    """Decision 8: alerts share `RuleLimits`, and the caps stay a rules-only check (#3259)."""
    alert = {
        "ir_version": 1,
        "trigger": {"type": "on_price_update", "debounce_ms": 250},
        "conditions": {
            "node_id": "c1",
            "op": "crosses_above",
            "left": {"metric": "price"},
            "right": {"const": 64000},
        },
        "limits": _ABOVE_CAP,
    }
    compiled = AlertCompiler(default_registry()).compile(alert)
    assert compiled.condition.limits == RuleLimits.model_validate(_ABOVE_CAP)
