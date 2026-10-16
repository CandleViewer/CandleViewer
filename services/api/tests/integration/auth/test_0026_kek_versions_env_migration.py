"""Integration: `0026_kek_versions_env` on real Postgres 16 (#2338, C-5.2, C-5.5).

Round trip on an empty and on a seeded database, the upgrade guard against usable `api_keys`
rows, the downgrade refusal when two lineages share a version, and the per-environment key.
Each test resets the shared database first, so the order does not matter. CI integration lane.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_REV, _PREV = "0026_kek_versions_env", "0025_settings"
_ACCT = "00000000-0000-4000-8000-0000000000a1"
_ROW = "INSERT INTO kek_versions (env, version, kcv) VALUES (%s, %s, %s)"


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn},
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip


def _step(dsn: str, *args: str) -> None:
    done = _alembic(dsn, *args)
    assert done.returncode == 0, done.stderr


def _sql(dsn: str, query: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    with psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True) as c:
        cur = c.execute(query, params)
        return cur.fetchall() if cur.description else []


def _reset(dsn: str, rev: str) -> None:
    """Empty `kek_versions` and `api_keys`, then move the shared database to `rev`."""
    if _sql(dsn, "SELECT to_regclass('public.kek_versions') IS NOT NULL")[0][0]:
        _sql(dsn, "DELETE FROM kek_versions")
        _sql(dsn, "DELETE FROM api_keys")
        current = _sql(dsn, "SELECT version_num FROM alembic_version")[0][0]
        if current != rev:
            _step(dsn, "downgrade" if current == _REV else "upgrade", rev)
    else:
        _step(dsn, "upgrade", rev)


def _version(dsn: str) -> object:
    return _sql(dsn, "SELECT version_num FROM alembic_version")[0][0]


def _env_column(dsn: str) -> list[tuple[object, ...]]:
    return _sql(
        dsn,
        "SELECT is_nullable, column_default FROM information_schema.columns "
        "WHERE table_name = 'kek_versions' AND column_name = 'env'",
    )


def _lineages(dsn: str) -> list[tuple[object, ...]]:
    return _sql(dsn, "SELECT env::text, version FROM kek_versions ORDER BY 1, 2")


def _key(dsn: str, *, revoked: bool) -> None:
    _sql(
        dsn,
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'demo', 'main', '42', 'seed') ON CONFLICT DO NOTHING",
        (_ACCT,),
    )
    _sql(
        dsn,
        "INSERT INTO api_keys (id, exchange_account_id, label, key_id_enc, key_id_last4, "
        "secret_enc, enc_nonce, dek_ref, permission_snapshot, status, revoked_at) VALUES "
        "(%s, %s, %s, %s, 'ABCD', %s, %s, 'v1:00', %s::jsonb, %s::key_status, "
        "CASE WHEN %s THEN now() END)",
        (uuid4(), _ACCT, f"k-{uuid4()}", b"x", b"y", bytes(12), '{"uid":"1","permissions":{}}',
         "revoked" if revoked else "active", revoked),
    )  # fmt: skip


def test_round_trip_on_an_empty_database(pg_dsn: str) -> None:
    _reset(pg_dsn, _PREV)
    _step(pg_dsn, "upgrade", _REV)
    _step(pg_dsn, "downgrade", _PREV)
    assert _env_column(pg_dsn) == []
    _step(pg_dsn, "upgrade", _REV)
    assert _env_column(pg_dsn) == [("NO", None)]


def test_round_trip_on_a_seeded_database_keeps_old_rows_in_demo(pg_dsn: str) -> None:
    _reset(pg_dsn, _PREV)
    _sql(pg_dsn, "INSERT INTO kek_versions (version, kcv) VALUES (1, %s)", (b"k" * 8,))
    _key(pg_dsn, revoked=True)
    _step(pg_dsn, "upgrade", _REV)
    assert _lineages(pg_dsn) == [("demo", 1)] and _env_column(pg_dsn) == [("NO", None)]
    _step(pg_dsn, "downgrade", _PREV)
    assert _sql(pg_dsn, "SELECT version, kcv FROM kek_versions") == [(1, b"k" * 8)]
    _step(pg_dsn, "upgrade", _REV)
    assert _lineages(pg_dsn) == [("demo", 1)] and _env_column(pg_dsn) == [("NO", None)]


def test_lineages_keyed_by_environment_while_kcv_stays_globally_unique(pg_dsn: str) -> None:
    _reset(pg_dsn, _REV)
    _sql(pg_dsn, _ROW, ("live", 1, b"L" * 8))
    _sql(pg_dsn, _ROW, ("demo", 1, b"D" * 8))
    with pytest.raises(psycopg.errors.UniqueViolation, match="kv_kcv_unique"):
        _sql(pg_dsn, _ROW, ("testnet", 1, b"L" * 8))
    with pytest.raises(psycopg.errors.UniqueViolation, match="kek_versions_pkey"):
        _sql(pg_dsn, _ROW, ("live", 1, b"X" * 8))
    with pytest.raises(psycopg.errors.NotNullViolation):  # no default: every insert names env
        _sql(pg_dsn, "INSERT INTO kek_versions (version, kcv) VALUES (2, %s)", (b"N" * 8,))
    assert _lineages(pg_dsn) == [("demo", 1), ("live", 1)]


def test_upgrade_refuses_while_a_usable_key_exists_and_changes_nothing(pg_dsn: str) -> None:
    _reset(pg_dsn, _PREV)
    _key(pg_dsn, revoked=False)
    refused = _alembic(pg_dsn, "upgrade", _REV)
    assert refused.returncode != 0
    assert 'kek-custody.md, "Upgrading to per-environment KEK lineages"' in refused.stderr
    assert _version(pg_dsn) == _PREV and _env_column(pg_dsn) == []


def test_downgrade_refuses_to_merge_two_lineages_and_changes_nothing(pg_dsn: str) -> None:
    _reset(pg_dsn, _REV)
    _sql(pg_dsn, _ROW, ("live", 1, b"L" * 8))
    _sql(pg_dsn, _ROW, ("demo", 1, b"D" * 8))
    refused = _alembic(pg_dsn, "downgrade", _PREV)
    assert refused.returncode != 0 and "downgrade refused" in refused.stderr
    assert _version(pg_dsn) == _REV and _lineages(pg_dsn) == [("demo", 1), ("live", 1)]
