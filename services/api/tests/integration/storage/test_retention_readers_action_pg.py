"""Integration (#2188 S2c): both retention readers (the roll-off and the klines boundary through
`SqlAlchemyRecorderRepository`, the reaper through `PgRetentionFacts`) read a stored
`retention_policies` row by its `action` on real Postgres 16 and agree; a `drop` row stored as
#492 S4 stores it is honoured at its own N by the real reaper and roll-off over in-memory stores."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.recorder.retention import RetentionConfig
from candleviewer.recorder.retention_defaults import STREAM_DEFAULTS
from candleviewer.recorder.rolloff import RollOffConfig
from candleviewer.retention_wiring import PgRetentionFacts, replay_retention_guard
from candleviewer.settings import Settings
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorder_sqlalchemy import SqlAlchemyRecorderRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.retention.policy import RowReading
from tests.unit.recorder._retention_fakes import T, World, day, manager
from tests.unit.recorder.test_rolloff import FakeArchiver, FakeHot, FakeMarks, _job

pytestmark = pytest.mark.integration

SYM = "BTCUSDT"
N = 12


@pytest.fixture(scope="module")
def dsns() -> Iterator[tuple[str, str]]:
    with PostgresContainer("postgres:16-alpine") as c:
        base = c.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).resolve().parents[3],
            env={**os.environ, "CV_PG_DSN": base},
            check=True,
        )
        yield base.replace("+psycopg", ""), base.replace("+psycopg", "+asyncpg")


@pytest.fixture
def conn(dsns: tuple[str, str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(dsns[0], autocommit=True) as c:
        c.execute("TRUNCATE recording_gaps, recording_sessions, recorded_symbols CASCADE")
        c.execute("DELETE FROM retention_policies")  # each test states the rows it reads
        c.execute(
            "INSERT INTO instruments (symbol, base_coin, status, tick_size, qty_step, "
            "min_order_qty, max_order_qty, max_leverage, raw) SELECT 'BTCUSDT', 'X', 'Trading', "
            "1, 1, 1, 1, 1, '{}' ON CONFLICT DO NOTHING"
        )
        yield c


def _store(conn: psycopg.Connection, action: str, scope: str, stream: str) -> None:
    """A row straight into the table, as #492 S4 stores it (no #492 code), `retain_days` N."""
    conn.execute(
        "INSERT INTO retention_policies (id, scope, symbol, stream, retain_days, action) VALUES "
        "(gen_random_uuid(), %s, %s, %s::stream_kind, %s, %s::retention_action)",
        (scope, SYM if scope == "symbol" else None, stream, N, action),
    )


def _record(conn: psycopg.Connection, *, pinned: bool = False) -> None:
    conn.execute(
        "INSERT INTO recorded_symbols (id, symbol, pinned) VALUES (gen_random_uuid(), %s, %s)",
        (SYM, pinned),
    )


def _readers(dsns: tuple[str, str]) -> tuple[SqlAlchemyRecorderRepository, PgRetentionFacts]:
    rel = SqlAlchemyRelationalRepository(dsns[1])
    return SqlAlchemyRecorderRepository(rel), PgRetentionFacts(
        rel, replay_retention_guard(Settings(), rel)
    )


@pytest.mark.parametrize("stream", ["trades", "klines"])  # §7 total: 730 d; forever
@pytest.mark.parametrize("scope", ["symbol", "default"])
@pytest.mark.parametrize("action", ["drop", "archive_parquet"])
async def test_both_readers_read_a_stored_row_by_its_action_and_agree(
    dsns: tuple[str, str], conn: psycopg.Connection, action: str, scope: str, stream: str
) -> None:
    _store(conn, action, scope, stream)
    repo, facts = _readers(dsns)
    expected = RowReading(N, N) if action == "drop" else RowReading(N, None)
    assert await repo.policy_reading(SYM, stream) == expected
    # The roll-off's window and the klines boundary are the reading's hot window ...
    assert await repo.resolve_policy(SYM, stream) == expected.hot_days
    assert await repo.explicit_policy_days(SYM, stream) == expected.hot_days
    # ... and the reaper's facts hold that hot window, with the horizon the row states (`drop`: N),
    # else the stream's §7 total, never shorter than the hot window.
    row = (await facts.policies())[(None if scope == "default" else SYM, stream)]
    section7 = STREAM_DEFAULTS[stream][1]
    assert row.hot_days == expected.hot_days
    assert row.total_days == (N if action == "drop" else section7 and max(section7, N))


@pytest.mark.parametrize("stream", [StreamKind.TRADES, StreamKind.LIQUIDATIONS])  # 730 d; forever
async def test_stored_drop_row_is_honoured_at_its_own_horizon(
    dsns: tuple[str, str], conn: psycopg.Connection, stream: StreamKind
) -> None:
    """A `drop` row stored before this slice acts at its own N in BOTH consumers: the reaper
    deletes the cold partition N days old (not at the §7 total; for liquidations, which §7 keeps
    forever, the first time) and keeps one a day short; the roll-off takes a hot day past N."""
    _store(conn, "drop", "symbol", stream.value)
    _record(conn)
    repo, facts = _readers(dsns)
    w = World()
    kept, due = w.add_cold(SYM, stream, N), w.add_cold(SYM, stream, N + 1)
    cfg = RetentionConfig(hot_streams=(stream,), cold_streams=(stream,), hard_default=(7, 30))
    w.facts = facts
    await manager(w, config=cfg).run_nightly()
    assert set(w.cold[(SYM, stream)]) == {kept} and due not in w.cold[(SYM, stream)]

    async def hot_days(symbol: str, kind: StreamKind) -> int | None:  # as `rolloff_wiring`'s
        return await repo.resolve_policy(symbol, kind.value)

    hot = FakeHot({stream: {day(N + 4): [SYM], day(N - 2): [SYM]}})
    config = RollOffConfig(streams=(stream,))
    await _job(hot, FakeArchiver(), FakeMarks(), hot_days=hot_days, config=config).run()
    assert hot.dropped == [(stream, day(N + 4))]


@pytest.mark.parametrize("action", ["drop", "archive_parquet"])
async def test_a_pinned_symbol_is_never_deleted_whatever_its_row_says(
    dsns: tuple[str, str], conn: psycopg.Connection, action: str
) -> None:
    _store(conn, action, "symbol", "trades")
    _record(conn, pinned=True)
    repo, facts = _readers(dsns)
    assert await repo.resolve_policy(SYM, "trades") is None  # infinite: never rolled off
    assert await repo.explicit_policy_days(SYM, "trades") is None
    assert await repo.policy_reading(SYM, "trades") is None
    assert await facts.pinned() == {SYM}
    w = World()
    w.add_cold(SYM, T, 1500)  # older than any horizon
    w.add_hot(T, 400, {SYM: 3})
    w.archived[(SYM, T)] = day(0)
    w.facts = facts
    await manager(w).run_nightly()
    assert w.deletes == []
