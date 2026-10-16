"""Integration (#2713): `SqlAlchemyIdentityProvider.accounts` on real Postgres 16.

The accounts `GET /me` lists: an owner reaches every live account with `trade`; anyone else
only the live, unfrozen, viewable grants of their own, `trade` where `can_trade`. A soft-deleted
account, a soft-revoked or frozen grant, and another user's grant never appear, and an expired
owner role, or an owner who is disabled, locked or deleted, is no owner. Every test runs alone and
in any order: the `db` fixture keeps one active owner standing, because the owner floor (migration
0001) refuses a commit that leaves none. Not run locally (no docker); exercised by CI `integration`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_USER = sa.text(
    "INSERT INTO users (id, email, username, password_hash, status) VALUES (CAST(:id AS uuid), "
    ":email, :name, '$argon2id$fixture', 'active')"
)
# The standing owner: fixed id, so seeding it again is a no-op.
_BASELINE_OWNER = "00000000-0000-4000-8000-0000000000b0"
_BASELINE_USER = sa.text(
    "INSERT INTO users (id, email, username, password_hash, status) VALUES (CAST(:id AS uuid), "
    "'baseline-owner@x.invalid', 'baseline-owner', '$argon2id$fixture', 'active') "
    "ON CONFLICT DO NOTHING"
)
_BASELINE_ROLE = sa.text(
    "INSERT INTO user_roles (user_id, role_id) SELECT CAST(:id AS uuid), id FROM roles "
    "WHERE name = 'owner' ON CONFLICT DO NOTHING"
)
_ROLE = sa.text(
    "INSERT INTO user_roles (user_id, role_id, granted_at, expires_at) "
    "SELECT CAST(:id AS uuid), id, now() - interval '2 hours', "
    "CASE WHEN :expired THEN now() - interval '1 hour' END "
    "FROM roles WHERE name = CAST(:role AS role_name)"
)
_ACCOUNT = sa.text(
    "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label, created_at) "
    "VALUES (CAST(:id AS uuid), 'bybit', CAST(:env AS exchange_env), 'main', :uid, :label, "
    "now() - make_interval(mins => :age))"
)
_GRANT = sa.text(
    "INSERT INTO user_account_access (user_id, exchange_account_id, can_view, can_trade, frozen, "
    "frozen_at) VALUES (CAST(:user AS uuid), CAST(:account AS uuid), :view, :trade, :frozen, "
    "CASE WHEN :frozen THEN now() END)"
)
_SOFT_DELETE = sa.text(
    "UPDATE exchange_accounts SET deleted_at = now() WHERE id = CAST(:id AS uuid)"
)
_SET_STATUS = sa.text(
    "UPDATE users SET status = CAST(:status AS user_status) WHERE id = CAST(:id AS uuid)"
)
_SOFT_DELETE_USER = sa.text("UPDATE users SET deleted_at = now() WHERE id = CAST(:id AS uuid)")


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg"),
            },
            check=True,
        )
        yield dsn


@pytest.fixture
async def db(pg_dsn: str) -> AsyncIterator[tuple[SqlAlchemyIdentityProvider, AsyncEngine]]:
    rel, engine = SqlAlchemyRelationalRepository(pg_dsn), create_async_engine(pg_dsn)
    try:
        await _ensure_owner(engine)
        yield SqlAlchemyIdentityProvider(rel), engine
    finally:
        await rel.dispose()
        await engine.dispose()


async def _exec(engine: AsyncEngine, stmt: sa.TextClause, **params: object) -> None:
    async with engine.begin() as conn:
        await conn.execute(stmt, params)


async def _ensure_owner(engine: AsyncEngine) -> None:
    """Keep one active owner standing (idempotent). The owner floor of migration 0001 raises
    23514 at commit when a role row is written while the database holds no active owner, so
    without this a test passes only after another one left an owner behind (C-13.7)."""
    async with engine.begin() as conn:
        await conn.execute(_BASELINE_USER, {"id": _BASELINE_OWNER})
        await conn.execute(_BASELINE_ROLE, {"id": _BASELINE_OWNER})


async def _user(engine: AsyncEngine, role: str, *, expired: bool = False) -> str:
    uid = str(uuid.uuid4())
    name = f"u-{uid[:12]}"
    await _exec(engine, _USER, id=uid, email=f"{name}@x.invalid", name=name)
    await _exec(engine, _ROLE, id=uid, role=role, expired=expired)
    return uid


async def _account(engine: AsyncEngine, label: str, *, age: int, env: str = "demo") -> str:
    """A live account created `age` minutes ago, so `created_at` fixes the order."""
    aid = str(uuid.uuid4())
    await _exec(
        engine,
        _ACCOUNT,
        id=aid,
        env=env,
        uid=str(uuid.UUID(aid).int % 10**12),
        label=label,
        age=age,
    )
    return aid


async def _grant(
    engine: AsyncEngine,
    user: str,
    account: str,
    *,
    view: bool = True,
    trade: bool = False,
    frozen: bool = False,
) -> None:
    await _exec(engine, _GRANT, user=user, account=account, view=view, trade=trade, frozen=frozen)


def _view(accounts: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(a["label"], a["mode"]) for a in accounts]


async def test_an_owner_reaches_every_live_account_with_trade(db: Any) -> None:
    provider, engine = db
    owner = await _user(engine, "owner")
    old = await _account(engine, f"o-old-{owner[:6]}", age=30)
    live = await _account(engine, f"o-live-{owner[:6]}", age=20, env="testnet")
    gone = await _account(engine, f"o-gone-{owner[:6]}", age=10)
    await _exec(engine, _SOFT_DELETE, id=gone)
    got = await provider.accounts(owner)
    mine = [a for a in got if a["exchange_account_id"] in {old, live, gone}]
    assert [(a["exchange_account_id"], a["mode"]) for a in mine] == [
        (old, "trade"),
        (live, "trade"),
    ]
    assert {a["environment"] for a in mine} == {"demo", "testnet"}
    assert gone not in {a["exchange_account_id"] for a in got}


async def test_a_manager_reaches_only_live_unfrozen_viewable_grants_with_their_mode(
    db: Any,
) -> None:
    provider, engine = db
    manager, other = await _user(engine, "manager"), await _user(engine, "manager")
    tag = manager[:6]
    trade = await _account(engine, f"m-trade-{tag}", age=50)
    read = await _account(engine, f"m-read-{tag}", age=40)
    frozen = await _account(engine, f"m-frozen-{tag}", age=30)
    revoked = await _account(engine, f"m-revoked-{tag}", age=25)
    deleted = await _account(engine, f"m-deleted-{tag}", age=20)
    theirs = await _account(engine, f"m-theirs-{tag}", age=15)
    await _grant(engine, manager, trade, trade=True)
    await _grant(engine, manager, read)
    await _grant(engine, manager, frozen, trade=True, frozen=True)
    await _grant(engine, manager, revoked, view=False)
    await _grant(engine, manager, deleted, trade=True)
    await _exec(engine, _SOFT_DELETE, id=deleted)
    await _grant(engine, other, theirs, trade=True)
    got = await provider.accounts(manager)
    assert _view(got) == [(f"m-trade-{tag}", "trade"), (f"m-read-{tag}", "read")]
    assert [a["exchange_account_id"] for a in got] == [trade, read]


async def test_a_viewer_with_no_grant_reaches_nothing_and_an_unknown_user_nothing(db: Any) -> None:
    provider, engine = db
    viewer = await _user(engine, "viewer")
    await _account(engine, f"v-unreached-{viewer[:6]}", age=5)
    assert await provider.accounts(viewer) == []
    assert await provider.accounts(str(uuid.uuid4())) == []


async def test_an_expired_owner_role_is_no_owner(db: Any) -> None:
    provider, engine = db
    lapsed = await _user(engine, "owner", expired=True)
    granted = await _account(engine, f"x-granted-{lapsed[:6]}", age=9)
    await _account(engine, f"x-other-{lapsed[:6]}", age=8)
    await _grant(engine, lapsed, granted)
    assert _view(await provider.accounts(lapsed)) == [(f"x-granted-{lapsed[:6]}", "read")]


def _reached(accounts: list[dict[str, Any]]) -> set[str]:
    return {a["exchange_account_id"] for a in accounts}


@pytest.mark.parametrize("status", ["disabled", "locked"])
async def test_an_owner_who_is_not_active_reaches_nothing(db: Any, status: str) -> None:
    provider, engine = db
    owner = await _user(engine, "owner")
    account = await _account(engine, f"n-{status}-{owner[:6]}", age=7)
    assert account in _reached(await provider.accounts(owner))
    await _exec(engine, _SET_STATUS, id=owner, status=status)
    assert await provider.accounts(owner) == []


async def test_a_soft_deleted_owner_reaches_nothing(db: Any) -> None:
    provider, engine = db
    owner = await _user(engine, "owner")
    account = await _account(engine, f"n-deleted-{owner[:6]}", age=6)
    assert account in _reached(await provider.accounts(owner))
    await _exec(engine, _SOFT_DELETE_USER, id=owner)
    assert await provider.accounts(owner) == []
