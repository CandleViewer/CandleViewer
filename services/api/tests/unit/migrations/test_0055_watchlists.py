"""The watchlists revision (E08-T07, #4706): offline render, `21` Sec.3.8.6 parity, the register
row, the downgrade guard and the model mirror. Real Postgres (the CHECKs, `ux_wl_name`, the round
trip and the refused downgrade): tests/integration/storage/test_watchlists_migration.py (CI only).
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
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP, UUID

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
#: The revision that creates the table, found by what it does, so its id is read from it (a
#: re-parent renames the file and its ids, and no test repeats them).
_FILE = next(
    path
    for path in sorted((_ROOT / "candleviewer" / "migrations" / "versions").glob("*.py"))
    if "CREATE TABLE watchlists (" in path.read_text(encoding="utf-8")
)
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
_CHECKS = ("wl_name_len", "wl_symbols_max", "wl_columns_max", "wl_version")


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rev_watchlists", _FILE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MOD = _module()
_REV, _PREV = _MOD.revision, _MOD.down_revision


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#4706)
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


def _doc_ddl() -> str:
    section = _DOC.read_text(encoding="utf-8").split("#### 3.8.6 ", 1)[1].split("### 3.9 ")[0]
    return _norm(section.split("```sql", 1)[1].split("```", 1)[0])


def test_the_revision_is_named_for_its_file_and_chains_onto_the_head_before_it() -> None:
    assert _REV == _FILE.stem and _REV.endswith("_watchlists")
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")


def test_the_revision_register_lists_the_revision() -> None:
    """21 Sec.9.4 keeps a row per landed revision (C-11.2: the docs reflect what ships)."""
    assert f"| `{_REV}` " in _DOC.read_text(encoding="utf-8").split("### 9.4 ", 1)[1]


def test_upgrade_is_section_3_8_6_verbatim_under_a_bounded_lock_wait() -> None:
    """C-5.1 and C-5.6: the table and `ux_wl_name`, as 21 Sec.3.8.6 states them, nothing else."""
    ddl = _doc_ddl()
    assert ddl.startswith("CREATE TABLE watchlists (id uuid PRIMARY KEY,")
    assert ddl.endswith("CREATE UNIQUE INDEX ux_wl_name ON watchlists (user_id, lower(name));")
    assert _in_order(_up(), [_LOCK, ddl, _RESET])
    for name in _CHECKS:
        assert f"CONSTRAINT {name} CHECK" in ddl, name
    assert "GRANT" not in _up() and "IF NOT EXISTS" not in _up()


def test_downgrade_refuses_while_any_list_exists_then_drops_the_table() -> None:
    """C-5.2: dropping a user's lists is refused; an empty table is dropped."""
    assert _in_order(
        _down(),
        [
            _LOCK,
            "LOCK TABLE watchlists IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM watchlists) THEN",
            f"RAISE EXCEPTION '{_REV} downgrade refused:",
            "DROP TABLE watchlists;",
            _RESET,
        ],
    )
    assert _down().count("DROP ") == 1 and "(C-5.2)" in _down()


def test_the_model_mirrors_the_table_its_checks_and_its_index() -> None:
    """`alembic check` (CI-MIG-002) diffs this model against the migrated database."""
    t = models.watchlists
    assert [c.name for c in t.columns] == [
        "id", "user_id", "name", "symbols", "columns", "version", "created_at", "updated_at",
    ]  # fmt: skip
    assert not [c.name for c in t.columns if c.nullable]
    defaults = {
        c.name: str(c.server_default.arg)
        for c in t.columns
        if isinstance(c.server_default, DefaultClause)
    }
    assert defaults == {
        "symbols": "'{}'", "columns": "'{}'", "version": "1", "created_at": "now()",
        "updated_at": "now()",
    }  # fmt: skip
    assert isinstance(t.c.id.type, UUID) and isinstance(t.c.symbols.type, ARRAY)
    assert all(isinstance(t.c[s].type, TIMESTAMP) for s in ("created_at", "updated_at"))
    (fk,) = t.c.user_id.foreign_keys
    assert (fk.target_fullname, fk.ondelete) == ("users.id", "CASCADE")
    checks = {
        str(c.name).removeprefix("ck_watchlists_"): _norm(str(c.sqltext))
        for c in t.constraints
        if isinstance(c, CheckConstraint)
    }
    assert sorted(checks) == sorted(_CHECKS)
    for check, text in checks.items():
        assert f"CONSTRAINT {check} CHECK ({text})" in _up(), check
    (index,) = t.indexes
    assert (index.name, index.unique) == ("ux_wl_name", True)
    assert [str(e) for e in index.expressions] == ["watchlists.user_id", "lower(name)"]
