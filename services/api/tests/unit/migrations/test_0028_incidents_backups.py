"""`0028_incidents_backups` (E42-T05 #966): offline render, plan-doc parity, models, classification.
Real Postgres: `tests/integration/storage/test_incidents_backups_migration.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import CheckConstraint, Column, Index, Table
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.schema import DefaultClause

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0028_incidents_backups", "0027_feature_flags"
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"
_KINDS = ("pg_basebackup", "pg_dump", "questdb_snapshot", "parquet_sync", "config_bundle")
_STATUSES = ("running", "ok", "failed", "verified", "restored")


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
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


def _doc_block(heading: str) -> str:
    """The first ```sql block after `heading` in 21-database-schema.md, to its fence."""
    section = _DOC.read_text(encoding="utf-8").split(heading, 1)[1]
    return section.split("```sql", 1)[1].split("```", 1)[0]


def _in_order(sql: str, steps: list[str]) -> bool:
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def test_revision_chains_onto_0027() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", _UP)


def test_upgrade_creates_both_types_as_the_plan_doc_declares_them() -> None:
    doc = _norm(_DOC.read_text(encoding="utf-8"))
    for name, values in (("backup_kind", _KINDS), ("backup_status", _STATUSES)):
        enum = f"CREATE TYPE {name} AS ENUM ({','.join(repr(v) for v in values)});"
        assert enum in doc and enum in _up(), name


def test_upgrade_ddl_is_the_plan_doc_ddl_verbatim() -> None:
    incidents = _norm(_doc_block("#### 3.10.2a `incidents`"))
    backups = _norm(_doc_block("#### 3.10.3 `backups`"))
    assert incidents.startswith("CREATE TABLE incidents (")
    assert backups.startswith("CREATE TABLE backups (")
    assert incidents in _up() and backups in _up()


def test_upgrade_ships_only_these_tables_and_types() -> None:
    sql = _up()
    assert sql.count("CREATE TABLE ") == 2 and sql.count("CREATE TYPE ") == 2
    assert sql.count("CREATE UNIQUE INDEX ") == 1 and sql.count("CREATE INDEX ") == 4
    for absent in ("INSERT INTO", "CREATE TRIGGER", "GRANT ", "REVOKE ", "TABLE feature_flag"):
        assert absent not in sql


def test_upgrade_tags_encryption_ref_as_secret_per_classification() -> None:
    """C-5.9 / 21 Sec.12: `backups.encryption_ref` is class S; the comment is the declaration and
    the model mirrors it verbatim (`alembic check` diffs column comments too)."""
    comment = models.backups.c.encryption_ref.comment
    assert comment is not None and comment.startswith("SECRET:")
    assert f"COMMENT ON COLUMN backups.encryption_ref IS '{comment}';" in _up()
    assert [c.name for c in models.backups.columns if c.comment] == ["encryption_ref"]
    assert not [c.name for c in models.incidents.columns if c.comment]


def test_upgrade_bounds_every_lock_with_lock_timeout() -> None:
    assert _in_order(
        _up(),
        [
            "SET LOCAL lock_timeout = '5s';",
            "CREATE TYPE backup_kind",
            "CREATE TABLE incidents (",
            "CREATE TABLE backups (",
            "COMMENT ON COLUMN backups.encryption_ref",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )


def test_downgrade_locks_refuses_while_populated_then_drops_tables_then_types() -> None:
    assert _in_order(
        _down(),
        [
            "SET LOCAL lock_timeout = '5s';",
            "LOCK TABLE incidents, backups IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM incidents) OR EXISTS (SELECT 1 FROM backups) THEN",
            "RAISE EXCEPTION '0028_incidents_backups downgrade refused",
            "DROP TABLE backups;",
            "DROP TABLE incidents;",
            "DROP TYPE backup_status;",
            "DROP TYPE backup_kind;",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )


def _default(column: Column[Any]) -> str | None:
    default = column.server_default
    if default is None:
        return None
    assert isinstance(default, DefaultClause)
    return str(default.arg)


def _doc_columns(heading: str) -> list[tuple[str, bool, str | None]]:
    """`(name, nullable, server default)` for every column line of the doc's ```sql block."""
    columns: list[tuple[str, bool, str | None]] = []
    for line in _doc_block(heading).splitlines():
        ddl = line.split("--", 1)[0].strip()
        if not line.startswith("  ") or ddl.startswith("CONSTRAINT"):
            continue
        default = re.search(r"DEFAULT (\S+?),?$", ddl)
        nullable = "NOT NULL" not in ddl and "PRIMARY KEY" not in ddl
        columns.append((ddl.split()[0], nullable, default[1] if default else None))
    return columns


@pytest.mark.parametrize(
    ("table", "heading"),
    [
        (models.incidents, "#### 3.10.2a `incidents`"),
        (models.backups, "#### 3.10.3 `backups`"),
    ],
)
def test_models_mirror_the_doc_columns(table: Table, heading: str) -> None:
    """The `migrations` job autogenerate-diffs the DB against `db.models.metadata`; names,
    nullability and server defaults are pinned against the plan doc here."""
    assert [(c.name, bool(c.nullable), _default(c)) for c in table.columns] == _doc_columns(heading)


def test_models_use_the_types_the_migration_owns() -> None:
    assert models.incidents.c.severity.type is models.severity
    for name, values in (("kind", _KINDS), ("status", _STATUSES)):
        enum = models.backups.c[name].type
        assert isinstance(enum, ENUM) and tuple(enum.enums) == values
        assert enum.create_type is False  # the migration creates and drops it


def test_models_mirror_the_foreign_keys_and_their_delete_rules() -> None:
    def fks(table: Table) -> set[tuple[str, str, str | None]]:
        return {(fk.parent.name, fk.column.table.name, fk.ondelete) for fk in table.foreign_keys}

    assert fks(models.incidents) == {("acknowledged_by", "users", "SET NULL")}
    assert fks(models.backups) == {("triggered_by_user", "users", "SET NULL")}


def _checks(table: Table) -> dict[str, str]:
    """`alembic check` never diffs CHECK bodies, so they are pinned against the SQL here."""
    return {
        str(c.name).removeprefix(f"ck_{table.name}_"): " ".join(str(c.sqltext).split())
        for c in table.constraints
        if isinstance(c, CheckConstraint)
    }


def test_models_mirror_the_check_constraints() -> None:
    for table in (models.incidents, models.backups):
        for name, body in _checks(table).items():
            assert f"CONSTRAINT {name} CHECK ({body})" in _up(), name
    incident_checks = "signature severity status count seen ack resolved".split()
    assert set(_checks(models.incidents)) == {f"inc_{n}" for n in incident_checks}
    assert set(_checks(models.backups)) == {"bk_trigger", "bk_verify"}


def _create_index(ix: Index) -> str:
    """The `CREATE INDEX` statement a model index stands for, in the migration's spelling."""
    assert ix.table is not None
    columns = ", ".join(str(e).removeprefix(f"{ix.table.name}.") for e in ix.expressions)
    where = ix.dialect_options["postgresql"]["where"]
    tail = "" if where is None else f" WHERE {where}"
    unique = "UNIQUE " if ix.unique else ""
    return f"CREATE {unique}INDEX {ix.name} ON {ix.table.name} ({columns}){tail};"


def test_models_mirror_the_indexes() -> None:
    for table, count in ((models.incidents, 3), (models.backups, 2)):
        assert len(table.indexes) == count
        for ix in table.indexes:
            assert _create_index(ix) in _up(), ix.name
