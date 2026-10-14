"""Integration: `SqlAlchemyDrawingRepository` on real Postgres 16 (E14-T01, migration 0021).

CI-only (testcontainers; no docker socket locally).
"""

from __future__ import annotations

import asyncio
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
from candleviewer.storage.repositories.drawings_sqlalchemy import SqlAlchemyDrawingRepository
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
    assert len({r for r in seen}) == len(seen)


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
    a = _user(pg_dsn)
    young, old = [str(uuid.uuid4()) for _ in range(2)], [str(uuid.uuid4()) for _ in range(3)]
    for i in young + old:
        await repo.create(a, i, _f())
        await repo.soft_delete(a, i)
    with _sync(pg_dsn) as c:
        c.execute("UPDATE drawings SET deleted_at = now() - interval '89 days' WHERE id = ANY(%s)",
                  (young,))  # fmt: skip
        c.execute("UPDATE drawings SET deleted_at = now() - interval '91 days' WHERE id = ANY(%s)",
                  (old,))  # fmt: skip
        c.execute("UPDATE drawings SET deleted_at = now() - interval '200 days' "
                  "WHERE deleted_at IS NOT NULL AND id <> ALL(%s)", (young + old,))  # fmt: skip
        stale_elsewhere = c.execute(
            "SELECT count(*) FROM drawings WHERE deleted_at < now() - interval '90 days'"
        ).fetchone()
    assert stale_elsewhere is not None
    total = int(str(stale_elsewhere[0]))
    assert await repo.purge_deleted(90, 1) == 1
    assert await repo.purge_deleted(90, total + 10) == total - 1
    assert await repo.purge_deleted(90, 10) == 0
    with _sync(pg_dsn) as c:
        left = c.execute("SELECT id::text FROM drawings WHERE id = ANY(%s)", (young,)).fetchall()
    assert sorted(str(r[0]) for r in left) == sorted(young)


_SEED_USERS = 20
_SEED_ROWS = 50_000
_RUNS = 200


@pytest.mark.perf
async def test_list_uses_ix_dr_user_symbol_and_p99_under_5ms(pg_dsn: str) -> None:
    """Ticket perf scenario: 50k rows; plan uses the index; server-side p99 < 5 ms (query #28)."""
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
        query = (
            "SELECT id::text, owner_user_id::text, symbol, layout_id::text, tool, geometry, style,"
            " label, locked, visible, z_index, created_at, updated_at FROM drawings"
            " WHERE owner_user_id = %s::uuid AND symbol = 'BTCUSDT' AND deleted_at IS NULL"
            " AND id > %s::uuid ORDER BY id LIMIT 101"
        )
        args = (users[0], "00000000-0000-0000-0000-000000000000")
        plan = c.execute("EXPLAIN (FORMAT JSON) " + query, args).fetchone()
        assert plan is not None and "ix_dr_user_symbol" in json.dumps(plan[0])
        for _ in range(20):  # warm-up
            c.execute(query, args).fetchall()
        # Budget #28 is server-side: use the executor's own "Execution Time", not a client
        # round trip (which adds Docker/network latency the AC does not measure).
        server_ms: list[float] = []
        for _ in range(_RUNS):
            analyzed = c.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + query, args).fetchone()
            assert analyzed is not None
            doc: Any = analyzed[0]
            server_ms.append(float(doc[0]["Execution Time"]))
    p99 = statistics.quantiles(server_ms, n=100)[98]
    assert p99 < 5.0, f"server-side p99 {p99:.3f} ms"
