"""Integration: `0067_rg_cause_maintenance_pause` on real Postgres 16 (#5629).

The round trip on the empty table (C-5.5), then a seeded one: a `maintenance_pause` row refuses the
downgrade (C-5.2); without it the downgrade restores 0011's five causes, refuses
`maintenance_pause` again, and `upgrade head` widens it once more. `testcontainers`; CI's
`integration` job, or `CV_CHAOS_STACK=1` (never a fixed-port stack).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr
from testcontainers.postgres import PostgresContainer

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CV_CHAOS_STACK") == "1"),
        reason="starts its own Postgres container: CI's integration job, or CV_CHAOS_STACK=1",
    ),
]

_ROOT = Path(__file__).resolve().parents[3]
_REVISION_FILE = (
    _ROOT / "candleviewer" / "migrations" / "versions"
    / "0067_rg_cause_maintenance_pause.py"
)  # fmt: skip

Conn = psycopg.Connection[tuple[Any, ...]]


def _down_revision() -> str:
    spec = importlib.util.spec_from_file_location("rev_0067_it", _REVISION_FILE)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return str(revision.down_revision)


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#5629)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _session(c: Conn) -> str:
    """One recorded symbol and one session to hang gap rows on."""
    c.execute(
        "INSERT INTO instruments (symbol, base_coin, status, tick_size, qty_step, min_order_qty, "
        "max_order_qty, max_leverage, raw) VALUES ('BTCUSDT', 'X', 'Trading', 1, 1, 1, 1, 1, "
        "'{}') ON CONFLICT DO NOTHING"
    )
    rsid = c.execute(
        "INSERT INTO recorded_symbols (id, symbol, reason, env) "
        "VALUES (gen_random_uuid(), 'BTCUSDT', 'manual', 'demo') RETURNING id"
    ).fetchone()
    assert rsid is not None
    sid = c.execute(
        "INSERT INTO recording_sessions (id, recorded_symbol_id, symbol, streams, "
        "orderbook_depth, ws_endpoint) VALUES (gen_random_uuid(), %s, 'BTCUSDT', "
        "ARRAY['trades']::stream_kind[], 200, 'public') RETURNING id",
        (rsid[0],),
    ).fetchone()
    assert sid is not None
    return str(sid[0])


def _gap(c: Conn, sid: str, cause: str) -> None:
    c.execute(
        "INSERT INTO recording_gaps (recording_session_id, symbol, stream, gap_start, gap_end, "
        "cause) VALUES (%s, 'BTCUSDT', 'trades', now() - interval '1 minute', now(), %s)",
        (sid, cause),
    )


def _check(c: Conn) -> tuple[Any, ...] | None:
    return c.execute(
        "SELECT pg_get_constraintdef(oid), convalidated FROM pg_constraint "
        "WHERE conname = 'rg_cause'"
    ).fetchone()


def test_round_trip_on_an_empty_table(pg_dsn: str) -> None:
    """C-5.5: up, down, up with no gap row; the widened CHECK is validated each time."""
    for step in (("upgrade", "head"), ("downgrade", _down_revision()), ("upgrade", "head")):
        done = _alembic(pg_dsn, *step)
        assert done.returncode == 0, done.stderr
    with _conn(pg_dsn) as c:
        found = _check(c)
        assert found is not None and "'maintenance_pause'::text" in found[0] and found[1] is True


def test_a_maintenance_pause_row_refuses_the_downgrade_until_it_is_gone(pg_dsn: str) -> None:
    prev = _down_revision()
    done = _alembic(pg_dsn, "upgrade", "head")
    assert done.returncode == 0, done.stderr
    with _conn(pg_dsn) as c:
        sid = _session(c)
        _gap(c, sid, "maintenance_pause")
        _gap(c, sid, "ws_disconnect")
        with pytest.raises(pgerr.CheckViolation):
            _gap(c, sid, "nope")
        refused = _alembic(pg_dsn, "downgrade", prev)
        assert refused.returncode != 0
        assert "downgrade refused" in refused.stderr
        assert "'maintenance_pause'::text" in (_check(c) or ("",))[0]
        c.execute("DELETE FROM recording_gaps WHERE cause = 'maintenance_pause'")
        done = _alembic(pg_dsn, "downgrade", prev)
        assert done.returncode == 0, done.stderr
        narrowed = _check(c)
        assert narrowed is not None and "maintenance_pause" not in narrowed[0]
        assert narrowed[1] is True
        with pytest.raises(pgerr.CheckViolation):
            _gap(c, sid, "maintenance_pause")
        assert c.execute("SELECT count(*) FROM recording_gaps").fetchone() == (1,)
        done = _alembic(pg_dsn, "upgrade", "head")
        assert done.returncode == 0, done.stderr
        _gap(c, sid, "maintenance_pause")
