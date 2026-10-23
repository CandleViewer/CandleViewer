"""Idempotent seeds for the admin area's fixtures (E42-Q01, #962).

`seed_admin_world` writes the handles of `handles.py` into a migrated test database: rows with
`INSERT ... ON CONFLICT`, keyed on each row's primary key (its derived id, the pair of ids of a role
or a grant, a flag's key), so a second run changes nothing. `check_admin_world` then asserts what
the plan's cases rely on. Both refuse a database whose name does not mark it as a test database, so
no fixture lands in a real one.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from candleviewer.db import models as m
from tests.fixtures.admin.handles import (
    ACCOUNTS,
    BACKUPS,
    FLAGS,
    GRANTS,
    KEY_RESTRICTION,
    LOCK_PERIOD,
    OWNER,
    PLACEHOLDER_HASH,
    USERS,
    account,
    fixture_id,
    user,
)

#: How long INVITED-I's invite stays open after the seed's `now`.
_INVITE_OPEN: Final = timedelta(days=7)
#: A fixture backup's size and how long its run, and then its verification, took.
_BACKUP_BYTES: Final = 1_073_741_824
_BACKUP_RUN: Final = timedelta(minutes=10)


class FixtureRefused(RuntimeError):
    """The target is not a test database: nothing was written."""


class FixtureCheckError(AssertionError):
    """The seeded rows do not hold what the plan's cases rely on."""


def is_test_database(name: str) -> bool:
    """`test` (the test container's) or a name ending `_test`."""
    return name == "test" or name.endswith("_test")


def _require_aware(now: datetime) -> None:
    if now.utcoffset() is None:
        raise ValueError("`now` must be timezone-aware: the clock the app under test reads, in UTC")


async def refuse_unless_test_database(conn: AsyncConnection) -> None:
    name = str((await conn.execute(sa.text("SELECT current_database()"))).scalar_one())
    if not is_test_database(name):
        raise FixtureRefused(f"refusing database {name!r}: not a test database")


async def seed_admin_world(
    conn: AsyncConnection, *, now: datetime, password_hash: str = PLACEHOLDER_HASH
) -> None:
    """Every handle's rows, as of `now`; a second run keeps the rows the first wrote."""
    _require_aware(now)
    await refuse_unless_test_database(conn)
    named = await conn.execute(sa.select(m.roles.c.name, m.roles.c.id))
    roles = {name: role_id for name, role_id in named.all()}
    for u in USERS:
        locked = now + LOCK_PERIOD if u.status == "locked" else None
        inviter = OWNER.id if u.status == "invited" else None  # as the invite flow records it
        row = {"id": u.id, "email": u.email, "username": u.username, "invited_by": inviter}
        await conn.execute(
            pg_insert(m.users)
            .values(**row, password_hash=password_hash, status=u.status, locked_until=locked)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await conn.execute(
            pg_insert(m.user_roles)
            .values(user_id=u.id, role_id=roles[u.role], granted_by=inviter)
            .on_conflict_do_nothing(index_elements=["user_id", "role_id"])
        )
    invited = user("INVITED-I")
    await conn.execute(
        pg_insert(m.user_invites)
        .values(
            id=fixture_id("INVITE-I"),
            user_id=invited.id,
            role=invited.role,
            # Drawn per run and never kept: nobody holds a token that redeems this invite.
            token_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
            invited_by=OWNER.id,
            expires_at=now + _INVITE_OPEN,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    main = account("MAIN")
    for a in ACCOUNTS:
        await conn.execute(
            pg_insert(m.exchange_accounts)
            .values(
                id=a.id,
                exchange=m.exchange_code.enums[0],  # the schema's one exchange
                env="demo",  # C-2.11: fixtures never touch live
                kind="main" if a.is_main else "sub",
                exchange_uid=a.exchange_uid,
                parent_account_id=None if a.is_main else main.id,
                label=a.label,
                created_by=OWNER.id,
                created_at=now - a.age,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
    for handle, granted in GRANTS.items():
        for sub in granted:
            await conn.execute(
                pg_insert(m.user_account_access)
                .values(
                    user_id=user(handle).id,
                    exchange_account_id=account(sub).id,
                    can_trade=True,
                    can_view=True,
                    frozen=False,
                    granted_by=OWNER.id,
                )
                .on_conflict_do_nothing(index_elements=["user_id", "exchange_account_id"])
            )
    flags = m.feature_flags
    for key, value in FLAGS.items():
        stmt = pg_insert(flags).values(
            id=fixture_id(f"flag:{key}"), key=key, kind="boolean", default_value=value
        )
        await conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["key"],
                set_={"default_value": stmt.excluded.default_value},
                where=flags.c.default_value.is_distinct_from(stmt.excluded.default_value),
            )
        )


async def _read(
    conn: AsyncConnection, table: sa.Table, key: str, ids: Sequence[Any], *names: str
) -> Sequence[RowMapping]:
    """`names` of each row of `table` whose `key` column is one of `ids`."""
    read = sa.select(*(table.c[n] for n in names)).where(table.c[key].in_(ids))
    return (await conn.execute(read)).mappings().all()


async def check_admin_world(conn: AsyncConnection, *, now: datetime) -> None:
    """Raise `FixtureCheckError` naming every post-condition the seeded rows break."""
    _require_aware(now)
    await refuse_unless_test_database(conn)
    failed: list[str] = []
    ids = [u.id for u in USERS]
    named = await conn.execute(sa.select(m.roles.c.id, m.roles.c.name))
    role_name = {role_id: name for role_id, name in named.all()}
    found = await _read(conn, m.users, "id", ids, "id", "status", "locked_until")
    users = {r["id"]: (r["status"], r["locked_until"]) for r in found}
    held: dict[uuid.UUID, set[str]] = {u.id: set() for u in USERS}
    for r in await _read(conn, m.user_roles, "user_id", ids, "user_id", "role_id"):
        held[r["user_id"]].add(role_name[r["role_id"]])
    for u in USERS:
        status, until = users.get(u.id, (None, None))
        if status != u.status:
            failed.append(f"{u.handle}: status is {status}, not {u.status}")
        if held[u.id] != {u.role}:
            failed.append(f"{u.handle}: roles are {sorted(held[u.id])}, not {u.role}")
        if u.status == "locked" and (until is None or until <= now):
            failed.append(f"{u.handle}: locked_until {until} is not after now")
    invited = user("INVITED-I")
    cols = ("role", "token_hash", "consumed_at", "revoked_at", "expires_at")
    invites = await _read(conn, m.user_invites, "user_id", [invited.id], *cols)
    pending = [
        i for i in invites if not (i["consumed_at"] or i["revoked_at"]) and i["expires_at"] > now
    ]
    if len(pending) != 1:
        failed.append(f"{invited.handle}: {len(pending)} open invites, not 1")
    for i in pending:
        if i["role"] != invited.role:
            failed.append(f"{invited.handle}: invite role is {i['role']}, not {invited.role}")
        if not re.fullmatch(r"[0-9a-f]{64}", i["token_hash"]):
            failed.append(f"{invited.handle}: token_hash is not a sha256")
    cols = ("user_id", "exchange_account_id", "can_trade", "can_view", "frozen")
    grants = await _read(conn, m.user_account_access, "user_id", ids, *cols)
    for handle, granted in GRANTS.items():
        mine = [g for g in grants if g["user_id"] == user(handle).id]
        if {g["exchange_account_id"] for g in mine} != {account(s).id for s in granted}:
            failed.append(f"{handle}: grants are not {', '.join(granted) or 'none'}")
        if not all(g["can_trade"] and g["can_view"] and not g["frozen"] for g in mine):
            failed.append(f"{handle}: a grant is frozen, or not viewable or not tradable")
    found = await _read(
        conn, m.exchange_accounts, "id", [a.id for a in ACCOUNTS], "id", "env", "created_at"
    )
    accounts = {r["id"]: (r["env"], r["created_at"]) for r in found}
    for a in ACCOUNTS:
        env, created = accounts.get(a.id, (None, None))
        if env != "demo":
            failed.append(f"{a.handle}: env is {env}, not demo")
        restricted = created is not None and now - created < KEY_RESTRICTION
        if restricted != (a.handle == "SUB-K"):
            failed.append(f"{a.handle}: inside the key restriction is {restricted}")
    found = await _read(conn, m.feature_flags, "key", list(FLAGS), "key", "default_value")
    stored = {r["key"]: r["default_value"] for r in found}
    failed += [
        f"{k}: is {stored.get(k)!r}, not {v!r}" for k, v in FLAGS.items() if stored.get(k) is not v
    ]
    if failed:
        raise FixtureCheckError("; ".join(failed))


async def seed_backups(conn: AsyncConnection, *, now: datetime) -> None:
    """BACKUP-VERIFY-FAILED as of `now`; a second run with the same `now` changes nothing."""
    await refuse_unless_test_database(conn)
    for b in BACKUPS:
        started = now - b.age
        verified = b.status == "verified"
        await conn.execute(
            pg_insert(m.backups)
            .values(
                id=b.id,
                kind="pg_basebackup",
                status=b.status,
                target_path=b.target_path,
                size_bytes=_BACKUP_BYTES,
                started_at=started,
                finished_at=started + _BACKUP_RUN,
                verified_at=started + 2 * _BACKUP_RUN if verified else None,
                verify_method="checksum" if verified else None,
                error_message=b.error,
                triggered_by="schedule",
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )


async def check_backups(conn: AsyncConnection) -> None:
    """Raise `FixtureCheckError` unless each backup holds its status and its failure code."""
    await refuse_unless_test_database(conn)
    rows = await conn.execute(
        sa.select(m.backups.c.id, m.backups.c.status, m.backups.c.error_message).where(
            m.backups.c.id.in_([b.id for b in BACKUPS])
        )
    )
    seen = {(i, str(status), error) for i, status, error in rows.tuples()}
    failed = [
        f"{b.handle}: not {b.status}" for b in BACKUPS if (b.id, b.status, b.error) not in seen
    ]
    if failed:
        raise FixtureCheckError("; ".join(failed))
