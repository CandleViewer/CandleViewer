"""FLAG-OVERRIDE-ROWS (E42-Q01, #962): AC-ADM-09's rows, written into the flag store's real tables.

A database writer can add override rows, or store in a flag a value no flag of its kind holds,
without the API; the resolver must hold either way (`admin/flags/resolver.py`). The seed writes:

- **Override rows on both safety flags**, the live gate and the kill switch `maintenance.mode`: a
  role override (`owner`) and a user override (MGR-M), each `true`. Neither flag takes an override,
  so each resolves to its stored `false` for both.
- **An unreadable row:** `algo.twap` stored as the string `"on"`, with a role override (`owner`) of
  `true`. Readable, it would resolve `true` for an Owner; unreadable, it fails closed to `false`,
  its override ignored. Slice A does not seed `algo.twap`, so no other handle reads it.

It builds on slice A's world (OWNER, MGR-M, the live gate's row) and never writes it. A kill switch
is not slice A's, so the seed adds the row of `maintenance.mode` at its default if it has none and
leaves a value already stored. The check reads the rows back and asserts each verdict with the
app's own `resolve`. Both refuse a database not named for tests before they read a row.
"""

from __future__ import annotations

from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from candleviewer.admin.flags.catalogue import FLAGS as CATALOGUE
from candleviewer.admin.flags.registry import LIVE_ENABLED, MAINTENANCE_MODE, value_matches
from candleviewer.admin.flags.resolver import StoredFlag, resolve
from candleviewer.db import models as m
from tests.fixtures.admin.handles import fixture_id, user
from tests.fixtures.admin.seed import FixtureCheckError, refuse_unless_test_database
from tests.fixtures.admin.world import require_world

#: The unreadable row's flag and what is stored in it: a string, where the flag is a boolean.
UNREADABLE: Final = "algo.twap"
UNREADABLE_VALUE: Final = "on"
#: The safety flags: the live gate and a kill switch, neither of which takes an override.
SAFETY: Final = (LIVE_ENABLED, MAINTENANCE_MODE)
#: The override rows, each `true`: the flag, whether the row targets a role (by name) or a user (by
#: handle), and whom.
OVERRIDES: Final = (
    (LIVE_ENABLED, "role", "owner"),
    (LIVE_ENABLED, "user", "MGR-M"),
    (MAINTENANCE_MODE, "role", "owner"),
    (MAINTENANCE_MODE, "user", "MGR-M"),
    (UNREADABLE, "role", "owner"),
)
REASON: Final = "fixture: an override row written outside the API"


async def seed_flag_overrides(conn: AsyncConnection) -> None:
    """The unreadable row and the kill switch's row, then the override rows; a second run keeps
    the rows the first wrote."""
    await refuse_unless_test_database(conn)
    await require_world(conn, users=("OWNER", "MGR-M"), flags=(LIVE_ENABLED,))
    flags = m.feature_flags
    stmt = pg_insert(flags).values(
        id=fixture_id(f"flag:{UNREADABLE}"),
        key=UNREADABLE,
        kind="boolean",
        default_value=UNREADABLE_VALUE,
    )
    await conn.execute(
        stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={"default_value": stmt.excluded.default_value},
            where=flags.c.default_value.is_distinct_from(stmt.excluded.default_value),
        )
    )
    await conn.execute(
        pg_insert(flags)
        .values(
            id=fixture_id(f"flag:{MAINTENANCE_MODE}"),
            key=MAINTENANCE_MODE,
            kind="boolean",
            default_value=False,
            is_killswitch=True,
        )
        .on_conflict_do_nothing(index_elements=["key"])  # a value already stored is not ours to set
    )
    keyed = await conn.execute(sa.select(flags.c.key, flags.c.id))
    flag_ids = {key: flag_id for key, flag_id in keyed.all()}
    named = await conn.execute(sa.select(m.roles.c.name, m.roles.c.id))
    role_ids = {name: role_id for name, role_id in named.all()}
    for key, kind, target in OVERRIDES:
        who: dict[str, Any] = (
            {"role_id": role_ids[target]} if kind == "role" else {"user_id": user(target).id}
        )
        await conn.execute(
            pg_insert(m.feature_flag_overrides)
            .values(
                id=fixture_id(f"override:{key}:{target}"),
                feature_flag_id=flag_ids[key],
                value=True,
                reason=REASON,
                **who,
            )
            .on_conflict_do_nothing()  # the primary key and both partial unique indexes
        )


async def _stored(conn: AsyncConnection) -> dict[str, StoredFlag]:
    """The flags this seed concerns as the store holds them, built from the rows read back."""
    f, o = m.feature_flags, m.feature_flag_overrides
    flags = (await conn.execute(sa.select(f.c.id, f.c.key, f.c.default_value))).mappings().all()
    read = sa.select(o.c.feature_flag_id, o.c.user_id, o.c.role_id, o.c.value)
    overrides = (await conn.execute(read)).mappings().all()
    named = await conn.execute(sa.select(m.roles.c.id, m.roles.c.name))
    role_names = {role_id: name for role_id, name in named.all()}
    stored: dict[str, StoredFlag] = {}
    for flag in flags:
        if flag["key"] not in (*SAFETY, UNREADABLE):
            continue
        mine = [row for row in overrides if row["feature_flag_id"] == flag["id"]]
        stored[flag["key"]] = StoredFlag(
            flag["default_value"],
            user_overrides={row["user_id"]: row["value"] for row in mine if row["user_id"]},
            role_overrides={
                role_names[row["role_id"]]: row["value"] for row in mine if row["role_id"]
            },
        )
    return stored


async def check_flag_overrides(conn: AsyncConnection) -> None:
    """Raise `FixtureCheckError` naming every post-condition the rows break: the override rows are
    the seed's, the unreadable row is unreadable, and the app's `resolve` gives each caller the
    closed value."""
    await refuse_unless_test_database(conn)
    stored = await _stored(conn)
    failed = [f"{key}: no row" for key in (*SAFETY, UNREADABLE) if key not in stored]
    if failed:
        raise FixtureCheckError("; ".join(failed))
    specs = {spec.key: spec for spec in CATALOGUE}
    owner, manager = user("OWNER"), user("MGR-M")
    for key in SAFETY:
        flag = stored[key]
        for who, principal, role in (("MGR-M", manager, "manager"), ("OWNER", owner, "owner")):
            got = resolve(specs[key], flag, user_id=principal.id, roles=frozenset({role}))
            if got is not False:
                failed.append(f"{key} for {who} resolves {got!r}, not False")
        if flag.value is not False:
            failed.append(f"{key}: is stored {flag.value!r}, not False")
        if flag.role_overrides != {"owner": True} or flag.user_overrides != {manager.id: True}:
            failed.append(f"{key}: its override rows are not owner and MGR-M, both true")
    twap = stored[UNREADABLE]
    got = resolve(specs[UNREADABLE], twap, user_id=owner.id, roles=frozenset({"owner"}))
    if got is not False:
        failed.append(f"{UNREADABLE} for OWNER resolves {got!r}, not False")
    if value_matches(specs[UNREADABLE], twap.value):
        failed.append(f"{UNREADABLE}: its stored value {twap.value!r} is readable")
    if twap.role_overrides != {"owner": True} or twap.user_overrides:
        failed.append(f"{UNREADABLE}: its override rows are not owner alone, true")
    if failed:
        raise FixtureCheckError("; ".join(failed))
