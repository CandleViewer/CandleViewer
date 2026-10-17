"""Integration (CI-only, testcontainers): the drawings layout check against racing soft deletes
(E15-T01 spec Sec.7, #402). Two engines (two connections), `asyncio.Event` barriers, no sleeps.

Layout soft-delete rounds rotate three modes: both sides released together, the batch released
only once the delete holds the layout row, and the delete released only once the batch holds its
share lock (an engine hook sets the event), so both interleavings are exercised every run.

Workspace soft-delete rounds race a two-layout batch in a fixed order. A third connection parks
the first side while it holds its layout locks (an uncommitted insert of the batch's new id, or a
lock on the drawing the delete cascades to); the second side is started and seen waiting on a
lock in `pg_stat_activity` (polled, no sleeps); then the third connection rolls back. With the
layout check weakened to `FOR KEY SHARE` the batch-first rounds leave a live drawing behind.

Two-layout writer rounds (a workspace soft delete; a replace taking over the default) insert and
name the layouts against their id order while a third connection share-locks the lower id: the
writer queues on it holding nothing and the batch commits at once, whether the third connection
lets go before or after the deadlock checks (a short `deadlock_timeout`). A writer locking in
scan or statement order holds the higher id there and deadlocks with the batch instead.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Coroutine, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy import event, text
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.drawings import (
    BatchOp,
    CreateOp,
    DrawingFields,
    DrawingLayoutNotFoundError,
    UpdateOp,
)
from candleviewer.storage.repositories.drawings_sqlalchemy import SqlAlchemyDrawingRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.workspaces import LayoutFields, WorkspaceFields
from candleviewer.storage.repositories.workspaces_sqlalchemy import SqlAlchemyWorkspaceRepository

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
ROUNDS = 60
WS_ROUNDS = 24  # even: the batch parks first (committed); odd: the delete parks first (rejected)
DEADLOCK_ROUNDS = 3  # per writer and release timing
DEADLOCK_MS = 100  # `deadlock_timeout` on the race engines (`_fast_deadlock_check`)
_POLL_TIMEOUT_S = 30  # fails a missed wait fast; polls stop as soon as their condition holds
Repos = tuple[SqlAlchemyDrawingRepository, SqlAlchemyWorkspaceRepository, str, str]


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        env = {**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=_ROOT, env=env, check=True
        )
        yield dsn


def _sync(dsn: str, *, autocommit: bool = True) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=autocommit)


async def _owner(dsn: str, workspaces: SqlAlchemyWorkspaceRepository) -> tuple[str, str]:
    """A user with one live workspace: (user id, workspace id)."""
    uid, wid = str(uuid.uuid4()), str(uuid.uuid4())
    with _sync(dsn) as c:
        c.execute(
            "INSERT INTO users (id, email, username, password_hash) "
            "VALUES (%s, %s, %s, '$argon2id$x')",
            (uid, f"{uid[:8]}@x.io", f"u{uid[:8]}"),
        )
    await workspaces.create_workspace(uid, wid, WorkspaceFields("w", False, "workspace.default", 0))
    return uid, wid


@pytest_asyncio.fixture
async def repos(pg_dsn: str) -> AsyncIterator[Repos]:
    drel = SqlAlchemyRelationalRepository(pg_dsn, "drawings-race")  # one engine per side
    wrel = SqlAlchemyRelationalRepository(pg_dsn, "workspaces-race")
    workspaces = SqlAlchemyWorkspaceRepository(wrel)
    try:
        yield (SqlAlchemyDrawingRepository(drel), workspaces, *await _owner(pg_dsn, workspaces))
    finally:
        await drel.dispose()
        await wrel.dispose()


def _f(layout: str | None) -> DrawingFields:
    return DrawingFields("BTCUSDT", layout, "trendline", {"points": []}, {}, None, False, True, 0,
                         None, None)  # fmt: skip


async def _layout(
    workspaces: SqlAlchemyWorkspaceRepository,
    owner: str,
    wid: str,
    lid: str | None = None,
    *,
    name: str | None = None,
    default: bool = False,
) -> str:
    lid = lid or str(uuid.uuid4())
    fields = LayoutFields(name or f"l-{lid}", "1x1", None, True, False, False, None, default, ())
    await workspaces.create_layout(owner, wid, lid, fields)
    return lid


async def _outcome(work: Coroutine[Any, Any, object]) -> str:
    """Run `work`: "rejected" on a layout refusal, else "committed" (anything else escapes)."""
    try:
        await work
    except DrawingLayoutNotFoundError:
        return "rejected"
    return "committed"


async def _parked(gate: asyncio.Event, work: Coroutine[Any, Any, object]) -> str:
    """Wait at the barrier, then run `work` (see `_outcome`)."""
    await gate.wait()
    return await _outcome(work)


async def _until_waiting(
    poll: psycopg.AsyncConnection[tuple[object, ...]],
    side: str,
    *,
    ms: int = 0,
    done: asyncio.Task[str] | None = None,
) -> None:
    """Poll `pg_stat_activity` (autocommit: a fresh snapshot per poll; the unit of work tags the
    backend `candleviewer:<side>`) until one of three exits: the `side` engine's backend has
    waited on a lock for `ms` milliseconds (return); `done` has finished (return: no wait is left
    to see); or `_POLL_TIMEOUT_S` has passed (AssertionError, so a missed wait fails fast)."""
    try:
        async with asyncio.timeout(_POLL_TIMEOUT_S):
            while done is None or not done.done():
                cur = await poll.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name = %s "
                    "AND wait_event_type = 'Lock' "
                    "AND clock_timestamp() - query_start >= %s * interval '1 ms'",
                    (f"candleviewer:{side}", ms),
                )
                if await cur.fetchone() != (0,):
                    return
    except TimeoutError:
        raise AssertionError(f"{side} never waited on a lock") from None


def _fast_deadlock_check(dbapi_connection: Any, _record: object) -> None:
    """Pool `connect` hook: run the deadlock check `DEADLOCK_MS` into a lock wait, not after 1 s
    (session level, outside any transaction, so it sticks)."""
    dbapi_connection.run_async(lambda c: c.execute("SET deadlock_timeout = '100ms'"))


def _assert_one_cascade(
    dsn: str, layouts: tuple[str, str], old: str, new: str, outcome: str
) -> None:
    """One soft-delete timestamp on both layouts and on `old`; `new` shares it when the batch
    committed first, else it was never written (the delete won)."""
    with _sync(dsn) as c:
        lays: dict[str, object] = {
            str(i): ts
            for i, ts in c.execute(
                "SELECT id::text, deleted_at FROM layouts WHERE id = ANY(%s::uuid[])",
                (list(layouts),),
            ).fetchall()
        }
        rows: dict[str, object] = {
            str(i): ts
            for i, ts in c.execute(
                "SELECT id::text, deleted_at FROM drawings WHERE id = ANY(%s::uuid[])",
                ([old, new],),
            ).fetchall()
        }
    ts = lays[layouts[0]]
    assert ts is not None and lays[layouts[1]] == ts and rows[old] == ts  # one cascade
    if outcome == "committed":
        assert rows[new] == ts  # committed first: the delete cascaded to the new row
    else:
        assert new not in rows  # the delete won: the batch wrote nothing


def _assert_settled(dsn: str, owner: str, outcomes: dict[str, int], rounds: int) -> None:
    """After the rounds: every one is counted and no live drawing of `owner` is left on a
    soft-deleted layout."""
    with _sync(dsn) as c:
        stray = c.execute(
            "SELECT count(*) FROM drawings d JOIN layouts l ON l.id = d.layout_id "
            "WHERE d.owner_user_id = %s AND d.deleted_at IS NULL AND l.deleted_at IS NOT NULL",
            (owner,),
        ).fetchone()
    assert stray == (0,) and sum(outcomes.values()) == rounds, outcomes


async def _release(gate: asyncio.Event) -> str:
    gate.set()  # both sides are parked on the event: release them together
    return "released"


@pytest.mark.parametrize("op", ["create", "update"])  # POST + batch create, PUT + batch update
async def test_only_an_own_live_layout_passes_and_a_refused_batch_writes_nothing(
    repos: Repos, pg_dsn: str, op: str
) -> None:
    drawings, workspaces, owner, wid = repos
    live, gone = await _layout(workspaces, owner, wid), await _layout(workspaces, owner, wid)
    await workspaces.soft_delete_layout(owner, wid, gone)
    foreign = await _layout(workspaces, *await _owner(pg_dsn, workspaces))
    target = (await drawings.create(owner, str(uuid.uuid4()), _f(None))).id  # updated in place

    async def write(layout: str) -> str | None:
        if op == "create":
            return (await drawings.create(owner, str(uuid.uuid4()), _f(layout))).layout_id
        return (await drawings.update(owner, target, _f(layout), if_match=None)).layout_id

    for refused in (gone, foreign, str(uuid.uuid4())):  # deleted, another owner's, unknown
        with pytest.raises(DrawingLayoutNotFoundError) as err:
            await write(refused)
        assert err.value.fields == ("layout_id",)
    assert await write(live) == live
    before, new = await drawings.get(owner, target), str(uuid.uuid4())
    assert before is not None
    refused_op = (CreateOp(str(uuid.uuid4()), _f(foreign)) if op == "create"
                  else UpdateOp(target, before.updated_at, _f(foreign)))  # fmt: skip
    with pytest.raises(DrawingLayoutNotFoundError) as err:
        await drawings.apply_batch(owner, [CreateOp(new, _f(live)), refused_op])
    assert err.value.fields == ("operations.1.drawing.layout_id",)
    assert await drawings.get(owner, new) is None  # the whole batch rolled back
    assert await drawings.get(owner, target) == before


async def test_a_batch_racing_the_soft_delete_of_its_layout_never_leaves_a_live_drawing(
    repos: Repos, pg_dsn: str
) -> None:
    drawings, workspaces, owner, wid = repos
    outcomes = {"committed": 0, "rejected": 0}
    held = {"batch": asyncio.Event(), "delete": asyncio.Event()}  # renewed every round

    def hook(side: str, marker: str) -> Any:
        def after(_c: object, _cur: object, statement: str, *_rest: object) -> None:
            if marker in statement:
                held[side].set()  # runs on the loop's thread (greenlet), after the lock is taken

        return after

    dengine = drawings._relational._engine.sync_engine
    wengine = workspaces._relational._engine.sync_engine
    # The batch's only `layouts` statement is its layout check, whatever its lock strength.
    event.listen(dengine, "after_cursor_execute", hook("batch", "FROM layouts"))
    event.listen(wengine, "after_cursor_execute", hook("delete", "ORDER BY id FOR UPDATE"))
    for n in range(ROUNDS):
        lid = await _layout(workspaces, owner, wid)
        old, new = str(uuid.uuid4()), str(uuid.uuid4())
        token = (await drawings.create(owner, old, _f(lid))).updated_at
        ops: list[BatchOp] = [CreateOp(new, _f(lid)), UpdateOp(old, token, _f(lid))]
        held.update(batch=asyncio.Event(), delete=asyncio.Event())
        go, mode = asyncio.Event(), n % 3  # 0: together, 1: batch locks first, 2: delete first
        batch = _parked(held["delete"] if mode == 2 else go, drawings.apply_batch(owner, ops))
        delete = _parked(held["batch"] if mode == 1 else go,
                         workspaces.soft_delete_layout(owner, wid, lid))  # fmt: skip
        got = await asyncio.gather(batch, delete, _release(go))  # a 40P01 or other error escapes
        outcome = got[0]
        assert mode == 0 or outcome == ("committed" if mode == 1 else "rejected"), (n, outcome)
        outcomes[outcome] += 1
        with _sync(pg_dsn) as c:
            ts = c.execute("SELECT deleted_at FROM layouts WHERE id = %s", (lid,)).fetchone()
            got_rows = c.execute(
                "SELECT id::text, deleted_at FROM drawings WHERE id = ANY(%s::uuid[])",
                ([old, new],),
            ).fetchall()
        rows: dict[str, object] = {str(i): ts for i, ts in got_rows}
        assert ts is not None and ts[0] is not None  # L is soft-deleted in every round
        assert rows[old] == ts[0]  # the pre-existing drawing went with L
        if outcome == "committed":
            assert rows[new] == ts[0]  # committed first: the delete cascaded to the new row
        else:
            assert new not in rows  # the delete won: the batch found L gone and wrote nothing
    _assert_settled(pg_dsn, owner, outcomes, ROUNDS)
    print("LAYOUT_RACE_OUTCOMES=" + repr(outcomes))


async def test_a_two_layout_batch_racing_a_workspace_soft_delete_never_leaves_a_live_drawing(
    repos: Repos, pg_dsn: str
) -> None:
    drawings, workspaces, owner, _home = repos  # `_home` stays live: never the last workspace
    outcomes, checks = {"committed": 0, "rejected": 0}, [0]

    def count(_c: object, _cur: object, statement: str, *_rest: object) -> None:
        if "FROM layouts" in statement:
            # `checks[0]` counts the drawings engine's `FROM layouts` statements: the batch runs
            # one (its layout check) per attempt, so a 40P01 retry would make it 2.
            checks[0] += 1

    event.listen(drawings._relational._engine.sync_engine, "before_cursor_execute", count)
    plain = pg_dsn.replace("postgresql+asyncpg", "postgresql")
    async with await psycopg.AsyncConnection.connect(plain, autocommit=True) as poll:
        for n in range(WS_ROUNDS):
            wid = str(uuid.uuid4())
            await workspaces.create_workspace(
                owner, wid, WorkspaceFields(f"w-{wid}", False, "workspace.default", 0)
            )
            lo, hi = sorted(str(uuid.uuid4()) for _ in range(2))
            l1, l2 = (lo, hi) if n % 4 < 2 else (hi, lo)  # both id orders, both modes
            await _layout(workspaces, owner, wid, l1)
            await _layout(workspaces, owner, wid, l2)
            old, new = str(uuid.uuid4()), str(uuid.uuid4())
            token = (await drawings.create(owner, old, _f(l2))).updated_at
            ops: list[BatchOp] = [CreateOp(new, _f(l1)), UpdateOp(old, token, _f(l2))]
            batch_first = n % 2 == 0
            with _sync(pg_dsn, autocommit=False) as third:
                if batch_first:  # the batch's insert of `new` waits for this transaction
                    third.execute(
                        "INSERT INTO drawings (id, owner_user_id, symbol, tool, geometry) "
                        "VALUES (%s, %s, 'BTCUSDT', 'trendline', '{\"points\":[]}'::jsonb)",
                        (new, owner),
                    )
                else:  # the delete's cascade to `old` waits for this transaction
                    third.execute("SELECT 1 FROM drawings WHERE id = %s FOR UPDATE", (old,))
                checks[0] = 0
                batch = _outcome(drawings.apply_batch(owner, ops))
                delete = _outcome(workspaces.soft_delete_workspace(owner, wid))
                sides = [(batch, "drawings-race"), (delete, "workspaces-race")]
                async with asyncio.TaskGroup() as tg:  # a 40P01, 503 or other error escapes
                    tasks = []
                    for work, side in sides if batch_first else sides[::-1]:
                        tasks.append(tg.create_task(work))
                        await _until_waiting(poll, side)  # holding its locks, or waiting
                    third.rollback()  # release the parked side
            outcome = tasks[0 if batch_first else 1].result()
            assert outcome == ("committed" if batch_first else "rejected"), (n, outcome)
            assert checks[0] == 1, (n, checks)  # the layout check ran once: no 40P01 retry
            outcomes[outcome] += 1
            _assert_one_cascade(pg_dsn, (l1, l2), old, new, outcome)
    _assert_settled(pg_dsn, owner, outcomes, WS_ROUNDS)
    print("WORKSPACE_RACE_OUTCOMES=" + repr(outcomes))


@pytest.mark.parametrize("late", [False, True])  # the third connection lets go before/after
@pytest.mark.parametrize("writer", ["delete", "replace"])
async def test_two_layout_writers_lock_in_id_order_so_a_batch_never_deadlocks(
    repos: Repos, pg_dsn: str, writer: str, late: bool
) -> None:
    drawings, workspaces, owner, _home = repos  # `_home` stays live: never the last workspace
    checks = [0]

    def count(_c: object, _cur: object, statement: str, *_rest: object) -> None:
        if "FROM layouts" in statement:
            # `checks[0]` counts the drawings engine's `FROM layouts` statements: the batch runs
            # one (its layout check) per attempt, so a 40P01 rerun would make it 2.
            checks[0] += 1

    event.listen(drawings._relational._engine.sync_engine, "before_cursor_execute", count)
    for rel in (drawings._relational, workspaces._relational):
        event.listen(rel._engine.sync_engine, "connect", _fast_deadlock_check)
        await rel.dispose()  # reconnect: every connection now has the short deadlock_timeout
        async with rel.unit_of_work() as uow:
            got: str = (await uow.session.execute(text("SHOW deadlock_timeout"))).scalar_one()
            assert got == f"{DEADLOCK_MS}ms"
    plain = pg_dsn.replace("postgresql+asyncpg", "postgresql")
    async with await psycopg.AsyncConnection.connect(plain, autocommit=True) as poll:
        for _ in range(DEADLOCK_ROUNDS):
            wid, (lo, hi) = str(uuid.uuid4()), sorted(str(uuid.uuid4()) for _ in range(2))
            await workspaces.create_workspace(
                owner, wid, WorkspaceFields(f"w-{wid}", False, "workspace.default", 0)
            )
            await _layout(workspaces, owner, wid, hi, name="a")  # first by insert and by name
            await _layout(workspaces, owner, wid, lo, name="b", default=True)
            old, new = str(uuid.uuid4()), str(uuid.uuid4())
            token = (await drawings.create(owner, old, _f(hi))).updated_at
            ops: list[BatchOp] = [CreateOp(new, _f(lo)), UpdateOp(old, token, _f(hi))]
            take = LayoutFields("a", "1x1", None, True, False, False, None, True, ())
            write = (
                workspaces.soft_delete_workspace(owner, wid)
                if writer == "delete"
                else workspaces.replace_layout(owner, wid, hi, take, if_match=None)
            )
            with _sync(pg_dsn, autocommit=False) as third:
                third.execute("SELECT 1 FROM layouts WHERE id = %s FOR SHARE", (lo,))
                checks[0] = 0
                async with asyncio.TaskGroup() as tg:  # a 40P01 on the writer escapes
                    tg.create_task(write)
                    await _until_waiting(poll, "workspaces-race")  # queued on `lo`
                    batch = tg.create_task(_outcome(drawings.apply_batch(owner, ops)))
                    await _until_waiting(poll, "drawings-race", done=batch)
                    if late:  # both sides' deadlock checks have run before the third lets go
                        await _until_waiting(poll, "workspaces-race", ms=3 * DEADLOCK_MS)
                        await _until_waiting(poll, "drawings-race", ms=3 * DEADLOCK_MS, done=batch)
                    third.rollback()
            # The outcome relies on Postgres granting the batch's FOR SHARE on `lo` alongside the
            # writer's queued FOR NO KEY UPDATE (the third connection holds a compatible FOR SHARE).
            assert (batch.result(), checks[0]) == ("committed", 1)  # first attempt, no rerun
            with _sync(pg_dsn) as c:
                kept = c.execute(
                    "SELECT count(*) FROM drawings d JOIN layouts l ON l.id = d.layout_id "
                    "WHERE d.id = ANY(%s::uuid[]) "
                    "AND (d.deleted_at IS NULL) = (l.deleted_at IS NULL)",
                    ([old, new],),
                ).fetchone()
                state = c.execute(
                    "SELECT bool_and(deleted_at IS NOT NULL), bool_and(is_default = "
                    "(id = %s::uuid)) FROM layouts WHERE id = ANY(%s::uuid[])",
                    (hi, [lo, hi]),
                ).fetchone()
            assert kept == (2,)  # each drawing shares its layout's fate: nothing stray
            assert state == (writer == "delete", writer == "replace")  # deleted, or default moved
