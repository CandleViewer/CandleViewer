"""Integration (#5629): maintenance mode holds the recorder and its interval lands in
`recording_gaps` as `maintenance_pause` on real Postgres 16 (Alembic head, 0067 included).

The real `SessionManager` over `SqlAlchemyRecorderRepository`, a `StreamWriter` with an in-memory
sink (QuestDB is not the subject), `RecorderPause` as the maintenance controller's
`RecorderControl`, and the controller driven through `FlagWriter` with `keep_recorder = false`.
Starts its own Postgres container: CI's integration job, or `CV_CHAOS_STACK=1`."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.flags import (
    MAINTENANCE_KEEP_RECORDER,
    MAINTENANCE_MODE,
    FlagService,
    FlagWriter,
    MaintenanceController,
    MaintenanceGate,
    chain_hooks,
    default_registry,
)
from candleviewer.audit.access import AuditPrincipal
from candleviewer.recorder.models import RecorderSetChanged
from candleviewer.recorder.pause import RecorderPause
from candleviewer.recorder.sessions import DEFAULT_STREAMS, SessionConfig, SessionManager, to_us
from candleviewer.storage.repositories.recorder_sqlalchemy import SqlAlchemyRecorderRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.unit.admin.flag_fakes import Clock, FakeFlagStore, FakeStepUp, FakeUsers
from tests.unit.admin.flag_fakes import FakeAudit as FlagAudit
from tests.unit.recorder._fakes import FakeAudit
from tests.unit.recorder._writer_helpers import make_writer, trade

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CV_CHAOS_STACK") == "1"),
        reason="starts its own Postgres container: CI's integration job, or CV_CHAOS_STACK=1",
    ),
]
T0 = int(datetime(2026, 11, 3, 18, 0, tzinfo=UTC).timestamp() * 1_000_000)
_OWNER = AuditPrincipal(user_id=UUID(int=1), username="owner", permissions=frozenset({"*"}))


@pytest.fixture(scope="module")
def dsns() -> Iterator[tuple[str, str]]:
    with PostgresContainer("postgres:16-alpine") as c:
        base = c.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        root, env = Path(__file__).resolve().parents[3], {**os.environ, "CV_PG_DSN": base}
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, env=env,
                       check=True)  # fmt: skip
        yield base.replace("+psycopg", ""), base.replace("+psycopg", "+asyncpg")


class _UsClock:
    def __init__(self) -> None:
        self.t = T0

    def __call__(self) -> int:
        return self.t


async def test_enter_holds_the_recorder_and_exit_writes_the_maintenance_pause_gaps(
    dsns: tuple[str, str], tmp_path: Path
) -> None:
    with psycopg.connect(dsns[0], autocommit=True) as conn:
        conn.execute("TRUNCATE recording_gaps, recording_sessions, recorded_symbols CASCADE")
        conn.execute(
            "INSERT INTO instruments (symbol, base_coin, status, tick_size, qty_step, "
            "min_order_qty, max_order_qty, max_leverage, raw) VALUES ('BTCUSDT', 'X', 'Trading', "
            "1, 1, 1, 1, 1, '{}') ON CONFLICT DO NOTHING"
        )
    repo = SqlAlchemyRecorderRepository(SqlAlchemyRelationalRepository(dsns[1]))
    clock = _UsClock()
    sessions = SessionManager(repo, now_us=clock, audit=FakeAudit(),
                              config=SessionConfig(env="demo"))  # fmt: skip
    added = RecorderSetChanged(symbol="BTCUSDT", change="added", reason="manual",
                               reasons=("manual",), priority=300, auto_evictable=False,
                               ts_event=T0)  # fmt: skip
    await sessions.on_set_changed(added)
    writer, *_ = await make_writer(tmp_path, env="demo")
    pause = RecorderPause(writer, sessions, now_us=clock, flush_timeout_s=5.0, gap_timeout_s=5.0)
    flags = FakeFlagStore()
    service = FlagService(default_registry(), flags, clock=Clock())
    await flags.ensure(service.registry.values())
    controller = MaintenanceController(service, MaintenanceGate(), notify=lambda _on: None,
                                       audit=FlagAudit(), recorder=pause)  # fmt: skip
    flag_writer = FlagWriter(
        service, FlagAudit(), FakeStepUp(), FakeUsers(),
        on_change=chain_hooks(controller.gate_hook, controller.effects_hook),
    )  # fmt: skip
    await controller.refresh()

    async def toggle(key: str, value: bool) -> None:
        await flag_writer.set(key, _OWNER, value=value, reason="maintenance window",
                              expected_updated_at=flags.rows[key].updated_at)  # fmt: skip

    await toggle(MAINTENANCE_KEEP_RECORDER, False)
    clock.t += 1_000_000
    paused_at = clock.t
    await toggle(MAINTENANCE_MODE, True)
    assert writer.held
    await writer.on_trade(trade(1))
    assert writer.backlog_rows == 0
    clock.t += 120_000_000
    await toggle(MAINTENANCE_MODE, False)
    assert not writer.held
    with psycopg.connect(dsns[0], autocommit=True) as conn:
        rows = conn.execute(
            "SELECT stream::text, gap_start, gap_end, cause FROM recording_gaps ORDER BY stream"
        ).fetchall()
    assert sorted((s, to_us(lo), to_us(hi), c) for s, lo, hi, c in rows) == sorted(
        (s, paused_at, paused_at + 120_000_000, "maintenance_pause") for s in DEFAULT_STREAMS
    )
    await sessions.stop()
