"""Integration: the break-glass Owner reset on real Postgres 16 (E09-S11 #2119 slice 3).

The plan's named tests: S1 one transaction, S10 a failed reset changes zero rows,
S5 refusals for non-Owners (forbidden role), the cross-Owner (IDOR) case, and a
recovery code consumed once under concurrency. Not run locally (no docker);
exercised by CI `integration`.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.break_glass import (
    BREAK_GLASS_EVENT_KIND,
    BREAK_GLASS_REVOKED_REASON,
    BreakGlassRefusal,
    BreakGlassResetResult,
    BreakGlassResetService,
)
from candleviewer.auth.errors import BreakGlassRefused
from candleviewer.auth.recovery_codes import generate_recovery_code, hash_recovery_code
from candleviewer.storage.repositories.break_glass_sqlalchemy import (
    SqlAlchemyBreakGlassRepository,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_KEY = bytes(range(32))  # test-only HMAC key, not a credential
_PW = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA"  # placeholder digest, not a credential
_KINDS = {  # kind -> (role, status, owner role already expired)
    "owner": ("owner", "active", False),
    "manager": ("manager", "active", False),
    "viewer": ("viewer", "active", False),
    "disabled": ("owner", "disabled", False),
    "expired": ("owner", "active", True),
}
_UNTOUCHED, _RESET = (2, 2, 1, 0), (0, 0, 0, 1)  # `_state` before / after a reset
# A user and role, a confirmed and a pending TOTP method, two live sessions, one code.
_SEED = sa.text(
    "WITH u AS (INSERT INTO users (id, email, username, password_hash, status) VALUES "
    "(CAST(:u AS uuid), :email, :name, :pw, CAST(:status AS user_status)) RETURNING id), "
    "r AS (INSERT INTO user_roles (user_id, role_id, granted_at, expires_at) SELECT u.id, "
    "roles.id, CASE WHEN :expired THEN now() - interval '2 days' ELSE now() END, "
    "CASE WHEN :expired THEN now() - interval '1 day' END FROM u, roles "
    "WHERE roles.name = CAST(:role AS role_name)), "
    "m AS (INSERT INTO mfa_methods (id, user_id, kind, secret_enc, confirmed_at) "
    "SELECT gen_random_uuid(), u.id, CAST('totp' AS mfa_method_kind), "
    "convert_to('ciphertext', 'UTF8'), v.c FROM u, (VALUES (now()), (NULL)) AS v(c)), "
    "s AS (INSERT INTO sessions (id, user_id, refresh_token_hash, expires_at) "
    "SELECT gen_random_uuid(), u.id, encode(sha256(convert_to(CAST(gen_random_uuid() AS text), "
    "'UTF8')), 'hex'), now() + interval '1 hour' FROM u, generate_series(1, 2)) "
    "INSERT INTO recovery_codes (id, user_id, code_hash) SELECT gen_random_uuid(), u.id, :h FROM u"
)
_STATE = sa.text(
    "SELECT (SELECT count(*) FROM mfa_methods WHERE user_id = CAST(:u AS uuid) "
    "AND revoked_at IS NULL), (SELECT count(*) FROM sessions WHERE user_id = CAST(:u AS uuid) "
    "AND revoked_at IS NULL), (SELECT count(*) FROM recovery_codes "
    "WHERE user_id = CAST(:u AS uuid) AND used_at IS NULL), (SELECT count(*) FROM "
    "system_events WHERE kind = 'break_glass_used' AND details->>'target_user_id' = :t)"
)

#: Transaction ids of every row of the user and of the event (one if one transaction).
_XMINS = sa.text(
    "SELECT CAST(xmin AS text) FROM mfa_methods WHERE user_id = CAST(:u AS uuid) UNION "
    "SELECT CAST(xmin AS text) FROM sessions WHERE user_id = CAST(:u AS uuid) UNION "
    "SELECT CAST(xmin AS text) FROM recovery_codes WHERE user_id = CAST(:u AS uuid) UNION "
    "SELECT CAST(xmin AS text) FROM system_events WHERE id = :e"
)
_EVENT = sa.text(
    "SELECT component, kind, CAST(severity AS text), resolved_at, details->>'target_user_id', "
    "(SELECT string_agg(DISTINCT revoked_reason, ',') FROM sessions "
    "WHERE user_id = CAST(:u AS uuid)) FROM system_events WHERE id = :e"
)


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


@asynccontextmanager
async def _env(pg_dsn: str) -> AsyncIterator[tuple[AsyncEngine, BreakGlassResetService]]:
    engine = create_async_engine(pg_dsn)
    rel = SqlAlchemyRelationalRepository(pg_dsn, "breakglass")
    store = SqlAlchemyBreakGlassRepository(rel)
    try:
        yield engine, BreakGlassResetService(store, recovery_code_key=_KEY)
    finally:
        await rel.dispose()
        await engine.dispose()


async def _user(engine: AsyncEngine, kind: str = "owner") -> tuple[str, str]:
    """Seed a `_SEED` user; returns (user id, its unused recovery code)."""
    role, status, expired = _KINDS[kind]
    uid, code = str(uuid.uuid4()), generate_recovery_code()
    params: dict[str, object] = {"u": uid, "email": f"{uid}@example.invalid", "name": uid[:30]}
    params |= {"pw": _PW, "status": status, "role": role, "expired": expired}
    async with engine.begin() as conn:
        await conn.execute(_SEED, {**params, "h": hash_recovery_code(code, key=_KEY)})
    return uid, code


async def _state(engine: AsyncEngine, uid: str) -> tuple[int, ...]:
    """(unrevoked methods, live sessions, unused codes, break-glass events) of `uid`."""
    async with engine.connect() as conn:
        return tuple((await conn.execute(_STATE, {"u": uid, "t": uid})).one())


async def _reset(svc: BreakGlassResetService, uid: str, code: str) -> BreakGlassResetResult:
    target = uuid.UUID(uid)
    return await svc.reset(target, live=True, recovery_code=code, correlation_id=uuid.uuid4())


async def test_reset_is_one_transaction(pg_dsn: str) -> None:
    async with _env(pg_dsn) as (engine, svc):
        uid, code = await _user(engine)
        got = await _reset(svc, uid, code)
        params = {"u": uid, "e": got.system_event_id}
        async with engine.connect() as conn:
            xids = await conn.execute(_XMINS, params)
            event = await conn.execute(_EVENT, params)
            assert len(xids.all()) == 1  # every row the reset wrote has one transaction id
            assert tuple(event.one()) == (
                "auth",
                BREAK_GLASS_EVENT_KIND,
                "critical",
                None,
                uid,
                BREAK_GLASS_REVOKED_REASON,
            )
        assert (got.methods_revoked, got.sessions_revoked, got.recovery_code_consumed) == (
            2,
            2,
            True,
        )
        assert await _state(engine, uid) == _RESET


async def test_failed_reset_changes_zero_rows(pg_dsn: str) -> None:
    async with _env(pg_dsn) as (engine, svc):
        uid, code = await _user(engine)
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "CREATE FUNCTION bg_crash() RETURNS trigger LANGUAGE plpgsql AS "
                    "$f$ BEGIN RAISE EXCEPTION 'injected crash'; END $f$"
                )
            )
            await conn.execute(
                sa.text(
                    "CREATE TRIGGER bg_crash BEFORE INSERT ON system_events "
                    "FOR EACH ROW EXECUTE FUNCTION bg_crash()"
                )
            )
        try:  # the crash hits the last statement, after every revoke ran
            with pytest.raises(DBAPIError, match="injected crash"):
                await _reset(svc, uid, code)
        finally:
            async with engine.begin() as conn:
                await conn.execute(sa.text("DROP TRIGGER bg_crash ON system_events"))
                await conn.execute(sa.text("DROP FUNCTION bg_crash()"))
        assert await _state(engine, uid) == _UNTOUCHED  # the code was not consumed either
        await _reset(svc, uid, code)  # a re-run succeeds
        assert await _state(engine, uid) == _RESET


@pytest.mark.parametrize("target", ["manager", "viewer", "disabled", "expired"])
async def test_refuses_manager_viewer_disabled(pg_dsn: str, target: str) -> None:
    async with _env(pg_dsn) as (engine, svc):
        owner, owner_code = await _user(engine)  # also keeps the owner floor satisfied
        uid, code = await _user(engine, target)
        # The target with its own code, then an unknown id with the Owner's valid code.
        for victim, attempt in ((uid, code), (str(uuid.uuid4()), owner_code)):
            with pytest.raises(BreakGlassRefused) as refused:
                await _reset(svc, victim, attempt)
            assert refused.value.reason == BreakGlassRefusal.NOT_OWNER
        assert [await _state(engine, u) for u in (owner, uid)] == [_UNTOUCHED] * 2


async def test_touches_only_named_owner(pg_dsn: str) -> None:
    async with _env(pg_dsn) as (engine, svc):
        (a, code_a), (b, code_b) = await _user(engine), await _user(engine)
        manager, _ = await _user(engine, "manager")
        with pytest.raises(BreakGlassRefused) as refused:
            await _reset(svc, a, code_b)  # another Owner's code
        assert refused.value.reason == BreakGlassRefusal.RECOVERY_CODE_INVALID
        everyone = (a, b, manager)
        assert [await _state(engine, u) for u in everyone] == [_UNTOUCHED] * 3
        await _reset(svc, a, code_a)
        assert [await _state(engine, u) for u in everyone] == [_RESET, _UNTOUCHED, _UNTOUCHED]


async def test_code_consumed_once_concurrently(pg_dsn: str) -> None:
    async with _env(pg_dsn) as (engine, svc):
        uid, code = await _user(engine)
        runs = await asyncio.gather(
            *(_reset(svc, uid, code) for _ in range(6)), return_exceptions=True
        )
        assert sum(isinstance(r, BreakGlassResetResult) for r in runs) == 1
        refused = [r.reason for r in runs if isinstance(r, BreakGlassRefused)]
        assert refused == [BreakGlassRefusal.RECOVERY_CODE_INVALID] * 5
        assert await _state(engine, uid) == _RESET
