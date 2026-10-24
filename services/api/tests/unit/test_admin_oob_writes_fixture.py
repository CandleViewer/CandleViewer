"""E42-Q01 (#962): OOB-WRITES: the writes' parameters, order and role, the refusals and the check
over a spoiled world, on an in-memory connection (no Docker). The Postgres half is
`tests/integration/admin/test_admin_fixture_b4a_pg.py`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import asyncpg

from candleviewer.admin.flags.registry import LIVE_ENABLED
from candleviewer.db import models as m
from candleviewer.observability.redaction import redact_text
from candleviewer.storage.repositories.backups_sqlalchemy import _path as backup_path_rule
from tests.fixtures.admin.handles import BACKUP_VERIFIED, BACKUPS, GRANTS, USERS, account, user
from tests.fixtures.admin.oob_writes import (
    BACKUP_DIGEST,
    BACKUP_ID,
    BACKUP_PATH,
    WIDENED_TO,
    check_oob_writes,
    seed_oob_writes,
)
from tests.fixtures.admin.seed import FixtureCheckError, FixtureRefused
from tests.unit._admin_fake_db import FakeDb

_NOW = datetime(2026, 10, 23, 19, 0, tzinfo=UTC)
_MGR_M = user("MGR-M")
_SUB_S, _SUB_T = account("SUB-S").id, account(WIDENED_TO).id
_PG = asyncpg.dialect()  # type: ignore[no-untyped-call]  # SQLAlchemy leaves the dialect untyped


def _world(**more: list[dict[str, Any]]) -> FakeDb:
    """Slice A's rows this seed builds on, and any `more` tables."""
    db = FakeDb(
        users=[{"id": _MGR_M.id}],
        exchange_accounts=[{"id": _SUB_S}, {"id": _SUB_T}],
        feature_flags=[{"key": LIVE_ENABLED, "default_value": False}],
    )
    db.tables |= more
    return db


def _written() -> FakeDb:
    """The rows the four writes leave, made by hand (the fake applies no update), beside the other
    users' rows slice A holds: OWNER and OWNER-2 are Owners, and MGR-MANY holds SUB-T."""
    db = _world()
    owner = db.row("roles", name="owner")["id"]
    owners = [user(h).id for h in ("OWNER", "OWNER-2", "MGR-M")]
    db.tables["user_roles"] = [{"user_id": u, "role_id": owner} for u in owners]
    access = [{"user_id": _MGR_M.id, "exchange_account_id": a} for a in (_SUB_S, _SUB_T)]
    access.append({"user_id": user("MGR-MANY").id, "exchange_account_id": _SUB_T})
    db.tables["user_account_access"] = access
    db.row("feature_flags", key=LIVE_ENABLED)["default_value"] = True
    db.tables["backups"] = [{"id": BACKUP_ID, "checksum_sha256": BACKUP_DIGEST}]
    return db


async def test_the_writes_run_as_cv_app_after_the_backups_own_row() -> None:
    db = _world()
    await seed_oob_writes(db.conn, now=_NOW)
    sent = db.shapes
    start, end = sent.index("SET ROLE cv_app"), sent.index("RESET ROLE")
    assert sent[start + 1 : end] == [
        "INSERT user_roles",
        "INSERT user_account_access",
        "UPDATE feature_flags",
        "UPDATE backups",
    ]
    assert "INSERT backups" in sent[:start]  # made as the session's user: no write of cv_app's
    assert end == len(sent) - 1


def _updates(db: FakeDb) -> dict[str, sa.Update]:
    return {cast(sa.Table, s.table).name: s for s in db.statements if isinstance(s, sa.Update)}


async def test_the_writes_set_the_owner_role_the_second_grant_the_gate_and_the_digest() -> None:
    db = _world()
    await seed_oob_writes(db.conn, now=_NOW)
    owner = db.row("roles", name="owner")["id"]
    updates = _updates(db)
    assert db.tables["user_roles"] == [{"user_id": _MGR_M.id, "role_id": owner}]
    assert [r["exchange_account_id"] for r in db.tables["user_account_access"]] == [_SUB_T]
    assert updates["feature_flags"].compile().params["default_value"] is True
    assert updates["backups"].compile().params["checksum_sha256"] == BACKUP_DIGEST


async def test_each_update_writes_only_where_it_changes_something() -> None:
    db = _world()
    await seed_oob_writes(db.conn, now=_NOW)
    updates = _updates(db)
    assert "IS DISTINCT FROM" in str(updates["feature_flags"])
    assert "checksum_sha256 IS NULL" in str(updates["backups"])


async def test_each_insert_does_nothing_on_a_conflict() -> None:
    db = _world()
    await seed_oob_writes(db.conn, now=_NOW)
    clauses = {
        cast(sa.Table, s.table).name: str(s.compile(dialect=_PG)).partition(" ON CONFLICT ")[2]
        for s in db.statements
        if isinstance(s, sa.Insert)
    }
    assert clauses == {
        "backups": "(id) DO NOTHING",
        "user_roles": "(user_id, role_id) DO NOTHING",
        "user_account_access": "(user_id, exchange_account_id) DO NOTHING",
    }


async def test_oob_backup_is_a_finished_dump_an_hour_old_with_no_digest() -> None:
    db = _world()
    await seed_oob_writes(db.conn, now=_NOW)
    row = db.row("backups", id=BACKUP_ID)
    started = _NOW - timedelta(hours=1)
    assert (row["kind"], row["status"], row["target_path"]) == ("pg_dump", "ok", BACKUP_PATH)
    assert (row["started_at"], row["finished_at"]) == (started, started + timedelta(minutes=10))
    assert row.get("checksum_sha256") is None


async def test_a_database_not_named_for_tests_is_refused_before_anything_else() -> None:
    db = FakeDb("candleviewer")
    with pytest.raises(FixtureRefused):
        await seed_oob_writes(db.conn, now=_NOW)
    assert db.shapes == ["SELECT current_database()"]


@pytest.mark.parametrize("login", ["cv_owner", "cv_app", "Test", "test2", "tester", "test ", ""])
async def test_a_login_other_than_the_test_containers_is_refused_before_a_row_is_read(
    login: str,
) -> None:
    db = FakeDb(login=login)
    with pytest.raises(FixtureRefused, match=re.escape(repr(login))):
        await seed_oob_writes(db.conn, now=_NOW)
    assert db.shapes == ["SELECT current_database()", "SELECT session_user"]


async def test_the_fake_fails_a_statement_it_does_not_model() -> None:
    with pytest.raises(AssertionError, match="does not model 'DELETE users'"):
        await FakeDb().conn.execute(sa.delete(m.users))


async def test_a_naive_now_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        await seed_oob_writes(_world().conn, now=_NOW.replace(tzinfo=None))


async def test_a_world_without_its_rows_is_named_and_nothing_is_written() -> None:
    db = FakeDb()
    with pytest.raises(
        FixtureCheckError, match=r"lacks MGR-M, SUB-S, SUB-T, trading\.live_enabled"
    ):
        await seed_oob_writes(db.conn, now=_NOW)
    assert [s for s in db.shapes if s.split()[0] in ("INSERT", "UPDATE", "SET")] == []


async def test_the_backups_of_seed_backups_are_refused_before_anything_is_written() -> None:
    db = _world(backups=[{"id": BACKUP_VERIFIED.id}])
    with pytest.raises(
        FixtureCheckError, match="OOB-BACKUP shares no database with seed_backups: BACKUP-VERIFIED"
    ):
        await seed_oob_writes(db.conn, now=_NOW)
    assert [s for s in db.shapes if s.split()[0] in ("INSERT", "UPDATE", "SET")] == []


async def test_the_check_passes_the_rows_the_writes_leave() -> None:
    await check_oob_writes(_written().conn)


def _drop(table: str) -> Callable[[FakeDb], object]:
    return lambda db: db.tables[table].clear()


def _drop_mgr_m(table: str, **where: Any) -> Callable[[FakeDb], object]:
    """Drop MGR-M's row of `table` alone: the other users' rows stay, so the check must filter."""
    return lambda db: db.tables[table].remove(db.row(table, user_id=_MGR_M.id, **where))


#: One write undone per case: how, and what the check names.
_SPOILS: list[tuple[str, Callable[[FakeDb], object], str]] = [
    ("no-owner-row", _drop_mgr_m("user_roles"), "MGR-M holds no Owner role row"),
    (
        "no-widened-grant",
        _drop_mgr_m("user_account_access", exchange_account_id=_SUB_T),
        "MGR-M holds no grant on SUB-T",
    ),
    (
        "no-original-grant",
        _drop_mgr_m("user_account_access", exchange_account_id=_SUB_S),
        "MGR-M holds no grant on SUB-S",
    ),
    (
        "gate-off",
        lambda db: db.row("feature_flags", key=LIVE_ENABLED).update(default_value=False),
        "is False, not True",
    ),
    ("no-backup", _drop("backups"), "OOB-BACKUP: no row"),
    (
        "no-digest",
        lambda db: db.tables["backups"][0].update(checksum_sha256=None),
        "its digest is None",
    ),
]


@pytest.mark.parametrize(
    ("spoil", "named"), [(c[1], c[2]) for c in _SPOILS], ids=[c[0] for c in _SPOILS]
)
async def test_the_check_names_a_write_that_is_not_there(
    spoil: Callable[[FakeDb], object], named: str
) -> None:
    db = _written()
    spoil(db)
    with pytest.raises(FixtureCheckError, match=re.escape(named)):
        await check_oob_writes(db.conn)


async def test_the_check_refuses_a_database_not_named_for_tests() -> None:
    db = FakeDb("candleviewer")
    with pytest.raises(FixtureRefused):
        await check_oob_writes(db.conn)
    assert db.shapes == ["SELECT current_database()"]


def test_the_digest_is_sha256_hex() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", BACKUP_DIGEST)


def test_the_backups_path_passes_the_stores_rule() -> None:
    assert backup_path_rule(BACKUP_PATH) == BACKUP_PATH


def test_the_widened_account_is_one_mgr_m_does_not_hold() -> None:
    assert WIDENED_TO not in GRANTS["MGR-M"]


def test_mgr_m_is_no_owner_until_the_writes() -> None:
    assert _MGR_M.role != "owner"


def test_slice_a_holds_owners_and_a_grantee_the_check_must_not_count() -> None:
    roles = {u.handle: u.role for u in USERS}
    assert (roles["OWNER"], roles["OWNER-2"], WIDENED_TO in GRANTS["MGR-MANY"]) == (
        "owner",
        "owner",
        True,
    )


def test_the_oob_backup_is_not_one_of_seed_backups_rows() -> None:
    assert BACKUP_ID not in {b.id for b in BACKUPS}


@pytest.mark.parametrize("value", [BACKUP_PATH, BACKUP_DIGEST])
def test_no_oob_value_is_secret_shaped(value: str) -> None:
    assert redact_text(value) == value
