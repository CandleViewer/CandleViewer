"""Idempotent seeds for the admin area's fixtures (E42-Q01, #962).

`seed_admin_world` writes the handles of `handles.py` into a migrated test database: rows with
`INSERT ... ON CONFLICT`, keyed on each row's derived id (a flag on its key), so a second run
changes nothing. `check_admin_world` then asserts what the plan's cases rely on. Both refuse a
database whose name does not mark it as a test database, so no fixture lands in a real one.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from candleviewer.db import models as m
from tests.fixtures.admin.handles import (
    ACCOUNTS,
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


class FixtureRefused(RuntimeError):
    """The target is not a test database: nothing was written."""


class FixtureCheckError(AssertionError):
    """The seeded rows do not hold what the plan's cases rely on."""


def is_test_database(name: str) -> bool:
    """`test` (the test container's) or a name ending `_test`."""
    return name == "test" or name.endswith("_test")


async def refuse_unless_test_database(conn: AsyncConnection) -> None:
    name = (await conn.execute(sa.text("SELECT current_database()"))).scalar_one()
    if not is_test_database(str(name)):
        raise FixtureRefused(f"refusing database {name!r}: not a test database")


async def seed_admin_world(
    conn: AsyncConnection, *, now: datetime, password_hash: str = PLACEHOLDER_HASH
) -> None:
    """Every handle's rows, as of `now`; a second run with the same `now` changes nothing."""
    await refuse_unless_test_database(conn)
    roles = dict((await conn.execute(sa.select(m.roles.c.name, m.roles.c.id))).tuples().all())
    for u in USERS:
        locked = now + LOCK_PERIOD if u.status == "locked" else None
        row = {"id": u.id, "email": u.email, "username": u.username}
        await conn.execute(
            pg_insert(m.users)
            .values(**row, password_hash=password_hash, status=u.status, locked_until=locked)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await conn.execute(
            pg_insert(m.user_roles)
            .values(user_id=u.id, role_id=roles[u.role])
            .on_conflict_do_nothing(index_elements=["user_id", "role_id"])
        )
    await conn.execute(
        pg_insert(m.user_invites)
        .values(
            id=fixture_id("INVITE-I"),
            user_id=user("INVITED-I").id,
            role="viewer",
            token_hash=hashlib.sha256(b"e42-admin fixture invite").hexdigest(),
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
                exchange="bybit",
                env="demo",
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


async def check_admin_world(conn: AsyncConnection, *, now: datetime) -> None:
    """Raise `FixtureCheckError` naming every post-condition the seeded rows break."""
    await refuse_unless_test_database(conn)
    failed: list[str] = []
    ids = [u.id for u in USERS]
    rows = await conn.execute(
        sa.select(m.users.c.id, m.users.c.status, m.roles.c.name)
        .join(m.user_roles, m.user_roles.c.user_id == m.users.c.id)
        .join(m.roles, m.roles.c.id == m.user_roles.c.role_id)
        .where(m.users.c.id.in_(ids))
    )
    seen = {(i, str(status), str(role)) for i, status, role in rows.tuples()}
    failed += [
        f"{u.handle}: not {u.status} {u.role}"
        for u in USERS
        if (u.id, u.status, u.role) not in seen
    ]
    invite = m.user_invites
    open_invites = await conn.scalar(
        sa.select(sa.func.count())
        .select_from(invite)
        .where(
            invite.c.user_id == user("INVITED-I").id,
            invite.c.consumed_at.is_(None),
            invite.c.revoked_at.is_(None),
            invite.c.expires_at > now,
        )
    )
    if open_invites != 1:
        failed.append(f"INVITED-I: {open_invites} open invites, not 1")
    access = m.user_account_access
    for handle, granted in GRANTS.items():
        found = await conn.execute(
            sa.select(access.c.exchange_account_id).where(
                access.c.user_id == user(handle).id, access.c.can_trade
            )
        )
        if set(found.scalars()) != {account(sub).id for sub in granted}:
            failed.append(f"{handle}: its trade grants are not {', '.join(granted) or 'none'}")
    created = dict(
        (
            await conn.execute(
                sa.select(m.exchange_accounts.c.id, m.exchange_accounts.c.created_at).where(
                    m.exchange_accounts.c.id.in_([a.id for a in ACCOUNTS])
                )
            )
        )
        .tuples()
        .all()
    )
    for a in ACCOUNTS:
        restricted = a.id in created and now - created[a.id] < KEY_RESTRICTION
        if restricted != (a.handle == "SUB-K"):
            failed.append(f"{a.handle}: inside the key restriction is {restricted}")
    stored = dict(
        (
            await conn.execute(
                sa.select(m.feature_flags.c.key, m.feature_flags.c.default_value).where(
                    m.feature_flags.c.key.in_(list(FLAGS))
                )
            )
        )
        .tuples()
        .all()
    )
    failed += [
        f"{key}: is {stored.get(key)!r}"
        for key, value in FLAGS.items()
        if stored.get(key) is not value
    ]
    if failed:
        raise FixtureCheckError("; ".join(failed))
