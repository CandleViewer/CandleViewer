"""E42-Q01 (#962): FLAG-OVERRIDE-ROWS: the rows' parameters, the refusal of a database not named for
tests and the check over a spoiled world, on an in-memory connection (no Docker). The Postgres half
is `tests/integration/admin/test_admin_fixture_b4a_pg.py`.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import asyncpg

from candleviewer.admin.flags.catalogue import FLAGS as CATALOGUE
from candleviewer.admin.flags.registry import LIVE_ENABLED, MAINTENANCE_MODE, value_matches
from candleviewer.admin.flags.resolver import StoredFlag, resolve
from candleviewer.db import models as m
from candleviewer.observability.redaction import redact_text
from tests.fixtures.admin import flag_overrides
from tests.fixtures.admin.flag_overrides import (
    OVERRIDES,
    REASON,
    UNREADABLE,
    UNREADABLE_VALUE,
    check_flag_overrides,
    seed_flag_overrides,
)
from tests.fixtures.admin.handles import FLAGS, USERS, account, fixture_id, user
from tests.fixtures.admin.seed import FixtureCheckError, FixtureRefused
from tests.fixtures.admin.world import require_world
from tests.unit._admin_fake_db import FakeDb

_SPECS = {spec.key: spec for spec in CATALOGUE}
_OWNER, _MGR_M = user("OWNER"), user("MGR-M")
_SAFETY = [LIVE_ENABLED, MAINTENANCE_MODE]  # the live gate and a kill switch: no override takes
_PG = asyncpg.dialect()  # type: ignore[no-untyped-call]  # SQLAlchemy leaves the dialect untyped


def _world() -> FakeDb:
    """Slice A's rows this seed builds on: OWNER, MGR-M and the live gate's flag row."""
    gate = {"id": fixture_id(f"flag:{LIVE_ENABLED}"), "key": LIVE_ENABLED, "default_value": False}
    return FakeDb(users=[{"id": _OWNER.id}, {"id": _MGR_M.id}], feature_flags=[gate])


@pytest.fixture
async def seeded() -> FakeDb:
    db = _world()
    await seed_flag_overrides(db.conn)
    return db


def _override(db: FakeDb, key: str, **target: Any) -> dict[str, Any]:
    return db.row(
        "feature_flag_overrides", feature_flag_id=db.row("feature_flags", key=key)["id"], **target
    )


async def test_the_check_passes_the_rows_the_seed_made(seeded: FakeDb) -> None:
    await check_flag_overrides(seeded.conn)


async def test_the_seed_stores_each_flag_it_concerns_as_documented(seeded: FakeDb) -> None:
    stored = {r["key"]: r["default_value"] for r in seeded.tables["feature_flags"]}
    assert stored == {LIVE_ENABLED: False, MAINTENANCE_MODE: False, UNREADABLE: UNREADABLE_VALUE}


async def test_the_seed_sends_no_update_and_no_delete(seeded: FakeDb) -> None:
    assert [s for s in seeded.shapes if s.lstrip().upper().startswith(("UPDATE", "DELETE"))] == []


async def test_only_the_unreadable_flags_row_is_written_over_on_a_conflict(seeded: FakeDb) -> None:
    """A safety flag's stored value is not the seed's to set: its insert does nothing on a
    conflict, and only the unreadable row's writes its value over a stored one."""
    upserts = [
        stmt.compile().params["key"]
        for stmt in seeded.statements
        if isinstance(stmt, sa.Insert)
        and stmt.table is m.feature_flags
        and "DO UPDATE" in str(stmt.compile(dialect=_PG))
    ]
    assert upserts == [UNREADABLE]


async def test_the_seed_makes_maintenance_mode_the_kill_switch_row_the_app_makes(
    seeded: FakeDb,
) -> None:
    row = seeded.row("feature_flags", key=MAINTENANCE_MODE)
    assert (row["is_killswitch"], row["kind"]) == (True, "boolean")


async def _refuses(db: FakeDb, named: str) -> None:
    with pytest.raises(FixtureCheckError, match=named):
        await check_flag_overrides(db.conn)


@pytest.mark.parametrize("key", _SAFETY)
@pytest.mark.parametrize(
    "named",
    [
        "{} for MGR-M resolves True, not False",
        "{} for OWNER resolves True, not False",
        "{}: is stored True",
    ],
)
async def test_the_check_names_a_safety_flag_stored_true(
    seeded: FakeDb, key: str, named: str
) -> None:
    seeded.row("feature_flags", key=key)["default_value"] = True
    await _refuses(seeded, named.format(key))


@pytest.mark.parametrize("key", _SAFETY)
async def test_the_check_names_a_safety_flag_stored_as_no_boolean(seeded: FakeDb, key: str) -> None:
    # unreadable, so each fails closed: trading.live_enabled to False, maintenance.mode to True
    seeded.row("feature_flags", key=key)["default_value"] = "off"
    await _refuses(seeded, f"{key}: is stored 'off', not False")


async def test_each_safety_verdict_is_the_apps_resolve(
    seeded: FakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(flag_overrides, "resolve", lambda *_args, **_kwargs: True)
    with pytest.raises(FixtureCheckError) as raised:
        await check_flag_overrides(seeded.conn)
    named = [f"{k} for {who} resolves True" for k in _SAFETY for who in ("MGR-M", "OWNER")]
    assert [n for n in named if n not in str(raised.value)] == []


@pytest.mark.parametrize("key", _SAFETY)
@pytest.mark.parametrize("lost", ["user", "role"])
async def test_the_check_names_a_lost_override_of_a_safety_flag(
    seeded: FakeDb, key: str, lost: str
) -> None:
    target = (
        {"user_id": _MGR_M.id}
        if lost == "user"
        else {"role_id": seeded.row("roles", name="owner")["id"]}
    )
    seeded.tables["feature_flag_overrides"].remove(_override(seeded, key, **target))
    await _refuses(seeded, f"{key}: its override rows are not owner and MGR-M")


async def test_the_check_names_an_override_turned_off(seeded: FakeDb) -> None:
    role = seeded.row("roles", name="owner")["id"]
    _override(seeded, UNREADABLE, role_id=role)["value"] = False
    await _refuses(seeded, f"{UNREADABLE}: its override rows are not owner alone, true")


async def test_the_check_names_a_user_override_on_the_unreadable_flag(seeded: FakeDb) -> None:
    flag = seeded.row("feature_flags", key=UNREADABLE)["id"]
    stray = {"feature_flag_id": flag, "user_id": _MGR_M.id, "value": True}
    seeded.tables["feature_flag_overrides"].append(stray)
    await _refuses(seeded, f"{UNREADABLE}: its override rows are not owner alone, true")


@pytest.mark.parametrize(
    "named",
    [f"{UNREADABLE}: its stored value False is readable", f"{UNREADABLE} for OWNER resolves True"],
)
async def test_the_check_names_a_row_made_readable(seeded: FakeDb, named: str) -> None:
    seeded.row("feature_flags", key=UNREADABLE)["default_value"] = False
    await _refuses(seeded, named)


async def test_the_check_names_a_missing_flag_row(seeded: FakeDb) -> None:
    seeded.tables["feature_flags"].remove(seeded.row("feature_flags", key=UNREADABLE))
    await _refuses(seeded, f"{UNREADABLE}: no row")


@pytest.mark.parametrize("run", [seed_flag_overrides, check_flag_overrides])
async def test_a_database_not_named_for_tests_is_refused_before_anything_else(run: Any) -> None:
    db = FakeDb("candleviewer")
    with pytest.raises(FixtureRefused):
        await run(db.conn)
    assert db.shapes == ["SELECT current_database()"]


async def test_the_check_names_a_missing_safety_flag_row(seeded: FakeDb) -> None:
    seeded.tables["feature_flags"].remove(seeded.row("feature_flags", key=MAINTENANCE_MODE))
    await _refuses(seeded, f"{MAINTENANCE_MODE}: no row")


async def test_a_world_without_its_rows_is_named_and_nothing_is_written() -> None:
    db = FakeDb()
    with pytest.raises(FixtureCheckError, match=r"lacks OWNER, MGR-M, trading\.live_enabled"):
        await seed_flag_overrides(db.conn)
    assert [s for s in db.shapes if s.startswith("INSERT")] == []


async def test_the_world_names_a_missing_account() -> None:
    held = FakeDb(exchange_accounts=[{"id": account("SUB-S").id}])
    await require_world(held.conn, accounts=("SUB-S",))
    with pytest.raises(FixtureCheckError, match=r"lacks SUB-T: run seed_admin_world first"):
        await require_world(held.conn, accounts=("SUB-S", "SUB-T"))


def test_the_unreadable_flag_is_a_catalogued_boolean_that_takes_overrides() -> None:
    spec = _SPECS[UNREADABLE]
    assert (spec.kind, spec.overridable, spec.fail_closed_value) == ("boolean", True, False)


def test_the_unreadable_value_is_none_a_boolean_flag_can_hold() -> None:
    assert not value_matches(_SPECS[UNREADABLE], UNREADABLE_VALUE)


def test_the_same_override_on_a_readable_row_would_resolve_true_for_an_owner() -> None:
    spec, roles = _SPECS[UNREADABLE], frozenset({"owner"})
    readable = StoredFlag(False, role_overrides={"owner": True})
    unreadable = dataclasses.replace(readable, value=UNREADABLE_VALUE)
    assert resolve(spec, readable, user_id=_OWNER.id, roles=roles) is True
    assert resolve(spec, unreadable, user_id=_OWNER.id, roles=roles) is False


@pytest.mark.parametrize("key", _SAFETY)
def test_a_safety_flag_takes_no_override_and_is_stored_off(key: str) -> None:
    spec = _SPECS[key]
    assert (spec.overridable, spec.default) == (False, False)
    assert FLAGS.get(key, False) is False  # the live gate is slice A's; the kill switch is not


def test_maintenance_mode_is_a_kill_switch_that_slice_a_does_not_seed() -> None:
    assert (_SPECS[MAINTENANCE_MODE].is_killswitch, MAINTENANCE_MODE in FLAGS) == (True, False)


def test_slice_a_does_not_seed_the_unreadable_flag() -> None:
    assert UNREADABLE not in FLAGS


def test_each_override_targets_a_known_role_or_user() -> None:
    known = {"role": set(m.role_name.enums), "user": {u.handle for u in USERS}}
    assert [t for _flag, kind, t in OVERRIDES if t not in known[kind]] == []


@pytest.mark.parametrize("value", [UNREADABLE, UNREADABLE_VALUE, REASON])
def test_no_flag_override_value_is_secret_shaped(value: str) -> None:
    assert redact_text(value) == value
