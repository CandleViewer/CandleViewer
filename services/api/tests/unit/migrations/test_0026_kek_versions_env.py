"""`0026_kek_versions_env` (#2338): offline render of the guard, the column, the key swap and the
downgrade refusal. Real Postgres: `tests/integration/auth/test_0026_kek_versions_env_migration.py`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_REV, _PREV = "0026_kek_versions_env", "0025_settings"


def _sql(direction: str, span: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", direction, span, "--sql"],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return " ".join(r.stdout.split())


def _in_order(sql: str, steps: list[str]) -> bool:
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def test_upgrade_refuses_usable_keys_then_keys_each_lineage_by_environment() -> None:
    sql = _sql("upgrade", f"{_PREV}:{_REV}")
    assert _in_order(
        sql,
        [
            "SET LOCAL lock_timeout = '5s';",
            "IF EXISTS (SELECT FROM api_keys WHERE revoked_at IS NULL AND status <> 'revoked') "
            "THEN RAISE EXCEPTION '0026_kek_versions_env upgrade refused: usable api_keys rows "
            "exist and may hold environment-free v1 KEK wraps (rows written before #2338), which "
            "cv-api refuses after #2338 and a migration cannot re-wrap; revoke them first "
            '(docs/ops/runbooks/kek-custody.md, "Upgrading to per-environment KEK lineages")\';',
            "ALTER TABLE kek_versions ADD COLUMN env exchange_env NOT NULL DEFAULT 'demo';",
            "ALTER TABLE kek_versions ALTER COLUMN env DROP DEFAULT;",
            "ALTER TABLE kek_versions DROP CONSTRAINT kek_versions_pkey;",
            "ALTER TABLE kek_versions ADD CONSTRAINT kek_versions_pkey PRIMARY KEY (env, version);",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )
    assert "kv_kcv_unique" not in sql  # UNIQUE (kcv) stays global (R1)
    assert "UPDATE api_keys" not in sql  # no re-wrap (R2)


def test_downgrade_refuses_to_merge_two_lineages_under_one_version() -> None:
    assert _in_order(
        _sql("downgrade", f"{_REV}:{_PREV}"),
        [
            "SET LOCAL lock_timeout = '5s';",
            "IF EXISTS (SELECT FROM kek_versions GROUP BY version HAVING count(*) > 1) "
            "THEN RAISE EXCEPTION '0026_kek_versions_env downgrade refused",
            "ALTER TABLE kek_versions DROP CONSTRAINT kek_versions_pkey;",
            "ALTER TABLE kek_versions ADD CONSTRAINT kek_versions_pkey PRIMARY KEY (version);",
            "ALTER TABLE kek_versions DROP COLUMN env;",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )
