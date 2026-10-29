"""The sessions lock-state revision (E09-S03-F1, #4743): offline render, `21` Sec.3.1.4 parity, the
register row, the downgrade guard and the model mirror. Real Postgres (the round trip on an empty
and a seeded database, the refused downgrade): tests/integration/storage/
test_sessions_lock_state_migration.py.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

from sqlalchemy.dialects.postgresql import TIMESTAMP

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
#: The revision that adds the columns, found by what it does, so its id is read from it (a
#: re-parent renames the file and its ids, and no test repeats them).
_FILE = next(
    path
    for path in sorted((_ROOT / "candleviewer" / "migrations" / "versions").glob("*.py"))
    if "ADD COLUMN locked_at" in path.read_text(encoding="utf-8")
)
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rev_sessions_lock_state", _FILE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MOD = _module()
_REV, _PREV = _MOD.revision, _MOD.down_revision


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#4743)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments and collapse whitespace, so layout never matters."""
    return " ".join(re.sub(r"--[^\n]*", "", sql).split()).replace(";;", ";")


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


def _doc_ddl() -> str:
    """Sec.3.1.4's third block: after the table's and 0042's (`test_0042_models_match_sql.py` reads
    the second)."""
    section = _DOC.read_text(encoding="utf-8").split("#### 3.1.4 ", 1)[1].split("#### 3.1.5 ")[0]
    return _norm(section.split("```sql")[3].split("```", 1)[0])


def test_the_revision_is_named_for_its_file_and_chains_onto_the_head_before_it() -> None:
    assert _REV == _FILE.stem and _REV.endswith("_sessions_lock_state")
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")


def test_the_revision_is_21s_ddl_verbatim_and_has_a_ledger_row() -> None:
    """C-5.1: the two columns as 21 Sec.3.1.4 states them; Sec.9.4 keeps a row per revision."""
    assert _doc_ddl() == (
        "ALTER TABLE sessions ADD COLUMN locked_at timestamptz, ADD COLUMN unlocked_at timestamptz;"
    )
    assert _doc_ddl() in _up()
    ledger = _DOC.read_text(encoding="utf-8").split("### 9.4 ", 1)[1].split("### 9.5 ", 1)[0]
    row = next(line for line in ledger.splitlines() if line.startswith(f"| `{_REV}` "))
    assert "the downgrade refuses while a live session is locked by request" in row


def test_the_revision_adds_two_nullable_columns_under_a_lock_timeout() -> None:
    """C-5.6 and Sec.9.3 rule 2: nullable, no default, so no rewrite; the lock wait bounded."""
    assert _in_order(_up(), [_LOCK, "ALTER TABLE sessions", _RESET])
    added = re.findall(r"ADD COLUMN (\w+) ([^,;]+)", _up())
    assert added == [("locked_at", "timestamptz"), ("unlocked_at", "timestamptz")]
    for word in ("DEFAULT now", "NOT NULL", "GRANT", "IF NOT EXISTS", "UPDATE sessions"):
        assert word not in _up(), word


def test_the_downgrade_refuses_while_a_live_session_is_locked() -> None:
    """C-5.2: dropping `locked_at` would unlock a live session, so that is refused; a revoked or
    expired row's lock does not hold the downgrade. Otherwise both columns go."""
    assert _in_order(
        _down(),
        [
            _LOCK,
            "LOCK TABLE sessions IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM sessions WHERE locked_at IS NOT NULL AND revoked_at IS NULL "
            "AND expires_at > now()) THEN",
            f"RAISE EXCEPTION '{_REV} downgrade refused:",
            "ALTER TABLE sessions DROP COLUMN unlocked_at, DROP COLUMN locked_at;",
            _RESET,
        ],
    )
    assert _down().count("DROP ") == 2 and "(C-5.2)" in _down()


def test_the_model_mirrors_the_columns() -> None:
    """`alembic check` (CI-MIG-002) diffs this model against the migrated database."""
    t = models.sessions
    assert [c.name for c in t.columns][-2:] == ["locked_at", "unlocked_at"]
    for name in ("locked_at", "unlocked_at"):
        column = t.c[name]
        assert column.nullable and column.server_default is None and column.comment is None
        assert isinstance(column.type, TIMESTAMP) and column.type.timezone
