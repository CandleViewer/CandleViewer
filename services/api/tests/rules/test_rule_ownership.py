"""#3334 (04 §7.2.2 rows 24 and 25, 24 §15.2): a rule is reached through its owner.

The Owner role reaches every rule; anyone else only a rule they own, and only while every account
any version of it names is granted to them. Grants alone never reach another user's rule, whether
it names accounts or none. A refused change is audited once, as `rule.scope_refused`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleError, RuleRow, RulesManager
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_rules_routes import _Env, _ir

A1 = "11111111-1111-4111-8111-111111111111"
PERMS = frozenset({"rules:read", "rules:write"})
OWNER = Actor("owner", "s0", PERMS, is_owner=True)
MANAGER = Actor("mgr", "s1", PERMS, frozenset({A1}))
#: A rule naming no account, and one whose every account is granted to the Manager.
KINDS = {
    "accountless": {"level": "symbol", "symbols": ["BTCUSDT"]},
    "fully_granted": {"level": "account", "account_ids": [A1]},
}
#: A save that rewrites the rule onto the Manager's own granted account.
_EDITED = _ir(name="edited", scope=KINDS["fully_granted"])
Audits = list[tuple[str, dict[str, Any]]]
Op = Callable[[RulesManager, str, str, Actor], Awaitable[Any]]
#: name -> (the `op` an audited refusal names, the call); `disarm` runs on an armed rule.
_OPS: dict[str, tuple[str, Op]] = {
    "update": ("update", lambda m, rid, _v, a: m.update(rid, _EDITED, 1, a)),
    "set_active_version": (
        "set_active_version",
        lambda m, rid, vid, a: m.set_active_version(rid, vid, "n", a),
    ),
    "set_mode": ("set_mode", lambda m, rid, _v, a: m.set_mode(rid, "simulate", a, "k")),
    "disarm": ("set_mode", lambda m, rid, _v, a: m.set_mode(rid, "disabled", a, "k")),
    "delete": ("delete", lambda m, rid, _v, a: m.delete(rid, a)),
}


def _mgr() -> tuple[RulesManager, Audits]:
    audits: Audits = []

    async def audit(action: str, payload: dict[str, Any]) -> None:
        audits.append((action, payload))

    return RulesManager(InMemoryRuleStore(), default_registry(), audit=audit), audits


async def _seed(
    m: RulesManager, kind: str, owner: Actor, *, armed: bool = False
) -> tuple[str, str]:
    """A rule of `kind` saved by `owner`, armed when asked: its id and its first version's id."""
    rid = str((await m.create(_ir(scope=KINDS[kind]), owner))["id"])
    first = (await m._row(rid)).versions[0]
    if armed:
        await m.set_mode(rid, "simulate", owner, "sim")
        await m.record_simulation(rid, first.ir_hash, 5, 0.0)
        await m.set_mode(rid, "armed", owner, "arm")
    return rid, first.id


def _state(row: RuleRow) -> tuple[Any, ...]:
    return (row.name, row.mode, row.deleted, row.latest_version, row.active_version_id)


_KIND = pytest.mark.parametrize("kind", KINDS)
_OP = pytest.mark.parametrize("name", _OPS)


@_KIND
async def test_list_of_a_rule_the_manager_does_not_own_leaves_it_out(kind: str) -> None:
    m, _ = _mgr()
    await _seed(m, kind, OWNER)
    assert (await m.list_rules(MANAGER))["items"] == []
    assert len((await m.list_rules(OWNER))["items"]) == 1


@_KIND
async def test_get_of_a_rule_the_manager_does_not_own_is_a_404_without_a_record(kind: str) -> None:
    m, audits = _mgr()
    rid, _ = await _seed(m, kind, OWNER)
    audits.clear()
    with pytest.raises(RuleError) as refused:
        await m.get(rid, MANAGER)
    assert (refused.value.status, refused.value.code) == (404, "not_found")
    assert audits == []  # a read is scoping, not a refusal
    assert (await m.get(rid, OWNER))["id"] == rid


@pytest.mark.parametrize(("theirs", "mine"), [("mgr-2", "mgr"), ("mgr", "mgr-2")])
async def test_read_and_update_of_another_managers_rule_on_a_shared_grant_are_404s(
    theirs: str, mine: str
) -> None:
    """Ownership is equality of user ids, not a prefix or a substring of one."""
    m, _ = _mgr()
    rid, _ = await _seed(m, "fully_granted", Actor(theirs, "s2", PERMS, frozenset({A1})))
    me = Actor(mine, "s3", PERMS, frozenset({A1}))
    assert (await m.list_rules(me))["items"] == []
    with pytest.raises(RuleError) as on_get:
        await m.get(rid, me)
    with pytest.raises(RuleError) as on_update:
        await m.update(rid, _EDITED, 1, me)
    assert on_get.value.status == on_update.value.status == 404


@_KIND
@_OP
async def test_change_of_a_rule_the_manager_does_not_own_is_refused_and_audited_once(
    kind: str, name: str
) -> None:
    m, audits = _mgr()
    rid, vid = await _seed(m, kind, OWNER, armed=name == "disarm")
    before = _state(await m._row(rid))
    audits.clear()
    op, call = _OPS[name]
    with pytest.raises(RuleError) as refused:
        await call(m, rid, vid, MANAGER)
    assert (refused.value.status, refused.value.code) == (404, "not_found")
    assert [(a, p["rule_id"], p["op"], p["reason"], p["actor"]) for a, p in audits] == [
        ("rule.scope_refused", rid, op, "rule_not_visible", MANAGER.user_id)
    ]
    assert _state(await m._row(rid)) == before


@_KIND
@_OP
@pytest.mark.parametrize("actor", [OWNER, MANAGER], ids=["owner_role", "own_rule"])
async def test_change_by_one_who_reaches_the_rule_goes_through(
    kind: str, name: str, actor: Actor
) -> None:
    """The Owner role, and a Manager on a rule they own: nothing is refused."""
    m, audits = _mgr()
    rid, vid = await _seed(m, kind, MANAGER, armed=name == "disarm")
    await _OPS[name][1](m, rid, vid, actor)
    assert "rule.scope_refused" not in [a for a, _ in audits]


# ---- HTTP: every route reads the stored rule's owner, whatever the request names ----------------
_ROUTES: dict[str, tuple[str, str, Callable[[str], Any], str | None]] = {
    "get": ("get", "/rules/{rid}", lambda _v: None, None),
    "list_versions": ("get", "/rules/{rid}/versions", lambda _v: None, None),
    "get_version": ("get", "/rules/{rid}/versions/{vid}", lambda _v: None, None),
    "update": ("put", "/rules/{rid}", lambda _v: {"ir": _EDITED, "expected_version": 1}, "update"),
    "set_active_version": (
        "put",
        "/rules/{rid}/active-version",
        lambda vid: {"version_id": vid},
        "set_active_version",
    ),
    "set_mode": ("put", "/rules/{rid}/mode", lambda _v: {"mode": "simulate"}, "set_mode"),
    "arm": ("put", "/rules/{rid}/mode", lambda _v: {"mode": "armed"}, "set_mode"),
    "disarm": ("put", "/rules/{rid}/mode", lambda _v: {"mode": "disabled"}, "set_mode"),
    "delete": ("delete", "/rules/{rid}", lambda _v: None, "delete"),
}


@_KIND
@pytest.mark.parametrize("route", _ROUTES)
def test_route_of_a_rule_the_manager_does_not_own_is_the_unseen_404(kind: str, route: str) -> None:
    owner = _Env()
    manager = _Env(set(PERMS), owner=False, granted=frozenset({A1}), mgr=owner.mgr, uid="mgr")
    rid = owner.create(scope=KINDS[kind])
    vid = owner.c.get(f"/rules/{rid}/versions").json()["items"][0]["id"]
    method, path, body, op = _ROUTES[route]
    owner.audits.clear()
    resp = manager.c.request(
        method, path.format(rid=rid, vid=vid), json=body(vid), headers={"Idempotency-Key": "k"}
    )
    assert (resp.status_code, resp.json()["code"]) == (404, "not_found"), resp.text
    refused = [(p["op"], p["reason"]) for a, p in owner.audits if a == "rule.scope_refused"]
    assert refused == ([(op, "rule_not_visible")] if op else [])
    assert owner.c.get(f"/rules/{rid}").json()["mode"] == "disabled"


@pytest.mark.parametrize("shape", ["tight", None, ["a"]], ids=["str", "none", "list"])
async def test_arm_with_a_stored_scope_that_is_not_a_mapping_is_a_422(shape: Any) -> None:
    """The arming pre-check reads the stored scope without trusting its shape: an unreadable rule
    is the 422 of any unreadable rule, never a 500."""
    e = _Env()
    rid = e.create()
    (await e.mgr._row(rid)).versions[0].ir["scope"] = shape
    resp = e.mode(rid, "armed", "k")
    assert (resp.status_code, resp.json()["code"]) == (422, "rule_invalid")
