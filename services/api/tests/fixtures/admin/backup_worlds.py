"""BACKUP-TAMPERED and BACKUP-THEN-REVOKED (E42-Q01, #962): two backups whose rows look usable,
each written with the audit records a restore reads, and each a world of its own: one database per
backup handle.

A restore reads its backup's digest and `covers_to` from the append-only trail, never from the row
(`admin/backups/evidence.py`): from the newest successful `backup.run` record at `stage: finished`.
Both seeds write that record through the real audit writer, with the engine's own builder. The
`backup.run` and `backup.verified` records name `system:backups` as their actor, where today's app
names the user who asked; the restore's reader ignores the actor.

- **BACKUP-TAMPERED** (AC-ADM-25): a `verified`, encrypted, kept row whose digest is not the one its
  run's record bound, as after an edit of the row or a swap of the artefact. The restore guard
  refuses it as `backup_not_usable` (`test_restore_guard.py`).
- **BACKUP-THEN-REVOKED** (AC-ADM-24): a backup the guard admits: its record binds the row's digest
  and its `covers_to`, and a passing `backup.verified` record stands beside it. After `covers_to`
  two revocations follow, each recorded through the writer as the app records it. MGR-M's grant on
  SUB-S is soft-revoked, `can_view` and `can_trade` false, as the disable cascade and
  `users.access_change` do it: `user_account_access` has no `revoked_at`, and `frozen` is the risk
  freeze, which a revocation never writes. OWNER-2's `owner` role is replaced by `viewer`
  (`roles.revoke`): the highest-privilege role, so a restore that brings it back is the worst
  rollback, and legal under the owner floor, as OWNER stays an Owner. A removed role leaves only
  its records as evidence: `roles.grant`, then `roles.revoke`, the role route's order.

Neither shares a database with `seed_backups`, whose check holds the catalogue to its two rows, nor
with the other: a seed refuses a catalogue that holds another backup, before it writes.
BACKUP-THEN-REVOKED builds on slice A's world (OWNER, OWNER-2, MGR-M, SUB-S) and never writes it;
after it, `check_admin_world` names the revoked grant and the replaced role. BACKUP-TAMPERED needs
no world and writes only its row and its record. Each seed waits for its writer's flush before it
reads the trail, so a record left in the WAL by a run cut before its flush is replayed, not written
twice. A database not named for tests is `FixtureRefused` before anything is read or written.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from candleviewer.admin.backups.rows import SYSTEM, run_record
from candleviewer.db import models as m
from candleviewer.storage.repositories.account_access import AccessChange, RemovalContext
from candleviewer.storage.repositories.account_access_sqlalchemy import _states
from tests.fixtures.admin.audit_session import audit_session, emit_at, read_audit_db
from tests.fixtures.admin.handles import (
    BACKUP_TAMPERED,
    BACKUP_THEN_REVOKED,
    BACKUPS,
    OWNER,
    FixtureBackup,
    account,
    fixture_id,
    user,
)
from tests.fixtures.admin.seed import (
    BACKUP_COLUMNS,
    FixtureCheckError,
    backup_differences,
    backup_row,
    insert_backup,
    require_aware,
)
from tests.fixtures.admin.world import require_world

#: The digest BACKUP-TAMPERED's run record bound: the artefact's, before the row was edited.
BOUND_DIGEST: Final = hashlib.sha256(b"fixture:BACKUP-TAMPERED:bound").hexdigest()
#: How long before `now` BACKUP-THEN-REVOKED's grant is revoked; its role goes an hour later.
REVOKED_AGO: Final = timedelta(days=2)
#: One fixture record: its action, the object it names, when it happened, and its `emit` fields.
_Record = tuple[str, str, datetime, dict[str, Any]]


async def _own_catalogue(conn: AsyncConnection, b: FixtureBackup) -> None:
    """`FixtureCheckError` unless `b`'s row is the only one in the catalogue, or none is."""
    held: Sequence[Any] = (await conn.execute(sa.select(m.backups.c.id))).scalars().all()
    named = {x.id: x.handle for x in (*BACKUPS, BACKUP_TAMPERED, BACKUP_THEN_REVOKED)}
    named[fixture_id("OOB-BACKUP")] = "OOB-BACKUP"  # OOB-WRITES' row (`oob_writes.BACKUP_ID`)
    if others := [named.get(i, "a row that is not a fixture's") for i in held if i != b.id]:
        raise FixtureCheckError(f"{b.handle} shares no database with another backup: {others}")


async def _recorded(conn: AsyncConnection, action: str, object_id: str) -> bool:
    log = m.audit_log
    read = sa.select(log.c.id).where(log.c.action == action, log.c.object_id == object_id)
    return bool((await conn.execute(read)).all())


async def _seed(
    dsn: str,
    wal_dir: Path,
    b: FixtureBackup,
    now: datetime,
    records: Sequence[_Record],
    *,
    prepare: Callable[[AsyncConnection], Awaitable[None]] | None = None,
    **columns: Any,
) -> None:
    """In one transaction `prepare`'s writes and `b`'s row (`columns` besides the seed's), then
    each record the trail does not hold yet, through a writer on `dsn`: a second run writes none."""
    require_aware(now)
    # One WAL per world: a backlog is replayed on start, into the database the writer points at.
    wal = wal_dir / f"fixture-{b.handle.lower()}.wal"
    async with audit_session(dsn, wal) as (relational, writer):
        await writer.flush(60)  # a backlog `start()` replays lands before the trail is read
        async with relational.engine.begin() as conn:
            await _own_catalogue(conn, b)
            if prepare is not None:
                await prepare(conn)
            await insert_backup(conn, b, now=now, **columns)
        async with relational.engine.connect() as conn:
            due = [r for r in records if not await _recorded(conn, r[0], r[1])]
        for action, _, at, fields in due:
            await emit_at(writer, action, at, **fields)


def _run(b: FixtureBackup, row: dict[str, Any], digest: str, **more: Any) -> _Record:
    """`b`'s `backup.run` record at `stage: finished`, as the engine's `RunRows.end` writes it."""
    state = {"stage": "finished", "size_bytes": row["size_bytes"], "checksum_sha256": digest}
    state |= {"error": None, **more}
    return ("backup.run", str(b.id), row["finished_at"], run_record(SYSTEM, b.id, state, None))


async def seed_backup_tampered(dsn: str, wal_dir: Path, *, now: datetime) -> None:
    """The row, `verified`, and its run's record binding another digest. `dsn` is the SQLAlchemy
    asyncpg URL of a migrated test database, and the writer's WAL goes in `wal_dir`."""
    b = BACKUP_TAMPERED
    await _seed(dsn, wal_dir, b, now, [_run(b, backup_row(b, now), BOUND_DIGEST)])


async def _revoke(conn: AsyncConnection) -> None:
    """MGR-M's grant on SUB-S soft-revoked as the app does it, and OWNER-2's `owner` role replaced
    by `viewer` as the role route does."""
    await require_world(conn, users=("OWNER", "OWNER-2", "MGR-M"), accounts=("SUB-S",))
    grants, roles, demoted = m.user_account_access, m.user_roles, user("OWNER-2").id
    live = sa.or_(grants.c.can_view, grants.c.can_trade)  # only a live grant is written
    mine = (
        grants.c.user_id == user("MGR-M").id,
        grants.c.exchange_account_id == account("SUB-S").id,
    )
    await conn.execute(sa.update(grants).where(*mine, live).values(can_view=False, can_trade=False))
    named = await conn.execute(sa.select(m.roles.c.name, m.roles.c.id))
    ids = {name: role_id for name, role_id in named.all()}
    await conn.execute(
        sa.delete(roles).where(roles.c.user_id == demoted, roles.c.role_id == ids["owner"])
    )
    viewer = pg_insert(roles).values(user_id=demoted, role_id=ids["viewer"], granted_by=OWNER.id)
    await conn.execute(viewer.on_conflict_do_nothing(index_elements=["user_id", "role_id"]))


async def seed_backup_then_revoked(dsn: str, wal_dir: Path, *, now: datetime) -> None:
    """The backup, its two records, the two revocations and their records. A second run writes
    nothing; `now` must be the first's, as a record's time is not refreshed."""
    b, row = BACKUP_THEN_REVOKED, backup_row(BACKUP_THEN_REVOKED, now)
    covers_to, manager, demoted = row["finished_at"], user("MGR-M").id, user("OWNER-2").id
    verified: dict[str, object] = {"stage": "finished"}
    verified["job_id"] = str(fixture_id("verify:BACKUP-THEN-REVOKED"))
    verified |= {"error": None, "verify_method": row["verify_method"]}
    checked = run_record(SYSTEM, b.id, verified, None)
    removed = AccessChange(manager, {account("SUB-S").id: "trade"}, {})
    before, after = _states(removed, RemovalContext(acknowledged_unknown_positions=True))
    by = {"actor_label": str(OWNER.id), "actor_user_id": OWNER.id, "object_kind": "user"}
    records: list[_Record] = [
        _run(b, row, b.checksum_sha256, covers_to=covers_to.isoformat()),
        ("backup.verified", str(b.id), row["verified_at"], checked),
        ("users.access_change", str(manager), now - REVOKED_AGO,
         {**by, "object_id": str(manager), "before_state": before, "after_state": after}),
    ]  # fmt: skip
    for action, role in (("roles.grant", "viewer"), ("roles.revoke", "owner")):
        fields = {**by, "object_id": str(demoted), "reason": role}
        fields |= {"before_state": {"roles": ["owner"]}, "after_state": {"roles": ["viewer"]}}
        records.append((action, str(demoted), now - REVOKED_AGO + timedelta(hours=1), fields))
    await _seed(dsn, wal_dir, b, now, records, prepare=_revoke, covers_to=covers_to)


def _row_read(b: FixtureBackup) -> sa.Select[Any]:
    columns = (*BACKUP_COLUMNS, "covers_to")
    return sa.select(*(m.backups.c[n] for n in columns)).where(m.backups.c.id == b.id)


def _record_read(*object_ids: str) -> sa.Select[Any]:
    log = m.audit_log
    columns = (log.c.action, log.c.object_id, log.c.outcome, log.c.event_ts, log.c.after_state)
    return sa.select(*columns).where(log.c.object_id.in_(object_ids)).order_by(log.c.id)


def _named(records: Sequence[RowMapping], action: str, object_id: str) -> list[RowMapping]:
    return [r for r in records if (r["action"], r["object_id"]) == (action, object_id)]


def _when(value: object) -> datetime | None:
    """A time a record's state holds as ISO text."""
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def _finished(records: Sequence[RowMapping]) -> list[dict[str, Any]]:
    """The states of the records a restore reads: successes at `stage: finished`."""
    states = [(r["outcome"], r["after_state"] or {}) for r in records]
    return [s for outcome, s in states if outcome == "success" and s.get("stage") == "finished"]


async def check_backup_tampered(dsn: str) -> None:
    """`FixtureCheckError` naming each way the world is not BACKUP-TAMPERED's: the row's values,
    and the digest its run record binds. It reads only its own row and records."""
    b = BACKUP_TAMPERED
    rows, records = await read_audit_db(dsn, _row_read(b), _record_read(str(b.id)))
    failed = backup_differences(b, rows[0] if rows else None)
    bound = [s.get("checksum_sha256") for s in _finished(_named(records, "backup.run", str(b.id)))]
    if bound != [BOUND_DIGEST]:
        failed.append(f"{b.handle}: its finished backup.run records bind {bound}, not its digest")
    if failed:
        raise FixtureCheckError("; ".join(failed))


async def check_backup_then_revoked(dsn: str) -> None:
    """`FixtureCheckError` naming each way the world is not BACKUP-THEN-REVOKED's: the row, its two
    records, the revocations in the rows, and their records after `covers_to`."""
    b, manager, demoted = BACKUP_THEN_REVOKED, user("MGR-M").id, user("OWNER-2").id
    grants, roles = m.user_account_access, m.user_roles
    revoked = grants.c.user_id == manager, grants.c.exchange_account_id == account("SUB-S").id
    rows, records, held, kept, named = await read_audit_db(
        dsn,
        _row_read(b),
        _record_read(str(b.id), str(manager), str(demoted)),
        sa.select(grants.c.can_view, grants.c.can_trade).where(*revoked),
        sa.select(roles.c.role_id).where(roles.c.user_id == demoted),
        sa.select(m.roles.c.id, m.roles.c.name),
    )
    failed = backup_differences(b, rows[0] if rows else None)
    if not rows:
        raise FixtureCheckError("; ".join(failed))
    row = rows[0]
    covers_to, finished_at = row["covers_to"], row["finished_at"]
    runs = _finished(_named(records, "backup.run", str(b.id)))
    passes = [
        s for s in _finished(_named(records, "backup.verified", str(b.id))) if not s.get("error")
    ]

    def follows(action: str, who: object) -> bool:
        """One record of `action` for `who`, after `covers_to`."""
        times = [r["event_ts"] for r in _named(records, action, str(who))]
        return len(times) == 1 and covers_to is not None and times[0] > covers_to

    names = {r["id"]: r["name"] for r in named}
    facts = {
        "covers_to is not when its run ended": covers_to is not None and covers_to == finished_at,
        "its backup.run record does not bind its digest and covers_to": [
            (s.get("checksum_sha256"), _when(s.get("covers_to"))) for s in runs
        ]
        == [(b.checksum_sha256, covers_to)],
        "it has not one passing backup.verified record": len(passes) == 1,
        "users.access_change is not one record after covers_to": follows(
            "users.access_change", manager
        ),
        "roles.revoke is not one record after covers_to": follows("roles.revoke", demoted),
        "MGR-M's grant on SUB-S is not soft-revoked": bool(held)
        and not any(g["can_view"] or g["can_trade"] for g in held),
        "OWNER-2's roles are not viewer alone": {names[r["role_id"]] for r in kept} == {"viewer"},
    }
    failed += [f"{b.handle}: {text}" for text, ok in facts.items() if not ok]
    if failed:
        raise FixtureCheckError("; ".join(failed))
