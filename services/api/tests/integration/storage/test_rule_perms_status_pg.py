"""Integration (E42-T04 S5a, O5, #965): the two permission readers check `users.status` on real
Postgres 16, so a user who is not active loses every permission at once, before the asynchronous
rule disarm has run (SR-029, C-2.21). `SqlAlchemyScopeSource.load_permissions` feeds the rule
engine's scope gate on every tick, `SqlAlchemyIdentityProvider.session_info` `/auth/session` and
the WS principal; both are asked about the same users. Not run on a laptop without docker;
exercised by CI `integration`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.rules.scope_state import ARM_LIVE
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.scope_sqlalchemy import SqlAlchemyScopeSource

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_USER = sa.text(
    "INSERT INTO users (id, email, username, password_hash, status) VALUES (CAST(:id AS uuid), "
    ":email, :name, '$argon2id$fixture', 'active') ON CONFLICT DO NOTHING"
)
_ROLE = sa.text(
    "INSERT INTO user_roles (user_id, role_id) SELECT CAST(:id AS uuid), id FROM roles "
    "WHERE name = CAST(:role AS role_name) ON CONFLICT DO NOTHING"
)
# The standing owner (fixed id, so seeding it again is a no-op): the owner floor of migration 0001
# refuses a commit that leaves no active owner, so a test may disable the owner it made.
_BASELINE = "00000000-0000-4000-8000-0000000000b5"
_STATUS = "UPDATE users SET status = CAST('{}' AS user_status) WHERE id = CAST(:id AS uuid)"
_CHANGES = {  # what makes a user stop being live: a status other than `active`, or a soft delete
    **{s: _STATUS.format(s) for s in ("disabled", "locked", "invited")},
    "deleted": "UPDATE users SET deleted_at = now() WHERE id = CAST(:id AS uuid)",
}
#: What each reader answers for a user: the `permissions.code` rows of the user's live roles.
Reader = Callable[[uuid.UUID], Awaitable[frozenset[str]]]


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        env = {**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=_ROOT, env=env, check=True
        )
        yield dsn


@pytest.fixture
async def db(pg_dsn: str) -> AsyncIterator[tuple[AsyncEngine, dict[str, Reader]]]:
    rel, engine = SqlAlchemyRelationalRepository(pg_dsn), create_async_engine(pg_dsn)
    scope, identity = SqlAlchemyScopeSource(rel), SqlAlchemyIdentityProvider(rel)

    async def from_identity(user: uuid.UUID) -> frozenset[str]:
        return frozenset((await identity.session_info(str(user)))["permissions"])

    try:
        async with engine.begin() as conn:
            await conn.execute(
                _USER, {"id": _BASELINE, "email": "b5@x.invalid", "name": "baseline-b5"}
            )
            await conn.execute(_ROLE, {"id": _BASELINE, "role": "owner"})
        yield engine, {"rule_scope": scope.load_permissions, "session_info": from_identity}
    finally:
        await rel.dispose()
        await engine.dispose()


async def _user(engine: AsyncEngine, role: str) -> uuid.UUID:
    """An active user holding `role` (no expiry)."""
    uid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            _USER, {"id": str(uid), "email": f"{uid.hex}@x.invalid", "name": uid.hex[:12]}
        )
        await conn.execute(_ROLE, {"id": str(uid), "role": role})
    return uid


@pytest.fixture(params=["rule_scope", "session_info"])
def reader(request: pytest.FixtureRequest, db: tuple[AsyncEngine, dict[str, Reader]]) -> Reader:
    return db[1][request.param]


@pytest.mark.parametrize("role", ["owner", "manager", "viewer"])
async def test_active_user_keeps_the_perms_of_their_role(
    db: tuple[AsyncEngine, dict[str, Reader]], reader: Reader, role: str
) -> None:
    """Control: an active user keeps the codes of the role, and both readers agree, so a pass
    below is not a reader that answers empty for everyone. Only the owner holds `rules:arm_live`,
    the code the rule engine's live gate asks for."""
    engine, readers = db
    user = await _user(engine, role)
    perms = await reader(user)
    assert perms and perms == await readers["rule_scope"](user) == await readers["session_info"](
        user
    )
    assert (ARM_LIVE in perms) is (role == "owner")


@pytest.mark.parametrize("role", ["owner", "manager"])
@pytest.mark.parametrize("change", list(_CHANGES))
async def test_disabled_user_no_rule_perms(
    db: tuple[AsyncEngine, dict[str, Reader]], reader: Reader, role: str, change: str
) -> None:
    """O5, SR-029: a user who is not `active`, or is deleted, has no permission on the next read,
    with the role row still live: the rule engine's gate cannot arm live and the session
    principal holds nothing, whatever the asynchronous disarm has done yet."""
    engine, _ = db
    user = await _user(engine, role)
    assert await reader(user)
    async with engine.begin() as conn:
        await conn.execute(sa.text(_CHANGES[change]), {"id": str(user)})
    assert await reader(user) == frozenset()
