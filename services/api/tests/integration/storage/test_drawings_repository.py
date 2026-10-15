"""Integration: `SqlAlchemyDrawingRepository` on real Postgres 16 (E14-T01, migration 0021).

CI-only (testcontainers; no docker socket locally).

Batch rule names: an update/delete target outside the caller's own rows (another owner's, live or
deleted, or missing) is `target_not_owned`, the repository's internal name for what the API audits
and answers as the wire rule `target_unavailable`; the caller's own soft-deleted target is
`target_unavailable`. Test names that say `target_unavailable` speak of the wire rule.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import statistics
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import psycopg
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import event
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.drawings import (
    BatchOp,
    BatchOpFailed,
    CreateOp,
    DeleteOp,
    DrawingFields,
    DrawingIdUnavailableError,
    DrawingNotFoundError,
    DrawingRow,
    DrawingVersionConflictError,
    UpdateOp,
)
from candleviewer.storage.repositories.drawings_sqlalchemy import (
    _INSERT_MANY,
    _LIST,
    _SNAPSHOT,
    _SOFT_DELETE_MANY,
    _UPDATE_MANY,
    MAX_BATCH_OPS_STORAGE,
    SqlAlchemyDrawingRepository,
    _row_json,
    _rows_param,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_T = datetime(2026, 10, 1, tzinfo=UTC)


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


def _sync(dsn: str) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _user(dsn: str) -> str:
    uid = str(uuid.uuid4())
    with _sync(dsn) as c:
        c.execute(
            "INSERT INTO users (id, email, username, password_hash) "
            "VALUES (%s, %s, %s, '$argon2id$x')",
            (uid, f"{uid[:8]}@x.io", f"u{uid[:8]}"),
        )
    return uid


def _layout(dsn: str, owner: str) -> str:
    """A live layout of `owner`: 0022's composite FK (D27) refuses a raw layout uuid."""
    wid, lid = str(uuid.uuid4()), str(uuid.uuid4())
    with _sync(dsn) as c:
        c.execute("INSERT INTO workspaces (id, user_id, name) VALUES (%s, %s, 'w')", (wid, owner))
        c.execute(
            "INSERT INTO layouts (id, workspace_id, owner_user_id, name) VALUES (%s, %s, %s, 'l')",
            (lid, wid, owner),
        )
    return lid


def _f(
    symbol: str = "BTCUSDT", *, p: str = "65000.10", layout: str | None = None, label: str = "x"
) -> DrawingFields:
    return DrawingFields(
        symbol=symbol,
        layout_id=layout,
        tool="trendline",
        geometry={
            "points": [
                {"t": "2026-10-01T00:00:00Z", "p": p},
                {"t": "2026-10-02T00:00:00Z", "p": "1.000000000001"},
            ]
        },
        style={"colour": "#ff0000"},
        label=label,
        locked=False,
        visible=True,
        z_index=0,
        anchor_start=_T,
        anchor_end=_T + timedelta(days=1),
    )


@pytest_asyncio.fixture
async def repo(pg_dsn: str) -> AsyncIterator[SqlAlchemyDrawingRepository]:
    rel = SqlAlchemyRelationalRepository(pg_dsn, "drawings-it")
    try:
        yield SqlAlchemyDrawingRepository(rel)
    finally:
        await rel.dispose()


async def test_create_get_list_round_trip_keeps_decimals_verbatim(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, rid = _user(pg_dsn), str(uuid.uuid4())
    made = await repo.create(a, rid, _f(p="65000.10"))
    got = await repo.get(a, rid)
    assert got == made and got is not None
    assert got.geometry["points"][0]["p"] == "65000.10"
    assert got.geometry["points"][1]["p"] == "1.000000000001"
    assert got.owner_user_id == a
    assert [r.id for r in await repo.list_page(a, symbol="BTCUSDT", layout_id=None,
                                                after_id=None, limit=10)] == [rid]  # fmt: skip


async def test_other_owner_cannot_get_update_or_delete(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, b, rid = _user(pg_dsn), _user(pg_dsn), str(uuid.uuid4())
    before = await repo.create(a, rid, _f())
    assert await repo.get(b, rid) is None
    with pytest.raises(DrawingNotFoundError):
        await repo.update(b, rid, _f(label="hijack"), if_match=None)
    assert await repo.soft_delete(b, rid) is False
    assert await repo.exists_for_other_owner(b, rid) is True
    assert await repo.exists_for_other_owner(a, rid) is False
    assert await repo.get(a, rid) == before
    assert await repo.list_page(b, symbol="BTCUSDT", layout_id=None, after_id=None, limit=5) == []


async def test_if_match_conflict_versus_not_found_and_last_write_wins(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, rid = _user(pg_dsn), str(uuid.uuid4())
    first = await repo.create(a, rid, _f())
    second = await repo.update(a, rid, _f(label="two"), if_match=first.updated_at)
    with pytest.raises(DrawingVersionConflictError):
        await repo.update(a, rid, _f(label="stale"), if_match=first.updated_at)
    with pytest.raises(DrawingNotFoundError):
        await repo.update(a, str(uuid.uuid4()), _f(), if_match=first.updated_at)
    lww = await repo.update(a, rid, _f(label="lww"), if_match=None)
    assert lww.label == "lww" and lww.updated_at > second.updated_at


async def test_token_strictly_increases_on_rapid_updates(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, rid = _user(pg_dsn), str(uuid.uuid4())
    row = await repo.create(a, rid, _f())
    seen = [row.updated_at]
    for i in range(15):
        row = await repo.update(a, rid, _f(label=str(i)), if_match=None)
        seen.append(row.updated_at)
    assert all(x < y for x, y in pairwise(seen))


async def test_soft_delete_hides_row_but_keeps_it(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, rid = _user(pg_dsn), str(uuid.uuid4())
    await repo.create(a, rid, _f())
    assert await repo.soft_delete(a, rid) is True
    assert await repo.soft_delete(a, rid) is False
    assert await repo.get(a, rid) is None
    assert await repo.list_page(a, symbol="BTCUSDT", layout_id=None, after_id=None, limit=5) == []
    with pytest.raises(DrawingNotFoundError):
        await repo.update(a, rid, _f(), if_match=None)
    with _sync(pg_dsn) as c:
        row = c.execute("SELECT deleted_at FROM drawings WHERE id = %s", (rid,)).fetchone()
    assert row is not None and row[0] is not None


async def test_create_with_used_id_is_id_unavailable_for_any_owner_or_state(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, b, rid = _user(pg_dsn), _user(pg_dsn), str(uuid.uuid4())
    await repo.create(a, rid, _f())
    with pytest.raises(DrawingIdUnavailableError):
        await repo.create(b, rid, _f())
    await repo.soft_delete(a, rid)
    with pytest.raises(DrawingIdUnavailableError):
        await repo.create(a, rid, _f())


async def test_concurrent_create_race_maps_to_id_unavailable(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, rid = _user(pg_dsn), str(uuid.uuid4())
    res = await asyncio.gather(
        *(repo.create(a, rid, _f(label=str(i))) for i in range(6)), return_exceptions=True
    )
    assert sum(not isinstance(r, BaseException) for r in res) == 1
    assert all(isinstance(r, DrawingIdUnavailableError) for r in res if isinstance(r, Exception))


async def test_batch_is_atomic_and_reports_target_unavailable_index(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    dead = str(uuid.uuid4())
    await repo.create(a, dead, _f())
    await repo.soft_delete(a, dead)
    new = [str(uuid.uuid4()) for _ in range(3)]
    ops: list[BatchOp] = [CreateOp(i, _f()) for i in new]
    ops.append(UpdateOp(dead, _T, _f()))
    with pytest.raises(BatchOpFailed) as err:
        await repo.apply_batch(a, ops)
    assert (err.value.index, err.value.rule) == (3, "target_unavailable")
    assert [await repo.get(a, i) for i in new] == [None, None, None]


async def test_batch_id_unavailable_for_foreign_and_own_deleted_ids(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, b = _user(pg_dsn), _user(pg_dsn)
    foreign, own, foreign_gone = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await repo.create(b, foreign, _f())
    await repo.create(a, own, _f())
    await repo.soft_delete(a, own)
    await repo.create(b, foreign_gone, _f())  # the snapshot sees only A's rows: for a foreign id
    await repo.soft_delete(b, foreign_gone)  # it is the INSERT's primary-key collision, any state
    for taken in (foreign, own, foreign_gone):
        fresh = str(uuid.uuid4())
        with pytest.raises(BatchOpFailed) as err:
            await repo.apply_batch(a, [CreateOp(fresh, _f()), CreateOp(taken, _f())])
        assert (err.value.index, err.value.rule) == (1, "id_unavailable")
        assert await repo.get(a, fresh) is None  # the whole batch rolled back, the INSERT clash too


async def test_batch_foreign_target_is_target_unavailable_and_stale_is_version_conflict(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, b, rid = _user(pg_dsn), _user(pg_dsn), str(uuid.uuid4())
    row = await repo.create(a, rid, _f())
    with pytest.raises(BatchOpFailed) as foreign:
        await repo.apply_batch(b, [DeleteOp(rid, row.updated_at)])
    assert (foreign.value.index, foreign.value.rule) == (0, "target_not_owned")
    fresh = await repo.update(a, rid, _f(label="v2"), if_match=None)
    mine = str(uuid.uuid4())
    with pytest.raises(BatchOpFailed) as stale:
        await repo.apply_batch(a, [CreateOp(mine, _f()), DeleteOp(rid, row.updated_at)])
    assert (stale.value.index, stale.value.rule) == (1, "version_conflict")
    assert await repo.get(a, mine) is None
    assert await repo.get(a, rid) == fresh


def _lockable(dsn: str, drawing_id: str) -> bool:
    """True when a second connection can lock the row at once (`FOR UPDATE NOWAIT`)."""
    with _sync(dsn) as c:
        try:
            c.execute("SELECT 1 FROM drawings WHERE id = %s FOR UPDATE NOWAIT", (drawing_id,))
        except psycopg.errors.LockNotAvailable:
            return False
    return True


@pytest.mark.parametrize(
    ("kind", "rule"),
    [("update", "target_not_owned"), ("delete", "target_not_owned"), ("create", "id_unavailable")],
)
async def test_a_batch_naming_a_foreign_id_never_locks_the_victims_row(
    pg_dsn: str, kind: str, rule: str
) -> None:
    """#357 R1: right after B's `SELECT … FOR UPDATE`, with B's batch transaction still open,
    another connection can lock A's row at once, and not B's own (the positive control)."""
    a, b, victim, mine = _user(pg_dsn), _user(pg_dsn), str(uuid.uuid4()), str(uuid.uuid4())
    held: dict[str, bool] = {}

    def probe(conn: Any, cursor: Any, statement: str, params: Any, ctx: Any, many: bool) -> None:
        if "FOR UPDATE" in statement:  # the batch snapshot is the only locking statement
            held["victim"], held["own"] = not _lockable(pg_dsn, victim), not _lockable(pg_dsn, mine)

    rel = SqlAlchemyRelationalRepository(pg_dsn, "drawings-lock-it")
    try:
        repo = SqlAlchemyDrawingRepository(rel)
        await repo.create(a, victim, _f(label="victim"))
        own = await repo.create(b, mine, _f(label="own"))
        event.listen(rel._engine.sync_engine, "after_cursor_execute", probe)
        aimed: BatchOp = {
            "update": UpdateOp(victim, _T, _f()),
            "delete": DeleteOp(victim, _T),
            "create": CreateOp(victim, _f()),
        }[kind]
        with pytest.raises(BatchOpFailed) as err:
            await repo.apply_batch(b, [UpdateOp(mine, own.updated_at, _f(label="x")), aimed])
    finally:
        await rel.dispose()
    assert (err.value.index, err.value.rule) == (1, rule)
    assert held == {"victim": False, "own": True}
    assert _lockable(pg_dsn, victim) and _lockable(pg_dsn, mine)  # rolled back: nothing held


async def test_batch_success_collects_results_in_op_order(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, u, d = _user(pg_dsn), str(uuid.uuid4()), str(uuid.uuid4())
    ru, rd = await repo.create(a, u, _f()), await repo.create(a, d, _f())
    c1, c2 = str(uuid.uuid4()), str(uuid.uuid4())
    ops: list[BatchOp] = [
        CreateOp(c1, _f()),
        UpdateOp(u, ru.updated_at, _f(label="n")),
        DeleteOp(d, rd.updated_at),
        CreateOp(c2, _f()),
    ]
    out = await repo.apply_batch(a, ops)
    assert [r.id for r in out.created] == [c1, c2]
    assert [(r.id, r.label) for r in out.updated] == [(u, "n")]
    assert out.deleted == (d,)
    assert await repo.get(a, d) is None


async def test_list_keyset_paging_and_layout_filter(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    ids = sorted(str(uuid.uuid4()) for _ in range(5))
    for i in ids:
        await repo.create(a, i, _f("ETHUSDT"))
    first = await repo.list_page(a, symbol="ETHUSDT", layout_id=None, after_id=None, limit=3)
    rest = await repo.list_page(a, symbol="ETHUSDT", layout_id=None, after_id=first[-1].id, limit=3)
    assert [r.id for r in first + rest] == ids
    assert await repo.list_page(a, symbol="SOLUSDT", layout_id=None, after_id=None, limit=3) == []
    lay = _layout(pg_dsn, a)
    tagged = str(uuid.uuid4())
    await repo.create(a, tagged, _f("ETHUSDT", layout=lay))
    got = await repo.list_page(a, symbol="ETHUSDT", layout_id=lay, after_id=None, limit=10)
    assert [r.id for r in got] == [tagged]


async def test_purge_respects_the_90_day_boundary_and_the_limit(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    """Touches only this test's own ids (C-13.7); other tests' rows are never rewritten."""
    a = _user(pg_dsn)
    young, old = [str(uuid.uuid4()) for _ in range(2)], [str(uuid.uuid4()) for _ in range(3)]
    live = str(uuid.uuid4())
    await repo.create(a, live, _f())
    for i in young + old:
        await repo.create(a, i, _f())
        await repo.soft_delete(a, i)
    with _sync(pg_dsn) as c:
        c.execute("UPDATE drawings SET deleted_at = now() - interval '89 days' WHERE id = ANY(%s)",
                  (young,))  # fmt: skip
        c.execute("UPDATE drawings SET deleted_at = now() - interval '91 days' WHERE id = ANY(%s)",
                  (old,))  # fmt: skip
        # Age the live row's created/updated too: a purge filtering on the wrong column
        # (created_at / updated_at instead of deleted_at) would delete it and fail below.
        c.execute("UPDATE drawings SET created_at = now() - interval '200 days', "
                  "updated_at = now() - interval '200 days' WHERE id = %s", (live,))  # fmt: skip

    def remaining() -> set[str]:
        with _sync(pg_dsn) as c:
            rows = c.execute(
                "SELECT id::text FROM drawings WHERE id = ANY(%s)", (young + old + [live],)
            ).fetchall()
        return {str(r[0]) for r in rows}

    assert await repo.purge_deleted(90, 1) == 1  # the limit caps one call
    assert len(remaining() & set(old)) == 2
    # Other tests only leave freshly deleted rows, so only this test's `old` rows qualify.
    assert await repo.purge_deleted(90, 100) == 2
    assert remaining() == set(young) | {live}  # 89-day-old and live rows survive
    assert await repo.purge_deleted(90, 100) == 0
    assert (await repo.get(a, live)) is not None


async def test_batch_duplicate_create_id_fails_at_the_second_create_and_rolls_back_everything(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, x = _user(pg_dsn), str(uuid.uuid4())
    with pytest.raises(BatchOpFailed) as err:
        await repo.apply_batch(a, [CreateOp(x, _f()), CreateOp(x, _f())])
    assert (err.value.index, err.value.rule) == (1, "id_unavailable")
    assert await repo.get(a, x) is None


async def test_idor_batch_update_by_other_owner_with_real_token_changes_nothing(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, b, rid = _user(pg_dsn), _user(pg_dsn), str(uuid.uuid4())
    mine = await repo.create(a, rid, _f(label="mine"))
    with pytest.raises(BatchOpFailed) as err:
        await repo.apply_batch(b, [UpdateOp(rid, mine.updated_at, _f(label="hijack"))])
    assert (err.value.index, err.value.rule) == (0, "target_not_owned")
    after = await repo.get(a, rid)
    assert after is not None and (after.label, after.updated_at) == ("mine", mine.updated_at)


async def test_idor_single_update_by_other_owner_is_not_found_for_any_token(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, b, rid = _user(pg_dsn), _user(pg_dsn), str(uuid.uuid4())
    mine = await repo.create(a, rid, _f(label="mine"))
    stale = mine.updated_at - timedelta(seconds=5)
    for token in (mine.updated_at, stale):
        with pytest.raises(DrawingNotFoundError):  # never VersionConflict: no oracle
            await repo.update(b, rid, _f(label="hijack"), if_match=token)
    after = await repo.get(a, rid)
    assert after is not None and (after.label, after.updated_at) == ("mine", mine.updated_at)


async def test_idor_other_owners_deleted_row_is_target_unavailable_in_a_batch(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, b, rid = _user(pg_dsn), _user(pg_dsn), str(uuid.uuid4())
    mine = await repo.create(a, rid, _f(label="mine"))
    await repo.soft_delete(a, rid)
    with _sync(pg_dsn) as c:
        before = c.execute(
            "SELECT label, updated_at FROM drawings WHERE id = %s", (rid,)
        ).fetchone()
    for op in (DeleteOp(rid, mine.updated_at), UpdateOp(rid, mine.updated_at, _f(label="x"))):
        with pytest.raises(BatchOpFailed) as err:
            await repo.apply_batch(b, [op])
        assert (err.value.index, err.value.rule) == (0, "target_not_owned")
    with _sync(pg_dsn) as c:
        assert (
            c.execute("SELECT label, updated_at FROM drawings WHERE id = %s", (rid,)).fetchone()
            == before
        )


async def test_exists_for_other_owner_is_false_for_a_deleted_row(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    """Pinned choice: only LIVE foreign rows count, so the cross-owner audit record is not
    emitted for a deleted id (it is indistinguishable from a missing one)."""
    a, b, rid = _user(pg_dsn), _user(pg_dsn), str(uuid.uuid4())
    await repo.create(a, rid, _f())
    assert await repo.exists_for_other_owner(b, rid) is True
    await repo.soft_delete(a, rid)
    assert await repo.exists_for_other_owner(b, rid) is False


async def test_batch_stale_update_token_and_never_existed_target(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, rid = _user(pg_dsn), str(uuid.uuid4())
    first = await repo.create(a, rid, _f(label="v1"))
    cur = await repo.update(a, rid, _f(label="v2"), if_match=None)
    with pytest.raises(BatchOpFailed) as stale:
        await repo.apply_batch(a, [UpdateOp(rid, first.updated_at, _f(label="v3"))])
    assert (stale.value.index, stale.value.rule) == (0, "version_conflict")
    with pytest.raises(BatchOpFailed) as ghost:
        await repo.apply_batch(a, [UpdateOp(str(uuid.uuid4()), _T, _f())])
    assert (ghost.value.index, ghost.value.rule) == (0, "target_not_owned")
    assert await repo.get(a, rid) == cur


async def test_batch_update_cannot_change_symbol_or_tool(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, rid, other = _user(pg_dsn), str(uuid.uuid4()), str(uuid.uuid4())
    mine = await repo.create(a, rid, _f("BTCUSDT", label="mine"))
    changed_tool = dataclasses.replace(_f("BTCUSDT"), tool="rectangle")
    for bad in (_f("ETHUSDT", label="x"), changed_tool):
        with pytest.raises(BatchOpFailed) as err:
            await repo.apply_batch(a, [CreateOp(other, _f()), UpdateOp(rid, mine.updated_at, bad)])
        assert (err.value.index, err.value.rule) == (1, "immutable_field")
        assert await repo.get(a, other) is None  # whole batch rolled back
        assert await repo.get(a, rid) == mine  # row (incl. token) unchanged


@pytest.mark.parametrize("target", ["live", "deleted", "missing"])
@pytest.mark.parametrize("change", ["symbol", "tool"])
async def test_immutable_field_is_never_an_oracle_for_another_owner(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str, target: str, change: str
) -> None:
    """Ownership/liveness is checked BEFORE immutability: B changing symbol/tool on a row
    it cannot see must get `target_not_owned`, never `immutable_field` (which would leak
    A's symbol/tool). Pins the check order."""
    a, b, rid = _user(pg_dsn), _user(pg_dsn), str(uuid.uuid4())
    token = _T
    mine = None
    if target != "missing":
        mine = await repo.create(a, rid, _f("BTCUSDT", label="mine"))
        token = mine.updated_at
    if target == "deleted":
        await repo.soft_delete(a, rid)
    fields = _f("ETHUSDT") if change == "symbol" else dataclasses.replace(_f(), tool="rectangle")
    with pytest.raises(BatchOpFailed) as err:
        await repo.apply_batch(b, [UpdateOp(rid, token, fields)])
    assert (err.value.index, err.value.rule) == (0, "target_not_owned")
    if target == "live":
        assert await repo.get(a, rid) == mine


_SEED_USERS = 20
_SEED_ROWS = 50_000
_RUNS = 200


async def _explain(
    repo: SqlAlchemyRelationalRepository, analyze: bool, params: dict[str, Any]
) -> Any:
    option = "ANALYZE, FORMAT JSON" if analyze else "FORMAT JSON"
    # Built only from the two fixed options above and the shipped `_LIST` text; no input.
    # nosemgrep: avoid-sqlalchemy-text reason=explain-shipped-sql owner=@basiltt review=2027-03-25
    stmt = sa.text(f"EXPLAIN ({option}) " + _LIST.text)
    async with repo.unit_of_work() as uow:
        return (await uow.session.execute(stmt, params)).scalar_one()


@pytest.mark.perf
async def test_list_uses_ix_dr_user_symbol_and_p99_under_5ms(pg_dsn: str) -> None:
    """Ticket perf scenario on the repository's shipped `_LIST` statement (query #28).

    50k rows over 20 users; the real parameter shape (layout NULL, after_id set). The plan
    must use `ix_dr_user_symbol`. The latency budget is the p99 of the server-side
    `Execution Time` of `EXPLAIN (ANALYZE, FORMAT JSON)` over 200 runs, in ms; it excludes
    planning time and client/Docker round trips, which the AC does not measure.
    """
    users = [_user(pg_dsn) for _ in range(_SEED_USERS)]
    syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    geom = json.dumps({"points": [{"t": "2026-10-01T00:00:00Z", "p": "1"}] * 2})
    with _sync(pg_dsn) as c:
        for u in users:
            c.execute(
                "INSERT INTO drawings (id, owner_user_id, symbol, tool, geometry) "
                "SELECT gen_random_uuid(), %s::uuid, (%s::text[])[1 + g %% 4]::symbol_code, "
                "'trendline', %s::jsonb FROM generate_series(1, %s) g",
                (u, syms, geom, _SEED_ROWS // _SEED_USERS),
            )
        c.execute("ANALYZE drawings")
    params: dict[str, Any] = {
        "owner": users[0],
        "symbol": "BTCUSDT",
        "layout": None,
        "after_id": "00000000-0000-0000-0000-000000000000",
        "limit": 101,
    }
    rel = SqlAlchemyRelationalRepository(pg_dsn, "drawings-perf")
    try:
        assert "ix_dr_user_symbol" in json.dumps(await _explain(rel, False, params))
        for _ in range(20):  # warm-up
            await _explain(rel, True, params)
        server_ms = [
            float((await _explain(rel, True, params))[0]["Execution Time"]) for _ in range(_RUNS)
        ]
    finally:
        await rel.dispose()
    p99 = statistics.quantiles(server_ms, n=100)[98]
    print(f"drawings list server-side p99 = {p99:.3f} ms over {len(server_ms)} runs")
    assert p99 < 5.0, f"server-side p99 {p99:.3f} ms"


async def test_count_live_by_tool_counts_only_live_rows_of_every_owner(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    """Deltas, not absolutes: other tests share the module database (C-13.7)."""
    a, b = _user(pg_dsn), _user(pg_dsn)
    before = await repo.count_live_by_tool()
    gone = str(uuid.uuid4())
    for owner in (a, b):
        await repo.create(owner, str(uuid.uuid4()), _f())
    await repo.create(a, str(uuid.uuid4()), dataclasses.replace(_f(), tool="rectangle"))
    await repo.create(a, gone, _f())
    await repo.soft_delete(a, gone)  # a soft-deleted row is not counted
    after = await repo.count_live_by_tool()
    assert after.get("trendline", 0) - before.get("trendline", 0) == 2
    assert after.get("rectangle", 0) - before.get("rectangle", 0) == 1
    assert all(isinstance(k, str) and isinstance(v, int) for k, v in after.items())


async def test_set_based_batch_mixed_success_keeps_order_and_bumps_tokens(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    ups = [str(uuid.uuid4()) for _ in range(3)]
    dels = [str(uuid.uuid4()) for _ in range(3)]
    rows = {i: await repo.create(a, i, _f()) for i in ups + dels}
    news = [str(uuid.uuid4()) for _ in range(4)]
    ops: list[BatchOp] = [
        CreateOp(news[0], _f(label="c0")),
        DeleteOp(dels[2], rows[dels[2]].updated_at),
        UpdateOp(ups[1], rows[ups[1]].updated_at, _f(label="u1")),
        CreateOp(news[1], _f(label="c1")),
        UpdateOp(ups[0], rows[ups[0]].updated_at, _f(label="u0")),
        DeleteOp(dels[0], rows[dels[0]].updated_at),
        CreateOp(news[2], _f(label="c2")),
        UpdateOp(ups[2], rows[ups[2]].updated_at, _f(label="u2")),
        DeleteOp(dels[1], rows[dels[1]].updated_at),
        CreateOp(news[3], _f(label="c3")),
    ]
    out = await repo.apply_batch(a, ops)
    assert [r.id for r in out.created] == news
    assert [r.id for r in out.updated] == [ups[1], ups[0], ups[2]]
    assert [r.label for r in out.updated] == ["u1", "u0", "u2"]
    assert out.deleted == (dels[2], dels[0], dels[1])
    for r in out.updated:
        assert r.updated_at > rows[r.id].updated_at
    assert [await repo.get(a, d) for d in dels] == [None, None, None]
    assert (await repo.get(a, news[3])) is not None


async def test_insert_many_skips_an_existing_id_via_on_conflict_without_erroring(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, b = _user(pg_dsn), _user(pg_dsn)
    taken = str(uuid.uuid4())
    await repo.create(b, taken, _f())
    fresh = [str(uuid.uuid4()) for _ in range(2)]
    payload = json.dumps([_row_json(i, _f()) for i in [fresh[0], taken, fresh[1]]])
    rel = SqlAlchemyRelationalRepository(pg_dsn, "drawings-it-on-conflict")
    try:
        async with rel.unit_of_work() as uow:
            got = await uow.session.execute(_INSERT_MANY, {"owner": a, "rows": payload})
            assert [r["id"] for r in got.mappings()] == fresh
    finally:
        await rel.dispose()


class _RaceSession:
    """Delegates to the real session; after the snapshot runs, commits a rival insert."""

    def __init__(self, inner: Any, rival: Any) -> None:
        self._inner, self._rival = inner, rival

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        res = await self._inner.execute(stmt, params)
        if "FOR UPDATE" in str(stmt):  # the snapshot: the id is still free here
            self._rival()
        return res

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _RaceUow:
    def __init__(self, inner: Any, rival: Any) -> None:
        self._inner, self.session = inner, _RaceSession(inner.session, rival)

    async def commit(self) -> None:
        await self._inner.commit()


class _RaceRelational:
    def __init__(self, real: SqlAlchemyRelationalRepository, rival: Any) -> None:
        self._real, self._rival = real, rival

    def unit_of_work(self) -> Any:
        real, rival = self._real.unit_of_work(), self._rival

        class _Ctx:
            async def __aenter__(self) -> _RaceUow:
                return _RaceUow(await real.__aenter__(), rival)

            async def __aexit__(self, *exc: Any) -> Any:
                return await real.__aexit__(*exc)

        return _Ctx()


async def test_batch_concurrent_create_after_snapshot_is_id_unavailable_via_on_conflict(
    pg_dsn: str,
) -> None:
    a, rival_owner = _user(pg_dsn), _user(pg_dsn)
    first, raced, last = (str(uuid.uuid4()) for _ in range(3))

    def rival() -> None:  # another connection commits `raced` between snapshot and INSERT
        with _sync(pg_dsn) as c:
            c.execute(
                "INSERT INTO drawings (id, owner_user_id, symbol, tool, geometry) "
                "VALUES (%s, %s, 'BTCUSDT', 'trendline', '{\"points\":[]}'::jsonb)",
                (raced, rival_owner),
            )

    rel = SqlAlchemyRelationalRepository(pg_dsn, "drawings-it-race")
    try:
        racing = SqlAlchemyDrawingRepository(
            _RaceRelational(rel, rival)  # type: ignore[arg-type]  # test double of the UoW factory
        )
        with pytest.raises(BatchOpFailed) as err:
            await racing.apply_batch(
                a, [CreateOp(first, _f()), CreateOp(raced, _f()), CreateOp(last, _f())]
            )
        assert (err.value.index, err.value.rule) == (1, "id_unavailable")
        real = SqlAlchemyDrawingRepository(rel)
        assert [await real.get(a, first), await real.get(a, last)] == [None, None]
        assert await real.get(rival_owner, raced) is not None  # only the rival's row exists
    finally:
        await rel.dispose()


async def test_batch_stale_target_deleted_before_batch_fails_at_snapshot_and_rolls_back(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    u, d, c = (str(uuid.uuid4()) for _ in range(3))
    ru, rd = await repo.create(a, u, _f()), await repo.create(a, d, _f())
    await repo.soft_delete(a, d)  # deleted between token read and batch
    with pytest.raises(BatchOpFailed) as err:
        await repo.apply_batch(
            a,
            [
                CreateOp(c, _f()),
                UpdateOp(u, ru.updated_at, _f(label="z")),
                DeleteOp(d, rd.updated_at),
            ],
        )
    assert (err.value.index, err.value.rule) == (2, "target_unavailable")
    assert await repo.get(a, c) is None
    assert (await repo.get(a, u)) == ru


async def test_batch_first_snapshot_failure_in_operation_order_wins(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    u = str(uuid.uuid4())
    ru = await repo.create(a, u, _f())
    ops: list[BatchOp] = [
        UpdateOp(u, ru.updated_at + timedelta(microseconds=5), _f()),
        DeleteOp(str(uuid.uuid4()), _T),
    ]
    with pytest.raises(BatchOpFailed) as err:
        await repo.apply_batch(a, ops)
    assert (err.value.index, err.value.rule) == (0, "version_conflict")


def _plan_nodes(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield node
    for child in node.get("Plans", []):
        yield from _plan_nodes(child)


async def test_bulk_batch_statements_use_the_pk_index_and_never_seq_scan_drawings(
    pg_dsn: str,
) -> None:
    """Plan shape (not wall clock): on 50k+ analysed rows owned by one user, each bulk statement
    reaches `drawings` through `drawings_pkey` and none seq-scans it."""
    owner = _user(pg_dsn)
    with _sync(pg_dsn) as c:
        c.execute(
            "INSERT INTO drawings (id, owner_user_id, symbol, tool, geometry) "
            "SELECT gen_random_uuid(), %s::uuid, 'BTCUSDT', 'trendline', "
            "'{\"points\":[]}'::jsonb FROM generate_series(1, 50000)",
            (owner,),
        )
        c.execute("ANALYZE drawings")
        sample = [str(r[0]) for r in c.execute(
            "SELECT id FROM drawings WHERE owner_user_id = %s LIMIT 50", (owner,)
        ).fetchall()]  # fmt: skip
    f = _f()
    ups = _rows_param([_row_json(i, f, _T) for i in sample])
    news = _rows_param([_row_json(str(uuid.uuid4()), f) for _ in range(100)])
    cases: dict[str, tuple[Any, dict[str, Any]]] = {
        "snapshot": (_SNAPSHOT, {"ids": sample}),
        "insert": (_INSERT_MANY, {"owner": owner, "rows": news}),
        "update": (_UPDATE_MANY, {"owner": owner, "ids": sample, "rows": ups}),
        "delete": (_SOFT_DELETE_MANY, {"owner": owner, "ids": sample}),
    }
    rel = SqlAlchemyRelationalRepository(pg_dsn, "drawings-it-plans")
    try:
        for name, (stmt, params) in cases.items():
            # Built only from a fixed literal and a shipped statement's text; no input.
            # nosemgrep: avoid-sqlalchemy-text reason=explain-sql owner=@basiltt review=2027-03-25
            explain = sa.text("EXPLAIN (FORMAT JSON) " + stmt.text)
            async with rel.unit_of_work() as uow:
                res = await uow.session.execute(explain, params)
                raw = res.scalar_one()
            plan = raw if isinstance(raw, list) else json.loads(raw)
            nodes = list(_plan_nodes(plan[0]["Plan"]))
            assert not [
                n for n in nodes
                if n.get("Node Type") == "Seq Scan" and n.get("Relation Name") == "drawings"
            ], f"{name}: seq scan on drawings"  # fmt: skip
            assert "drawings_pkey" in json.dumps(plan), f"{name}: PK index unused"
    finally:
        await rel.dispose()


_BATCH_RUNS = 500  # measured runs; p99 = ~5th-worst, so 1-2 fsync hiccups cannot decide it
_WARMUP = 10


def _vacuum(dsn: str) -> None:
    with _sync(dsn) as c:  # autocommit: VACUUM cannot run inside a transaction
        c.execute("VACUUM ANALYZE drawings")


def _checkpoint(dsn: str) -> None:
    with _sync(dsn) as c:  # superuser, autocommit
        c.execute("ANALYZE drawings")  # the seed grew the table; stale stats pick owner-index scans
        c.execute("CHECKPOINT")  # flush the test's own seed/warm-up writes


def _timed(label: str, timings: list[float]) -> float:
    p99 = statistics.quantiles(timings, n=100)[98]
    print(f"drawings batch {label}: p50 = {statistics.median(timings):.3f} ms, "
          f"p99 = {p99:.3f} ms, max = {max(timings):.3f} ms over {len(timings)} runs")  # fmt: skip
    return p99


@pytest.mark.perf
async def test_batch_of_200_creates_p99_under_50ms(pg_dsn: str) -> None:
    """Ticket NFR: a batch of 200 ops < 50 ms p99.

    Fixed data: one user, 200 `CreateOp`s with fresh ids per run (ids are the only thing that
    varies). Wall time of `apply_batch` (snapshot lock + insert + commit) as the repository sees
    it, p99 over 500 runs after a warm-up, on the same host as the database.

    Methodology (both choices keep the 50 ms bound exact): 500 measured runs instead of 100,
    because with 100 samples `quantiles(n=100)[98]` is effectively the second-worst run and one
    or two fsync hiccups decide the result; with 500 it is about the 5th-worst.
    An `ANALYZE` and a `CHECKPOINT` run after seeding and warm-up and before measuring. The
    ANALYZE matters because the seed grows the table: with stale statistics the planner
    reached rows through the owner index (`ix_dr_user_symbol`) instead of the primary key. The
    CHECKPOINT keeps the measurement from absorbing the flush of the test's own seed data.

    Where it runs: judged by the isolated `py-perf` CI job (`pytest -m perf`, C-13.9). CI's
    `integration` job passes `-m integration`, which overrides the default `not perf`, so these
    tests ALSO run there in the full-file context; they are judged in both jobs. Local runs on
    a shared laptop are informational only. The time includes the commit, which is what a
    caller experiences.
    """
    owner = _user(pg_dsn)
    _vacuum(pg_dsn)
    rel = SqlAlchemyRelationalRepository(pg_dsn, "drawings-batch-perf")
    repo = SqlAlchemyDrawingRepository(rel)
    fields = _f()

    def ops() -> list[BatchOp]:
        return [CreateOp(str(uuid.uuid4()), fields) for _ in range(200)]

    try:
        for _ in range(_WARMUP):  # warm-up: connection, statement cache
            await repo.apply_batch(owner, ops())
        _checkpoint(pg_dsn)
        timings: list[float] = []
        for _ in range(_BATCH_RUNS):
            batch = ops()
            t0 = time.perf_counter()
            result = await repo.apply_batch(owner, batch)
            timings.append((time.perf_counter() - t0) * 1000)
            assert len(result.created) == 200
    finally:
        await rel.dispose()
    p99 = _timed("(200 creates)", timings)
    assert p99 < 50.0, f"batch p99 {p99:.3f} ms"


@pytest.mark.perf
async def test_mixed_batch_of_200_p99_under_50ms(pg_dsn: str) -> None:
    """Mixed NFR variant: 100 creates + 50 updates + 50 soft deletes per batch (200 ops).

    Methodology (both choices keep the 50 ms bound exact): 500 measured runs instead of 100,
    because with 100 samples `quantiles(n=100)[98]` is effectively the second-worst run and one
    or two fsync hiccups decide the result; with 500 it is about the 5th-worst.
    An `ANALYZE` and a `CHECKPOINT` run after seeding and warm-up and before measuring. The
    ANALYZE matters because the seed grows the table: with stale statistics the planner
    reached rows through the owner index (`ix_dr_user_symbol`) instead of the primary key. The
    CHECKPOINT keeps the measurement from absorbing the flush of the test's own seed data.

    Where it runs: judged by the isolated `py-perf` CI job (`pytest -m perf`, C-13.9). CI's
    `integration` job passes `-m integration`, which overrides the default `not perf`, so these
    tests ALSO run there in the full-file context; they are judged in both jobs. Local runs on
    a shared laptop are informational only. The time includes the commit, which is what a
    caller experiences.
    """
    owner = _user(pg_dsn)
    _vacuum(pg_dsn)
    rel = SqlAlchemyRelationalRepository(pg_dsn, "drawings-batch-perf-mixed")
    repo = SqlAlchemyDrawingRepository(rel)
    fields = _f()
    runs = _WARMUP + _BATCH_RUNS
    pool: list[DrawingRow] = []  # 50 update targets + 50 delete targets per run
    for _ in range(100 * runs // MAX_BATCH_OPS_STORAGE):
        seeded = await repo.apply_batch(
            owner, [CreateOp(str(uuid.uuid4()), fields) for _ in range(MAX_BATCH_OPS_STORAGE)]
        )
        pool.extend(seeded.created)
    try:
        timings: list[float] = []
        for run in range(runs):
            if run == _WARMUP:  # seed + warm-up are flushed before the first measured run
                _checkpoint(pg_dsn)
            chunk = pool[run * 100 : (run + 1) * 100]
            batch: list[BatchOp] = [CreateOp(str(uuid.uuid4()), fields) for _ in range(100)]
            batch += [UpdateOp(r.id, r.updated_at, _f(label="m")) for r in chunk[:50]]
            batch += [DeleteOp(r.id, r.updated_at) for r in chunk[50:]]
            t0 = time.perf_counter()
            result = await repo.apply_batch(owner, batch)
            elapsed = (time.perf_counter() - t0) * 1000
            assert (len(result.created), len(result.updated), len(result.deleted)) == (100, 50, 50)
            if run >= _WARMUP:
                timings.append(elapsed)
    finally:
        await rel.dispose()
    p99 = _timed("(100 creates, 50 updates, 50 deletes)", timings)
    assert p99 < 50.0, f"mixed batch p99 {p99:.3f} ms"
