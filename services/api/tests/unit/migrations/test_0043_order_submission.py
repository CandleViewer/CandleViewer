"""`0043_order_submission` (E29-T04 #913, slice 2a): offline render, plan-doc parity, the guards,
the TRUNCATE triggers, the grants, the PII comments, the downgrade guard and the model mirror.
Real Postgres: `tests/integration/storage/test_order_submission_migration.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import CheckConstraint, Column, Index, Numeric, Table, UniqueConstraint
from sqlalchemy.schema import DefaultClause

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0043_order_submission", "0046_audit_signing_keys"
_ORDERS = "3.3.4 `orders`"
_ANCHORS = "3.3.10 `idempotency_anchors`"
_STOPS = "3.3.11 `recorded_stops`"
#: (heading, n-th ```sql block, the number of blocks the section holds): the revision's blocks.
_BLOCKS = ((_ORDERS, 2, 4), (_ANCHORS, 0, 3), (_ANCHORS, 1, 3), (_STOPS, 0, 2), (_STOPS, 1, 2))
_BLOCK_IDS = ["provenance", "anchors", "anchor-guard", "stops", "stop-guard"]
_TABLES = {t.name: t for t in (models.idempotency_anchors, models.recorded_stops)}
#: What a later revision changed in a table this one creates, pinned by that revision's own test:
#: `0052_ia_purge_anchor` (`test_0052_ia_purge_anchor.py`, Sec.3.3.10's third block) adds
#: `before_us` and `ia_bound` and replaces `ia_operation`.
_LATER_COLUMNS: dict[str, frozenset[str]] = {"idempotency_anchors": frozenset({"before_us"})}
_LATER_CHECKS: dict[str, frozenset[str]] = {"idempotency_anchors": frozenset({"ia_bound"})}
_REPLACED_CHECKS: dict[str, frozenset[str]] = {"idempotency_anchors": frozenset({"ia_operation"})}
#: (function, trigger, table) of each guard, in the order the revision creates them.
_GUARDS = (
    ("ia_write_once", "trg_ia_write_once", "idempotency_anchors"),
    ("rs_guard", "trg_rs_guard", "recorded_stops"),
)
_TRUNCATE = (
    ("trg_ia_no_truncate", "idempotency_anchors"),
    ("trg_rs_no_truncate", "recorded_stops"),
)
_LOCK_ON, _LOCK_OFF = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
_DDL = re.compile(r"\b(?:CREATE|ALTER|DROP|DO|COMMENT|REVOKE|LOCK)\b")


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#913)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments, collapse whitespace and the space inside a bracket, and fold the `;`
    alembic appends to a statement that has one, so neither layout nor the split of a block over
    two `op.execute` calls matters."""
    flat = " ".join(re.sub(r"--[^\n]*", "", sql).split())
    return flat.replace("( ", "(").replace(" )", ")").replace(";;", ";")


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", f"{_PREV}:{_REV}", "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", f"{_REV}:{_PREV}", "--sql"))


@cache
def _section(heading: str) -> str:
    section = _DOC.read_text(encoding="utf-8").split(f"#### {heading}", 1)[1]
    return re.split(r"\n#{1,4} ", section, maxsplit=1)[0]


def _doc_block(heading: str, index: int) -> str:
    return _section(heading).split("```sql")[index + 1].split("```", 1)[0]


def _doc_table(name: str) -> str:
    heading = _ANCHORS if name == "idempotency_anchors" else _STOPS
    return _doc_block(heading, 0).split(f"CREATE TABLE {name} (", 1)[1].split("\n);", 1)[0]


def _in_order(sql: str, steps: list[str]) -> bool:
    missing = [step for step in steps if step not in sql]
    assert not missing, f"not in the rendered SQL: {missing}"
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def _function(name: str) -> str:
    return _up().split(f"CREATE FUNCTION {name}() ", 1)[1].split("END $BODY$;", 1)[0]


def test_revision_chains_onto_its_parent() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")


@pytest.mark.parametrize(("heading", "count"), [(_ORDERS, 4), (_ANCHORS, 3), (_STOPS, 2)])
def test_each_section_holds_the_fences_the_parity_test_walks(heading: str, count: int) -> None:
    """The verbatim test walks the fences by index: one more would go unchecked."""
    assert _section(heading).count("```sql") == count


@pytest.mark.parametrize(("heading", "index", "count"), _BLOCKS, ids=_BLOCK_IDS)
def test_upgrade_ddl_is_the_plan_doc_ddl_verbatim(heading: str, index: int, count: int) -> None:
    assert _section(heading).count("```sql") == count
    assert _norm(_doc_block(heading, index)) in _up()


def test_upgrade_creates_in_dependency_order_under_a_bounded_lock_wait() -> None:
    """The column before the tables, each table before its guard and its TRUNCATE trigger (one
    block each, as 21 has them), then the grants and the comments."""
    assert _in_order(
        _up(),
        [
            _LOCK_ON,
            "ALTER TABLE orders ADD COLUMN provenance ",
            "CREATE TABLE idempotency_anchors (",
            "CREATE FUNCTION ia_write_once()",
            "ALTER TABLE idempotency_anchors ENABLE ALWAYS TRIGGER trg_ia_write_once; "
            "CREATE TRIGGER trg_ia_no_truncate BEFORE TRUNCATE ON idempotency_anchors ",
            "CREATE TABLE recorded_stops (",
            "CREATE FUNCTION rs_guard()",
            "CREATE TRIGGER trg_rs_no_truncate",
            "REVOKE DELETE, TRUNCATE ON idempotency_anchors, recorded_stops FROM cv_app",
            "COMMENT ON COLUMN recorded_stops.trigger_price",
            _LOCK_OFF,
        ],
    )


@pytest.mark.parametrize("render", [_up, _down], ids=["upgrade", "downgrade"])
def test_nothing_changes_the_schema_outside_the_lock_timeout_bracket(
    render: Callable[[], str],
) -> None:
    sql = render()
    assert sql.count("SET LOCAL lock_timeout") == 2
    assert not _DDL.search(sql.split(_LOCK_ON, 1)[0])
    assert not _DDL.search(sql.split(_LOCK_OFF, 1)[1])


def test_upgrade_ships_only_these_objects() -> None:
    sql = _up()
    assert sql.count("CREATE TABLE ") == 2 and sql.count("CREATE FUNCTION ") == 2
    assert sql.count("CREATE UNIQUE INDEX ") == 2 and sql.count("CREATE INDEX ") == 3
    assert sql.count("CREATE TRIGGER ") == 4 and sql.count("ENABLE ALWAYS TRIGGER ") == 4
    assert sql.count("COMMENT ON COLUMN ") == 6 and sql.count("REVOKE ") == 2
    assert sql.count("ALTER TABLE orders ADD ") == 2
    for absent in ("GRANT ", "IF NOT EXISTS", "DROP ", "INSERT INTO ", "SECURITY DEFINER"):
        assert absent not in sql


@pytest.mark.parametrize(("function", "trigger", "table"), _GUARDS, ids=[g[1] for g in _GUARDS])
def test_each_guard_fires_before_update_always_and_pins_its_search_path(
    function: str, trigger: str, table: str
) -> None:
    head = f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql "
    assert f"{head}SET search_path = pg_catalog, pg_temp AS $BODY$ " in _up()
    create = (
        f"CREATE TRIGGER {trigger} BEFORE UPDATE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {function}();"
    )
    assert _in_order(_up(), [create, f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {trigger};"])


@pytest.mark.parametrize(("function", "trigger", "table"), _GUARDS, ids=[g[1] for g in _GUARDS])
def test_each_guard_reads_only_its_own_columns_and_hands_the_row_back(
    function: str, trigger: str, table: str
) -> None:
    """plpgsql resolves `NEW.x` only when the trigger first fires, so a typo would survive
    CREATE FUNCTION; a BEFORE ROW trigger that returns NULL silently drops the write."""
    body = _function(function)
    own = {c.name for c in _TABLES[table].columns}
    assert {c for c in re.findall(r"\b(?:NEW|OLD)\.(\w+)", body) if c not in own} == set()
    assert body.count("RETURN ") == 1 and body.rstrip().endswith("RETURN NEW;")
    assert "FROM " not in body.replace("IS DISTINCT FROM", "")  # reads no other table


@pytest.mark.parametrize(("function", "trigger", "table"), _GUARDS, ids=[g[1] for g in _GUARDS])
def test_each_guard_refuses_under_its_own_name_and_prints_a_column_name_only(
    function: str, trigger: str, table: str
) -> None:
    body = _function(function)
    refusals = re.findall(r"RAISE EXCEPTION '([^']*)'([^;]*);", body)
    assert len(refusals) == 1 and body.count("RAISE ") == 1
    ((message, rest),) = refusals
    assert message.startswith(f"{trigger}: {table}.% ") and message.count("%") == 1
    assert rest == f", changed USING ERRCODE = 'check_violation', CONSTRAINT = '{trigger}'"
    case = body.split("changed := CASE ", 1)[1].split(" END; ", 1)[0]
    assert " ELSE " not in case and set(re.findall(r"THEN '(\w+)'", case)) <= (
        {c.name for c in _TABLES[table].columns} | {"request", "outcome"}
    )


@pytest.mark.parametrize(("trigger", "table"), _TRUNCATE, ids=[t for t, _ in _TRUNCATE])
def test_no_role_truncates_either_table(trigger: str, table: str) -> None:
    """SR-E29-05's pattern, 0003's `audit_refuse_truncate()`, always enabled (the anchor's by the
    orchestrator's Q8 ruling on #913)."""
    create = (
        f"CREATE TRIGGER {trigger} BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();"
    )
    assert _in_order(_up(), [create, f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {trigger};"])
    assert "CREATE FUNCTION audit_refuse_truncate" not in _up()


def test_the_app_and_read_only_roles_hold_no_delete_or_truncate() -> None:
    """Each REVOKE runs only where `pg_bootstrap.sql` made its role (0029's pattern)."""
    revoke = "REVOKE DELETE, TRUNCATE ON idempotency_anchors, recorded_stops FROM"
    role = "IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{0}') THEN EXECUTE '{1} {0}'; END IF;"
    guarded = " ".join(("DO $BODY$ BEGIN", role.format("cv_app", revoke)))
    guarded = " ".join((guarded, role.format("cv_ro", revoke), "END $BODY$;"))
    assert guarded in _up()


_COMMENT = re.compile(r"COMMENT ON COLUMN (\w+)\.(\w+) IS '([^']*)';")


def test_every_rendered_comment_is_a_model_comment_and_the_other_way_round() -> None:
    """C-5.9 / 21 Sec.12 class P1: the stops' four money columns and the anchor's key and
    fingerprint; `alembic check` diffs comments, so the SQL and `db.models` agree text for text."""
    rendered = _COMMENT.findall(_up())
    model = [
        (t.name, c.name, str(c.comment)) for t in _TABLES.values() for c in t.columns if c.comment
    ]
    assert len(rendered) == len(model) == 6 and sorted(rendered) == sorted(model)
    money = {
        c.name
        for c in models.recorded_stops.columns
        if isinstance(c.type, Numeric) and (c.type.precision, c.type.scale) == (38, 18)
    }
    assert {c for t, c, text in model if text == models.OMS_MONEY_COMMENT} == money
    key = {c for t, c, text in model if text == models.ANCHOR_KEY_COMMENT}
    assert key == {"client_ref", "request_sha256"}
    for text in (models.OMS_MONEY_COMMENT, models.ANCHOR_KEY_COMMENT):
        assert text.startswith("PII: ") and "class P1" in text and "'" not in text


def test_downgrade_refuses_first_under_share_locks_then_drops_in_dependency_order() -> None:
    """C-5.2: the record is permanent, so nothing is dropped while a row exists or an order says
    it came another way; 0003's `audit_refuse_truncate()` is kept."""
    assert _in_order(
        _down(),
        [
            _LOCK_ON,
            "LOCK TABLE recorded_stops, idempotency_anchors, orders IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM recorded_stops) "
            "OR EXISTS (SELECT 1 FROM idempotency_anchors) "
            "OR EXISTS (SELECT 1 FROM orders WHERE provenance <> 'placed') THEN",
            "RAISE EXCEPTION '0043_order_submission downgrade refused: ",
            "Fix forward with a new revision instead (C-5.2)';",
            "DROP TABLE recorded_stops;",
            "DROP FUNCTION rs_guard();",
            "DROP TABLE idempotency_anchors;",
            "DROP FUNCTION ia_write_once();",
            "ALTER TABLE orders DROP CONSTRAINT ord_provenance;",
            "ALTER TABLE orders DROP COLUMN provenance;",
            _LOCK_OFF,
        ],
    )
    up, down = _up(), _down()
    for kind in ("TABLE", "FUNCTION"):
        created = sorted(re.findall(rf"CREATE {kind} (\w+)", up))
        assert created == sorted(re.findall(rf"DROP {kind} (\w+)", down)), kind
    assert "audit_refuse_truncate" not in down


def _default(column: Column[Any]) -> str | None:
    default = column.server_default
    if default is None:
        return None
    assert isinstance(default, DefaultClause)
    return str(default.arg)


def _doc_columns(table: str) -> list[tuple[str, bool, str | None]]:
    columns: list[tuple[str, bool, str | None]] = []
    for line in _doc_table(table).splitlines():
        found = re.match(r"  ([a-z][a-z0-9_]*) ", line)
        if found is None:
            continue
        ddl = line.split("--", 1)[0].strip()
        default = re.search(r"DEFAULT (\S+?),?$", ddl)
        nullable = "NOT NULL" not in ddl and "PRIMARY KEY" not in ddl
        columns.append((found[1], nullable, default[1] if default else None))
    return columns


def _checks(table: Table) -> dict[str, str]:
    return {
        str(c.name).removeprefix(f"ck_{table.name}_"): " ".join(str(c.sqltext).split())
        for c in table.constraints
        if isinstance(c, CheckConstraint)
    }


def _create_index(ix: Index) -> str:
    assert ix.table is not None
    columns = ", ".join(str(e).removeprefix(f"{ix.table.name}.") for e in ix.expressions)
    where = ix.dialect_options["postgresql"]["where"]
    unique = "UNIQUE " if ix.unique else ""
    return f"CREATE {unique}INDEX {ix.name} ON {ix.table.name} ({columns}) WHERE {where};"


@pytest.mark.parametrize("table", _TABLES.values(), ids=list(_TABLES))
def test_models_mirror_the_doc_columns_keys_checks_and_indexes(table: Table) -> None:
    """The `migrations` job autogenerate-diffs the DB against `db.models`; names, nullability,
    defaults, CHECK bodies and partial predicates, which it does not diff, are pinned here."""
    later = _LATER_COLUMNS.get(table.name, frozenset())
    got = [(c.name, bool(c.nullable), _default(c)) for c in table.columns if c.name not in later]
    assert got == _doc_columns(table.name)
    doc_fks = re.findall(
        r"^  (\w+)\s+uuid(?: NOT NULL)? REFERENCES (\w+)\(id\) ON DELETE (RESTRICT)",
        _doc_table(table.name),
        re.MULTILINE,
    )
    fks = {
        (c.column_keys[0], c.referred_table.name, c.ondelete) for c in table.foreign_key_constraints
    }
    assert fks == set(doc_fks) and fks
    checks = _checks(table)
    added = _LATER_CHECKS.get(table.name, frozenset())
    doc_checks = set(re.findall(r"CONSTRAINT (\w+)\s+CHECK", _doc_table(table.name)))
    assert set(checks) - added == doc_checks
    replaced = _REPLACED_CHECKS.get(table.name, frozenset())
    for name, body in checks.items():
        if name not in added | replaced:
            assert _norm(f"CONSTRAINT {name} CHECK ({body})") in _up(), name
    for ix in table.indexes:
        assert _create_index(ix) in _up(), ix.name


def test_the_anchor_is_unique_per_principal_and_operation_only() -> None:
    uniques = [
        (c.name, tuple(col.name for col in c.columns))
        for t in _TABLES.values()
        for c in t.constraints
        if isinstance(c, UniqueConstraint)
    ]
    assert uniques == [("ux_ia_principal_ref", ("created_by", "operation", "client_ref"))]
    stops = {str(ix.name) for ix in models.recorded_stops.indexes if ix.unique}
    assert stops == {"ux_rs_in_flight", "ux_rs_in_force"}


def test_the_ref_format_is_the_group_ref_format() -> None:
    """One key, two homes (21 Sec.3.3.2, Sec.3.3.10): the anchor and an entry's group admit the
    same canonical lower-case UUID text."""
    check = f"CONSTRAINT ia_ref_fmt CHECK (client_ref ~ '{models.GROUP_REF_PATTERN}'),"
    assert check in _up()
    assert _checks(models.idempotency_anchors)["ia_ref_fmt"] == (
        f"client_ref ~ '{models.GROUP_REF_PATTERN}'"
    )


def test_provenance_follows_lifecycle_state_and_its_check_admits_three_values() -> None:
    """Appended after `lifecycle_state`, as its ALTER TABLE adds it; `0064_orders_origin`'s two
    columns come after it (`test_0064_orders_origin.py`)."""
    columns = list(models.orders.c)
    assert [c.name for c in columns[-5:-2]] == ["is_paper", "lifecycle_state", "provenance"]
    provenance = models.orders.c.provenance
    assert not provenance.nullable and _default(provenance) == "'placed'"
    body = _checks(models.orders)["ord_provenance"]
    assert body == "provenance IN ('placed','reconciliation','recorded_stop')"
    assert f"ALTER TABLE orders ADD CONSTRAINT ord_provenance CHECK ({body});" in _up()


def test_section_9_4_registers_the_revision() -> None:
    plan = _DOC.read_text(encoding="utf-8").split("### 9.4 ", 1)[1].split("### 9.5 ", 1)[0]
    [row] = [line for line in plan.splitlines() if line.startswith(f"| `{_REV}`")]
    assert "**E29-T04 #913**" in row and "the downgrade refuses while an anchor" in row
    assert "NNNN_" not in plan
