"""#5691 (E35, C-12.4): a rule's scope lists at most 100 accounts and 3 environments, each once.

A save (create, update, an import), validate and compile hold `account_ids` to the bound and to one
entry per account, as the model holds anything: a longer list or a repeat is `422 rule_ir_invalid`
at `/scope/account_ids` (validate: `200` with `valid: false`), decided on the list alone before the
scope check, for every role, with no record and no count. `environments` is held the same way at
`/scope/environments`. A list within the bound still meets the grant check of each account it
names, and every reader takes it as sent. A stored version that breaks a bound is quarantined:
read-only, disarmed, never evaluated, never clamped or edited.
"""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import Response
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.api.rules import make_rules_router
from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.rules.compiler.common import MAX_ITEMS
from candleviewer.rules.ir import Rule, ir_hash
from candleviewer.rules.ir.accounts import collect_account_ids
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleError, RulesManager
from candleviewer.rules.runner import EvalTick, _instances
from candleviewer.rules.scope import AuditSink, ScopeResolver, ScopeState, summarize_scope
from candleviewer.rules.scope_state import SnapshotScopeState
from candleviewer.rules.vocabulary import default_registry
from tests.rules._check_limiter import unthrottled

FIX = Path(__file__).parents[1] / "fixtures/rule_ir"
REG = default_registry()
#: The ruled bound (#5691, BQ-1); only `test_the_test_bound_is_the_constant` reads the model's.
BOUND = 100
RULE_ID = "00000000-0000-4000-8000-000000000001"  # form_simple_0's own rule_id
OWNER_ID, MANAGER_ID = uuid.UUID(int=1), uuid.UUID(int=2)
A, C = uuid.UUID(int=10), uuid.UUID(int=12)  # every caller holds a grant on A by default, none on C
PERMS = frozenset({"rules:read", "rules:write"})
OWNER = Actor(str(OWNER_ID), "s-owner", PERMS, is_owner=True)
MANAGER = Actor(str(MANAGER_ID), "s-manager", PERMS, frozenset({str(A)}))
ACTORS = pytest.mark.parametrize("actor", [OWNER, MANAGER], ids=["owner", "manager"])
SAVES = pytest.mark.parametrize("op", ["create", "update"])
PATH = "/scope/account_ids"
#: How `_validated` words the model's refusal; a refusal's `detail` is this and its message, whole.
NOT_VALID = "The rule document is not valid: "
REPEAT = "List each account once."
#: Each list the model refuses -> the refusal's message. `repeat_apart` names the account twice
#: with another between, so only a check of every pair, not of neighbours, refuses it.
MESSAGES = {
    "repeat": REPEAT,
    "repeat_apart": REPEAT,
    "past_the_bound": f"Tuple should have at most {BOUND} items after validation, not {BOUND + 1}",
}
LISTS = pytest.mark.parametrize("name", sorted(MESSAGES))
#: The ruled bound on a scope's environments (the orchestrator's addition to #5691). The scope
#: names three at most, so a list past it repeats one.
ENVIRONMENTS = 3
ENVIRONMENTS_PATH = "/scope/environments"
#: Environment lists the model refuses -> (the list sent, the refusal's message). `repeat_apart`
#: repeats without passing the length bound.
ENVIRONMENT_LISTS = {
    "repeat": (["demo", "demo"], "List each environment once."),
    "repeat_apart": (["demo", "live", "demo"], "List each environment once."),
    "live_twice": (["live", "live"], "List each environment once."),
    "past_the_bound": (
        ["demo", "testnet", "live", "demo"],
        f"Tuple should have at most {ENVIRONMENTS} items after validation, not {ENVIRONMENTS + 1}",
    ),
}
ENVIRONMENT_NAMES = pytest.mark.parametrize("name", sorted(ENVIRONMENT_LISTS))
#: Spellings of one id that read as the same UUID: the model parses before it compares.
SPELLINGS: dict[str, Callable[[str], str]] = {
    "upper_case": str.upper,
    "no_hyphens": lambda text: text.replace("-", ""),
    "braced": lambda text: "{" + text + "}",
    "urn": lambda text: "urn:uuid:" + text,
}
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def _distinct(n: int) -> list[str]:
    return [str(uuid.UUID(int=0x1000 + i)) for i in range(n)]


def _refused(name: str, account: uuid.UUID = A) -> list[str]:
    """The list `name` names, around `account`: it twice (the second time after another one, for
    `repeat_apart`), or it and `BOUND` others."""
    if name == "repeat":
        return [str(account), str(account)]
    if name == "repeat_apart":
        return [str(account), *_distinct(1), str(account)]
    return [str(account), *_distinct(BOUND)]


def _ir(ids: list[str], environments: list[str] | None = None, **over: Any) -> dict[str, Any]:
    """`form_simple_0`, saveable, its scope listing `ids` (and naming `environments`, if given)."""
    raw: dict[str, Any] = json.loads((FIX / "form_simple_0.json").read_text(encoding="utf-8"))
    raw["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
    raw["scope"] = {"level": "account", "account_ids": ids}
    if environments is not None:
        raw["scope"]["environments"] = environments
    return {**raw, **over}


def _names_no_account(ids: Iterable[str], text: str) -> None:
    """The refusal names no account (22 `RuleIrScope`, 24 §19.123): none of `ids` is in `text`."""
    assert [one for one in ids if one.lower() in text.lower()] == []


class _Watched(ScopeResolver):
    """The real scope resolver, noting each account list it is asked to authorize."""

    def __init__(self, state: ScopeState, audit: AuditSink) -> None:
        super().__init__(state, audit)
        self.asked: list[list[uuid.UUID]] = []

    async def authorize_accounts(self, caller: uuid.UUID, account_ids: Iterable[uuid.UUID]) -> None:
        ids = list(account_ids)
        self.asked.append(ids)
        await super().authorize_accounts(caller, ids)


class _Api:
    """The save routes (`c`) and the checks (`checks`) over one in-memory manager and the real
    scope resolver, whose grant source gives every caller `granted` (A by default). It is the
    checks' principal too: `rules:read`, its user id the actor's."""

    def __init__(self, actor: Actor, granted: Iterable[str] = (str(A),)) -> None:
        self.granted = [uuid.UUID(a) for a in granted]
        self.audits: list[tuple[str, dict[str, Any]]] = []
        self.denials: list[tuple[str, dict[str, str]]] = []
        self.refreshed: list[uuid.UUID] = []
        self.capped: list[str] = []
        self.state = SnapshotScopeState(self, "demo")
        self.resolver = _Watched(self.state, self._deny)
        if not actor.is_owner:
            actor = replace(actor, granted_accounts=frozenset(map(str, self.granted)))
        self.actor, self.user_id = actor, uuid.UUID(actor.user_id)
        self.mgr = RulesManager(InMemoryRuleStore(), REG, audit=self._audit)
        crud, checks = FastAPI(), FastAPI()
        crud.include_router(
            make_rules_crud_router(
                lambda: self.mgr,
                lambda _request: actor,
                scope_resolver=lambda: self.resolver,
                scope_refresh=self._refresh,
                on_cap_refused=self.capped.append,
            )
        )
        checks.include_router(
            make_rules_router(
                lambda: REG,
                principal_resolver=self,
                scope_resolver=self.resolver,
                scope_refresh=self._refresh,
                check_limiter=unthrottled(),
                on_cap_refused=self.capped.append,
            )
        )
        self.c, self.checks = TestClient(crud), TestClient(checks)

    def has(self, permission: str) -> bool:
        return permission == "rules:read"

    def resolve(self, request: Request) -> _Api:
        return self

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        return [(a, True, False) for a in self.granted]

    async def load_permissions(self, owner: uuid.UUID) -> frozenset[str]:
        return frozenset({"rules:read"})

    async def _audit(self, action: str, payload: dict[str, Any]) -> None:
        self.audits.append((action, payload))

    async def _deny(self, event: str, data: dict[str, str]) -> None:
        self.denials.append((event, data))

    async def _refresh(self, owner: uuid.UUID) -> None:
        self.refreshed.append(owner)
        await self.state.refresh(owner)

    def stored(self, rid: str, version: int) -> list[str]:
        """The `account_ids` of the rule's stored `version`."""
        items = self.c.get(f"/rules/{rid}/versions").json()["items"]
        vid = next(v["id"] for v in items if v["version"] == version)
        ir: dict[str, Any] = self.c.get(f"/rules/{rid}/versions/{vid}").json()["ir"]
        return list(ir["scope"]["account_ids"])

    def unchecked(self) -> bool:
        """Whether nothing read a grant, refreshed one, wrote a scope record or counted a cap."""
        return (self.resolver.asked, self.refreshed, self.denials, self.capped) == ([], [], [], [])


def _save(
    api: _Api, op: str, ids: list[str], environments: list[str] | None = None
) -> tuple[Response, str | None]:
    """The answer to a save whose scope lists `ids` and names `environments`; an update edits a
    rule saved on A first."""
    if op == "create":
        return api.c.post("/rules", json={"ir": _ir(ids, environments)}), None
    made = api.c.post("/rules", json={"ir": _ir([str(A)])})
    assert made.status_code == 201, made.text[:300]
    rid: str = made.json()["id"]
    api.resolver.asked.clear()
    api.refreshed.clear()
    sent = {"ir": _ir(ids, environments)}
    return api.c.put(f"/rules/{rid}", json=sent, headers={"If-Match": "1"}), rid


def _assert_refused_and_nothing_stored(
    api: _Api,
    op: str,
    path: str,
    message: str,
    ids: list[str],
    environments: list[str] | None = None,
) -> None:
    """The save is the 422 at `path`, its `detail` the model's `message` whole and naming no
    account; nothing is stored, read, recorded or counted."""
    answer, rid = _save(api, op, ids, environments)
    assert answer.status_code == 422, answer.text[:300]
    assert answer.headers["content-type"] == "application/problem+json"
    body = answer.json()
    assert (body["code"], body["path"]) == ("rule_ir_invalid", path)
    assert body["detail"] == NOT_VALID + message
    _names_no_account(ids, answer.text)
    assert api.unchecked()
    if rid is None:
        assert api.c.get("/rules").json()["items"] == [] and api.audits == []
    else:
        assert api.c.get(f"/rules/{rid}").json()["latest_version"] == 1
        assert [action for action, _ in api.audits] == ["rule.created"]


@ACTORS
@SAVES
@pytest.mark.parametrize("name", ["repeat", "repeat_apart"])
def test_save_with_one_account_listed_twice_is_422_naming_account_ids_and_stores_nothing(
    name: str, op: str, actor: Actor
) -> None:
    _assert_refused_and_nothing_stored(_Api(actor), op, PATH, MESSAGES[name], _refused(name))


@ACTORS
@SAVES
def test_save_past_the_bound_is_422_naming_account_ids_and_stores_nothing(
    op: str, actor: Actor
) -> None:
    ids = _refused("past_the_bound")
    api = _Api(actor, granted=ids)
    _assert_refused_and_nothing_stored(api, op, PATH, MESSAGES["past_the_bound"], ids)


def test_save_at_the_bound_with_unique_accounts_is_stored_as_sent() -> None:
    ids = _distinct(BOUND)
    api = _Api(OWNER, granted=ids)
    made = api.c.post("/rules", json={"ir": _ir(ids)})
    assert made.status_code == 201, made.text[:300]
    rid = made.json()["id"]
    turned = ids[::-1]
    put = api.c.put(f"/rules/{rid}", json={"ir": _ir(turned)}, headers={"If-Match": "1"})
    assert put.status_code == 200, put.text[:300]
    assert [api.stored(rid, 1), api.stored(rid, 2)] == [ids, turned]


@pytest.mark.parametrize("spelling", sorted(SPELLINGS))
def test_a_repeat_in_another_spelling_is_still_refused(spelling: str) -> None:
    api, ids = _Api(OWNER), [str(A), SPELLINGS[spelling](str(A))]
    answer = api.c.post("/rules", json={"ir": _ir(ids)})
    assert (answer.status_code, answer.json()["path"]) == (422, PATH), answer.text[:300]
    assert answer.json()["detail"] == NOT_VALID + REPEAT
    _names_no_account(ids, answer.text)
    assert api.c.get("/rules").json()["items"] == []


@ACTORS
@LISTS
def test_the_bound_is_decided_before_the_grant_check(name: str, actor: Actor) -> None:
    """A list the bound refuses that names an ungranted account is the 422, never the 403: the
    scope check reads no grant for it and writes no record, and the refusal does not name C."""
    api, ids = _Api(actor), _refused(name, C)
    answer = api.c.post("/rules", json={"ir": _ir(ids)})
    assert (answer.status_code, answer.json()["code"]) == (422, "rule_ir_invalid"), answer.text
    assert answer.json()["path"] == PATH
    _names_no_account(ids, answer.text)
    assert api.unchecked() and api.audits == []


@ACTORS
def test_a_scope_within_the_bound_still_meets_the_grant_check(actor: Actor) -> None:
    api = _Api(actor)
    assert api.c.post("/rules", json={"ir": _ir([str(A)])}).status_code == 201
    for ids in ([str(C)], [str(A), str(C)]):
        answer = api.c.post("/rules", json={"ir": _ir(ids)})
        assert (answer.status_code, answer.json()["code"]) == (403, "forbidden"), answer.text
    assert [event for event, _ in api.denials] == ["rule_scope_denied"] * 2
    assert len(api.c.get("/rules").json()["items"]) == 1


@ACTORS
@SAVES
@ENVIRONMENT_NAMES
def test_save_naming_an_environment_twice_or_past_the_bound_is_422_at_scope_environments(
    name: str, op: str, actor: Actor
) -> None:
    """Held as the account list is, before the scope check: `live` twice, from a caller who may
    not arm live, is the 422 and writes no `rule_scope_denied` record."""
    sent, message = ENVIRONMENT_LISTS[name]
    api = _Api(actor)
    _assert_refused_and_nothing_stored(api, op, ENVIRONMENTS_PATH, message, [str(A)], sent)


def _assert_validate_refuses(
    api: _Api, ids: list[str], environments: list[str] | None, member: str, message: str
) -> None:
    """`validateRule` answers `200` with `valid: false` and the one `schema_error` at
    `scope.<member>`, naming no account."""
    answer = api.checks.post("/rules/validate", json={"ir": _ir(ids, environments)})
    assert answer.status_code == 200, answer.text[:300]
    body = answer.json()
    assert (body["valid"], len(body["errors"])) == (False, 1)
    (issue,) = body["errors"]
    want = (f"scope.{member}", "schema_error", "syntax")
    assert (issue["path"], issue["code"], issue["class"]) == want
    assert issue["message"].endswith(message)
    _names_no_account(ids, answer.text)
    assert api.unchecked()


def _assert_compile_refuses(
    api: _Api, ids: list[str], environments: list[str] | None, member: str, message: str
) -> None:
    """`compileRule` answers `422 rule_ir_invalid` with the one error whose field is
    `scope.<member>`, naming no account."""
    body = {"editor": "form", "model": _ir(ids, environments)}
    answer = api.checks.post(f"/rules/{RULE_ID}/compile", json=body)
    assert (answer.status_code, answer.json()["code"]) == (422, "rule_ir_invalid"), answer.text
    (error,) = answer.json()["errors"]
    assert (error["field"], error["rule"]) == (f"scope.{member}", "schema_error")
    assert error["message"].endswith(message)
    _names_no_account(ids, answer.text)
    assert api.unchecked()


@LISTS
def test_validate_answers_valid_false_at_scope_account_ids_for_a_list_past_the_bound_or_repeated(
    name: str,
) -> None:
    ids = _refused(name)
    _assert_validate_refuses(_Api(OWNER, granted=ids), ids, None, "account_ids", MESSAGES[name])


@ENVIRONMENT_NAMES
def test_validate_answers_valid_false_at_scope_environments_for_a_list_past_the_bound_or_repeated(
    name: str,
) -> None:
    sent, message = ENVIRONMENT_LISTS[name]
    _assert_validate_refuses(_Api(OWNER), [str(A)], sent, "environments", message)


@LISTS
def test_compile_refuses_a_list_past_the_bound_or_repeated_with_a_field_naming_scope_account_ids(
    name: str,
) -> None:
    ids = _refused(name)
    _assert_compile_refuses(_Api(OWNER, granted=ids), ids, None, "account_ids", MESSAGES[name])


@ENVIRONMENT_NAMES
def test_compile_refuses_an_environment_list_past_the_bound_or_repeated_with_a_field_naming_it(
    name: str,
) -> None:
    sent, message = ENVIRONMENT_LISTS[name]
    _assert_compile_refuses(_Api(OWNER), [str(A)], sent, "environments", message)


@ACTORS
@LISTS
async def test_import_of_a_bundle_over_the_bound_or_repeated_is_refused_as_a_save_is(
    name: str, actor: Actor
) -> None:
    ids = _refused(name)
    api = _Api(actor, granted=ids)
    mgr, audits = api.mgr, api.audits
    with pytest.raises(RuleError) as refused:
        await mgr.import_rule({"format": "cv-rule-bundle/1", "ir": _ir(ids)}, api.actor)
    assert (refused.value.status, refused.value.code) == (422, "rule_ir_invalid")
    assert refused.value.extra == {"path": PATH}
    assert refused.value.message == NOT_VALID + MESSAGES[name]
    assert (await mgr.list_rules(OWNER))["items"] == [] and audits == []


@LISTS
async def test_import_decides_the_bound_before_the_grant_walk_as_a_save_does(name: str) -> None:
    """A Manager with one grant imports a bundle whose list is past the bound or repeats and names
    C, whom no grant covers: the 422 at `/scope/account_ids`, as the save answers it, never the
    403 with its `rule.import_refused` record and count. The refusal does not name C."""
    api, ids = _Api(MANAGER), _refused(name, C)
    mgr, audits = api.mgr, api.audits
    with pytest.raises(RuleError) as refused:
        await mgr.import_rule({"format": "cv-rule-bundle/1", "ir": _ir(ids)}, api.actor)
    assert (refused.value.status, refused.value.code) == (422, "rule_ir_invalid")
    assert refused.value.extra == {"path": PATH}
    assert refused.value.message == NOT_VALID + MESSAGES[name]
    _names_no_account(ids, refused.value.message)
    assert (await mgr.list_rules(OWNER))["items"] == [] and audits == []


async def test_import_of_a_bundle_within_the_bound_still_meets_the_grant_walk() -> None:
    """Within the bound the walk is as it was: a Manager is refused `403` for C, the record holding
    the count refused (never an id) and nothing stored."""
    api = _Api(MANAGER)
    bundle = {"format": "cv-rule-bundle/1", "ir": _ir([str(A), str(C)])}
    with pytest.raises(RuleError) as refused:
        await api.mgr.import_rule(bundle, api.actor)
    assert (refused.value.status, refused.value.code) == (403, "forbidden")
    held = {"actor": str(MANAGER_ID), "reason": "ungranted_account", "count": 1}
    assert api.audits == [("rule.import_refused", held)]
    assert (await api.mgr.list_rules(OWNER))["items"] == []


async def test_import_moves_only_the_two_list_bounds_ahead_of_the_grant_walk() -> None:
    """Any other fault of a list is the save's, after the walk: an entry no UUID reads as, beside
    C, meets the walk first, as it did (`403`, its record counting both entries)."""
    api = _Api(MANAGER)
    bundle = {"format": "cv-rule-bundle/1", "ir": _ir(["not-a-uuid", str(C)])}
    with pytest.raises(RuleError) as refused:
        await api.mgr.import_rule(bundle, api.actor)
    assert (refused.value.status, refused.value.code) == (403, "forbidden")
    held = {"actor": str(MANAGER_ID), "reason": "ungranted_account", "count": 2}
    assert api.audits == [("rule.import_refused", held)]


@ENVIRONMENT_NAMES
async def test_import_of_a_bundle_naming_an_environment_twice_or_past_the_bound_is_refused(
    name: str,
) -> None:
    """The import lands on demo whatever the bundle says, but a list the model refuses is refused
    as a save refuses it: the 422 at `/scope/environments`, no record, nothing stored."""
    sent, message = ENVIRONMENT_LISTS[name]
    api = _Api(MANAGER)
    mgr, audits = api.mgr, api.audits
    bundle = {"format": "cv-rule-bundle/1", "ir": _ir([str(A)], sent)}
    with pytest.raises(RuleError) as refused:
        await mgr.import_rule(bundle, api.actor)
    assert (refused.value.status, refused.value.code) == (422, "rule_ir_invalid")
    assert refused.value.extra == {"path": ENVIRONMENTS_PATH}
    assert refused.value.message == NOT_VALID + message
    assert (await mgr.list_rules(OWNER))["items"] == [] and audits == []


@ENVIRONMENT_NAMES
async def test_import_decides_the_environment_lists_before_the_grant_walk_as_a_save_does(
    name: str,
) -> None:
    """A Manager with one grant imports a bundle that names C, whom no grant covers, and an
    environment list the model refuses: the 422 at `/scope/environments`, as the save answers
    it, never the 403 with its `rule.import_refused` record."""
    sent, message = ENVIRONMENT_LISTS[name]
    api = _Api(MANAGER)
    mgr, audits = api.mgr, api.audits
    bundle = {"format": "cv-rule-bundle/1", "ir": _ir([str(C)], sent)}
    with pytest.raises(RuleError) as refused:
        await mgr.import_rule(bundle, api.actor)
    assert (refused.value.status, refused.value.code) == (422, "rule_ir_invalid")
    assert refused.value.extra == {"path": ENVIRONMENTS_PATH}
    assert refused.value.message == NOT_VALID + message
    assert (await mgr.list_rules(OWNER))["items"] == [] and audits == []


@ACTORS
async def test_import_of_a_bundle_past_the_document_bound_is_refused_before_its_lists_are_read(
    actor: Actor,
) -> None:
    """A bundle past the document bound is that bound's 422 (`1 error in the rule IR.`), whatever
    its scope lists hold: the bound is applied first, so an account list of `MAX_ITEMS` and one
    more distinct accounts is not read as a list past its own bound (`/scope/account_ids`)."""
    ids = _distinct(MAX_ITEMS + 1)
    api = _Api(actor, granted=ids[:1])
    mgr, audits = api.mgr, api.audits
    with pytest.raises(RuleError) as refused:
        await mgr.import_rule({"format": "cv-rule-bundle/1", "ir": _ir(ids)}, api.actor)
    assert (refused.value.status, refused.value.code) == (422, "rule_ir_invalid")
    assert refused.value.message == "1 error in the rule IR."
    assert (await mgr.list_rules(OWNER))["items"] == [] and audits == []


#: A stored scope that breaks a bound -> its member, the list stored and the path quarantine names.
STORED = {
    "accounts_repeat": ("account_ids", _refused("repeat"), PATH),
    "accounts_past_the_bound": ("account_ids", _refused("past_the_bound"), PATH),
    "environments_repeat": ("environments", ["demo", "demo"], ENVIRONMENTS_PATH),
}


@pytest.mark.parametrize("name", sorted(STORED))
async def test_a_stored_scope_over_the_bound_is_quarantined_disarmed_and_never_evaluated(
    name: str,
) -> None:
    """A version stored before the bound whose scope breaks it: the model cannot read it, so it
    takes the quarantine path (G-15), beside a sound armed rule that still runs."""
    member, held_list, path = STORED[name]
    api = _Api(OWNER)
    mgr, audits = api.mgr, api.audits
    sound = (await mgr.create(_ir([str(A)], name="sound"), OWNER))["id"]
    held = (await mgr.create(_ir([str(A)], name="held"), OWNER))["id"]
    for rid in (sound, held):
        (await mgr._row(rid)).mode = "armed"
    stored = (await mgr._row(held)).versions[0].ir
    stored["scope"][member] = held_list  # as a save stored it before the bound
    kept = copy.deepcopy(stored)
    audits.clear()
    assert [str(e.rule.rule_id) for e in await mgr.evaluable_rules()] == [sound]
    view = await mgr.get(held, OWNER)
    want = (True, True, path, "disabled")
    assert (view["read_only"], view["quarantined"], view["failing_path"], view["mode"]) == want
    assert collect_account_ids(view["export_json"]) == ()
    assert [(action, p["reason"]) for action, p in audits] == [("rule.disarmed", "quarantined")]
    with pytest.raises(RuleError) as refused:
        await mgr.set_mode(held, "simulate", OWNER, "k-simulate")
    assert (refused.value.status, refused.value.code) == (422, "rule_invalid")
    assert (await mgr._row(held)).versions[0].ir == kept


@settings(max_examples=30, deadline=None)
@given(
    ids=st.lists(st.uuids(), max_size=BOUND, unique=True),
    symbols=st.lists(st.sampled_from(SYMBOLS), max_size=2, unique=True),
)
def test_a_bounded_scope_reads_the_same_in_every_reader(
    ids: list[uuid.UUID], symbols: list[str]
) -> None:
    sent = [str(a) for a in ids]
    doc = _ir(sent)
    doc["scope"]["symbols"] = symbols
    rule = Rule.model_validate(doc)
    assert ir_hash(Rule.model_validate(rule.model_dump(mode="json"))) == ir_hash(rule)
    expected = max(len(ids), 1) * max(len(symbols), 1)
    keys = _instances(rule, EvalTick("on_price_update"))
    assert len(keys) == len(set(keys)) == expected
    api = _Api(OWNER, granted=sent or [str(A)])  # the real resolver, every listed account granted
    asyncio.run(api.state.refresh(OWNER_ID))
    resolved = api.resolver.resolve(rule.scope, OWNER_ID, "demo")
    assert (len(resolved.instances), resolved.suppressed, api.denials) == (expected, [], [])
    if ids:
        assert {ref.key for ref in resolved.instances} == set(keys)
    count = f"{len(ids)} account{'s' if len(ids) != 1 else ''}" if ids else "all permitted accounts"
    assert summarize_scope(rule.scope).startswith(f"{count} ")
    assert collect_account_ids(rule.model_dump(mode="json")) == tuple(sent)


def test_the_test_bound_is_the_constant() -> None:
    from candleviewer.rules.ir.models import MAX_SCOPE_ACCOUNTS

    assert BOUND == MAX_SCOPE_ACCOUNTS
