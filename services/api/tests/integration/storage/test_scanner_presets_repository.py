"""Integration: `SqlAlchemyScannerPresetRepository` on real Postgres 16 (E08-T09 PR 2a, #4708;
migration 0054).

Owner scoping, the hard delete, `ux_sp_name` -> `name_taken` by Postgres's own `lower()`, one
default per user cleared in the write's transaction with its `version` raised, the expected
default, the race-safe 100 cap under the owner lock, and the Gherkin round trip through
`ScannerPresetService` (the create audited ahead, a Manager's request for the preset 404).
testcontainers; CI's `integration` job.
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

from candleviewer.api.scanner_presets_models import ScannerPresetInput
from candleviewer.api.scanner_presets_service import ScannerPresetService
from candleviewer.audit.access import AuditPrincipal
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.scanner_presets import (
    MAX_PRESETS,
    ExpectedDefault,
    ScannerPresetConflictError,
    ScannerPresetFields,
    ScannerPresetNotFoundError,
    ScannerPresetShapeError,
)
from candleviewer.storage.repositories.scanner_presets_sqlalchemy import (
    SqlAlchemyScannerPresetRepository,
)
from tests.scanner_presets._scanner_env import Audit, body

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]


def _alembic(dsn: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#4708)
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


def _user(dsn: str) -> str:
    uid = str(uuid.uuid4())
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        c.execute(
            "INSERT INTO users (id, email, username, password_hash) "
            "VALUES (%s, %s, %s, '$argon2id$x')",
            (uid, f"{uid[:8]}@x.io", f"u{uid[:8]}"),
        )
    return uid


def _f(name: str = "Fast", *, default: bool = False, **flt: object) -> ScannerPresetFields:
    return ScannerPresetFields(name, dict(flt) or {"spread_bps": {"max": "2"}}, "spread_bps",
                               default)  # fmt: skip


def _id() -> str:
    return str(uuid.uuid4())


@pytest_asyncio.fixture
async def repo(pg_dsn: str) -> AsyncIterator[SqlAlchemyScannerPresetRepository]:
    rel = SqlAlchemyRelationalRepository(pg_dsn, "scanner-presets-it")
    try:
        yield SqlAlchemyScannerPresetRepository(rel)
    finally:
        await rel.dispose()


async def test_rows_are_owner_scoped_and_listed_by_case_insensitive_name(
    repo: SqlAlchemyScannerPresetRepository, pg_dsn: str
) -> None:
    a, b = _user(pg_dsn), _user(pg_dsn)
    for name in ("beta", "Alpha"):
        await repo.create(a, _id(), _f(name))
    theirs = (await repo.create(b, _id(), _f("aardvark"))).row
    assert [r.name for r in await repo.list_own(a)] == ["Alpha", "beta"]
    assert await repo.get_own(a, theirs.id) is None
    assert await repo.is_foreign(a, theirs.id) and not await repo.is_foreign(b, theirs.id)
    assert not await repo.is_foreign(a, _id())
    with pytest.raises(ScannerPresetNotFoundError):
        await repo.update(a, theirs.id, _f("stolen"))
    assert not await repo.delete(a, theirs.id)
    assert (await repo.get_own(b, theirs.id)) == theirs


async def test_create_stores_the_filter_as_written_with_version_1(
    repo: SqlAlchemyScannerPresetRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    flt = {"regime": {"classes": ["calm"]}, "funding_rate": {"min": "-0.0001", "max": "0.0005"}}
    row = (await repo.create(a, _id(), _f("Filter", **flt))).row
    assert (row.filter, row.version, row.created_at) == (flt, 1, row.updated_at)
    again = (await repo.update(a, row.id, _f("Filter2"))).row
    assert again.version == 2 and again.updated_at > row.updated_at


async def test_names_collide_by_postgres_lower_and_map_to_name_taken(
    repo: SqlAlchemyScannerPresetRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    await repo.create(a, _id(), _f("Momentum"))
    assert await repo.occupancy(a, "MOMENTUM") == (1, True)
    with pytest.raises(ScannerPresetConflictError) as err:
        await repo.create(a, _id(), _f("MOMENTUM"))
    assert err.value.rule == "name_taken"


async def test_setting_a_default_clears_the_previous_one_in_the_same_write(
    repo: SqlAlchemyScannerPresetRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    first = (await repo.create(a, _id(), _f("First", default=True))).row
    expected = ExpectedDefault(first.id, first.version)
    second = await repo.create(a, _id(), _f("Second", default=True), expected_default=expected)
    assert second.cleared is not None and second.cleared.id == first.id
    assert (second.cleared.is_default, second.cleared.version) == (False, 2)
    assert (await repo.get_default(a)) == second.row
    with pytest.raises(ScannerPresetConflictError) as err:  # the caller expected another default
        await repo.update(a, first.id, _f("First", default=True), expected_default=None)
    assert err.value.rule == "conflict"
    assert (await repo.get_default(a)) == second.row  # nothing changed
    stale = ExpectedDefault(second.row.id, second.row.version + 1)  # S-2 (round 1)
    with pytest.raises(ScannerPresetConflictError) as err:  # the default changed since its record
        await repo.update(a, first.id, _f("First", default=True), expected_default=stale)
    assert err.value.rule == "conflict"
    assert (await repo.get_default(a)) == second.row  # nothing changed


async def test_the_shape_check_backs_the_apis_size_check(
    repo: SqlAlchemyScannerPresetRepository, pg_dsn: str
) -> None:
    with pytest.raises(ScannerPresetShapeError):
        await repo.create(_user(pg_dsn), _id(), _f("big", k={"v": "x" * 5000}))


async def test_the_cap_holds_under_concurrent_creates(
    repo: SqlAlchemyScannerPresetRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    for i in range(MAX_PRESETS - 2):
        await repo.create(a, _id(), _f(f"p{i}"))
    results = await asyncio.gather(
        *(repo.create(a, _id(), _f(f"race{i}")) for i in range(5)), return_exceptions=True
    )
    refused = [r for r in results if isinstance(r, ScannerPresetConflictError)]
    assert len(refused) == 3 and all(r.rule == "limit_reached" for r in refused)
    assert (await repo.occupancy(a))[0] == MAX_PRESETS


async def test_the_gherkin_round_trip_through_the_service(
    repo: SqlAlchemyScannerPresetRepository, pg_dsn: str
) -> None:
    """Presets are private and store criteria only; the create is audited ahead."""
    owner, manager = _user(pg_dsn), _user(pg_dsn)
    audit = Audit()
    service = ScannerPresetService(lambda: repo, audit, new_id=uuid.uuid4)
    as_owner = AuditPrincipal(uuid.UUID(owner), "o", frozenset(), session_id=uuid.uuid4())
    as_manager = AuditPrincipal(uuid.UUID(manager), "m", frozenset(), session_id=uuid.uuid4())
    made = await service.create(as_owner, ScannerPresetInput.model_validate(body()))
    assert audit.actions() == ["scanner_preset.created"]
    (listed,) = await service.list_own(owner)
    assert (listed.name, listed.filter) == ("Momentum", body()["filter"])
    with pytest.raises(ScannerPresetNotFoundError):
        await service.delete(as_manager, made.id)
    assert audit.actions()[-1] == "rbac.denied" and await repo.get_own(owner, made.id) == made
    await service.delete(as_owner, made.id)
    assert await service.list_own(owner) == []
