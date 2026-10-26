"""`0052_ia_purge_anchor` (E16-T06, #490): offline render, two-way plan-doc parity, the bound's
column and constraints, the write-once trigger's new column, and the downgrade. The route side
(the anchor written after the write-ahead record and read back across a restart):
`tests/unit/api/test_recorder_purge.py`; the store's statements:
`tests/unit/storage/test_purge_anchors_store.py`.
Real Postgres: `tests/integration/storage/test_ia_purge_anchor_migration.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

from sqlalchemy import CheckConstraint

from candleviewer.db.models import idempotency_anchors

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0052_ia_purge_anchor", "0051_replay_symbols_streams"
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
_STAMP_UP = (
    "UPDATE alembic_version SET version_num='0052_ia_purge_anchor' "
    "WHERE alembic_version.version_num = '0051_replay_symbols_streams'"
)
_STAMP_DOWN = (
    "UPDATE alembic_version SET version_num='0051_replay_symbols_streams' "
    "WHERE alembic_version.version_num = '0052_ia_purge_anchor'"
)
_OLD_OPERATIONS = "'placeOrder','closePosition','reversePosition','closeAllPositions'"


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#490)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    flat = " ".join(re.sub(r"--[^\n]*", "", sql).split())
    return flat.replace("( ", "(").replace(" )", ")")


def _statements(sql: str) -> list[str]:
    """`sql` cut at every `;`, blanks dropped; a function body is cut the same way both sides."""
    return [part.strip() for part in sql.split(";") if part.strip()]


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", _UP, "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", _DOWN, "--sql"))


def _doc_block() -> str:
    """Sec.3.3.10's third ```sql block (0043's table and its guard come first)."""
    text = _DOC.read_text(encoding="utf-8")
    section = text.split("#### 3.3.10 ", 1)[1].split("#### 3.3.11 ")[0]
    return section.split("```sql")[3].split("```", 1)[0]


def test_revision_chains_onto_0051() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", _UP)


def test_upgrade_is_exactly_the_plan_doc_ddl_under_a_bounded_lock_wait() -> None:
    before, rest = _up().split(_LOCK, 1)
    ddl, after = rest.split(_RESET, 1)
    assert _statements(ddl) == _statements(_norm(_doc_block()))
    assert _statements(before) == ["BEGIN"]
    assert _statements(after) == [_STAMP_UP, "COMMIT"]


def test_the_bound_arrives_nullable_and_both_checks_validate_outside_the_exclusive_lock() -> None:
    """C-5.1 and C-5.6: no default, no NOT NULL; each CHECK is added NOT VALID in the ALTER that
    takes ACCESS EXCLUSIVE and validated in its own statement (SHARE UPDATE EXCLUSIVE)."""
    up = _statements(_up())
    alter = next(s for s in up if s.startswith("ALTER TABLE idempotency_anchors ADD COLUMN"))
    assert "ADD COLUMN before_us bigint," in alter and "NOT NULL" not in alter.split("CHECK")[0]
    assert alter.count("NOT VALID") == 2 and "DEFAULT" not in alter
    assert f"CHECK (operation IN ({_OLD_OPERATIONS},'purgeRecordedData')) NOT VALID" in alter
    bound = (
        "ADD CONSTRAINT ia_bound CHECK ((before_us IS NOT NULL) = (operation = "
        "'purgeRecordedData') AND (before_us IS NULL OR before_us >= 0)) NOT VALID"
    )
    assert bound in alter
    assert "ALTER TABLE idempotency_anchors VALIDATE CONSTRAINT ia_operation" in up
    assert "ALTER TABLE idempotency_anchors VALIDATE CONSTRAINT ia_bound" in up


def test_the_write_once_trigger_freezes_the_bound_and_keeps_every_earlier_column() -> None:
    up, down = _up(), _down()
    frozen = "WHEN NEW.before_us IS DISTINCT FROM OLD.before_us THEN 'before_us'"
    assert frozen in up and frozen not in down
    columns = ("id", "created_by", "operation", "client_ref", "request_sha256", "trade_group_id")
    for column in (*columns, "order_id", "created_at"):
        clause = f"WHEN NEW.{column} IS DISTINCT FROM OLD.{column} THEN '{column}'"
        assert clause in up and clause in down
    assert "CREATE OR REPLACE FUNCTION ia_write_once()" in up
    assert "SET search_path = pg_catalog, pg_temp" in up and "SECURITY DEFINER" not in up
    assert "CREATE TRIGGER" not in up  # the trigger keeps pointing at the replaced function


def test_downgrade_refuses_while_a_purge_anchor_exists_then_restores_0043() -> None:
    down = _statements(_down())
    assert down[:2] == ["BEGIN", _LOCK.rstrip(";")]
    refusal = next(s for s in down if s.startswith("DO $BODY$"))
    held = "IF EXISTS (SELECT 1 FROM idempotency_anchors WHERE operation = 'purgeRecordedData')"
    assert held in refusal
    assert "RAISE EXCEPTION '0052_ia_purge_anchor downgrade refused:" in refusal
    assert "DELETE" not in _down() and "TRUNCATE" not in _down()  # the anchor is permanent
    restore = (
        "ALTER TABLE idempotency_anchors DROP CONSTRAINT ia_bound, DROP CONSTRAINT ia_operation, "
        f"ADD CONSTRAINT ia_operation CHECK (operation IN ({_OLD_OPERATIONS})) NOT VALID"
    )
    assert restore in down
    assert down[-5:] == [
        "ALTER TABLE idempotency_anchors VALIDATE CONSTRAINT ia_operation",
        "ALTER TABLE idempotency_anchors DROP COLUMN before_us",
        _RESET.rstrip(";"),
        _STAMP_DOWN,
        "COMMIT",
    ]


def test_the_model_declares_the_column_and_both_constraints_as_the_migration() -> None:
    column = idempotency_anchors.c.before_us
    assert column.nullable and column.server_default is None
    assert str(column.type) == "BIGINT"
    checks = {
        str(c.name).removeprefix("ck_idempotency_anchors_"): " ".join(str(c.sqltext).split())
        for c in idempotency_anchors.constraints
        if isinstance(c, CheckConstraint)
    }
    assert checks["ia_operation"] == f"operation IN ({_OLD_OPERATIONS},'purgeRecordedData')"
    assert checks["ia_bound"] == (
        "(before_us IS NOT NULL) = (operation = 'purgeRecordedData') "
        "AND (before_us IS NULL OR before_us >= 0)"
    )
