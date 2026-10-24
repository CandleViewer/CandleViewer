"""Integration (#492 S9): the recording lifecycle against the composed runtime on real Postgres 16.

The pieces S9 can compose before #2188 S4b lands its wiring: the real `RecordingPolicy` (with
#2188 S3c's relax guard and retention writes), the real `SessionManager`
mirroring B11 and the policy's bus, `SqlAlchemyRecorderRepository` as the policy's store, and
`SqlAlchemyRecordingReads` as the rows; `RuntimeRecordingControl` over them, and the 1 Hz
`RecordingStatusCache` whose snapshots the `recorder` WS topic carries. A fake feed reports rows.

Add, the status transitions, pin, retention, stop: the row lingers until the grace window ends,
then the session closes, and the recorded session (the data's coverage) stays queryable (AC3).
Purge is not driven here: its deletion runs through `RetentionManager` over QuestDB and Parquet
(E16-T06; AC4 is pinned by `tests/unit/api/test_recorder_purge.py`)."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.bus.models import Topic
from candleviewer.recorder import control as rc
from candleviewer.recorder.control_runtime import RuntimeRecordingControl
from candleviewer.recorder.models import RecorderSetChanged
from candleviewer.recorder.policy import PolicyConfig, RecordingPolicy, user_actor
from candleviewer.recorder.sessions import SessionConfig, SessionManager
from candleviewer.recorder.status import RecordingStatusCache
from candleviewer.storage.repositories.recorder_sqlalchemy import SqlAlchemyRecorderRepository
from candleviewer.storage.repositories.recording_reads_sqlalchemy import SqlAlchemyRecordingReads
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
OWNER = user_actor(str(uuid.UUID(int=1)))
MANAGER = user_actor(str(uuid.UUID(int=2)))
CONFIG = PolicyConfig(max_symbols=5)


@pytest.fixture(scope="module")
def dsns() -> Iterator[tuple[str, str]]:
    with PostgresContainer("postgres:16-alpine") as c:
        base = c.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        root, env = Path(__file__).resolve().parents[3], {**os.environ, "CV_PG_DSN": base}
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, env=env,
                       check=True)  # fmt: skip
        yield base.replace("+psycopg", ""), base.replace("+psycopg", "+asyncpg")


class _Clock:
    def __init__(self) -> None:
        self.t = T0.timestamp()

    def __call__(self) -> float:
        return self.t


class _Audit:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **record: Any) -> None:
        self.records.append((action, record))


class _Bus:
    """The policy's set changes, handed to the session manager as the wiring will."""

    def __init__(self) -> None:
        self.sessions: SessionManager | None = None

    async def publish(self, topic: Topic, event: Any) -> None:
        if isinstance(event, RecorderSetChanged) and self.sessions is not None:
            await self.sessions.on_set_changed(event)


@dataclass(frozen=True)
class _Wiring:  # #2188 S4b's `RecorderWiring`, field for field
    policy: RecordingPolicy
    rows: SqlAlchemyRecordingReads
    budget: None
    env: str


@pytest.fixture
async def runtime(dsns: tuple[str, str]) -> AsyncIterator[SimpleNamespace]:
    conn = psycopg.connect(dsns[0], autocommit=True)
    conn.execute("TRUNCATE recording_gaps, recording_sessions, recorded_symbols CASCADE")
    conn.execute(
        "INSERT INTO instruments (symbol, base_coin, status, tick_size, qty_step, min_order_qty, "
        "max_order_qty, max_leverage, raw) VALUES ('BTCUSDT', 'X', 'Trading', 1, 1, 1, 1, 1, "
        "'{}') ON CONFLICT DO NOTHING"
    )
    for user in (OWNER, MANAGER):  # `added_by` names a user
        conn.execute("INSERT INTO users (id, email, username, password_hash) VALUES (%s, %s, %s, "
                     "'$argon2id$x') ON CONFLICT DO NOTHING",
                     (user.id, f"{user.id[-4:]}@x.io", f"u{user.id[-4:]}"))  # fmt: skip
    relational = SqlAlchemyRelationalRepository(dsns[1])
    repo, reads = SqlAlchemyRecorderRepository(relational), SqlAlchemyRecordingReads(relational)
    clock, audit, bus = _Clock(), _Audit(), _Bus()
    sessions = SessionManager(repo, now_us=lambda: int(clock.t * 1_000_000), audit=audit,
                              config=SessionConfig(env="demo"))  # fmt: skip
    bus.sessions = sessions
    policy = RecordingPolicy(bus=bus, audit=audit, env="demo", now=clock, recorded=repo,
                             disk_refuses=lambda: False, config=CONFIG)  # fmt: skip
    policy.observe_states(sessions.on_b11_state)
    policy.positions_reloaded()
    wired = policy
    control = RuntimeRecordingControl(
        _Wiring(wired, reads, None, "demo"), config=CONFIG,
        now=lambda: datetime.fromtimestamp(clock.t, UTC),
    )  # fmt: skip
    cache = RecordingStatusCache(lambda: control, None,
                                 wall=lambda: datetime.fromtimestamp(clock.t, UTC))  # fmt: skip
    try:
        yield SimpleNamespace(c=control, p=wired, cache=cache, clock=clock, audit=audit,
                              reads=reads, conn=conn)  # fmt: skip
    finally:
        await policy.stop()
        conn.close()


async def _frame(rt: SimpleNamespace) -> list[dict[str, Any]]:
    """One second's status, as the topic sends it to the Owner."""
    await rt.cache.refresh_once()
    body = rt.cache.body(False)
    assert body is not None and body["overall"] == "healthy"
    return list(body["symbols"])


async def test_add_pin_retention_stop_then_the_session_closes_and_its_data_stays(
    runtime: SimpleNamespace,
) -> None:
    rt = runtime
    entry, prior = await rt.c.add("BTCUSDT", rc.EntrySpec(("trades",), 50), OWNER,
                                  restricted=False)  # fmt: skip
    assert prior is None and (entry.streams, entry.depth, entry.reasons) == (
        ("trades",), 50, ("manual",))  # fmt: skip
    rt.c.note("BTCUSDT", rows=120)  # the fake feed
    (live,) = await _frame(rt)
    assert live["state"] in ("starting", "recording") and live["rows_last_hour"] == 120
    pinned = await rt.c.pin(entry.id, True, OWNER, restricted=False)
    assert pinned is not None and pinned.pinned and pinned.retention_days is None
    unpinned = await rt.c.pin(entry.id, False, OWNER, restricted=False, retention_days=60)
    assert unpinned is not None and (unpinned.pinned, unpinned.retention_days) == (False, 60)
    await rt.p.on_position_opened("BTCUSDT", "p1")  # a cause a Manager's view hides
    with pytest.raises(rc.RelaxRefused):
        await rt.c.update(entry.id, rc.EntrySpec(retention_days=7), MANAGER, restricted=True)
    await rt.p.on_position_closed("BTCUSDT", "p1")
    lowered = await rt.c.update(entry.id, rc.EntrySpec(retention_days=7), MANAGER, restricted=True)
    assert lowered is not None and lowered.retention_days == 7
    assert await rt.c.remove(entry.id, OWNER) is not None  # 204 at the route
    (lingering,) = await _frame(rt)
    until = T0 + timedelta(seconds=CONFIG.autostop_grace_s)
    assert lingering["lingering"] and lingering["linger_until"] == until.isoformat().replace(
        "+00:00", "Z")  # fmt: skip
    rt.clock.t += CONFIG.autostop_grace_s
    await rt.p.tick()  # the lifespan's tick: the grace ends
    assert await _frame(rt) == []
    query = dict(env="demo", symbol="BTCUSDT", since=None, until=None, hidden=(), after=None)
    (session,) = await rt.reads.sessions_page(**query, limit=10)  # the data's coverage stays
    assert session["ended_at"] is not None and session["state"] == "stopped"
    actions = [a for a, r in rt.audit.records if r["outcome"] == "success"]
    assert actions.count("retention.change") == 3 and "recorder.stop" in actions
    denied = [(a, r["reason"]) for a, r in rt.audit.records if r["outcome"] == "denied"]
    assert denied == []  # the port refused the relax before the policy: the route records it
