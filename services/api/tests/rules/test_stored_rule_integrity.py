"""#4835 (E36-X01 G-4, G-12): what a stored rule says about itself comes from the server.

G-4: every save and every import stores the acting user and the server's clock as the IR's
`created_by`, `created_at` and `updated_at`, whatever the document claimed, and the version's
author is that user. G-12: a save body names a rule's accounts only in `ir.scope.account_ids`; a
member `22` does not name, or an account key in a member outside `ir`, is refused with an audited
`422 rule_ir_invalid` naming the member, and nothing is stored.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.api.rules_actor import make_rules_audit
from candleviewer.audit.models import AuditOutcome
from candleviewer.rules.manager import (
    MAX_BODY_REFUSALS,
    Actor,
    InMemoryRuleStore,
    RuleError,
    RulesManager,
    rule_visible,
)
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_rules_routes import _Env, _ir
from tests.rules.test_scope import A, C

NOW = 1_761_652_800_000_000  # the server's clock in these tests, in µs
USER_A, USER_B = str(uuid.UUID(int=0xA)), str(uuid.UUID(int=0xB))
CLAIMED: dict[str, Any] = {"created_by": str(uuid.UUID(int=0xC1)), "created_at": 1, "updated_at": 2}
WRITE = {"rules:read", "rules:write"}


def _env(uid: str = USER_A, **kw: Any) -> _Env:
    """`_Env` whose manager reads the server's time from `NOW`, audits into `e.audits`."""
    e = _Env(uid=uid, **kw)

    async def audit(action: str, payload: dict[str, Any]) -> None:
        e.audits.append((action, payload))

    e.mgr = RulesManager(InMemoryRuleStore(), default_registry(), audit=audit, now_us=lambda: NOW)
    return e


def _save(e: _Env, op: str, rid: str, body: dict[str, Any]) -> Any:
    if op == "create":
        return e.c.post("/rules", json=body)
    return e.c.put(f"/rules/{rid}", json=body, headers={"If-Match": "1"})


async def _latest(mgr: RulesManager, rid: str) -> dict[str, Any]:
    """The newest version of `rid` with its IR, as `getRuleVersion` serves it."""
    return await mgr.version(rid, (await mgr.versions(rid))[0]["id"])


def _authored(version: dict[str, Any]) -> tuple[Any, ...]:
    ir = version["ir"]
    return ir["created_by"], ir["created_at"], ir["updated_at"], version["author"]


def _rows(e: _Env) -> list[tuple[str, int]]:
    """Every stored rule, by name and latest version, as the Owner's `listRules` shows it."""
    return [(i["name"], i["latest_version"]) for i in e.c.get("/rules").json()["items"]]


async def test_a_save_stores_the_acting_user_and_the_server_time_never_the_bodys() -> None:
    """Scenario: Client authorship never survives a save (create, then update, over HTTP)."""
    e = _env()
    rid = e.create(**CLAIMED)
    assert _authored(await _latest(e.mgr, rid)) == (USER_A, NOW, NOW, USER_A)
    saved = _save(e, "update", rid, {"ir": _ir("2", **CLAIMED)})
    assert saved.status_code == 200 and saved.json()["version"]["author"] == USER_A
    assert _authored(await _latest(e.mgr, rid)) == (USER_A, NOW, NOW, USER_A)


async def test_an_import_stores_the_importer_and_the_server_time_never_the_bundles() -> None:
    """Scenario: Client authorship never survives an import."""
    e = _env()
    owner = Actor(USER_A, "s1", frozenset(WRITE), is_owner=True)
    bundle = {"format": "cv-rule-bundle/1", "ir": _ir(name="imported", **CLAIMED)}
    rid = (await e.mgr.import_rule(bundle, owner))["id"]
    assert _authored(await _latest(e.mgr, rid)) == (USER_A, NOW, NOW, USER_A)


@pytest.mark.parametrize(("saver", "claimed"), [(USER_B, USER_A), (USER_A, USER_B)])
async def test_one_users_save_or_import_never_stores_the_other_users_authorship(
    saver: str, claimed: str
) -> None:
    """A Manager's create, update and import that name the other user as author store the saver."""
    e = _env(saver, perms=WRITE, owner=False, granted=frozenset({str(A)}))
    rid = e.create(created_by=claimed)
    assert _save(e, "update", rid, {"ir": _ir("2", created_by=claimed)}).status_code == 200
    manager = Actor(saver, "s1", frozenset(WRITE), granted_accounts=frozenset({str(A)}))
    bundle = {"ir": _ir(name="imported", created_by=claimed)}
    imported = (await e.mgr.import_rule(bundle, manager))["id"]
    for version in await e.mgr.versions(rid):
        assert _authored(await e.mgr.version(rid, version["id"])) == (saver, NOW, NOW, saver)
    assert _authored(await _latest(e.mgr, imported)) == (saver, NOW, NOW, saver)


async def test_an_actor_whose_id_is_not_a_uuid_stores_no_ir_author_never_the_bodys() -> None:
    e = _env("u1")
    rid = e.create(**CLAIMED)
    assert _authored(await _latest(e.mgr, rid)) == (None, NOW, NOW, "u1")


_ANY = st.none() | st.booleans() | st.integers() | st.text(max_size=8) | st.uuids().map(str)


@settings(deadline=None)
@given(
    op=st.sampled_from(["create", "update", "import"]),
    user=st.uuids(),
    claimed=st.tuples(_ANY, _ANY, _ANY),
)
async def test_no_client_authorship_survives_a_save_or_an_import_property(
    op: str, user: uuid.UUID, claimed: tuple[Any, Any, Any]
) -> None:
    """Whatever authorship a document claims, a stored version holds the acting user and the
    server's time, or the save is refused and stores nothing."""
    mgr = RulesManager(InMemoryRuleStore(), default_registry(), now_us=lambda: NOW)
    actor = Actor(str(user), "s1", frozenset(WRITE), is_owner=True)
    rid = (await mgr.create(_ir(name="base"), actor))["id"]
    keys = ("created_by", "created_at", "updated_at")
    ir = _ir("2", name="sent", **dict(zip(keys, claimed, strict=True)))
    try:
        if op == "create":
            rid = (await mgr.create(ir, actor))["id"]
        elif op == "update":
            await mgr.update(rid, ir, 1, actor)
        else:
            rid = (await mgr.import_rule({"ir": ir}, actor))["id"]
    except RuleError as refused:
        assert refused.status == 422
        assert [len(r.versions) for r in await mgr._s.all()] == [1]  # nothing stored
        return
    assert _authored(await _latest(mgr, rid)) == (str(user), NOW, NOW, str(user))


_OUTSIDE = {
    "bindings": {"exchange_account_ids": [str(A)]},
    "account_ids": [str(A)],
    "scope": {"account_ids": [str(A)]},
    "graph_layout": {"nodes": [{"id": "n1", "account_ids": []}]},
}


@pytest.mark.parametrize("op", ["create", "update"])
@pytest.mark.parametrize("member", list(_OUTSIDE))
def test_an_account_list_outside_ir_scope_is_refused_audited_and_stores_nothing(
    op: str, member: str
) -> None:
    """Scenario: A body key the server does not store is refused (an account list outside
    ir.scope.account_ids), whether `22` names the member or not."""
    e = _env()
    rid = e.create(name="base")
    r = _save(e, op, rid, {"ir": _ir("2", name="sent"), member: _OUTSIDE[member]})
    assert r.status_code == 422 and r.json()["code"] == "rule_ir_invalid"
    assert [(x["field"], x["rule"]) for x in r.json()["errors"]] == [
        (member, "accounts_outside_scope")
    ]
    record = {"rule_id": "" if op == "create" else rid, "op": op}
    assert e.audits[-1] == (
        "rule.scope_refused",
        record | {"reason": "accounts_outside_scope", "actor": USER_A},
    )
    assert _rows(e) == [("base", 1)]


@pytest.mark.parametrize(
    ("op", "member"),
    [("create", "zzz"), ("update", "zzz"), ("create", "expected_version"), ("update", "id")],
)
def test_a_member_22_does_not_name_is_refused_naming_it_audited_and_stores_nothing(
    op: str, member: str
) -> None:
    """Scenario: A body key the server does not store is refused (a key the contract does not
    name; `expected_version` is named on `updateRule` only)."""
    e = _env()
    rid = e.create(name="base")
    r = _save(e, op, rid, {"ir": _ir("2", name="sent"), member: 1})
    assert r.status_code == 422 and r.json()["code"] == "rule_ir_invalid"
    assert r.json()["errors"] == [
        {"field": member, "rule": "unknown_field", "message": r.json()["detail"]}
    ]
    assert e.audits[-1][0] == "rule.scope_refused"
    assert e.audits[-1][1]["reason"] == "unknown_field" and e.audits[-1][1]["op"] == op
    assert _rows(e) == [("base", 1)]


def test_a_refusal_names_a_member_only_by_a_plain_identifier_and_a_bounded_number() -> None:
    e = _env()
    body: dict[str, Any] = {"ir": _ir(), "a b": 1, "x" * 65: 1, "\u0101": 1, "fine_name": 1}
    body |= {f"k{i}": i for i in range(MAX_BODY_REFUSALS)}
    r = e.c.post("/rules", json=body)
    fields = [x["field"] for x in r.json()["errors"]]
    assert r.status_code == 422 and fields[:5] == ["$", "$", "$", "fine_name", "k0"]
    assert len(fields) == MAX_BODY_REFUSALS == 20


def test_every_member_22_names_is_taken_on_each_save_route() -> None:
    e = _env()
    named = {"description": "d", "scope": "symbol", "editor": "form", "tags": ["t"],
             "graph_layout": {"nodes": []}, "note": "n"}  # fmt: skip
    r = e.c.post("/rules", json={"name": "all", "ir": _ir(), **named})
    assert r.status_code == 201, r.text
    body = {"name": "all", "ir": _ir("2"), "expected_version": 1, **named}
    assert e.c.put(f"/rules/{r.json()['id']}", json=body).status_code == 200
    assert not [a for a, _ in e.audits if a == "rule.scope_refused"]


def test_the_refusal_is_written_with_the_scope_refusal_record_shape() -> None:
    """24 §15.5: the denial is `rules.scope_denied`, its before and after states shaped as every
    scope refusal's."""
    emitted: list[tuple[str, dict[str, Any]]] = []

    class _Emitter:
        async def emit(self, action: str, **record: Any) -> None:
            emitted.append((action, record))

    e = _env()
    e.mgr.set_hooks(audit=make_rules_audit(_Emitter()))
    r = e.c.post("/rules", json={"ir": _ir(), "bindings": _OUTSIDE["bindings"]})
    assert r.status_code == 422
    [(action, record)] = emitted
    assert action == "rules.scope_denied" and record["outcome"] == AuditOutcome.DENIED
    assert record["actor_user_id"] == USER_A and record["before_state"] is None
    assert record["after_state"] == {
        "rule_id": "",
        "op": "create",
        "reason": "accounts_outside_scope",
        "event": "rule.scope_refused",
    }


@pytest.mark.parametrize("op", ["create", "update"])
def test_a_caller_without_rules_write_is_refused_before_the_body_is_read(op: str) -> None:
    """Forbidden role, each route: a Viewer's save is `403`, nothing is stored or audited."""
    e = _env()
    rid = e.create(name="base")
    e.perms = frozenset({"rules:read"})
    body = {"ir": _ir("2", **CLAIMED), "bindings": _OUTSIDE["bindings"]}
    r = _save(e, op, rid, body)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert [action for action, _ in e.audits] == ["rule.created"]
    assert _rows(e) == [("base", 1)]


@pytest.mark.parametrize("op", ["create", "update"])
def test_a_managers_save_on_another_users_rule_or_an_ungranted_account_stores_nothing(
    op: str,
) -> None:
    """Cross-account, each route: B's update of A's rule is the unseen `404`, and a create naming
    an account outside B's grants is `403`; both are audited and nothing is stored."""
    e = _env()
    rid = e.create(name="base")
    e_b = _env(USER_B, perms=WRITE, owner=False, granted=frozenset({str(A)}))
    e_b.mgr = e.mgr
    scope = {"level": "account", "account_ids": [str(C)]}
    r = _save(e_b, op, rid, {"ir": _ir("2", name="sent", scope=scope, **CLAIMED)})
    assert r.status_code == (403 if op == "create" else 404)
    assert e.audits[-1][0] == "rule.scope_refused" and e.audits[-1][1]["actor"] == USER_B
    assert _rows(e) == [("base", 1)]


async def test_a_stored_rule_reads_back_only_while_it_lives_and_by_its_own_versions() -> None:
    """The reads a save relies on: a page after a cursor holds only the later rules, a version id
    the rule does not hold is `404` and changes nothing, and a deleted rule is no one's."""
    e = _env()
    first, second = sorted([e.create(name="one"), e.create(name="two")])
    assert [i["id"] for i in e.c.get(f"/rules?cursor={first}").json()["items"]] == [second]
    owner = Actor(USER_A, "s1", frozenset(WRITE), is_owner=True)
    with pytest.raises(RuleError) as missing:
        await e.mgr.set_active_version(first, str(uuid.UUID(int=0xDEAD)), "", owner)
    assert missing.value.status == 404 and sorted(_rows(e)) == [("one", 1), ("two", 1)]
    assert e.c.delete(f"/rules/{second}").status_code == 204
    deleted = await e.mgr._s.get(second)
    assert deleted is not None and not rule_visible(deleted, owner)
