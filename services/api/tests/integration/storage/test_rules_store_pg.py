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

from candleviewer.accounts.profile_repository import ARMED_SHOWN
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


def _ir(n: str) -> dict[str, object]:
    raw = json.loads(_FIX.read_text(encoding="utf-8"), parse_float=str)
    raw["conditions"]["right"]["const"] = n
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
    assert (await mgr.update(rid, _ir("2"), 1, actor))["version"]["version"] == 2
    assert (await mgr.update(rid, _ir("2"), 2, actor))["created"] is False  # UNIQUE(rule, hash)
    with pytest.raises(RuleError) as e:
        await mgr.update(rid, _ir("3"), 1, actor)
    assert e.value.status == 409
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


async def test_conflict_after_restart_names_the_other_session(pg_dsn: str) -> None:
    repo = SqlAlchemyRelationalRepository(pg_dsn, "rules-it-sess")
    uid = await _owner(repo)
    a = Actor(uid, "session-A", frozenset({"rules:write"}), is_owner=True)
    b = Actor(uid, "session-B", frozenset({"rules:write"}), is_owner=True)
    mgr = RulesManager(PostgresRuleStore(repo), default_registry())
    rid = (await mgr.create(_ir("1"), a))["id"]
    await mgr.update(rid, _ir("2"), 1, a)
    fresh = RulesManager(PostgresRuleStore(repo), default_registry())  # restart / other worker
    with pytest.raises(RuleError) as e:
        await fresh.update(rid, _ir("3"), 1, b)
    assert e.value.status == 409
    assert e.value.extra["session"] == "session-A"


def _armed(
    c: Any, owner: str, name: str, account: uuid.UUID, *, mode: str = "armed",
    scope: str = "account", deleted: bool = False,
) -> str:  # fmt: skip
    """A rule naming `account` in `mode`, with its version active and its arming recorded, so an
    armed one meets `rule_armed_shape`."""
    rid = _mig._rule(c, owner, name)
    c.execute(
        "UPDATE rules SET scope = %s::rule_scope, scope_account_id = %s, mode = %s::rule_mode, "
        "active_version_id = %s, armed_at = now(), armed_by = owner_user_id, "
        "deleted_at = CASE WHEN %s THEN now() END WHERE id = %s",
        (scope, account, mode, _mig._version(c, rid, 1, _mig._H1), deleted, rid),
    )
    return rid


async def test_armed_on_lists_the_live_armed_rules_scoped_to_the_account(pg_dsn: str) -> None:
    """#906 ruling B6, a profile delete's blockers: the account's live rules in `armed` with
    `scope='account'`, by lower(name) then id, at most `ARMED_SHOWN + 1`. A disabled, simulating
    or deleted rule, another account's, and one of another scope that names the account are not."""
    account, other, crowded = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with _mig._conn(pg_dsn) as c:
        owner, second = _mig._user(c), _mig._user(c)
        _armed(c, owner, "off", account, mode="disabled")
        _armed(c, owner, "sim", account, mode="simulate")
        _armed(c, owner, "gone", account, deleted=True)
        _armed(c, owner, "theirs", other)
        _armed(c, owner, "everywhere", account, scope="global")
        gamma, beta, alpha = [(_armed(c, owner, n, account), n) for n in ("Gamma", "beta", "Alpha")]
        twins = [(_armed(c, who, n, account), n) for who, n in ((owner, "Dup"), (second, "dup"))]
        names = [f"r{i:02}" for i in range(ARMED_SHOWN + 2)]
        many = [(_armed(c, owner, n, crowded), n) for n in names]
    rules = PostgresArmedRules(SqlAlchemyRelationalRepository(pg_dsn, "armed-it"))
    got = await rules.armed_on(account)
    assert [(str(r.rule_id), r.name) for r in got] == [alpha, beta, *sorted(twins), gamma]
    assert [(str(r.rule_id), r.name) for r in await rules.armed_on(crowded)] == many[:-1]
    assert await rules.armed_on(uuid.uuid4()) == ()
