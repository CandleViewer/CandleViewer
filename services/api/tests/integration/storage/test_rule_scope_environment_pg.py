"""Integration: the scope source reads each granted account's environment (E35-T10 #5002, BQ-3).

`SqlAlchemyScopeSource.load_account_environments` is one static, parameterised read of
`exchange_accounts.env` (revision `0017`), on real Postgres 16 at head: each live account of the
ones asked about with its environment, a soft-deleted one and one that does not exist left out, so
the scope snapshot reads their environment as not read and the action re-check refuses them.
Seeded as `test_rule_runs_write_ahead_pg.py` seeds its world; `testcontainers` in CI.
"""

from __future__ import annotations

import uuid

import pytest

from candleviewer.rules.ir.models import RuleScope
from candleviewer.rules.scope import ScopeInstanceRef, ScopeResolver
from candleviewer.rules.scope_state import SnapshotScopeState
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.scope_sqlalchemy import SqlAlchemyScopeSource
from tests.integration import _refused
from tests.integration.storage.test_tg_frozen_after_draft_pg import _USER, _conn, db

pytestmark = pytest.mark.integration

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16 at head
__all__ = ["db", "pg_dsn"]  # fixtures, imported for this module
DEMO, TESTNET, GONE, NEVER = (uuid.UUID(int=n) for n in (0xD1, 0xD2, 0xD3, 0xD4))


def _seed(dsn: str) -> None:
    """The user, granted three accounts: one on demo, one on testnet, one soft-deleted."""
    with _conn(dsn) as c:
        c.execute(
            "INSERT INTO users (id, email, username, password_hash, status) "
            "VALUES (%s, 'u@example.test', 'user_one', '$argon2id$x', 'active')",
            (_USER,),
        )
        for n, (account, env) in enumerate(((DEMO, "demo"), (TESTNET, "testnet"), (GONE, "demo"))):
            c.execute(
                "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
                "VALUES (%s, 'bybit', %s, 'main', %s, %s)",
                (account, env, str(1000 + n), f"acct-{n}"),
            )
            c.execute(
                "INSERT INTO user_account_access (user_id, exchange_account_id, can_view) "
                "VALUES (%s, %s, true)",
                (_USER, account),
            )
        c.execute("UPDATE exchange_accounts SET deleted_at = now() WHERE id = %s", (GONE,))


async def test_the_scope_source_reads_each_granted_accounts_environment(db: str) -> None:
    _seed(db)
    source = SqlAlchemyScopeSource(SqlAlchemyRelationalRepository(db, "rule-scope-env"))
    read = await source.load_account_environments([DEMO, TESTNET, GONE, NEVER])
    assert read == {DEMO: "demo", TESTNET: "testnet"}  # the deleted and the missing: not read
    assert await source.load_account_environments([]) == {}

    async def audit(event: str, data: dict[str, str]) -> None:
        return None

    state = SnapshotScopeState(source)
    await state.refresh(_USER)
    resolver, scope = ScopeResolver(state, audit), RuleScope.model_validate({"level": "account"})
    verdicts = {
        a: resolver.check_action(scope, _USER, "demo", ScopeInstanceRef(f"*@{a}", None, a))
        for a in (DEMO, TESTNET, GONE)
    }
    assert verdicts == {DEMO: None, TESTNET: "environment", GONE: "environment"}
