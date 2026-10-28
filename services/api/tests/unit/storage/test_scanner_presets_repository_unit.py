"""Pure parts and fail-closed branches of the scanner-presets repository (E08-T09 PR 2a,
#4708): the owner filter in every statement, the error mapping, the one retry of a racing
default, and each method's statements against a stub unit of work.

Real-Postgres behaviour (the indexes, the cap under the owner lock, round trips) lives in
`tests/integration/storage/test_scanner_presets_repository.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.errors import StorageConstraintViolated
from candleviewer.storage.repositories import scanner_presets_sqlalchemy as mod
from candleviewer.storage.repositories.scanner_presets import (
    MAX_PRESETS,
    ExpectedDefault,
    ScannerPresetConflictError,
    ScannerPresetFields,
    ScannerPresetNotFoundError,
    ScannerPresetShapeError,
)

_T = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
_OWNER = "00000000-0000-4000-8000-00000000000a"
_ID = "00000000-0000-4000-8000-0000000000f1"
_STATEMENTS = {n: v for n, v in vars(mod).items() if isinstance(v, sa.TextClause)}
_TABLELESS = frozenset({"_LOCK_OWNER"})
_OTHER = "00000000-0000-4000-8000-0000000000f2"
_FORWARD = "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond')"


def _fields(name: str = "Fast", *, default: bool = False) -> ScannerPresetFields:
    return ScannerPresetFields(name, {"spread_bps": {"max": "2"}}, "spread_bps", default)


def _mapping(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": _ID, "user_id": _OWNER, "name": "Fast", "filter": '{"spread_bps": {"max": "2"}}',
        "sort": "spread_bps", "is_default": False, "version": 1, "created_at": _T,
        "updated_at": _T,
    }  # fmt: skip
    return row | over


def test_the_statement_set_is_pinned() -> None:
    assert set(_STATEMENTS) == {
        "_LOCK_OWNER", "_LIST", "_GET_OWN", "_GET_DEFAULT", "_IS_FOREIGN", "_OCCUPANCY",
        "_COUNT_OWN", "_OTHER_DEFAULT", "_CLEAR_DEFAULT", "_INSERT", "_UPDATE", "_DELETE",
    }  # fmt: skip


@pytest.mark.parametrize("name", sorted(set(_STATEMENTS) - mod.UNSCOPED - _TABLELESS))
def test_every_statement_filters_the_owner(name: str) -> None:
    text = str(_STATEMENTS[name])
    if name == "_INSERT":  # no WHERE: the owner is a bound value
        assert "CAST(:id AS uuid), CAST(:owner AS uuid), :name" in text
    else:
        assert "user_id = CAST(:owner AS uuid)" in text


def test_the_one_unscoped_statement_returns_no_row_data() -> None:
    assert mod.UNSCOPED == {"_IS_FOREIGN"}
    assert str(mod._IS_FOREIGN).startswith("SELECT 1 FROM scanner_presets WHERE")


def test_reads_use_the_explicit_column_list_and_names_compare_with_postgres_lower() -> None:
    for name in ("_LIST", "_GET_OWN", "_GET_DEFAULT", "_CLEAR_DEFAULT", "_INSERT", "_UPDATE"):
        assert mod.PRESET_COLUMNS in str(_STATEMENTS[name]), name
    assert "lower(name) = lower(CAST(:name AS text))" in str(mod._OCCUPANCY)
    assert "ORDER BY lower(name), id" in str(mod._LIST)


def test_every_write_raises_version_and_moves_updated_at_forward() -> None:
    for name in ("_CLEAR_DEFAULT", "_UPDATE"):
        text = str(_STATEMENTS[name])
        assert "version = version + 1" in text
        assert _FORWARD in text


class _Result:
    def __init__(self, rows: list[dict[str, object]], scalar: object = None) -> None:
        self._rows, self._scalar, self.rowcount = rows, scalar, len(rows)

    def mappings(self) -> _Result:
        return self

    def first(self) -> dict[str, object] | None:
        return self._rows[0] if self._rows else None

    def one(self) -> dict[str, object]:
        return self._rows[0]

    def all(self) -> list[dict[str, object]]:
        return self._rows

    def __iter__(self) -> Any:
        return iter(self._rows)

    def scalar_one(self) -> object:
        return self._scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar


class _Session:
    def __init__(self, answer: Callable[[str, dict[str, Any]], _Result]) -> None:
        self.answer = answer
        self.seen: list[str] = []

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _Result:
        name = next(n for n, v in _STATEMENTS.items() if v is stmt)
        self.seen.append(name)
        return self.answer(name, params or {})


class _Uow:
    def __init__(self, session: _Session) -> None:
        self.session, self.committed = session, 0

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed += 1


class _Relational:
    def __init__(self, answer: Callable[[str, dict[str, Any]], _Result]) -> None:
        self.session, self.uows = _Session(answer), 0

    def unit_of_work(self) -> _Uow:
        self.uows += 1
        return _Uow(self.session)


def _repo(answer: Callable[[str, dict[str, Any]], _Result]) -> tuple[Any, _Relational]:
    rel = _Relational(answer)
    return mod.SqlAlchemyScannerPresetRepository(rel), rel  # type: ignore[arg-type]  # the stub


def _integrity(constraint: str, state: str = "23505") -> IntegrityError:
    class _Orig(Exception):
        sqlstate = state
        constraint_name = constraint

    return IntegrityError("INSERT ...", {}, _Orig())


async def test_create_locks_the_owner_counts_clears_the_default_and_inserts() -> None:
    def answer(name: str, _p: dict[str, Any]) -> _Result:
        if name == "_COUNT_OWN":
            return _Result([], 3)
        if name == "_OTHER_DEFAULT":
            return _Result([{"id": _OTHER, "version": 3}])
        if name == "_CLEAR_DEFAULT":
            return _Result([_mapping(id=_OTHER, version=4)])
        return _Result([_mapping(is_default=True)])

    repo, rel = _repo(answer)
    got = await repo.create(_OWNER, _ID, _fields(default=True),
                            expected_default=ExpectedDefault(_OTHER, 3))  # fmt: skip
    assert rel.session.seen == ["_LOCK_OWNER", "_COUNT_OWN", "_OTHER_DEFAULT", "_CLEAR_DEFAULT",
                                "_INSERT"]  # fmt: skip
    assert got.row.filter == {"spread_bps": {"max": "2"}} and got.row.is_default
    assert got.cleared is not None and got.cleared.version == 4


def test_the_clear_is_keyed_on_the_expected_default_and_its_version() -> None:
    """S-1/S-2 (round 1): the clear touches only the row, at the version, its record names."""
    text = str(mod._CLEAR_DEFAULT)
    assert "id = CAST(:expected AS uuid)" in text
    assert "version = CAST(:expected_version AS integer)" in text


async def test_a_default_at_another_version_than_its_record_is_conflict_before_any_write() -> None:
    """S-2 (round 1): the owner changed the default after its record was written."""

    def answer(name: str, _p: dict[str, Any]) -> _Result:
        if name == "_OTHER_DEFAULT":
            return _Result([{"id": _OTHER, "version": 4}])
        return _Result([], 0)

    repo, rel = _repo(answer)
    with pytest.raises(ScannerPresetConflictError) as err:
        await repo.create(_OWNER, _ID, _fields(default=True),
                          expected_default=ExpectedDefault(_OTHER, 3))  # fmt: skip
    assert err.value.rule == "conflict"
    assert "_CLEAR_DEFAULT" not in rel.session.seen and "_INSERT" not in rel.session.seen


async def test_a_clear_that_touches_no_row_is_conflict_not_a_500() -> None:
    """S-1 (round 1): the default went between the read and the clear."""

    def answer(name: str, _p: dict[str, Any]) -> _Result:
        if name == "_OTHER_DEFAULT":
            return _Result([{"id": _OTHER, "version": 3}])
        return _Result([], 0)

    repo, rel = _repo(answer)
    with pytest.raises(ScannerPresetConflictError) as err:
        await repo.update(_OWNER, _ID, _fields(default=True),
                          expected_default=ExpectedDefault(_OTHER, 3))  # fmt: skip
    assert err.value.rule == "conflict" and "_UPDATE" not in rel.session.seen


async def test_create_at_the_cap_is_limit_reached_and_inserts_nothing() -> None:
    repo, rel = _repo(lambda n, _p: _Result([], MAX_PRESETS))
    with pytest.raises(ScannerPresetConflictError) as err:
        await repo.create(_OWNER, _ID, _fields())
    assert err.value.rule == "limit_reached" and "_INSERT" not in rel.session.seen


async def test_a_default_other_than_the_expected_one_is_conflict_before_any_write() -> None:
    def answer(name: str, _p: dict[str, Any]) -> _Result:
        if name == "_OTHER_DEFAULT":
            return _Result([{"id": "00000000-0000-4000-8000-0000000000f9", "version": 1}])
        return _Result([], 0)

    repo, rel = _repo(answer)
    with pytest.raises(ScannerPresetConflictError) as err:
        await repo.create(_OWNER, _ID, _fields(default=True), expected_default=None)
    assert err.value.rule == "conflict"
    assert "_CLEAR_DEFAULT" not in rel.session.seen and "_INSERT" not in rel.session.seen


async def test_a_racing_default_is_retried_once_then_answered_conflict() -> None:
    def answer(name: str, _p: dict[str, Any]) -> _Result:
        if name == "_INSERT":
            raise _integrity("ux_sp_default")
        return _Result([], 0 if name == "_COUNT_OWN" else None)

    repo, rel = _repo(answer)
    with pytest.raises(ScannerPresetConflictError) as err:
        await repo.create(_OWNER, _ID, _fields(default=True))
    assert err.value.rule == "conflict" and rel.session.seen.count("_INSERT") == 2


async def test_a_racing_default_that_clears_on_the_retry_succeeds() -> None:
    tries: list[int] = []

    def answer(name: str, _p: dict[str, Any]) -> _Result:
        if name == "_INSERT":
            tries.append(1)
            if len(tries) == 1:
                raise _integrity("ux_sp_default")
            return _Result([_mapping()])
        return _Result([], 0 if name == "_COUNT_OWN" else None)

    repo, _ = _repo(answer)
    assert (await repo.create(_OWNER, _ID, _fields(default=True))).row.id == _ID


@pytest.mark.parametrize(
    ("constraint", "state", "expected"),
    [("ux_sp_name", "23505", ScannerPresetConflictError),
     ("sp_filter_shape", "23514", ScannerPresetShapeError),
     ("sp_name_len", "23514", StorageConstraintViolated)],
)  # fmt: skip
async def test_integrity_errors_map_to_the_refusals_the_api_answers(
    constraint: str, state: str, expected: type[Exception]
) -> None:
    def answer(name: str, _p: dict[str, Any]) -> _Result:
        if name == "_UPDATE":
            raise _integrity(constraint, state)
        return _Result([], None)

    repo, _ = _repo(answer)
    with pytest.raises(expected) as err:
        await repo.update(_OWNER, _ID, _fields())
    if expected is ScannerPresetConflictError:
        assert err.value.rule == "name_taken" and err.value.field == "name"  # type: ignore[attr-defined]  # narrowed by the case


async def test_update_of_a_row_that_is_gone_is_not_found() -> None:
    repo, _ = _repo(lambda n, _p: _Result([], None))
    with pytest.raises(ScannerPresetNotFoundError):
        await repo.update(_OWNER, _ID, _fields())


async def test_update_that_keeps_no_default_never_touches_another_row() -> None:
    repo, rel = _repo(lambda n, _p: _Result([_mapping(version=2)]))
    got = await repo.update(_OWNER, _ID, _fields())
    assert rel.session.seen == ["_LOCK_OWNER", "_UPDATE"] and got.cleared is None


async def test_delete_reports_whether_a_row_went() -> None:
    repo, rel = _repo(lambda n, _p: _Result([{"id": _ID}]))
    assert await repo.delete(_OWNER, _ID) is True
    assert rel.session.seen == ["_LOCK_OWNER", "_DELETE"]  # S-1 (round 1): every write locks
    repo, _ = _repo(lambda n, _p: _Result([]))
    assert await repo.delete(_OWNER, _ID) is False


async def test_reads_decode_the_stored_filter_and_occupancy_reads_both_values() -> None:
    def answer(name: str, _p: dict[str, Any]) -> _Result:
        if name == "_OCCUPANCY":
            return _Result([{"n": 7, "taken": True}])
        if name == "_IS_FOREIGN":
            return _Result([], 1)
        return _Result([_mapping()])

    repo, _ = _repo(answer)
    (row,) = await repo.list_own(_OWNER)
    assert row.filter == {"spread_bps": {"max": "2"}}
    assert (await repo.get_own(_OWNER, _ID)) == row
    assert (await repo.get_default(_OWNER)) == row
    assert await repo.occupancy(_OWNER, "fast", exclude_id=_ID) == (7, True)
    assert await repo.is_foreign(_OWNER, _ID) is True
