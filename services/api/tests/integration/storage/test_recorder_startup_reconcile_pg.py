"""#2188 S3a, the issue's "Done means" test: the startup reconcile on a seeded Postgres 16. Only
this env's active rows are read, a manual row resumes, the auto rows nothing holds linger, a seeded
live position resumes recording, and a pinned row is never a pre-emption victim."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row
from testcontainers.postgres import PostgresContainer

from candleviewer.recorder.policy import PolicyConfig, RecordingPolicy
from candleviewer.recorder.sessions import SessionManager, startup_reconcile
from candleviewer.storage.repositories.recorder_sqlalchemy import SqlAlchemyRecorderRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.unit.recorder._fakes import FakeAudit, FakeBus, FakeClock, FakeSeed, no_restore

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
Conn = psycopg.Connection
SYMBOLS = (
    "BTCUSDT", "TRXUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT",
    "AVAXUSDT",
)  # fmt: skip
CHART = {"kind": "chart", "id": "c1"}


@pytest.fixture(scope="module")
def dsns() -> Iterator[tuple[str, str]]:
    with PostgresContainer("postgres:16-alpine") as c:
        base = c.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={**os.environ, "CV_PG_DSN": base},
            check=True,
        )
        yield base.replace("+psycopg", ""), base.replace("+psycopg", "+asyncpg")


@pytest.fixture
def conn(dsns: tuple[str, str]) -> Iterator[Conn]:
    with psycopg.connect(dsns[0], autocommit=True) as c:
        c.execute("TRUNCATE recording_gaps, recording_sessions, recorded_symbols CASCADE")
        c.execute(
            "INSERT INTO instruments (symbol, base_coin, status, tick_size, qty_step, "
            "min_order_qty, max_order_qty, max_leverage, raw) SELECT s, 'X', 'Trading', 1, 1, "
            "1, 1, 1, '{}' FROM unnest(%s::text[]) s ON CONFLICT DO NOTHING",
            (list(SYMBOLS),),
        )
        yield c


def _seed(conn: Conn, symbol: str, **kw: Any) -> None:
    """One `recorded_symbols` row, as an earlier process left it (`rs_autoshape` kept)."""
    reason = kw.get("reason", "chart_open")
    conn.execute(
        "INSERT INTO recorded_symbols (id, symbol, env, reason, reason_refs, streams, "
        "orderbook_depth, pinned, added_by, auto_added_at, removed_at) VALUES (gen_random_uuid(), "
        "%s, %s::exchange_env, %s::record_reason, %s::jsonb, %s::stream_kind[], %s, %s, %s::uuid, "
        "%s, %s)",
        (
            symbol, kw.get("env", "demo"), reason, json.dumps(kw.get("refs", [])),
            kw.get("streams", "{trades,orderbook_delta,tickers,liquidations}"),
            kw.get("depth", 200), kw.get("pinned", False), kw.get("added_by"),
            None if reason == "manual" else datetime.now(UTC),
            datetime.now(UTC) if kw.get("removed") else None,
        ),
    )  # fmt: skip


@dataclass
class _Run:
    policy: RecordingPolicy
    audit: FakeAudit
    clock: FakeClock
    conn: Conn
    user: str
    repo: SqlAlchemyRecorderRepository

    def row(self, symbol: str) -> dict[str, Any]:
        """The newest `demo` row of `symbol`, as it stands now."""
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT streams::text[] AS streams, orderbook_depth, pinned, "
                "added_by::text AS added_by, removed_at FROM recorded_symbols "
                "WHERE symbol = %s AND env = 'demo' ORDER BY created_at DESC LIMIT 1",
                (symbol,),
            )
            return cur.fetchone() or {}

    def starts(self, symbol: str) -> list[tuple[str, str, str | None]]:
        return [
            (kw["actor_label"], kw["reason"], kw["after_state"]["trigger_ref"])
            for action, kw in self.audit.records
            if action == "recorder.start" and kw["object_id"] == symbol
        ]


@pytest.fixture
async def run(dsns: tuple[str, str], conn: Conn) -> AsyncIterator[_Run]:
    user = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users (id, email, username, password_hash, status) "
        "VALUES (%s, %s, %s, '$argon2id$fixture', 'active')",
        (user, f"{user[:8]}@example.invalid", f"rec{user[:8]}"),
    )
    _seed(conn, "BTCUSDT", reason="manual", added_by=user, streams="{trades,tickers}", depth=50)
    _seed(conn, "TRXUSDT", reason="manual", streams="{trades}", depth=500)  # its user was deleted
    _seed(conn, "ETHUSDT", refs=[CHART])  # auto rows nothing holds: a chart ref,
    _seed(conn, "SOLUSDT", refs=[{"kind": "recorder", "id": "session"}])  # the legacy ref,
    _seed(conn, "XRPUSDT", reason="position_open", refs=[{"kind": "position", "id": "gone"}])
    _seed(conn, "DOGEUSDT", pinned=True, refs=[CHART])  # a pinned auto row
    _seed(conn, "ADAUSDT", reason="position_open", refs=[{"kind": "position", "id": "p1"}])  # live
    _seed(conn, "LINKUSDT", removed=True)  # soft-removed
    _seed(conn, "AVAXUSDT", env="live", reason="manual", added_by=user)  # another env's
    relational = SqlAlchemyRelationalRepository(dsns[1])
    repo, clock, audit = SqlAlchemyRecorderRepository(relational), FakeClock(), FakeAudit()
    policy = RecordingPolicy(
        bus=FakeBus(), audit=audit, env="demo", now=clock, disk_refuses=bool, recorded=repo,
        config=PolicyConfig(max_symbols=7),
    )  # fmt: skip
    sessions = SessionManager(repo, now_us=lambda: 0, audit=FakeAudit())
    await startup_reconcile(sessions, policy, process_start_us=0, restore_b11=no_restore,
                            seed=FakeSeed([("ADAUSDT", "p1")]))  # fmt: skip
    yield _Run(policy, audit, clock, conn, user, repo)
    await policy.stop()
    await relational.dispose()


async def test_only_this_envs_active_rows_are_read_and_the_others_are_left_alone(
    run: _Run,
) -> None:
    read = {row["symbol"] for row in await run.repo.list_recorded("demo")}
    # the active rows of this env: not LINKUSDT (soft-removed), not AVAXUSDT (live)
    assert read == {"BTCUSDT", "TRXUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"}
    assert set(run.policy.effective_set()) == read
    assert run.row("LINKUSDT")["removed_at"] is not None  # still soft-removed, not revived
    live = run.conn.execute("SELECT removed_at FROM recorded_symbols WHERE env = 'live'").fetchone()
    assert live == (None,)  # the other env's row is neither adopted nor touched


async def test_a_manual_row_resumes_with_one_start_and_keeps_its_streams_and_depth(
    run: _Run,
) -> None:
    assert [run.policy.leaf(s) for s in ("BTCUSDT", "TRXUSDT")] == ["recording", "recording"]
    assert run.starts("BTCUSDT") == [("system:recorder-policy", "manual", f"manual:{run.user}")]
    assert run.starts("TRXUSDT") == [("system:recorder-policy", "manual", "manual:recorder-policy")]
    btc, trx = run.row("BTCUSDT"), run.row("TRXUSDT")
    assert (btc["streams"], btc["orderbook_depth"]) == (["trades", "tickers"], 50)
    assert (btc["added_by"], trx["added_by"]) == (run.user, None)


async def test_auto_rows_go_to_lingering_and_a_seeded_position_resumes_recording(
    run: _Run,
) -> None:
    deadline = datetime.fromtimestamp(run.clock() + 1_800, UTC)
    for symbol in ("ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"):
        assert run.policy.leaf(symbol) == "lingering"
        assert run.policy.linger_until(symbol) == deadline
    ada = run.policy.effective_set()["ADAUSDT"]
    assert (run.policy.leaf("ADAUSDT"), ada.reasons) == ("recording", ("position_open",))
    assert run.starts("ADAUSDT") == [("system:recorder-policy", "position_open", "position:p1")]


async def test_a_pinned_row_is_never_a_pre_emption_victim(run: _Run) -> None:
    await run.policy.on_position_opened("LINKUSDT", "p9")  # the cap is full: one lingering row goes
    stops = [(kw["object_id"], kw["reason"]) for a, kw in run.audit.records if a == "recorder.stop"]
    assert stops == [("ETHUSDT", "cap_preempted")]  # DOGEUSDT sorts first, but it is pinned
    assert run.policy.leaf("DOGEUSDT") == "lingering" and run.policy.leaf("LINKUSDT") == "recording"
    assert run.row("ETHUSDT")["removed_at"] is not None and run.row("DOGEUSDT")["pinned"]
