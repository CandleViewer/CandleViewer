"""The hotkey profile store without a database (E10-T05, #5211): every statement names the owner and
repeats the column list, a replace naming a version is guarded by it, and each method runs its
statements in order against a stub unit of work: the owner's lock first, its record after its
statements and before the commit, nothing committed when it is refused. Real Postgres:
tests/integration/storage/test_hotkey_profiles_store_pg.py (the shared contract and the races).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.errors import StorageConstraintViolated
from candleviewer.storage.repositories import hotkey_profiles_sqlalchemy as mod
from candleviewer.storage.repositories.hotkey_profiles import (
    MAX_PROFILES,
    HotkeyProfileActiveError,
    HotkeyProfileFields,
    HotkeyProfileLimitError,
    HotkeyProfileNameTakenError,
    HotkeyProfileNotFoundError,
    HotkeyProfileRow,
    HotkeyProfileStaleError,
)

_T = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
_OWNER, _ID, _OTHER = uuid.UUID(int=10), uuid.UUID(int=1), uuid.UUID(int=2)
_STATEMENTS = {n: v for n, v in vars(mod).items() if isinstance(v, sa.TextClause)}
_BINDINGS = {"ticket.side_buy": "Ctrl+B", "replay.step_bar_back": "←", "dom.recentre": ""}
_FIELDS = HotkeyProfileFields("Scalping", _BINDINGS)


def _mapping(version: int = 1, *, active: bool = False, stored: Any = None) -> dict[str, object]:
    """A row as asyncpg answers it: `jsonb` as its text."""
    bindings = json.dumps(_BINDINGS) if stored is None else stored
    return {"id": str(_ID), "owner_user_id": str(_OWNER), "name": "Scalping",
            "is_active": active, "bindings": bindings, "version": version, "created_at": _T,
            "updated_at": _T}  # fmt: skip


def _row(version: int = 1, *, active: bool = False) -> HotkeyProfileRow:
    return HotkeyProfileRow(_ID, _OWNER, "Scalping", active, _BINDINGS, version, _T, _T)


class _Result:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def __iter__(self) -> Any:
        return iter(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def one(self) -> Any:
        (row,) = self._rows
        return row

    def scalar_one(self) -> object:
        ((value,),) = (tuple(row.values()) for row in self._rows)
        return value


class _Uow:
    """One unit of work: each `execute` answers the script's next rows (or raises its error)."""

    def __init__(self, script: list[Any], log: list[str], params: list[dict[str, Any]]) -> None:
        self.script, self.log, self.params, self.session = script, log, params, self

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.log.append("exit")

    async def execute(self, stmt: sa.TextClause, params: dict[str, Any]) -> _Result:
        self.log.append(next(n for n, s in _STATEMENTS.items() if s is stmt))
        assert params["owner"] == str(_OWNER)  # every statement is bound to the owner
        self.params.append(params)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return _Result(step)

    async def commit(self) -> None:
        self.log.append("commit")


class _Rel:
    def __init__(self, *script: Any) -> None:
        self.script, self.log, self.params = list(script), list[str](), list[dict[str, Any]]()

    def unit_of_work(self) -> _Uow:
        return _Uow(self.script, self.log, self.params)


def _store(*script: Any) -> tuple[mod.SqlAlchemyHotkeyProfileStore, _Rel]:
    rel = _Rel(*script)
    return mod.SqlAlchemyHotkeyProfileStore(rel), rel  # type: ignore[arg-type]  # a stub UoW


async def _never(*_rows: object) -> None:
    raise AssertionError("no record may be written")


_LOCKED = [{"pg_advisory_xact_lock": None}]  # what the owner's lock answers


def test_every_statement_names_the_owner_and_repeats_the_columns() -> None:
    assert set(_STATEMENTS) == {
        "_LOCK_OWNER", "_LIST", "_GET", "_GET_ACTIVE", "_LOCK", "_COUNT", "_INSERT", "_REPLACE",
        "_REPLACE_AT", "_DEACTIVATE", "_ACTIVATE", "_DELETE", "_OTHER_OWNER",
    }  # fmt: skip
    no_columns = {"_LOCK_OWNER", "_COUNT", "_DEACTIVATE", "_DELETE", *mod.UNSCOPED}
    for name, stmt in _STATEMENTS.items():
        text = str(stmt)
        assert "CAST(:owner AS uuid)" in text or name == "_LOCK_OWNER", name
        assert (mod.COLUMNS in text) is (name not in no_columns), name
    assert "hashtextextended('cv.hotkey_profiles:' || CAST(:owner AS text), 0)" in str(
        _STATEMENTS["_LOCK_OWNER"]
    )
    assert str(_STATEMENTS["_LOCK"]).endswith(" FOR UPDATE")


def test_a_replace_naming_a_version_is_guarded_by_it_and_activation_keeps_the_version() -> None:
    """21 Sec.3.8.5: of two writers holding one version exactly one wins; one with no version is
    last-write-wins; activation changes neither `version` nor `updated_at`."""
    guarded, plain = str(_STATEMENTS["_REPLACE_AT"]), str(_STATEMENTS["_REPLACE"])
    assert "owner_user_id = CAST(:owner AS uuid) AND version = :expected RETURNING" in guarded
    assert "version = version + 1, updated_at = now()" in guarded
    assert plain == guarded.replace(" AND version = :expected", "")
    for name in ("_DEACTIVATE", "_ACTIVATE"):
        assert "version" not in str(_STATEMENTS[name]).split("RETURNING")[0], name
        assert "updated_at" not in str(_STATEMENTS[name]).split("RETURNING")[0], name
    assert str(_STATEMENTS["_DELETE"]).endswith("AND NOT is_active")


async def test_the_one_unscoped_statement_answers_another_owners_existence_alone() -> None:
    """For the router's `rbac.denied` record: whether another user holds the id, and no column."""
    assert mod.UNSCOPED == frozenset({"_OTHER_OWNER"})
    assert str(_STATEMENTS["_OTHER_OWNER"]) == (
        "SELECT EXISTS (SELECT 1 FROM hotkey_profiles WHERE id = CAST(:id AS uuid) "
        "AND owner_user_id <> CAST(:owner AS uuid))"
    )
    store, rel = _store([{"exists": True}], [{"exists": False}])
    assert await store.exists_for_other_owner(_OWNER, _ID) is True
    assert await store.exists_for_other_owner(_OWNER, _ID) is False
    assert rel.log == ["_OTHER_OWNER", "exit", "_OTHER_OWNER", "exit"]


async def test_reads_map_the_owners_rows() -> None:
    store, rel = _store([_mapping()], [_mapping()], [], [_mapping(active=True)], [])
    assert await store.list_own(_OWNER) == [_row()]
    assert await store.get_own(_OWNER, _ID) == _row()
    assert await store.get_own(_OWNER, _ID) is None
    assert await store.get_active(_OWNER) == _row(active=True)
    assert await store.get_active(_OWNER) is None
    assert rel.log == ["_LIST", "exit", "_GET", "exit", "_GET", "exit", "_GET_ACTIVE", "exit",
                       "_GET_ACTIVE", "exit"]  # fmt: skip


@pytest.mark.parametrize(
    ("stored", "read"),
    [
        (_BINDINGS, _BINDINGS),  # a driver that decodes jsonb itself
        (json.dumps({"a": "B", "b": 1, "c": None, "d": ["X"]}), {"a": "B"}),
        (json.dumps(["B"]), {}),
        ("null", {}),
    ],
)
async def test_bindings_are_read_as_their_string_members(stored: Any, read: dict[str, str]) -> None:
    store, _ = _store([_mapping(stored=stored)])
    found = await store.get_own(_OWNER, _ID)
    assert found is not None and found.bindings == read


async def test_create_counts_under_the_owners_lock_then_records_before_its_commit() -> None:
    store, rel = _store(_LOCKED, [{"count": MAX_PROFILES - 1}], [_mapping()])
    seen: list[tuple[object, ...]] = []

    async def ahead(*rows: object) -> None:
        seen.append(rows)
        rel.log.append("record")

    assert await store.create(_OWNER, _ID, _FIELDS, write_ahead=ahead) == _row()
    assert seen == [(None, _row())]
    assert rel.log == ["_LOCK_OWNER", "_COUNT", "_INSERT", "record", "commit", "exit"]
    inserted = rel.params[2]
    assert (inserted["id"], inserted["name"]) == (str(_ID), "Scalping")
    assert json.loads(inserted["bindings"]) == _BINDINGS and "←" in inserted["bindings"]


async def test_create_at_the_cap_inserts_nothing() -> None:
    store, rel = _store(_LOCKED, [{"count": MAX_PROFILES}])
    with pytest.raises(HotkeyProfileLimitError):
        await store.create(_OWNER, _ID, _FIELDS, write_ahead=_never)
    assert rel.log == ["_LOCK_OWNER", "_COUNT", "exit"]


async def test_a_replace_with_no_version_is_last_write_wins() -> None:
    store, rel = _store(_LOCKED, [_mapping(4)], [_mapping(5)])
    seen: list[tuple[object, ...]] = []

    async def ahead(*rows: object) -> None:
        seen.append(rows)
        rel.log.append("record")

    after = await store.replace(_OWNER, _ID, _FIELDS, expected_version=None, write_ahead=ahead)
    assert after == _row(5) and seen == [(_row(4), _row(5))]
    assert rel.log == ["_LOCK_OWNER", "_LOCK", "_REPLACE", "record", "commit", "exit"]
    assert "expected" not in rel.params[2]


async def test_a_replace_naming_a_version_writes_only_at_that_version() -> None:
    store, rel = _store(
        _LOCKED, [_mapping(1)], [_mapping(2)],  # applied
        _LOCKED, [],  # no such profile
        _LOCKED, [_mapping(2)],  # another version held
        _LOCKED, [_mapping(1)], [],  # the guarded UPDATE matched no row
    )  # fmt: skip
    seen: list[tuple[object, ...]] = []

    async def ahead(*rows: object) -> None:
        seen.append(rows)

    assert await store.replace(_OWNER, _ID, _FIELDS, expected_version=1, write_ahead=ahead) == (
        _row(2))  # fmt: skip
    assert rel.params[2]["expected"] == 1 and seen == [(_row(1), _row(2))]
    with pytest.raises(HotkeyProfileNotFoundError):
        await store.replace(_OWNER, _ID, _FIELDS, expected_version=1, write_ahead=_never)
    for current in (2, 1):  # compared under the lock, then the UPDATE's own guard
        with pytest.raises(HotkeyProfileStaleError) as stale:
            await store.replace(_OWNER, _ID, _FIELDS, expected_version=1, write_ahead=_never)
        assert stale.value.version == current
    assert rel.log.count("commit") == 1 and rel.log.count("_REPLACE_AT") == 2


async def test_activating_deactivates_the_other_first_and_records_its_id() -> None:
    store, rel = _store(
        _LOCKED, [_mapping()], [{"id": str(_OTHER)}], [_mapping(active=True)],
        _LOCKED, [_mapping()], [], [_mapping(active=True)],
    )  # fmt: skip
    seen: list[tuple[object, ...]] = []

    async def ahead(*rows: object) -> None:
        seen.append(rows)
        rel.log.append("record")

    assert await store.activate(_OWNER, _ID, write_ahead=ahead) == _row(active=True)
    assert await store.activate(_OWNER, _ID, write_ahead=ahead) == _row(active=True)
    assert seen == [(_row(), _row(active=True), _OTHER), (_row(), _row(active=True), None)]
    once = ["_LOCK_OWNER", "_LOCK", "_DEACTIVATE", "_ACTIVATE", "record", "commit", "exit"]
    assert rel.log == once + once


async def test_activating_the_active_profile_or_none_writes_nothing() -> None:
    store, rel = _store(_LOCKED, [_mapping(active=True)], _LOCKED, [])
    assert await store.activate(_OWNER, _ID, write_ahead=_never) == _row(active=True)
    with pytest.raises(HotkeyProfileNotFoundError):
        await store.activate(_OWNER, _ID, write_ahead=_never)
    assert rel.log == ["_LOCK_OWNER", "_LOCK", "exit", "_LOCK_OWNER", "_LOCK", "exit"]


async def test_a_delete_removes_an_inactive_profile_and_refuses_the_active_one() -> None:
    store, rel = _store(
        _LOCKED, [_mapping()], [],
        _LOCKED, [_mapping(active=True)],
        _LOCKED, [],
    )  # fmt: skip
    seen: list[tuple[object, ...]] = []

    async def ahead(*rows: object) -> None:
        seen.append(rows)
        rel.log.append("record")

    assert await store.delete(_OWNER, _ID, write_ahead=ahead) == _row()
    assert seen == [(_row(), None)]
    with pytest.raises(HotkeyProfileActiveError):
        await store.delete(_OWNER, _ID, write_ahead=_never)
    with pytest.raises(HotkeyProfileNotFoundError):
        await store.delete(_OWNER, _ID, write_ahead=_never)
    assert rel.log == ["_LOCK_OWNER", "_LOCK", "_DELETE", "record", "commit", "exit",
                       "_LOCK_OWNER", "_LOCK", "exit", "_LOCK_OWNER", "_LOCK", "exit"]  # fmt: skip


async def test_a_refused_record_commits_nothing() -> None:
    class Refused(Exception):
        pass

    async def refused(*_rows: object) -> None:
        raise Refused

    store, rel = _store(
        _LOCKED, [{"count": 0}], [_mapping()],
        _LOCKED, [_mapping()], [_mapping(2)],
        _LOCKED, [_mapping()], [], [_mapping(active=True)],
        _LOCKED, [_mapping()], [],
    )  # fmt: skip
    with pytest.raises(Refused):
        await store.create(_OWNER, _ID, _FIELDS, write_ahead=refused)
    with pytest.raises(Refused):
        await store.replace(_OWNER, _ID, _FIELDS, expected_version=None, write_ahead=refused)
    with pytest.raises(Refused):
        await store.activate(_OWNER, _ID, write_ahead=refused)
    with pytest.raises(Refused):
        await store.delete(_OWNER, _ID, write_ahead=refused)
    assert "commit" not in rel.log


class _Orig(Exception):
    def __init__(self, sqlstate: str, constraint: str) -> None:
        super().__init__("Key (owner_user_id, lower(name))=(canary) already exists.")
        self.sqlstate, self.constraint_name = sqlstate, constraint


@pytest.mark.parametrize(
    ("state", "name", "raised"),
    [("23505", "ux_hk_name", HotkeyProfileNameTakenError),
     ("23505", "ux_hk_active", StorageConstraintViolated),
     ("23514", "hk_name_len", StorageConstraintViolated)],
)  # fmt: skip
async def test_an_integrity_error_maps_by_its_constraint_and_carries_no_value(
    state: str, name: str, raised: type[Exception]
) -> None:
    error = IntegrityError("s", {}, _Orig(state, name))
    store, rel = _store(_LOCKED, [{"count": 0}], error, _LOCKED, [_mapping()], error)
    with pytest.raises(raised) as create:
        await store.create(_OWNER, _ID, _FIELDS, write_ahead=_never)
    with pytest.raises(raised):
        await store.replace(_OWNER, _ID, _FIELDS, expected_version=None, write_ahead=_never)
    assert "canary" not in str(create.value) and "commit" not in rel.log
