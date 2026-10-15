"""`0025_settings` (E42-T01 #963): offline render, plan-doc parity, models, classification.

Real-Postgres behaviour (named-constraint rejection, key regex, unique system key, catalog parity,
round trip) is covered by `tests/integration/storage/test_settings_migration.py`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Column, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.schema import DefaultClause

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0025_settings", "0024_api_keys_write_once"
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _sql(direction: str, span: str) -> str:
    return _alembic(direction, span, "--sql")


def _norm(sql: str) -> str:
    """Drop `--` comments and collapse whitespace so layout never matters."""
    return " ".join(re.sub(r"--[^\n]*", "", sql).split())


def _doc_ddl() -> str:
    """The `settings` table and its two indexes, verbatim from 21-database-schema.md Sec.3.9.

    Sec.3.9 shares one ```sql block with `feature_flags` and `feature_flag_overrides`; only the
    part before `CREATE TABLE feature_flags` belongs to this revision.
    """
    text = _DOC.read_text(encoding="utf-8")
    block = text.split("### 3.9 Settings & feature flags", 1)[1].split("```sql", 1)[1]
    return block.split("CREATE TABLE feature_flags (", 1)[0]


def test_revision_follows_0024_and_is_the_head() -> None:
    """`test_single_head.py` owns "exactly one head"; this pins where 0025 sits in the chain."""
    assert f"{_PREV} -> {_REV} (head)" in _alembic("history", "-r", f"{_PREV}:{_REV}")


def test_upgrade_ddl_is_the_plan_doc_ddl_verbatim() -> None:
    """The table, its four named CHECKs and both indexes are exactly Sec.3.9's `settings` DDL."""
    doc = _norm(_doc_ddl())
    assert doc.startswith("CREATE TABLE settings (")
    assert doc.endswith(
        "CREATE UNIQUE INDEX ux_settings_user ON settings (user_id, key) WHERE scope = 'user';"
    )
    assert doc in _norm(_sql("upgrade", _UP))


def test_upgrade_ships_only_the_settings_table() -> None:
    """Nothing more than Sec.3.9's `settings`: no feature-flag tables, seed, trigger or grant."""
    sql = _norm(_sql("upgrade", _UP))
    assert sql.count("CREATE TABLE ") == 1
    assert sql.count("CREATE UNIQUE INDEX ") == 2
    assert sql.count("CREATE INDEX ") == 0
    for absent in ("feature_flag", "flag_kind", "INSERT INTO settings", "CREATE TRIGGER"):
        assert absent not in sql
    assert "GRANT " not in sql and "REVOKE " not in sql


def test_upgrade_names_every_check_constraint_and_index() -> None:
    sql = _norm(_sql("upgrade", _UP))
    for name in ("st_scope", "st_shape", "st_key_fmt", "st_vtype"):
        assert f"CONSTRAINT {name} CHECK" in sql
    assert "CONSTRAINT st_key_fmt CHECK (key ~ '^[a-z0-9_]+([.][a-z0-9_]+){0,4}$')" in sql
    assert "CREATE UNIQUE INDEX ux_settings_sys ON settings (key) WHERE scope = 'system';" in sql
    assert (
        "CREATE UNIQUE INDEX ux_settings_user ON settings (user_id, key) WHERE scope = 'user';"
    ) in sql


def test_upgrade_tags_value_as_secret_per_classification() -> None:
    """C-5.9 / 21 Sec.12: `value` is class S when `is_secret`; the comment is the declaration.

    The model mirrors the comment verbatim (`alembic check` diffs column comments too); no other
    column can hold a credential, token or PII, so no other column carries one.
    """
    comment = models.settings.c.value.comment
    assert comment is not None and comment.startswith("SECRET:")
    assert f"COMMENT ON COLUMN settings.value IS '{comment}';" in _norm(_sql("upgrade", _UP))
    assert [c.name for c in models.settings.columns if c.comment] == ["value"]
    assert "| `settings` " in _DOC.read_text(encoding="utf-8")


def test_upgrade_bounds_every_lock_with_lock_timeout() -> None:
    """C-5.6 (0019/0022/0023 pattern): the two FKs take a SHARE ROW EXCLUSIVE lock on `users`,
    so every statement sits inside a 5 s lock_timeout that is reset for the next revision."""
    sql = _norm(_sql("upgrade", _UP))
    first = sql.index("SET LOCAL lock_timeout = '5s';")
    assert first < sql.index("CREATE TABLE settings (")
    assert sql.rindex("COMMENT ON COLUMN settings.") < sql.index(
        "SET LOCAL lock_timeout = DEFAULT;"
    )


def test_downgrade_refuses_while_populated_then_drops_the_table() -> None:
    sql = _norm(_sql("downgrade", _DOWN))
    assert "IF EXISTS (SELECT 1 FROM settings) THEN" in sql
    assert "RAISE EXCEPTION '0025_settings downgrade refused" in sql
    assert sql.index("DROP TABLE settings;") > sql.index("RAISE EXCEPTION")
    assert "DROP TYPE" not in sql  # this revision creates no type


def test_downgrade_locks_before_it_checks_and_bounds_every_lock() -> None:
    """The SHARE lock keeps a concurrent writer from slipping a row in between the guard and the
    DROP, and `lock_timeout` bounds both that lock and the `users` lock the FK drops take."""
    sql = _norm(_sql("downgrade", _DOWN))
    lock_timeout = sql.index("SET LOCAL lock_timeout = '5s';")
    lock = sql.index("LOCK TABLE settings IN SHARE MODE;")
    guard = sql.index("IF EXISTS (SELECT 1 FROM settings) THEN")
    assert lock_timeout < lock < guard
    assert sql.index("DROP TABLE settings;") < sql.index("SET LOCAL lock_timeout = DEFAULT;")


_COLUMNS = [
    # (name, nullable, server_default) in DDL order (Sec.3.9).
    ("id", False, None),
    ("scope", False, None),
    ("user_id", True, None),
    ("key", False, None),
    ("value", False, None),
    ("value_type", False, None),
    ("is_secret", False, "false"),
    ("updated_by", True, None),
    ("created_at", False, "now()"),
    ("updated_at", False, "now()"),
]


def _default(column: Column[Any]) -> str | None:
    default = column.server_default
    if default is None:
        return None
    assert isinstance(default, DefaultClause)
    return str(default.arg)


def test_models_mirror_the_settings_columns() -> None:
    """The `migrations` job autogenerate-diffs the DB against `db.models.metadata`."""
    t = models.settings
    assert [(c.name, c.nullable, _default(c)) for c in t.columns] == _COLUMNS
    assert [c.name for c in t.primary_key.columns] == ["id"]
    expected = {
        "id": UUID,
        "scope": Text,
        "user_id": UUID,
        "key": Text,
        "value": JSONB,
        "value_type": Text,
        "is_secret": Boolean,
        "updated_by": UUID,
        "created_at": TIMESTAMP,
        "updated_at": TIMESTAMP,
    }
    for name, kind in expected.items():
        assert isinstance(t.c[name].type, kind), name
    for name in ("created_at", "updated_at"):
        stamp = t.c[name].type
        assert isinstance(stamp, TIMESTAMP) and stamp.timezone is True, name


def test_models_mirror_the_foreign_keys_and_their_delete_rules() -> None:
    fks = {
        (fk.parent.name, fk.column.table.name, fk.ondelete) for fk in models.settings.foreign_keys
    }
    assert fks == {("user_id", "users", "CASCADE"), ("updated_by", "users", "SET NULL")}


def test_models_mirror_the_check_and_index_names() -> None:
    t = models.settings
    checks = {str(c.name) for c in t.constraints if isinstance(c, CheckConstraint)}
    # CHECK names get the metadata naming-convention prefix (`ck_<table>_`).
    assert checks == {
        f"ck_settings_{n}" for n in ("st_scope", "st_shape", "st_key_fmt", "st_vtype")
    }
    indexes = {str(ix.name): ix for ix in t.indexes}
    assert set(indexes) == {"ux_settings_sys", "ux_settings_user"}
    sys_ix, user_ix = indexes["ux_settings_sys"], indexes["ux_settings_user"]
    assert sys_ix.unique and [c.name for c in sys_ix.columns] == ["key"]
    assert user_ix.unique and [c.name for c in user_ix.columns] == ["user_id", "key"]
    assert str(sys_ix.dialect_options["postgresql"]["where"]) == "scope = 'system'"
    assert str(user_ix.dialect_options["postgresql"]["where"]) == "scope = 'user'"


def test_models_mirror_the_check_expressions() -> None:
    """`alembic check` never diffs CHECK bodies, so pin them against the SQL here."""
    bodies = {
        str(c.name): " ".join(str(c.sqltext).split())
        for c in models.settings.constraints
        if isinstance(c, CheckConstraint)
    }
    assert bodies == {
        "ck_settings_st_scope": "scope IN ('system','user')",
        "ck_settings_st_shape": "(scope = 'user') = (user_id IS NOT NULL)",
        "ck_settings_st_key_fmt": "key ~ '^[a-z0-9_]+([.][a-z0-9_]+){0,4}$'",
        "ck_settings_st_vtype": "value_type IN ('string','number','boolean','object','array')",
    }
