"""Integration: `0021_drawings` against real Postgres 16 (E14-T01).

Not run locally (no docker socket in WSL); exercised by the integration CI job.
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
_TOOLS = (
    "trendline,horizontal_line,vertical_line,ray,extended_line,"
    "parallel_channel,rectangle,ellipse,triangle,fib_retracement,"
    "fib_extension,fib_timezone,pitchfork,gann_fan,text,"
    "arrow,callout,measure,long_position,short_position,"
    "price_range,date_range,brush,polyline,anchored_vwap"
).split(",")
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
        (uid, f"{uid[:8]}@x.io", f"u{uid[:8]}"),
    )
    return uid


def _drawing(
    c: Conn,
    owner: str,
    *,
    tool: str = "trendline",
    geometry: str = _GEOM,
    symbol: str = "BTCUSDT",
    alert_id: str | None = None,
) -> str:
    did = str(uuid.uuid4())
    c.execute(
        "INSERT INTO drawings (id, owner_user_id, symbol, tool, geometry, alert_id) "
        "VALUES (%s, %s, %s, %s, %s::jsonb, %s)",
        (did, owner, symbol, tool, geometry, alert_id),
    )
    return did


def test_dr_tool_rejects_unknown_and_accepts_all_25(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        owner = _user(c)
        with pytest.raises(pgerr.CheckViolation):
            _drawing(c, owner, tool="scribble")
        for tool in _TOOLS:
            _drawing(c, owner, tool=tool)
        row = c.execute(
            "SELECT count(*) FROM drawings WHERE owner_user_id = %s", (owner,)
        ).fetchone()
        assert row == (25,)


@pytest.mark.parametrize("geometry", ["{}", "[]", '"x"', "1", "null", '{"levels": []}'])
def test_dr_geom_rejects_missing_points_and_non_objects(pg_dsn: str, geometry: str) -> None:
    with _conn(pg_dsn) as c:
        owner = _user(c)
        with pytest.raises(pgerr.CheckViolation):
            _drawing(c, owner, geometry=geometry)


def test_symbol_domain_rejects_over_20_chars(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        owner = _user(c)
        _drawing(c, owner, symbol="A" * 20)
        with pytest.raises(pgerr.Error):
            _drawing(c, owner, symbol="A" * 21)


def test_user_delete_cascades_drawings(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        owner = _user(c)
        did = _drawing(c, owner)
        c.execute("DELETE FROM users WHERE id = %s", (owner,))
        assert c.execute("SELECT 1 FROM drawings WHERE id = %s", (did,)).fetchone() is None


def test_alert_delete_sets_alert_id_null(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        owner = _user(c)
        aid = str(uuid.uuid4())
        c.execute(
            "INSERT INTO alerts (id, owner_user_id, name, condition_ir, condition_hash) "
            "VALUES (%s, %s, %s, '{}'::jsonb, %s)",
            (aid, owner, f"a-{aid}", "c" * 64),
        )
        did = _drawing(c, owner, alert_id=aid)
        c.execute("DELETE FROM alerts WHERE id = %s", (aid,))
        row = c.execute("SELECT alert_id FROM drawings WHERE id = %s", (did,)).fetchone()
        assert row == (None,)


def test_user_symbol_index_serves_the_list_query(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        owner = _user(c)
        c.execute(
            "INSERT INTO drawings (id, owner_user_id, symbol, tool, geometry) "
            "SELECT gen_random_uuid(), u.id, 'S' || (g % 200) || 'USDT', 'trendline', %s::jsonb "
            "FROM generate_series(1, 20000) g CROSS JOIN LATERAL "
            "(SELECT id FROM users ORDER BY id LIMIT 1) u",
            (_GEOM,),
        )
        # Spread rows over many owners so the (owner, symbol) predicate is selective.
        for _ in range(30):
            other = _user(c)
            c.execute(
                "INSERT INTO drawings (id, owner_user_id, symbol, tool, geometry) "
                "SELECT gen_random_uuid(), %s, 'S' || (g % 200) || 'USDT', 'trendline', %s::jsonb "
                "FROM generate_series(1, 700) g",
                (other, _GEOM),
            )
        _drawing(c, owner, symbol="BTCUSDT")
        c.execute("ANALYZE drawings")
        plan = "\n".join(
            str(r[0])
            for r in c.execute(
                "EXPLAIN SELECT id FROM drawings "
                "WHERE owner_user_id = %s AND symbol = %s AND deleted_at IS NULL",
                (owner, "BTCUSDT"),
            ).fetchall()
        )
        assert "ix_dr_user_symbol" in plan, plan


def test_downgrade_refuses_while_populated_then_succeeds_when_empty(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM drawings")
        owner = _user(c)
        _drawing(c, owner)
        refused = _alembic(pg_dsn, "downgrade", "0020_kek_versions")
        assert refused.returncode != 0
        assert "downgrade refused" in refused.stderr
        assert c.execute("SELECT to_regclass('drawings')").fetchone() == ("drawings",)
        c.execute("DELETE FROM drawings")
        assert _alembic(pg_dsn, "downgrade", "0020_kek_versions").returncode == 0
        assert c.execute("SELECT to_regclass('drawings')").fetchone() == (None,)
        assert _alembic(pg_dsn, "upgrade", "head").returncode == 0
