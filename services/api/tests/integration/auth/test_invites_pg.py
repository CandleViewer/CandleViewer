"""Integration: single-use invite redemption on real Postgres 16 (E09-S05).

Concurrent `consume` calls must have exactly one winner. Not run locally (no
docker); exercised by CI `integration`.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.models import InviteRecord, UserRecord
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories.invites_sqlalchemy import SqlAlchemyInviteRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserRepository
from scripts.seed_fixture_user import seed

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
PW = "pending-hash"
_COUNT = sa.text(
    "SELECT (SELECT count(*) FROM users WHERE username = :u) + "
    "(SELECT count(*) FROM user_invites WHERE token_hash = :h)"
)


async def _ok(user_id: uuid.UUID, role: str) -> None:
    return None


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


async def test_concurrent_consume_has_exactly_one_winner(pg_dsn: str) -> None:
    # `user_invites.created_at` defaults to the DB's now() and is CHECKed
    # `expires_at > created_at`, so the test clock must track real time; a frozen
    # date silently turns into an expired insert (IntegrityError -> False) once
    # the wall clock passes it (regression: failed from 2026-10-04).
    now = datetime.now(UTC)
    await seed(pg_dsn, "owner1", "correct horse battery")
    rel = SqlAlchemyRelationalRepository(pg_dsn)
    repo = SqlAlchemyInviteRepository(rel, lambda **f: InviteRecord.model_validate(f))
    try:
        users = SqlAlchemyUserRepository(
            rel, lambda **f: UserRecord.model_validate(f), clock=lambda: datetime.now(UTC)
        )
        owner = await users.find_by_identifier("owner1")
        assert owner is not None
        by = owner.id
        th = "h" * 64
        created = await repo.create_user_with_invite(
            user_id=uuid.uuid4(),
            invite_id=uuid.uuid4(),
            email="race@example.com",
            username="racer",
            display_name=None,
            role="viewer",
            placeholder_password_hash="$argon2id$x",  # noqa: S106 - placeholder, not a credential
            invited_by=by,
            token_hash=th,
            expires_at=now + timedelta(hours=72),
            audit=_ok,
        )
        assert created is True
        results = await asyncio.gather(
            *(repo.consume(th, now=now, pending_password_hash=PW) for _ in range(8))
        )
        assert sum(r is not None for r in results) == 1
        assert await repo.consume(th, now=now, pending_password_hash=PW) is None
    finally:
        await rel.dispose()


async def test_downgrade_to_viewer_rewrites_invite_and_user_role(pg_dsn: str) -> None:
    now = datetime.now(UTC)
    await seed(pg_dsn, "owner2", "correct horse battery")
    rel = SqlAlchemyRelationalRepository(pg_dsn)
    repo = SqlAlchemyInviteRepository(rel, lambda **f: InviteRecord.model_validate(f))
    try:
        users = SqlAlchemyUserRepository(
            rel, lambda **f: UserRecord.model_validate(f), clock=lambda: datetime.now(UTC)
        )
        owner = await users.find_by_identifier("owner2")
        assert owner is not None
        uid = uuid.uuid4()
        th = "d" * 64
        assert await repo.create_user_with_invite(
            user_id=uid,
            invite_id=uuid.uuid4(),
            email="legacy@example.com",
            username="legacy",
            display_name=None,
            role="manager",  # legacy row minted before #2109
            placeholder_password_hash="$argon2id$x",  # noqa: S106 - placeholder, not a credential
            invited_by=owner.id,
            token_hash=th,
            expires_at=now + timedelta(hours=72),
            audit=_ok,
        )
        await repo.downgrade_to_viewer(uid)
        async with rel.unit_of_work() as uow:
            inv = (
                (
                    await uow.session.execute(
                        sa.text(
                            "SELECT role::text FROM user_invites WHERE user_id = CAST(:i AS uuid)"
                        ),
                        {"i": str(uid)},
                    )
                )
                .scalars()
                .all()
            )
            roles = (
                (
                    await uow.session.execute(
                        sa.text(
                            "SELECT r.name::text FROM user_roles ur "
                            "JOIN roles r ON r.id = ur.role_id "
                            "WHERE ur.user_id = CAST(:i AS uuid)"
                        ),
                        {"i": str(uid)},
                    )
                )
                .scalars()
                .all()
            )
            other = (
                (
                    await uow.session.execute(
                        sa.text(
                            "SELECT r.name::text FROM user_roles ur "
                            "JOIN roles r ON r.id = ur.role_id "
                            "WHERE ur.user_id = CAST(:i AS uuid)"
                        ),
                        {"i": str(owner.id)},
                    )
                )
                .scalars()
                .all()
            )
        assert inv == ["viewer"] and roles == ["viewer"]
        assert "owner" in other  # unrelated user's role untouched
    finally:
        await rel.dispose()


async def test_refused_or_hung_write_ahead_audit_rolls_each_invite_action_back(
    pg_dsn: str,
) -> None:
    """#2510 (C-2.9): the owner hook runs inside the transaction after the rows are staged;
    a raise or a timeout persists nothing (no user or invite row; the old link stays valid)."""
    now, th, th2 = datetime.now(UTC), "w" * 64, "x" * 64
    by = uuid.UUID(str(await seed(pg_dsn, "owner3", "correct horse battery")))
    rel = SqlAlchemyRelationalRepository(pg_dsn)
    repo = SqlAlchemyInviteRepository(
        rel, lambda **f: InviteRecord.model_validate(f), audit_timeout_s=0.2
    )

    async def refuse(user_id: uuid.UUID, role: str) -> None:
        raise RuntimeError("audit refused")

    async def hang(user_id: uuid.UUID, role: str) -> None:
        await asyncio.Event().wait()

    uid, exp, ph = uuid.uuid4(), now + timedelta(hours=72), "$argon2id$x"  # not a credential
    new: dict[str, Any] = {"user_id": uid, "email": "ahead@example.com", "username": "ahead"}
    new |= {"display_name": None, "role": "viewer", "placeholder_password_hash": ph}
    new |= {"invite_id": uuid.uuid4(), "invited_by": by, "token_hash": th, "expires_at": exp}
    again: dict[str, Any] = {"invite_id": uuid.uuid4(), "token_hash": th2, "expires_at": exp}
    try:
        for hook, raised in ((refuse, RuntimeError), (hang, WriteAheadTimeout)):
            with pytest.raises(raised):
                await repo.create_user_with_invite(**new, audit=hook)
            async with rel.unit_of_work() as uow:
                left = await uow.session.execute(_COUNT, {"u": "ahead", "h": th})
                assert left.scalar_one() == 0
        assert await repo.create_user_with_invite(**new, audit=_ok) is True
        for hook, raised in ((refuse, RuntimeError), (hang, WriteAheadTimeout)):
            with pytest.raises(raised):
                await repo.reissue(uid, **again, invited_by=by, now=now, audit=hook)
            with pytest.raises(raised):
                await repo.revoke_open(uid, now=now, audit=hook)
        old = await repo.find_by_token_hash(th)
        assert old is not None and old.revoked_at is None  # the old link stays valid
        assert await repo.find_by_token_hash(th2) is None
    finally:
        await rel.dispose()
