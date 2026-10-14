"""Integration: `0022_workspaces` against real Postgres 16 (E15-T01).

CI-only (no docker socket in WSL); SQL hand-run on a scratch Postgres 16.4 first.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import errors as pgerr
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_GEOM = json.dumps({"points": [{"t": "2026-01-01T00:00:00Z", "p": "1"}]})

Conn = psycopg.Connection[tuple[object, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _user(c: Conn) -> str:
    uid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO users (id, email, username, password_hash) VALUES (%s, %s, %s, '$argon2id$x')",
        (uid, f"{uid[:8]}@x.io", f"user_{uid[:8]}"),
    )
    return uid


def _active_owner(c: Conn) -> None:
    """Keep one active owner so `trg_owner_floor_fn` allows deleting other users."""
    uid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO users (id, email, username, display_name, password_hash, status) "
        "VALUES (%s, %s, %s, 'o', '$argon2id$x', 'active')",
        (uid, f"{uid}@example.test", f"o{uid[:12]}"),
    )
    c.execute(
        "INSERT INTO user_roles (user_id, role_id) SELECT %s, id FROM roles WHERE name = 'owner'",
        (uid,),
    )


def _workspace(c: Conn, user: str, name: str | None = None, **cols: object) -> str:
    wid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO workspaces (id, user_id, name, is_default) VALUES (%s, %s, %s, %s)",
        (wid, user, name or f"w-{wid}", bool(cols.get("is_default", False))),
    )
    return wid


def _layout(c: Conn, wid: str, owner: str, name: str | None = None, **cols: object) -> str:
    lid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO layouts (id, workspace_id, owner_user_id, name, grid_preset, hotkey_slot, "
        "is_default) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            lid,
            wid,
            owner,
            name or f"l-{lid}",
            cols.get("grid_preset", "1x1"),
            cols.get("hotkey_slot"),
            bool(cols.get("is_default", False)),
        ),
    )
    return lid


def _pane(
    c: Conn,
    lid: str,
    slot: int,
    *,
    kind: str = "chart",
    symbol: str | None = None,
    scale: str = "auto",
) -> None:
    c.execute(
        "INSERT INTO layout_panes (id, layout_id, slot_index, pane_kind, symbol, scale_mode) "
        "VALUES (gen_random_uuid(), %s, %s, %s, %s, %s)",
        (lid, slot, kind, symbol, scale),
    )


def _drawing(c: Conn, owner: str, layout_id: str | None) -> str:
    did = str(uuid.uuid4())
    c.execute(
        "INSERT INTO drawings (id, owner_user_id, symbol, layout_id, tool, geometry) "
        "VALUES (%s, %s, 'BTCUSDT', %s, 'trendline', %s::jsonb)",
        (did, owner, layout_id, _GEOM),
    )
    return did


_EXISTS_SQL = {
    "drawings": "SELECT 1 FROM drawings WHERE id = %s",
    "layouts": "SELECT 1 FROM layouts WHERE id = %s",
    "workspaces": "SELECT 1 FROM workspaces WHERE id = %s",
}


def _exists(c: Conn, table: str, row_id: str) -> bool:
    return c.execute(_EXISTS_SQL[table], (row_id,)).fetchone() is not None


def test_check_constraints_reject_out_of_domain_values(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        u = _user(c)
        w = _workspace(c, u)
        with pytest.raises(pgerr.CheckViolation):
            _layout(c, w, u, grid_preset="5x5")
        with pytest.raises(pgerr.CheckViolation):
            _layout(c, w, u, hotkey_slot=10)
        lid = _layout(c, w, u)
        with pytest.raises(pgerr.CheckViolation):
            _pane(c, lid, 16)
        with pytest.raises(pgerr.CheckViolation):
            _pane(c, lid, 1, kind="orders")
        with pytest.raises(pgerr.CheckViolation):
            _pane(c, lid, 1, scale="pow")
        for slot, kind in enumerate(
            "chart,dom,tape,profile,cvd,oi,deep_stats,regime,positions,journal,watchlist,alerts".split(
                ","
            )
        ):
            _pane(c, lid, slot, kind=kind)


def test_unique_indexes_name_slot_and_default(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        u = _user(c)
        w = _workspace(c, u, "Scalping", is_default=True)
        with pytest.raises(pgerr.UniqueViolation) as name_exc:
            _workspace(c, u, "scalping")
        assert name_exc.value.diag.constraint_name == "ux_ws_name"
        with pytest.raises(pgerr.UniqueViolation) as def_exc:
            _workspace(c, u, "other", is_default=True)
        assert def_exc.value.diag.constraint_name == "ux_ws_default"
        _layout(c, w, u, "L", hotkey_slot=1, is_default=True)
        with pytest.raises(pgerr.UniqueViolation) as slot_exc:
            _layout(c, w, u, "M", hotkey_slot=1)
        assert slot_exc.value.diag.constraint_name == "ux_lay_slot"
        with pytest.raises(pgerr.UniqueViolation) as lay_def:
            _layout(c, w, u, "N", is_default=True)
        assert lay_def.value.diag.constraint_name == "ux_lay_default"
        lid = _layout(c, w, u, "P")
        _pane(c, lid, 3)
        with pytest.raises(pgerr.UniqueViolation) as pane_exc:
            _pane(c, lid, 3, kind="dom")
        assert pane_exc.value.diag.constraint_name == "ux_lp_slot"


def test_d27_layout_owner_must_match_workspace_owner(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        a, b = _user(c), _user(c)
        wa = _workspace(c, a)
        with pytest.raises(pgerr.ForeignKeyViolation) as exc:
            _layout(c, wa, b)
        assert exc.value.diag.constraint_name == "fk_layouts_workspace_id_workspaces"
        lid = _layout(c, wa, a)
        with pytest.raises(pgerr.ForeignKeyViolation):
            c.execute("UPDATE layouts SET owner_user_id = %s WHERE id = %s", (b, lid))


def test_d27_drawing_cannot_reference_another_owners_layout(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        a, b = _user(c), _user(c)
        lb = _layout(c, _workspace(c, b), b)
        with pytest.raises(pgerr.ForeignKeyViolation) as exc:
            _drawing(c, a, lb)
        assert exc.value.diag.constraint_name == "fk_drawings_layout_id_layouts"


def test_d27_symbol_global_and_same_owner_drawings_are_accepted(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        a = _user(c)
        la = _layout(c, _workspace(c, a), a)
        assert _exists(c, "drawings", _drawing(c, a, None))
        assert _exists(c, "drawings", _drawing(c, a, la))


def test_d27_purging_one_owners_layout_never_deletes_another_owners_rows(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _active_owner(c)
        a, b = _user(c), _user(c)
        wa, wb = _workspace(c, a), _workspace(c, b)
        la, lb = _layout(c, wa, a), _layout(c, wb, b)
        _pane(c, la, 0)
        _pane(c, lb, 0, symbol="ETHUSDT")
        da_global, da_layout = _drawing(c, a, None), _drawing(c, a, la)
        db_layout = _drawing(c, b, lb)
        c.execute("DELETE FROM layouts WHERE id = %s", (lb,))
        assert not _exists(c, "drawings", db_layout)
        assert _exists(c, "drawings", da_layout) and _exists(c, "drawings", da_global)
        assert c.execute(
            "SELECT count(*) FROM layout_panes WHERE layout_id = %s", (lb,)
        ).fetchone() == (0,)
        assert c.execute(
            "SELECT count(*) FROM layout_panes WHERE layout_id = %s", (la,)
        ).fetchone() == (1,)
        c.execute("DELETE FROM workspaces WHERE id = %s", (wa,))
        assert not _exists(c, "layouts", la) and not _exists(c, "drawings", da_layout)
        assert _exists(c, "drawings", da_global)


def test_recorder_probe_uses_ix_lp_symbol_without_seq_scan(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        a, b = _user(c), _user(c)
        wa, wb = _workspace(c, a), _workspace(c, b)
        c.execute(
            "INSERT INTO layouts (id, workspace_id, owner_user_id, name) "
            "SELECT gen_random_uuid(), CASE WHEN g %% 2 = 0 THEN %s::uuid ELSE %s::uuid END, "
            "CASE WHEN g %% 2 = 0 THEN %s::uuid ELSE %s::uuid END, 'bulk-' || g "
            "FROM generate_series(1, 1000) g",
            (wa, wb, a, b),
        )
        c.execute(
            "INSERT INTO layout_panes (id, layout_id, slot_index, pane_kind, symbol) "
            "SELECT gen_random_uuid(), l.id, s, 'chart', "
            "'S' || ((row_number() OVER ()) % 200) || 'USDT' "
            "FROM layouts l CROSS JOIN generate_series(0, 15) s WHERE l.name LIKE 'bulk-%'"
        )
        for i in range(3):
            lid = _layout(c, wa if i % 2 else wb, a if i % 2 else b)
            _pane(c, lid, 0, symbol="BTCUSDT")
        c.execute("ANALYZE layouts")
        c.execute("ANALYZE layout_panes")
        pane_rows = c.execute(
            "SELECT lp.layout_id, lp.slot_index FROM layout_panes lp JOIN layouts l "
            "ON l.id = lp.layout_id WHERE lp.symbol = 'BTCUSDT' AND l.deleted_at IS NULL"
        ).fetchall()
        assert len(pane_rows) == 3
        plan = c.execute(
            "EXPLAIN (FORMAT JSON) SELECT EXISTS (SELECT 1 FROM layout_panes lp JOIN layouts l "
            "ON l.id = lp.layout_id WHERE lp.symbol = 'BTCUSDT' AND l.deleted_at IS NULL)"
        ).fetchone()
        assert plan is not None
        text = json.dumps(plan[0])
        assert '"Index Name": "ix_lp_symbol"' in text, text
        assert '"Node Type": "Seq Scan"' not in text, text


def test_downgrade_refuses_while_populated_then_succeeds_when_empty(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM drawings")
        c.execute("DELETE FROM workspaces")
        u = _user(c)
        w = _workspace(c, u)
        _layout(c, w, u)
        refused = _alembic(pg_dsn, "downgrade", "0021_drawings")
        assert refused.returncode != 0
        assert "downgrade refused" in refused.stderr
        assert c.execute("SELECT to_regclass('layouts')").fetchone() == ("layouts",)
        c.execute("DELETE FROM workspaces")
        assert _alembic(pg_dsn, "downgrade", "0021_drawings").returncode == 0
        assert c.execute("SELECT to_regclass('layouts')").fetchone() == (None,)
        assert c.execute("SELECT to_regclass('workspaces')").fetchone() == (None,)
        assert _alembic(pg_dsn, "upgrade", "head").returncode == 0
        assert c.execute("SELECT to_regclass('layout_panes')").fetchone() == ("layout_panes",)
