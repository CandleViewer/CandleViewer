"""Integration: `0019_snapshot_withdraw_transfer` on real Postgres 16 (#2240, C-2.8 / SR-030a).

Round-trip 0019 -> parent -> 0019 on an empty and a seeded DB (C-5.5); the CHECK and the M13
predicate agree on every case of the shared corpus; `ak_no_transfer` pins `can_transfer`; a stored
row granting a transfer right, or claiming `can_transfer`, blocks the upgrade, which then leaves
the parent's constraints in place; a held lock makes the upgrade give up after `lock_timeout`
instead of queueing. CI integration lane (testcontainers).
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
from tests.unit.accounts._permission_cases import (
    ALLOWED,
    BASE,
    EXACT_WITHDRAW,
    KNOWN_GAPS,
    REFUSED,
    Case,
)

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
    """Bounded, so a lost `lock_timeout` fails the test instead of deadlocking it."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn},
        capture_output=True, text=True, check=False, timeout=120,
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


def _insert_key(dsn: str, permissions: dict[str, Any], *, can_transfer: bool = False) -> None:
    with _conn(dsn) as c:
        c.execute(
            "INSERT INTO api_keys (id, exchange_account_id, label, key_id_enc, key_id_last4, "
            "secret_enc, enc_nonce, dek_ref, permission_snapshot, can_transfer) "
            "VALUES (%s, %s, %s, %s, 'ABCD', %s, %s, 'ref', %s::jsonb, %s)",
            (
                uuid4(), _ACCT, f"k-{uuid4()}", b"x", b"y", bytes(12),
                json.dumps({"uid": "42", "permissions": permissions}), can_transfer,
            ),
        )  # fmt: skip


def _shape(dsn: str) -> dict[str, str]:
    """`ak_snapshot*` and `ak_no_transfer` constraints on api_keys: name -> definition."""
    with _conn(dsn) as c:
        rows = c.execute(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'api_keys'::regclass "
            "AND (conname LIKE 'ak_snapshot%' OR conname = 'ak_no_transfer') ORDER BY conname"
        ).fetchall()
    return {str(name): str(definition) for name, definition in rows}


def _ids(cases: list[Case]) -> list[str]:
    return [c[0] for c in cases]


def test_round_trip_empty_then_seeded(pg_dsn: str) -> None:
    _at(pg_dsn, _REV)
    _exec(pg_dsn, "TRUNCATE api_keys CASCADE")
    assert list(_shape(pg_dsn)) == ["ak_no_transfer", "ak_snapshot_shape"]
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


@pytest.mark.parametrize(
    "permissions", [c[1] for c in EXACT_WITHDRAW], ids=[c[0] for c in EXACT_WITHDRAW]
)
def test_check_raises_22023_on_a_non_list_legacy_withdraw_group(
    pg_dsn: str, permissions: dict[str, Any]
) -> None:
    _at(pg_dsn, _REV)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="cannot get array length"):
        _insert_key(pg_dsn, permissions)


@pytest.mark.parametrize("permissions", [c[1] for c in KNOWN_GAPS], ids=_ids(KNOWN_GAPS))
def test_check_shares_the_deny_list_gaps_of_the_m13_predicate(
    pg_dsn: str, permissions: dict[str, Any]
) -> None:
    reject_withdraw(permissions)
    _at(pg_dsn, _REV)
    _insert_key(pg_dsn, permissions)


def test_check_refuses_a_key_claiming_can_transfer(pg_dsn: str) -> None:
    _at(pg_dsn, _REV)
    with pytest.raises(psycopg.errors.CheckViolation, match="ak_no_transfer"):
        _insert_key(pg_dsn, BASE, can_transfer=True)


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


def test_stored_can_transfer_blocks_upgrade_atomically(pg_dsn: str) -> None:
    _at(pg_dsn, _PREV)
    _exec(pg_dsn, "TRUNCATE api_keys CASCADE")
    _insert_key(pg_dsn, BASE, can_transfer=True)  # 0017 lets the flag contradict the snapshot
    refused = _alembic(pg_dsn, "upgrade", _REV)
    assert refused.returncode != 0
    assert "ak_no_transfer" in refused.stderr
    assert _one(pg_dsn, "SELECT version_num FROM alembic_version") == _PREV
    assert list(_shape(pg_dsn)) == ["ak_snapshot_shape"]
    _exec(pg_dsn, "TRUNCATE api_keys CASCADE")
    _at(pg_dsn, _REV)


def test_upgrade_gives_up_on_a_held_lock_instead_of_queueing(pg_dsn: str) -> None:
    _at(pg_dsn, _PREV)
    with _conn(pg_dsn) as holder, holder.transaction():
        holder.execute("LOCK TABLE api_keys IN ACCESS SHARE MODE")
        refused = _alembic(pg_dsn, "upgrade", _REV)
    assert refused.returncode != 0
    assert "lock timeout" in refused.stderr
    assert _one(pg_dsn, "SELECT version_num FROM alembic_version") == _PREV
    _at(pg_dsn, _REV)
