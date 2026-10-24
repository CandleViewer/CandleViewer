"""What the later admin seeds need of slice A's world (E42-Q01, #962).

FLAG-OVERRIDE-ROWS and OOB-WRITES build on the users, accounts and flags that `seed_admin_world`
writes. They never write those rows themselves: a missing one is a `FixtureCheckError` naming its
handle, and the cure is to seed the world first.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from candleviewer.db import models as m
from tests.fixtures.admin.handles import account, user
from tests.fixtures.admin.seed import FixtureCheckError


async def require_world(
    conn: AsyncConnection,
    *,
    users: Sequence[str] = (),
    accounts: Sequence[str] = (),
    flags: Sequence[str] = (),
) -> None:
    """Raise `FixtureCheckError` naming each user, account (by handle) and flag (by key) of the
    world that has no row."""
    wanted: list[tuple[sa.Table, str, dict[Any, str]]] = [
        (m.users, "id", {user(h).id: h for h in users}),
        (m.exchange_accounts, "id", {account(h).id: h for h in accounts}),
        (m.feature_flags, "key", {k: k for k in flags}),
    ]
    missing: list[str] = []
    for table, column, names in wanted:
        if names:
            read = sa.select(table.c[column]).where(table.c[column].in_(list(names)))
            held: set[Any] = set((await conn.execute(read)).scalars().all())
            missing += [name for key, name in names.items() if key not in held]
    if missing:
        raise FixtureCheckError(f"the world lacks {', '.join(missing)}: run seed_admin_world first")
