"""Integration: `PostgresRuleStore` + `RulesManager` on real Postgres (E35-S01).

Versioning, dedupe, optimistic concurrency, armed-shape and quarantine persisted through
the real `0013_rules`/`0014` schema. Not run locally (no docker); exercised by the
integration CI job.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random
import uuid
from pathlib import Path
from typing import Any

import pytest

from candleviewer.accounts.profile_repository import ARMED_SHOWN, ArmedRule
from candleviewer.rules.ir.accounts import collect_account_ids
from candleviewer.rules.manager import (
    Actor,
    GrantRead,
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
from candleviewer.rules_store_pg import PostgresArmedRules, PostgresRuleStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration.storage import test_rules_migration as _mig

pytestmark = pytest.mark.integration
pg_dsn = _mig.pg_dsn  # reuse the module-scoped Postgres 16 container fixture
_FIX = Path(__file__).resolve().parents[2] / "fixtures/rule_ir/form_simple_0.json"
_RUN = uuid.uuid4().hex[:8]


def _ir(n: str) -> dict[str, object]:
    raw = json.loads(_FIX.read_text(encoding="utf-8"), parse_float=str)
    raw["conditions"]["right"]["const"] = n
    raw["name"] = f"form-{_RUN}"  # re-runnable on a reused database
    raw["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
    return dict(raw)


async def _owner(repo: SqlAlchemyRelationalRepository) -> str:
    """An active user holding the owner role: the Owner role's reads bind the caller to a live
    owner role in the statement itself (SR-051, #2291)."""
    from sqlalchemy import text

    uid = str(uuid.uuid4())
    async with repo.unit_of_work() as uow:
        await uow.session.execute(
            text(
                "INSERT INTO users (id, username, email, display_name, password_hash, status) "
                "VALUES (CAST(:i AS uuid), :u, :e, 'T', '$argon2id$v=19$x', 'active')"
            ),
            {"i": uid, "u": f"u{uid[:8]}", "e": f"{uid[:8]}@example.test"},
        )
        await uow.session.execute(
            text(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT CAST(:i AS uuid), id FROM roles WHERE name = 'owner'"
            ),
            {"i": uid},
        )
        await uow.commit()
    return uid


async def test_versions_dedupe_conflict_arm_and_delete_survive_a_reload(
    pg_dsn: str,
) -> None:
    repo = SqlAlchemyRelationalRepository(pg_dsn, "rules-it")
    uid = await _owner(repo)
    actor = Actor(uid, "s1", frozenset({"rules:write"}), is_owner=True)
    mgr = RulesManager(PostgresRuleStore(repo), default_registry())
    rid = (await mgr.create(_ir("1"), actor))["id"]
    try:
        assert (await mgr.update(rid, _ir("2"), 1, actor))["version"]["version"] == 2
        assert (await mgr.update(rid, _ir("2"), 2, actor))["created"] is False  # UNIQUE(rule, hash)
        with pytest.raises(RuleError) as e:
            await mgr.update(rid, _ir("3"), 1, actor)
        assert e.value.status == 412  # #4674: a stale version is a failed precondition
        fresh = RulesManager(PostgresRuleStore(repo), default_registry())  # new process view
        assert [v["version"] for v in await fresh.versions(rid)] == [2, 1]
        await fresh.set_mode(rid, "simulate", actor, "k1")
        active = (await fresh.get(rid, actor))["active_version_id"]
        h = next(v["ir_hash"] for v in await fresh.versions(rid) if v["id"] == active)
        await fresh.record_simulation(rid, h, 5, 0.0)
        await fresh.set_mode(rid, "armed", actor, "k2")  # satisfies rule_armed_shape
        again = RulesManager(PostgresRuleStore(repo), default_registry())
        assert (await again.get(rid, actor))["mode"] == "armed"
        with pytest.raises(RuleError) as d:
            await again.delete(rid, actor)
        assert d.value.status == 409
        await again.set_mode(rid, "disabled", actor, "k3")
        await again.delete(rid, actor)
        with pytest.raises(RuleError):
            await again.get(rid, actor)
    finally:
        _retire(pg_dsn, rid)


async def test_conflict_after_restart_carries_the_stored_version_and_time(pg_dsn: str) -> None:
    repo = SqlAlchemyRelationalRepository(pg_dsn, "rules-it-sess")
    uid = await _owner(repo)
    a = Actor(uid, "session-A", frozenset({"rules:write"}), is_owner=True)
    b = Actor(uid, "session-B", frozenset({"rules:write"}), is_owner=True)
    store = PostgresRuleStore(repo)
    mgr = RulesManager(store, default_registry(), now_us=lambda: 1_790_000_000_123_456)
    rid = (await mgr.create(_ir("1"), a))["id"]
    await mgr.update(rid, _ir("2"), 1, a)
    fresh = RulesManager(PostgresRuleStore(repo), default_registry())  # restart / other worker
    with pytest.raises(RuleError) as e:
        await fresh.update(rid, _ir("3"), 1, b)
    assert e.value.status == 412  # #4674: a stale version is a failed precondition
    assert (e.value.extra["version"], e.value.extra["updated_at"]) == (
        2,
        "2026-09-21T14:13:20.123456Z",
    )


def _scope_ir(level: str, accounts: tuple[uuid.UUID, ...]) -> dict[str, object]:
    return {
        "conditions": {}, "actions": [],
        "scope": {"level": level, "account_ids": [str(a) for a in accounts]},
    }  # fmt: skip


def _version(c: Any, rid: str, n: int, ir: dict[str, object]) -> str:
    vid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO rule_versions (id, rule_id, version, ir, ir_hash, compiler_version) "
        "VALUES (%s, %s, %s, %s::jsonb, %s, '1.0.0')",
        (vid, rid, n, json.dumps(ir), uuid.uuid4().hex * 2),
    )
    return vid


def _armed(
    c: Any, owner: str, name: str, *accounts: uuid.UUID, level: str = "account",
    mode: str = "armed", deleted: bool = False, ir: dict[str, object] | None = None,
) -> str:  # fmt: skip
    """A rule in `mode` whose one version, active, lists `accounts` at scope `level` (or holds
    `ir`), with its arming recorded so an armed one meets `rule_armed_shape`. The `rules.scope*`
    columns are written as `PostgresRuleStore.put` writes them: the level and the first account."""
    rid = _mig._rule(c, owner, name)
    vid = _version(c, rid, 1, _scope_ir(level, accounts) if ir is None else ir)
    first = accounts[0] if accounts and level == "account" else None
    c.execute(
        "UPDATE rules SET scope = %s::rule_scope, scope_account_id = %s, scope_symbol = %s, "
        "mode = %s::rule_mode, active_version_id = %s, armed_at = now(), "
        "armed_by = owner_user_id, deleted_at = CASE WHEN %s THEN now() END WHERE id = %s",
        (level, first, "BTCUSDT" if level == "symbol" else None, mode, vid, deleted, rid),
    )
    return rid


def _retire(dsn: str, *rids: str) -> None:
    """Soft-deletes the rules: a live armed rule that lists no account blocks every account, so
    one a test made must not outlive it (the module shares one database)."""
    with _mig._conn(dsn) as c:
        c.execute("UPDATE rules SET deleted_at = now() WHERE id = ANY(%s::uuid[])", (list(rids),))


def _named(got: tuple[ArmedRule, ...]) -> list[tuple[str, str]]:
    return [(str(r.rule_id), r.name) for r in got]


def _store(dsn: str) -> PostgresArmedRules:
    return PostgresArmedRules(SqlAlchemyRelationalRepository(dsn, "armed-it"))


async def test_armed_on_lists_the_live_armed_rules_covering_the_account(pg_dsn: str) -> None:
    """#906 ruling B6, #4563: a profile delete's blockers are the live rules in `armed` whose
    active version covers the account, by lower(name) then id, at most `ARMED_SHOWN + 1`. A
    disabled, simulating or deleted rule and another account's are not; a `global`-level rule
    that lists the account is."""
    account, other, crowded = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with _mig._conn(pg_dsn) as c:
        owner, second = _mig._user(c), _mig._user(c)
        _armed(c, owner, "off", account, mode="disabled")
        _armed(c, owner, "sim", account, mode="simulate")
        _armed(c, owner, "gone", account, deleted=True)
        _armed(c, owner, "theirs", other)
        everywhere = (_armed(c, owner, "everywhere", account, level="global"), "everywhere")
        gamma, beta, alpha = [(_armed(c, owner, n, account), n) for n in ("Gamma", "beta", "Alpha")]
        twins = [(_armed(c, who, n, account), n) for who, n in ((owner, "Dup"), (second, "dup"))]
        names = [f"r{i:02}" for i in range(ARMED_SHOWN + 2)]
        many = [(_armed(c, owner, n, crowded), n) for n in names]
    rules = _store(pg_dsn)
    assert _named(await rules.armed_on(account)) == [alpha, beta, *sorted(twins), everywhere, gamma]
    assert _named(await rules.armed_on(crowded)) == many[:-1]
    assert await rules.armed_on(uuid.uuid4()) == ()


async def test_armed_on_two_account_rule_blocks_both_accounts(pg_dsn: str) -> None:
    """AC1: a rule listing A then B blocks a delete on B too, not on A only (the first-account
    column)."""
    a, b = uuid.uuid4(), uuid.uuid4()
    with _mig._conn(pg_dsn) as c:
        rule = (_armed(c, _mig._user(c), "pair", a, b), "pair")
    rules = _store(pg_dsn)
    assert [_named(await rules.armed_on(x)) for x in (a, b)] == [[rule], [rule]]


async def test_armed_on_matches_an_uppercase_stored_account_id(pg_dsn: str) -> None:
    """A stored id in uppercase still names the account (UUID compare, not string compare)."""
    a = uuid.uuid4()
    ir = _scope_ir("account", ()) | {"scope": {"level": "account", "account_ids": [str(a).upper()]}}
    with _mig._conn(pg_dsn) as c:
        rid = _armed(c, _mig._user(c), "shout", level="global", ir=ir)
    assert _named(await _store(pg_dsn).armed_on(a)) == [(rid, "shout")]
    assert await _store(pg_dsn).armed_on(uuid.uuid4()) == ()


async def test_armed_on_rule_listing_no_account_blocks_every_account(pg_dsn: str) -> None:
    """AC2: a rule that lists no account runs on every granted account, so it blocks any."""
    with _mig._conn(pg_dsn) as c:
        rid = _armed(c, _mig._user(c), "all-of-them", level="global")
    try:
        got = [_named(await _store(pg_dsn).armed_on(uuid.uuid4())) for _ in range(2)]
        assert got == [[(rid, "all-of-them")]] * 2
    finally:
        _retire(pg_dsn, rid)


async def test_armed_on_unrelated_rule_blocks_none(pg_dsn: str) -> None:
    a, c_acct = uuid.uuid4(), uuid.uuid4()
    with _mig._conn(pg_dsn) as c:
        _armed(c, _mig._user(c), "elsewhere", c_acct, uuid.uuid4())
    assert await _store(pg_dsn).armed_on(a) == ()


async def test_armed_on_symbol_level_rule_listing_the_account_blocks_it(pg_dsn: str) -> None:
    """The level does not decide: a `symbol`-level rule that lists the account covers it."""
    a, b = uuid.uuid4(), uuid.uuid4()
    with _mig._conn(pg_dsn) as c:
        rid = _armed(c, _mig._user(c), "btc-only", b, a, level="symbol")
    rules = _store(pg_dsn)
    got = (_named(await rules.armed_on(a)), await rules.armed_on(uuid.uuid4()))
    assert got == ([(rid, "btc-only")], ())


async def test_armed_on_reads_the_active_version_not_the_first(pg_dsn: str) -> None:
    """Version 1 lists A (and the `scope_account_id` column keeps A); the active version 2 lists
    B: B is blocked, A is not."""
    a, b = uuid.uuid4(), uuid.uuid4()
    with _mig._conn(pg_dsn) as c:
        rid = _armed(c, _mig._user(c), "moved", a)
        v2 = _version(c, rid, 2, _scope_ir("account", (b,)))
        c.execute("UPDATE rules SET active_version_id = %s WHERE id = %s", (v2, rid))
    rules = _store(pg_dsn)
    assert (await rules.armed_on(a), _named(await rules.armed_on(b))) == ((), [(rid, "moved")])


@pytest.mark.parametrize(
    "ir",
    [
        {"conditions": {}, "actions": []},
        {"conditions": {}, "actions": [], "scope": {"level": "symbol", "symbols": ["BTCUSDT"]}},
        {"conditions": {}, "actions": [], "scope": {"level": "account", "account_ids": None}},
        {"conditions": {}, "actions": [], "scope": {"level": "account", "account_ids": "x"}},
        {"conditions": {}, "actions": [], "scope": {"level": "account", "account_ids": [None]}},
        {"conditions": {}, "actions": [], "scope": {"level": "account", "account_ids": [123]}},
        {"conditions": {}, "actions": [], "scope": {"level": "account", "account_ids": ["nope"]}},
        {"conditions": {}, "actions": [], "scope": {"level": "account", "account_ids": [{}]}},
    ],
    ids=[
        "no-scope",
        "no-list",
        "null-list",
        "not-a-list",
        "null-item",
        "number-item",
        "bad-uuid",
        "object-item",
    ],
)
async def test_armed_on_rule_without_a_readable_account_list_fails_closed(
    pg_dsn: str, ir: dict[str, object]
) -> None:
    """A version whose account list is missing, not an array, or holds an element that is not an
    account id blocks every account."""
    with _mig._conn(pg_dsn) as c:
        rid = _armed(c, _mig._user(c), "unreadable", level="global", ir=ir)
    try:
        assert _named(await _store(pg_dsn).armed_on(uuid.uuid4())) == [(rid, "unreadable")]
    finally:
        _retire(pg_dsn, rid)


@pytest.mark.parametrize(
    ("mode", "deleted"), [("disabled", False), ("simulate", False), ("armed", True)],
    ids=["disabled", "simulate", "deleted"],
)  # fmt: skip
async def test_armed_on_rule_not_armed_and_live_blocks_none(
    pg_dsn: str, mode: str, deleted: bool
) -> None:
    """A rule that lists no account blocks nothing unless it is armed and live."""
    with _mig._conn(pg_dsn) as c:
        rid = _armed(c, _mig._user(c), "idle", level="global", mode=mode, deleted=deleted)
    try:
        assert await _store(pg_dsn).armed_on(uuid.uuid4()) == ()
    finally:
        _retire(pg_dsn, rid)


async def test_armed_on_reads_a_rule_the_manager_armed_over_two_accounts(pg_dsn: str) -> None:
    """End to end through `RulesManager` and `PostgresRuleStore`: the IR as the manager stores it
    is what the query reads; once disarmed the rule blocks neither account."""
    a, b = uuid.uuid4(), uuid.uuid4()
    repo = SqlAlchemyRelationalRepository(pg_dsn, "armed-e2e")
    actor = Actor(await _owner(repo), "s1", frozenset({"rules:write"}), is_owner=True)
    mgr = RulesManager(PostgresRuleStore(repo), default_registry())
    scope = {"level": "account", "account_ids": [str(a), str(b)]}
    ir = _ir("1") | {"name": f"pair-{a.hex[:8]}", "scope": scope}
    rid = (await mgr.create(ir, actor))["id"]
    try:
        await mgr.set_mode(rid, "simulate", actor, "k1")
        active = (await mgr.get(rid, actor))["active_version_id"]
        h = next(v["ir_hash"] for v in await mgr.versions(rid) if v["id"] == active)
        await mgr.record_simulation(rid, h, 5, 0.0)
        await mgr.set_mode(rid, "armed", actor, "k2")
        rules = _store(pg_dsn)
        assert [[str(r.rule_id) for r in await rules.armed_on(x)] for x in (a, b)] == [[rid]] * 2
        await mgr.set_mode(rid, "disabled", actor, "k3")
        assert [await rules.armed_on(x) for x in (a, b)] == [(), ()]
    finally:
        _retire(pg_dsn, rid)


async def test_covering_lists_past_the_delete_guards_cap_by_the_same_predicate(
    pg_dsn: str,
) -> None:
    """#898 ruling 10: the consequence read lists every armed rule covering the account, one
    that lists no account included, by the guard's predicate; `limit` bounds it."""
    account = uuid.uuid4()
    with _mig._conn(pg_dsn) as c:
        owner = _mig._user(c)
        many = [(_armed(c, owner, f"c{i:02}", account), f"c{i:02}") for i in range(ARMED_SHOWN + 2)]
        _armed(c, owner, "off", account, mode="disabled")
        everywhere = _armed(c, owner, "zz-everywhere", level="global")
    rules = _store(pg_dsn)
    try:
        got = _named(await rules.covering(account, limit=100))
        assert got == [*many, (everywhere, "zz-everywhere")]
        assert _named(await rules.covering(account, limit=3)) == many[:3]
        assert await rules.armed_on(account) == await rules.covering(account, limit=ARMED_SHOWN + 1)
        with pytest.raises(ValueError):
            await rules.covering(account, limit=0)
    finally:
        _retire(pg_dsn, everywhere)


# ----- #2291 (SR-051): the scoped reads, the account sets and the fill ---------------------------


def _refs_ir(
    scope: tuple[str, ...] = (), *, metric: str | None = None, param: str | None = None
) -> dict[str, Any]:
    """A stored IR naming `scope`'s accounts, and one more in a metric reference or in a nested
    action parameter: the three places the walker reads an account."""
    ir: dict[str, Any] = {
        "conditions": {"left": {"metric": "price"}},
        "actions": [{"type": "send_notification", "params": {}}],
        "scope": {"level": "account" if scope else "global", "account_ids": list(scope)},
    }
    if metric is not None:
        ir["conditions"]["left"]["account_id"] = metric
    if param is not None:
        ir["actions"][0]["params"]["route"] = {"account_ids": [param]}
    return ir


def _row(
    owner: str, *versions: dict[str, Any], deleted: bool = False, rid: str = "", name: str = ""
) -> RuleRow:
    """A rule of `owner` holding `versions` in order, the last one active, as `put` stores it."""
    rid = rid or str(uuid.uuid4())
    vs = [
        VersionRow(str(uuid.uuid5(uuid.UUID(rid), str(n))), rid, n, ir,
                   hashlib.sha256(f"{rid}/{n}".encode()).hexdigest(), "1.0.0", "", owner, "")
        for n, ir in enumerate(versions, start=1)
    ]  # fmt: skip
    return RuleRow(
        rid, name or f"rule-{rid}", owner, active_version_id=vs[-1].id,
        latest_version=len(vs), deleted=deleted, versions=vs,
    )  # fmt: skip


async def _page(store: PostgresRuleStore, scope: RuleReadScope, **kw: Any) -> list[str]:
    asked = {"mode": None, "level": None, "after": None, "limit": 50} | kw
    return [r.id for r in await store.scoped_page(scope, **asked)]


def _refs(dsn: str, rule_id: str) -> dict[str, Any]:
    """Each version's stored `account_refs` (a list, or None when not computed), by version id."""
    with _mig._conn(dsn) as c:
        rows = c.execute(
            "SELECT id::text, account_refs FROM rule_versions WHERE rule_id = %s", (rule_id,)
        ).fetchall()
    return {str(row[0]): row[1] for row in rows}


async def test_a_grant_scope_reads_only_the_callers_live_rules_on_granted_accounts(
    pg_dsn: str,
) -> None:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    store = PostgresRuleStore(SqlAlchemyRelationalRepository(pg_dsn, "rules-scope-it"))
    with _mig._conn(pg_dsn) as c:
        me, other = _mig._user(c), _mig._user(c)
    on_a, none, on_b = _row(me, _refs_ir((a,))), _row(me, _refs_ir()), _row(me, _refs_ir((b,)))
    gone, theirs = _row(me, _refs_ir((a,)), deleted=True), _row(other, _refs_ir((a,)))
    for rule in (on_a, none, on_b, gone, theirs):
        await store.put(rule)
    granted = GrantRead(me, frozenset({a}))
    assert await _page(store, granted) == sorted([on_a.id, none.id])
    assert await store.scoped_ids(granted) == {on_a.id, none.id}
    assert await store.scoped_ids(GrantRead(me, frozenset())) == {none.id}
    assert await store.scoped_ids(GrantRead(me, frozenset({a, b}))) == {on_a.id, none.id, on_b.id}
    assert await store.scoped_ids(GrantRead(other, frozenset({a, b}))) == {theirs.id}
    read = (await store.scoped_page(granted, mode=None, level=None, after=None, limit=1))[0]
    assert [v.ir for v in read.versions] == [min((on_a, none), key=lambda r: r.id).versions[0].ir]


async def test_the_owner_scope_reads_every_live_rule_for_a_live_owner_only(pg_dsn: str) -> None:
    repo = SqlAlchemyRelationalRepository(pg_dsn, "rules-owner-it")
    store = PostgresRuleStore(repo)
    boss, lapsed, expired = await _owner(repo), await _owner(repo), await _owner(repo)
    with _mig._conn(pg_dsn) as c:
        someone, plain = _mig._user(c), _mig._user(c)
        c.execute("UPDATE users SET status = 'disabled' WHERE id = %s", (lapsed,))
        c.execute(
            "UPDATE user_roles SET granted_at = now() - interval '2 days', "
            "expires_at = now() - interval '1 day' WHERE user_id = %s",
            (expired,),
        )
    theirs = _row(someone, _refs_ir((str(uuid.uuid4()),)))
    gone = _row(someone, _refs_ir(), deleted=True)
    for rule in (theirs, gone):
        await store.put(rule)
    ids = await store.scoped_ids(OwnerRead(boss))
    assert theirs.id in ids and gone.id not in ids
    assert await _page(store, OwnerRead(boss), only=theirs.id) == [theirs.id]
    assert await store.name_taken(OwnerRead(boss), theirs.name, "") is True
    for nobody in (plain, lapsed, expired):  # no live owner role: the Owner scope reads nothing
        assert await store.scoped_ids(OwnerRead(nobody)) == frozenset()
        assert await _page(store, OwnerRead(nobody)) == []
        assert await store.name_taken(OwnerRead(nobody), theirs.name, "") is False


async def test_pages_of_one_chain_over_interleaved_ids_in_each_scope(pg_dsn: str) -> None:
    """Ids interleaved with rules the caller does not read: a page of one row at a time walks the
    caller's rows in id order, by the keyset, with none missing or repeated."""
    repo = SqlAlchemyRelationalRepository(pg_dsn, "rules-chain-it")
    store = PostgresRuleStore(repo)
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    boss = await _owner(repo)
    with _mig._conn(pg_dsn) as c:
        me, other = _mig._user(c), _mig._user(c)
    prefix = uuid.uuid4().hex[:24]
    ids = [str(uuid.UUID(prefix + f"{n:08x}")) for n in range(1, 9)]
    plan: list[tuple[str, tuple[dict[str, Any], ...], bool]] = [
        (me, (_refs_ir((a,)),), False), (other, (_refs_ir((a,)),), False),
        (me, (_refs_ir((b,)),), False), (me, (_refs_ir(),), False),
        (other, (_refs_ir(),), False), (me, (_refs_ir((a,)),), True),
        (me, (_refs_ir((b,)), _refs_ir((a,))), False), (me, (_refs_ir((a,)),), False),
    ]  # fmt: skip
    for rid, (who, versions, deleted) in zip(ids, plan, strict=True):
        await store.put(_row(who, *versions, deleted=deleted, rid=rid))
    manager = RulesManager(store, default_registry())
    caller = Actor(me, "s", granted_accounts=frozenset({a}))
    walked: list[str] = []
    cursor: str | None = None
    while True:
        page = await manager.list_rules(caller, cursor=cursor, limit=1)
        walked += [str(i["id"]) for i in page["items"]]
        if (cursor := page["next_cursor"]) is None:
            break
    assert walked == [ids[0], ids[3], ids[7]]
    chained: list[str] = []
    after: str | None = None
    while (got := await _page(store, OwnerRead(boss), after=after, limit=1)) != []:
        chained += got
        after = got[0]
    assert chained == sorted(set(chained))  # in id order, none repeated
    assert [rid for rid in chained if rid in ids] == [ids[n] for n in (0, 1, 2, 3, 4, 6, 7)]


async def test_a_version_with_no_computed_set_is_outside_every_grant_scope_until_filled(
    pg_dsn: str,
) -> None:
    repo = SqlAlchemyRelationalRepository(pg_dsn, "rules-null-it")
    store = PostgresRuleStore(repo)
    a = str(uuid.uuid4())
    boss = await _owner(repo)
    with _mig._conn(pg_dsn) as c:
        me = _mig._user(c)
    grant = GrantRead(me, frozenset({a}))
    assert await store.scoped_ids(grant) == frozenset()  # this process has filled
    on_a, none = _row(me, _refs_ir((a,))), _row(me, _refs_ir())
    for rule in (on_a, none):
        await store.put(rule)
    with _mig._conn(pg_dsn) as c:
        c.execute(
            "UPDATE rule_versions SET account_refs = NULL WHERE rule_id = ANY(%s::uuid[])",
            ([on_a.id, none.id],),
        )
    assert await store.scoped_ids(grant) == frozenset()  # NULL is outside the scope
    assert await _page(store, grant, only=on_a.id) == []
    assert {on_a.id, none.id} <= await store.scoped_ids(OwnerRead(boss))
    restarted = PostgresRuleStore(repo)  # a new process fills before its first grant read
    assert await restarted.scoped_ids(grant) == {on_a.id, none.id}
    assert await store.scoped_ids(grant) == {on_a.id, none.id}
    assert list(_refs(pg_dsn, none.id).values()) == [[]]  # an empty set, not NULL


async def test_the_fill_writes_only_the_versions_that_hold_none(pg_dsn: str) -> None:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    with _mig._conn(pg_dsn) as c:
        owner = _mig._user(c)
        rid = _mig._rule(c, owner)
        named: dict[str, object] = {
            "conditions": {},
            "actions": [],
            "scope": {"account_ids": [b, a, b]},
        }
        v1 = _version(c, rid, 1, named)
        v2 = _version(c, rid, 2, {"conditions": {}, "actions": [], "scope": {"account_ids": [a]}})
        v3 = _version(c, rid, 3, {"conditions": {}, "actions": []})
        c.execute("UPDATE rule_versions SET account_refs = ARRAY['kept'] WHERE id = %s", (v2,))
    store = PostgresRuleStore(SqlAlchemyRelationalRepository(pg_dsn, "rules-fill-it"))
    await store.scoped_ids(GrantRead(owner, frozenset()))
    assert _refs(pg_dsn, rid) == {v1: sorted([a, b]), v2: ["kept"], v3: []}
    with _mig._conn(pg_dsn) as c:
        left = c.execute("SELECT count(*) FROM rule_versions WHERE account_refs IS NULL").fetchone()
    assert left == (0,)


async def test_each_saved_version_holds_the_account_set_the_walker_reads(pg_dsn: str) -> None:
    a, b, c_acct = (str(uuid.uuid4()) for _ in range(3))
    repo = SqlAlchemyRelationalRepository(pg_dsn, "rules-refs-it")
    store = PostgresRuleStore(repo)
    with _mig._conn(pg_dsn) as c:
        me = _mig._user(c)
    rule = _row(me, _refs_ir((b, a, b)), _refs_ir(metric=c_acct, param=a.upper()))
    await store.put(rule)
    first, second = rule.versions
    stored = _refs(pg_dsn, rule.id)
    assert stored == {first.id: sorted([a, b]), second.id: sorted([a.upper(), c_acct])}
    assert all(stored[v.id] == sorted(set(collect_account_ids(v.ir))) for v in rule.versions)
    boss = Actor(await _owner(repo), "s", frozenset({"rules:write"}), is_owner=True)
    made = await RulesManager(store, default_registry()).create(
        _ir("1") | {"name": f"refs-{a[:8]}", "scope": {"level": "account", "account_ids": [a]}},
        boss,
    )
    assert list(_refs(pg_dsn, made["id"]).values()) == [[a]]


async def test_the_name_lookup_reads_own_rules_or_every_live_rule_for_the_owner(
    pg_dsn: str,
) -> None:
    repo = SqlAlchemyRelationalRepository(pg_dsn, "rules-name-it")
    store = PostgresRuleStore(repo)
    tag = uuid.uuid4().hex[:8]
    boss = await _owner(repo)
    with _mig._conn(pg_dsn) as c:
        me, other = _mig._user(c), _mig._user(c)
    mine = _row(me, _refs_ir((str(uuid.uuid4()),)), name=f"alpha-{tag}")
    theirs = _row(other, _refs_ir(), name=f"beta-{tag}")
    gone = _row(me, _refs_ir(), name=f"gamma-{tag}", deleted=True)
    for rule in (mine, theirs, gone):
        await store.put(rule)
    own = GrantRead(me, frozenset())  # no grants: the caller's own rule counts, readable or not
    assert await store.name_taken(own, mine.name, "") is True
    assert await store.name_taken(own, mine.name, mine.id) is False  # the rule being saved
    assert await store.name_taken(own, theirs.name, "") is False  # never another user's
    assert await store.name_taken(own, gone.name, "") is False
    assert await store.name_taken(own, mine.name.upper(), "") is False  # the exact name
    assert await store.name_taken(OwnerRead(boss), theirs.name, "") is True


async def test_a_point_read_outside_the_scope_reads_no_row(pg_dsn: str) -> None:
    a = str(uuid.uuid4())
    store = PostgresRuleStore(SqlAlchemyRelationalRepository(pg_dsn, "rules-point-it"))
    with _mig._conn(pg_dsn) as c:
        me, other = _mig._user(c), _mig._user(c)
    mine = _row(me, _refs_ir((a,)))
    await store.put(mine)
    assert await _page(store, GrantRead(me, frozenset({a})), only=mine.id) == [mine.id]
    assert await _page(store, GrantRead(other, frozenset({a})), only=mine.id) == []
    assert await _page(store, GrantRead(me, frozenset()), only=mine.id) == []
    assert await _page(store, GrantRead(me, frozenset({a})), only=str(uuid.uuid4())) == []


async def test_the_scoped_reads_equal_rule_visible_over_a_seeded_population(pg_dsn: str) -> None:
    """A seeded population (fixed seed): several owners, accounts A, B and C named in the scope, a
    metric reference and a nested parameter, sometimes in another letter case, one to three
    versions, some rules deleted. For every actor, pages of one and of three chained by the keyset
    hold exactly the rows `rule_visible` shows, in id order, and so do the scoped ids."""
    rng = random.Random(2291)  # noqa: S311  (a fixed seed for a reproducible population)
    repo = SqlAlchemyRelationalRepository(pg_dsn, "rules-population-it")
    store = PostgresRuleStore(repo)
    accounts = [str(uuid.UUID(int=rng.getrandbits(128))) for _ in range(3)]
    with _mig._conn(pg_dsn) as c:
        owners = [_mig._user(c) for _ in range(3)]
    boss = await _owner(repo)

    def ref() -> str | None:
        account = rng.choice([None, None, *accounts])
        return account.upper() if account is not None and rng.random() < 0.1 else account

    for _ in range(24):
        versions = [
            _refs_ir(tuple(rng.sample(accounts, rng.randint(0, 2))), metric=ref(), param=ref())
            for _ in range(rng.randint(1, 3))
        ]
        rid = str(uuid.UUID(int=rng.getrandbits(128)))
        await store.put(_row(rng.choice(owners), *versions, deleted=rng.random() < 0.2, rid=rid))
    every = await store.all()
    grants = [frozenset(g) for k in range(4) for g in itertools.combinations(accounts, k)]
    actors = [Actor(o, "s", granted_accounts=g) for o in owners for g in grants]
    for actor in [*actors, Actor(boss, "s", is_owner=True)]:
        scope = read_scope(actor)
        shown = sorted(r.id for r in every if rule_visible(r, actor))
        for size in (1, 3):
            walked: list[str] = []
            after: str | None = None
            while True:
                page = await _page(store, scope, after=after, limit=size + 1)
                walked += page[:size]
                if len(page) <= size:
                    break
                after = page[size - 1]
            assert walked == shown, (actor.user_id, actor.is_owner, sorted(actor.granted_accounts))
        assert await store.scoped_ids(scope) == frozenset(shown)
