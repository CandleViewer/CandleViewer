"""Integration: `SqlAlchemyIndicatorPresetRepository` on real Postgres 16 (E13-T03, #427;
migration 0040).

Owner scoping (the list is the caller's rows and the built-ins; writes never reach a built-in or
another user's row), the soft delete, `ux_ip_name` -> `name_taken`, the race-safe 500 cap and the
atomic bundle import. CI only (testcontainers; no docker socket locally).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from candleviewer.db.builtin_indicator_presets import BUILTIN_PRESETS
from candleviewer.storage.repositories.indicator_presets import (
    MAX_LIVE_PRESETS,
    PresetConflictError,
    PresetFields,
    PresetNotFoundError,
    PresetShapeError,
)
from candleviewer.storage.repositories.indicator_presets_sqlalchemy import (
    SqlAlchemyIndicatorPresetRepository,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_BUILTIN = BUILTIN_PRESETS[0]  # ema(9)


def _alembic(dsn: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#427)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        check=True,
        timeout=120,
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


def _f(name: str = "Fast", code: str = "ema", **params: object) -> PresetFields:
    return PresetFields(code, name, dict(params) or {"n": 9}, {}, "overlay", False)


@pytest_asyncio.fixture
async def repo(pg_dsn: str) -> AsyncIterator[SqlAlchemyIndicatorPresetRepository]:
    rel = SqlAlchemyRelationalRepository(pg_dsn, "indicator-presets-it")
    try:
        yield SqlAlchemyIndicatorPresetRepository(rel)
    finally:
        await rel.dispose()


async def test_list_is_owner_or_builtin_only_builtins_first(
    repo: SqlAlchemyIndicatorPresetRepository, pg_dsn: str
) -> None:
    a, b = _user(pg_dsn), _user(pg_dsn)
    mine = await repo.create(a, str(uuid.uuid4()), _f("Mine"))
    await repo.create(b, str(uuid.uuid4()), _f("Theirs"))
    rows = await repo.list_visible(a)
    assert [r.id for r in rows if not r.is_builtin] == [mine.id]
    assert {r.id for r in rows if r.is_builtin} == {p.id for p in BUILTIN_PRESETS}
    assert all(r.owner_user_id in (None, a) for r in rows)
    assert rows[: len(BUILTIN_PRESETS)] == [r for r in rows if r.is_builtin]  # built-ins first


async def test_update_and_soft_delete_never_touch_a_builtin(
    repo: SqlAlchemyIndicatorPresetRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    before = [r for r in await repo.list_visible(a) if r.id == _BUILTIN.id]
    assert await repo.get_own(a, _BUILTIN.id) is None
    with pytest.raises(PresetNotFoundError):
        await repo.update(a, _BUILTIN.id, _f("hijack"))
    assert await repo.soft_delete(a, _BUILTIN.id) is False
    assert await repo.other_class(a, _BUILTIN.id) == "builtin"
    assert [r for r in await repo.list_visible(a) if r.id == _BUILTIN.id] == before


async def test_another_owner_cannot_read_update_or_delete(
    repo: SqlAlchemyIndicatorPresetRepository, pg_dsn: str
) -> None:
    a, b = _user(pg_dsn), _user(pg_dsn)
    made = await repo.create(a, str(uuid.uuid4()), _f())
    assert await repo.get_own(b, made.id) is None
    with pytest.raises(PresetNotFoundError):
        await repo.update(b, made.id, _f("hijack"))
    assert await repo.soft_delete(b, made.id) is False
    assert (await repo.other_class(b, made.id), await repo.other_class(a, made.id)) == (
        "foreign",
        None,
    )
    assert await repo.get_own(a, made.id) == made


async def test_unique_violation_maps_to_name_taken_and_keeps_the_first(
    repo: SqlAlchemyIndicatorPresetRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    first = await repo.create(a, str(uuid.uuid4()), _f("Fast"))
    assert (await repo.occupancy(a, ("ema", "FAST"))).name_taken
    with pytest.raises(PresetConflictError) as err:
        await repo.create(a, str(uuid.uuid4()), _f("fast"))
    assert (err.value.rule, err.value.field) == ("name_taken", "name")
    other = await repo.create(a, str(uuid.uuid4()), _f("Other"))
    with pytest.raises(PresetConflictError):
        await repo.update(a, other.id, _f("FAST"))
    assert await repo.get_own(a, first.id) == first


async def test_delete_sets_deleted_at_keeps_row_hides_from_list(
    repo: SqlAlchemyIndicatorPresetRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    made = await repo.create(a, str(uuid.uuid4()), _f("Gone"))
    assert await repo.soft_delete(a, made.id) is True
    assert await repo.soft_delete(a, made.id) is False  # a second delete finds nothing live
    assert made.id not in {r.id for r in await repo.list_visible(a)}
    with _sync(pg_dsn) as c:
        row = c.execute(
            "SELECT deleted_at IS NOT NULL FROM indicator_presets WHERE id = %s", (made.id,)
        ).fetchone()
    assert row == (True,)
    await repo.create(a, str(uuid.uuid4()), _f("gone"))  # the name is free again


async def test_clearing_deleted_at_restores_visibility(
    repo: SqlAlchemyIndicatorPresetRepository, pg_dsn: str
) -> None:
    """A5: reversible at the data layer (an operator clears `deleted_at`)."""
    a = _user(pg_dsn)
    made = await repo.create(a, str(uuid.uuid4()), _f("Back"))
    await repo.soft_delete(a, made.id)
    with _sync(pg_dsn) as c:
        c.execute("UPDATE indicator_presets SET deleted_at = NULL WHERE id = %s", (made.id,))
    assert made.id in {r.id for r in await repo.list_visible(a)}


async def test_updated_at_moves_strictly_forward_and_the_code_never_changes(
    repo: SqlAlchemyIndicatorPresetRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    made = await repo.create(a, str(uuid.uuid4()), _f("Tick"))
    assert made.created_at == made.updated_at
    first = await repo.update(a, made.id, _f("Tock", code="sma", n=20))
    second = await repo.update(a, made.id, _f("Tock", code="sma", n=20))
    assert made.updated_at < first.updated_at < second.updated_at
    assert first.indicator_code == "ema" and first.params == {"n": 20}


async def test_500_cap_is_race_safe(repo: SqlAlchemyIndicatorPresetRepository, pg_dsn: str) -> None:
    """SR-E13-07: two concurrent creates at 499 live presets: the advisory lock admits one."""
    a = _user(pg_dsn)
    with _sync(pg_dsn) as c:
        c.execute(
            "INSERT INTO indicator_presets (id, owner_user_id, indicator_code, name, params) "
            "SELECT gen_random_uuid(), %s, 'ema', 'p' || g, '{\"n\": 9}' "
            "FROM generate_series(1, %s) g",
            (a, MAX_LIVE_PRESETS - 1),
        )
    results = await asyncio.gather(
        repo.create(a, str(uuid.uuid4()), _f("race 1")),
        repo.create(a, str(uuid.uuid4()), _f("race 2")),
        return_exceptions=True,
    )
    refused = [r for r in results if isinstance(r, PresetConflictError)]
    assert len(refused) == 1 and refused[0].rule == "limit_reached"
    assert (await repo.occupancy(a)).live_presets == MAX_LIVE_PRESETS


async def test_bundle_roundtrip_on_postgres_renames_collisions_and_is_atomic(
    repo: SqlAlchemyIndicatorPresetRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    await repo.create(a, str(uuid.uuid4()), _f("Fast"))
    rows = await repo.import_many(
        a, [(str(uuid.uuid4()), _f("Fast")), (str(uuid.uuid4()), _f("FAST"))]
    )
    assert [r.name for r in rows] == ["Fast (2)", "FAST (3)"]
    assert all(r.owner_user_id == a and not r.is_builtin for r in rows)
    before = await repo.list_visible(a)
    oversize = PresetFields("ema", "big", {"k": "v" * 5000}, {}, "overlay", False)
    with pytest.raises(PresetShapeError):  # the DB CHECK, past the API's own size check
        await repo.import_many(a, [(str(uuid.uuid4()), _f("ok")), (str(uuid.uuid4()), oversize)])
    assert await repo.list_visible(a) == before  # nothing of the refused import landed


async def test_counts_by_builtin_cover_every_owner(
    repo: SqlAlchemyIndicatorPresetRepository, pg_dsn: str
) -> None:
    before = await repo.count_live_by_builtin()
    a = _user(pg_dsn)
    await repo.create(a, str(uuid.uuid4()), _f("Counted"))
    after = await repo.count_live_by_builtin()
    assert after[True] == len(BUILTIN_PRESETS)
    assert after[False] == before.get(False, 0) + 1
