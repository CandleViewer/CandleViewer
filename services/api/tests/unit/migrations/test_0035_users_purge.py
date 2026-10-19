"""`0035_users_purge` (E42-T10 #2650, S2): offline render, plan-doc parity, the downgrade guard
and what it drops, and the model mirror. Real Postgres (the round trip on an empty and a seeded
database, the CHECK and the refused downgrade): tests/integration/storage/
test_users_purge_migration.py."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

from sqlalchemy.dialects.postgresql import TIMESTAMP

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0035_users_purge", "0034_order_vocabulary"
_COLUMNS = ("purge_after", "anonymised_at")
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#2650)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments, collapse whitespace, the space after `(` and the `;` alembic appends to
    a statement that has one, so layout never matters."""
    return " ".join(re.sub(r"--[^\n]*", "", sql).split()).replace("( ", "(").replace(";;", ";")


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", f"{_PREV}:{_REV}", "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", f"{_REV}:{_PREV}", "--sql"))


def _in_order(sql: str, steps: list[str]) -> bool:
    missing = [step for step in steps if step not in sql]
    assert not missing, f"not in the rendered SQL: {missing}"
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def test_revision_chains_onto_0034_order_vocabulary() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")


def test_the_revision_register_lists_the_revision() -> None:
    """21 Sec.9.4 keeps a row per landed revision (C-11.2: the docs reflect what ships)."""
    assert f"| `{_REV}` " in _DOC.read_text(encoding="utf-8").split("### 9.4 ", 1)[1]


def test_0035_adds_nullable_columns() -> None:
    """C-5.1, Sec.9.3 rule 2: the second ```sql block of Sec.3.1.1, verbatim, under a bounded lock
    wait (C-5.6): two nullable `timestamptz` columns with no default (no rewrite) and the CHECK that
    only a scheduled purge is ever marked done. No GRANT (the default privileges cover added
    columns) and no comment tag (neither column is PII, Sec.12)."""
    section = _DOC.read_text(encoding="utf-8").split("#### 3.1.1 ", 1)[1].split("#### 3.1.2 ")[0]
    ddl = _norm(section.split("```sql", 2)[2].split("```", 1)[0])
    assert ddl.startswith("ALTER TABLE users ADD COLUMN purge_after timestamptz,")
    assert _in_order(_up(), [_LOCK, ddl, _RESET, "UPDATE alembic_version"])
    columns = "ADD COLUMN purge_after timestamptz, ADD COLUMN anonymised_at timestamptz,"
    assert columns in ddl and "DEFAULT" not in ddl  # nullable, no default
    assert "GRANT" not in _up() and "COMMENT ON" not in _up()


def test_0035_downgrade_only_new_columns() -> None:
    """C-5.2: it refuses while a purge is pending (dropping `purge_after` would cancel it
    silently), then drops the CHECK and the two columns and nothing else."""
    assert _in_order(
        _down(),
        [
            _LOCK,
            "LOCK TABLE users IN SHARE MODE;",
            "WHERE purge_after IS NOT NULL AND anonymised_at IS NULL) THEN",
            "RAISE EXCEPTION '0035_users_purge downgrade refused:",
            "ALTER TABLE users DROP CONSTRAINT users_purge_shape, "
            "DROP COLUMN anonymised_at, DROP COLUMN purge_after;",
            _RESET,
        ],
    )
    assert _down().count("DROP ") == 3 and "(C-5.2)" in _down()


def test_the_model_mirrors_the_columns_nullable_with_no_default_or_comment() -> None:
    """`alembic check` (CI-MIG-002) compares the model with the database: tz-aware, nullable."""
    columns = [models.users.c[name] for name in _COLUMNS]
    assert [(c.nullable, c.server_default, c.comment) for c in columns] == [(True, None, None)] * 2
    assert all(isinstance(c.type, TIMESTAMP) and c.type.timezone for c in columns)
    assert "ck_users_users_purge_shape" in {str(c.name) for c in models.users.constraints}
