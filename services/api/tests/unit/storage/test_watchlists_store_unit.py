"""The watchlists store without a database (E08-T07, #4706): every statement names the owner and
repeats the column list, the replace is guarded by the version, and each method runs its
statements in order against a stub unit of work, its record after its statement and before the
commit, nothing committed when it is refused. Real Postgres: tests/integration/storage/ (CI only).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.errors import StorageConstraintViolated
from candleviewer.storage.repositories import watchlists_sqlalchemy as mod
from candleviewer.storage.repositories.watchlists import (
    WatchlistFields,
    WatchlistNameTakenError,
    WatchlistNotFoundError,
    WatchlistRow,
    WatchlistStaleError,
)

_T = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
_OWNER, _ID = uuid.UUID(int=10), uuid.UUID(int=1)
_STATEMENTS = {n: v for n, v in vars(mod).items() if isinstance(v, sa.TextClause)}
_FIELDS = WatchlistFields("Majors", ("BTCUSDT",), ())


def _mapping(version: int = 1) -> dict[str, object]:
    return {"id": str(_ID), "user_id": str(_OWNER), "name": "Majors", "symbols": ["BTCUSDT"],
            "columns": [], "version": version, "created_at": _T, "updated_at": _T}  # fmt: skip


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

    def __init__(self, script: list[Any], log: list[str]) -> None:
        self.script, self.log, self.session = script, log, self

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.log.append("exit")

    async def execute(self, stmt: sa.TextClause, params: dict[str, Any]) -> _Result:
        self.log.append(next(n for n, s in _STATEMENTS.items() if s is stmt))
        assert params["owner"] == str(_OWNER)  # every statement is bound to the owner
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return _Result(step)

    async def commit(self) -> None:
        self.log.append("commit")


class _Rel:
    def __init__(self, *script: Any) -> None:
        self.script, self.log = list(script), list[str]()

    def unit_of_work(self) -> _Uow:
        return _Uow(self.script, self.log)


def _store(*script: Any) -> tuple[mod.SqlAlchemyWatchlistStore, list[str]]:
    rel = _Rel(*script)
    return mod.SqlAlchemyWatchlistStore(rel), rel.log  # type: ignore[arg-type]  # a stub UoW


async def _never(_before: WatchlistRow | None, _after: WatchlistRow | None) -> None:
    raise AssertionError("no record may be written")


def test_every_statement_names_the_owner_and_the_replace_is_guarded_by_the_version() -> None:
    assert set(_STATEMENTS) == {
        "_LIST", "_GET", "_LOCK", "_INSERT", "_REPLACE", "_DELETE", "_OTHER_OWNER",
    }  # fmt: skip
    for name, stmt in _STATEMENTS.items():
        assert "CAST(:owner AS uuid)" in str(stmt), name
        assert (mod.COLUMNS in str(stmt)) is (name not in mod.UNSCOPED), name
    replace = str(_STATEMENTS["_REPLACE"])
    assert "version = version + 1" in replace
    assert "user_id = CAST(:owner AS uuid) AND version = :expected RETURNING" in replace
    assert str(_STATEMENTS["_LOCK"]).endswith(" FOR UPDATE")


async def test_the_one_unscoped_statement_answers_another_owners_existence_alone() -> None:
    """For the router's `rbac.denied` record: whether another user holds the id, and no column."""
    assert mod.UNSCOPED == frozenset({"_OTHER_OWNER"})
    assert str(_STATEMENTS["_OTHER_OWNER"]) == (
        "SELECT EXISTS (SELECT 1 FROM watchlists WHERE id = CAST(:id AS uuid) "
        "AND user_id <> CAST(:owner AS uuid))"
    )
    store, log = _store([{"exists": True}], [{"exists": False}])
    assert await store.exists_for_other_owner(_OWNER, _ID) is True
    assert await store.exists_for_other_owner(_OWNER, _ID) is False
    assert log == ["_OTHER_OWNER", "exit", "_OTHER_OWNER", "exit"]


async def test_reads_map_the_owners_rows() -> None:
    store, log = _store([_mapping()], [_mapping()], [])
    (row,) = await store.list_own(_OWNER)
    assert row == WatchlistRow(_ID, _OWNER, "Majors", ("BTCUSDT",), (), 1, _T, _T)
    assert await store.get_own(_OWNER, _ID) == row
    assert await store.get_own(_OWNER, _ID) is None
    assert log == ["_LIST", "exit", "_GET", "exit", "_GET", "exit"]


async def test_each_write_records_after_its_statement_and_before_its_commit() -> None:
    store, log = _store([_mapping()], [_mapping()], [_mapping(2)], [_mapping(2)])
    seen: list[tuple[WatchlistRow | None, WatchlistRow | None]] = []

    async def ahead(before: WatchlistRow | None, after: WatchlistRow | None) -> None:
        seen.append((before, after))
        log.append("record")

    created = await store.create(_OWNER, _ID, _FIELDS, write_ahead=ahead)
    replaced = await store.replace(_OWNER, _ID, _FIELDS, expected_version=1, write_ahead=ahead)
    assert await store.delete(_OWNER, _ID, write_ahead=ahead) == replaced
    assert seen == [(None, created), (created, replaced), (replaced, None)]
    assert log == ["_INSERT", "record", "commit", "exit", "_LOCK", "_REPLACE", "record", "commit",
                   "exit", "_DELETE", "record", "commit", "exit"]  # fmt: skip


async def test_a_replace_writes_only_the_owners_list_at_the_named_version() -> None:
    store, log = _store([], [_mapping(2)], [_mapping(2)], [_mapping(1)], [])
    with pytest.raises(WatchlistNotFoundError):
        await store.replace(_OWNER, _ID, _FIELDS, expected_version=1, write_ahead=_never)
    for expected in (1, None):
        with pytest.raises(WatchlistStaleError) as stale:
            await store.replace(_OWNER, _ID, _FIELDS, expected_version=expected, write_ahead=_never)
        assert stale.value.version == 2
    with pytest.raises(WatchlistStaleError):  # the guarded UPDATE matched no row
        await store.replace(_OWNER, _ID, _FIELDS, expected_version=1, write_ahead=_never)
    assert "commit" not in log and log.count("_REPLACE") == 1


async def test_deleting_no_list_is_not_found_and_commits_nothing() -> None:
    store, log = _store([])
    with pytest.raises(WatchlistNotFoundError):
        await store.delete(_OWNER, _ID, write_ahead=_never)
    assert log == ["_DELETE", "exit"]


class _Orig(Exception):
    def __init__(self, sqlstate: str, constraint: str) -> None:
        super().__init__("Key (user_id, lower(name))=(canary) already exists.")
        self.sqlstate, self.constraint_name = sqlstate, constraint


@pytest.mark.parametrize(
    ("state", "name", "raised"),
    [("23505", "ux_wl_name", WatchlistNameTakenError),
     ("23505", "watchlists_pkey", StorageConstraintViolated),
     ("23514", "wl_symbols_max", StorageConstraintViolated)],
)  # fmt: skip
async def test_an_integrity_error_maps_by_its_constraint_and_carries_no_value(
    state: str, name: str, raised: type[Exception]
) -> None:
    error = IntegrityError("s", {}, _Orig(state, name))
    store, log = _store(error, [_mapping()], error)
    with pytest.raises(raised) as create:
        await store.create(_OWNER, _ID, _FIELDS, write_ahead=_never)
    with pytest.raises(raised):
        await store.replace(_OWNER, _ID, _FIELDS, expected_version=1, write_ahead=_never)
    assert "canary" not in str(create.value) and "commit" not in log
