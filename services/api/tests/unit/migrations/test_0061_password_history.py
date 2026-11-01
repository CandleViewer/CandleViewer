"""The password_history revision (#2110 / #2330): offline render, `21` Sec.3.1.1a parity, the
register and classification rows, the downgrade guard and the model mirror. Real Postgres (the
CHECK, the cascade and the round trip with the refused downgrade):
tests/integration/storage/test_password_history_migration.py (CI only).
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

from sqlalchemy import CheckConstraint, DefaultClause
from sqlalchemy.dialects.postgresql import TIMESTAMP

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
#: The revision that creates the table, found by what it does (a re-parent renames the file).
_FILE = next(
    path
    for path in sorted((_ROOT / "candleviewer" / "migrations" / "versions").glob("*.py"))
    if "CREATE TABLE password_history (" in path.read_text(encoding="utf-8")
)
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rev_password_history", _FILE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MOD = _module()
_REV, _PREV = _MOD.revision, _MOD.down_revision


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#2110)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments, collapse whitespace, the space after `(` and a doubled `;`."""
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


def _doc_ddl() -> str:
    section = _DOC.read_text(encoding="utf-8").split("#### 3.1.1a ", 1)[1].split("#### 3.1.2 ")[0]
    return _norm(section.split("```sql", 1)[1].split("```", 1)[0])


def test_the_revision_is_named_for_its_file_and_chains_onto_the_head_before_it() -> None:
    assert _REV == _FILE.stem and _REV.endswith("_password_history")
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")


def test_the_register_and_the_classification_list_the_table() -> None:
    """21 Sec.9.4 keeps a row per landed revision; Sec.12 classifies the secret column (C-5.9)."""
    doc = _DOC.read_text(encoding="utf-8")
    assert f"| `{_REV}` " in doc.split("### 9.4 ", 1)[1]
    classified = doc.split("## 12. ", 1)[1]
    assert re.search(r"\| `password_history` +\| `password_hash` +\| S ", classified)


def test_upgrade_is_section_3_1_1a_verbatim_under_a_bounded_lock_wait() -> None:
    """C-5.1 and C-5.6: the table, its CHECK and its SECRET comment, nothing else."""
    ddl = _doc_ddl()
    assert ddl.startswith("CREATE TABLE password_history (user_id uuid NOT NULL REFERENCES")
    assert "CONSTRAINT ph_pwd_argon CHECK (password_hash LIKE '$argon2id$%')" in ddl
    assert "COMMENT ON COLUMN password_history.password_hash IS 'SECRET:" in ddl
    assert _in_order(_up(), [_LOCK, ddl, _RESET])
    assert "GRANT" not in _up() and "IF NOT EXISTS" not in _up()


def test_downgrade_refuses_while_any_row_exists_then_drops_the_table() -> None:
    """C-5.2: dropping retired hashes would let a user reuse one; an empty table is dropped."""
    assert _in_order(
        _down(),
        [
            _LOCK,
            "LOCK TABLE password_history IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM password_history) THEN",
            f"RAISE EXCEPTION '{_REV} downgrade refused:",
            "DROP TABLE password_history;",
            _RESET,
        ],
    )
    assert _down().count("DROP ") == 1 and "(C-5.2)" in _down()


def test_the_model_mirrors_the_table_its_check_and_its_comment() -> None:
    """`alembic check` (CI-MIG-002) diffs this model against the migrated database."""
    t = models.password_history
    assert [c.name for c in t.columns] == ["user_id", "password_hash", "retired_at"]
    assert not [c.name for c in t.columns if c.nullable]
    assert [c.name for c in t.primary_key.columns] == ["user_id", "retired_at"]
    defaults = {
        c.name: str(c.server_default.arg)
        for c in t.columns
        if isinstance(c.server_default, DefaultClause)
    }
    assert defaults == {"retired_at": "now()"}
    assert isinstance(t.c.retired_at.type, TIMESTAMP)
    (fk,) = t.c.user_id.foreign_keys
    assert (fk.target_fullname, fk.ondelete) == ("users.id", "CASCADE")
    (check,) = [c for c in t.constraints if isinstance(c, CheckConstraint)]
    assert f"CONSTRAINT ph_pwd_argon CHECK ({_norm(str(check.sqltext))})" in _up()
    assert str(t.c.password_hash.comment).startswith("SECRET:")
    assert f"IS '{t.c.password_hash.comment}'" in _up()
