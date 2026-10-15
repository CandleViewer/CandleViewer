"""`0022_replay_sessions` (E26-T01 #624): offline render, plan-doc parity, models, downgrade.

Real-Postgres behaviour (named-constraint rejection, catalog parity, round trip) is covered by
`tests/integration/storage/test_replay_sessions_migration.py`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import CheckConstraint, Column, ForeignKeyConstraint, Numeric
from sqlalchemy.schema import DefaultClause

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0022_replay_sessions", "0021_drawings"
#: The six API-facing values, then B12's `stepping` and `destroyed` (C-2.19: the chart wins).
_STATES = (
    "created",
    "buffering",
    "playing",
    "paused",
    "finished",
    "error",
    "stepping",
    "destroyed",
)


def _sql(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args, "--sql"],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments and collapse whitespace so layout never matters."""
    return " ".join(re.sub(r"--[^\n]*", "", sql).split())


def _doc_block(heading: str) -> str:
    text = _DOC.read_text(encoding="utf-8")
    return text.split(heading, 1)[1].split("```sql", 1)[1].split("```", 1)[0]


def test_upgrade_creates_replay_state_with_the_contract_values_in_order() -> None:
    sql = _norm(_sql("upgrade", f"{_PREV}:{_REV}"))
    values = ",".join(f"'{s}'" for s in _STATES)
    assert f"CREATE TYPE replay_state AS ENUM ({values});" in sql
    # 21 Sec.1.2 declares the same type; the migration is its first owner.
    assert f"CREATE TYPE replay_state AS ENUM ({values});" in _norm(_DOC.read_text("utf-8"))


def test_replay_state_covers_every_b12_chart_state() -> None:
    """C-2.19: the persisted status mirrors the B12 `replay` chart, so every chart state
    (incl. transient `stepping` and final `destroyed`) is a valid `replay_state` value."""
    from candleviewer.statechart.registry import Registry

    assert set(Registry().get("replay")["states"]) == set(_STATES)


def test_upgrade_ddl_is_the_plan_doc_ddl_verbatim() -> None:
    """AC1: the table, constraints and indexes are exactly 21-database-schema.md Sec.3.6.4."""
    doc = _norm(_doc_block("#### 3.6.4 `replay_sessions`"))
    assert doc.startswith("CREATE TABLE replay_sessions (")
    assert doc in _norm(_sql("upgrade", f"{_PREV}:{_REV}"))


def test_upgrade_names_every_check_constraint_and_index() -> None:
    sql = _norm(_sql("upgrade", f"{_PREV}:{_REV}"))
    for name in ("rps_range", "rps_speed", "rps_tier", "rps_cursor", "rps_paper"):
        assert f"CONSTRAINT {name} CHECK" in sql
    assert "CREATE INDEX ix_rps_user_time ON replay_sessions (user_id, created_at DESC);" in sql
    assert (
        "CREATE INDEX ix_rps_live ON replay_sessions (state) "
        "WHERE state IN ('buffering','playing','paused','stepping');"
    ) in sql


def test_upgrade_tags_bookmarks_as_pii_per_classification() -> None:
    """C-5.9 / 21 Sec.12: user notes in `bookmarks` are P1 and carry a `PII:` comment that
    the model mirrors verbatim (`alembic check` diffs column comments too)."""
    sql = _norm(_sql("upgrade", f"{_PREV}:{_REV}"))
    comment = models.replay_sessions.c.bookmarks.comment
    assert comment is not None and comment.startswith("PII:")
    assert f"COMMENT ON COLUMN replay_sessions.bookmarks IS '{comment}';" in sql
    assert "| `replay_sessions` " in _DOC.read_text(encoding="utf-8")


def test_downgrade_refuses_while_populated_then_drops_table_before_type() -> None:
    sql = _norm(_sql("downgrade", f"{_REV}:{_PREV}"))
    assert "IF EXISTS (SELECT 1 FROM replay_sessions) THEN" in sql
    assert "RAISE EXCEPTION '0022_replay_sessions downgrade refused" in sql
    drop_table = sql.index("DROP TABLE IF EXISTS replay_sessions;")
    assert drop_table < sql.index("DROP TYPE IF EXISTS replay_state;")


_COLUMNS = [
    # (name, nullable, server_default) in DDL order (Sec.3.6.4).
    ("id", False, None),
    ("user_id", False, None),
    ("recording_session_id", True, None),
    ("symbol", False, None),
    ("range_start", False, None),
    ("range_end", False, None),
    ("cursor_ts", True, None),
    ("speed", False, "1"),
    ("state", False, "'created'"),
    ("source_tier", False, "'auto'"),
    ("paper_trading", False, "false"),
    ("paper_account_id", True, None),
    ("bookmarks", False, "'[]'::jsonb"),
    ("loop_enabled", False, "false"),
    ("events_emitted", False, "0"),
    ("gap_warnings", False, "0"),
    ("error_message", True, None),
    ("created_at", False, "now()"),
    ("updated_at", False, "now()"),
    ("finished_at", True, None),
]


def _default(column: Column[Any]) -> str | None:
    default = column.server_default
    if default is None:
        return None
    assert isinstance(default, DefaultClause)
    return str(default.arg)


def test_models_mirror_the_replay_sessions_columns() -> None:
    """The `migrations` job autogenerate-diffs the DB against `db.models.metadata`."""
    t = models.replay_sessions
    assert [(c.name, c.nullable, _default(c)) for c in t.columns] == _COLUMNS
    speed = t.c.speed.type
    assert isinstance(speed, Numeric) and (speed.precision, speed.scale) == (6, 2)
    assert tuple(models.replay_state.enums) == _STATES


def test_models_mirror_the_foreign_keys_and_their_delete_rules() -> None:
    fks = {
        (fk.parent.name, fk.column.table.name, fk.ondelete)
        for c in models.replay_sessions.constraints
        if isinstance(c, ForeignKeyConstraint)
        for fk in c.elements
    }
    assert fks == {
        ("user_id", "users", "CASCADE"),
        ("recording_session_id", "recording_sessions", "SET NULL"),
        ("paper_account_id", "exchange_accounts", "SET NULL"),
    }


def test_models_mirror_the_check_and_index_names() -> None:
    t = models.replay_sessions
    checks = {str(c.name) for c in t.constraints if isinstance(c, CheckConstraint)}
    # CHECK names get the metadata naming-convention prefix (`ck_<table>_`).
    assert checks == {
        f"ck_replay_sessions_{n}"
        for n in ("rps_range", "rps_speed", "rps_tier", "rps_cursor", "rps_paper")
    }
    indexes = {str(ix.name): ix for ix in t.indexes}
    assert set(indexes) == {"ix_rps_user_time", "ix_rps_live"}
    live_where = indexes["ix_rps_live"].dialect_options["postgresql"]["where"]
    assert str(live_where) == "state IN ('buffering','playing','paused','stepping')"


def test_no_column_can_carry_a_filesystem_path() -> None:
    """SR-097: `source_tier` is a closed enum, and no column is path-shaped."""
    names = [c.name for c in models.replay_sessions.columns]
    assert not [n for n in names if re.search(r"path|file|dir|uri|url", n)]
    sql = _norm(_sql("upgrade", f"{_PREV}:{_REV}"))
    assert "CONSTRAINT rps_tier CHECK (source_tier IN ('auto','questdb','parquet'))" in sql
