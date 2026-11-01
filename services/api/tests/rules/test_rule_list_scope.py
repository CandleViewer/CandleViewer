"""#2291 (SR-051: the scope is part of the query): `RulesManager`'s reads of the rule store.

Every read that answers a caller asks the store with the caller's `RuleReadScope` (`read_scope`):
the list's page, the notifications' rule ids, the plain reads by id and the save's name check. The
in-memory store applies a scope with the reading rule itself (`rule_visible`), which the property
tests hold, and the manager re-checks every row the store returns. The Postgres statements are
pinned in tests/unit/test_rules_store_pg_scope.py and run in
tests/integration/storage/test_rules_store_pg.py.
"""

from __future__ import annotations

import ast
import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args
from uuid import UUID, uuid5

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.rules import manager as manager_module
from candleviewer.rules.ir.models import RuleScope
from candleviewer.rules.manager import (
    RULE_LEVELS,
    Actor,
    GrantRead,
    InMemoryRuleStore,
    OwnerRead,
    RuleError,
    RuleReadScope,
    RuleRow,
    RulesManager,
    VersionRow,
    read_scope,
    rule_visible,
)
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_rules_routes import _ir

_ROOT = Path(__file__).resolve().parents[4]
_FIXTURE: dict[str, Any] = json.loads(
    (Path(__file__).parents[1] / "fixtures/rule_ir/form_simple_0.json").read_text(encoding="utf-8"),
    parse_float=str,
)
A, B, C = (str(UUID(int=n)) for n in (0xA, 0xB, 0xC))
MGR, OTHER, BOSS = "mgr", "other", "boss"
PERMS = frozenset({"rules:read", "rules:write"})

#: One read of the store: the method, the scope asked (`None` by id or whole) and its arguments.
Read = tuple[str, RuleReadScope | None, dict[str, Any]]


class Recording(InMemoryRuleStore):
    """`InMemoryRuleStore` logging each read, so a test sees which read served a call."""

    def __init__(self) -> None:
        super().__init__()
        self.reads: list[Read] = []

    def seed(self, *rows: RuleRow) -> None:
        for row in rows:
            self._rows[row.id] = row

    async def get(self, rule_id: str) -> RuleRow | None:
        self.reads.append(("get", None, {"rule_id": rule_id}))
        return await super().get(rule_id)

    async def all(self) -> list[RuleRow]:
        self.reads.append(("all", None, {}))
        return await super().all()

    async def scoped_page(
        self,
        scope: RuleReadScope,
        *,
        mode: str | None,
        level: str | None,
        after: str | None,
        limit: int,
        only: str | None = None,
    ) -> list[RuleRow]:
        asked = {"mode": mode, "level": level, "after": after, "limit": limit, "only": only}
        self.reads.append(("scoped_page", scope, asked))
        return await super().scoped_page(
            scope, mode=mode, level=level, after=after, limit=limit, only=only
        )

    async def scoped_ids(self, scope: RuleReadScope) -> frozenset[str]:
        self.reads.append(("scoped_ids", scope, {}))
        return await super().scoped_ids(scope)

    async def name_taken(self, scope: RuleReadScope, name: str, exclude: str) -> bool:
        self.reads.append(("name_taken", scope, {"name": name, "exclude": exclude}))
        return await super().name_taken(scope, name, exclude)


class _Unscoped(Recording):
    """A faulty store: every live row whatever the scope, as a query that lost its predicate."""

    async def scoped_page(
        self,
        scope: RuleReadScope,
        *,
        mode: str | None,
        level: str | None,
        after: str | None,
        limit: int,
        only: str | None = None,
    ) -> list[RuleRow]:
        rows = sorted(
            (r for r in self._rows.values() if not r.deleted and only in (None, r.id)),
            key=lambda r: r.id,
        )
        return rows[:limit]


@dataclass(frozen=True)
class V:
    """One version: the accounts its scope names, and one in a metric reference or a nested
    action parameter."""

    scope: tuple[str, ...] = ()
    metric: str | None = None
    param: str | None = None


def _doc(rid: str, n: int, v: V) -> dict[str, Any]:
    doc = copy.deepcopy(_FIXTURE) | {"rule_id": rid, "version": n, "name": f"r-{rid[-3:]}"}
    doc["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
    if v.scope:
        doc["scope"] = {"level": "account", "account_ids": list(v.scope)}
    if v.metric is not None:
        doc["conditions"]["left"]["account_id"] = v.metric
    if v.param is not None:
        doc["actions"][0]["params"]["route"] = {"target_account_ids": [v.param]}
    return doc


def _rid(n: int) -> str:
    return str(UUID(int=n))


def _vid(rid: str, n: int) -> str:
    """Version `n`'s id in a rule `_rule` builds."""
    return str(uuid5(UUID(rid), str(n)))


def _rule(
    rid: str, owner: str, *versions: V | tuple[str, ...], name: str = "", deleted: bool = False
) -> RuleRow:
    """A stored rule of `owner`, one version per entry (a tuple names the scope's accounts), the
    last one active."""
    vs = [
        VersionRow(_vid(rid, n), rid, n, _doc(rid, n, v if isinstance(v, V) else V(v)),
                   f"{n:064x}", "1.0.0", "", owner, "s")
        for n, v in enumerate(versions, start=1)
    ]  # fmt: skip
    return RuleRow(
        rid, name or f"r-{rid[-3:]}", owner, active_version_id=vs[-1].id,
        latest_version=len(vs), deleted=deleted, versions=vs,
    )  # fmt: skip


def _actor(user: str = MGR, *granted: str, owner: bool = False) -> Actor:
    return Actor(user, "s", PERMS, frozenset(granted), is_owner=owner)


def _manager(*rows: RuleRow, store: Recording | None = None) -> tuple[RulesManager, Recording]:
    held = Recording() if store is None else store
    held.seed(*rows)
    return RulesManager(held, default_registry()), held


async def _listed(m: RulesManager, actor: Actor) -> list[str]:
    return [str(i["id"]) for i in (await m.list_rules(actor, limit=200))["items"]]


# ----- the scope and the reads that take it ------------------------------------------------------


@pytest.mark.parametrize("granted", [(), (A,), (A, B)])
def test_read_scope_is_the_owner_scope_only_for_the_owner_role(granted: tuple[str, ...]) -> None:
    assert read_scope(_actor(BOSS, *granted, owner=True)) == OwnerRead(BOSS)
    assert read_scope(_actor(MGR, *granted)) == GrantRead(MGR, frozenset(granted))


async def test_list_asks_the_store_with_the_callers_scope_and_never_reads_every_rule() -> None:
    m, store = _manager(_rule(_rid(1), MGR, (A,)), _rule(_rid(2), OTHER, (A,)))
    page = await m.list_rules(_actor(MGR, A), mode="disabled", scope="global", limit=5)
    assert [i["id"] for i in page["items"]] == [_rid(1)]
    asked = {"mode": "disabled", "level": "global", "after": None, "limit": 6, "only": None}
    assert store.reads == [("scoped_page", GrantRead(MGR, frozenset({A})), asked)]
    store.reads.clear()
    owners = await m.list_rules(_actor(BOSS, owner=True), cursor=_rid(1), limit=5)
    assert [i["id"] for i in owners["items"]] == [_rid(2)]
    asked |= {"mode": None, "level": None, "after": _rid(1)}
    assert store.reads == [("scoped_page", OwnerRead(BOSS), asked)]


async def test_a_row_the_store_returns_outside_the_scope_is_dropped_and_logged_by_id() -> None:
    """Defence in depth (C-12.4): a store that lost its predicate returns another user's row; the
    re-check drops it from the page and from a read by id, and logs its id and a count only."""
    mine, theirs = _rule(_rid(1), MGR, (A,)), _rule(_rid(2), OTHER, (A,))
    m, _ = _manager(mine, theirs, store=_Unscoped())
    with capture_logs() as logs:
        page = await m.list_rules(_actor(MGR, A), limit=5)
        with pytest.raises(RuleError) as unseen:
            await m.get(theirs.id, _actor(MGR, A))
    assert [i["id"] for i in page["items"]] == [mine.id] and page["next_cursor"] is None
    assert (unseen.value.status, unseen.value.code) == (404, "not_found")
    found = [e for e in logs if e["event"] == "rules.scope_mismatch"]
    assert [(e["log_level"], e["rule_ids"], e["count"]) for e in found] == [
        ("error", [theirs.id], 1),
        ("error", [theirs.id], 1),
    ]
    assert all(set(e) == {"event", "log_level", "rule_ids", "count"} for e in found)


async def test_visible_rule_ids_reads_the_scoped_ids_only() -> None:
    m, store = _manager(
        _rule(_rid(1), MGR, (A,)), _rule(_rid(2), OTHER, (A,)), _rule(_rid(3), MGR, (B,))
    )
    assert await m.visible_rule_ids(_actor(MGR, A)) == {_rid(1)}
    assert store.reads == [("scoped_ids", GrantRead(MGR, frozenset({A})), {})]


async def test_reads_by_id_take_the_scoped_point_read() -> None:
    rid = _rid(1)
    m, store = _manager(_rule(rid, MGR, (A,), (A,)))
    caller = _actor(MGR, A)
    await m.get(rid, caller)
    await m.export_rule(rid, caller)
    assert [v["version"] for v in await m.versions_for(rid, caller)] == [2, 1]
    assert (await m.version_for(rid, _vid(rid, 1), caller))["version"] == 1
    point = {"mode": None, "level": None, "after": None, "limit": 1, "only": rid}
    assert store.reads == [("scoped_page", GrantRead(MGR, frozenset({A})), point)] * 4
    with pytest.raises(RuleError) as missing:
        await m.version_for(rid, _vid(rid, 9), caller)
    assert (missing.value.status, missing.value.message) == (404, "That version does not exist.")


async def test_a_write_on_a_rule_outside_the_scope_records_its_refusal_as_before() -> None:
    """A write still reads the rule by its id and fails in full with its refusal recorded first
    (C-2.9, 04 §7.3); only the plain reads narrow in the query."""
    audits: list[tuple[str, dict[str, Any]]] = []

    async def audit(action: str, payload: dict[str, Any]) -> None:
        audits.append((action, payload))

    store = Recording()
    store.seed(theirs := _rule(_rid(2), OTHER, (A,)))
    m = RulesManager(store, default_registry(), audit=audit)
    with pytest.raises(RuleError) as refused:
        await m.delete(theirs.id, _actor(MGR, A))
    assert (refused.value.status, refused.value.code) == (404, "not_found")
    refusal = {"rule_id": theirs.id, "op": "delete", "reason": "rule_not_visible", "actor": MGR}
    assert audits == [("rule.scope_refused", refusal)]
    assert [method for method, _, _ in store.reads] == ["get"]
    assert not store._rows[theirs.id].deleted


@pytest.mark.parametrize(
    ("mode", "level"), [("live", None), ("ARMED", None), (None, "galaxy"), (None, "Global")]
)
async def test_an_unknown_mode_or_level_matches_no_rule_without_a_store_read(
    mode: str | None, level: str | None
) -> None:
    m, store = _manager(_rule(_rid(1), MGR, (A,)))
    page = await m.list_rules(_actor(MGR, A), mode=mode, scope=level)
    assert page == {"items": [], "next_cursor": None} and store.reads == []
    assert len((await m.list_rules(_actor(MGR, A), mode="", scope=""))["items"]) == 1


def test_the_level_filter_vocabulary_is_the_rule_scope_levels() -> None:
    spec = (_ROOT / "docs/plan/22-api-openapi.yaml").read_text(encoding="utf-8")
    block = re.search(r"^    RuleScope:\n((?:      .*\n)+)", spec, re.MULTILINE)
    assert block is not None
    listed = re.search(r"enum: \[([^\]]*)\]", block.group(1))
    assert listed is not None
    contract = [level.strip() for level in listed.group(1).split(",")]
    assert (
        list(RULE_LEVELS) == contract == list(get_args(RuleScope.model_fields["level"].annotation))
    )


def test_only_the_system_reads_read_every_rule() -> None:
    """BQ-4's guard: `RuleStore.all()` serves the system reads with no principal, never a read that
    answers a caller, which takes the caller's scope in the query."""
    tree = ast.parse(Path(str(manager_module.__file__)).read_text(encoding="utf-8"))
    readers = {
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "all"
        and ast.unparse(node.func.value) == "self._s"
    }
    assert readers == {"verify_system_rules", "evaluable_rules"}


# ----- what a scope admits (BQ-6: exactly `_visible`'s answers) ---------------------------------


async def test_an_own_rule_naming_no_account_stays_listed_with_no_grants() -> None:
    m, _ = _manager(_rule(_rid(1), MGR, ()))
    assert await _listed(m, _actor(MGR)) == [_rid(1)]
    assert await m.visible_rule_ids(_actor(MGR)) == {_rid(1)}
    assert await _listed(m, _actor(OTHER, A, B, C)) == []  # grants alone reach no other user's rule
    assert await _listed(m, _actor(BOSS, owner=True)) == [_rid(1)]


async def test_an_own_rule_naming_a_lost_grant_leaves_the_list_and_returns_with_it() -> None:
    m, _ = _manager(_rule(_rid(1), MGR, (A,)))
    assert await _listed(m, _actor(MGR, A)) == [_rid(1)]
    assert await _listed(m, _actor(MGR)) == []
    with pytest.raises(RuleError) as gone:
        await m.versions_for(_rid(1), _actor(MGR))
    assert gone.value.status == 404
    assert await _listed(m, _actor(MGR, A)) == [_rid(1)]
    assert await _listed(m, _actor(BOSS, owner=True)) == [_rid(1)]


async def test_an_older_version_naming_an_ungranted_account_hides_the_rule() -> None:
    m, _ = _manager(_rule(_rid(1), MGR, (B,), (A,)))  # the active version names A only
    assert await _listed(m, _actor(MGR, A)) == []
    assert await m.visible_rule_ids(_actor(MGR, A)) == frozenset()
    assert await _listed(m, _actor(MGR, A, B)) == [_rid(1)]


async def test_a_rule_naming_two_accounts_needs_both_granted() -> None:
    """One missing account hides the whole rule (no partial view), wherever the IR names it, and
    another user holding every grant still never reads it (IDOR, #3334)."""
    pair = _rule(_rid(1), MGR, (A, B))
    metric = _rule(_rid(2), MGR, V((A,), metric=C))
    param = _rule(_rid(3), MGR, V((A,), param=C))
    m, _ = _manager(pair, metric, param)
    assert await _listed(m, _actor(MGR, A)) == []
    assert await _listed(m, _actor(MGR, A, B)) == [_rid(1)]
    assert await _listed(m, _actor(MGR, A, C)) == [_rid(2), _rid(3)]
    assert await _listed(m, _actor(OTHER, A, B, C)) == []
    with pytest.raises(RuleError):
        await m.get(_rid(1), _actor(OTHER, A, B, C))


async def test_a_deleted_rule_is_in_no_scope() -> None:
    m, store = _manager(_rule(_rid(1), MGR, (A,), deleted=True), _rule(_rid(2), MGR, ()))
    for actor in (_actor(MGR, A), _actor(BOSS, owner=True)):
        scope = read_scope(actor)
        page = await store.scoped_page(scope, mode=None, level=None, after=None, limit=5)
        assert [r.id for r in page] == [_rid(2)]  # the store reads none, before any re-check
        assert await _listed(m, actor) == [_rid(2)]
        assert await m.visible_rule_ids(actor) == {_rid(2)}
        with pytest.raises(RuleError):
            await m.get(_rid(1), actor)


async def test_a_sys_rule_is_listed_for_the_owner_role_only() -> None:
    """No path creates a `sys.*` rule; a stored one follows the one rule, with no special case."""
    m, _ = _manager(_rule(_rid(1), BOSS, (), name="sys.native_sl_watchdog"))
    assert await _listed(m, _actor(BOSS, owner=True)) == [_rid(1)]
    assert await _listed(m, _actor(MGR, A, B, C)) == []


async def test_the_name_check_counts_own_rules_readable_or_not_and_never_another_users() -> None:
    """G-14: the caller's own rule naming an account they no longer hold still holds its name; a
    rule of another user never does, so no answer hints at it."""
    m, store = _manager(
        _rule(_rid(1), MGR, (B,), name="alpha"), _rule(_rid(2), OTHER, (A,), name="beta")
    )
    caller = _actor(MGR, A)
    with pytest.raises(RuleError) as taken:
        await m.create(_ir(name="alpha", scope={"level": "account", "account_ids": [A]}), caller)
    assert (taken.value.status, taken.value.code) == (409, "name_taken")
    made = await m.create(_ir(name="beta", scope={"level": "account", "account_ids": [A]}), caller)
    assert made["name"] == "beta"
    asked = [scope for method, scope, _ in store.reads if method == "name_taken"]
    assert asked == [GrantRead(MGR, frozenset({A}))] * 2
    assert "all" not in [method for method, _, _ in store.reads]


async def test_the_name_check_for_the_owner_role_counts_every_live_rule() -> None:
    m, _ = _manager(
        _rule(_rid(1), OTHER, (A,), name="gamma"),
        _rule(_rid(2), OTHER, (A,), name="delta", deleted=True),
    )
    boss = _actor(BOSS, owner=True)
    with pytest.raises(RuleError) as taken:
        await m.create(_ir(name="gamma"), boss)
    assert taken.value.code == "name_taken"
    assert (await m.create(_ir(name="delta"), boss))["name"] == "delta"
    assert (await m.create(_ir(name="Gamma"), boss))["name"] == "Gamma"  # the exact name, as before
    rid = (await m.create(_ir(name="epsilon"), boss))["id"]
    with pytest.raises(RuleError) as renamed:
        await m.update(rid, _ir(name="gamma"), 1, boss)
    assert renamed.value.code == "name_taken"
    assert await m._s.name_taken(OwnerRead(BOSS), "epsilon", rid) is False  # the rule itself


# ----- property: the in-memory store and the manager read exactly what `rule_visible` shows -----

_ACCOUNT = st.sampled_from((A, B, C))
_VERSION = st.builds(
    V,
    st.lists(_ACCOUNT, max_size=2, unique=True).map(tuple),
    st.none() | _ACCOUNT,
    st.none() | _ACCOUNT,
)
_ROWS = st.lists(
    st.tuples(
        st.sampled_from((MGR, OTHER)), st.lists(_VERSION, min_size=1, max_size=3), st.booleans()
    ),
    max_size=7,
)
_ACTORS = st.builds(
    lambda user, owner, granted: _actor(user, *sorted(granted), owner=owner),
    st.sampled_from((MGR, OTHER)),
    st.booleans(),
    st.sets(_ACCOUNT),
)
Spec = list[tuple[str, list[V], bool]]


def _population(spec: Spec) -> list[RuleRow]:
    """The rows in id order; seeded in reverse, so no read relies on insertion order."""
    return [_rule(_rid(n), who, *vs, deleted=gone) for n, (who, vs, gone) in enumerate(spec, 1)]


@settings(deadline=None, max_examples=80)
@given(spec=_ROWS, actor=_ACTORS)
async def test_scope_admits_exactly_what_rule_visible_shows(spec: Spec, actor: Actor) -> None:
    rows = _population(spec)
    store = Recording()
    store.seed(*reversed(rows))
    scope = read_scope(actor)
    shown = [r.id for r in rows if rule_visible(r, actor)]
    page = await store.scoped_page(scope, mode=None, level=None, after=None, limit=len(rows) + 1)
    assert [r.id for r in page] == shown
    assert await store.scoped_ids(scope) == frozenset(shown)
    for r in rows:
        point = await store.scoped_page(
            scope, mode=None, level=None, after=None, limit=1, only=r.id
        )
        assert [p.id for p in point] == ([r.id] if r.id in shown else [])


@settings(deadline=None, max_examples=40)
@given(spec=_ROWS, actor=_ACTORS, limit=st.integers(min_value=1, max_value=5))
async def test_pages_walked_by_the_cursor_concatenate_to_the_visible_set(
    spec: Spec, actor: Actor, limit: int
) -> None:
    """Whatever the page size, the pages a walk by `next_cursor` reads are full until the last and
    concatenate to the rows the caller reads, in id order: no page is cut before the scope."""
    rows = _population(spec)
    m, store = _manager(*reversed(rows))
    pages: list[list[str]] = []
    cursor: str | None = None
    while len(pages) <= len(rows):
        page = await m.list_rules(actor, cursor=cursor, limit=limit)
        pages.append([str(i["id"]) for i in page["items"]])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert cursor is None
    assert all(len(p) == limit for p in pages[:-1]) and len(pages[-1]) <= limit
    assert [rid for p in pages for rid in p] == [r.id for r in rows if rule_visible(r, actor)]
    assert {method for method, _, _ in store.reads} == {"scoped_page"}
