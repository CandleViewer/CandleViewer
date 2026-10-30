"""Integration: `PostgresRuleStore` + `RulesManager` on real Postgres (E35-S01).

Versioning, dedupe, optimistic concurrency, armed-shape and quarantine persisted through
the real `0013_rules`/`0014` schema. Not run locally (no docker); exercised by the
integration CI job.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from candleviewer.accounts.profile_repository import ARMED_SHOWN, ArmedRule
from candleviewer.rules.manager import Actor, RuleError, RulesManager
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
