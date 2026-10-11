"""Integration: `0011_recorder` + `SqlAlchemyRecorderRepository` on real Postgres 16 (E16-T01).

Covers the ticket Gherkin: round-trip, duplicate active recording, most-specific-first
policy resolution, pinned override, degenerate gap. Not run locally (no docker);
exercised by the integration CI job.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.recorder_sqlalchemy import SqlAlchemyRecorderRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]


def _alembic(psycopg_dsn: str, *args: str) -> None:
    subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": psycopg_dsn},
        check=True,
    )


@pytest.fixture(scope="module")
def dsns() -> Iterator[tuple[str, str]]:
    with PostgresContainer("postgres:16-alpine") as c:
        base = c.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        _alembic(base, "upgrade", "head")
        _alembic(base, "downgrade", "-1")
        _alembic(base, "upgrade", "head")
        yield base.replace("+psycopg", ""), base.replace("+psycopg", "+asyncpg")


@pytest.fixture
def conn(dsns: tuple[str, str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(dsns[0], autocommit=True) as c:
        c.execute("TRUNCATE recording_gaps, recording_sessions, recorded_symbols CASCADE")
        c.execute("DELETE FROM retention_policies WHERE scope = 'symbol'")
        c.execute(
            "INSERT INTO instruments (symbol, base_coin, status, tick_size, qty_step, "
            "min_order_qty, max_order_qty, max_leverage, raw) SELECT s, 'X', 'Trading', 1, 1, "
            "1, 1, 1, '{}' FROM unnest(ARRAY['BTCUSDT','ETHUSDT']) s ON CONFLICT DO NOTHING"
        )
        yield c


def _add(conn: psycopg.Connection, sym: str, **kw: object) -> str:
    row = conn.execute(
        "INSERT INTO recorded_symbols (id, symbol, pinned) VALUES (gen_random_uuid(), %s, %s) "
        "RETURNING id::text",
        (sym, kw.get("pinned", False)),
    ).fetchone()
    assert row is not None
    return str(row[0])


def test_seed_has_one_default_row_per_stream(conn: psycopg.Connection) -> None:
    row = conn.execute("SELECT count(*) FROM retention_policies WHERE scope='default'").fetchone()
    assert row == (8,)


def test_duplicate_active_recording_fails_on_ux_rs_symbol(conn: psycopg.Connection) -> None:
    first = _add(conn, "BTCUSDT")
    with pytest.raises(psycopg.errors.UniqueViolation) as ei:
        _add(conn, "BTCUSDT")
    assert "ux_rs_symbol" in str(ei.value)
    conn.execute("UPDATE recorded_symbols SET removed_at = now() WHERE id = %s::uuid", (first,))
    _add(conn, "BTCUSDT")


def test_degenerate_gap_rejected_by_rg_window(conn: psycopg.Connection) -> None:
    rs = _add(conn, "BTCUSDT")
    sid = conn.execute(
        "INSERT INTO recording_sessions (id, recorded_symbol_id, symbol, streams, "
        "orderbook_depth, ws_endpoint) VALUES (gen_random_uuid(), %s::uuid, 'BTCUSDT', "
        "'{trades}', 200, 'x') RETURNING id::text",
        (rs,),
    ).fetchone()
    assert sid is not None
    with pytest.raises(psycopg.errors.CheckViolation) as ei:
        conn.execute(
            "INSERT INTO recording_gaps (recording_session_id, symbol, stream, gap_start, "
            "gap_end, cause) VALUES (%s::uuid, 'BTCUSDT', 'trades', now(), now(), 'seq_jump')",
            (sid[0],),
        )
    assert "rg_window" in str(ei.value)


async def test_policy_resolution_most_specific_then_pinned(
    dsns: tuple[str, str], conn: psycopg.Connection
) -> None:
    repo = SqlAlchemyRecorderRepository(SqlAlchemyRelationalRepository(dsns[1]))
    conn.execute(
        "INSERT INTO retention_policies (id, scope, symbol, stream, retain_days) "
        "VALUES (gen_random_uuid(), 'symbol', 'ETHUSDT', 'trades', 3)"
    )
    assert await repo.resolve_policy("ETHUSDT", "trades") == 3
    assert await repo.resolve_policy("BTCUSDT", "trades") == 30
    _add(conn, "BTCUSDT", pinned=True)
    assert await repo.resolve_policy("BTCUSDT", "trades") is None
    assert await repo.resolve_policy("BTCUSDT", "klines") is None


async def test_repository_lifecycle(dsns: tuple[str, str], conn: psycopg.Connection) -> None:
    repo = SqlAlchemyRecorderRepository(SqlAlchemyRelationalRepository(dsns[1]))
    ref = {"kind": "chart", "id": "c1"}
    rid = await repo.upsert_auto("BTCUSDT", "chart_open", ref)
    assert await repo.upsert_auto("BTCUSDT", "chart_open", ref) == rid
    await repo.add_reason_ref(rid, {"kind": "position", "id": "p1"})
    row = await repo.get_by_symbol("BTCUSDT")
    assert row is not None and len(row["reason_refs"]) == 2
    await repo.remove_reason_ref(rid, ref)
    row = await repo.get_by_symbol("BTCUSDT")
    assert row is not None and row["reason_refs"] == [{"kind": "position", "id": "p1"}]
    sid = await repo.open_session(
        recorded_symbol_id=rid,
        symbol="BTCUSDT",
        streams=["trades"],
        orderbook_depth=200,
        ws_endpoint="wss://example.invalid",
    )
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    await repo.record_gap(
        session_id=sid,
        symbol="BTCUSDT",
        stream="trades",
        gap_start=t0,
        gap_end=t1,
        cause="ws_disconnect",
    )
    assert await repo.close_session(sid, "manual_stop")
    assert await repo.soft_remove(rid)
    assert await repo.list_recorded() == []


async def test_e16_t04_session_gap_coverage_round_trip(
    dsns: tuple[str, str], conn: psycopg.Connection
) -> None:
    """E16-T04: crash-close + gap + coverage query against real Postgres (tiers: no watermark
    store wired here -> all `questdb`; tier split is unit-tested)."""
    from candleviewer.recorder.coverage import CoverageService
    from candleviewer.recorder.models import RecorderSetChanged
    from candleviewer.recorder.sessions import SessionManager, to_us

    repo = SqlAlchemyRecorderRepository(SqlAlchemyRelationalRepository(dsns[1]))
    t0 = to_us(datetime(2026, 9, 1, tzinfo=UTC))
    clock = [t0]
    dead = SessionManager(repo, now_us=lambda: clock[0])
    ev = RecorderSetChanged(symbol="BTCUSDT", change="added", reason="manual",
                            reasons=("manual",), priority=300, auto_evictable=False,
                            ts_event=t0)  # fmt: skip
    await dead.on_set_changed(ev)
    sid = dead.live_session("BTCUSDT")
    assert sid is not None
    await repo.touch_session_events(sid, first=datetime(2026, 9, 1, 0, 0, 1, tzinfo=UTC),
                                    last=datetime(2026, 9, 1, 1, tzinfo=UTC))  # fmt: skip
    restart = to_us(datetime(2026, 9, 1, 1, 5, tzinfo=UTC))
    clock[0] = restart
    fresh = SessionManager(repo, now_us=lambda: clock[0])
    assert await fresh.recover_on_startup(restart) == 1
    assert await repo.list_live_sessions() == []
    svc = CoverageService(repo, now_us=lambda: clock[0])
    (cov,) = await svc.coverage("BTCUSDT", ["trades"], t0, restart)
    assert [(i.lo, i.hi, i.tier) for i in cov.intervals] == [
        (t0, to_us(datetime(2026, 9, 1, 1, tzinfo=UTC)), "questdb")
    ]
    assert [g.cause for g in cov.gaps] == ["process_restart"]
    assert await svc.recording_started_at_us("BTCUSDT") == t0 + 1_000_000
    row = conn.execute(
        "SELECT state::text, end_reason FROM recording_sessions WHERE id = %s", (sid,)
    ).fetchone()
    assert row == ("stopped", "process_restart")
