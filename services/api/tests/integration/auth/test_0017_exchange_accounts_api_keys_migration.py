"""Integration: `0017_exchange_accounts_api_keys` on real Postgres 16 (#834).

Round-trip 0017 -> 0016 -> 0017 (C-5.5) plus one violating row per named constraint, asserting
the constraint name appears in the error. Not run locally (no docker); CI integration lane.
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
_A = "'00000000-0000-4000-8000-00000000000{n}'"
_SNAP = """'{"uid":"1","permissions":{"Withdraw":[]}}'"""


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")


def _alembic(dsn: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn},
        check=True,
    )


def _exec(dsn: str, sql: str) -> None:
    with psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True) as c:
        c.execute(sql)


def _tables(dsn: str) -> set[str]:
    q = "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    with psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql")) as c:
        return {r[0] for r in c.execute(q).fetchall()}


def _acct(
    n: int, uid: str, label: str, env: str = "live", kind: str = "main", parent: str = "NULL"
) -> str:
    return (
        "INSERT INTO exchange_accounts (id, env, kind, exchange_uid, label, parent_account_id) "  # noqa: S608 -- test-only literal SQL, no external input
        f"VALUES ({_A.format(n=n)}, '{env}', '{kind}', '{uid}', '{label}', {parent})"
    )


def _key(n: int, acct: int, **over: str) -> str:
    v = {
        "can_withdraw": "false", "enc_nonce": "decode('000000000000000000000000','hex')",
        "enc_alg": "'AES-256-GCM'", "key_id_last4": "'AbC1'", "read_only": "false",
        "can_trade": "false", "kek_version": "1", "status": "'pending'", "snap": _SNAP,
        "label": f"'k{n}'",
    }  # fmt: skip
    v.update(over)
    return (
        "INSERT INTO api_keys (id, exchange_account_id, label, key_id_enc, key_id_last4, "  # noqa: S608 -- test-only literal SQL, no external input
        "secret_enc, enc_nonce, enc_alg, dek_ref, kek_version, permission_snapshot, "
        "can_trade, can_withdraw, read_only, status) VALUES "
        f"('00000000-0000-4000-8000-0000000001{n:02d}', {_A.format(n=acct)}, {v['label']}, "
        f"'\\x01', {v['key_id_last4']}, '\\x02', {v['enc_nonce']}, {v['enc_alg']}, 'ref', "
        f"{v['kek_version']}, {v['snap']}::jsonb, {v['can_trade']}, {v['can_withdraw']}, "
        f"{v['read_only']}, {v['status']})"
    )


def test_0017_round_trip(pg_dsn: str) -> None:
    _alembic(pg_dsn, "upgrade", "0017_exchange_accounts_api_keys")
    assert {"exchange_accounts", "api_keys", "api_key_rotations"} <= _tables(pg_dsn)
    _alembic(pg_dsn, "downgrade", "0016_audit_read_grants")
    assert not {"exchange_accounts", "api_keys", "api_key_rotations"} & _tables(pg_dsn)
    _alembic(pg_dsn, "upgrade", "0017_exchange_accounts_api_keys")
    assert "api_keys" in _tables(pg_dsn)


_CASES = [
    ("ak_no_withdraw", [_key(1, 1, can_withdraw="true")]),
    ("ak_alg", [_key(1, 1, enc_alg="'ROT13'")]),
    ("ak_nonce_len", [_key(1, 1, enc_nonce="'\\x00'")]),
    ("ak_last4", [_key(1, 1, key_id_last4="'a-b'")]),
    ("ak_readonly_excl", [_key(1, 1, read_only="true", can_trade="true")]),
    ("ak_kek_pos", [_key(1, 1, kek_version="0")]),
    ("ak_snapshot_shape", [_key(1, 1, snap="""'{"uid":"1","permissions":{"Withdraw":["x"]}}'""")]),
    ("ux_api_keys_active", [_key(1, 1, status="'active'"), _key(2, 1, status="'active'")]),
    ("ux_api_keys_label", [_key(1, 1, label="'Dup'"), _key(2, 1, label="'dup'")]),
    ("ux_ea_uid", [_acct(9, "10234567", "dupuid")]),
    ("ux_ea_label", [_acct(9, "777", "MAIN-A")]),
    ("ea_parent_shape", [_acct(9, "778", "x", kind="sub")]),
    ("ea_no_self_parent", ["UPDATE exchange_accounts SET parent_account_id = id"]),
    ("ea_acct_type", ["UPDATE exchange_accounts SET account_type = 'SPOT'"]),
    ("trg_ea_env_parent", [_acct(9, "779", "x", env="demo", kind="sub", parent=_A.format(n=1))]),
]  # fmt: skip


@pytest.mark.parametrize(("name", "stmts"), _CASES, ids=[c[0] for c in _CASES])
def test_constraint_matrix(pg_dsn: str, name: str, stmts: list[str]) -> None:
    _alembic(pg_dsn, "upgrade", "0017_exchange_accounts_api_keys")
    _exec(pg_dsn, "TRUNCATE exchange_accounts CASCADE")
    _exec(pg_dsn, _acct(1, "10234567", "main-a"))
    with pytest.raises(psycopg.Error) as exc:
        for s in stmts:
            _exec(pg_dsn, s)
    assert name in str(exc.value)
