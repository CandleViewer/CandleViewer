"""Integration: `SqlAlchemyDrawingRepository` on real Postgres 16 (E14-T01, migration 0021).

CI-only (testcontainers; no docker socket locally).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import statistics
import subprocess
import sys
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
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.drawings import (
    BatchOp,
    BatchOpFailed,
    CreateOp,
    DeleteOp,
    DrawingFields,
    DrawingIdUnavailableError,
    DrawingNotFoundError,
    DrawingVersionConflictError,
    UpdateOp,
)
from candleviewer.storage.repositories.drawings_sqlalchemy import (
    _LIST,
    SqlAlchemyDrawingRepository,
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
    foreign, own = str(uuid.uuid4()), str(uuid.uuid4())
    await repo.create(b, foreign, _f())
    await repo.create(a, own, _f())
    await repo.soft_delete(a, own)
    for taken in (foreign, own):
        with pytest.raises(BatchOpFailed) as err:
            await repo.apply_batch(a, [CreateOp(str(uuid.uuid4()), _f()), CreateOp(taken, _f())])
        assert (err.value.index, err.value.rule) == (1, "id_unavailable")


async def test_batch_foreign_target_is_target_unavailable_and_stale_is_version_conflict(
    repo: SqlAlchemyDrawingRepository, pg_dsn: str
) -> None:
    a, b, rid = _user(pg_dsn), _user(pg_dsn), str(uuid.uuid4())
    row = await repo.create(a, rid, _f())
    with pytest.raises(BatchOpFailed) as foreign:
        await repo.apply_batch(b, [DeleteOp(rid, row.updated_at)])
    assert (foreign.value.index, foreign.value.rule) == (0, "target_unavailable")
    fresh = await repo.update(a, rid, _f(label="v2"), if_match=None)
    mine = str(uuid.uuid4())
    with pytest.raises(BatchOpFailed) as stale:
        await repo.apply_batch(a, [CreateOp(mine, _f()), DeleteOp(rid, row.updated_at)])
    assert (stale.value.index, stale.value.rule) == (1, "version_conflict")
    assert await repo.get(a, mine) is None
    assert await repo.get(a, rid) == fresh


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
    # layout_id has no FK until E15-T01, so a raw uuid is storable at the data layer.
    lay = str(uuid.uuid4())
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


async def test_batch_duplicate_create_id_hits_the_savepoint_and_rolls_back_everything(
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
    assert (err.value.index, err.value.rule) == (0, "target_unavailable")
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
        assert (err.value.index, err.value.rule) == (0, "target_unavailable")
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
    assert (ghost.value.index, ghost.value.rule) == (0, "target_unavailable")
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
    it cannot see must get `target_unavailable`, never `immutable_field` (which would leak
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
    assert (err.value.index, err.value.rule) == (0, "target_unavailable")
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
