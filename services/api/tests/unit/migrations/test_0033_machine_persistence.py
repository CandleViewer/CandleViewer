"""`0033_machine_persistence` (E50-T61 #2744): offline render, 24 Sec.17.6 parity, the guards and
grants, the downgrade, the model mirror and the C-5.9 classification.
Real Postgres: `tests/integration/storage/test_machine_persistence_migration.py`."""

from __future__ import annotations

import dataclasses
import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, DOMAIN, JSONB, TIMESTAMP
from sqlalchemy.schema import DefaultClause
from sqlalchemy.types import TypeEngine

from candleviewer.db import models
from candleviewer.statechart.plugins.audit import MachineEventRow

_ROOT = Path(__file__).resolve().parents[3]
_PLAN = _ROOT.parents[1] / "docs" / "plan"
_REV = "0033_machine_persistence"
_NAMES = ("machine_snapshots", "machine_drain_journal", "machine_events")
#: C-5.9 / 21 Sec.12 class P1 (#2744 security notes), byte for byte; every other column is P0.
_P1 = {
    ("machine_snapshots", "snapshot"): "machine context, HMAC-sealed (CV-C53)",
    ("machine_drain_journal", "payload"): "a drained event replayed once after restore",
    ("machine_events", "payload"): "event data, hash-chained (row_hash)",
}
_P1_TEXT = (
    "PII: financial personal data (21 Sec.12, class P1): {}; holds no credential, token or key; "
    "never logged"
)
#: The journal columns `trg_mdj_stamp_once` freezes, in its CASE order; `replayed_at` is set once.
_FROZEN = (
    "machine_kind", "entity_id", "env", "send_id", "lane", "ordinal", "event_type", "payload",
    "receipt_error",
)  # fmt: skip
_SQL_TYPES: dict[type[Any], str] = {
    Text: "text",
    Integer: "int",
    BigInteger: "bigserial",
    JSONB: "jsonb",
    BYTEA: "bytea",
}


@cache
def _prev() -> str:
    """The parent, read from the revision itself, so re-parenting never touches this module."""
    revision = (_ROOT / "candleviewer" / "migrations" / "versions" / f"{_REV}.py").read_text(
        "utf-8"
    )
    found = re.search(r'^down_revision: str \| None = "(\w+)"$', revision, re.M)
    assert found is not None
    return found[1]


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#2744)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments, collapse whitespace and the space after `(`, so layout never matters."""
    return " ".join(re.sub(r"--[^\n]*", "", sql).split()).replace("( ", "(")


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", f"{_prev()}:{_REV}", "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", f"{_REV}:{_prev()}", "--sql"))


@cache
def _section() -> str:
    """24-internal-schemas.md Sec.17.6, to the next heading."""
    text = (_PLAN / "24-internal-schemas.md").read_text(encoding="utf-8")
    return text.split("\n### 17.6 ", 1)[1].split("\n## ", 1)[0]


def _doc_ddl() -> str:
    """The section's ```sql block: the three tables and their indexes."""
    return _section().split("```sql", 1)[1].split("```", 1)[0]


def _doc_table(name: str) -> str:
    return _doc_ddl().split(f"CREATE TABLE {name} (", 1)[1].split("\n);", 1)[0]


def _table(name: str) -> Table:
    table = getattr(models, name)
    assert isinstance(table, Table)
    return table


def _in_order(sql: str, steps: list[str]) -> bool:
    missing = [step for step in steps if step not in sql]
    assert not missing, f"not in the rendered SQL: {missing}"
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def _sql_type(t: TypeEngine[Any]) -> str:
    if isinstance(t, DOMAIN):
        return str(t.name)
    if isinstance(t, ARRAY):
        return _sql_type(t.item_type) + "[]"
    if isinstance(t, TIMESTAMP):
        assert t.timezone
        return "timestamptz"
    return _SQL_TYPES[type(t)]


def _default(column: Column[Any]) -> str | None:
    default = column.server_default
    if default is None:
        return None
    assert isinstance(default, DefaultClause)
    return str(default.arg)


def _doc_columns(name: str) -> list[tuple[str, str, bool, str | None]]:
    """`(name, type, nullable, server default)` for every column line of the section's table."""
    columns = []
    for line in _doc_table(name).splitlines():
        found = re.match(r"  ([a-z][a-z0-9_]*) +([a-z0-9_]+(?:\[\])?)", line)
        if found is None:  # PRIMARY KEY and CONSTRAINT lines
            continue
        ddl = line.split("--", 1)[0].strip().rstrip(",")
        default = re.search(r"DEFAULT (\S+)", ddl)
        nullable = "NOT NULL" not in ddl and "PRIMARY KEY" not in ddl
        columns.append((found[1], found[2], nullable, default[1] if default else None))
    return columns


def test_revision_chains_onto_its_parent_as_its_only_child() -> None:
    """The parent comes from `down_revision`, so re-parenting never touches this module; nothing
    else branches off it (the tip-agnostic single-head check is `test_single_head.py`)."""
    parent = _prev()
    assert re.fullmatch(r"\d{4}_\w+", parent) and parent < _REV
    children = re.findall(rf"^{parent} -> (\w+)", _alembic("history", "-r", f"{parent}:"), re.M)
    assert children == [_REV]


def test_upgrade_is_the_section_ddl_verbatim_under_a_bounded_lock_wait() -> None:
    """24 Sec.17.6 is implementable as written: its ```sql block, comments aside, is the render."""
    assert _in_order(
        _up(),
        [
            "SET LOCAL lock_timeout = '5s';",
            _norm(_doc_ddl()),
            "CREATE FUNCTION machine_drain_journal_stamp_once()",
            "DO $BODY$",
            "COMMENT ON COLUMN machine_snapshots.machine_kind IS",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )


def test_upgrade_creates_only_its_own_objects() -> None:
    """`sha256_hex`, `forbid_mutation()` and `audit_refuse_truncate()` are reused, not redefined."""
    up = _up()
    counts = [
        up.count(f"CREATE {kind} ")
        for kind in ("TABLE", "INDEX", "UNIQUE INDEX", "TRIGGER", "FUNCTION", "DOMAIN", "TYPE")
    ]
    assert counts == [3, 2, 0, 3, 1, 0, 0] and up.count("COMMENT ON COLUMN ") == 12 + 10 + 14
    for absent in ("CREATE OR REPLACE", "IF NOT EXISTS", "INSERT INTO", "audit_log", "DROP "):
        assert absent not in up


def test_machine_events_carries_the_audit_log_guards() -> None:
    """C-2.9 / C-5.7: the 0003 row and TRUNCATE triggers, on the shared functions."""
    up = _up()
    assert (
        "CREATE TRIGGER trg_me_append BEFORE UPDATE OR DELETE ON machine_events "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation();"
    ) in up
    assert (
        "CREATE TRIGGER trg_me_no_truncate BEFORE TRUNCATE ON machine_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();"
    ) in up


def _guarded(role: str, *statements: str) -> str:
    executes = " ".join(f"EXECUTE '{statement}';" for statement in statements)
    return f"IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN {executes} END IF;"


def test_grants_are_the_section_table_and_each_runs_only_where_its_role_exists() -> None:
    """24 Sec.17.6 "Privileges and triggers": narrowings of the `pg_bootstrap.sql` defaults; the
    one GRANT gives `cv_app` back `replayed_at` alone, and nothing grants UPDATE or DELETE on
    `machine_events` (C-5.7)."""
    up = _up()
    app = _guarded(
        "cv_app",
        "REVOKE DELETE, TRUNCATE ON machine_snapshots FROM cv_app",
        "REVOKE UPDATE, DELETE, TRUNCATE ON machine_drain_journal FROM cv_app",
        "GRANT UPDATE (replayed_at) ON machine_drain_journal TO cv_app",
        "REVOKE UPDATE, DELETE, TRUNCATE ON machine_events FROM cv_app",
    )
    ro = _guarded("cv_ro", "REVOKE UPDATE, DELETE, TRUNCATE ON machine_events FROM cv_ro")
    assert f"DO $BODY$ BEGIN {app} {ro} END $BODY$;" in up
    assert (up.count("REVOKE "), up.count("GRANT ")) == (4, 1)


def test_the_journal_guard_freezes_every_column_but_replayed_at_which_is_set_once() -> None:
    """The 0024/0032 write-once pattern: pinned `search_path`, `ENABLE ALWAYS`, one CASE arm per
    column in table order, and a refusal naming the column and its rule, never a value."""
    up = _up()
    assert _in_order(
        up,
        [
            "CREATE FUNCTION machine_drain_journal_stamp_once() RETURNS trigger LANGUAGE plpgsql "
            "SET search_path = pg_catalog, pg_temp AS $BODY$",
            "CREATE TRIGGER trg_mdj_stamp_once BEFORE UPDATE ON machine_drain_journal "
            "FOR EACH ROW EXECUTE FUNCTION machine_drain_journal_stamp_once();",
            "ALTER TABLE machine_drain_journal ENABLE ALWAYS TRIGGER trg_mdj_stamp_once;",
        ],
    )
    found = re.search(r"changed := CASE WHEN (.+?) END;", up)
    assert found is not None
    arms = [f"NEW.{c} IS DISTINCT FROM OLD.{c} THEN '{c}'" for c in _FROZEN]
    arms.append(
        "OLD.replayed_at IS NOT NULL AND NEW.replayed_at IS DISTINCT FROM OLD.replayed_at "
        "THEN 'replayed_at'"
    )
    assert found[1].split(" WHEN ") == arms
    assert [c.name for c in _table("machine_drain_journal").columns] == [*_FROZEN, "replayed_at"]
    assert re.findall(r"RAISE EXCEPTION (.+? USING ERRCODE = '\w+');", up) == [
        "'trg_mdj_stamp_once: machine_drain_journal.% is %', changed, CASE WHEN changed = "
        "'replayed_at' THEN 'set-once' ELSE 'write-once' END USING ERRCODE = 'check_violation'"
    ]


def test_downgrade_refuses_naming_each_populated_table_then_drops_only_its_own_objects() -> None:
    """C-5.2 / C-5.7: audit history and recovery state are never dropped; the shared functions
    and the domain stay."""
    down = _down()
    guards = re.findall(
        r"IF EXISTS \(SELECT 1 FROM (\w+)\) THEN RAISE EXCEPTION "
        r"'0033_machine_persistence downgrade refused: (\w+) holds rows;",
        down,
    )
    assert guards == [(name, name) for name in _NAMES]  # each names the table it found populated
    drops = [f"DROP TABLE {name};" for name in reversed(_NAMES)]
    assert _in_order(
        down,
        [
            "SET LOCAL lock_timeout = '5s';",
            "LOCK TABLE machine_snapshots, machine_drain_journal, machine_events IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM machine_snapshots) THEN",
            *drops,
            "DROP FUNCTION machine_drain_journal_stamp_once();",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )
    assert down.count("DROP ") == 4 and down.count("RAISE EXCEPTION") == 3
    for shared in ("forbid_mutation", "audit_refuse_truncate", "sha256_hex", "GRANT", "REVOKE"):
        assert shared not in down


@pytest.mark.parametrize("name", _NAMES)
def test_models_mirror_the_section_columns(name: str) -> None:
    """`alembic check` diffs the database against `db.models`; names, types, nullability and
    server defaults are pinned against the section here."""
    got = [(c.name, _sql_type(c.type), bool(c.nullable), _default(c)) for c in _table(name).columns]
    assert got == _doc_columns(name)


@pytest.mark.parametrize("name", _NAMES)
def test_models_mirror_the_named_checks(name: str) -> None:
    """`alembic check` never diffs CHECK bodies, so they are pinned against the section here."""
    checks = {
        str(c.name).removeprefix(f"ck_{name}_"): " ".join(str(c.sqltext).split())
        for c in _table(name).constraints
        if isinstance(c, CheckConstraint)
    }
    assert checks == dict(
        re.findall(r"CONSTRAINT (\w+) +CHECK \((.*)\),?$", _doc_table(name), re.M)
    )


def _create_index(ix: Index) -> str:
    assert ix.table is not None
    columns = ", ".join(str(e).removeprefix(f"{ix.table.name}.") for e in ix.expressions)
    where = ix.dialect_options["postgresql"]["where"]
    tail = "" if where is None else f" WHERE {where}"
    return f"CREATE INDEX {ix.name} ON {ix.table.name} ({columns}){tail};"


def test_models_mirror_the_keys_and_indexes() -> None:
    tables = [_table(name) for name in _NAMES]
    keys = {t.name: [c.name for c in t.primary_key.columns] for t in tables}
    for name, columns in keys.items():
        assert f"PRIMARY KEY ({', '.join(columns)})" in _doc_table(name) or columns == ["seq"]
    assert keys["machine_events"] == ["seq"] and "(seq bigserial PRIMARY KEY," in _up()
    uniques = [
        (str(c.name), [col.name for col in c.columns])
        for t in tables
        for c in t.constraints
        if isinstance(c, UniqueConstraint)
    ]
    assert uniques == [("machine_events_row_hash_key", ["row_hash"])]  # Postgres's own name
    assert " row_hash sha256_hex NOT NULL UNIQUE," in _up()
    indexes = [_create_index(ix) for t in tables for ix in sorted(t.indexes, key=str)]
    assert len(indexes) == 2 and all(statement in _up() for statement in indexes), indexes


def test_every_machine_event_row_field_has_a_column_of_the_stated_type() -> None:
    """Gherkin "24 Sec.17.6 is implementable as written": the section's type mapping covers every
    `MachineEventRow` field, and each maps to the same-named `machine_events` column."""
    prose = " ".join(_section().split())
    sentence = prose.split("Type mapping from `MachineEventRow`: ", 1)[1].split(". ", 1)[0]
    stated = {
        field: sql_type
        for names, sql_type in re.findall(
            r"((?:`\w+`(?:, and |, | and )?)+) \([^)]*\) to `([^`]+)`", sentence
        )
        for field in re.findall(r"`(\w+)`", names)
    }
    fields = {f.name for f in dataclasses.fields(MachineEventRow)}
    columns = {c.name: _sql_type(c.type) for c in _table("machine_events").columns}
    assert set(stated) == fields and set(columns) == fields | {"seq"}
    assert {field: columns[field] for field in fields} == stated


def test_every_column_is_classified_in_the_render_and_the_models_alike() -> None:
    """C-5.9: every column carries a comment starting with its class tag; the three P1 columns
    carry the #2744 texts; nothing is class S. `alembic check` diffs the comments themselves."""
    up = _up()
    for name in _NAMES:
        for column in _table(name).columns:
            comment = column.comment
            assert comment is not None and "'" not in comment, (name, column.name)
            p1 = _P1.get((name, column.name))
            assert comment == _P1_TEXT.format(p1) if p1 else comment.startswith("P0: ")
            assert f"COMMENT ON COLUMN {name}.{column.name} IS '{comment}';" in up


def test_21_section_12_has_a_row_for_every_class_bearing_column() -> None:
    """21 Sec.12 lists each P1 column of the three tables; its Enforcement list introduces the
    `P0:` tag that every other column of them carries."""
    text = (_PLAN / "21-database-schema.md").read_text(encoding="utf-8")
    section = text.split("\n## 12. ", 1)[1].split("\n## 13. ", 1)[0]
    rows = re.findall(r"^\| `(machine_\w+)` +\| `(\w+)` +\| (\S+) +\|", section, re.M)
    assert sorted(rows) == sorted((table, column, "P1") for table, column in _P1)
    assert "`P0:`" in section.split("Enforcement:", 1)[1]


@pytest.mark.parametrize("name", _NAMES)
def test_a_later_migration_naming_a_machine_table_is_flagged_for_security_review(
    tmp_path: Path, name: str
) -> None:
    """CI-MIG-006 lists the three tables (`tools/ci/security-sensitive-tables.txt`): audit-class
    storage and signed state, so a revision that alters one raises the security-review flag."""
    later = tmp_path / "0099_later.py"
    later.write_text(f'op.add_column("{name}", sa.Column("note", sa.Text()))\n', encoding="utf-8")
    lint = _ROOT.parents[1] / "tools" / "ci" / "migration_lint.py"
    r = subprocess.run(  # noqa: S603 -- fixed argv, the repo's own lint script, no shell (#2744)
        [sys.executable, str(lint), "--versions-dir", str(tmp_path)],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert f"WARN CI-MIG-006: {later}: touches security-sensitive table '{name}'" in r.stderr
