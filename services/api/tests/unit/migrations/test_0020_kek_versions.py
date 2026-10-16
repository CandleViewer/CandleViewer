"""`0020_kek_versions` (#835, E27-K01 FU-4): offline render, constraints, reversibility."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_REV, _PREV = "0020_kek_versions", "0019_snapshot_withdraw_transfer"


def _sql(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args, "--sql"],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return " ".join(r.stdout.split())


def test_upgrade_creates_kek_versions_without_key_material() -> None:
    sql = _sql("upgrade", f"{_PREV}:{_REV}")
    assert "CREATE TABLE kek_versions" in sql
    assert "kv_kcv_len CHECK (octet_length(kcv) = 8)" in sql and "kv_version_pos" in sql
    assert "audit_log" not in sql


def test_downgrade_drops_table() -> None:
    assert "DROP TABLE IF EXISTS kek_versions" in _sql("downgrade", f"{_REV}:{_PREV}")


def test_models_mirror_kek_versions_sql() -> None:
    """The `migrations` job autogenerate-diffs the DB against `db.models.metadata`."""
    from candleviewer.db import models

    t = models.kek_versions
    assert [c.name for c in t.columns] == ["version", "kcv", "created_at", "retired_at", "env"]
    assert t.c.kcv.nullable is False and t.c.retired_at.nullable is True
    # 0026_kek_versions_env (#2338): `env` names every row's lineage and leads the primary key.
    assert t.c.env.nullable is False and t.c.env.server_default is None
    assert [c.name for c in t.primary_key.columns] == ["env", "version"]
    names = {str(c.name) for c in t.constraints}
    # CHECK names get the metadata naming-convention prefix (`ck_<table>_`).
    assert {
        "ck_kek_versions_kv_version_pos",
        "ck_kek_versions_kv_kcv_len",
        "kv_kcv_unique",
    } <= names
