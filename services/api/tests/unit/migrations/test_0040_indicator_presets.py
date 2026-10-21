"""`0040_indicator_presets` (E13-T03, #427): offline render, plan-doc parity, the seed, the
downgrade guard and the model mirror. Real Postgres (the CHECKs, `ux_ip_name`, the round trip on
an empty and a seeded database, the re-seed and the refused downgrade):
tests/integration/storage/test_indicator_presets_migration.py (CI only: no Docker here)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

from sqlalchemy import CheckConstraint, DefaultClause
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

from candleviewer.db import models
from candleviewer.db.builtin_indicator_presets import BUILTIN_PRESETS

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_FILE = _ROOT / "candleviewer" / "migrations" / "versions" / "0040_indicator_presets.py"
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
_CHECKS = (
    "ip_target", "ip_code", "ip_builtin_owner", "ip_name_len", "ip_params_shape", "ip_style_shape",
)  # fmt: skip


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rev_0040", _FILE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MOD = _module()
_REV, _PREV = _MOD.revision, _MOD.down_revision


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#427)
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
    section = _DOC.read_text(encoding="utf-8").split("#### 3.8.4 ", 1)[1].split("#### 3.8.5 ")[0]
    return _norm(section.split("```sql", 1)[1].split("```", 1)[0])


def test_revision_is_named_0040_and_chains_onto_the_single_head_before_it() -> None:
    assert _REV == "0040_indicator_presets"
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")


def test_the_revision_register_lists_the_revision() -> None:
    """21 Sec.9.4 keeps a row per landed revision (C-11.2: the docs reflect what ships)."""
    assert f"| `{_REV}` " in _DOC.read_text(encoding="utf-8").split("### 9.4 ", 1)[1]


def test_upgrade_is_section_3_8_4_verbatim_under_a_bounded_lock_wait() -> None:
    """C-5.1 and C-5.6: the Sec.3.8.4 block as amended (Q5's four CHECKs), then the seed."""
    ddl = _doc_ddl()
    assert ddl.startswith("CREATE TABLE indicator_presets (id uuid PRIMARY KEY,")
    assert _in_order(_up(), [_LOCK, ddl, "INSERT INTO indicator_presets", _RESET])
    for name in _CHECKS:
        assert f"CONSTRAINT {name} CHECK" in ddl, name
    assert "GRANT" not in _up() and "IF NOT EXISTS" not in _up()


def test_unique_name_index_is_case_insensitive_per_owner_and_code_among_live_rows() -> None:
    assert (
        "CREATE UNIQUE INDEX ux_ip_name ON indicator_presets "
        "(coalesce(owner_user_id,'00000000-0000-0000-0000-000000000000'::uuid), "
        "indicator_code, lower(name)) WHERE deleted_at IS NULL;"
    ) in _up()
    favourite = "CREATE INDEX ix_ip_fav ON indicator_presets (owner_user_id) "
    assert favourite + "WHERE is_favourite AND deleted_at IS NULL;" in _up()


def test_the_seed_is_the_18_builtins_owned_by_no_one_and_never_overwrites() -> None:
    seed = _norm(_MOD._SEED_SQL)
    rows = re.findall(r"\('([0-9a-f-]{36})', NULL, '([a-z0-9_]+)', '([^']*)', '([^']*)', "
                      r"'\{\}', '(overlay|subpane)', true, false\)", seed)  # fmt: skip
    expected = [
        (p.id, p.indicator_code, p.name, json.dumps(dict(p.params)), p.pane_target)
        for p in BUILTIN_PRESETS
    ]
    assert rows == expected and len(rows) == 18
    assert seed.endswith("ON CONFLICT DO NOTHING;") and seed in _up()


def test_downgrade_refuses_while_any_user_preset_exists_then_drops_the_table() -> None:
    """C-5.2: soft-deleted user presets block it too; the built-ins alone never do, so CI's
    `downgrade base` then `upgrade head` runs on a seeded database."""
    assert _in_order(
        _down(),
        [
            _LOCK,
            "LOCK TABLE indicator_presets IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM indicator_presets WHERE NOT is_builtin "
            "OR owner_user_id IS NOT NULL) THEN",
            "RAISE EXCEPTION '0040_indicator_presets downgrade refused:",
            "DROP TABLE IF EXISTS indicator_presets;",
            _RESET,
        ],
    )
    assert _down().count("DROP ") == 1 and "(C-5.2)" in _down()


def test_the_model_mirrors_the_columns_and_their_defaults() -> None:
    """`alembic check` (CI-MIG-002) diffs this model against the migrated database."""
    t = models.indicator_presets
    assert [c.name for c in t.columns] == [
        "id", "owner_user_id", "indicator_code", "name", "params", "style", "pane_target",
        "is_builtin", "is_favourite", "created_at", "updated_at", "deleted_at",
    ]  # fmt: skip
    nullable = {c.name for c in t.columns if c.nullable}
    assert nullable == {"owner_user_id", "deleted_at"}
    defaults = {
        c.name: str(c.server_default.arg)
        for c in t.columns
        if isinstance(c.server_default, DefaultClause)
    }
    assert defaults == {
        "params": "'{}'::jsonb", "style": "'{}'::jsonb", "pane_target": "'overlay'",
        "is_builtin": "false", "is_favourite": "false", "created_at": "now()",
        "updated_at": "now()",
    }  # fmt: skip
    assert isinstance(t.c.id.type, UUID) and isinstance(t.c.params.type, JSONB)
    for stamp in ("created_at", "updated_at", "deleted_at"):
        column_type = t.c[stamp].type
        assert isinstance(column_type, TIMESTAMP) and column_type.timezone, stamp
    (fk,) = t.c.owner_user_id.foreign_keys
    assert (fk.target_fullname, fk.ondelete) == ("users.id", "CASCADE")


def test_the_model_checks_and_indexes_are_the_migrations() -> None:
    t = models.indicator_presets
    checks = {
        str(c.name).removeprefix("ck_indicator_presets_"): _norm(str(c.sqltext))
        for c in t.constraints
        if isinstance(c, CheckConstraint)
    }
    assert sorted(checks) == sorted(_CHECKS)
    for check, text in checks.items():
        assert f"CONSTRAINT {check} CHECK ({text})" in _up(), check
    indexes = {str(ix.name): ix for ix in t.indexes}
    assert sorted(indexes) == ["ix_ip_fav", "ux_ip_name"]
    unique = indexes["ux_ip_name"]
    assert unique.unique and [str(e) for e in unique.expressions] == [
        "coalesce(owner_user_id, '00000000-0000-0000-0000-000000000000'::uuid)",
        "indicator_presets.indicator_code",
        "lower(name)",
    ]
    assert str(unique.dialect_options["postgresql"]["where"]) == "deleted_at IS NULL"
    fav = indexes["ix_ip_fav"]
    assert not fav.unique and [c.name for c in fav.columns] == ["owner_user_id"]
    assert str(fav.dialect_options["postgresql"]["where"]) == "is_favourite AND deleted_at IS NULL"
