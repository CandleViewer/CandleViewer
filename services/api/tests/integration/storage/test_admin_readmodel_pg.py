"""Integration: `SqlAlchemyAdminCounts` on real Postgres 16 (E42-T01).

One seeded dataset exercises every filter edge of the admin read-model counts: deleted rows,
user status, confirmed / unconfirmed / revoked MFA, disabled and deleted accounts, the demo/live
environment split (C-2.11), key status, revocation and the expiry horizon, resolved and
low-severity events, and per-main sub-account usage. Ids are deterministic and the password
hash is a fixed fake. Not run locally (no docker); CI integration lane.
"""

from __future__ import annotations

import itertools
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.admin_readmodel_sqlalchemy import (
    AccountTotals,
    SqlAlchemyAdminCounts,
    UserTotals,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 10, 15, 18, 0, tzinfo=UTC)
_FAKE_HASH = "$argon2id$fixed-test-vector"
_SNAP = '{"uid": "1", "permissions": {"ContractTrade": ["Order"]}}'
_IDS = itertools.count(1)


def _id() -> UUID:
    return UUID(int=next(_IDS))


def _seed(c: psycopg.Connection) -> None:
    users = [
        ("alice", "active", "confirmed"),
        ("bob", "active", None),
        ("carol", "active", "revoked"),
    ]
    users += [
        ("frank", "active", "unconfirmed"),
        ("dave", "invited", None),
        ("erin", "active", "deleted"),
    ]
    for name, status, mfa in users:
        uid = _id()
        c.execute(
            "INSERT INTO users (id, email, username, password_hash, status, deleted_at) "
            "VALUES (%s, %s, %s, %s, %s, CASE WHEN %s THEN now() END)",
            (uid, f"{name}@example.test", name, _FAKE_HASH, status, mfa == "deleted"),
        )
        if mfa in ("confirmed", "revoked", "unconfirmed"):
            c.execute(
                "INSERT INTO mfa_methods (id, user_id, kind, secret_enc, confirmed_at, revoked_at) "
                "VALUES (%s, %s, 'totp', '\\x00', CASE WHEN %s THEN now() END, "
                "CASE WHEN %s THEN now() END)",
                (_id(), uid, mfa != "unconfirmed", mfa == "revoked"),
            )
    m1, m2 = _account(c, "main", None), _account(c, "main", None)
    s1, s2 = _account(c, "sub", m1), _account(c, "sub", m1)
    s3, s4 = _account(c, "sub", m1, enabled=False), _account(c, "sub", m1, deleted=True)
    _account(c, "sub", m2)
    live = _account(c, "main", None, env="live")
    l1, _ = _account(c, "sub", live, env="live"), _account(c, "sub", live, env="live")
    _key(c, s1, "active", NOW + timedelta(days=10))  # expiring within 30 days
    _key(c, s2, "active", NOW + timedelta(days=60))
    _key(c, s2, "active", NOW + timedelta(days=5), revoked=True)  # revoked: never counted
    _key(c, m1, "active", None)
    _key(c, s3, "invalid", None)
    _key(c, s4, "active", NOW + timedelta(days=5))  # deleted account: never counted
    _key(c, m2, "expired", NOW - timedelta(days=1))
    _key(c, l1, "active", NOW + timedelta(days=3))  # live: never in the demo totals
    for component, kind, severity, resolved in [
        ("recorder", "disk_halt", "critical", False),
        ("recorder", "disk_halt", "critical", False),  # same incident, second occurrence
        ("ingestion", "ws_gap", "error", False),
        ("oms", "reject", "error", True),
        ("api", "slow", "warning", False),
    ]:
        c.execute(
            "INSERT INTO system_events (component, kind, severity, message, resolved_at) "
            "VALUES (%s, %s, %s, 'seeded', CASE WHEN %s THEN now() END)",
            (component, kind, severity, resolved),
        )


def _account(
    c: psycopg.Connection,
    kind: str,
    parent: UUID | None,
    *,
    enabled: bool = True,
    deleted: bool = False,
    env: str = "demo",
) -> UUID:
    acct = _id()
    c.execute(
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label, "
        "parent_account_id, is_enabled, deleted_at) "
        "VALUES (%s, 'bybit', %s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() END)",
        (acct, env, kind, str(acct.int), f"acct-{acct.int}", parent, enabled, deleted),
    )
    return acct


def _key(
    c: psycopg.Connection,
    acct: UUID,
    status: str,
    expires: datetime | None,
    *,
    revoked: bool = False,
) -> None:
    c.execute(
        "INSERT INTO api_keys (id, exchange_account_id, label, key_id_enc, key_id_last4, "
        "secret_enc, enc_nonce, dek_ref, permission_snapshot, status, expires_at, revoked_at) "
        "VALUES (%s, %s, 'k', '\\x01', 'AB12', '\\x02', %s, 'dek', %s, %s, %s, "
        "CASE WHEN %s THEN now() END)",
        (_id(), acct, bytes(12), _SNAP, status, expires, revoked),
    )


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        env = {**os.environ, "CV_PG_DSN": url.replace("postgresql+psycopg2", "postgresql+psycopg")}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=_ROOT, env=env, check=True
        )
        with psycopg.connect(
            url.replace("postgresql+psycopg2", "postgresql"), autocommit=True
        ) as c:
            _seed(c)
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture
async def relational(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield repo
    finally:
        await repo.dispose()


async def test_user_totals_count_active_users_without_a_confirmed_unrevoked_mfa(
    relational: SqlAlchemyRelationalRepository,
) -> None:
    counts = SqlAlchemyAdminCounts(relational, env="demo")
    assert await counts.user_totals() == UserTotals(total=5, active=4, without_mfa=3)


@pytest.mark.parametrize(
    ("env", "expected"),
    [("demo", AccountTotals(6, 5, 1, 1)), ("live", AccountTotals(3, 3, 1, 0))],
    ids=["demo-only", "live-only"],
)
async def test_account_totals_are_scoped_to_the_bound_environment(
    relational: SqlAlchemyRelationalRepository, env: str, expected: AccountTotals
) -> None:
    counts = SqlAlchemyAdminCounts(relational, env=env)
    assert await counts.account_totals(NOW + timedelta(days=30)) == expected


async def test_open_incidents_group_unresolved_errors_by_component_and_kind(
    relational: SqlAlchemyRelationalRepository,
) -> None:
    assert await SqlAlchemyAdminCounts(relational, env="demo").open_incidents() == 2


@pytest.mark.parametrize(("env", "used"), [("demo", 3), ("live", 2)], ids=["demo", "live"])
async def test_subaccounts_in_use_is_the_busiest_main_in_the_bound_environment(
    relational: SqlAlchemyRelationalRepository, env: str, used: int
) -> None:
    assert await SqlAlchemyAdminCounts(relational, env=env).subaccounts_in_use() == used
