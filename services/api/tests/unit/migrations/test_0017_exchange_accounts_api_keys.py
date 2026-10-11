"""`0017_exchange_accounts_api_keys` (#834): offline render, named constraints, reversibility."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_REV = "0017_exchange_accounts_api_keys"
_PREV = "0016_audit_read_grants"
NAMED = [
    "ea_parent_shape", "ea_no_self_parent", "ea_acct_type", "ux_ea_uid", "ux_ea_label",
    "ix_ea_parent", "ix_ea_tradeable", "ak_no_withdraw", "ak_alg", "ak_nonce_len", "ak_last4",
    "ak_readonly_excl", "ak_kek_pos", "ak_snapshot_shape", "ux_api_keys_label",
    "ux_api_keys_active", "ix_api_keys_rotation", "ix_api_keys_kek", "trg_ea_env_parent",
]  # fmt: skip


def _sql(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args, "--sql"],
        cwd=_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return " ".join(r.stdout.split())


@pytest.mark.parametrize("name", NAMED)
def test_upgrade_declares_named_constraint(name: str) -> None:
    assert name in _sql("upgrade", f"{_PREV}:{_REV}")


def test_upgrade_has_no_plaintext_key_column() -> None:
    sql = _sql("upgrade", f"{_PREV}:{_REV}")
    assert "api_key " not in sql and "api_secret" not in sql
    assert "key_id_enc bytea NOT NULL" in sql and "secret_enc bytea NOT NULL" in sql


def test_upgrade_does_not_touch_audit_tables() -> None:
    assert "audit_log" not in _sql("upgrade", f"{_PREV}:{_REV}")


def test_downgrade_drops_everything_it_created() -> None:
    sql = _sql("downgrade", f"{_REV}:{_PREV}")
    for table in ("api_key_rotations", "api_keys", "exchange_accounts"):
        assert f"DROP TABLE IF EXISTS {table}" in sql
    for typ in ("key_status", "account_kind"):
        assert f"DROP TYPE IF EXISTS {typ}" in sql
    assert "DROP TRIGGER IF EXISTS trg_ea_env_parent" in sql
