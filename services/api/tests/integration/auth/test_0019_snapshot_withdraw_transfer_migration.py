"""Integration: `0019_snapshot_withdraw_transfer` on real Postgres 16 (#2240, C-2.8 / SR-030a).

Round-trip 0019 -> parent -> 0019 on an empty and a seeded DB (C-5.5); the CHECK and the M13
predicate agree on every case of the shared corpus; a stored row granting a transfer right
blocks the upgrade, which then leaves 0017's constraint in place. Not run locally (no docker in
the authoring environment); CI integration lane.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from testcontainers.postgres import PostgresContainer

from candleviewer.accounts._permissions import reject_withdraw
from candleviewer.accounts.errors import WithdrawPermissionError
from tests.unit.accounts._permission_cases import ALLOWED, BASE, REFUSED, Case

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_REV = "0019_snapshot_withdraw_transfer"
_ACCT = "00000000-0000-4000-8000-0000000000a1"


def _parent() -> str:
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "candleviewer/migrations"))
    script = ScriptDirectory.from_config(cfg).get_revision(_REV)
    assert script is not None and isinstance(script.down_revision, str)
    return script.down_revision


_PREV = _parent()


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn},
        capture_output=True, text=True, check=False,
    )  # fmt: skip


def _conn(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True)


def _exec(dsn: str, sql: str) -> None:
    with _conn(dsn) as c:
        c.execute(sql)


def _one(dsn: str, sql: str) -> Any:
    with _conn(dsn) as c:
        row = c.execute(sql).fetchone()
    return row[0] if row else None


def _at(dsn: str, rev: str) -> None:
    """Move the module's shared database to `rev` and make sure the seed account exists."""
    has_version = _one(dsn, "SELECT to_regclass('public.alembic_version') IS NOT NULL")
    current = _one(dsn, "SELECT version_num FROM alembic_version") if has_version else None
    if current != rev:
        done = _alembic(dsn, "downgrade" if current == _REV else "upgrade", rev)
        assert done.returncode == 0, done.stderr
    with _conn(dsn) as c:
        c.execute(
            "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
            "VALUES (%s, 'bybit', 'demo', 'main', '42', 'seed') ON CONFLICT DO NOTHING",
            (_ACCT,),
        )


def _insert_key(dsn: str, permissions: dict[str, Any]) -> None:
    with _conn(dsn) as c:
        c.execute(
            "INSERT INTO api_keys (id, exchange_account_id, label, key_id_enc, key_id_last4, "
            "secret_enc, enc_nonce, dek_ref, permission_snapshot) "
            "VALUES (%s, %s, %s, %s, 'ABCD', %s, %s, 'ref', %s::jsonb)",
            (
                uuid4(), _ACCT, f"k-{uuid4()}", b"x", b"y", bytes(12),
                json.dumps({"uid": "42", "permissions": permissions}),
            ),
        )  # fmt: skip


def _shape(dsn: str) -> dict[str, str]:
    """`ak_snapshot*` constraints on api_keys: name -> definition."""
    with _conn(dsn) as c:
        rows = c.execute(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'api_keys'::regclass AND conname LIKE 'ak_snapshot%'"
        ).fetchall()
    return {str(name): str(definition) for name, definition in rows}


def _ids(cases: list[Case]) -> list[str]:
    return [c[0] for c in cases]


def test_round_trip_empty_then_seeded(pg_dsn: str) -> None:
    _at(pg_dsn, _REV)
    _exec(pg_dsn, "TRUNCATE api_keys CASCADE")
    assert list(_shape(pg_dsn)) == ["ak_snapshot_shape"]
    assert 'like_regex "withdraw|transfer" flag "i"' in _shape(pg_dsn)["ak_snapshot_shape"]
    _at(pg_dsn, _PREV)
    assert list(_shape(pg_dsn)) == ["ak_snapshot_shape"]
    assert "like_regex" not in _shape(pg_dsn)["ak_snapshot_shape"]
    _at(pg_dsn, _REV)
    _insert_key(pg_dsn, BASE)
    _at(pg_dsn, _PREV)  # the trade-only row re-validates under 0017's CHECK
    _at(pg_dsn, _REV)  # ... and again under 0019's
    assert _one(pg_dsn, "SELECT count(*) FROM api_keys") == 1


@pytest.mark.parametrize("permissions", [c[1] for c in ALLOWED], ids=_ids(ALLOWED))
def test_check_stores_what_the_m13_predicate_allows(
    pg_dsn: str, permissions: dict[str, Any]
) -> None:
    reject_withdraw(permissions)
    _at(pg_dsn, _REV)
    _insert_key(pg_dsn, permissions)


@pytest.mark.parametrize("permissions", [c[1] for c in REFUSED], ids=_ids(REFUSED))
def test_check_refuses_what_the_m13_predicate_refuses(
    pg_dsn: str, permissions: dict[str, Any]
) -> None:
    with pytest.raises(WithdrawPermissionError):
        reject_withdraw(permissions)
    _at(pg_dsn, _REV)
    with pytest.raises(psycopg.errors.CheckViolation, match="ak_snapshot_shape"):
        _insert_key(pg_dsn, permissions)


def test_stored_transfer_right_blocks_upgrade_atomically(pg_dsn: str) -> None:
    _at(pg_dsn, _PREV)
    _exec(pg_dsn, "TRUNCATE api_keys CASCADE")
    _insert_key(pg_dsn, {**BASE, "Wallet": ["AccountTransfer"]})  # 0017 accepts it: the bug
    refused = _alembic(pg_dsn, "upgrade", _REV)
    assert refused.returncode != 0
    assert "ak_snapshot_shape_0019" in refused.stderr
    assert _one(pg_dsn, "SELECT version_num FROM alembic_version") == _PREV
    assert list(_shape(pg_dsn)) == ["ak_snapshot_shape"]
    assert "like_regex" not in _shape(pg_dsn)["ak_snapshot_shape"]
    _exec(pg_dsn, "TRUNCATE api_keys CASCADE")
    _at(pg_dsn, _REV)
