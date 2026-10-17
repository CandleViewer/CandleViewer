"""Integration (CI-only, testcontainers): the drawings layout check against a racing layout soft
delete (E15-T01 spec Sec.7, #402). Two engines (two connections), `asyncio.Event` barriers, no
sleeps. Rounds rotate three modes: both sides released together, the batch released only once
the delete holds the layout row, and the delete released only once the batch holds its share
lock (an engine hook sets the event), so both interleavings are exercised every run.
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
from sqlalchemy import event
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.drawings import (
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


def _sync(dsn: str) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


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


async def _layout(workspaces: SqlAlchemyWorkspaceRepository, owner: str, wid: str) -> str:
    lid = str(uuid.uuid4())
    fields = LayoutFields(f"l-{lid}", "1x1", None, True, False, False, None, False, ())
    await workspaces.create_layout(owner, wid, lid, fields)
    return lid


async def _parked(gate: asyncio.Event, work: Coroutine[Any, Any, object]) -> str:
    """Wait at the barrier, then run `work`: "rejected" on a layout refusal, else "committed"."""
    await gate.wait()
    try:
        await work
    except DrawingLayoutNotFoundError:
        return "rejected"
    return "committed"


async def _release(gate: asyncio.Event) -> str:
    gate.set()  # both sides are parked on the event: release them together
    return "released"


async def test_only_an_own_live_layout_passes_and_a_refused_batch_writes_nothing(
    repos: Repos, pg_dsn: str
) -> None:
    drawings, workspaces, owner, wid = repos
    live, gone = await _layout(workspaces, owner, wid), await _layout(workspaces, owner, wid)
    await workspaces.soft_delete_layout(owner, wid, gone)
    foreign = await _layout(workspaces, *await _owner(pg_dsn, workspaces))
    assert (await drawings.create(owner, str(uuid.uuid4()), _f(live))).layout_id == live
    for refused in (gone, foreign, str(uuid.uuid4())):  # deleted, another owner's, unknown
        with pytest.raises(DrawingLayoutNotFoundError) as err:
            await drawings.create(owner, str(uuid.uuid4()), _f(refused))
        assert err.value.fields == ("layout_id",)
    new = str(uuid.uuid4())
    ops = [CreateOp(new, _f(live)), CreateOp(str(uuid.uuid4()), _f(foreign))]
    with pytest.raises(DrawingLayoutNotFoundError) as err:
        await drawings.apply_batch(owner, ops)
    assert err.value.fields == ("operations.1.drawing.layout_id",)
    assert await drawings.get(owner, new) is None  # the whole batch rolled back


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
    event.listen(dengine, "after_cursor_execute", hook("batch", "FOR SHARE"))
    event.listen(wengine, "after_cursor_execute", hook("delete", "ORDER BY id FOR UPDATE"))
    for n in range(ROUNDS):
        lid = await _layout(workspaces, owner, wid)
        old, new = str(uuid.uuid4()), str(uuid.uuid4())
        token = (await drawings.create(owner, old, _f(lid))).updated_at
        ops = [CreateOp(new, _f(lid)), UpdateOp(old, token, _f(lid))]
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
        rows = dict(got_rows)
        assert ts is not None and ts[0] is not None  # L is soft-deleted in every round
        assert rows[old] == ts[0]  # the pre-existing drawing went with L
        if outcome == "committed":
            assert rows[new] == ts[0]  # committed first: the delete cascaded to the new row
        else:
            assert new not in rows  # the delete won: the batch found L gone and wrote nothing
    with _sync(pg_dsn) as c:
        stray = c.execute(
            "SELECT count(*) FROM drawings d JOIN layouts l ON l.id = d.layout_id "
            "WHERE d.owner_user_id = %s AND d.deleted_at IS NULL AND l.deleted_at IS NOT NULL",
            (owner,),
        ).fetchone()
    assert stray == (0,) and sum(outcomes.values()) == ROUNDS, outcomes
    print("LAYOUT_RACE_OUTCOMES=" + repr(outcomes))
