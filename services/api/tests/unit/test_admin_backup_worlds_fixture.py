"""E42-Q01 (#962): BACKUP-TAMPERED and BACKUP-THEN-REVOKED: the digests, the rows and records each
seed writes (through the real audit writer, over an in-memory database: no Docker), the refusals,
and each check over a spoiled world. The Postgres half, which reads the records back with the app's
own evidence reader, is `tests/integration/admin/test_admin_fixture_b4b_pg.py`.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
import sqlalchemy as sa

from candleviewer.audit.models import AuditOutcome
from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.writer import AuditWriter
from candleviewer.db import models as m
from candleviewer.storage.repositories.backups import SUCCESS_STATUSES
from tests.fixtures.admin.audit_session import emit_at
from tests.fixtures.admin.backup_worlds import (
    BOUND_DIGEST,
    REVOKED_AGO,
    _run,
    check_backup_tampered,
    check_backup_then_revoked,
    seed_backup_tampered,
    seed_backup_then_revoked,
)
from tests.fixtures.admin.handles import (
    BACKUP_TAMPERED,
    BACKUP_THEN_REVOKED,
    BACKUPS,
    OWNER,
    account,
    fixture_id,
    user,
)
from tests.fixtures.admin.seed import FixtureCheckError, FixtureRefused, backup_row
from tests.unit._admin_fake_db import FakeDb, patch_audit_session

_DSN = "postgresql+asyncpg://fixture@127.0.0.1:1/test"  # nothing connects: the fakes answer
_NOW = datetime(2026, 10, 23, 19, 0, tzinfo=UTC)
_OWNER_2, _MGR_M, _SUB_S = user("OWNER-2").id, user("MGR-M").id, account("SUB-S").id
_T, _R = BACKUP_TAMPERED, BACKUP_THEN_REVOKED
_Seed = Callable[[Path], Awaitable[None]]
_SEEDS: dict[str, _Seed] = {
    "tampered": lambda wal: seed_backup_tampered(_DSN, wal, now=_NOW),
    "revoked": lambda wal: seed_backup_then_revoked(_DSN, wal, now=_NOW),
}
_CHECKS: dict[str, Callable[[], Awaitable[None]]] = {
    "tampered": lambda: check_backup_tampered(_DSN),
    "revoked": lambda: check_backup_then_revoked(_DSN),
}
_BOTH = pytest.mark.parametrize("world", ["tampered", "revoked"])
FAILED = AuditOutcome.FAILURE.value


def _slice_a(deletes: tuple[str, ...] = ()) -> FakeDb:
    """The rows of slice A that BACKUP-THEN-REVOKED builds on; `deletes` as `FakeDb` takes it."""
    users = [{"id": i} for i in (OWNER.id, _OWNER_2, _MGR_M)]
    return FakeDb(deletes=deletes, users=users, exchange_accounts=[{"id": _SUB_S}])


#: The one delete BACKUP-THEN-REVOKED sends, OWNER-2's `owner` role; the tampered world sends none.
_REVOKED_DELETES = ("user_roles",)


async def _seeded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, world: str) -> FakeDb:
    """`world`'s seed run on the fake. It applies no UPDATE or DELETE, so the rows BACKUP-THEN-
    REVOKED's revocations leave are made by hand."""
    db = _slice_a(_REVOKED_DELETES if world == "revoked" else ())
    patch_audit_session(monkeypatch, db)
    await _SEEDS[world](tmp_path)
    if world == "revoked":
        viewer, owner = (db.row("roles", name=n)["id"] for n in ("viewer", "owner"))
        both = {"exchange_account_id": _SUB_S, "can_view": False, "can_trade": False}
        both |= {"frozen": False, "frozen_at": None}
        db.tables["user_account_access"] = [{"user_id": _MGR_M} | both]
        db.tables["user_roles"] = [
            {"user_id": _OWNER_2, "role_id": viewer},
            {"user_id": OWNER.id, "role_id": owner},
        ]
    return db


def _files(directory: Path) -> list[Path]:
    return list(directory.iterdir())


def _sent(db: FakeDb, kind: type[Any], table: str) -> Any:
    """The statement of `kind` that wrote `table`."""
    return next(s for s in db.statements if isinstance(s, kind) and s.table.name == table)


async def test_the_fake_allows_only_the_delete_a_test_names() -> None:
    db = FakeDb(deletes=("user_roles",))
    await db.conn.execute(sa.delete(m.user_roles))  # named: kept, and not applied
    with pytest.raises(AssertionError, match="does not model 'DELETE backups'"):
        await db.conn.execute(sa.delete(m.backups))


async def test_the_fake_with_a_named_delete_still_refuses_a_text_it_does_not_model() -> None:
    db = FakeDb(deletes=("user_roles",))
    with pytest.raises(AssertionError, match="does not model"):
        await db.conn.execute(sa.text("DROP TABLE x"))


def test_a_tampered_row_holds_a_digest_its_record_did_not_bind() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", BOUND_DIGEST)
    assert _T.checksum_sha256 != BOUND_DIGEST


@pytest.mark.parametrize("b", [_T, _R], ids=["tampered", "revoked"])
def test_each_backup_is_usable_and_not_one_of_seed_backups_rows(b: Any) -> None:
    assert b.status in SUCCESS_STATUSES  # the guard's status check
    assert b.id not in {x.id for x in BACKUPS}
    assert b.error is None


def test_the_revocations_follow_the_backups_covers_to() -> None:
    covers_to = backup_row(_R, _NOW)["finished_at"]
    assert _NOW - REVOKED_AGO > covers_to


async def test_the_tampered_seed_writes_a_verified_row_and_a_record_binding_the_other_digest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = await _seeded(monkeypatch, tmp_path, "tampered")
    [row] = db.tables["backups"]
    assert (row["id"], row["status"], row["encrypted"]) == (_T.id, "verified", True)
    assert row["checksum_sha256"] == _T.checksum_sha256
    [record] = db.tables["audit_log"]
    assert (record["action"], record["object_kind"], record["object_id"]) == (
        "backup.run",
        "backup",
        str(_T.id),
    )
    assert (record["outcome"], record["event_ts"]) == ("success", row["finished_at"])
    assert record["after_state"] == {
        "stage": "finished",
        "size_bytes": row["size_bytes"],
        "checksum_sha256": BOUND_DIGEST,
        "error": None,
    }
    await _CHECKS["tampered"]()


async def test_the_tampered_seed_needs_no_world_and_writes_only_its_row_and_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = FakeDb()  # no row of slice A, and no delete allowed
    patch_audit_session(monkeypatch, db)
    await _SEEDS["tampered"](tmp_path)
    assert [s for s in db.shapes if s.split()[0] in ("INSERT", "UPDATE", "DELETE")] == [
        "INSERT backups"
    ]
    assert [r["action"] for r in db.tables["audit_log"]] == ["backup.run"]


class _Down:
    """An `audit_log` that is unreachable: a record stays in the WAL."""

    async def insert(self, record: dict[str, Any]) -> None:
        raise OSError("the database is down")


async def test_a_seed_after_a_run_cut_before_its_flush_writes_no_second_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A run that ended between its emit and its flush leaves the record in the WAL. The next
    run's writer replays it inside its flusher, after `start()` returns: a seed that read the trail
    before the flush would find no record and write a second one, which can never be removed."""
    wal = tmp_path / f"fixture-{_T.handle.lower()}.wal"
    cut = AuditWriter(cast("AuditRepository", _Down()), str(wal))
    await cut.start()
    action, _, at, fields = _run(_T, backup_row(_T, _NOW), BOUND_DIGEST)
    await emit_at(cut, action, at, **fields)
    await cut.stop(0.05)
    db = await _seeded(monkeypatch, tmp_path, "tampered")
    assert [r["action"] for r in db.tables["audit_log"]] == ["backup.run"]


@pytest.fixture
async def revoked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeDb:
    """BACKUP-THEN-REVOKED seeded on the fake, with its revocations' rows made by hand."""
    return await _seeded(monkeypatch, tmp_path, "revoked")


def _records(db: FakeDb) -> dict[str, dict[str, Any]]:
    """Each record by its action: the seed writes one of each."""
    return {r["action"]: r for r in db.tables["audit_log"]}


async def test_the_revoked_seeds_row_covers_to_when_its_run_ended(revoked: FakeDb) -> None:
    [row] = revoked.tables["backups"]
    assert row["covers_to"] == row["finished_at"] == backup_row(_R, _NOW)["finished_at"]


async def test_the_revoked_seed_writes_its_records_in_the_apps_order(revoked: FakeDb) -> None:
    assert [r["action"] for r in revoked.tables["audit_log"]] == [
        "backup.run",
        "backup.verified",
        "users.access_change",
        "roles.grant",
        "roles.revoke",
    ]


async def test_the_revoked_seeds_run_record_binds_its_digest_and_covers_to(
    revoked: FakeDb,
) -> None:
    [row] = revoked.tables["backups"]
    assert _records(revoked)["backup.run"]["after_state"] == {
        "stage": "finished",
        "size_bytes": row["size_bytes"],
        "checksum_sha256": _R.checksum_sha256,
        "error": None,
        "covers_to": row["covers_to"].isoformat(),
    }


async def test_the_revoked_seeds_verification_passes_when_its_row_was_verified(
    revoked: FakeDb,
) -> None:
    [row] = revoked.tables["backups"]
    verified = _records(revoked)["backup.verified"]
    assert (verified["event_ts"], verified["after_state"]["error"]) == (row["verified_at"], None)


async def test_the_grant_revocation_is_recorded_by_owner_after_covers_to(revoked: FakeDb) -> None:
    [row] = revoked.tables["backups"]
    access = _records(revoked)["users.access_change"]
    assert access["event_ts"] == _NOW - REVOKED_AGO
    assert access["event_ts"] > row["covers_to"]
    assert (access["actor_user_id"], access["object_kind"], access["object_id"]) == (
        str(OWNER.id),
        "user",
        str(_MGR_M),
    )
    assert access["before_state"] == {
        "grants": [{"exchange_account_id": str(_SUB_S), "level": "trade", "frozen": False}]
    }
    assert access["after_state"]["grants"] == []


async def test_the_role_swap_is_recorded_an_hour_later_as_the_route_records_it(
    revoked: FakeDb,
) -> None:
    records = _records(revoked)
    grant, revoke = records["roles.grant"], records["roles.revoke"]
    assert grant["event_ts"] == revoke["event_ts"] == _NOW - REVOKED_AGO + timedelta(hours=1)
    assert (revoke["reason"], revoke["before_state"], revoke["after_state"]) == (
        "owner",
        {"roles": ["owner"]},
        {"roles": ["viewer"]},
    )
    assert (grant["reason"], grant["object_id"]) == ("viewer", str(_OWNER_2))


async def test_the_revoked_world_passes_its_check(revoked: FakeDb) -> None:
    await _CHECKS["revoked"]()


async def test_the_revoked_seed_soft_revokes_the_grant_and_swaps_the_role(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The statements; that they share one transaction the fake cannot see, and the Postgres
    case reads the rows they leave."""
    db = _slice_a(_REVOKED_DELETES)
    patch_audit_session(monkeypatch, db)
    await _SEEDS["revoked"](tmp_path)
    soft = _sent(db, sa.Update, "user_account_access").compile().params
    assert (soft["can_view"], soft["can_trade"]) == (False, False)
    assert "frozen" not in soft  # the risk freeze, which a revocation never writes
    assert {_MGR_M, _SUB_S} <= set(soft.values())
    live = "(user_account_access.can_view OR user_account_access.can_trade)"
    assert live in str(_sent(db, sa.Update, "user_account_access"))  # so a second run writes none
    dropped = _sent(db, sa.Delete, "user_roles").compile().params
    assert {_OWNER_2, db.row("roles", name="owner")["id"]} <= set(dropped.values())
    added = db.row("user_roles", user_id=_OWNER_2)
    assert (added["role_id"], added["granted_by"]) == (
        db.row("roles", name="viewer")["id"],
        OWNER.id,
    )


@_BOTH
async def test_a_second_seed_writes_no_record_and_each_row_is_do_nothing_on_its_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, world: str
) -> None:
    db = await _seeded(monkeypatch, tmp_path, world)
    records = len(db.tables["audit_log"])
    await _SEEDS[world](tmp_path)
    assert len(db.tables["audit_log"]) == records
    backup = _sent(db, sa.Insert, "backups")
    assert "ON CONFLICT (id) DO NOTHING" in str(backup.compile())


async def test_a_second_revoked_seed_adds_the_viewer_role_only_if_it_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = await _seeded(monkeypatch, tmp_path, "revoked")
    viewer = _sent(db, sa.Insert, "user_roles")
    assert "ON CONFLICT (user_id, role_id) DO NOTHING" in str(viewer.compile())


@_BOTH
async def test_a_naive_now_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, world: str
) -> None:
    patch_audit_session(monkeypatch, _slice_a())
    seed = {"tampered": seed_backup_tampered, "revoked": seed_backup_then_revoked}[world]
    with pytest.raises(ValueError, match="timezone-aware"):
        await seed(_DSN, tmp_path, now=_NOW.replace(tzinfo=None))


@pytest.mark.parametrize("run", ["seed", "check"])
@_BOTH
async def test_a_database_not_named_for_tests_is_refused_before_a_writer_or_a_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, world: str, run: str
) -> None:
    db = FakeDb("candleviewer")
    built = patch_audit_session(monkeypatch, db)
    with pytest.raises(FixtureRefused):
        await (_SEEDS[world](tmp_path) if run == "seed" else _CHECKS[world]())
    assert (built, db.shapes, "audit_log" in db.tables) == (
        [],
        ["SELECT current_database()"],
        False,
    )
    assert _files(tmp_path) == []  # no WAL file


_OTHERS = [
    ("tampered", BACKUPS[0].id, "BACKUP-VERIFIED"),
    ("tampered", BACKUPS[1].id, "BACKUP-VERIFY-FAILED"),
    ("tampered", _R.id, "BACKUP-THEN-REVOKED"),
    ("revoked", _T.id, "BACKUP-TAMPERED"),
    ("revoked", fixture_id("OOB-BACKUP"), "OOB-BACKUP"),
    ("revoked", uuid.UUID(int=7), "a row that is not a fixture's"),
]


@pytest.mark.parametrize(
    ("world", "other", "named"), _OTHERS, ids=[f"{o[0]}-{o[2]}" for o in _OTHERS]
)
async def test_a_catalogue_holding_another_backup_is_refused_and_nothing_is_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, world: str, other: uuid.UUID, named: str
) -> None:
    db = _slice_a()
    db.tables["backups"] = [{"id": other}]
    patch_audit_session(monkeypatch, db)
    with pytest.raises(
        FixtureCheckError, match=rf"shares no database with another backup: .*{named}"
    ):
        await _SEEDS[world](tmp_path)
    assert [s for s in db.shapes if s.split()[0] in ("INSERT", "UPDATE", "DELETE")] == []
    assert db.tables.get("audit_log", []) == []  # no record either


async def test_the_revoked_world_without_slice_as_rows_is_named_and_nothing_is_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = FakeDb()
    patch_audit_session(monkeypatch, db)
    with pytest.raises(FixtureCheckError, match="lacks OWNER, OWNER-2, MGR-M, SUB-S"):
        await _SEEDS["revoked"](tmp_path)
    assert [s for s in db.shapes if s.split()[0] in ("INSERT", "UPDATE", "DELETE")] == []


def _row(db: FakeDb, **changed: Any) -> None:
    db.tables["backups"][0].update(changed)  # the only row


def _drop(db: FakeDb, action: str) -> None:
    db.tables["audit_log"].remove(next(r for r in db.tables["audit_log"] if r["action"] == action))


def _edit(action: str, **changed: Any) -> Callable[[FakeDb], None]:
    return lambda db: next(r for r in db.tables["audit_log"] if r["action"] == action).update(
        changed
    )


def _twice(action: str) -> Callable[[FakeDb], None]:
    """The record of `action`, written a second time."""
    return lambda db: db.tables["audit_log"].append(
        dict(next(r for r in db.tables["audit_log"] if r["action"] == action))
    )


def _bound(**changed: Any) -> Callable[[FakeDb], None]:
    """The `backup.run` record's state, with `changed`."""

    def spoil(db: FakeDb) -> None:
        run = next(r for r in db.tables["audit_log"] if r["action"] == "backup.run")
        run["after_state"] = run["after_state"] | changed

    return spoil


#: One fact spoiled per case: its world, how, and what the check names.
_SPOILS: list[tuple[str, str, Callable[[FakeDb], None], str]] = [
    ("tampered", "a row with the bound digest", lambda d: _row(d, checksum_sha256=BOUND_DIGEST),
     "checksum_sha256 is .*, not"),
    ("tampered", "a deleted row", lambda d: _row(d, deleted_at=_NOW), "deleted_at is 'set'"),
    ("tampered", "a failed row", lambda d: _row(d, status="failed"), "status is 'failed'"),
    ("tampered", "no row", lambda d: d.tables["backups"].clear(), "BACKUP-TAMPERED: no row"),
    ("tampered", "no record", lambda d: _drop(d, "backup.run"), r"bind \[\], not its digest"),
    ("tampered", "the digest of the row", _bound(checksum_sha256=_T.checksum_sha256), "bind"),
    ("tampered", "a record not at finished", _bound(stage="requested"), r"bind \[\]"),
    ("tampered", "a failed record", _edit("backup.run", outcome=FAILED), "bind"),
    ("revoked", "covers_to unset", lambda d: _row(d, covers_to=None), "covers_to is not when"),
    ("revoked", "covers_to early", lambda d: _row(d, covers_to=_NOW - timedelta(days=9)),
     "covers_to is not when"),
    ("revoked", "no covers_to in the record", _bound(covers_to=None),
     "backup.run record does not bind its digest and covers_to"),
    ("revoked", "another digest bound", _bound(checksum_sha256=BOUND_DIGEST),
     "backup.run record does not bind"),
    ("revoked", "no verification", lambda d: _drop(d, "backup.verified"),
     "not one passing backup.verified record"),
    ("revoked", "a failed verification",
     _edit("backup.verified", after_state={"stage": "finished", "error": "checksum_mismatch"}),
     "not one passing backup.verified record"),
    ("revoked", "two passing verifications", _twice("backup.verified"),
     "not one passing backup.verified record"),
    ("revoked", "the grant record before covers_to",
     _edit("users.access_change", event_ts=_NOW - timedelta(days=9)),
     "users.access_change is not one record after covers_to"),
    ("revoked", "no grant record", lambda d: _drop(d, "users.access_change"),
     "users.access_change is not one record"),
    ("revoked", "no role record", lambda d: _drop(d, "roles.revoke"),
     "roles.revoke is not one record"),
    ("revoked", "a live grant", lambda d: d.tables["user_account_access"][0].update(can_view=True),
     "grant on SUB-S is not soft"),
    ("revoked", "a trade grant",
     lambda d: d.tables["user_account_access"][0].update(can_view=True, can_trade=True),
     "grant on SUB-S is not soft"),
    ("revoked", "no grant row", lambda d: d.tables["user_account_access"].clear(),
     "grant on SUB-S is not soft"),
    ("revoked", "the owner role kept",
     lambda d: d.tables["user_roles"].append(
         {"user_id": _OWNER_2, "role_id": d.row("roles", name="owner")["id"]}),
     "OWNER-2's roles are not viewer alone"),
    ("revoked", "no role left", lambda d: d.tables["user_roles"].clear(),
     "OWNER-2's roles are not viewer alone"),
    ("revoked", "a frozen grant",
     lambda d: d.tables["user_account_access"][0].update(frozen=True, frozen_at=_NOW),
     "carries the risk freeze"),
    ("revoked", "a freeze time alone",
     lambda d: d.tables["user_account_access"][0].update(frozen_at=_NOW),
     "carries the risk freeze"),
    ("revoked", "OWNER demoted too",
     lambda d: d.tables["user_roles"].remove(
         {"user_id": OWNER.id, "role_id": d.row("roles", name="owner")["id"]}),
     "OWNER no longer holds the owner role"),
]  # fmt: skip


@pytest.mark.parametrize("world", ["tampered", "revoked"])
async def test_the_check_passes_the_world_its_seed_made(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, world: str
) -> None:
    await _seeded(monkeypatch, tmp_path, world)
    await _CHECKS[world]()


@pytest.mark.parametrize(
    ("world", "spoil", "named"), [c[:1] + c[2:] for c in _SPOILS], ids=[c[1] for c in _SPOILS]
)
async def test_the_check_names_a_fact_that_is_spoiled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    world: str,
    spoil: Callable[[FakeDb], None],
    named: str,
) -> None:
    db = await _seeded(monkeypatch, tmp_path, world)
    spoil(db)
    with pytest.raises(FixtureCheckError, match=named):
        await _CHECKS[world]()
