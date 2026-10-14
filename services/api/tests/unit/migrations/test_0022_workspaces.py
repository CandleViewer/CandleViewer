"""`0022_workspaces`: model mirrors the SQL, DDL renders, downgrade guard (E15-T01)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import Table

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_KINDS = (
    "chart,dom,tape,profile,cvd,oi,deep_stats,regime,positions,journal,watchlist,alerts"
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


def _checks(table: Table) -> set[str]:
    return {str(c.name) for c in table.constraints if c.__class__.__name__ == "CheckConstraint"}


def test_model_constraint_and_index_names_match_sql() -> None:
    assert _checks(models.layouts) == {"ck_layouts_lay_preset", "ck_layouts_lay_slot"}
    assert _checks(models.layout_panes) == {
        "ck_layout_panes_lp_kind",
        "ck_layout_panes_lp_slot",
        "ck_layout_panes_lp_scale",
    }
    assert {i.name for i in models.workspaces.indexes} == {"ux_ws_name", "ux_ws_default"}
    assert {i.name for i in models.layouts.indexes} == {
        "ux_lay_name",
        "ux_lay_slot",
        "ux_lay_default",
        "ix_lay_workspace",
    }
    assert {i.name for i in models.layout_panes.indexes} == {"ix_lp_layout", "ix_lp_symbol"}
    assert "ix_dr_layout" in {i.name for i in models.drawings.indexes}


def test_model_pane_kinds_match_spec_order() -> None:
    assert list(models.PANE_KINDS) == _KINDS


def test_upgrade_sql_has_tables_composite_fks_and_indexes() -> None:
    sql = _render("upgrade", "0021_drawings:0022_workspaces")
    for table in ("workspaces", "layouts", "layout_panes"):
        assert f"CREATE TABLE {table} (" in sql
    assert "CONSTRAINT ux_workspaces_id_user_id UNIQUE (id, user_id)" in sql
    assert "FOREIGN KEY (workspace_id, owner_user_id)" in sql
    assert "REFERENCES workspaces (id, user_id) ON DELETE CASCADE" in sql
    assert "CONSTRAINT ux_layouts_id_owner_user_id UNIQUE (id, owner_user_id)" in sql
    assert "CONSTRAINT ux_lp_slot UNIQUE (layout_id, slot_index)" in sql
    assert "CREATE INDEX ix_lp_layout ON layout_panes (layout_id, slot_index)" in sql
    assert "CREATE INDEX ix_lp_symbol ON layout_panes (symbol) WHERE symbol IS NOT NULL" in sql
    assert "CREATE UNIQUE INDEX ux_lay_default" in sql
    flat = "".join(sql.split())
    assert "pane_kindIN(" + ",".join(f"'{k}'" for k in _KINDS) + ")" in flat


def test_chart_template_id_has_no_foreign_key() -> None:
    sql = _render("upgrade", "0021_drawings:0022_workspaces")
    assert "chart_template_id    uuid," in sql
    assert "chart_templates" not in sql.split("CREATE TABLE layout_panes")[1].split(";")[0]


def test_drawings_fk_is_added_not_valid_then_validated() -> None:
    sql = _render("upgrade", "0021_drawings:0022_workspaces")
    assert "ADD CONSTRAINT fk_drawings_layout_id_layouts" in sql
    assert "FOREIGN KEY (layout_id, owner_user_id) REFERENCES layouts (id, owner_user_id)" in sql
    assert "MATCH SIMPLE ON DELETE CASCADE NOT VALID" in sql
    assert "VALIDATE CONSTRAINT fk_drawings_layout_id_layouts" in sql
    assert sql.index("NOT VALID") < sql.index("VALIDATE CONSTRAINT")
    assert "CREATE INDEX ix_dr_layout ON drawings (layout_id) WHERE layout_id IS NOT NULL" in sql


def test_downgrade_refuses_populated_and_drops_in_reverse_order() -> None:
    sql = _render("downgrade", "0022_workspaces:0021_drawings")
    assert "downgrade refused" in sql
    order = [
        sql.index(s)
        for s in (
            "DROP INDEX ix_dr_layout",
            "DROP CONSTRAINT IF EXISTS fk_drawings_layout_id_layouts",
            "DROP TABLE layout_panes",
            "DROP TABLE layouts",
            "DROP TABLE workspaces",
        )
    ]
    assert order == sorted(order)
