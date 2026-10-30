"""#4836 (E36-X01 G-6, G-10, G-14, G-15): the scope and visibility of rules and their accounts.

G-6: an action param naming an account takes the walker's spelling (the catalogue naming rule), and
the walker reads what an account key holds wherever an action's params take any JSON: values, and
the UUID-shaped keys of a held object. G-10: an import keeps each account reference the importer is
granted, as written, and refuses a bundle naming any other. G-14: a rule's name conflicts only with
a rule its caller owns or may read. G-15: a quarantined rule's view carries its stored IR only in
the form an export carries it. The conflict response carries only the version and the time. The
export strips by an allow-list of IR keys, and an import needs its ir_version, ignores the keys the
server sets and lands at version 1; it weighs a bundle in one order, and waits a bounded time for
each refusal's record.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
import uuid
from typing import Any

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.rules import manager as rules_manager
from candleviewer.rules.ir import ir_hash
from candleviewer.rules.ir.accounts import collect_account_ids, redact_account_ids
from candleviewer.rules.ir.models import Rule, RuleScope
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleError, RulesManager
from candleviewer.rules.scope import summarize_scope
from candleviewer.rules.vocabulary import default_registry
from candleviewer.rules.vocabulary.catalogue import ACTIONS
from tests.rules.test_rules_routes import _ir
from tests.rules.test_scope import A, B, C

#: Apart from every account id (`A`, `B` and `C` are 10, 11 and 12), so a user never passes for one.
USER_A, USER_B = str(uuid.UUID(int=0xA1)), str(uuid.UUID(int=0xB1))
WRITE = frozenset({"rules:read", "rules:write"})
OWNER = Actor(str(uuid.UUID(int=0xF)), "s-owner", WRITE, is_owner=True)
#: The catalogue naming rule (G-6): a param naming an account is spelled `account_id` or
#: `account_ids`, alone or after a snake_case prefix (`target_account_id`).
NAMING_RULE = re.compile(r"(?:[a-z][a-z0-9]*_)*account_ids?")
#: The words this domain and the exchange use for an account, as the catalogue's module docstring
#: lists them: `account`, `acct` or `wallet` anywhere in a name ...
MENTIONS_ACCOUNT = re.compile(r"acc(?:oun)?t|wallet", re.IGNORECASE)
#: ... or `acc`, `accid`, `acnt`, `uid`, `subuid`, `member` or `memberid`, plural too, as a whole
#: word of a snake_case, kebab-case or camelCase name: `subUid` holds one, `liquidity` none.
ACCOUNT_WORD = re.compile(r"(?:acc|accid|acnt|uid|subuid|member|memberid)s?")


def _mentions_account(name: str) -> bool:
    """Whether a param name mentions an account, however it is spelled."""
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name).lower()
    whole = any(ACCOUNT_WORD.fullmatch(w) for w in re.split(r"[^a-z]+", words))
    return whole or MENTIONS_ACCOUNT.search(name) is not None


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
                out += [n for n in names if _mentions_account(n)]
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
     "sub_account", "exchangeAccountId", "Account_Id", "account-id", "uid", "sub_uid", "subUid",
     "parentUID", "member_id", "subMemberIds", "wallet", "wallet_id", "acc_id", "accid",
     "acnt_id", "exchange_acc"],
)  # fmt: skip
def test_the_naming_rule_fails_a_param_naming_an_account_any_other_way_at_any_depth(
    name: str,
) -> None:
    """Scenario: ... a field named otherwise fails the catalogue naming rule, by any word this
    domain or the exchange uses for an account."""
    nested = {"properties": {"algo": {"type": "array", "items": {"properties": {name: {}}}}}}
    assert _misnamed(nested) == [name]


def test_the_naming_rule_passes_each_spelling_it_allows() -> None:
    """The naming rule's own spellings pass, and so does a name holding the letters of a short
    account word inside another word (it mentions no account)."""
    spelled = ("account_id", "account_ids", "target_account_id", "a_b2_account_ids")
    unrelated = ("liquidity", "fluid", "remember", "accept", "uuid", "node_id")
    assert _misnamed({"properties": dict.fromkeys(spelled + unrelated)}) == []


def _holding(schema: dict[str, Any], key: str, keyed: bool) -> tuple[dict[str, Any], list[str]]:
    """Params holding a distinct account under `key` at their root and inside every param whose
    schema takes any JSON (an object, an array or an untyped value), with the accounts placed:
    each as a value, or `keyed`, as the key of an object the account key holds."""

    def held(ref: str) -> Any:
        return {ref: None} if keyed else ref

    refs = [str(uuid.UUID(int=0xACC0))]
    params: dict[str, Any] = {key: held(refs[0])}
    for name, sub in schema["properties"].items():
        if sub.get("type") in ("object", "array", None):
            refs.append(str(uuid.UUID(int=0xACC0 + len(refs))))
            nested = {"legs": [{key: [held(refs[-1])]}]}
            params[name] = [nested] if sub.get("type") == "array" else nested
    return params, refs


@settings(deadline=None, max_examples=40)
@given(key=st.from_regex(NAMING_RULE, fullmatch=True), keyed=st.booleans())
@example(key="account_ids", keyed=False)
@example(key="target_account_id", keyed=True)
def test_the_walker_matches_every_spelling_the_naming_rule_allows_in_every_actions_params(
    key: str, keyed: bool
) -> None:
    """Scenario: Every action's params_schema is walked: every field that can name an account is
    matched by the walker, for the grant check and for export stripping alike, an account held
    as a value or in key position."""
    for spec in ACTIONS:
        params, refs = _holding(spec.params_schema, key, keyed)
        assert set(collect_account_ids(params)) == set(refs), spec.type
        assert not [r for r in refs if r in json.dumps(redact_account_ids(params))], spec.type


@pytest.mark.parametrize(
    "held", [{"id": str(C)}, [{"legs": [str(C)]}], {"legs": {"x": str(C)}}, {str(C): None}]
)
async def test_every_value_an_account_key_holds_is_grant_checked_as_it_is_export_stripped(
    held: Any,
) -> None:
    """What an account key holds is read at any depth, values and the UUID-shaped keys of a held
    object (a plain key such as `id` is no account), for the grant check as for the strip."""
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


@pytest.mark.parametrize("where", ["scope", "metric", "param", "nested", "keyed"])
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
        held = {"param": str(C), "nested": {"legs": [str(C)]}, "keyed": {str(C): None}}[where]
        ir["actions"][0]["params"]["target_account_id"] = held
    with pytest.raises(RuleError) as refused:
        await m.import_rule({"ir": ir}, _manager(USER_A, A))
    assert (refused.value.status, refused.value.code) == (403, "forbidden")
    refusal = {"actor": USER_A, "reason": "ungranted_account", "count": 1}
    assert audits == [("rule.import_refused", refusal)] and await m._s.all() == []


@pytest.mark.parametrize("lacks", ["ir_version", "an object ir"])
async def test_an_import_naming_an_ungranted_account_is_the_audited_403_whatever_else_it_lacks(
    lacks: str,
) -> None:
    """The grant check comes first (C-12.4): a bundle naming an ungranted account that also carries
    no `ir_version`, or whose `ir` is a list, is the audited `403`, and nothing is stored."""
    m, audits = _mgr()
    ir: Any = _ir(name="imp", scope={"level": "account", "account_ids": [str(A), str(C)]})
    del ir["ir_version"]
    if lacks == "an object ir":
        ir = [ir]
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


# ----- the export strips by an allow-list of IR keys; an import lands at version 1 ----------
#: The `Rule` fields the server sets on every stored version: its id, its revision and its
#: authorship. Every other field of the model is an IR key, `ir_version` among them.
SERVER_SET = frozenset({"rule_id", "version", "created_by", "created_at", "updated_at"})
IR_KEYS = frozenset(Rule.model_fields) - SERVER_SET


def _meaning(ir: dict[str, Any]) -> dict[str, Any]:
    """What a rule says, less its accounts and its environments: its trigger, conditions, actions,
    limits and the rest of its scope."""
    parts = ("trigger", "conditions", "actions", "limits", "scope")
    out: dict[str, Any] = redact_account_ids({k: ir[k] for k in parts})
    del out["scope"]["environments"]
    return out


async def test_an_export_round_trips_to_a_disabled_demo_rule_at_version_one() -> None:
    """Another user's import of an export lands disabled, on demo, at version 1 (hashed as
    stored) under a new rule id, and says what the source says but for its accounts."""
    m, _ = _mgr()
    owner_a = _manager(USER_A, A, B)
    scope = {"level": "account", "account_ids": [str(A)], "symbols": ["BTCUSDT"],
             "applies_to": "open_positions", "environments": ["demo", "live"],
             "exclude_algo_children": False}  # fmt: skip
    src = _ir(name="src", scope=scope, limits={"cooldown_ms": 5000, "max_fires_per_hour": 7})
    src["conditions"]["left"]["account_id"] = str(B)
    src["actions"][0]["params"]["target_account_id"] = str(A)
    rid = (await m.create(src, owner_a))["id"]
    for edit in (1, 2):
        await m.update(rid, {**src, "description": f"edit {edit}"}, edit, owner_a)
    out = await m.import_rule(await m.export_rule(rid, owner_a), _manager(USER_B, C))
    source, landed = await _stored(m, rid), await _stored(m, out["id"])
    assert (source["version"], out["id"] != rid, landed["rule_id"]) == (3, True, out["id"])
    assert (out["mode"], landed["mode"], landed["enabled"]) == ("disabled", "disabled", False)
    assert landed["scope"]["environments"] == ["demo"] and _meaning(landed) == _meaning(source)
    versions = await m.versions(out["id"])
    assert [v["version"] for v in versions] == [landed["version"]] == [1]
    assert versions[0]["ir_hash"] == ir_hash(landed)


@pytest.mark.parametrize(
    "carried",
    [{}, {"version": 0}, {"version": "3"}, {"rule_id": "r-1"}, {"created_at": "x"},
     {"created_by": "x", "updated_at": 1.5}, dict.fromkeys(SERVER_SET, "x")],
)  # fmt: skip
async def test_an_import_ignores_the_rule_id_version_and_authorship_a_bundle_carries(
    carried: dict[str, Any],
) -> None:
    """A bundle carrying a rule id, a version or authorship (its source's, or any other value,
    malformed included) imports cleanly with each ignored: the rule lands under a new rule id at
    version 1, hashed as stored, authored by the importer at the server's time, and the source is
    untouched."""
    now = [SAVED_US]
    m = RulesManager(InMemoryRuleStore(), default_registry(), now_us=lambda: now[0])
    owner_a = _manager(USER_A, A)
    rid = (await m.create(_ir(name="src"), owner_a))["id"]
    await m.update(rid, _ir("2", name="src"), 1, owner_a)
    source = await _stored(m, rid)  # its rule id, version 2 and authorship, all carried below
    now[0] += 1
    bundle = {"format": "cv-rule-bundle/1", "ir": source | carried}
    out = await m.import_rule(bundle, _manager(USER_B, A))
    landed, versions = await _stored(m, out["id"]), await m.versions(out["id"])
    assert out["id"] != rid and landed["rule_id"] == out["id"]
    assert [v["version"] for v in versions] == [landed["version"]] == [1]
    assert versions[0]["ir_hash"] == ir_hash(landed)
    authored = (landed["created_by"], landed["created_at"], landed["updated_at"])
    assert authored == (USER_B, now[0], now[0]) and await _stored(m, rid) == source


async def test_an_exported_bundle_holds_only_ir_keys() -> None:
    """The export strips by an allow-list of IR keys, built from the IR model's own fields less
    the ones the server sets, so a field the server adds to a stored version is never exported;
    `ir_version`, the schema an import validates against, stays. export_json takes the same form."""
    m, _ = _mgr()
    rid = (await m.create(_ir(name="src"), OWNER))["id"]
    await m.update(rid, _ir("2", name="src"), 1, OWNER)
    row = await m._s.get(rid)
    assert row is not None
    row.versions[-1].ir["etag"] = '"2"'  # a field a later server stores beside the IR's own
    bundle = await m.export_rule(rid, OWNER)
    assert set(bundle["ir"]) == IR_KEYS and bundle["ir"]["ir_version"] == 1
    assert (await m.get(rid, OWNER))["export_json"] == bundle["ir"]


@pytest.mark.parametrize("carried", [2, None])
async def test_an_import_validates_the_ir_version_a_bundle_carries(carried: int | None) -> None:
    """`ir_version` is read as the bundle carries it, never supplied: a version the server does not
    read, `null` among them (carried, so not missing), is refused 422 at its path (AC-RA-08),
    unaudited as a value the model refuses is, and nothing is stored."""
    m, audits = _mgr()
    bundle = {"format": "cv-rule-bundle/1", "ir": _ir(name="imp", ir_version=carried)}
    with pytest.raises(RuleError) as refused:
        await m.import_rule(bundle, OWNER)
    assert (refused.value.status, refused.value.extra.get("path")) == (422, "/ir_version")
    assert audits == [] and await m._s.all() == []


@pytest.mark.parametrize("importer", [_manager(USER_A, A), OWNER])
async def test_an_import_refuses_a_bundle_that_carries_no_ir_version(importer: Actor) -> None:
    """`ir_version` is never supplied or defaulted on import: a bundle carrying none is refused as
    a bundle missing any other required key is, `422 rule_ir_invalid` at its path, audited as the
    ungranted-account refusal is, and nothing is stored."""
    m, audits = _mgr()
    unnamed, ir = _ir(), _ir(name="imp")
    del unnamed["name"], ir["ir_version"]
    with pytest.raises(RuleError) as missing:  # the model's own answer to a missing key
        await m.import_rule({"ir": unnamed}, importer)
    with pytest.raises(RuleError) as refused:
        await m.import_rule({"format": "cv-rule-bundle/1", "ir": ir}, importer)
    answer = (refused.value.status, refused.value.code, refused.value.message)
    assert answer == (422, "rule_ir_invalid", missing.value.message)
    assert refused.value.extra == {"path": "/ir_version"}
    refusal = {"actor": importer.user_id, "reason": "ir_version_missing", "count": 1}
    assert audits == [("rule.import_refused", refusal)] and await m._s.all() == []


# ----- an import weighs a bundle in one order and bounds each refusal's record ---------------
#: Bundles with no object `ir`, or whose scope is not an object, each with the path its refusal
#: names: the bundle's own `ir` member, or the IR's `scope` as a save names it.
_SHAPES: dict[str, tuple[dict[str, Any], str]] = {
    "no ir": ({"format": "cv-rule-bundle/1"}, "/ir"),
    "ir a string": ({"ir": "ir_version"}, "/ir"),
    "ir a list": ({"ir": [1]}, "/ir"),
    "scope a scalar": ({"ir": _ir(name="imp", scope=5)}, "/scope"),
    "scope a list": ({"ir": _ir(name="imp", scope=[["level", "account"]])}, "/scope"),
}


def _model_words(doc: Any) -> str:
    """How `_validated` words the model's first refusal of `doc`."""
    with pytest.raises(ValidationError) as refused:
        Rule.model_validate(doc)
    return f"The rule document is not valid: {refused.value.errors()[0]['msg']}"


@pytest.mark.parametrize("shape", list(_SHAPES))
async def test_an_import_refuses_a_bundle_whose_ir_or_scope_is_no_object_unaudited(
    shape: str,
) -> None:
    """A bundle with no `ir`, or whose `ir` or `scope` is not an object (a list of pairs neither),
    is refused `422 rule_ir_invalid` in the words `_validated` gives the model's refusal, before
    any read that takes it for an object: unaudited, as a shape failure on create is, and nothing
    is stored."""
    bundle, path = _SHAPES[shape]
    m, audits = _mgr()
    with pytest.raises(RuleError) as refused:
        await m.import_rule(copy.deepcopy(bundle), _manager(USER_A, A))
    answer = (refused.value.status, refused.value.code, refused.value.message)
    assert answer == (422, "rule_ir_invalid", _model_words(bundle.get("ir", {})))
    assert refused.value.extra == {"path": path}
    assert audits == [] and await m._s.all() == []


@pytest.mark.parametrize("reason", ["ungranted_account", "ir_version_missing"])
@pytest.mark.parametrize("hook", ["stalls", "raises"])
async def test_an_import_refusal_whose_record_is_not_written_in_time_is_unrecorded(
    reason: str, hook: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.9: each import refusal waits at most `REFUSAL_AUDIT_TIMEOUT_S` for its record, as a scope
    refusal does: a hook that stalls past the bound, or raises, is `RuleRefusalUnrecorded` (the
    routes' `503`), and nothing is stored."""
    m, _ = _mgr()
    seen: list[tuple[str, str]] = []
    down = ConnectionError("audit down")

    async def broken(action: str, payload: dict[str, Any]) -> None:
        seen.append((action, payload["reason"]))
        if hook == "raises":
            raise down
        await asyncio.Event().wait()  # never set: only the bound ends this wait

    m.set_hooks(audit=broken)
    monkeypatch.setattr(rules_manager, "REFUSAL_AUDIT_TIMEOUT_S", 0.0)
    ir = _ir(name="imp", scope={"level": "account", "account_ids": [str(C)]})
    if reason == "ir_version_missing":
        ir = _ir(name="imp")
        del ir["ir_version"]
    async with asyncio.timeout(1):  # the test's own guard: the record's bound ends the wait first
        with pytest.raises(rules_manager.RuleRefusalUnrecorded) as unrecorded:
            await m.import_rule({"ir": ir}, _manager(USER_A, A))
    cause = unrecorded.value.__cause__
    assert (cause is down) if hook == "raises" else isinstance(cause, TimeoutError)
    assert seen == [("rule.import_refused", reason)] and await m._s.all() == []
