"""The `oms_handovers` revision (E29-T06 #914 PR 1; 21 Sec.3.3.12): offline render, plan-doc
parity, the guard, the PII comments, the downgrade guard, the model mirror and the ledger row.

The revision's id and parent are read from its file, so the provisional number and the parent it
is re-parented onto at the PR's open (C-5.3) change nothing here. Real Postgres: the `migrations`
CI job's round trip (upgrade, downgrade, upgrade on an empty and a seeded database, C-5.5)."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from collections.abc import Callable
from functools import cache
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, Column, Index, Table
from sqlalchemy.schema import DefaultClause

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_VERSIONS = _ROOT / "candleviewer" / "migrations" / "versions"
_HEADING = "3.3.12 `oms_handovers`"
_TABLE: Table = models.oms_handovers
_LOCK_ON, _LOCK_OFF = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
_DDL = re.compile(r"\b(?:CREATE|ALTER|DROP|DO|COMMENT|REVOKE|LOCK)\b")
_COMMENT = re.compile(r"COMMENT ON COLUMN (\w+)\.(\w+) IS '([^']*)';")


def _ids(path: Path) -> tuple[str, str]:
    """The `revision` and `down_revision` string literals a version file assigns."""
    found: dict[str, str] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                found[node.target.id] = node.value.value
    return found["revision"], found["down_revision"]


[_FILE] = sorted(_VERSIONS.glob("*_oms_handovers.py"))
_REV, _PREV = _ids(_FILE)


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#914)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments, collapse whitespace and the space inside a bracket, and fold the `;`
    alembic appends, as the 0043 suite does."""
    flat = " ".join(re.sub(r"--[^\n]*", "", sql).split())
    return flat.replace("( ", "(").replace(" )", ")").replace(";;", ";")


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", f"{_PREV}:{_REV}", "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", f"{_REV}:{_PREV}", "--sql"))


@cache
def _section() -> str:
    section = _DOC.read_text(encoding="utf-8").split(f"#### {_HEADING}", 1)[1]
    return re.split(r"\n#{1,4} ", section, maxsplit=1)[0]


def _doc_block(index: int) -> str:
    return _section().split("```sql")[index + 1].split("```", 1)[0]


def _in_order(sql: str, steps: list[str]) -> bool:
    missing = [step for step in steps if step not in sql]
    assert not missing, f"not in the rendered SQL: {missing}"
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def test_the_file_is_named_for_its_revision_and_chains_onto_the_head_before_it() -> None:
    """One revision per PR (C-5.3): it follows the newest revision below its own number, which is
    the parent it names, so `alembic heads` stays one."""
    assert _FILE.stem == _REV and re.fullmatch(r"\d{4}_oms_handovers", _REV)
    below = sorted(p.stem for p in _VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py") if p.stem < _REV)
    assert _PREV == below[-1]
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")


def test_the_section_holds_two_sql_blocks_and_the_upgrade_is_them_verbatim() -> None:
    """21 Sec.3.3.12 is the DDL, word for word: the table with its indexes, then its guard."""
    assert _section().count("```sql") == 2
    for index in (0, 1):
        assert _norm(_doc_block(index)) in _up(), index


def test_upgrade_creates_the_table_then_its_guard_and_comments_under_a_bounded_lock_wait() -> None:
    assert _in_order(
        _up(),
        [
            _LOCK_ON,
            "CREATE TABLE oms_handovers (",
            "CREATE UNIQUE INDEX ux_oh_order ON oms_handovers",
            "CREATE FUNCTION oh_guard()",
            "ALTER TABLE oms_handovers ENABLE ALWAYS TRIGGER trg_oh_guard;",
            "COMMENT ON COLUMN oms_handovers.record",
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


def test_upgrade_ships_only_these_objects_and_no_grant() -> None:
    """Additive (C-5.1): one table, its three indexes, one guard; `cv_app` keeps DELETE, as entries
    are pruned, so nothing is granted or revoked (21 Sec.3.3.12)."""
    sql = _up()
    assert sql.count("CREATE TABLE ") == 1 and sql.count("CREATE FUNCTION ") == 1
    assert sql.count("CREATE UNIQUE INDEX ") == 2 and sql.count("CREATE INDEX ") == 1
    assert sql.count("CREATE TRIGGER ") == 1 and sql.count("ENABLE ALWAYS TRIGGER ") == 1
    assert sql.count("COMMENT ON COLUMN ") == 2
    for absent in (
        "GRANT ",
        "REVOKE ",
        "IF NOT EXISTS",
        "DROP ",
        "INSERT INTO ",
        "SECURITY DEFINER",
    ):
        assert absent not in sql


def test_the_guard_pins_its_search_path_refuses_under_its_own_name_and_returns_the_row() -> None:
    body = _up().split("CREATE FUNCTION oh_guard() ", 1)[1].split("END $BODY$;", 1)[0]
    assert "SET search_path = pg_catalog, pg_temp" in body
    assert "USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_oh_guard'" in body
    assert "RAISE EXCEPTION 'trg_oh_guard: oms_handovers.% may not change so', changed" in body
    assert body.rstrip().endswith("RETURN NEW;")
    assert "CREATE TRIGGER trg_oh_guard BEFORE UPDATE ON oms_handovers" in _up()


def test_the_two_p1_columns_carry_their_pii_comments_and_the_models_say_the_same() -> None:
    """C-5.9 / 21 Sec.12, class P1: `record` and `payload` can repeat an order's money values;
    `alembic check` diffs comments, so the SQL and `db.models` agree text for text."""
    rendered = _COMMENT.findall(_up())
    model = [(_TABLE.name, c.name, str(c.comment)) for c in _TABLE.columns if c.comment]
    assert sorted(rendered) == sorted(model)
    assert {c for _t, c, _text in model} == {"record", "payload"}
    for _t, _c, text in model:
        assert text.startswith("PII: ") and "class P1" in text and "'" not in text
    classified = _DOC.read_text(encoding="utf-8").split("## 12. PII", 1)[1]
    [row] = [line for line in classified.splitlines() if line.startswith("| `oms_handovers`")]
    assert "`record`, `payload`" in row and "| P1 " in row


def test_downgrade_refuses_while_any_entry_exists_then_drops_the_table_and_its_guard() -> None:
    """C-5.2: dropping the table would lose hand-overs nobody has recorded elsewhere."""
    assert _in_order(
        _down(),
        [
            _LOCK_ON,
            "LOCK TABLE oms_handovers IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM oms_handovers) THEN",
            f"RAISE EXCEPTION '{_REV} downgrade refused: ",
            "DROP TABLE oms_handovers;",
            "DROP FUNCTION oh_guard();",
            _LOCK_OFF,
        ],
    )


def _default(column: Column[object]) -> str | None:
    default = column.server_default
    if default is None:
        return None
    assert isinstance(default, DefaultClause)
    return str(getattr(default.arg, "text", default.arg))


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
    tail = f" WHERE {where};" if where is not None else ";"
    return f"CREATE {unique}INDEX {ix.name} ON {ix.table.name} ({columns}){tail}"


def test_the_model_mirrors_the_doc_columns_checks_and_indexes() -> None:
    """The `migrations` job autogenerate-diffs the database against `db.models`; names, defaults,
    CHECK bodies and partial predicates, which it does not diff, are pinned here."""
    table = _doc_block(0).split("CREATE TABLE oms_handovers (", 1)[1].split("\n);", 1)[0]
    doc_columns = re.findall(r"^  ([a-z_]+)\s+[a-z]", table, re.MULTILINE)
    assert [c.name for c in _TABLE.columns] == doc_columns
    assert [c.name for c in _TABLE.columns if not c.nullable] == [
        "id", "exchange_account_id", "kind", "exchange_order_id", "source", "record", "payload",
        "empty_reads", "created_at",
    ]  # fmt: skip
    assert _default(_TABLE.c.payload) == "'{}'::jsonb" and _default(_TABLE.c.empty_reads) == "0"
    [fk] = list(_TABLE.foreign_key_constraints)
    assert (fk.column_keys, fk.referred_table.name, fk.ondelete) == (
        ["exchange_account_id"], "exchange_accounts", "RESTRICT",
    )  # fmt: skip
    checks = _checks(_TABLE)
    assert set(checks) == set(re.findall(r"CONSTRAINT (\w+)\s+CHECK", table))
    for name, body in checks.items():
        assert _norm(f"CONSTRAINT {name} CHECK ({body})") in _up(), name
    assert {str(ix.name) for ix in _TABLE.indexes} == {"ux_oh_order", "ux_oh_exec", "ix_oh_account"}
    for ix in _TABLE.indexes:
        assert _create_index(ix) in _up(), ix.name


def test_section_9_4_registers_the_revision_and_section_7_its_retention() -> None:
    text = _DOC.read_text(encoding="utf-8")
    plan = text.split("### 9.4 ", 1)[1].split("### 9.5 ", 1)[0]
    [row] = [line for line in plan.splitlines() if line.startswith(f"| `{_REV}`")]
    assert "**E29-T06 #914**" in row and "the downgrade refuses while any entry exists" in row
    retention = text.split("## 7. Retention policy matrix", 1)[1].split("## 8. ", 1)[0]
    assert any(line.startswith("| `oms_handovers` (PG)") for line in retention.splitlines())
