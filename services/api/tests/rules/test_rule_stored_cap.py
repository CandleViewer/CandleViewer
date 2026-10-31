"""#4834 (E35 authoring limits, G-16): a user holds at most `MAX_STORED_RULES_PER_USER` rules.

The count is the caller's own rules that are not deleted, the Owner's included; a save past it is
`409 conflict` with `errors[].rule` `limit_reached` and the cap in the message (22 `storedRuleCap`),
after the permission and scope checks, and nothing is stored. The count and the write it admits
run under one manager-level lock, so two creates at the cap never both pass. An import is held to
the same cap. A page of `listRules` holds at most `MAX_PAGE` rules, the cap, so one page holds a
user's whole set; the rest follow by `meta.next_cursor`.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.api.rules_crud import MAX_PAGE, make_rules_crud_router
from candleviewer.rules.limits import MAX_STORED_RULES_PER_USER, stored_rules_message
from candleviewer.rules.manager import (
    CONFLICT_TITLE,
    Actor,
    InMemoryRuleStore,
    RuleCapRefused,
    RuleError,
    RuleRow,
    RulesManager,
)
from candleviewer.rules.vocabulary import default_registry
from tests.contract._admin_support import SPEC
from tests.rules.test_rules_manager import OWNER
from tests.rules.test_rules_routes import BASE, _ir
from tests.rules.test_scope_crud import A, C, _scoped, _setup

REG = default_registry()
MANAGER = Actor("u2", "s2", frozenset(BASE), granted_accounts=frozenset({str(A)}))
OTHER = Actor("u3", "s3", frozenset(BASE), granted_accounts=frozenset({str(A)}))


def _manager(cap: int = MAX_STORED_RULES_PER_USER, store: Any = None) -> RulesManager:
    return RulesManager(store or InMemoryRuleStore(), REG, max_rules_per_user=cap)


async def _seed(store: InMemoryRuleStore, owner: str, n: int, *, deleted: bool = False) -> None:
    """`n` stored rows of `owner`'s, as many rules as a create would count."""
    for i in range(n):
        name = f"{owner}-{'gone' if deleted else 'held'}-{i}"
        await store.put(RuleRow(str(uuid.uuid4()), name, owner, deleted=deleted))


def _live(store: InMemoryRuleStore, owner: str) -> int:
    return sum(1 for r in store._rows.values() if r.owner == owner and not r.deleted)


class _Routes:
    """The `/rules` routes over one manager, the actor swappable, with `on_cap_refused`'s calls
    and the manager's audit records."""

    def __init__(self, cap: int = MAX_STORED_RULES_PER_USER) -> None:
        self.audits: list[tuple[str, dict[str, Any]]] = []
        self.capped: list[str] = []
        self.store = InMemoryRuleStore()

        async def audit(action: str, payload: dict[str, Any]) -> None:
            self.audits.append((action, payload))

        self.mgr = RulesManager(self.store, REG, audit=audit, max_rules_per_user=cap)
        self.actor = Actor(OWNER.user_id, "s1", frozenset(BASE), is_owner=True, step_up_fresh=True)

        def resolve(_request: Request) -> Actor:
            return self.actor

        app = FastAPI()
        app.include_router(
            make_rules_crud_router(lambda: self.mgr, resolve, on_cap_refused=self.capped.append)
        )
        self.c = TestClient(app)

    def create(self, name: str, **over: Any) -> Any:
        return self.c.post("/rules", json={"ir": _ir(name=name, **over)})


def _refusal(cap: int) -> dict[str, Any]:
    message = stored_rules_message(cap)
    return {
        "type": "https://candleviewer.local/errors/conflict",
        "title": CONFLICT_TITLE,
        "status": 409,
        "code": "conflict",
        "detail": message,
        "errors": [{"rule": "limit_reached", "message": message}],
    }


async def test_the_201st_rule_of_a_user_is_409_limit_reached_with_the_cap_in_the_message() -> None:
    e = _Routes()
    await _seed(e.store, OWNER.user_id, MAX_STORED_RULES_PER_USER - 1)
    assert e.create("the 200th").status_code == 201  # at the cap, not past it
    r = e.create("the 201st")
    assert r.status_code == 409 and r.json() == _refusal(MAX_STORED_RULES_PER_USER)
    example = SPEC["paths"]["/rules"]["post"]["responses"]["409"]["content"]
    stated = example["application/problem+json"]["examples"]["storedRuleCap"]["value"]
    assert r.json() == {k: v for k, v in stated.items() if k != "instance"}
    assert _live(e.store, OWNER.user_id) == MAX_STORED_RULES_PER_USER
    assert e.capped == ["stored_rules"]
    assert [a for a, _ in e.audits] == ["rule.created"]  # counted, never recorded


class _Gated(InMemoryRuleStore):
    """Holds every write until `gate` opens: two creates that both counted before either wrote
    would both reach it."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()
        self.waiting = 0

    async def put(self, row: RuleRow) -> None:
        self.waiting += 1
        await self.gate.wait()
        await super().put(row)


async def test_concurrent_creates_at_the_cap_admit_exactly_one() -> None:
    store = _Gated()
    store.gate.set()
    await _seed(store, OWNER.user_id, 2)
    store.gate.clear()
    store.waiting = 0
    m = _manager(3, store)

    async def release() -> None:
        for _ in range(50):  # both creates run as far as they can before any write lands
            await asyncio.sleep(0)
        store.gate.set()

    results = await asyncio.gather(
        m.create(_ir(name="one"), OWNER),
        m.create(_ir(name="two"), OWNER),
        release(),
        return_exceptions=True,
    )
    refused = [r for r in results[:2] if isinstance(r, RuleCapRefused)]
    created = [r for r in results[:2] if isinstance(r, dict)]
    assert (len(created), len(refused), _live(store, OWNER.user_id)) == (1, 1, 3)
    assert refused[0].cap == "stored_rules" and store.waiting == 1  # one write ever reached


async def test_a_user_below_the_cap_creates_and_a_delete_frees_a_slot() -> None:
    m = _manager(2)
    first = (await m.create(_ir(name="a"), MANAGER))["id"]
    await m.create(_ir(name="b"), MANAGER)
    with pytest.raises(RuleCapRefused):
        await m.create(_ir(name="c"), MANAGER)
    await m.delete(first, MANAGER)
    assert (await m.create(_ir(name="c"), MANAGER))["name"] == "c"


async def test_deleted_rules_never_count() -> None:
    store = InMemoryRuleStore()
    await _seed(store, OWNER.user_id, 5, deleted=True)
    m = _manager(2, store)
    await m.create(_ir(name="a"), OWNER)
    await m.create(_ir(name="b"), OWNER)
    with pytest.raises(RuleCapRefused):
        await m.create(_ir(name="c"), OWNER)


async def test_import_rule_at_the_cap_is_the_same_refusal() -> None:
    m = _manager(1)
    await m.create(_ir(name="held"), OWNER)
    with pytest.raises(RuleCapRefused) as refused:
        await m.import_rule({"format": "cv-rule-bundle/1", "ir": _ir(name="imported")}, OWNER)
    answer = refused.value
    assert (answer.status, answer.code, answer.message) == (
        409,
        "conflict",
        stored_rules_message(1),
    )
    assert answer.extra["errors"] == [{"rule": "limit_reached", "message": answer.message}]


def test_the_cap_refusal_comes_after_the_permission_and_scope_checks() -> None:
    """At the cap a viewer is still `403` at the gate, and an ungranted account in the scope
    still the audited scope refusal: the cap never answers for a request it does not reach."""
    e = _Routes(cap=1)
    assert e.create("held").status_code == 201
    e.actor = Actor(OWNER.user_id, "s1", frozenset({"rules:read"}), is_owner=True)
    assert (e.create("viewer").status_code, e.capped) == (403, [])
    e.actor = Actor(OWNER.user_id, "s1", frozenset(BASE))  # not the Owner, no grant
    refused = e.create("ungranted", scope={"level": "account", "account_ids": [str(C)]})
    assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
    assert e.audits[-1][0] == "rule.scope_refused" and e.capped == []


def test_an_ungranted_scope_is_the_resolvers_audited_refusal_before_the_cap() -> None:
    """The route's scope check, by the real resolver, answers before the cap of one is weighed."""
    c, scope_audits, _src, mgr = _setup()
    mgr._max_rules = 1
    assert c.post("/rules", json={"ir": _scoped(A)}).status_code == 201
    r = c.post("/rules", json={"ir": {**_scoped(C), "name": "other"}})
    assert r.status_code == 403 and scope_audits == ["rule_scope_denied"]


def test_a_viewer_gets_403_before_any_cap_check() -> None:
    e = _Routes(cap=0)
    e.actor = Actor(OWNER.user_id, "s1", frozenset({"rules:read"}), is_owner=True)
    assert (e.create("x").status_code, e.capped) == (403, [])


async def test_name_taken_keeps_its_409_and_its_order() -> None:
    """Below the cap a taken name is `name_taken`; at the cap the cap answers first."""
    m = _manager(2)
    await m.create(_ir(name="same"), OWNER)
    with pytest.raises(RuleError) as taken:
        await m.create(_ir(name="same"), OWNER)
    assert (taken.value.status, taken.value.code) == (409, "name_taken")
    await m.create(_ir(name="other"), OWNER)
    with pytest.raises(RuleCapRefused):
        await m.create(_ir(name="same"), OWNER)


async def test_another_users_rules_never_count() -> None:
    store = InMemoryRuleStore()
    await _seed(store, OTHER.user_id, 3)
    m = _manager(1, store)
    assert (await m.create(_ir(name="mine"), MANAGER))["name"] == "mine"


async def test_a_manager_at_the_cap_does_not_stop_the_owner_and_the_owner_counts_too() -> None:
    m = _manager(1)
    await m.create(_ir(name="m"), MANAGER)
    with pytest.raises(RuleCapRefused):
        await m.create(_ir(name="m2"), MANAGER)
    await m.create(_ir(name="o"), OWNER)
    with pytest.raises(RuleCapRefused) as refused:  # every role counts, the Owner included
        await m.create(_ir(name="o2"), OWNER)
    assert refused.value.message == stored_rules_message(1)


def test_listing_is_paginated_and_bounded() -> None:
    e = _Routes()
    asyncio.run(_seed(e.store, OWNER.user_id, MAX_PAGE + 5))
    first = e.c.get("/rules?limit=500").json()
    assert first["meta"]["count"] == MAX_PAGE and first["meta"]["has_more"] is True
    cursor = first["meta"]["next_cursor"]
    second = e.c.get(f"/rules?limit=500&cursor={cursor}").json()
    assert second["meta"] == {"next_cursor": None, "has_more": False, "count": 5}
    ids = [r["id"] for r in first["items"] + second["items"]]
    assert ids == sorted(ids) and len(set(ids)) == MAX_PAGE + 5
    assert e.c.get("/rules?limit=0").json()["meta"]["count"] == 1  # at least one


_OPS = st.lists(
    st.tuples(st.sampled_from(["create", "delete"]), st.sampled_from([OWNER, MANAGER])),
    max_size=24,
)


@settings(max_examples=40, deadline=None)
@given(ops=_OPS, cap=st.integers(min_value=1, max_value=4))
async def test_live_rules_per_user_never_exceed_the_cap_under_create_and_delete_sequences(
    ops: list[tuple[str, Actor]], cap: int
) -> None:
    store = InMemoryRuleStore()
    m = _manager(cap, store)
    for n, (op, actor) in enumerate(ops):
        held = _live(store, actor.user_id)
        if op == "create":
            try:
                await m.create(_ir(name=f"r{n}"), actor)
                assert held < cap
            except RuleCapRefused:
                assert held == cap
        else:
            mine = [r for r in store._rows.values() if r.owner == actor.user_id and not r.deleted]
            if mine:
                await m.delete(mine[0].id, actor)
        assert all(_live(store, who.user_id) <= cap for who in (OWNER, MANAGER))


@settings(max_examples=30, deadline=None)
@given(count=st.integers(min_value=0, max_value=40), limit=st.integers(min_value=-2, max_value=60))
async def test_pages_concatenate_to_the_full_sorted_set(count: int, limit: int) -> None:
    store = InMemoryRuleStore()
    await _seed(store, OWNER.user_id, count)
    m = _manager(store=store)
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(count + 2):
        page = await m.list_rules(OWNER, cursor=cursor, limit=max(1, min(limit, MAX_PAGE)))
        seen += [r["id"] for r in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == sorted(r.id for r in store._rows.values())
