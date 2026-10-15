"""Integration: `SqlAlchemyReplaySessionRepository` on real Postgres 16 (E26-T01 slice 2/3).

CI-only (testcontainers; no docker socket locally). The shared behavioural contract runs here
exactly as it does against the fake (`tests/unit/storage/replay_sessions_contract.py`), plus what
only a real database can prove: FK names and actions, the planner's use of `ix_rps_user_time` and
`ix_rps_live`, and the compare-and-set under concurrency.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories import replay_sessions_sqlalchemy as mod
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.replay_sessions import (
    ReplaySessionConstraintError,
    ReplaySessionIllegalUpdateError,
    ReplaySessionRow,
    ReplayState,
)
from tests.unit.storage.fakes_replay_sessions import FakeClock
from tests.unit.storage.replay_sessions_contract import (
    Harness,
    ReplaySessionRepositoryContract,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
S = ReplayState
Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        check=True,
    )


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        _alembic(dsn, "upgrade", "head")
        yield dsn


def _sync(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _user(dsn: str, *, active_owner: bool = False) -> str:
    uid = str(uuid.uuid4())
    with _sync(dsn) as c:
        c.execute(
            "INSERT INTO users (id, email, username, password_hash, status) "
            "VALUES (%s, %s, %s, '$argon2id$x', %s)",
            (uid, f"{uid[:8]}@x.io", f"u{uid[:8]}", "active" if active_owner else "invited"),
        )
        if active_owner:  # `trg_owner_floor_fn` only lets other users be deleted while one exists
            c.execute(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT %s, id FROM roles WHERE name = 'owner'",
                (uid,),
            )
    return uid


def _account(dsn: str) -> str:
    aid = str(uuid.uuid4())
    with _sync(dsn) as c:
        c.execute(
            "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
            "VALUES (%s, 'bybit', 'demo', 'main', %s, %s)",
            (aid, str(uuid.uuid4().int % 10**12), f"paper-{aid[:8]}"),
        )
    return aid


def _recording(dsn: str) -> str:
    symbol = f"T{uuid.uuid4().hex[:8].upper()}"
    rsid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    with _sync(dsn) as c:
        c.execute(
            "INSERT INTO instruments (symbol, base_coin, status, tick_size, qty_step, "
            "min_order_qty, max_order_qty, max_leverage, raw) "
            "VALUES (%s, 'T', 'Trading', 0.1, 0.001, 0.001, 100, 100, '{}'::jsonb)",
            (symbol,),
        )
        c.execute("INSERT INTO recorded_symbols (id, symbol) VALUES (%s, %s)", (rsid, symbol))
        c.execute(
            "INSERT INTO recording_sessions (id, recorded_symbol_id, symbol, streams, "
            "orderbook_depth, ws_endpoint) VALUES (%s, %s, %s, '{trades}', 200, 'public')",
            (sid, rsid, symbol),
        )
    return sid


@pytest_asyncio.fixture
async def h(pg_dsn: str) -> AsyncIterator[Harness]:
    """A repository on an empty `replay_sessions` (system-wide reads stay exact per test)."""
    with _sync(pg_dsn) as c:
        c.execute("TRUNCATE replay_sessions")
    rel = SqlAlchemyRelationalRepository(pg_dsn, "replay-sessions-it")
    clock = FakeClock()
    repo = mod.SqlAlchemyReplaySessionRepository(rel, clock=clock)
    try:
        yield Harness(
            repo, clock, lambda: _user(pg_dsn), lambda: _account(pg_dsn), lambda: _recording(pg_dsn)
        )
    finally:
        await rel.dispose()


class TestPostgresRepository(ReplaySessionRepositoryContract):
    """The whole behavioural contract, against the real adapter on real Postgres."""


# -- foreign keys: names and actions ------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "constraint"),
    [
        ("user_id", "replay_sessions_user_id_fkey"),
        ("recording_session_id", "replay_sessions_recording_session_id_fkey"),
        ("paper_account_id", "replay_sessions_paper_account_id_fkey"),
    ],
)
async def test_an_unknown_reference_names_its_foreign_key(
    h: Harness, column: str, constraint: str
) -> None:
    with pytest.raises(ReplaySessionConstraintError) as err:
        await h.make(**{column: str(uuid.uuid4())})
    assert err.value.constraint == constraint


async def test_deleting_the_user_cascades_to_their_sessions(h: Harness, pg_dsn: str) -> None:
    _user(pg_dsn, active_owner=True)
    user = _user(pg_dsn)
    row = await h.make(user)
    with _sync(pg_dsn) as c:
        c.execute("DELETE FROM users WHERE id = %s", (user,))
    assert await h.repo.get(user, row.id) is None


async def test_deleting_the_recording_keeps_the_session_with_a_null_link(
    h: Harness, pg_dsn: str
) -> None:
    rec = _recording(pg_dsn)
    row = await h.make(recording_session_id=rec)
    with _sync(pg_dsn) as c:
        c.execute("DELETE FROM recording_sessions WHERE id = %s", (rec,))
    kept = await h.repo.get(row.user_id, row.id)
    assert kept is not None and kept.recording_session_id is None


# -- planner: the indexes the table was designed around -----------------------------------------

_USERS, _PER_USER = 20, 2_500


def _seed(dsn: str) -> list[str]:
    """50k deterministic rows, ~4% live: the shape in which both indexes pay off."""
    users = [_user(dsn) for _ in range(_USERS)]
    with _sync(dsn) as c:
        for user in users:
            c.execute(
                "INSERT INTO replay_sessions (id, user_id, symbol, range_start, range_end, state, "
                "created_at, updated_at) SELECT gen_random_uuid(), %s::uuid, 'BTCUSDT', "
                "'2026-01-01', '2026-01-02', (CASE WHEN g %% 50 = 0 THEN 'playing' "
                "WHEN g %% 50 = 1 THEN 'paused' WHEN g %% 7 = 0 THEN 'finished' "
                "ELSE 'destroyed' END)::replay_state, now() - (g || ' minutes')::interval, "
                "now() - (g || ' minutes')::interval FROM generate_series(1, %s) g",
                (user, _PER_USER),
            )
        c.execute("ANALYZE replay_sessions")
    return users


async def _plan(dsn: str, stmt: Any) -> str:
    """The planner's chosen node tree for the shipped statement (literals inlined), as JSON."""
    rel = SqlAlchemyRelationalRepository(dsn, "replay-sessions-explain")
    try:
        async with rel.unit_of_work() as uow:
            conn = await uow.session.connection()
            sql = str(stmt.compile(dialect=conn.dialect, compile_kwargs={"literal_binds": True}))
            result = await conn.exec_driver_sql("EXPLAIN (FORMAT JSON) " + sql)
            return json.dumps(result.scalar_one())
    finally:
        await rel.dispose()


async def test_the_planner_uses_the_indexes_the_table_was_designed_around(
    h: Harness, pg_dsn: str
) -> None:
    user = uuid.UUID(_seed(pg_dsn)[0])
    now = datetime.now(UTC)  # the seeded rows are dated relative to the real clock
    page = mod.list_statement(user, None, None, 51)
    next_page = mod.list_statement(user, None, (now - timedelta(hours=1), str(uuid.uuid4())), 51)
    by_state = mod.list_statement(user, S.PAUSED, None, 51)
    assert "ix_rps_user_time" in await _plan(pg_dsn, page)
    assert "ix_rps_user_time" in await _plan(pg_dsn, next_page)
    assert "ix_rps_live" in await _plan(pg_dsn, by_state)
    assert "ix_rps_live" in await _plan(pg_dsn, mod.count_statement(user))
    sweep = await _plan(pg_dsn, mod.idle_statement(now - timedelta(hours=2), 200))
    assert "ix_rps_live" in sweep and "Seq Scan" not in sweep


# -- concurrency ----------------------------------------------------------------------------------


async def test_concurrent_compare_and_set_has_exactly_one_winner(h: Harness) -> None:
    row = await h.in_state(S.PAUSED)
    results = await asyncio.gather(
        *(
            h.repo.update_state(row.user_id, row.id, state=S.PLAYING, expected_state=S.PAUSED)
            for _ in range(8)
        ),
        return_exceptions=True,
    )
    winners = [r for r in results if isinstance(r, ReplaySessionRow)]
    losers = [r for r in results if isinstance(r, ReplaySessionIllegalUpdateError)]
    assert (len(winners), len(losers)) == (1, 7)
    assert {r.current for r in losers} == {S.PLAYING}
