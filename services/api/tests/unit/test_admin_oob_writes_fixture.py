"""E42-Q01 (#962): OOB-WRITES: the writes' parameters, order and role, the refusals and the check
over a spoiled world, on an in-memory connection (no Docker). The Postgres half is
`tests/integration/admin/test_admin_fixture_b4a_pg.py`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import sqlalchemy as sa

from candleviewer.admin.flags.registry import LIVE_ENABLED
from candleviewer.observability.redaction import redact_text
from candleviewer.storage.repositories.backups_sqlalchemy import _path as backup_path_rule
from tests.fixtures.admin.handles import BACKUP_VERIFIED, BACKUPS, GRANTS, account, user
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
    """The rows the four writes leave, made by hand: the fake applies no update."""
    db = _world()
    owner = db.row("roles", name="owner")["id"]
    db.tables["user_roles"] = [{"user_id": _MGR_M.id, "role_id": owner}]
    access = [{"user_id": _MGR_M.id, "exchange_account_id": a} for a in (_SUB_S, _SUB_T)]
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


async def test_the_writes_set_the_owner_role_the_second_grant_the_gate_and_the_digest() -> None:
    db = _world()
    await seed_oob_writes(db.conn, now=_NOW)
    owner = db.row("roles", name="owner")["id"]
    assert db.tables["user_roles"] == [{"user_id": _MGR_M.id, "role_id": owner}]
    assert [r["exchange_account_id"] for r in db.tables["user_account_access"]] == [_SUB_T]
    updates = {cast(sa.Table, s.table).name: s for s in db.statements if isinstance(s, sa.Update)}
    assert updates["feature_flags"].compile().params["default_value"] is True
    assert updates["backups"].compile().params["checksum_sha256"] == BACKUP_DIGEST
    # each update writes only where it changes something, so a second run writes nothing
    assert "IS DISTINCT FROM" in str(updates["feature_flags"])
    assert "checksum_sha256 IS NULL" in str(updates["backups"])


async def test_a_database_not_named_for_tests_is_refused_before_anything_else() -> None:
    db = FakeDb("candleviewer")
    with pytest.raises(FixtureRefused):
        await seed_oob_writes(db.conn, now=_NOW)
    assert db.shapes == ["SELECT current_database()"]


async def test_a_login_other_than_the_test_containers_is_refused_before_a_row_is_read() -> None:
    db = FakeDb(login="cv_owner")
    with pytest.raises(FixtureRefused, match="cv_owner"):
        await seed_oob_writes(db.conn, now=_NOW)
    assert db.shapes == ["SELECT current_database()", "SELECT session_user"]


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


#: One write undone per case: how, and what the check names.
_SPOILS: list[tuple[str, Callable[[FakeDb], object], str]] = [
    ("no-owner-row", _drop("user_roles"), "MGR-M holds no Owner role row"),
    (
        "no-widened-grant",
        lambda db: db.tables["user_account_access"].pop(),
        "MGR-M holds no grant on SUB-T",
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


def test_the_digest_is_sha256_hex_and_the_path_passes_the_stores_rule() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", BACKUP_DIGEST)
    assert backup_path_rule(BACKUP_PATH) == BACKUP_PATH


def test_the_widened_account_is_one_mgr_m_does_not_hold_and_mgr_m_is_no_owner_yet() -> None:
    assert WIDENED_TO not in GRANTS["MGR-M"]
    assert _MGR_M.role != "owner"


def test_the_oob_backup_is_not_one_of_seed_backups_rows() -> None:
    assert BACKUP_ID not in {b.id for b in BACKUPS}


@pytest.mark.parametrize("value", [BACKUP_PATH, BACKUP_DIGEST])
def test_no_oob_value_is_secret_shaped(value: str) -> None:
    assert redact_text(value) == value
