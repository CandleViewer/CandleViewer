"""Integration (#2893 closure): the seed command on real Postgres 16, and its Owner signing in.

The real shared seeder (argon2id and all) and the real database probe run against one migrated
database per test, cloned from a template; the Owner then signs in through the real app
(`create_app`, `storage_backend=real`, the fixture armed as on the stack): password, TOTP code made
from the seeded secret file, session, `GET /me`. The S8 boot guard, which the stack's api runs
before any module starts, then passes on the seeded database. Fabricated throwaway values only.
Every password and secret is read back from the run directory and never put in an assertion
message.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from itertools import count
from pathlib import Path

import httpx
import psycopg
import pytest
import sqlalchemy as sa
import structlog
from psycopg import sql
from pydantic import SecretStr
from testcontainers.postgres import PostgresContainer

from candleviewer.app import create_app
from candleviewer.auth.totp import base32_to_secret, generate_code, time_step_for
from candleviewer.settings import Environment, FeedMode, Settings
from cvdev.account_fixture import boot, seed
from tests._account_fixtures import PACK

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
# Track real time: rows carry DB-stamped `created_at` (now()), so a frozen date is a time bomb.
_NOW = datetime.now(UTC).replace(microsecond=0)
_TEMPLATE = "template_test"
_NAMES = count(1)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in os.environ if n.upper().startswith("CV_")]:
        monkeypatch.delenv(name)


def _url(server: str, database: str, driver: str) -> str:
    return server.rsplit("/", 1)[0].replace("postgresql+psycopg2", driver) + "/" + database


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    """A Postgres 16 server holding one migrated database, `template_test`, to clone."""
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        with psycopg.connect(_url(url, "test", "postgresql"), autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(_TEMPLATE)))
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={**os.environ, "CV_PG_DSN": _url(url, _TEMPLATE, "postgresql+psycopg")},
            check=True,
        )
        yield url


@pytest.fixture
def database(server: str) -> Callable[[str], str]:
    """A fresh migrated database called `seed_<n>_<suffix>`; its asyncpg DSN."""

    def make(suffix: str) -> str:
        name = f"seed_{next(_NAMES)}_{suffix}"
        with psycopg.connect(_url(server, "test", "postgresql"), autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(name), sql.Identifier(_TEMPLATE)
                )
            )
        return _url(server, name, "postgresql+asyncpg")

    return make


@pytest.fixture
def lane_key(tmp_path_factory: pytest.TempPathFactory) -> str:
    """ADR-0037: the audit lane key file, outside the audit directory."""
    key = tmp_path_factory.mktemp("lane-key").resolve() / "key"
    key.write_text(os.urandom(32).hex(), encoding="ascii")
    key.chmod(0o400)
    return str(key)


def _settings(tmp_path: Path, dsn: str, lane_key: str) -> Settings:
    """The stack's armed settings: demo, the synthetic feed, the fixture on, the real backend."""
    return Settings(
        environment=Environment.DEMO,
        feed=FeedMode.SYNTHETIC,
        account_fixture="compliant",
        account_fixture_dir=str(tmp_path / "state"),
        storage_backend="real",
        pg_dsn=SecretStr(dsn),
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
        auth_pepper=SecretStr("it-pepper"),
        audit_wal_path=str(tmp_path / "audit.wal"),
        CV_AUDIT_LANE_KEY_FILE=lane_key,
    )


async def _seed(settings: Settings, run_dir: Path) -> int:
    """`main` with the real seeder and probe; its own event loop runs in a worker thread."""
    return await asyncio.to_thread(
        seed.main, ["users", "--run-dir", str(run_dir)], settings=settings
    )


def _run_dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir(mode=0o700)
    return path


@pytest.fixture
async def app_client(
    database: Callable[[str], str], tmp_path: Path, lane_key: str
) -> AsyncIterator[tuple[httpx.AsyncClient, Path]]:
    """The seeded database behind the real app, with only its audit and auth modules started."""
    settings = _settings(tmp_path, database("signin_test"), lane_key)
    run_dir = _run_dir(tmp_path, "run")
    assert await _seed(settings, run_dir) == 0
    app = create_app(settings, auth_clock=lambda: _NOW)
    assert app.state.account_fixture is not None  # the fixture is armed, as on the stack
    ctx = app.state.app_context
    await ctx.audit.start(ctx)
    await ctx.auth.start(ctx)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
            yield client, run_dir
    finally:
        await ctx.audit.writer.flush(10.0)
        await ctx.auth.stop(1.0)
        await ctx.audit.stop(1.0)


async def test_the_seeded_owner_signs_in_on_the_real_backend(
    app_client: tuple[httpx.AsyncClient, Path],
) -> None:
    client, run_dir = app_client
    user = "qa-owner-1"
    password = (run_dir / f"pw-{user}").read_text(encoding="ascii")
    secret = base32_to_secret((run_dir / f"totp-{user}").read_text(encoding="ascii"))

    login = await client.post("/auth/login", json={"identifier": user, "password": password})
    assert login.status_code == 200, login.text
    assert login.json()["status"] == "mfa_required" and login.json()["methods"] == ["totp"]
    code = generate_code(secret, time_step_for(_NOW.timestamp()))
    verified = await client.post(
        "/auth/mfa/verify",
        json={"mfa_token": login.json()["mfa_token"], "method": "totp", "code": code},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "authenticated"
    bearer = {"Authorization": f"Bearer {verified.json()['tokens']['access_token']}"}

    me = await client.get("/me", headers=bearer)

    assert me.status_code == 200, me.text
    assert (me.json()["user"]["username"], me.json()["role"]) == (user, "owner")


async def test_the_s8_boot_guard_passes_on_the_seeded_database(
    database: Callable[[str], str], tmp_path: Path, lane_key: str
) -> None:
    """The guard the stack's api runs before any module starts reads the seeded database's
    unrevoked keys (the seed makes users and never a key) and passes, with its warning."""
    settings = _settings(tmp_path, database("guard_test"), lane_key)
    assert await _seed(settings, _run_dir(tmp_path, "run")) == 0

    with structlog.testing.capture_logs() as events:
        passed = await boot.run(settings, pack=PACK)

    assert passed == boot.Passed(settings)
    names = [event["event"] for event in events]
    assert names == ["exchange.account_fixture_boot_guard_passed"]
    assert (events[0]["fixture_keys"], events[0]["storage_backend"]) == (0, "real")


async def test_the_probe_runs_in_a_read_only_transaction_on_postgres(
    database: Callable[[str], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write issued where the probe reads is refused by Postgres itself."""
    monkeypatch.setattr(seed, "_FACTS", sa.text("UPDATE users SET status = status"))

    with pytest.raises(Exception, match="read-only transaction"):
        await seed.probe_database(database("probe_test"))


async def test_seed_refuses_a_populated_database_on_postgres(
    database: Callable[[str], str],
    tmp_path: Path,
    lane_key: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _settings(tmp_path, database("populated_test"), lane_key)
    assert await _seed(settings, _run_dir(tmp_path, "first")) == 0
    capsys.readouterr()
    second = _run_dir(tmp_path, "second")

    assert await _seed(settings, second) == 2

    assert capsys.readouterr().err == f"account-fixture: refused: {seed.NOT_EMPTY}\n"
    assert not list(second.iterdir())


async def test_seed_refuses_a_database_that_is_not_a_throwaway_and_writes_nothing(
    database: Callable[[str], str],
    tmp_path: Path,
    lane_key: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dsn = database("kept")
    run_dir = _run_dir(tmp_path, "run")

    assert await _seed(_settings(tmp_path, dsn, lane_key), run_dir) == 2

    assert capsys.readouterr().err == f"account-fixture: refused: {seed.NOT_THROWAWAY}\n"
    assert not list(run_dir.iterdir())
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql")) as check:
        assert check.execute("SELECT count(*) FROM users").fetchone() == (0,)
