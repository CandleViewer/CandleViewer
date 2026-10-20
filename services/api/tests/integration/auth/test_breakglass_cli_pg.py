"""Integration: the break-glass CLI on real Postgres 16 (E09-S11 #2119 slice 5, SR-023).

- S1 `test_cli_end_to_end`: `python -m candleviewer.breakglass` in a child process on a real
  pseudo-terminal, through the whole composition (settings, logging, the KEK file, the host
  journal and run lock, the `pg_stat_activity` probe, the reset store, `audit_log`); the operator
  retypes the phrase. Nothing is faked: the child's I/O is the terminal, the files and Postgres.
- S4 (R2c) `test_api_probe_sees_other_session`: the probe sees another session of the database
  role, busy or idle, and never one of the CLI's own.
- S7 `test_db_down_refusal_folds_in` (chaos scenario 10): the records of a refusal journaled while
  Postgres is down land in `audit_log` exactly once at cv-api's next boots, chain verified.
- R6 `test_owner_reenrols_after_reset`: once reset, the Owner signs in with the password
  (enrolment-only), enrols TOTP and confirms it, and the next sign-in asks for that factor.

The KEK is a test value in a temporary directory, enrolled as a cv-api boot enrols one; the keys
are test-only bytes. Real Postgres via testcontainers (the CI integration lane; needs Docker).
"""

from __future__ import annotations

import asyncio
import base64
import functools
import os
import re
import select
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer import breakglass
from candleviewer.admin import breakglass as flow
from candleviewer.admin import breakglass_wiring
from candleviewer.admin.breakglass import BreakGlassExit as X
from candleviewer.app import create_app
from candleviewer.audit.journal import journal_dir
from candleviewer.audit.service import AuditService
from candleviewer.audit.wal import AuditWal
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.models import MfaChallengeRecord, MfaMethodRecord
from candleviewer.auth.totp import generate_code, generate_secret, time_step_for
from candleviewer.secrets import prove_kek_possession
from candleviewer.secrets._kek import LoadedKek
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.break_glass_cli_sqlalchemy import (
    SqlAlchemyBreakGlassDatabase,
)
from candleviewer.storage.repositories.mfa_sqlalchemy import SqlAlchemyMfaRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from scripts.seed_fixture_user import seed

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime.now(UTC).replace(microsecond=0)  # rows are DB-stamped: track real time
_RC_KEY = bytes.fromhex("22" * 32)  # test-only recovery-code HMAC key, not a credential
_TOTP_KEY = bytes.fromhex("11" * 32)  # test-only TOTP sealing key, not a credential
_PEPPER = "it-pepper"
_PW = "correct horse battery"  # throwaway fixture sign-in value, not a credential
_DIGEST = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA"  # placeholder digest, not a credential
_ACTIONS = ("auth.break_glass_attempt", "auth.break_glass_refused", "auth.break_glass_reset")
_PHRASE = re.compile(rb"To confirm, type: (reset [^\r\n]+)\r?\n")
#: A user, its Owner role, a confirmed and a pending TOTP method, and two live sessions.
_SEED = sa.text(
    "WITH u AS (INSERT INTO users (id, email, username, password_hash, status) VALUES "
    "(CAST(:u AS uuid), :email, :name, :digest, 'active') RETURNING id), "
    "r AS (INSERT INTO user_roles (user_id, role_id) SELECT u.id, roles.id FROM u, roles "
    "WHERE roles.name = 'owner'), "
    "m AS (INSERT INTO mfa_methods (id, user_id, kind, secret_enc, confirmed_at) "
    "SELECT gen_random_uuid(), u.id, CAST('totp' AS mfa_method_kind), "
    "convert_to('ciphertext', 'UTF8'), v.c FROM u, (VALUES (now()), (NULL)) AS v(c)) "
    "INSERT INTO sessions (id, user_id, refresh_token_hash, expires_at) "
    "SELECT gen_random_uuid(), u.id, encode(sha256(convert_to(CAST(gen_random_uuid() AS text), "
    "'UTF8')), 'hex'), now() + interval '1 hour' FROM u, generate_series(1, 2)"
)
_STATE = sa.text(
    "SELECT (SELECT count(*) FROM mfa_methods WHERE user_id = CAST(:u AS uuid) "
    "AND revoked_at IS NULL), (SELECT count(*) FROM sessions WHERE user_id = CAST(:u AS uuid) "
    "AND revoked_at IS NULL), (SELECT count(*) FROM system_events WHERE kind = "
    "'break_glass_used' AND resolved_at IS NULL AND details->>'target_user_id' = :t)"
)
_HASHES = sa.text("SELECT refresh_token_hash FROM sessions WHERE user_id = CAST(:u AS uuid)")
#: The records of the run that reset `:u`: the attempt carries no target yet, so by run id.
_RECORDS = sa.text(
    "SELECT action, CAST(outcome AS text), reason, actor_label, CAST(severity AS text) "
    "FROM audit_log WHERE request_id = (SELECT request_id FROM audit_log WHERE object_id = :u "
    "AND action = 'auth.break_glass_reset') ORDER BY id"
)
_BY_IDS = sa.text(
    "SELECT action, CAST(outcome AS text), reason FROM audit_log "
    "WHERE CAST(record_id AS text) = ANY(:ids) ORDER BY id"
)
_ENROL = sa.text("INSERT INTO kek_versions (env, version, kcv) VALUES ('demo', 1, :kcv)")
_STRAYS = sa.text(
    "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE usename = session_user "
    "AND backend_type = 'client backend' AND pid <> pg_backend_pid()"
)
_NAMED = sa.text(
    "SELECT application_name FROM pg_stat_activity WHERE application_name LIKE "
    "'candleviewer:breakglass:%' AND usename = session_user"
)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={**os.environ, "CV_PG_DSN": dsn.replace("+asyncpg", "+psycopg")},
            check=True,
        )
        yield dsn


@pytest.fixture(scope="module")
def kek(pg_dsn: str, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A test KEK file (`0400`) whose check value a cv-api boot enrolled for `demo`, version 1."""
    path = tmp_path_factory.mktemp("kek").resolve() / "kek"
    raw = os.urandom(32)
    path.write_bytes(raw)
    path.chmod(0o400)
    loaded = LoadedKek(bytearray(raw), 1, env_name="demo")
    kcv = loaded.kcv()
    loaded.close()
    asyncio.run(_execute(pg_dsn, _ENROL, kcv=kcv))
    return path


@pytest.fixture
def alone(pg_dsn: str) -> None:
    """No other session of the role, as R2c needs: a test that started cv-api's modules outside
    their lifespan may have left pooled sessions behind, whatever the order tests run in."""
    asyncio.run(_execute(pg_dsn, _STRAYS))


async def _execute(dsn: str, statement: sa.TextClause, **params: Any) -> None:
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            await conn.execute(statement, params)
    finally:
        await engine.dispose()


async def _fetch(dsn: str, statement: sa.TextClause, **params: Any) -> list[tuple[Any, ...]]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            return [tuple(row) for row in await conn.execute(statement, params)]
    finally:
        await engine.dispose()


async def _owner(dsn: str, name: str) -> str:
    """The id of a seeded Owner `name` with MFA methods and live sessions."""
    uid = str(uuid.uuid4())
    await _execute(dsn, _SEED, u=uid, email=f"{name}@example.invalid", name=name, digest=_DIGEST)
    return uid


def _settings(kek: Path, wal: Path, dsn: str, **extra: Any) -> Settings:
    return Settings(
        environment=Environment.DEMO,
        pg_dsn=SecretStr(dsn),
        kek_source="file",
        kek_handle=str(kek),
        audit_wal_path=str(wal),
        **extra,
    )


def _dead_dsn() -> str:
    """A Postgres address nothing listens on: every connect is refused at once."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"postgresql+asyncpg://cv:unused@127.0.0.1:{port}/candleviewer"


class _Operator:
    """The operator in-process: retypes the phrase shown; no recovery code outside live."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def is_interactive(self) -> bool:
        return True

    def write(self, line: str) -> None:
        self.lines.append(line)

    async def ask(self, prompt: str) -> str:
        return self.lines[-1].removeprefix("To confirm, type: ")

    async def ask_secret(self, prompt: str) -> str:
        raise AssertionError("no recovery code is asked for outside live")


async def _cli(settings: Settings, owner: str) -> tuple[X, _Operator]:
    """One CLI run in-process over its real Postgres side (SR-009 hardening stays out of the
    pytest process; the child process of `test_cli_end_to_end` runs it for real)."""
    operator = _Operator()
    proof = functools.partial(prove_kek_possession, harden=lambda: True)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(breakglass_wiring, "prove_kek_possession", proof)
        status = await breakglass.run(
            settings, owner, live_flag=False, recovery_code_key=_RC_KEY, terminal=operator
        )
    return status, operator


async def _boot(settings: Settings) -> bool:
    """One cv-api audit-module boot and stop (it folds in the journal); the chain verdict."""
    relational = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value())
    try:
        service = AuditService(SqlAlchemyAuditRepository(relational))
        ctx: Any = SimpleNamespace(settings=settings)  # all the audit module reads at start
        await service.start(ctx)
        await service.writer.flush(60)
        verdict = (await service.query.verify()).verified
        await service.stop(5)
        return verdict
    finally:
        await relational.dispose()


def _child_env(dsn: str, kek: Path, wal: Path) -> dict[str, str]:
    """The CLI's settings, as `docker compose run` hands cv-api's own to it; no other `CV_*`."""
    inherited = {k: v for k, v in os.environ.items() if not k.startswith("CV_")}
    return inherited | {
        "CV_ENVIRONMENT": "demo",
        "CV_PG_DSN": dsn,
        "CV_KEK_SOURCE": "file",
        "CV_KEK_HANDLE": str(kek),
        "CV_AUDIT_WAL_PATH": str(wal),
        "CV_AUTH_RECOVERY_HMAC_KEY_HEX": _RC_KEY.hex(),
    }


def _on_a_terminal(env: dict[str, str], cwd: Path) -> tuple[int, str]:
    """`python -m candleviewer.breakglass --owner bg_e2e` on a pseudo-terminal whose operator
    retypes the phrase it shows; its exit status and everything it wrote to the terminal. The
    argv is literal (ruff S603): the settings travel in the environment, as in compose."""
    master, slave = os.openpty()
    child = subprocess.Popen(
        [sys.executable, "-m", "candleviewer.breakglass", "--owner", "bg_e2e"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        cwd=cwd,
    )
    os.close(slave)
    shown, answered, deadline = bytearray(), False, time.monotonic() + 120
    try:
        while True:
            ready, _, _ = select.select([master], [], [], max(deadline - time.monotonic(), 0))
            if not ready:
                raise AssertionError(f"the CLI did not end: {shown.decode(errors='replace')}")
            try:
                chunk = os.read(master, 4096)
            except OSError:  # EIO: the child has closed the terminal
                break
            if not chunk:
                break
            shown += chunk
            typed = _PHRASE.search(shown)
            if typed is not None and not answered:
                os.write(master, typed.group(1) + b"\n")
                answered = True
        return child.wait(timeout=60), shown.decode(errors="replace")
    finally:
        if child.poll() is None:
            child.kill()
        os.close(master)


@pytest.mark.usefixtures("alone")
def test_cli_end_to_end(pg_dsn: str, kek: Path, tmp_path: Path) -> None:
    uid = asyncio.run(_owner(pg_dsn, "bg_e2e"))
    hashes = [row[0] for row in asyncio.run(_fetch(pg_dsn, _HASHES, u=uid))]
    wal = tmp_path / "audit" / "audit.wal"
    status, shown = _on_a_terminal(_child_env(pg_dsn, kek, wal), tmp_path)
    assert status == 0, shown
    assert "reset done for bg_e2e on demo: 2 MFA methods and 2 sessions revoked" in shown
    assert "Audit: every record reached audit_log." in shown
    assert asyncio.run(_fetch(pg_dsn, _STATE, u=uid, t=uid)) == [(0, 0, 1)]  # one event
    actor = ("system:breakglass", "critical")
    assert asyncio.run(_fetch(pg_dsn, _RECORDS, u=uid)) == [
        ("auth.break_glass_attempt", "success", None, *actor),
        ("auth.break_glass_reset", "success", None, *actor),
    ]
    dsn = urlparse(pg_dsn)
    secret = [kek.read_bytes().hex(), _RC_KEY.hex(), f"{dsn.username}:{dsn.password}@", *hashes]
    assert [value for value in secret if value in shown] == []
    assert (journal_dir(str(wal)) / "journal.wal").read_bytes() == b""
    assert asyncio.run(_boot(_settings(kek, wal, pg_dsn)))  # cv-api boots after it; chain holds


@pytest.mark.usefixtures("alone")
async def test_api_probe_sees_other_session(pg_dsn: str) -> None:
    cli = SqlAlchemyBreakGlassDatabase(pg_dsn)
    api = SqlAlchemyRelationalRepository(pg_dsn)  # as cv-api's pools: named per transaction only
    try:
        # Three of the CLI's own sessions at once, then idle in its pool: never "another".
        assert await asyncio.gather(*(cli.others_connected() for _ in range(3))) == [False] * 3
        named = {row[0] for row in await _fetch(pg_dsn, _NAMED)}
        assert named == {cli.application_name}  # idle sessions too carry the run's name
        async with api.unit_of_work() as uow:
            await uow.session.execute(sa.text("SELECT 1"))
            assert await cli.others_connected()  # a busy session of cv-api
        assert await cli.others_connected()  # the same session, idle in cv-api's pool
        await api.dispose()
        assert not await cli.others_connected()
        second = SqlAlchemyBreakGlassDatabase(pg_dsn)  # another run is another session too
        try:
            assert await second.reachable() and await cli.others_connected()
        finally:
            await second.dispose()
        assert not await cli.others_connected()
    finally:
        await api.dispose()
        await cli.dispose()


async def test_db_down_refusal_folds_in(
    pg_dsn: str, kek: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(flow, "CLOSE_GRACE_S", 0.5)  # no flush can succeed: Postgres is down
    wal = tmp_path / "audit" / "audit.wal"
    status, operator = await _cli(_settings(kek, wal, _dead_dsn()), "anyone")
    assert status is X.KEK_UNPROVEN  # the proof reads `kek_versions`, which is down too
    waiting = "Audit: records waiting in the host journal: 2; cv-api folds them in."
    assert operator.lines[-1] == waiting
    journal = journal_dir(str(wal)) / "journal.wal"
    ids = [str(record["record_id"]) for _end, record in AuditWal(journal).replay()]
    up = _settings(kek, wal, pg_dsn)
    assert await _boot(up) and await _boot(up)  # the chain verifies after each boot
    assert await _fetch(pg_dsn, _BY_IDS, ids=ids) == [  # each record exactly once
        ("auth.break_glass_attempt", "success", None),
        ("auth.break_glass_refused", "denied", "kek_unproven"),
    ]


@pytest.fixture
def lane_key(tmp_path_factory: pytest.TempPathFactory) -> str:
    """ADR-0037: the audit lane key file, outside the audit directory."""
    key = tmp_path_factory.mktemp("lane-key").resolve() / "key"
    key.write_text(os.urandom(32).hex(), encoding="ascii")
    key.chmod(0o400)
    return str(key)


async def _enrol_totp(dsn: str, user_id: str) -> None:
    """The factor the Owner then lost, confirmed the way production confirms one (#2295)."""
    rel = SqlAlchemyRelationalRepository(dsn)
    mfa = SqlAlchemyMfaRepository(
        rel,
        lambda **f: MfaMethodRecord.model_validate(f),
        lambda **f: MfaChallengeRecord.model_validate(f),
    )
    try:
        sealer = TotpEncryptor(_TOTP_KEY)
        sealed = sealer.encrypt(generate_secret())
        method = await mfa.create_pending_method(
            user_id, secret_enc=sealed, secret_key_ref=sealer.key_ref, label="lost"
        )
        step = time_step_for(_NOW.timestamp()) - 20
        done = await mfa.complete_enrollment(
            user_id, method_id=str(method.id), time_step=step, now=_NOW, code_hashes=()
        )
        assert done is not None
    finally:
        await rel.dispose()


@asynccontextmanager
async def _cv_api(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """cv-api's auth and audit modules over the same Postgres and audit directory."""
    app = create_app(settings, auth_clock=lambda: _NOW)
    ctx = app.state.app_context
    await ctx.audit.start(ctx)
    await ctx.auth.start(ctx)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
            yield c
    finally:
        await ctx.auth.stop(1.0)
        await ctx.audit.stop(1.0)


@pytest.mark.usefixtures("alone")
async def test_owner_reenrols_after_reset(
    pg_dsn: str, kek: Path, tmp_path: Path, lane_key: str
) -> None:
    uid = await seed(pg_dsn, "bg_reenrol", _PW, _PEPPER)
    assert uid is not None
    await _enrol_totp(pg_dsn, uid)
    wal = tmp_path / "audit" / "audit.wal"
    assert (await _cli(_settings(kek, wal, pg_dsn), "bg_reenrol"))[0] is X.RESET
    keys: dict[str, Any] = {"auth_totp_key_hex": SecretStr(_TOTP_KEY.hex())}
    keys |= {"auth_pepper": SecretStr(_PEPPER)}
    keys |= {"auth_recovery_hmac_key_hex": SecretStr(_RC_KEY.hex())}
    keys |= {"auth_csrf_key_hex": SecretStr("33" * 32), "CV_AUDIT_LANE_KEY_FILE": lane_key}
    sign_in = {"identifier": "bg_reenrol", "password": _PW}
    async with _cv_api(_settings(kek, wal, pg_dsn, storage_backend="real", **keys)) as client:
        login = await client.post("/auth/login", json=sign_in)
        assert login.status_code == 200, login.text
        assert login.json()["user"]["mfa_enabled"] is False  # enrolment-only (#2295)
        token = login.json()["tokens"]["access_token"]
        auth = {"Authorization": f"Bearer {token}", CSRF_HEADER: login.cookies[CSRF_COOKIE]}
        body = {"method": "totp", "label": "after break-glass"}
        enrol = await client.post("/auth/mfa/enroll", headers=auth, json=body)
        assert enrol.status_code == 201, enrol.text
        b32 = parse_qs(urlparse(enrol.json()["otpauth_uri"]).query)["secret"][0]
        code = generate_code(base64.b32decode(b32 + "=" * (-len(b32) % 8)), time_step_for(
            _NOW.timestamp()))  # fmt: skip
        confirm = {"method_id": enrol.json()["method_id"], "code": code}
        confirmed = await client.post("/auth/mfa/enroll/confirm", headers=auth, json=confirm)
        assert confirmed.status_code == 200, confirmed.text
        again = await client.post("/auth/login", json=sign_in)
        assert (again.json()["status"], again.json()["methods"]) == ("mfa_required", ["totp"])
