"""Integration (#492 S1): `SqlAlchemyRecordingReads` on real Postgres 16, rows read behind
`StoredRecordingControl`. A fresh database lists nothing; rows carry their latest session's state
(`idle` with none) and start; removed and other environments' rows never show (C-2.11); the
filters and the restricted view's filter hold; pages keep a stable `(symbol, id)` order. Sessions
come newest first with their gap counts, held to the env, a symbol and a window."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.recorder.control import HIDDEN_CAUSES, EntryQuery, StoredRecordingControl
from candleviewer.storage.repositories.recording_reads_sqlalchemy import SqlAlchemyRecordingReads
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration
_T0 = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def dsns() -> Iterator[tuple[str, str]]:
    with PostgresContainer("postgres:16-alpine") as c:
        base = c.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        root, env = Path(__file__).resolve().parents[3], {**os.environ, "CV_PG_DSN": base}
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, env=env,
                       check=True)  # fmt: skip
        yield base.replace("+psycopg", ""), base.replace("+psycopg", "+asyncpg")


@pytest.fixture
def conn(dsns: tuple[str, str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(dsns[0], autocommit=True) as c:
        c.execute("TRUNCATE recording_gaps, recording_sessions, recorded_symbols CASCADE")
        c.execute(
            "INSERT INTO instruments (symbol, base_coin, status, tick_size, qty_step, "
            "min_order_qty, max_order_qty, max_leverage, raw) SELECT s, 'X', 'Trading', 1, 1, "
            "1, 1, 1, '{}' FROM unnest(ARRAY['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT']) s "
            "ON CONFLICT DO NOTHING"
        )
        yield c


@pytest.fixture
def reads(dsns: tuple[str, str]) -> SqlAlchemyRecordingReads:
    return SqlAlchemyRecordingReads(SqlAlchemyRelationalRepository(dsns[1]))


@pytest.fixture
def control(reads: SqlAlchemyRecordingReads) -> StoredRecordingControl:
    return StoredRecordingControl(reads, "demo")


def _row(c: psycopg.Connection, sym: str, reason: str = "manual", env: str = "demo",
         pinned: bool = False, removed: bool = False) -> str:  # fmt: skip
    row = c.execute("INSERT INTO recorded_symbols (id, symbol, env, reason, pinned, auto_added_at, "
                    "removed_at) VALUES (gen_random_uuid(), %s, %s::exchange_env, "
                    "%s::record_reason, %s, now(), CASE WHEN %s THEN now() END) RETURNING id::text",
                    (sym, env, reason, pinned, removed)).fetchone()  # fmt: skip
    assert row is not None
    return str(row[0])


def _session(c: psycopg.Connection, rsid: str, sym: str, state: str, hour: int,
             gaps: int = 0) -> str:  # fmt: skip
    start = _T0 + timedelta(hours=hour)
    end = start + timedelta(hours=1) if state == "stopped" else None
    row = c.execute(
        "INSERT INTO recording_sessions (id, recorded_symbol_id, symbol, state, streams, "
        "orderbook_depth, ws_endpoint, started_at, ended_at) VALUES (gen_random_uuid(), %s, %s, "
        "%s::recording_state, '{trades}', 200, 'public', %s, %s) RETURNING id::text",
        (rsid, sym, state, start, end),
    ).fetchone()
    assert row is not None
    for n in range(gaps):
        window = (start + timedelta(minutes=n), start + timedelta(minutes=n + 1))
        c.execute(
            "INSERT INTO recording_gaps (recording_session_id, symbol, stream, gap_start, "
            "gap_end, cause) VALUES (%s, %s, 'trades', %s, %s, 'seq_jump')",
            (row[0], sym, *window),
        )
    return str(row[0])


async def test_rows_carry_their_latest_session_and_stay_in_their_env(
    conn: psycopg.Connection, control: StoredRecordingControl
) -> None:
    assert (await control.list(EntryQuery())).items == ()  # a fresh database lists nothing
    btc = _row(conn, "BTCUSDT", pinned=True)
    _session(conn, btc, "BTCUSDT", "stopped", 1)
    _session(conn, btc, "BTCUSDT", "recording", 5)
    _session(conn, _row(conn, "ETHUSDT", "chart_open"), "ETHUSDT", "starting", 6)
    _row(conn, "SOLUSDT", removed=True)
    live = _row(conn, "XRPUSDT", env="live")
    items = (await control.list(EntryQuery())).items
    assert [(e.symbol, e.state, e.reason, e.pinned, e.started_at) for e in items] == [
        ("BTCUSDT", "recording", "manual", True, _T0 + timedelta(hours=5)),
        ("ETHUSDT", "starting", "chart_open", False, None),
    ]
    assert (items[0].streams, items[0].depth) == (
        ("trades", "orderbook_delta", "tickers", "liquidations"), 200)  # fmt: skip
    assert await control.get(btc) == items[0] and await control.get(live) is None


async def test_filters_pages_and_the_restricted_view(
    conn: psycopg.Connection, control: StoredRecordingControl
) -> None:
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        _row(conn, sym)
    _row(conn, "XRPUSDT", "position_open")
    first = await control.list(EntryQuery(limit=2))
    assert [e.symbol for e in first.items] == ["BTCUSDT", "ETHUSDT"] and first.has_more
    rest = await control.list(EntryQuery(after=(first.items[-1].symbol, first.items[-1].id)))
    assert [e.symbol for e in rest.items] == ["SOLUSDT", "XRPUSDT"] and not rest.has_more
    shown = await control.list(EntryQuery(hidden=HIDDEN_CAUSES))
    assert [e.symbol for e in shown.items] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    hit = await control.list(EntryQuery(reason="position_open", state="idle", pinned=False))
    assert [e.symbol for e in hit.items] == ["XRPUSDT"]
    assert (await control.list(EntryQuery(state="recording"))).items == ()


async def test_sessions_page_newest_first_with_gap_counts(
    conn: psycopg.Connection, reads: SqlAlchemyRecordingReads
) -> None:
    btc = _row(conn, "BTCUSDT")
    old = _session(conn, btc, "BTCUSDT", "stopped", 1, gaps=2)
    new = _session(conn, btc, "BTCUSDT", "recording", 5)
    _session(conn, _row(conn, "ETHUSDT", "position_open"), "ETHUSDT", "recording", 3, gaps=1)
    _session(conn, _row(conn, "XRPUSDT", env="live"), "XRPUSDT", "recording", 4)

    async def page(**q: Any) -> list[dict[str, Any]]:
        base: dict[str, Any] = {"env": "demo", "symbol": None, "since": None, "until": None}
        base |= {"after": None, "hidden": tuple(HIDDEN_CAUSES), "limit": 9}
        return await reads.sessions_page(**(base | q))

    every = await page(hidden=())
    assert [(r["id"], r["symbol"], r["gap_count"]) for r in every][::2] == [
        (new, "BTCUSDT", 0), (old, "BTCUSDT", 2)]  # fmt: skip
    assert (every[1]["symbol"], every[1]["gap_count"], every[0]["recorded_symbol_id"]) == (
        "ETHUSDT", 1, btc)  # fmt: skip
    older = await page(symbol="BTCUSDT", until=_T0 + timedelta(hours=4),
                       after=(every[0]["started_at"], new))  # fmt: skip
    assert [r["id"] for r in older] == [old]
    assert [r["id"] for r in await page(since=_T0 + timedelta(hours=2))] == [new]
