"""`0054_scanner_presets` (E08-T09 PR 2a, #4708): offline render, plan-doc parity (21 section
3.8.7 and the `lp_kind` block of section 3.8.1), the downgrade guards and the model mirror. Real
Postgres (the CHECKs, the two unique indexes, the widened `lp_kind`, the round trip and the
refused downgrades): tests/integration/storage/test_scanner_presets_migration.py."""

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
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

from candleviewer.api.workspaces_models import PANE_KINDS
from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_FILE = _ROOT / "candleviewer" / "migrations" / "versions" / "0054_scanner_presets.py"
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
_CHECKS = ("sp_name_len", "sp_filter_shape", "sp_sort", "sp_version")
_OLD_KINDS = (
    "'chart','dom','tape','profile','cvd','oi','deep_stats','regime','positions','journal',"
    "'watchlist','alerts'"
)


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rev_0054", _FILE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MOD = _module()
_REV, _PREV = _MOD.revision, _MOD.down_revision


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#4708)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
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


def _doc_block(heading: str, nth: int = 0) -> str:
    section = _DOC.read_text(encoding="utf-8").split(f"#### {heading} ", 1)[1].split("\n#### ")[0]
    return _norm(section.split("```sql")[nth + 1].split("```", 1)[0])


def test_revision_is_named_0054_and_chains_onto_the_single_head_before_it() -> None:
    assert _REV == "0054_scanner_presets"
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")


def test_the_revision_register_lists_the_revision() -> None:
    assert f"| `{_REV}` " in _DOC.read_text(encoding="utf-8").split("### 9.4 ", 1)[1]


def test_upgrade_is_section_3_8_7_then_the_lp_kind_block_under_a_bounded_lock_wait() -> None:
    table, kinds = _doc_block("3.8.7"), _doc_block("3.8.1", 1)
    assert table.startswith("CREATE TABLE scanner_presets (id uuid PRIMARY KEY,")
    assert kinds.startswith("ALTER TABLE layout_panes DROP CONSTRAINT lp_kind,")
    assert _in_order(_up(), [_LOCK, table, kinds, _RESET])
    for name in _CHECKS:
        assert f"CONSTRAINT {name} CHECK" in table, name
    assert "GRANT" not in _up() and "IF NOT EXISTS" not in _up()


def test_the_two_unique_indexes_are_name_per_user_case_insensitive_and_one_default() -> None:
    assert "CREATE UNIQUE INDEX ux_sp_name ON scanner_presets (user_id, lower(name));" in _up()
    assert "CREATE UNIQUE INDEX ux_sp_default ON scanner_presets (user_id) WHERE is_default;" in (
        _up()
    )


def test_lp_kind_is_widened_to_scanner_not_valid_then_validated() -> None:
    kinds = ",".join(f"'{k}'" for k in PANE_KINDS)
    assert PANE_KINDS[-1] == "scanner" and kinds == _OLD_KINDS + ",'scanner'"
    assert _in_order(_up(), [
        f"ADD CONSTRAINT lp_kind CHECK (pane_kind IN ({kinds})) NOT VALID;",
        "ALTER TABLE layout_panes VALIDATE CONSTRAINT lp_kind;",
    ])  # fmt: skip


def test_downgrade_refuses_while_a_preset_or_a_scanner_pane_exists_then_restores() -> None:
    """C-5.2: dropping the table would lose a user's presets, and the narrowed `lp_kind` cannot
    hold a scanner pane, so either refuses; otherwise 0022's `lp_kind` comes back."""
    assert _in_order(
        _down(),
        [
            _LOCK,
            "LOCK TABLE scanner_presets, layout_panes IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM scanner_presets) THEN",
            "RAISE EXCEPTION '0054_scanner_presets downgrade refused: scanner_presets",
            "IF EXISTS (SELECT 1 FROM layout_panes WHERE pane_kind = 'scanner') THEN",
            "RAISE EXCEPTION '0054_scanner_presets downgrade refused: a layout",
            f"ADD CONSTRAINT lp_kind CHECK (pane_kind IN ({_OLD_KINDS})) NOT VALID;",
            "ALTER TABLE layout_panes VALIDATE CONSTRAINT lp_kind;",
            "DROP TABLE scanner_presets;",
            _RESET,
        ],
    )
    assert _down().count("DROP TABLE") == 1 and "(C-5.2)" in _down()


def test_the_model_mirrors_the_columns_and_their_defaults() -> None:
    t = models.scanner_presets
    assert [c.name for c in t.columns] == [
        "id", "user_id", "name", "filter", "sort", "is_default", "version", "created_at",
        "updated_at",
    ]  # fmt: skip
    assert not any(c.nullable for c in t.columns if not c.primary_key)
    defaults = {
        c.name: str(c.server_default.arg)
        for c in t.columns
        if isinstance(c.server_default, DefaultClause)
    }
    assert defaults == {
        "filter": "'{}'::jsonb", "sort": "'turnover_24h'", "is_default": "false", "version": "1",
        "created_at": "now()", "updated_at": "now()",
    }  # fmt: skip
    assert isinstance(t.c.id.type, UUID) and isinstance(t.c.filter.type, JSONB)
    for stamp in ("created_at", "updated_at"):
        column_type = t.c[stamp].type
        assert isinstance(column_type, TIMESTAMP) and column_type.timezone, stamp
    (fk,) = t.c.user_id.foreign_keys
    assert (fk.target_fullname, fk.ondelete) == ("users.id", "CASCADE")


def test_the_model_checks_and_indexes_are_the_migrations() -> None:
    t = models.scanner_presets
    checks = {
        str(c.name).removeprefix("ck_scanner_presets_"): _norm(str(c.sqltext))
        for c in t.constraints
        if isinstance(c, CheckConstraint)
    }
    assert sorted(checks) == sorted(_CHECKS)
    for check, text in checks.items():
        assert f"CONSTRAINT {check} CHECK ({text})" in _up(), check
    indexes = {str(ix.name): ix for ix in t.indexes}
    assert sorted(indexes) == ["ux_sp_default", "ux_sp_name"]
    name, default = indexes["ux_sp_name"], indexes["ux_sp_default"]
    assert name.unique and [str(e) for e in name.expressions] == [
        "scanner_presets.user_id", "lower(name)",
    ]  # fmt: skip
    assert default.unique and [c.name for c in default.columns] == ["user_id"]
    assert str(default.dialect_options["postgresql"]["where"]) == "is_default"
    lp_kind = next(
        c for c in models.layout_panes.constraints
        if isinstance(c, CheckConstraint) and str(c.name).endswith("lp_kind")
    )  # fmt: skip
    assert f"CHECK ({_norm(str(lp_kind.sqltext))}) NOT VALID" in _up()
