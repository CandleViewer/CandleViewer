"""Integration: `0020_kek_versions` on real Postgres 16 (#835, C-5.5).

Round-trip 0020 -> 0019 -> 0020 on an empty and on a seeded DB, plus one violating row per
CHECK. Not run locally (no docker in the authoring environment); CI integration lane.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")


def _alembic(dsn: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn}, check=True,
    )  # fmt: skip


def _conn(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True)


def _has_table(dsn: str) -> bool:
    q = "SELECT to_regclass('public.kek_versions') IS NOT NULL"
    with _conn(dsn) as c:
        row = c.execute(q).fetchone()
        return bool(row and row[0])


def test_round_trip_empty_then_seeded(pg_dsn: str) -> None:
    _alembic(pg_dsn, "upgrade", "0020_kek_versions")
    assert _has_table(pg_dsn)
    _alembic(pg_dsn, "downgrade", "0019_snapshot_withdraw_transfer")
    assert not _has_table(pg_dsn)
    _alembic(pg_dsn, "upgrade", "0020_kek_versions")
    acct, key = "00000000-0000-4000-8000-0000000000a1", "00000000-0000-4000-8000-0000000000b1"
    with _conn(pg_dsn) as c:
        c.execute("INSERT INTO kek_versions (version, kcv) VALUES (1, %s)", (bytes(8),))
        c.execute(
            "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
            "VALUES (%s, 'bybit', 'demo', 'main', '42', 'seed')",
            (acct,),
        )
        c.execute(
            "INSERT INTO api_keys (id, exchange_account_id, label, key_id_enc, key_id_last4, "
            "secret_enc, enc_nonce, dek_ref, permission_snapshot) VALUES "
            "(%s, %s, 'k', %s, 'ABCD', %s, %s, 'v1:00', %s::jsonb)",
            (key, acct, b"x", b"y", bytes(12), '{"uid":"1","permissions":{}}'),
        )
    _alembic(pg_dsn, "downgrade", "0019_snapshot_withdraw_transfer")
    assert not _has_table(pg_dsn)
    with _conn(pg_dsn) as c:  # downgrade removed only kek_versions
        row = c.execute("SELECT count(*) FROM api_keys WHERE id = %s", (key,)).fetchone()
        assert row is not None and row[0] == 1
    _alembic(pg_dsn, "upgrade", "0020_kek_versions")
    assert _has_table(pg_dsn)


@pytest.mark.parametrize(
    ("version", "kcv", "constraint"),
    [(0, b"a" * 8, "kv_version_pos"), (7, bytes(7), "kv_kcv_len"), (8, bytes(9), "kv_kcv_len")],
)
def test_check_constraints(pg_dsn: str, version: int, kcv: bytes, constraint: str) -> None:
    _alembic(pg_dsn, "upgrade", "0020_kek_versions")
    with _conn(pg_dsn) as c, pytest.raises(psycopg.errors.CheckViolation) as ei:
        c.execute("INSERT INTO kek_versions (version, kcv) VALUES (%s, %s)", (version, kcv))
    assert constraint in str(ei.value)


def test_kcv_unique_constraint(pg_dsn: str) -> None:
    _alembic(pg_dsn, "upgrade", "0020_kek_versions")
    with _conn(pg_dsn) as c:
        c.execute("INSERT INTO kek_versions (version, kcv) VALUES (5, %s)", (b"z" * 8,))
        with pytest.raises(psycopg.errors.UniqueViolation) as ei:
            c.execute("INSERT INTO kek_versions (version, kcv) VALUES (6, %s)", (b"z" * 8,))
    assert "kv_kcv_unique" in str(ei.value)
