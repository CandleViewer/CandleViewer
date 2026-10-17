"""Integration: the account fixture boot guard reads `api_keys` on real Postgres 16 (#2893 S8).

Fabricated rows only (placeholder ciphertext). Each test starts with every stored key revoked,
which the guard ignores, so order does not matter. Not run locally (no docker); CI integration lane.
"""

from __future__ import annotations

import itertools
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from pydantic import SecretStr
from testcontainers.postgres import PostgresContainer

from candleviewer.account_fixture_wiring import AccountFixtureRefused
from candleviewer.settings import Environment, FeedMode, Settings
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from cvdev.account_fixture.boot import PgStoredKeys, StoredKey, run
from tests._account_fixtures import PACK

pytestmark = [pytest.mark.integration, pytest.mark.integration_db]

_ROOT = Path(__file__).resolve().parents[3]
_SNAP = '{"uid": "1", "permissions": {"ContractTrade": ["Order"]}}'
_IDS = itertools.count(1)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        env = {**os.environ, "CV_PG_DSN": url.replace("postgresql+psycopg2", "postgresql+psycopg")}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=_ROOT, env=env, check=True
        )
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture
def db(pg_dsn: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(pg_dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        _revoke(c)
        yield c


@pytest.fixture
def settings(pg_dsn: str, tmp_path: Path) -> Settings:
    return Settings(
        environment=Environment.DEMO,
        feed=FeedMode.SYNTHETIC,
        account_fixture="compliant",
        account_fixture_dir=str(tmp_path / "state"),
        storage_backend="real",
        pg_dsn=SecretStr(pg_dsn),
    )


def _revoke(c: psycopg.Connection, key: UUID | None = None) -> None:
    c.execute(
        "UPDATE api_keys SET revoked_at = now(), status = 'revoked' "
        "WHERE revoked_at IS NULL AND (%s::uuid IS NULL OR id = %s::uuid)",
        (key, key),
    )


def _key(c: psycopg.Connection, env: str, last4: str, *, revoked: bool = False) -> UUID:
    """One key on a fresh main account of `env` (a unique uid and label per account)."""
    acct, key = UUID(int=next(_IDS)), UUID(int=next(_IDS))
    c.execute(
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', %s, 'main', %s, %s)",
        (acct, env, str(acct.int), f"boot-guard-{acct.int}"),
    )
    c.execute(
        "INSERT INTO api_keys (id, exchange_account_id, label, key_id_enc, key_id_last4, "
        "secret_enc, enc_nonce, dek_ref, permission_snapshot, revoked_at) "
        "VALUES (%s, %s, 'k', '\\x01', %s, '\\x02', %s, 'dek', %s, CASE WHEN %s THEN now() END)",
        (key, acct, last4, bytes(12), _SNAP, revoked),
    )
    return key


async def test_guard_reads_api_keys_on_postgres(
    db: psycopg.Connection, pg_dsn: str, settings: Settings
) -> None:
    _key(db, "demo", "0001")
    _key(db, "demo", "0002")
    _key(db, "live", "Ab12", revoked=True)
    _key(db, "demo", "Zq9X", revoked=True)
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        stored = await PgStoredKeys(relational).stored_keys()
    finally:
        await relational.dispose()

    unrevoked = sorted((k.env, k.key_id_last4) for k in stored if not k.revoked)
    assert unrevoked == [("demo", "0001"), ("demo", "0002")]
    assert {StoredKey("live", "Ab12", True), StoredKey("demo", "Zq9X", True)} <= set(stored)
    await run(settings, None, pack=PACK)  # fixture tails only, so boot passes


@pytest.mark.parametrize(
    ("env", "last4", "reason"),
    [("live", "0001", "1 outside demo (live 1)"), ("demo", "Zq9X", "1 on demo whose key id")],
    ids=["live-key", "non-fixture-demo-key"],
)
async def test_guard_refuses_a_stored_key_until_it_is_revoked(
    db: psycopg.Connection, settings: Settings, env: str, last4: str, reason: str
) -> None:
    _key(db, "demo", "0001")
    offending = _key(db, env, last4)

    with pytest.raises(AccountFixtureRefused, match=re.escape(reason)):
        await run(settings, None, pack=PACK)

    _revoke(db, offending)
    await run(settings, None, pack=PACK)
