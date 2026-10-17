"""Integration e2e (QA #1658): the REAL app (`create_app`, storage_backend=real)
against Postgres 16 — Alembic head, seeded owner + TOTP, password login, TOTP
step, session cookie, `/auth/session`, logout/revoke, owner floor, and the
C-2.9 audit rows written by the real WAL-backed `AuditWriter`.

Deterministic: fixed auth clock (TOTP codes computed for it), no sleeps, no
network beyond the local testcontainer. Integration tests run in CI only (no
docker locally).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.app import create_app
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.models import MfaChallengeRecord, MfaMethodRecord
from candleviewer.auth.totp import generate_code, generate_secret, time_step_for
from candleviewer.auth.totp_skew import SKEW_HOLD_S
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.mfa_sqlalchemy import SqlAlchemyMfaRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from scripts.seed_fixture_user import seed

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
# Track real time: rows carry DB-stamped `created_at` (now()) and CHECKs such as
# `expires_at > created_at` make a frozen date a time bomb once the wall clock passes it.
_NOW = datetime.now(UTC).replace(microsecond=0)
_TOTP_KEY = bytes.fromhex("11" * 32)
_PEPPER = "it-pepper"
_PASSWORD = "correct horse battery"  # noqa: S105 -- throwaway fixture password


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


async def _seed_owner_with_totp(dsn: str, username: str) -> tuple[str, bytes]:
    """Seeder code path (mfa_required=true by default) + TOTP enrolment via
    the real MFA repository, the seed encrypted with the app's TOTP key."""
    user_id = await seed(dsn, username, _PASSWORD, _PEPPER)
    assert user_id is not None
    secret = generate_secret()
    rel = SqlAlchemyRelationalRepository(dsn)
    mfa = SqlAlchemyMfaRepository(
        rel,
        lambda **f: MfaMethodRecord.model_validate(f),
        lambda **f: MfaChallengeRecord.model_validate(f),
    )
    try:
        enc = TotpEncryptor(_TOTP_KEY)
        method = await mfa.create_pending_method(
            user_id, secret_enc=enc.encrypt(secret), secret_key_ref=enc.key_ref, label="it"
        )
        await mfa.confirm_method(str(method.id), now=_NOW)
    finally:
        await rel.dispose()
    return user_id, secret


@pytest.fixture
async def client(pg_dsn: str, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        environment=Environment.TESTNET,
        storage_backend="real",
        pg_dsn=SecretStr(pg_dsn),
        auth_totp_key_hex=SecretStr(_TOTP_KEY.hex()),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
        auth_pepper=SecretStr(_PEPPER),
        audit_wal_path=str(tmp_path / "audit.wal"),
    )
    app = create_app(settings, auth_clock=lambda: _NOW)
    ctx = app.state.app_context
    # Only the modules under test: StorageService(real) is not implemented yet
    # (raises StorageTierUnavailable), and auth/audit own their own engines.
    await ctx.audit.start(ctx)
    await ctx.auth.start(ctx)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
            c.app_context = ctx  # type: ignore[attr-defined]  # test-only handle
            yield c
    finally:
        await ctx.audit.writer.flush(10.0)
        await ctx.auth.stop(1.0)
        await ctx.audit.stop(1.0)


def _code(secret: bytes, at: datetime = _NOW) -> str:
    return generate_code(secret, time_step_for(at.timestamp()))


async def _audit_rows(dsn: str, user_marker: str) -> list[dict[str, Any]]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                sa.text(
                    "SELECT action, actor_label, actor_user_id::text AS actor_user_id, "
                    "host(actor_ip) AS actor_ip, outcome::text AS outcome, reason, "
                    "object_id, before_state, after_state, session_id::text AS session_id "
                    "FROM audit_log WHERE actor_label LIKE :m OR actor_user_id::text = :m "
                    "OR object_id = :m ORDER BY id"
                ),
                {"m": user_marker},
            )
            return [dict(r._mapping) for r in rows]
    finally:
        await engine.dispose()


async def _login_and_verify(c: httpx.AsyncClient, username: str, secret: bytes) -> httpx.Response:
    r = await c.post("/auth/login", json={"identifier": username, "password": _PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "mfa_required" and r.json()["methods"] == ["totp"]
    return await c.post(
        "/auth/mfa/verify",
        json={"mfa_token": r.json()["mfa_token"], "method": "totp", "code": _code(secret)},
    )


async def test_login_totp_session_cookie_session_logout_round_trip(
    pg_dsn: str, client: httpx.AsyncClient
) -> None:
    user_id, secret = await _seed_owner_with_totp(pg_dsn, "e2e_owner")

    verified = await _login_and_verify(client, "e2e_owner", secret)
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["status"] == "authenticated" and body["user"]["id"] == user_id
    assert body["tokens"]["token_type"] == "Bearer"  # noqa: S105 -- scheme name
    cookie = verified.headers["set-cookie"].lower()
    assert cookie.startswith("cv_refresh=")
    assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie
    assert "path=/api/v1/auth" in cookie

    csrf = verified.cookies[CSRF_COOKIE]  # SR-041: issued with the session (#2090)
    bearer = {"Authorization": f"Bearer {body['tokens']['access_token']}", CSRF_HEADER: csrf}
    session = await client.get("/auth/session", headers=bearer)
    assert session.status_code == 200, session.text
    info = session.json()
    assert info["user"]["id"] == user_id and info["user"]["roles"] == ["owner"]
    assert info["user"]["mfa_enabled"] is True and info["user"]["mfa_required"] is True
    assert isinstance(info["permissions"], list) and info["permissions"]

    logout = await client.post("/auth/logout", headers=bearer)
    assert logout.status_code == 204
    after = await client.get("/auth/session", headers=bearer)
    assert after.status_code == 401


async def test_wrong_totp_is_rejected_and_no_session_minted(
    pg_dsn: str, client: httpx.AsyncClient
) -> None:
    _, secret = await _seed_owner_with_totp(pg_dsn, "e2e_badcode")
    r = await client.post("/auth/login", json={"identifier": "e2e_badcode", "password": _PASSWORD})
    wrong = _code(secret, _NOW + timedelta(minutes=10))
    v = await client.post(
        "/auth/mfa/verify",
        json={"mfa_token": r.json()["mfa_token"], "method": "totp", "code": wrong},
    )
    assert v.status_code == 401 and "set-cookie" not in v.headers


async def test_mfa_verify_after_a_disable_mints_nothing(
    pg_dsn: str, client: httpx.AsyncClient
) -> None:
    """#2911: a user disabled between the password step and the TOTP step gets the operation's
    401 and no session, and the refusal is audited (`auth.login_failed`, denied)."""
    await seed(pg_dsn, "e2e_keeper", _PASSWORD, _PEPPER)  # the owner floor keeps an active owner
    user_id, secret = await _seed_owner_with_totp(pg_dsn, "e2e_disabled")
    r = await client.post("/auth/login", json={"identifier": "e2e_disabled", "password": _PASSWORD})
    assert r.status_code == 200, r.text
    engine = create_async_engine(pg_dsn)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE users SET status = 'disabled' WHERE id = CAST(:id AS uuid)"),
                {"id": user_id},
            )
        body = {"mfa_token": r.json()["mfa_token"], "method": "totp", "code": _code(secret)}
        refused = await client.post("/auth/mfa/verify", json=body)
        assert refused.status_code == 401 and "set-cookie" not in refused.headers
        async with engine.connect() as conn:
            minted = await conn.execute(
                sa.text("SELECT count(*) FROM sessions WHERE user_id = CAST(:id AS uuid)"),
                {"id": user_id},
            )
            assert minted.scalar_one() == 0
    finally:
        await engine.dispose()
    ctx = client.app_context  # type: ignore[attr-defined]  # set by the client fixture
    await ctx.audit.writer.flush(10.0)
    rows = await _audit_rows(pg_dsn, user_id)
    assert ("auth.login_failed", "denied", "user_disabled") in {
        (x["action"], x["outcome"], x["reason"]) for x in rows
    }


async def test_skewed_totp_is_refused_generically_and_raises_a_system_event_after_the_hold(
    pg_dsn: str, client: httpx.AsyncClient
) -> None:
    """#2146: a valid code from an authenticator a few steps behind the server is refused with the
    generic answer; the real `system_events` table gets one `auth` skew row once the hold has
    elapsed, and none before."""
    _, secret = await _seed_owner_with_totp(pg_dsn, "e2e_skew")

    def code_at(steps: int) -> str:
        return _code(secret, _NOW + timedelta(seconds=30 * steps))

    # A step behind by 3 or more whose code is not also the code of a step inside +/-1.
    window = {code_at(k) for k in (-1, 0, 1)}
    skewed = next(c for c in map(code_at, range(-3, -11, -1)) if c not in window)
    r = await client.post("/auth/login", json={"identifier": "e2e_skew", "password": _PASSWORD})
    body = {"mfa_token": r.json()["mfa_token"], "method": "totp", "code": skewed}
    refused = await client.post("/auth/mfa/verify", json=body)
    assert refused.status_code == 401 and "set-cookie" not in refused.headers
    assert refused.json()["detail"] == "invalid or expired code"  # no skew-specific answer

    async def skew_rows() -> list[Any]:
        engine = create_async_engine(pg_dsn)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    sa.text(
                        "SELECT severity::text AS severity, details FROM system_events "
                        "WHERE component = 'auth' AND kind = 'totp_clock_skew'"
                    )
                )
                return [dict(row._mapping) for row in result]
        finally:
            await engine.dispose()

    assert await skew_rows() == []  # held: no row yet
    reporter = client.app_context.auth.mfa._skew_reporter  # type: ignore[attr-defined]  # test handle
    await reporter.publish_due(_NOW.timestamp() + SKEW_HOLD_S)
    (row,) = await skew_rows()
    assert row["severity"] == "warning" and "refused_at" in row["details"]


async def test_audit_rows_for_login_failure_totp_failure_success_and_logout(
    pg_dsn: str, client: httpx.AsyncClient
) -> None:
    """C-2.9: each step writes an append-only, hash-chained audit_log row
    through the real AuditWriter -> SqlAlchemyAuditRepository wiring."""
    user_id, secret = await _seed_owner_with_totp(pg_dsn, "e2e_audited")
    bad = await client.post("/auth/login", json={"identifier": "e2e_audited", "password": "nope"})
    assert bad.status_code == 401
    r = await client.post("/auth/login", json={"identifier": "e2e_audited", "password": _PASSWORD})
    wrong = _code(secret, _NOW + timedelta(minutes=10))
    totp_bad = await client.post(
        "/auth/mfa/verify",
        json={"mfa_token": r.json()["mfa_token"], "method": "totp", "code": wrong},
    )
    assert totp_bad.status_code == 401
    ok = await _login_and_verify(client, "e2e_audited", secret)
    token = ok.json()["tokens"]["access_token"]
    hdrs = {"Authorization": f"Bearer {token}", CSRF_HEADER: ok.cookies[CSRF_COOKIE]}
    assert (await client.post("/auth/logout", headers=hdrs)).status_code == 204
    await client.app_context.audit.writer.flush(10.0)  # type: ignore[attr-defined]

    failed = await _audit_rows(pg_dsn, "e2e***%")
    assert [(x["action"], x["outcome"]) for x in failed] == [("auth.login_failed", "failure")]
    assert failed[0]["actor_label"] == "e2e***(len=11)" and failed[0]["actor_ip"] == "127.0.0.1"
    logins = [x for x in await _audit_rows(pg_dsn, "e2e_audited") if x["action"] == "auth.login"]
    assert [x["outcome"] for x in logins] == ["success", "success"]

    by_user = await _audit_rows(pg_dsn, user_id)
    actions = [x["action"] for x in by_user]
    # seeder (users.create, roles.grant) -> mfa_verified -> session_created -> logout -> revoke
    assert actions[:2] == ["users.create", "roles.grant"]
    assert by_user[0]["after_state"] == {"mfa_required": True, "username": "e2e_audited"}
    assert by_user[0]["actor_label"] == "seed_fixture_user"
    assert {
        "auth.mfa_verified",
        "auth.session_created",
        "auth.logout",
        "auth.session_revoked",
    } <= set(actions)
    created = next(x for x in by_user if x["action"] == "auth.session_created")
    assert created["before_state"] is None and created["session_id"] is not None
    assert created["after_state"] == {"mfa_method": "totp", "mfa_satisfied": True}
    logout = next(x for x in by_user if x["action"] == "auth.logout")
    assert logout["actor_user_id"] == user_id and logout["reason"] == "logout"
    assert logout["outcome"] == "success" and logout["actor_ip"] == "127.0.0.1"
    assert logout["after_state"] == {"session_ids": [created["session_id"]], "session_count": 1}
    assert actions.index("auth.logout") < actions.index("auth.session_revoked")

    engine = create_async_engine(pg_dsn)
    try:
        async with engine.connect() as conn:
            mfa_failed = await conn.execute(
                sa.text(
                    "SELECT count(*) FROM audit_log WHERE action = 'auth.mfa_failed' "
                    "AND outcome = 'failure'"
                )
            )
            assert mfa_failed.scalar_one() >= 1
            with pytest.raises(sa.exc.DBAPIError):  # append-only (C-5.7 trigger)
                await conn.execute(sa.text("UPDATE audit_log SET reason = 'x'"))
    finally:
        await engine.dispose()


async def test_owner_floor_rejects_removing_the_last_owner_role(pg_dsn: str) -> None:
    """Owner floor (21-database-schema.md Sec.3.1.2) on the seeded data: the
    deferred trigger refuses a commit leaving zero active owners (SQLSTATE
    23514, which the PUT /users/{id}/roles route of #1654 maps to 409)."""
    await seed(pg_dsn, "e2e_floor", _PASSWORD, _PEPPER)
    engine = create_async_engine(pg_dsn)
    try:
        with pytest.raises(sa.exc.DBAPIError) as excinfo:
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        "DELETE FROM user_roles USING roles WHERE roles.id = user_roles.role_id "
                        "AND roles.name = 'owner'"
                    )
                )
        assert getattr(excinfo.value.orig, "sqlstate", None) == "23514"
        async with engine.connect() as conn:
            left = await conn.execute(
                sa.text(
                    "SELECT count(*) FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                    "WHERE r.name = 'owner'"
                )
            )
            assert left.scalar_one() >= 1
    finally:
        await engine.dispose()
