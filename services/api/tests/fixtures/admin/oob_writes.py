"""OOB-WRITES (E42-Q01, #962): AC-ADM-31's writes, made as the app's database role outside the API.

`cv_app` can UPDATE the identity, flag and backup tables, so a writer holding it can change what the
API changes only with a record written ahead (C-2.9). The seed makes four such writes, none with an
audit record, for the change capture of SR-E42-06 (#3196) to catch: an Owner role row for MGR-M, a
second grant for MGR-M (SUB-T beside SUB-S), `trading.live_enabled` set, and a backup's digest set.
The digest is set, not rewritten: `0032_backups_write_once` refuses a change to one already set, for
every role, so OOB-BACKUP, the seed's own row, has none. It shares no database with `seed_backups`.

Each write runs after `SET ROLE cv_app`, reset after the last. They leave a standing privilege and a
set live gate, so the seed refuses, before it reads a row, a database not named for tests and a
session not logged in as the test container's own user. It builds on slice A's world, which
`check_admin_world` no longer passes afterwards: it names the widened grant and the extra role.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from candleviewer.admin.flags.registry import LIVE_ENABLED
from candleviewer.db import models as m
from tests.fixtures.admin.handles import BACKUPS, account, fixture_id, user
from tests.fixtures.admin.seed import (
    FixtureCheckError,
    FixtureRefused,
    refuse_unless_test_database,
)
from tests.fixtures.admin.world import require_world

#: The only login that runs the seed: the user of the test container (`testcontainers`' Postgres).
TEST_LOGIN: Final = "test"
#: The account MGR-M's grant is widened to; SUB-S is the grant it holds.
WIDENED_TO: Final = "SUB-T"
#: OOB-BACKUP: a finished backup an hour old with no digest, and the digest the write sets: that of
#: the handle's name, as for the other fixture backups; no artefact exists behind the row.
BACKUP_ID: Final = fixture_id("OOB-BACKUP")
BACKUP_PATH: Final = "/fixture/backups/oob-backup"
BACKUP_DIGEST: Final = hashlib.sha256(b"fixture:OOB-BACKUP").hexdigest()
_BACKUP_AGE: Final = timedelta(hours=1)


async def seed_oob_writes(conn: AsyncConnection, *, now: datetime) -> None:
    """OOB-BACKUP's row, then the four writes as `cv_app`; a second run writes nothing. Run it in a
    transaction: a failed write rolls the role switch back with the rest."""
    if now.utcoffset() is None:
        raise ValueError("`now` must be timezone-aware: the clock the app under test reads, in UTC")
    await refuse_unless_test_database(conn)
    login = str((await conn.execute(sa.text("SELECT session_user"))).scalar_one())
    if login != TEST_LOGIN:
        raise FixtureRefused(f"refusing login {login!r}: not the test container's user")
    await require_world(
        conn, users=("MGR-M",), accounts=("SUB-S", WIDENED_TO), flags=(LIVE_ENABLED,)
    )
    held = {row["id"] for row in await _rows(conn, m.backups, "id")}
    if clash := [b.handle for b in BACKUPS if b.id in held]:
        raise FixtureCheckError(
            f"OOB-BACKUP shares no database with seed_backups: {', '.join(clash)}"
        )
    named = await conn.execute(sa.select(m.roles.c.name, m.roles.c.id))
    role_ids = {name: role_id for name, role_id in named.all()}
    started = now - _BACKUP_AGE
    await conn.execute(
        pg_insert(m.backups)
        .values(
            id=BACKUP_ID,
            kind="pg_dump",
            status="ok",
            target_path=BACKUP_PATH,
            started_at=started,
            finished_at=started + timedelta(minutes=10),
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    manager, flags = user("MGR-M"), m.feature_flags
    await conn.execute(sa.text("SET ROLE cv_app"))
    await conn.execute(
        pg_insert(m.user_roles)
        .values(user_id=manager.id, role_id=role_ids["owner"])
        .on_conflict_do_nothing(index_elements=["user_id", "role_id"])
    )
    await conn.execute(
        pg_insert(m.user_account_access)
        .values(
            user_id=manager.id,
            exchange_account_id=account(WIDENED_TO).id,
            can_trade=True,
            can_view=True,
            frozen=False,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "exchange_account_id"])
    )
    await conn.execute(
        sa.update(flags)
        .where(flags.c.key == LIVE_ENABLED)
        .where(flags.c.default_value.is_distinct_from(sa.literal(True, JSONB)))
        .values(default_value=True)
    )
    await conn.execute(
        sa.update(m.backups)
        .where(m.backups.c.id == BACKUP_ID)
        .where(sa.type_coerce(m.backups.c.checksum_sha256, sa.Text).is_(None))  # a DOMAIN column
        .values(checksum_sha256=BACKUP_DIGEST)
    )
    await conn.execute(sa.text("RESET ROLE"))


async def _rows(conn: AsyncConnection, table: sa.Table, *names: str) -> list[RowMapping]:
    """`names` of every row of `table`: a test database holds a handful."""
    read = sa.select(*(table.c[n] for n in names))
    return list((await conn.execute(read)).mappings().all())


async def check_oob_writes(conn: AsyncConnection) -> None:
    """Raise `FixtureCheckError` naming each of the four writes that is not in the rows."""
    await refuse_unless_test_database(conn)
    manager = user("MGR-M")
    failed: list[str] = []
    named = await conn.execute(sa.select(m.roles.c.id, m.roles.c.name))
    role_names = {role_id: name for role_id, name in named.all()}
    roles = {
        role_names[row["role_id"]]
        for row in await _rows(conn, m.user_roles, "user_id", "role_id")
        if row["user_id"] == manager.id
    }
    if "owner" not in roles:
        failed.append("MGR-M holds no Owner role row")
    access = await _rows(conn, m.user_account_access, "user_id", "exchange_account_id")
    granted = {row["exchange_account_id"] for row in access if row["user_id"] == manager.id}
    failed += [
        f"MGR-M holds no grant on {handle}"
        for handle in ("SUB-S", WIDENED_TO)
        if account(handle).id not in granted
    ]
    flags = {
        row["key"]: row["default_value"]
        for row in await _rows(conn, m.feature_flags, "key", "default_value")
    }
    if flags.get(LIVE_ENABLED) is not True:
        failed.append(f"{LIVE_ENABLED} is {flags.get(LIVE_ENABLED)!r}, not True")
    digests = {
        row["id"]: row["checksum_sha256"]
        for row in await _rows(conn, m.backups, "id", "checksum_sha256")
    }
    if BACKUP_ID not in digests:
        failed.append("OOB-BACKUP: no row")
    elif digests[BACKUP_ID] != BACKUP_DIGEST:
        failed.append(
            f"OOB-BACKUP: its digest is {digests[BACKUP_ID]!r}, not the one the write sets"
        )
    if failed:
        raise FixtureCheckError("; ".join(failed))
