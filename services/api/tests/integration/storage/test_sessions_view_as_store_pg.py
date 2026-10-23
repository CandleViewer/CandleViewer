"""Integration (#3085 S2b, S3): `SqlAlchemySessionRepository` as the `ViewAsSessionStore` on real
Postgres 16. CI-only (testcontainers); not run on the shared VPS while the perf bench owns it.

The parity table (`tests/unit/auth/view_as_store_scenarios.py`) runs here as it runs against the
fake. Then what only Postgres proves: writers racing on one row's lock leave one applying, and
`leave_view_as` reports which call ended the context; a refresh carries the context to its
successor row; the due read stays on its indexes past a pile of rotated copies (M6)."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
import sqlalchemy as sa
from psycopg import sql
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.view_as import ViewAsEndReason, ViewAsNotice, ViewAsState
from candleviewer.storage.repositories import sessions_sqlalchemy as mod
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    constraint_of,
    sqlstate_of,
)
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from tests.integration._refused import assert_no_row_values, server_text
from tests.unit.auth import view_as_store_scenarios as sc

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATE = "view_as_store_template"
_WAIT_S = 30.0  # bounds every wait on a racing call: a regression fails instead of hanging CI
_WAITING = sa.text("SELECT count(DISTINCT pid) FROM pg_locks WHERE NOT granted")
_HOLD = sa.text("SELECT 1 FROM sessions WHERE id = CAST(:id AS uuid) FOR NO KEY UPDATE")
_USER = (
    "INSERT INTO users (id, email, username, password_hash, status) "
    "VALUES (%s, %s, %s, '$argon2id$fixture', 'active')"
)
_CREATE = sql.SQL("CREATE DATABASE {} TEMPLATE {}")
Conn = psycopg.Connection[tuple[Any, ...]]


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True)


def _create(server: str, name: str, template: str) -> None:
    """From `postgres`: a template database must have no other connection while it is copied."""
    with _conn(f"{server}/postgres") as c:
        c.execute(_CREATE.format(sql.Identifier(name), sql.Identifier(template)))


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """As `test_sessions_view_as_migration.py`: a server whose template database is at head."""
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        subprocess.run(  # fixed argv, a literal alembic subcommand, no shell
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn}, check=True, timeout=120,
        )  # fmt: skip
        server, head = dsn.rsplit("/", 1)
        _create(server, _TEMPLATE, head)
        yield dsn


def _fresh(pg_dsn: str) -> str:
    """A database of the test's own at head, holding the table's viewer (the one active owner:
    the owner floor checks every `users` write) and the two users its contexts name."""
    server, name = pg_dsn.rsplit("/", 1)[0], f"view_as_{uuid.uuid4().hex[:12]}"
    _create(server, name, _TEMPLATE)
    with _conn(f"{server}/{name}") as c:
        for user in (sc.VIEWER, sc.TARGET, sc.OTHER):
            handle = f"v{user.hex[-12:]}"
            c.execute(_USER, (user, f"{handle}@x.invalid", handle))
        c.execute(
            "INSERT INTO user_roles (user_id, role_id) "
            "SELECT %s, id FROM roles WHERE name::text = 'owner'",
            (sc.VIEWER,),
        )
    return f"{server}/{name}".replace("postgresql+psycopg", "postgresql+asyncpg")


@asynccontextmanager
async def _store(dsn: str) -> AsyncIterator[SqlAlchemySessionRepository]:
    relational = SqlAlchemyRelationalRepository(dsn, "view-as-store")
    try:
        yield SqlAlchemySessionRepository(relational, lambda **f: SessionRecord.model_validate(f))
    finally:
        await relational.dispose()


def _stamp(dsn: str) -> sc.Stamp:
    """A row's `revoked_reason` alone, written raw: no store method leaves one with no time."""

    async def stamp(session: str, reason: str) -> None:
        with _conn(dsn.replace("postgresql+asyncpg", "postgresql+psycopg")) as c:
            c.execute(
                "UPDATE sessions SET revoked_reason = %s WHERE id = CAST(%s AS uuid)",
                (reason, session),
            )

    return stamp


@pytest.mark.parametrize("scenario", sc.SCENARIOS, ids=[s.id for s in sc.SCENARIOS])
async def test_the_postgres_store_gives_each_outcome_the_table_states(
    pg_dsn: str, scenario: sc.Scenario
) -> None:
    dsn = _fresh(pg_dsn)
    async with _store(dsn) as store:
        assert await sc.play(store, scenario, _stamp(dsn)) == sc.expected(scenario)


# -- races: the row lock decides --------------------------------------------------------------


async def _until_blocked(probe: AsyncConnection, n: int) -> None:
    """Bounded condition wait: `n` backends queued on a lock (`pg_locks` is never cached)."""
    for _ in range(400):
        if (await probe.execute(_WAITING)).scalar_one() >= n:
            return
        await asyncio.sleep(0.025)
    raise AssertionError(f"{n} callers never queued on the row lock")


async def _queued(dsn: str, row: str, calls: list[Callable[[], Awaitable[Any]]]) -> list[Any]:
    """Run `calls` while another transaction holds `row`, starting each once the one before it has
    queued on the lock, then release it: they apply in that order, each after the one before."""
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as probe:
            async with engine.begin() as holder:
                await holder.execute(_HOLD, {"id": row})
                tasks = []
                for n, call in enumerate(calls, start=1):
                    tasks.append(asyncio.create_task(call()))
                    await _until_blocked(probe, n)
            return list(await asyncio.wait_for(asyncio.gather(*tasks), _WAIT_S))
    finally:
        await engine.dispose()


async def _seeded(store: SqlAlchemySessionRepository, state: ViewAsState | None) -> str:
    seeded = sc.record("a", sc.Row(state))
    assert await store.create_session(seeded) is not None
    return str(seeded.id)


async def test_two_starts_on_one_row_one_applies(pg_dsn: str) -> None:
    dsn, other = _fresh(pg_dsn), ViewAsState.start(uuid.uuid4(), sc.OTHER, now=sc.T0)
    async with _store(dsn) as store:
        sid = await _seeded(store, None)
        starts = [lambda s=s: store.start_view_as(sid, s, now=sc.T0) for s in (sc.FRESH, other)]
        first, second = await _queued(dsn, sid, starts)
        assert first.view_as == sc.FRESH and second is None
        assert (await store.find_by_id(sid)).view_as == sc.FRESH


async def test_two_start_units_on_one_row_one_starts_with_one_notice_and_record(
    pg_dsn: str,
) -> None:
    """#3085 S13b (the #4170 security look's Low-3): of two starts queued on one row's lock, the
    first starts its context, with one notice and its record written ahead, and the second reads
    that context held and writes nothing: 22 `startViewAs`'s `201` and `409 view_as_active`."""
    dsn, other = _fresh(pg_dsn), ViewAsState.start(uuid.uuid4(), sc.OTHER, now=sc.T0)
    written: list[str] = []

    async def ahead(record: SessionRecord) -> None:
        written.append(str(record.id))

    async with _store(dsn) as store:
        sid = await _seeded(store, None)

        def unit(state: ViewAsState) -> Callable[[], Awaitable[Any]]:
            notice = ViewAsNotice(state.target_user_id, "m", None)
            return lambda: store.start_view_as_unit(
                sid, state, now=sc.T0, notice=notice, flush_pending_end=ahead,
                write_ahead=ahead, audit_timeout_s=_WAIT_S,
            )  # fmt: skip

        (started, none), (lost, held) = await _queued(dsn, sid, [unit(sc.FRESH), unit(other)])
        assert (started.view_as, none, lost, held.view_as) == (sc.FRESH, None, None, sc.FRESH)
        assert written == [sid]
    with _conn(dsn.replace("postgresql+asyncpg", "postgresql+psycopg")) as c:
        query = "SELECT recipient_user_id FROM system_events WHERE kind = 'view_as_started'"
        assert c.execute(query).fetchall() == [(sc.TARGET,)]


async def test_two_ends_of_one_context_one_applies(pg_dsn: str) -> None:
    dsn, cid = _fresh(pg_dsn), sc.LIVE.context_id
    async with _store(dsn) as store:
        sid = await _seeded(store, sc.LIVE)
        reasons = (ViewAsEndReason.SESSION_ENDED, ViewAsEndReason.ENDED)
        ends = [lambda r=r: store.end_view_as(sid, cid, ended_at=sc.T0, reason=r) for r in reasons]
        first, second = await _queued(dsn, sid, ends)
        assert first.view_as.end_reason is ViewAsEndReason.SESSION_ENDED and second is None


@pytest.mark.parametrize(
    ("order", "outcomes"),
    [
        (("leave", "leave"), (True, None)),  # the second finds it cleared
        (("end", "leave"), ("applied", False)),  # the leave clears what the end ended
        (("leave", "end"), (True, None)),  # the end finds it ended
    ],
    ids=["leave-leave", "end-leave", "leave-end"],
)
async def test_leave_reports_whether_this_call_ended_the_context(
    pg_dsn: str, order: tuple[str, str], outcomes: tuple[object, object]
) -> None:
    """`RETURNING` sees the row as updated: the flag comes from the row as locked before it, so a
    leave queued behind an end reports False, and only the call that set the end reports True."""
    dsn, cid = _fresh(pg_dsn), sc.LIVE.context_id
    async with _store(dsn) as store:
        sid = await _seeded(store, sc.LIVE)
        by: dict[str, Callable[[], Awaitable[Any]]] = {
            "leave": lambda: store.leave_view_as(
                sid, cid, ended_at=sc.T0, reason=ViewAsEndReason.ENDED, now=sc.at(1)
            ),
            "end": lambda: store.end_view_as(
                sid, cid, ended_at=sc.T0, reason=ViewAsEndReason.SESSION_ENDED
            ),
        }
        results = await _queued(dsn, sid, [by[name] for name in order])
        seen = [r if r is None else r[1] if isinstance(r, tuple) else "applied" for r in results]
        assert tuple(seen) == outcomes
        held = (await store.find_by_id(sid)).view_as
        assert held.cleared_at == sc.at(1) and held.ended_at == sc.T0 and held.end_pending
        # a leave keeps the end it finds, its reason too, and sets its own only when none was
        by_the_first = ViewAsEndReason.SESSION_ENDED if order[0] == "end" else ViewAsEndReason.ENDED
        assert held.end_reason is by_the_first


# -- the refresh carry, end to end (S3) -------------------------------------------------------


async def test_a_refresh_carries_the_context_and_its_rotated_copy_is_never_due(pg_dsn: str) -> None:
    async with _store(_fresh(pg_dsn)) as store:
        service = SessionService(store, Hasher(), clock=lambda: sc.T0)
        minted = await service.mint(str(sc.VIEWER))
        sid = str(minted.session_id)
        assert await store.start_view_as(sid, sc.FRESH, now=sc.T0) is not None
        successor = (await service.refresh(minted.refresh_token)).minted.session_id
        rotated, carried = await store.find_by_id(sid), await store.find_by_id(str(successor))
        assert (
            rotated.revoked_reason == "rotated" and rotated.view_as == carried.view_as == sc.FRESH
        )
        assert await store.list_view_as_due(now=sc.at(10), rotated_grace=sc.GRACE, limit=9) == ()
        assert [r.id for r in await store.list_live_view_as(limit=9)] == [successor]


# -- the due read's plan: one rotated copy per refresh during a view (M6) ---------------------

_PILE = """
INSERT INTO sessions (id, user_id, refresh_token_hash, issued_at, last_seen_at, expires_at,
    revoked_at, revoked_reason, view_as_context_id, view_as_target_user_id, view_as_started_at,
    view_as_expires_at, view_as_ended_at, view_as_end_reason, view_as_end_recorded_at)
SELECT gen_random_uuid(), %(viewer)s, md5(v.k || g::text) || md5(g::text || v.k),
    t - interval '1 hour', t - interval '1 hour', t + interval '11 hours',
    t + interval '5 minutes', v.reason, md5(g::text)::uuid, %(target)s, t,
    t + interval '30 minutes',
    CASE WHEN v.k = 'c' THEN t + interval '10 minutes' END,
    CASE WHEN v.k = 'c' THEN 'session_ended' END,
    CASE WHEN v.k = 'c' THEN t + interval '11 minutes' END
FROM generate_series(1, %(n)s) AS g
CROSS JOIN (VALUES ('r', 'rotated'), ('c', 'logout')) AS v(k, reason)
CROSS JOIN LATERAL (
    SELECT %(t0)s::timestamptz - interval '3 days' + g * interval '1 minute'
) AS s(t)
"""
#: For this transaction only (`is_local`): no table scan, no bitmap scan, no sort.
_NO_SCAN_NO_SORT = sa.text(
    "SELECT set_config('enable_seqscan', 'off', true), "
    "set_config('enable_bitmapscan', 'off', true), set_config('enable_sort', 'off', true)"
)


def _nodes(explained: Any) -> list[dict[str, Any]]:
    """Every node of an `EXPLAIN (FORMAT JSON)` plan (its `json` column, decoded or not)."""
    tree = json.loads(explained) if isinstance(explained, str) else explained
    stack, nodes = [tree[0]["Plan"]], []
    while stack:
        nodes.append(stack.pop())
        stack.extend(nodes[-1].get("Plans", []))
    return nodes


async def test_the_due_read_can_run_on_its_indexes_past_a_pile_of_rotated_copies(
    pg_dsn: str,
) -> None:
    """Each context has a rotated copy (unrecorded, so in `ix_sessions_view_as_due`) and its last
    carrier, logged out and recorded: nothing is due. With the alternatives off, the plan is still
    an index scan of `ix_sessions_view_as_due` in `ORDER BY` order (its predicate is implied, so
    no scan of the table and no sort) that probes `ix_sessions_view_as_context` for each copy."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn.replace("postgresql+asyncpg", "postgresql+psycopg")) as c:
        c.execute(_PILE, {"viewer": sc.VIEWER, "target": sc.TARGET, "n": 300, "t0": sc.T0})
        c.execute("ANALYZE sessions")
    params = {"now": sc.T0, "cutoff": sc.T0 - sc.GRACE, "limit": 50}
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            await conn.execute(_NO_SCAN_NO_SORT)
            # Built only from a fixed literal and the shipped statement's text; no input.
            # nosemgrep: avoid-sqlalchemy-text reason=explain-sql owner=@basiltt review=2027-03-25
            explain = sa.text("EXPLAIN (FORMAT JSON) " + mod._VIEW_AS_DUE_SQL.text)
            nodes = _nodes((await conn.execute(explain, params)).scalar_one())
            due = (await conn.execute(mod._VIEW_AS_DUE_SQL, params)).all()
    finally:
        await engine.dispose()
    assert due == []
    assert {"ix_sessions_view_as_due", "ix_sessions_view_as_context"} <= {
        node.get("Index Name") for node in nodes
    }
    assert {"Seq Scan", "Sort", "Bitmap Heap Scan"}.isdisjoint(n["Node Type"] for n in nodes)


# -- a refused write leaves without the row's values (#2748, C-12.6) ---------------------------

_UA, _IP, _DEVICE = "SECRET-UA/1.0", "203.0.113.77", "SECRET-DEVICE"  # P2, planted by name


@pytest.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    rel = SqlAlchemyRelationalRepository(_fresh(pg_dsn), "sessions-refused-it")
    try:
        yield rel
    finally:
        await rel.dispose()


@pytest.fixture
def store(rel: SqlAlchemyRelationalRepository) -> SqlAlchemySessionRepository:
    return SqlAlchemySessionRepository(rel, lambda **f: SessionRecord.model_validate(f))


def _planted(**over: Any) -> SessionRecord:
    """The viewer's row `a`, its P2 columns planted (its S refresh hash is `sc.record`'s)."""
    planted = {"ip": _IP, "user_agent": _UA, "device_label": _DEVICE} | over
    return sc.record("a", sc.Row()).model_copy(update=planted)


async def test_an_idle_timeout_out_of_range_leaves_without_the_session_row(
    rel: SqlAlchemyRelationalRepository, store: SqlAlchemySessionRepository
) -> None:
    row = _planted(idle_timeout_s=10)
    with server_text(rel) as seen, pytest.raises(sa.exc.IntegrityError) as err:
        await store.create_session(row)
    facts = (sqlstate_of(err.value), constraint_of(err.value))
    assert facts == ("23514", "sessions_idle_timeout_range")
    assert (err.value.__cause__, err.value.__suppress_context__) == (None, True)
    assert_no_row_values(err.value, seen, _IP, _UA, _DEVICE, row.refresh_token_hash)


async def test_a_view_as_of_the_sessions_own_user_leaves_without_the_session_row(
    rel: SqlAlchemyRelationalRepository, store: SqlAlchemySessionRepository
) -> None:
    row = _planted()
    assert await store.create_session(row) is not None
    with server_text(rel) as seen, pytest.raises(ValueError, match="its own user") as err:
        await store.start_view_as(str(row.id), sc.SELF, now=sc.T0)
    assert (err.value.__cause__, err.value.__suppress_context__) == (None, True)
    assert_no_row_values(err.value, seen, _IP, _UA, _DEVICE, row.refresh_token_hash)
