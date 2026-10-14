"""`0021_drawings`: model mirrors the SQL, DDL renders, downgrade guard (E14-T01)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]

_TOOLS = (
    "trendline,horizontal_line,vertical_line,ray,extended_line,"
    "parallel_channel,rectangle,ellipse,triangle,fib_retracement,"
    "fib_extension,fib_timezone,pitchfork,gann_fan,text,"
    "arrow,callout,measure,long_position,short_position,"
    "price_range,date_range,brush,polyline,anchored_vwap"
).split(",")


def _render(*args: str) -> str:
    result = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args, "--sql"],
        cwd=_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_model_constraint_and_index_names_match_sql() -> None:
    checks = {
        str(c.name)
        for c in models.drawings.constraints
        if c.__class__.__name__ == "CheckConstraint"
    }
    assert checks == {"ck_drawings_dr_tool", "ck_drawings_dr_geom"}
    assert {ix.name for ix in models.drawings.indexes} == {"ix_dr_user_symbol", "ix_dr_range"}


def test_upgrade_sql_has_table_constraints_and_indexes() -> None:
    sql = _render("upgrade", "0020_kek_versions:0021_drawings")
    assert "CREATE TABLE drawings" in sql
    assert "CONSTRAINT dr_tool" in sql and "CONSTRAINT dr_geom" in sql
    flat = "".join(sql.split())
    assert "tool IN (" in sql
    assert "toolIN(" + ",".join(f"'{t}'" for t in _TOOLS) + "))" in flat
    assert "jsonb_typeof(geometry) = 'object' AND geometry ? 'points'" in sql
    assert "CREATE INDEX ix_dr_user_symbol ON drawings (owner_user_id, symbol)" in sql
    assert "CREATE INDEX ix_dr_range       ON drawings (symbol, anchor_start, anchor_end)" in sql
    assert sql.count("WHERE deleted_at IS NULL") == 2
    assert "layout_id     uuid," in sql
    assert "REFERENCES layouts" not in sql


def test_model_tool_list_matches_spec_order() -> None:
    assert list(models.DRAWING_TOOLS) == _TOOLS
    assert len(_TOOLS) == 25


def test_downgrade_refuses_populated_and_drops() -> None:
    sql = _render("downgrade", "0021_drawings:0020_kek_versions")
    assert "downgrade refused" in sql
    assert "DROP TABLE IF EXISTS drawings" in sql
