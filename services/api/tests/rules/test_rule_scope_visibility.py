"""#4836 (E36-X01 G-6, G-10, G-14, G-15): the scope and visibility of rules and their accounts.

G-6: an action param naming an account takes the walker's spelling (the catalogue naming rule), and
the walker reads every value an account key holds wherever an action's params take any JSON. G-10:
an import keeps each account reference the importer is granted, as written, and refuses a bundle
naming any other. G-14: a rule's name conflicts only with a rule its caller owns or may read. G-15:
a quarantined rule's view carries its stored IR only in the form an export carries it. The conflict
response carries only the version and the time.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from typing import Any

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from candleviewer.rules.ir.accounts import collect_account_ids, redact_account_ids
from candleviewer.rules.ir.models import Rule, RuleScope
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleError, RulesManager
from candleviewer.rules.scope import summarize_scope
from candleviewer.rules.vocabulary import default_registry
from candleviewer.rules.vocabulary.catalogue import ACTIONS
from tests.rules.test_rules_routes import _ir
from tests.rules.test_scope import A, B, C

USER_A, USER_B = str(uuid.UUID(int=0xA)), str(uuid.UUID(int=0xB))
WRITE = frozenset({"rules:read", "rules:write"})
OWNER = Actor(str(uuid.UUID(int=0xF)), "s-owner", WRITE, is_owner=True)
#: The catalogue naming rule (G-6): a param naming an account is spelled `account_id` or
#: `account_ids`, alone or after a snake_case prefix (`target_account_id`).
NAMING_RULE = re.compile(r"(?:[a-z][a-z0-9]*_)*account_ids?")
#: A param name that mentions an account, however it is spelled.
MENTIONS_ACCOUNT = re.compile(r"acc(?:oun)?t", re.IGNORECASE)


def _manager(user: str, *granted: uuid.UUID) -> Actor:
    return Actor(user, f"s-{user}", WRITE, granted_accounts=frozenset(str(a) for a in granted))


def _mgr() -> tuple[RulesManager, list[tuple[str, dict[str, Any]]]]:
    audits: list[tuple[str, dict[str, Any]]] = []

    async def audit(action: str, payload: dict[str, Any]) -> None:
        audits.append((action, payload))

    return RulesManager(InMemoryRuleStore(), default_registry(), audit=audit), audits


async def _stored(m: RulesManager, rid: str) -> dict[str, Any]:
    """The IR the store holds for the newest version of `rid`."""
    return dict((await m.version(rid, (await m.versions(rid))[0]["id"]))["ir"])


# ----- G-6: the catalogue naming rule and the walker's coverage ------------------------------
def _misnamed(schema: Any) -> list[str]:
    """The catalogue naming rule as a lint: every property a JSON Schema declares, at any depth,
    whose name mentions an account but does not take the naming rule's spelling."""
    out: list[str] = []
    todo = [schema]
    while todo:
        cur = todo.pop()
        if isinstance(cur, dict):
            names = cur.get("properties")
            if isinstance(names, dict):
                out += [n for n in names if MENTIONS_ACCOUNT.search(n)]
            todo += cur.values()
        elif isinstance(cur, list):
            todo += cur
    return [n for n in out if not NAMING_RULE.fullmatch(n)]


def test_every_param_naming_an_account_in_the_catalogue_and_the_ir_takes_the_naming_rule() -> None:
    """Scenario: Every action's params_schema is walked (no catalogued field escapes the rule)."""
    assert {a.type: _misnamed(a.params_schema) for a in ACTIONS if _misnamed(a.params_schema)} == {}
    assert _misnamed(Rule.model_json_schema()) == []


@pytest.mark.parametrize(
    "name",
    ["account", "accounts", "target_account", "acct_id", "account_uuid", "account_name",
     "sub_account", "exchangeAccountId", "Account_Id", "account-id"],
)  # fmt: skip
def test_the_naming_rule_fails_a_param_naming_an_account_any_other_way_at_any_depth(
    name: str,
) -> None:
    """Scenario: ... a field named otherwise fails the catalogue naming rule."""
    nested = {"properties": {"algo": {"type": "array", "items": {"properties": {name: {}}}}}}
    assert _misnamed(nested) == [name]


def test_the_naming_rule_passes_each_spelling_it_allows() -> None:
    spelled = dict.fromkeys(("account_id", "account_ids", "target_account_id", "a_b2_account_ids"))
    assert _misnamed({"properties": spelled}) == []


def _holding(schema: dict[str, Any], key: str) -> tuple[dict[str, Any], list[str]]:
    """Params holding a distinct account under `key` at their root and inside every param whose
    schema takes any JSON (an object, an array or an untyped value), with the accounts placed."""
    refs = [str(uuid.UUID(int=0xACC0))]
    params: dict[str, Any] = {key: refs[0]}
    for name, sub in schema["properties"].items():
        if sub.get("type") in ("object", "array", None):
            refs.append(str(uuid.UUID(int=0xACC0 + len(refs))))
            nested = {"legs": [{key: [refs[-1]]}]}
            params[name] = [nested] if sub.get("type") == "array" else nested
    return params, refs


@settings(deadline=None, max_examples=40)
@given(key=st.from_regex(NAMING_RULE, fullmatch=True))
@example(key="account_ids")
@example(key="target_account_id")
def test_the_walker_matches_every_spelling_the_naming_rule_allows_in_every_actions_params(
    key: str,
) -> None:
    """Scenario: Every action's params_schema is walked: every field that can name an account is
    matched by the walker, for the grant check and for export stripping alike."""
    for spec in ACTIONS:
        params, refs = _holding(spec.params_schema, key)
        assert set(collect_account_ids(params)) == set(refs), spec.type
        assert not [r for r in refs if r in json.dumps(redact_account_ids(params))], spec.type


@pytest.mark.parametrize("held", [{"id": str(C)}, [{"legs": [str(C)]}], {"legs": {"x": str(C)}}])
async def test_every_value_an_account_key_holds_is_grant_checked_as_it_is_export_stripped(
    held: Any,
) -> None:
    ir = _ir(name="nested")
    ir["actions"][0]["params"]["target_account_id"] = held
    assert collect_account_ids(ir) == (str(C),)
    assert str(C) not in json.dumps(redact_account_ids(ir))
    m, _ = _mgr()
    with pytest.raises(RuleError) as refused:
        await m.create(ir, _manager(USER_A, A))
    assert refused.value.status == 403 and await m._s.all() == []


# ----- G-10: import keeps granted references, rejects the rest, remaps none -------------------
@pytest.mark.parametrize("importer", [_manager(USER_A, A, B, C), OWNER])
async def test_an_import_keeps_each_granted_reference_as_written_and_names_no_other(
    importer: Actor,
) -> None:
    """Scenario: Import keeps granted references, in the scope, a metric and an action param."""
    m, _ = _mgr()
    scope = {"level": "account", "account_ids": [str(A), str(B)], "environments": ["live"]}
    ir = _ir(name="imp", mode="armed", enabled=True, scope=scope)
    ir["conditions"]["left"]["account_id"] = str(B)
    ir["actions"][0]["params"]["target_account_id"] = str(A)
    out = await m.import_rule({"format": "cv-rule-bundle/1", "ir": ir}, importer)
    stored = await _stored(m, out["id"])
    assert stored["scope"]["account_ids"] == [str(A), str(B)]
    assert stored["conditions"]["left"]["account_id"] == str(B)
    assert stored["actions"][0]["params"]["target_account_id"] == str(A)
    assert collect_account_ids(stored) == (str(A), str(B))  # nothing remapped, nothing added
    assert (out["mode"], stored["scope"]["environments"]) == ("disabled", ["demo"])


@pytest.mark.parametrize("where", ["scope", "metric", "param", "nested"])
async def test_an_import_naming_a_granted_and_an_ungranted_account_refuses_the_ungranted_one(
    where: str,
) -> None:
    """Scenario: ... the ungranted reference is rejected with its reason: the bundle is refused and
    audited with the reason and the count of references refused, never their ids; nothing is
    stored, so nothing is remapped."""
    m, audits = _mgr()
    ir = _ir(name="imp", scope={"level": "account", "account_ids": [str(A)]})
    if where == "scope":
        ir["scope"]["account_ids"].append(str(C))
    elif where == "metric":
        ir["conditions"]["left"]["account_id"] = str(C)
    else:
        held = str(C) if where == "param" else {"legs": [str(C)]}
        ir["actions"][0]["params"]["target_account_id"] = held
    with pytest.raises(RuleError) as refused:
        await m.import_rule({"ir": ir}, _manager(USER_A, A))
    assert (refused.value.status, refused.value.code) == (403, "forbidden")
    refusal = {"actor": USER_A, "reason": "ungranted_account", "count": 1}
    assert audits == [("rule.import_refused", refusal)] and await m._s.all() == []


async def test_an_import_naming_no_account_lands_naming_none_and_covers_every_grant() -> None:
    """A bundle naming no account is never bound by the server: until its accounts are bound it
    applies to every account its owner is granted, as its scope summary says."""
    m, _ = _mgr()
    out = await m.import_rule({"ir": _ir(name="imp")}, _manager(USER_A, A, B))
    stored = await _stored(m, out["id"])
    assert collect_account_ids(stored) == ()
    summary = summarize_scope(RuleScope.model_validate(stored["scope"]))
    assert summary.startswith("all permitted accounts")


# ----- G-14: a name conflict names only a rule the caller owns or may read --------------------
async def test_a_name_only_another_users_unreadable_rule_holds_is_no_conflict() -> None:
    """Scenario: Conflicts name only readable rules (IDOR): B's create and rename never meet A's
    rules, so nothing B is answered names, counts or hints at them."""
    m, _ = _mgr()
    a, b = _manager(USER_A, A), _manager(USER_B, B)
    await m.create(_ir(name="Alpha"), a)
    await m.create(_ir(name="Gamma"), a)
    beta = (await m.create(_ir(name="Beta"), b))["id"]
    assert (await m.create(_ir(name="Alpha"), b))["name"] == "Alpha"
    assert (await m.update(beta, _ir("2", name="Gamma"), 1, b))["created"] is True
    assert sorted(r["name"] for r in (await m.list_rules(b))["items"]) == ["Alpha", "Gamma"]


async def test_a_name_a_rule_the_caller_may_read_or_owns_holds_is_still_a_conflict() -> None:
    """The Owner reads every rule, so meets A's; B meets B's own, even one B can no longer read."""
    m, _ = _mgr()
    await m.create(_ir(name="Alpha"), _manager(USER_A, A))
    lost = _ir(name="Delta", scope={"level": "account", "account_ids": [str(B)]})
    await m.create(lost, _manager(USER_B, B))
    for actor, name in ((OWNER, "Alpha"), (_manager(USER_B, C), "Delta")):
        with pytest.raises(RuleError) as taken:
            await m.create(_ir(name=name), actor)
        assert (taken.value.status, taken.value.code) == (409, "name_taken")


# ----- the conflict response carries only the version and the time ---------------------------
SAVED_US, SAVED_AT = 1_790_000_000_123_456, "2026-09-21T14:13:20.123456Z"
PRECONDITION = "If-Match / ETag precondition failed"  # 22's `PreconditionFailed` title


@pytest.mark.parametrize("owner_writes", [True, False])
async def test_a_conflict_after_another_users_save_carries_only_the_version_and_the_time(
    owner_writes: bool,
) -> None:
    """The conflict response carries only the version and the time: after another user saves a
    version, a stale save is answered with that version and the time it was saved."""
    now = [1_000_000]
    m = RulesManager(InMemoryRuleStore(), default_registry(), now_us=lambda: now[0])
    owner_a = _manager(USER_A, A)
    writer, stale_saver = (OWNER, owner_a) if owner_writes else (owner_a, OWNER)
    rid = (await m.create(_ir(name="mine"), owner_a))["id"]
    now[0] = SAVED_US
    await m.update(rid, _ir("2", name="mine"), 1, writer)
    with pytest.raises(RuleError) as stale:
        await m.update(rid, _ir("3", name="mine"), 1, stale_saver)
    assert (stale.value.status, stale.value.code) == (412, "version_conflict")
    assert stale.value.extra == {"version": 2, "updated_at": SAVED_AT, "title": PRECONDITION}
    answer = json.dumps([stale.value.message, stale.value.extra])
    assert writer.user_id not in answer and writer.session_id not in answer


@pytest.mark.parametrize("held", [None, "soon", True, 10**18])
async def test_a_conflict_on_a_version_holding_no_readable_time_carries_none(held: Any) -> None:
    """A stored version whose `updated_at` is missing, not an integer or out of range answers a
    stale save with its version and no time."""
    m, _ = _mgr()
    rid = (await m.create(_ir(name="t"), OWNER))["id"]
    await m.update(rid, _ir("2", name="t"), 1, OWNER)
    row = await m._s.get(rid)
    assert row is not None
    row.versions[-1].ir["updated_at"] = held
    with pytest.raises(RuleError) as stale:
        await m.update(rid, _ir("3", name="t"), 1, OWNER)
    assert (stale.value.extra["version"], stale.value.extra["updated_at"]) == (2, None)


# ----- G-15: a quarantined rule's view is the export form only --------------------------------
async def test_a_quarantined_rules_view_carries_only_the_export_form_of_its_stored_ir() -> None:
    """Scenario: A quarantined rule's export is stripped: for its owner and for the Owner, on get
    and on list, export_json is what an export carries; the stored IR is never changed; another
    user never reads it (cross-user)."""
    m, _ = _mgr()
    owner_a = _manager(USER_A, A, B)
    ir = _ir(name="q", scope={"level": "account", "account_ids": [str(A)]})
    ir["conditions"]["left"]["account_id"] = str(B)
    rid = (await m.create(ir, owner_a))["id"]
    row = await m._s.get(rid)
    assert row is not None
    row.versions[0].ir |= {"mode": "armed", "enabled": True, "zzz": {"account_ids": [str(A)]}}
    row.versions[0].ir["scope"]["environments"] = ["demo", "live"]
    stored = copy.deepcopy(row.versions[0].ir)
    for reader in (owner_a, OWNER):
        exported = (await m.export_rule(rid, reader))["ir"]
        for view in (await m.get(rid, reader), (await m.list_rules(reader))["items"][0]):
            assert view["quarantined"] and view["export_json"] == exported
            assert str(A) not in json.dumps(view) and str(B) not in json.dumps(view)
    assert exported["scope"]["environments"] == ["demo"] and "created_by" not in exported
    assert row.versions[0].ir == stored
    other = _manager(USER_B, A, B)
    with pytest.raises(RuleError) as unseen:
        await m.get(rid, other)
    assert unseen.value.status == 404 and (await m.list_rules(other))["items"] == []


@pytest.mark.parametrize(
    ("stored", "exported"),
    [
        ([{"account_ids": [str(A)]}, "x"], [{}, "x"]),
        (
            {"scope": [str(A)], "account_id": str(A)},
            {"scope": {"environments": ["demo"]}, "mode": "disabled", "enabled": False},
        ),
    ],
)
async def test_a_stored_ir_of_any_shape_is_shown_and_exported_in_the_export_form(
    stored: Any, exported: Any
) -> None:
    """A store may hold any JSON as a version's IR: a scope that is not an object becomes the
    demo scope, and no account reference survives in the view or the export."""
    m, _ = _mgr()
    rid = (await m.create(_ir(name="odd"), OWNER))["id"]
    row = await m._s.get(rid)
    assert row is not None
    row.versions[0].ir = stored
    view = await m.get(rid, OWNER)
    assert view["export_json"] == exported == (await m.export_rule(rid, OWNER))["ir"]


# ----- the export scan's server leg (E36-X02) ------------------------------------------------
KNOWN = tuple(str(uuid.UUID(int=0xACC1 + i)) for i in range(3))  # the accounts the fixture knows
_REF = st.sampled_from(KNOWN)
_PLAIN = st.sampled_from(["note", "legs", "x"])
_HELD = st.recursive(
    _REF, lambda v: st.lists(v, max_size=2) | st.dictionaries(_PLAIN, v, max_size=2)
)
_JSON = st.recursive(
    st.integers(0, 9) | st.sampled_from(["a", "b"]),
    lambda v: (
        st.lists(v, max_size=2)
        | st.dictionaries(_PLAIN, v, max_size=2)
        | st.dictionaries(st.from_regex(NAMING_RULE, fullmatch=True), _HELD, min_size=1, max_size=2)
    ),
    max_leaves=6,
)


@settings(deadline=None, max_examples=60)
@given(
    scope=st.lists(_REF, unique=True, max_size=3),
    metric=st.none() | _REF,
    params=st.dictionaries(_PLAIN, _JSON, max_size=2),
    quarantined=st.booleans(),
)
async def test_no_known_account_id_reaches_an_export_or_an_export_json_property(
    scope: list[str], metric: str | None, params: dict[str, Any], quarantined: bool
) -> None:
    """Whatever account references a rule holds, in its scope, a metric or its action params at
    any depth, no account id the fixture knows is in its export or, quarantined, its view."""
    m, _ = _mgr()
    ir = _ir(name="p", scope={"level": "account", "account_ids": scope})
    ir["conditions"]["left"]["account_id"] = metric
    ir["actions"][0]["params"] |= params
    rid = (await m.create(ir, OWNER))["id"]
    row = await m._s.get(rid)
    assert row is not None
    if quarantined:
        row.versions[0].ir["zzz"] = {"account_ids": list(KNOWN)}
    views = [await m.get(rid, OWNER), *(await m.list_rules(OWNER))["items"]]
    assert all(("export_json" in v) is quarantined for v in views)
    blob = json.dumps([await m.export_rule(rid, OWNER), views])
    assert not [a for a in KNOWN if a in blob]
