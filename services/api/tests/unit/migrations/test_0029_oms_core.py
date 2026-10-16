"""`0029_oms_core` (E29-T01 #845): offline render, plan-doc parity, models, classification.
Real Postgres: `tests/integration/storage/test_oms_core_migration.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import CheckConstraint, Column, Computed, Index, Numeric, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.schema import DefaultClause

from candleviewer.db import models
from candleviewer.domain.order_link import EXT_ID, OUR_ID

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0029_oms_core", "0028_incidents_backups"
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"
_BLOCKS = ("3.3.4 `orders`", "3.3.5 `order_events`", "3.3.6 `executions`", "3.3.7 `positions`")
#: The one documented deviation (Sec.3.3.4 note): `trade_group_legs` (E28-T01) does not exist yet.
_LEG_FK = " REFERENCES trade_group_legs(id) ON DELETE SET NULL"
_TABLES = {
    t.name: t
    for t in (
        models.orders,
        models.order_events,
        models.executions,
        models.positions,
        models.position_snapshots,
    )
}


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#845)
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
    return _norm(_alembic("upgrade", _UP, "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", _DOWN, "--sql"))


@cache
def _doc_block(heading: str) -> str:
    """The first ```sql block after `#### <heading>` in 21-database-schema.md, to its fence."""
    section = _DOC.read_text(encoding="utf-8").split(f"#### {heading}", 1)[1]
    return section.split("```sql", 1)[1].split("```", 1)[0]


def _doc_table(name: str) -> str:
    """One `CREATE TABLE <name> (...);` of the doc, raw (comments kept)."""
    text = "\n".join(_doc_block(h) for h in _BLOCKS)
    return text.split(f"CREATE TABLE {name} (", 1)[1].split("\n);", 1)[0]


def _in_order(sql: str, steps: list[str]) -> bool:
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def test_revision_chains_onto_0028() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", _UP)


@pytest.mark.parametrize(
    ("enum", "name"),
    [
        (models.order_intent, "order_intent"),
        (models.order_state, "order_state"),
        (models.order_event_kind, "order_event_kind"),
    ],
)
def test_upgrade_creates_each_enum_as_the_plan_doc_and_the_model_declare_it(
    enum: ENUM, name: str
) -> None:
    statement = f"CREATE TYPE {name} AS ENUM ({','.join(repr(v) for v in enum.enums)});"
    assert statement in _norm(_DOC.read_text(encoding="utf-8")) and statement in _up()
    assert enum.name == name and enum.create_type is False  # the migration creates and drops it


@pytest.mark.parametrize("heading", _BLOCKS)
def test_upgrade_ddl_is_the_plan_doc_ddl_verbatim_but_the_leg_fk(heading: str) -> None:
    assert _norm(_doc_block(heading).replace(_LEG_FK, "")) in _up()


def test_only_the_two_leg_references_are_deferred() -> None:
    doc = "".join(_doc_block(h) for h in _BLOCKS)
    assert doc.count(_LEG_FK) == 2 and "trade_group_legs" not in _up()
    for table in ("orders", "executions"):
        leg = _TABLES[table].c.trade_group_leg_id
        assert _LEG_FK in _doc_table(table) and leg.nullable and not leg.foreign_keys


def test_ord_link_fmt_admits_exactly_the_two_domain_id_shapes() -> None:
    """The CHECK and `candleviewer.domain.order_link` must never drift (24 Sec.8.3)."""
    check = re.search(r"CONSTRAINT ord_link_fmt CHECK \((.*?)\), CONSTRAINT", _up())
    assert check is not None
    assert re.findall(r"order_link_id ~ '([^']*)'", check[1]) == [OUR_ID.pattern, EXT_ID.pattern]


def test_upgrade_ships_only_these_objects() -> None:
    sql = _up()
    assert sql.count("CREATE TABLE ") == 5 and sql.count("CREATE TYPE ") == 3
    assert sql.count("CREATE UNIQUE INDEX ") == 3 and sql.count("CREATE INDEX ") == 19
    assert sql.count("CREATE TRIGGER ") == 4
    assert sql.count("COMMENT ON COLUMN ") == 38 + 5  # money columns, exchange answer columns
    for absent in ("CREATE FUNCTION", "INSERT INTO", "GRANT ", "audit_log", "IF NOT EXISTS"):
        assert absent not in sql


@pytest.mark.parametrize(
    ("table", "tag", "heading"),
    [("order_events", "oe", _BLOCKS[1]), ("executions", "exec", _BLOCKS[2])],
)
def test_append_only_tables_copy_the_audit_log_guards(table: str, tag: str, heading: str) -> None:
    """C-5.7 (the #845 ruling): row trigger, TRUNCATE statement trigger and the grant
    revocation, the 0003 pattern."""
    sql = _up()
    assert (
        f"CREATE TRIGGER trg_{tag}_append BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation();"
    ) in sql
    assert (
        f"CREATE TRIGGER trg_{tag}_no_truncate BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();"
    ) in sql
    for role in ("cv_app", "cv_ro"):
        assert _in_order(
            sql,
            [
                f"IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN",
                "EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON order_events, executions "
                f"FROM {role}';",
            ],
        )
    revoke = f"-- REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM cv_app, cv_ro;"
    assert revoke in " ".join(_doc_block(heading).split())  # recorded in the doc


def test_upgrade_bounds_every_lock_with_lock_timeout() -> None:
    steps = ["SET LOCAL lock_timeout = '5s';", "CREATE TYPE order_intent", "CREATE TABLE orders ("]
    steps += ["CREATE TABLE position_snapshots (", "DO $BODY$", "COMMENT ON COLUMN orders.qty"]
    assert _in_order(_up(), [*steps, "SET LOCAL lock_timeout = DEFAULT;"])


def test_downgrade_locks_refuses_while_populated_then_drops_tables_then_types() -> None:
    tables = ["position_snapshots", "positions", "executions", "order_events", "orders"]
    assert _in_order(
        _down(),
        [
            "SET LOCAL lock_timeout = '5s';",
            "LOCK TABLE orders, order_events, executions, positions, position_snapshots "
            "IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM orders) OR EXISTS (SELECT 1 FROM order_events) "
            "OR EXISTS (SELECT 1 FROM executions) OR EXISTS (SELECT 1 FROM positions) "
            "OR EXISTS (SELECT 1 FROM position_snapshots) THEN",
            "RAISE EXCEPTION '0029_oms_core downgrade refused: the OMS tables hold rows.",
            "fix forward with a new revision instead (C-5.2)';",
            *(f"DROP TABLE {t};" for t in tables),
            *(f"DROP TYPE {t};" for t in ("order_event_kind", "order_state", "order_intent")),
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )


def _default(column: Column[Any]) -> str | None:
    default = column.server_default
    if default is None or isinstance(default, Computed):
        return None
    assert isinstance(default, DefaultClause)
    return str(default.arg)


def _doc_columns(table: str) -> list[tuple[str, bool, str | None]]:
    """`(name, nullable, server default)` for every column line of the doc's CREATE TABLE."""
    columns: list[tuple[str, bool, str | None]] = []
    for line in _doc_table(table).splitlines():
        found = re.match(r"  ([a-z][a-z0-9_]*) ", line)
        if found is None:  # CONSTRAINT / UNIQUE lines and the ord_link_fmt continuation
            continue
        ddl = line.split("--", 1)[0].strip()
        default = re.search(r"DEFAULT (\S+?),?$", ddl)
        nullable = "NOT NULL" not in ddl and "PRIMARY KEY" not in ddl
        columns.append((found[1], nullable, default[1] if default else None))
    return columns


@pytest.mark.parametrize("table", _TABLES.values(), ids=list(_TABLES))
def test_models_mirror_the_doc_columns(table: Table) -> None:
    """The `migrations` job autogenerate-diffs the DB against `db.models.metadata`; names,
    nullability and server defaults are pinned against the plan doc here."""
    got = [(c.name, bool(c.nullable), _default(c)) for c in table.columns]
    assert got == _doc_columns(table.name)


@pytest.mark.parametrize("table", _TABLES.values(), ids=list(_TABLES))
def test_models_mirror_the_foreign_keys_and_their_delete_rules(table: Table) -> None:
    doc = re.findall(
        r"^  (\w+)\s+uuid(?: NOT NULL)? REFERENCES (\w+)\(id\) "
        r"ON DELETE (RESTRICT|CASCADE|SET NULL)",
        _doc_table(table.name),
        re.MULTILINE,
    )
    got = {(fk.parent.name, fk.column.table.name, fk.ondelete) for fk in table.foreign_keys}
    assert got == {fk for fk in doc if fk[1] != "trade_group_legs"} and got


@pytest.mark.parametrize("table", _TABLES.values(), ids=list(_TABLES))
def test_models_mirror_the_check_constraints(table: Table) -> None:
    """`alembic check` never diffs CHECK bodies, so they are pinned against the SQL here."""
    checks = {
        str(c.name).removeprefix(f"ck_{table.name}_"): " ".join(str(c.sqltext).split())
        for c in table.constraints
        if isinstance(c, CheckConstraint)
    }
    assert set(checks) == set(re.findall(r"CONSTRAINT (\w+)\s+CHECK", _doc_table(table.name)))
    for name, body in checks.items():
        assert _norm(f"CONSTRAINT {name} CHECK ({body})") in _up(), name


def test_models_mirror_the_unique_constraints_under_their_postgres_names() -> None:
    """Postgres names an unnamed `UNIQUE (a, b)` `<table>_a_b_key`; `alembic check` diffs names."""
    uniques = {
        (str(c.name), tuple(col.name for col in c.columns))
        for table in _TABLES.values()
        for c in table.constraints
        if isinstance(c, UniqueConstraint)
    }
    assert uniques == {
        ("order_events_order_id_seq_key", ("order_id", "seq")),
        (
            "positions_exchange_account_id_symbol_position_idx_key",
            ("exchange_account_id", "symbol", "position_idx"),
        ),
    }
    assert "UNIQUE (order_id, seq)" in _up()
    assert "UNIQUE (exchange_account_id, symbol, position_idx)" in _up()


def _create_index(ix: Index) -> str:
    """The `CREATE INDEX` statement a model index stands for, in the migration's spelling."""
    assert ix.table is not None
    columns = ", ".join(str(e).removeprefix(f"{ix.table.name}.") for e in ix.expressions)
    where = ix.dialect_options["postgresql"]["where"]
    tail = "" if where is None else f" WHERE {where}"
    unique = "UNIQUE " if ix.unique else ""
    return f"CREATE {unique}INDEX {ix.name} ON {ix.table.name} ({columns}){tail};"


@pytest.mark.parametrize("table", _TABLES.values(), ids=list(_TABLES))
def test_models_mirror_the_indexes(table: Table) -> None:
    doc = "\n".join(_doc_block(h) for h in _BLOCKS)
    assert sorted(str(ix.name) for ix in table.indexes) == sorted(
        re.findall(rf"INDEX (\w+)\s+ON {table.name} ", doc)
    )
    for ix in table.indexes:
        assert _create_index(ix) in _up(), ix.name


def test_leaves_qty_is_the_stored_generated_column() -> None:
    computed = models.orders.c.leaves_qty.computed
    assert isinstance(computed, Computed) and computed.persisted is True
    assert str(computed.sqltext) == "qty - cum_exec_qty"
    assert "leaves_qty numeric(38,18) GENERATED ALWAYS AS (qty - cum_exec_qty) STORED," in _up()


def test_orders_carry_the_native_stop_loss_fields_from_day_one() -> None:
    """C-2.6 (main-orchestrator ruling on #845, 2026-10-16): the TP/SL attached on create
    (24-internal-schemas.md Sec.8.1 `Order`, Sec.8.8 rule 1) is stored on the order row."""
    ddl = _up().split("CREATE TABLE orders (", 1)[1].split(");", 1)[0]
    for name, tag in (("take_profit", "tp"), ("stop_loss", "sl")):
        column = models.orders.c[name]
        assert f" {name} numeric(38,18), " in ddl
        assert column.nullable and column.comment == models.OMS_MONEY_COMMENT
        assert f" CONSTRAINT ord_{tag}_px CHECK ({name} IS NULL OR {name} > 0), " in ddl
    tpsl_mode = models.orders.c.tpsl_mode
    assert " tpsl_mode text NOT NULL DEFAULT 'Full', " in ddl
    assert " CONSTRAINT ord_tpslmode CHECK (tpsl_mode IN ('Full','Partial')), " in ddl
    assert not tpsl_mode.nullable and _default(tpsl_mode) == "'Full'"


def test_every_numeric_column_reads_back_as_decimal() -> None:
    """`Decimal` end to end (#845): no numeric column may hand a writer or reader a float."""
    numeric = [c.type for t in _TABLES.values() for c in t.columns if isinstance(c.type, Numeric)]
    assert len(numeric) == 10 + 8 + 15 + 7  # orders, executions, positions, position_snapshots
    assert all(n.asdecimal and n.python_type is Decimal for n in numeric)


#: C-5.9 / Sec.12: the columns that keep the exchange's answer to an order, class P1 as well.
_EXCHANGE_TEXT = {
    "orders": {"reject_code", "reject_message"},
    "order_events": {"payload", "ret_code", "ret_msg"},
}


def test_money_and_exchange_text_columns_carry_the_p1_classification_comment() -> None:
    """C-5.9 / Sec.12: every numeric(38,18) column of an OMS table is P1, `position_snapshots`
    (the history of `positions`) included, and so are the columns that keep the exchange's answer
    (it can repeat those values); nothing else carries a comment."""
    assert models.OMS_MONEY_COMMENT.startswith("PII: ")
    assert models.OMS_EXCHANGE_TEXT_COMMENT.startswith("PII: ")
    assert "class P1" in models.OMS_EXCHANGE_TEXT_COMMENT
    assert "'" not in models.OMS_EXCHANGE_TEXT_COMMENT  # it sits in a SQL string literal
    for name, table in _TABLES.items():
        money = {
            c.name
            for c in table.columns
            if isinstance(c.type, Numeric) and (c.type.precision, c.type.scale) == (38, 18)
        }
        want = dict.fromkeys(money, models.OMS_MONEY_COMMENT)
        want |= dict.fromkeys(_EXCHANGE_TEXT.get(name, ()), models.OMS_EXCHANGE_TEXT_COMMENT)
        assert {c.name: c.comment for c in table.columns if c.comment} == want, name
        for column, comment in want.items():
            assert f"COMMENT ON COLUMN {name}.{column} IS '{comment}';" in _up()


@pytest.mark.parametrize("table", list(_TABLES))
def test_a_later_migration_naming_an_oms_table_is_flagged_for_security_review(
    tmp_path: Path, table: str
) -> None:
    """CI-MIG-006 lists the OMS tables (`tools/ci/security-sensitive-tables.txt`): financial records
    (#845 security notes, Sec.12), so a revision that alters one raises the security-review flag."""
    later = tmp_path / "0099_later.py"
    later.write_text(f'op.add_column("{table}", sa.Column("note", sa.Text()))\n', encoding="utf-8")
    lint = _ROOT.parents[1] / "tools" / "ci" / "migration_lint.py"
    r = subprocess.run(  # noqa: S603 -- fixed argv, the repo's own lint script, no shell (#845)
        [sys.executable, str(lint), "--versions-dir", str(tmp_path)],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert f"WARN CI-MIG-006: {later}: touches security-sensitive table '{table}'" in r.stderr
