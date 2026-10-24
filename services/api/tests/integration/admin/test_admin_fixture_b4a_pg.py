"""Integration (E42-Q01, #962): the seeds of slice B4a on a migrated Postgres 16:
FLAG-OVERRIDE-ROWS, OOB-WRITES and SC-FORGED-SEAL.

FLAG-OVERRIDE-ROWS passes its own check and leaves slice A's rows as it found them; a second run
changes no row (nor any row's version); a re-seed over a changed world puts its own rows back and
leaves a stored kill switch as it is; and the seed holds over the rows the app's own boot makes.
OOB-WRITES and SC-FORGED-SEAL each pass their own check on a second run, and each seed refuses a
database not named for tests. OOB-WRITES runs as the test container's user with a stand-in
`cv_app` role: `SELECT`, `INSERT` and `UPDATE` on every table, what the default privileges of
`infra/scripts/pg_bootstrap.sql` give the app's role less the `DELETE` no seed uses; a test shows
the writes are made with its privileges. Needs Docker (testcontainers); CI `integration` runs it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from functools import partial
from typing import Any

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy import exc as sa_exc
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from candleviewer.admin.flags.catalogue import FLAGS as CATALOGUE
from candleviewer.admin.flags.registry import LIVE_ENABLED, MAINTENANCE_MODE
from candleviewer.admin.flags.resolver import resolve
from candleviewer.db import models as m
from candleviewer.flags_wiring import stored_flag
from candleviewer.statechart_wiring import SnapshotAdapter
from candleviewer.storage.repositories.flags_sqlalchemy import FlagSeed, SqlAlchemyFlagRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.statechart_sqlalchemy import SqlAlchemySnapshotStore
from tests.fixtures.admin.flag_overrides import (
    SAFETY,
    UNREADABLE,
    UNREADABLE_VALUE,
    check_flag_overrides,
    seed_flag_overrides,
)
from tests.fixtures.admin.forged_seal import check_forged_seal, seed_forged_seal
from tests.fixtures.admin.handles import FLAGS, fixture_id, user
from tests.fixtures.admin.latched_machine import ENTITY_ID, KIND
from tests.fixtures.admin.oob_writes import BACKUP_ID, check_oob_writes, seed_oob_writes
from tests.fixtures.admin.seed import (
    FixtureCheckError,
    FixtureRefused,
    check_admin_world,
    connect_test_database,
    seed_admin_world,
)
from tests.integration import _refused

pytestmark = pytest.mark.integration

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16, migrated; database and login `test`
_NOW = datetime(2026, 10, 23, 19, 0, tzinfo=UTC)
_XMIN = sa.cast(sa.column("xmin"), sa.Text).label("xmin")  # a rewrite, even of an equal row, shows
_F, _O = m.feature_flags, m.feature_flag_overrides
#: The rows this seed writes: the flags it concerns, and every override.
_SEEDED = ((_F, _F.c.key.in_([LIVE_ENABLED, MAINTENANCE_MODE, UNREADABLE])), (_O, sa.true()))
#: Slice A's flag rows, the live gate's among them: the seed reads them and never writes them.
_WORLD = ((_F, _F.c.key.in_(list(FLAGS))),)
_MGR_M = user("MGR-M").id


class _Keys:
    """`HmacKeys` with one test key, never a real one."""

    def current(self) -> str:
        return "k1"

    def key(self, key_id: str) -> bytes:
        return {"k1": b"\x01" * 32}[key_id]


def _admin(dsn: str) -> psycopg.Connection[Any]:
    """The container's superuser, on its database named for tests: it makes roles and databases."""
    return connect_test_database(dsn.replace("postgresql+asyncpg", "postgresql"))


@pytest.fixture(scope="module")
def cv_app(pg_dsn: str) -> None:
    with _admin(pg_dsn) as c:
        c.execute("CREATE ROLE cv_app NOLOGIN")
        c.execute("GRANT USAGE ON SCHEMA public TO cv_app")
        c.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO cv_app")


@pytest.fixture(scope="module")
def other_dsn(pg_dsn: str) -> str:
    """An empty database not named for tests: a refused seed finds nothing to read there."""
    with _admin(pg_dsn) as c:  # named for no app either: the refusal needs only "not for tests"
        c.execute("DROP DATABASE IF EXISTS cv_refusal_probe")
        c.execute("CREATE DATABASE cv_refusal_probe")
    return pg_dsn.rsplit("/", 1)[0] + "/cv_refusal_probe"


@pytest.fixture
async def engine(pg_dsn: str) -> AsyncIterator[AsyncEngine]:
    created = create_async_engine(pg_dsn)
    try:
        async with created.begin() as conn:
            await seed_admin_world(conn, now=_NOW)  # slice A's world, which each seed builds on
            await conn.execute(sa.delete(_O))  # and nothing more, whatever an earlier case left
            await conn.execute(sa.delete(_F).where(_F.c.key.not_in(list(FLAGS))))
        yield created
    finally:
        await created.dispose()


@pytest.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(pg_dsn, "fixture")
    try:
        yield repo
    finally:
        await repo.dispose()


async def _rows(engine: AsyncEngine, *reads: tuple[sa.Table, Any]) -> list[list[tuple[Any, ...]]]:
    """Each table's rows that its condition selects, with their `xmin`; never `encryption_ref`."""
    async with engine.connect() as conn:
        found: list[list[tuple[Any, ...]]] = []
        for table, where in reads:
            columns = [c for c in table.c if c.name != "encryption_ref"]
            rows = (await conn.execute(sa.select(*columns, _XMIN).where(where))).all()
            found.append(sorted((tuple(r) for r in rows), key=str))
        return found


async def _is_refused_elsewhere(other_dsn: str, seed: Callable[..., Awaitable[None]]) -> None:
    """`seed` on a connection to the database not named for tests: refused, before a row is read."""
    other = create_async_engine(other_dsn)
    try:
        async with other.begin() as conn:
            with pytest.raises(FixtureRefused):
                await seed(conn)
    finally:
        await other.dispose()


async def test_the_flag_override_rows_pass_their_check_and_leave_slice_a_untouched(
    engine: AsyncEngine,
) -> None:
    world = await _rows(engine, *_WORLD)
    async with engine.begin() as conn:
        await seed_flag_overrides(conn)
    async with engine.connect() as conn:
        await check_flag_overrides(conn)
        await check_admin_world(conn, now=_NOW)
    assert await _rows(engine, *_WORLD) == world  # every column, and each row's version


async def test_a_second_flag_seed_changes_no_row(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await seed_flag_overrides(conn)
    before = await _rows(engine, *_SEEDED)
    async with engine.begin() as conn:
        await seed_flag_overrides(conn)
    assert await _rows(engine, *_SEEDED) == before


async def test_a_reseed_puts_its_rows_back_and_leaves_an_engaged_kill_switch(
    engine: AsyncEngine,
) -> None:
    """A database writer engages `maintenance.mode`, makes the unreadable row readable and drops
    MGR-M's override on the kill switch. A second seed puts back the rows it owns and leaves the
    stored value it does not, which its check then names."""
    lost = fixture_id(f"override:{MAINTENANCE_MODE}:MGR-M")
    async with engine.begin() as conn:
        await seed_flag_overrides(conn)
        await conn.execute(
            sa.update(_F).where(_F.c.key == MAINTENANCE_MODE).values(default_value=True)
        )
        await conn.execute(sa.update(_F).where(_F.c.key == UNREADABLE).values(default_value=False))
        await conn.execute(sa.delete(_O).where(_O.c.id == lost))
    async with engine.begin() as conn:
        await seed_flag_overrides(conn)
    with pytest.raises(FixtureCheckError) as raised:
        async with engine.connect() as conn:
            await check_flag_overrides(conn)
    named = [f"{MAINTENANCE_MODE} for {who} resolves True, not False" for who in ("MGR-M", "OWNER")]
    assert str(raised.value) == "; ".join(
        [*named, f"{MAINTENANCE_MODE}: is stored True, not False"]
    )


async def test_the_seed_holds_over_the_rows_the_apps_boot_makes(
    engine: AsyncEngine, rel: SqlAlchemyRelationalRepository
) -> None:
    """The app boots first: `ensure` makes each catalogued flag a row with an id of its own. The
    seed writes on those rows, and the app's own load resolves each caller as the check does."""
    flags = SqlAlchemyFlagRepository(rel, read_budget_ms=2000)
    await flags.ensure(
        FlagSeed(s.key, s.kind.value, s.description, s.default, s.is_killswitch, s.variants)
        for s in CATALOGUE
    )
    async with engine.begin() as conn:
        booted: dict[str, Any] = dict((await conn.execute(sa.select(_F.c.key, _F.c.id))).all())
        await seed_flag_overrides(conn)
    async with engine.connect() as conn:
        await check_flag_overrides(conn)
    assert [k for k in (MAINTENANCE_MODE, UNREADABLE) if booted[k] == fixture_id(f"flag:{k}")] == []
    loaded = {key: stored_flag(row) for key, row in (await flags.load()).items()}
    specs = {spec.key: spec for spec in CATALOGUE}
    owner, manager = user("OWNER"), user("MGR-M")
    callers = ((manager.id, frozenset({"manager"})), (owner.id, frozenset({"owner"})))
    verdicts = [
        resolve(specs[k], loaded[k], user_id=u, roles=r) for k in SAFETY for u, r in callers
    ]
    twap = loaded[UNREADABLE]
    assert verdicts == [False] * 4
    assert twap.value == UNREADABLE_VALUE
    assert resolve(specs[UNREADABLE], twap, user_id=owner.id, roles=frozenset({"owner"})) is False


async def test_the_flag_seed_is_refused_on_a_database_not_named_for_tests(other_dsn: str) -> None:
    await _is_refused_elsewhere(other_dsn, seed_flag_overrides)


async def test_the_oob_writes_pass_their_check_and_a_second_seed_changes_none(
    engine: AsyncEngine, cv_app: None
) -> None:
    uaa, f, b = m.user_account_access, m.feature_flags, m.backups
    reads = (
        (m.user_roles, m.user_roles.c.user_id == _MGR_M),
        (uaa, uaa.c.user_id == _MGR_M),
        (f, f.c.key == LIVE_ENABLED),
        (b, b.c.id == BACKUP_ID),
    )
    async with engine.begin() as conn:
        await seed_oob_writes(conn, now=_NOW)
    async with engine.connect() as conn:
        await check_oob_writes(conn)
    before = await _rows(engine, *reads)
    async with engine.begin() as conn:
        await seed_oob_writes(conn, now=_NOW)
    assert await _rows(engine, *reads) == before


async def test_the_oob_writes_are_made_with_the_app_roles_privileges(
    pg_dsn: str, engine: AsyncEngine, cv_app: None
) -> None:
    with _admin(pg_dsn) as c:
        c.execute("REVOKE UPDATE ON feature_flags FROM cv_app")
    try:
        with pytest.raises(sa_exc.DBAPIError, match="permission denied"):
            async with engine.begin() as conn:
                await seed_oob_writes(conn, now=_NOW)
    finally:
        with _admin(pg_dsn) as c:
            c.execute("GRANT UPDATE ON feature_flags TO cv_app")


async def test_the_oob_seed_is_refused_on_a_database_not_named_for_tests(other_dsn: str) -> None:
    await _is_refused_elsewhere(other_dsn, partial(seed_oob_writes, now=_NOW))


async def test_the_forged_row_is_left_out_and_a_second_seed_keeps_one_row(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    first = await seed_forged_seal(rel, _Keys(), now=_NOW)
    await check_forged_seal(rel, _Keys(), now=_NOW)
    assert await seed_forged_seal(rel, _Keys(), now=_NOW) == first
    rows = await SnapshotAdapter(SqlAlchemySnapshotStore(rel)).snapshots()
    assert [(r.machine_kind, r.entity_id) for r in rows].count((KIND, ENTITY_ID)) == 1


async def test_the_forged_seed_is_refused_on_a_database_not_named_for_tests(other_dsn: str) -> None:
    other = SqlAlchemyRelationalRepository(other_dsn, "fixture")
    try:
        with pytest.raises(FixtureRefused):
            await seed_forged_seal(other, _Keys(), now=_NOW)
    finally:
        await other.dispose()
