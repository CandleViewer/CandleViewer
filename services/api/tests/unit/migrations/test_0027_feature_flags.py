"""`0027_feature_flags` (E42-T03 #964): offline render, plan-doc parity, models.

Real-Postgres behaviour (named-constraint rejection, key regex, override uniqueness, delete rules,
catalog parity, round trip, lock bounds) is covered by
`tests/integration/storage/test_feature_flags_migration.py`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Column, SmallInteger, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TIMESTAMP, UUID
from sqlalchemy.schema import DefaultClause

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0027_feature_flags", "0026_kek_versions_env"
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"
_KINDS = ("boolean", "percentage", "variant")


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#964)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments and collapse whitespace so layout never matters."""
    return " ".join(re.sub(r"--[^\n]*", "", sql).split())


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", _UP, "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", _DOWN, "--sql"))


def _doc_ddl() -> str:
    """Sec.3.9's second ```sql block (the two flag tables and both indexes), to its fence."""
    section = _DOC.read_text(encoding="utf-8").split("### 3.9 Settings & feature flags", 1)[1]
    return section.split("```sql", 2)[2].split("```", 1)[0]


def test_revision_chains_onto_0026() -> None:
    history = _alembic("history", "-r", _UP)
    assert f"{_PREV} -> {_REV}" in history, f"0027 must revise 0026, got: {history}"


def test_upgrade_creates_flag_kind_as_the_plan_doc_declares_it() -> None:
    enum = f"CREATE TYPE flag_kind AS ENUM ({','.join(repr(k) for k in _KINDS)});"
    assert enum in _norm(_DOC.read_text(encoding="utf-8")), "Sec.1.2 must declare flag_kind"
    sql = _up()
    assert enum in sql, "the upgrade must create flag_kind with Sec.1.2's values, in order"
    assert sql.index(enum) < sql.index("CREATE TABLE feature_flags ("), "the type precedes its use"


def test_upgrade_ddl_is_the_plan_doc_ddl_verbatim() -> None:
    doc = _norm(_doc_ddl())
    assert doc.startswith("CREATE TABLE feature_flags ("), "Sec.3.9's flag DDL block moved"
    assert doc.endswith("(feature_flag_id, role_id) WHERE role_id IS NOT NULL;"), "block cut short"
    assert doc in _up(), "the upgrade DDL has drifted from Sec.3.9 (comments and layout aside)"


def test_upgrade_ships_only_the_flag_tables() -> None:
    """Nothing beyond Sec.3.9's flag DDL: no seed, trigger, grant or classification comment."""
    sql = _up()
    assert sql.count("CREATE TABLE ") == 2 and sql.count("CREATE TYPE ") == 1, "tables or types"
    assert sql.count("CREATE UNIQUE INDEX ") == 2 and sql.count("CREATE INDEX ") == 0, "indexes"
    for absent in ("settings", "INSERT INTO", "CREATE TRIGGER", "GRANT ", "REVOKE ", "COMMENT ON"):
        assert absent not in sql, f"{absent!r} is outside this revision's scope"


def test_upgrade_bounds_every_lock_with_lock_timeout() -> None:
    """C-5.6: the FKs lock `users` and `roles`; every statement sits inside a 5 s bound."""
    sql = _up()
    assert sql.index("SET LOCAL lock_timeout = '5s';") < sql.index("CREATE TYPE flag_kind"), "opens"
    assert sql.rindex("CREATE UNIQUE INDEX ux_ffo_role") < sql.index(
        "SET LOCAL lock_timeout = DEFAULT;"
    ), "the bound must stay open until the last index is built"


def test_downgrade_locks_refuses_while_populated_then_drops_children_first() -> None:
    sql = _down()
    steps = [
        "SET LOCAL lock_timeout = '5s';",
        "LOCK TABLE feature_flags, feature_flag_overrides IN SHARE MODE;",
        "IF EXISTS (SELECT 1 FROM feature_flags) OR EXISTS (SELECT 1 FROM feature_flag_overrides)",
        "RAISE EXCEPTION '0027_feature_flags downgrade refused",
        "Export the overrides you want to keep",
        "run DELETE FROM feature_flags (it cascades to the overrides) and retry",
        "DROP TABLE feature_flag_overrides;",
        "DROP TABLE feature_flags;",
        "DROP TYPE flag_kind;",
        "SET LOCAL lock_timeout = DEFAULT;",
    ]
    positions = [sql.index(step) for step in steps]
    order = dict(zip(steps, positions, strict=True))
    assert positions == sorted(positions), f"steps out of order: {order}"


def _default(column: Column[Any]) -> str | None:
    default = column.server_default
    if default is None:
        return None
    assert isinstance(default, DefaultClause)
    return str(default.arg)


_FLAG_COLUMNS = [
    # (name, nullable, server_default, type) in DDL order (Sec.3.9).
    ("id", False, None, UUID),
    ("key", False, None, Text),
    ("kind", False, "'boolean'", ENUM),
    ("description", False, "''", Text),
    ("default_value", False, "'false'::jsonb", JSONB),
    ("rollout_pct", True, None, SmallInteger),
    ("variants", True, None, JSONB),
    ("is_killswitch", False, "false", Boolean),
    ("owner_team", False, "'platform'", Text),
    ("expires_at", True, None, TIMESTAMP),
    ("updated_by", True, None, UUID),  # added before merge (E42-T03 review), in Sec.3.9 too
    ("created_at", False, "now()", TIMESTAMP),
    ("updated_at", False, "now()", TIMESTAMP),
]
_OVERRIDE_COLUMNS = [
    ("id", False, None, UUID),
    ("feature_flag_id", False, None, UUID),
    ("user_id", True, None, UUID),
    ("role_id", True, None, UUID),
    ("value", False, None, JSONB),
    ("reason", False, "''", Text),
    ("set_by", True, None, UUID),
    ("expires_at", True, None, TIMESTAMP),
    ("created_at", False, "now()", TIMESTAMP),
]


def test_models_mirror_the_columns_of_both_tables() -> None:
    """The `migrations` job autogenerate-diffs the DB against `db.models.metadata`."""
    for table, columns in (
        (models.feature_flags, _FLAG_COLUMNS),
        (models.feature_flag_overrides, _OVERRIDE_COLUMNS),
    ):
        assert [(c.name, c.nullable, _default(c)) for c in table.columns] == [
            (name, nullable, default) for name, nullable, default, _ in columns
        ]
        assert [c.name for c in table.primary_key.columns] == ["id"]
        for name, _, _, kind in columns:
            column_type = table.c[name].type
            assert isinstance(column_type, kind), name
            if isinstance(column_type, TIMESTAMP):
                assert column_type.timezone is True, name
    enum = models.feature_flags.c.kind.type
    assert isinstance(enum, ENUM) and enum.name == "flag_kind" and tuple(enum.enums) == _KINDS
    assert enum.create_type is False  # the migration owns the type


def test_models_mirror_the_foreign_keys_and_their_delete_rules() -> None:
    fks = {
        (fk.parent.name, fk.column.table.name, fk.ondelete)
        for fk in models.feature_flag_overrides.foreign_keys
    }
    assert fks == {
        ("feature_flag_id", "feature_flags", "CASCADE"),
        ("user_id", "users", "CASCADE"),
        ("role_id", "roles", "CASCADE"),
        ("set_by", "users", "SET NULL"),
    }
    flag_fks = {
        (fk.parent.name, fk.column.table.name, fk.ondelete)
        for fk in models.feature_flags.foreign_keys
    }
    assert flag_fks == {("updated_by", "users", "SET NULL")}


def _checks(table: Any) -> dict[str, str]:
    """`alembic check` never diffs CHECK bodies, so they are pinned against the SQL here."""
    return {
        str(c.name): " ".join(str(c.sqltext).split())
        for c in table.constraints
        if isinstance(c, CheckConstraint)
    }


def test_models_mirror_the_constraints_and_indexes() -> None:
    # CHECK names get the metadata naming-convention prefix (`ck_<table>_`).
    assert _checks(models.feature_flags) == {
        "ck_feature_flags_ff_key": "key ~ '^[a-z0-9_]+([.][a-z0-9_]+){0,3}$'",
        "ck_feature_flags_ff_pct": "rollout_pct IS NULL OR rollout_pct BETWEEN 0 AND 100",
        "ck_feature_flags_ff_shape": "(kind <> 'percentage' OR rollout_pct IS NOT NULL) "
        "AND (kind <> 'variant' OR variants IS NOT NULL)",
    }
    assert _checks(models.feature_flag_overrides) == {
        "ck_feature_flag_overrides_ffo_target": "num_nonnulls(user_id, role_id) = 1"
    }
    uniques = [c for c in models.feature_flags.constraints if isinstance(c, UniqueConstraint)]
    # Postgres's own name for the inline `key ... UNIQUE`, so autogenerate sees no rename.
    assert [(str(c.name), [col.name for col in c.columns]) for c in uniques] == [
        ("feature_flags_key_key", ["key"])
    ]
    assert not models.feature_flags.indexes
    indexes = {str(ix.name): ix for ix in models.feature_flag_overrides.indexes}
    assert set(indexes) == {"ux_ffo_user", "ux_ffo_role"}
    for name, target in (("ux_ffo_user", "user_id"), ("ux_ffo_role", "role_id")):
        ix = indexes[name]
        assert ix.unique and [c.name for c in ix.columns] == ["feature_flag_id", target]
        assert str(ix.dialect_options["postgresql"]["where"]) == f"{target} IS NOT NULL"
