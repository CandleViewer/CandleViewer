"""Pure parts and fail-closed branches of the indicator-presets repository (E13-T03, #427): the
owner filter in every statement, no hard delete, the error mapping, and each method's
statements against a stub unit of work (the drawings unit test's pattern).

Real-Postgres behaviour (the cap race, `ux_ip_name`, round trips) lives in
`tests/integration/storage/test_indicator_presets_repository.py` (CI only).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.repositories import indicator_presets_sqlalchemy as mod
from candleviewer.storage.repositories.indicator_presets import (
    MAX_IMPORT_PRESETS,
    MAX_LIVE_PRESETS,
    NAME_MAX,
    PresetConflictError,
    PresetFields,
    PresetNotFoundError,
    PresetRow,
    PresetShapeError,
    name_candidates,
)

_T = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
_OWNER = "00000000-0000-4000-8000-00000000000a"
_STATEMENTS = {n: v for n, v in vars(mod).items() if isinstance(v, sa.TextClause)}
_WRITES = ("_INSERT", "_UPDATE", "_SOFT_DELETE")
#: Statements that read no table: the owner lock and Postgres's own `lower()` of given names.
_TABLELESS = frozenset({"_LOCK_OWNER", "_FOLD"})


def _fields(name: str = "Fast", code: str = "ema") -> PresetFields:
    return PresetFields(code, name, {"n": 9}, {}, "overlay", False)


def _mapping(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "p1", "owner_user_id": _OWNER, "indicator_code": "ema", "name": "Fast",
        "params": '{"n": 9}', "style": "{}", "pane_target": "overlay", "is_builtin": False,
        "is_favourite": False, "created_at": _T, "updated_at": _T,
    }  # fmt: skip
    return row | over


# --- statements -----------------------------------------------------------------------------


def test_the_statement_set_is_pinned() -> None:
    assert set(_STATEMENTS) == {
        "_LOCK_OWNER", "_LIST", "_GET_OWN", "_OTHER_CLASS", "_OCCUPANCY", "_COUNT_OWN",
        "_NAMES_OWN", "_FOLD", "_INSERT", "_UPDATE", "_SOFT_DELETE", "_COUNT_LIVE",
    }  # fmt: skip


@pytest.mark.parametrize("name", sorted(set(_STATEMENTS) - mod.UNSCOPED - _TABLELESS))
def test_every_write_statement_filters_owner(name: str) -> None:
    """IR-01/SR-051: the owner filter is part of each statement itself, never added later."""
    text = str(_STATEMENTS[name])
    if name == "_INSERT":  # no WHERE: the owner is a bound value and is_builtin a literal false
        assert "CAST(:owner AS uuid), :indicator_code" in text and ", false, :is_favourite" in text
    elif name == "_LIST":  # reads: the caller's rows and the built-ins
        assert "AND (owner_user_id = CAST(:owner AS uuid) OR owner_user_id IS NULL)" in text
    else:  # the caller's own rows, never a built-in
        assert "owner_user_id = CAST(:owner AS uuid) AND NOT is_builtin" in text


@pytest.mark.parametrize("name", sorted(_TABLELESS))
def test_the_owner_lock_and_the_fold_read_no_table(name: str) -> None:
    assert "FROM indicator_presets" not in str(_STATEMENTS[name])


def test_import_keys_are_postgres_lower_as_ux_ip_name_folds_them() -> None:
    """The keys an import compares are `lower()` in Postgres, the expression `ux_ip_name`
    indexes, of the stored names and of every name it may give; never Python's `str.lower`."""
    names = str(_STATEMENTS["_NAMES_OWN"])
    assert names.startswith("SELECT indicator_code, lower(name) AS name_key FROM indicator_presets")
    fold = str(_STATEMENTS["_FOLD"])
    assert fold.startswith("SELECT lower(n) AS name_key FROM unnest(CAST(:names AS text[]))")
    assert fold.endswith(" WITH ORDINALITY AS c(n, i) ORDER BY i")
    assert ".lower()" not in inspect.getsource(mod)


def test_only_two_statements_are_unscoped_and_they_return_no_row_data() -> None:
    assert mod.UNSCOPED == frozenset({"_OTHER_CLASS", "_COUNT_LIVE"})
    assert str(_STATEMENTS["_OTHER_CLASS"]).startswith("SELECT is_builtin FROM")
    assert str(_STATEMENTS["_COUNT_LIVE"]).startswith("SELECT is_builtin, count(*) AS n FROM")


def test_repository_sql_never_issues_delete_from() -> None:
    """A5: deletion is reversible at the data layer; nothing in the module hard-deletes."""
    source = inspect.getsource(mod)
    assert "DELETE FROM" not in source.upper()
    assert all(not str(s).upper().startswith("DELETE") for s in _STATEMENTS.values())


@pytest.mark.parametrize("name", ["_LIST", "_GET_OWN", "_INSERT", "_UPDATE"])
def test_literal_column_lists_match_the_allow_list(name: str) -> None:
    assert mod.PRESET_COLUMNS in " ".join(str(_STATEMENTS[name]).split())
    assert "deleted_at AS" not in str(_STATEMENTS[name])


@pytest.mark.parametrize("name", ["_UPDATE", "_SOFT_DELETE"])
def test_updates_bump_the_token_monotonically(name: str) -> None:
    text = str(_STATEMENTS[name])
    assert "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond')" in text


def test_update_never_writes_the_code_or_the_server_managed_columns() -> None:
    set_clause = str(_STATEMENTS["_UPDATE"]).split(" WHERE ", 1)[0]
    for column in ("indicator_code =", "owner_user_id =", "is_builtin =", "id =", "created_at ="):
        assert column not in set_clause, column


def test_list_orders_builtins_first_then_code_name_and_id() -> None:
    text = str(_STATEMENTS["_LIST"])
    assert text.endswith("ORDER BY is_builtin DESC, indicator_code, lower(name), id")
    assert "deleted_at IS NULL" in text


def test_the_cap_lock_is_per_owner_and_transaction_scoped() -> None:
    text = str(_STATEMENTS["_LOCK_OWNER"])
    assert "pg_advisory_xact_lock(hashtextextended('cv.indicator_presets:' ||" in text


def test_soft_delete_sets_deleted_at_and_keeps_the_row() -> None:
    text = str(_STATEMENTS["_SOFT_DELETE"])
    assert text.startswith("UPDATE indicator_presets SET deleted_at = clock_timestamp()")


# --- error mapping ----------------------------------------------------------------------------


class _Orig(Exception):
    def __init__(self, sqlstate: str, constraint: str | None) -> None:
        super().__init__("boom")
        self.sqlstate = sqlstate
        self.constraint_name = constraint


def _err(state: str, name: str | None) -> IntegrityError:
    return IntegrityError("s", {}, _Orig(state, name))


def test_ux_ip_name_violation_maps_to_name_taken_on_the_name_field() -> None:
    got = mod.map_integrity(_err("23505", "ux_ip_name"))
    assert isinstance(got, PresetConflictError) and (got.rule, got.field) == ("name_taken", "name")


@pytest.mark.parametrize(
    ("name", "field"), [("ip_params_shape", "params"), ("ip_style_shape", "style")]
)
def test_a_json_shape_check_maps_to_a_shape_error(name: str, field: str) -> None:
    got = mod.map_integrity(_err("23514", name))
    assert isinstance(got, PresetShapeError) and got.field == field


@pytest.mark.parametrize(
    ("state", "name"),
    [("23505", "indicator_presets_pkey"), ("23514", "ip_code"), ("23503", "ux_ip_name"),
     ("23505", None)],
)  # fmt: skip
def test_any_other_integrity_error_is_not_mapped(state: str, name: str | None) -> None:
    assert mod.map_integrity(_err(state, name)) is None


def test_the_constraint_is_read_from_the_driver_exception_cause() -> None:
    class _Driver(Exception):
        constraint_name = "ux_ip_name"

    class _Wrapper(Exception):
        sqlstate = "23505"

    wrapper = _Wrapper("dup")
    wrapper.__cause__ = _Driver()
    assert isinstance(mod.map_integrity(IntegrityError("s", {}, wrapper)), PresetConflictError)


def test_limit_reached_has_no_field() -> None:
    err = PresetConflictError("limit_reached")
    assert (err.rule, err.field) == ("limit_reached", None)


# --- name_candidates (bundle import) -----------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "count", "expected"),
    [
        ("Fast", 1, ["Fast"]),
        ("Fast", 3, ["Fast", "Fast (2)", "Fast (3)"]),
        ("x" * 80, 2, ["x" * 80, "x" * 76 + " (2)"]),
        ("a" * 74 + "     b", 2, ["a" * 74 + "     b", "a" * 74 + " (2)"]),  # the cut is trimmed
        ("y" * 76 + " (2)", 3, ["y" * 76 + " (2)"] * 2 + ["y" * 76 + " (3)"]),  # one repeat only
    ],
)
def test_name_candidates_are_the_name_then_its_suffixed_copies_within_80_characters(
    name: str, count: int, expected: list[str]
) -> None:
    got = name_candidates(name, count)
    assert got == expected and all(len(candidate) <= NAME_MAX for candidate in got)


# --- methods against a stub unit of work ------------------------------------------------------


class _Result:
    def __init__(self, rows: list[dict[str, object]], rowcount: int = 0) -> None:
        self._rows, self.rowcount = rows, rowcount

    def mappings(self) -> _Result:
        return self

    def __iter__(self) -> Any:
        return iter(self._rows)

    def all(self) -> list[Any]:
        return [tuple(r.values()) for r in self._rows]

    def one(self) -> dict[str, object]:
        (row,) = self._rows
        return row

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> object:
        (row,) = self._rows
        (value,) = row.values()
        return value

    def scalar_one_or_none(self) -> object:
        return self.scalar_one() if self._rows else None


class _Session:
    def __init__(self, script: list[_Result]) -> None:
        self._script = script
        self.executed: list[str] = []
        self.params: list[dict[str, Any]] = []

    async def execute(self, stmt: sa.TextClause, params: dict[str, Any] | None = None) -> _Result:
        name = next(n for n, s in _STATEMENTS.items() if s is stmt)
        self.executed.append(name)
        self.params.append(params or {})
        return self._script.pop(0)


#: LATIN CAPITAL LETTER I WITH DOT ABOVE, and the 'i' + COMBINING DOT ABOVE Python lowers it to.
_I_DOT, _I_COMBINING = "\u0130", "i\u0307"


def _pg_lower(text: str) -> str:
    """Postgres's `lower()` under a libc collation: one character at a time, the simple case
    mapping, so U+0130 folds onto 'i'; Python's `str.lower` gives 'i' plus U+0307."""
    return "".join("i" if ch == _I_DOT else ch.lower() for ch in text)


class _Folding(_Session):
    """`_FOLD` answered as Postgres would (`fold` of each name, in order); the rest scripted."""

    def __init__(self, script: list[_Result], fold: Callable[[str], str] = _pg_lower) -> None:
        super().__init__(script)
        self._fold = fold

    async def execute(self, stmt: sa.TextClause, params: dict[str, Any] | None = None) -> _Result:
        if stmt is not mod._FOLD:
            return await super().execute(stmt, params)
        self.executed.append("_FOLD")
        self.params.append(params or {})
        return _Result([{"name_key": self._fold(n)} for n in (params or {})["names"]])


class _Uow:
    def __init__(self, session: _Session) -> None:
        self.session, self.commits = session, 0

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class _Rel:
    def __init__(self, *script: _Result) -> None:
        self.uow = _Uow(_Folding(list(script)))

    def unit_of_work(self) -> _Uow:
        return self.uow


def _repo(*script: _Result) -> tuple[mod.SqlAlchemyIndicatorPresetRepository, _Uow]:
    rel = _Rel(*script)
    return mod.SqlAlchemyIndicatorPresetRepository(rel), rel.uow  # type: ignore[arg-type]  # stub UoW


def _count(n: int) -> _Result:
    return _Result([{"count": n}])


async def test_list_visible_decodes_json_text_and_keeps_builtins() -> None:
    builtin = _mapping(id="b", owner_user_id=None, is_builtin=True, params={"n": 9})
    repo, uow = _repo(_Result([builtin, _mapping()]))
    rows = await repo.list_visible(_OWNER)
    assert [r.id for r in rows] == ["b", "p1"] and rows[1].params == {"n": 9}
    assert rows[0].owner_user_id is None and rows[0].is_builtin
    assert (uow.session.executed, uow.session.params) == (["_LIST"], [{"owner": _OWNER}])


async def test_get_own_returns_the_row_or_none() -> None:
    repo, _ = _repo(_Result([_mapping()]), _Result([]))
    row = await repo.get_own(_OWNER, "p1")
    assert isinstance(row, PresetRow) and row.fields() == _fields()
    assert await repo.get_own(_OWNER, "p1") is None


@pytest.mark.parametrize(
    ("rows", "expected"),
    [([{"is_builtin": True}], "builtin"), ([{"is_builtin": False}], "foreign"), ([], None)],
)
async def test_other_class_tells_builtin_from_foreign_and_nothing_else(
    rows: list[dict[str, object]], expected: str | None
) -> None:
    repo, uow = _repo(_Result(rows))
    assert await repo.other_class(_OWNER, "p9") == expected
    assert uow.session.params == [{"id": "p9", "owner": _OWNER}]


async def test_occupancy_binds_the_name_key_or_nulls() -> None:
    repo, uow = _repo(_Result([{"live": 3, "taken": True}]), _Result([{"live": 0, "taken": False}]))
    got = await repo.occupancy(_OWNER, ("ema", "Fast"), exclude_id="p1")
    assert (got.live_presets, got.name_taken) == (3, True)
    assert (await repo.occupancy(_OWNER)).live_presets == 0
    assert uow.session.params == [
        {"owner": _OWNER, "code": "ema", "name": "Fast", "exclude": "p1"},
        {"owner": _OWNER, "code": None, "name": None, "exclude": None},
    ]


async def test_create_locks_counts_then_inserts_with_the_owner_bound() -> None:
    repo, uow = _repo(
        _Result([{"lock": None}]), _count(MAX_LIVE_PRESETS - 1), _Result([_mapping()])
    )
    row = await repo.create(_OWNER, "p1", _fields())
    assert row.id == "p1" and uow.commits == 1
    assert uow.session.executed == ["_LOCK_OWNER", "_COUNT_OWN", "_INSERT"]
    insert = uow.session.params[2]
    assert insert == {
        "id": "p1", "owner": _OWNER, "indicator_code": "ema", "name": "Fast",
        "params": '{"n":9}', "style": "{}", "pane_target": "overlay", "is_favourite": False,
    }  # fmt: skip


async def test_create_at_the_cap_is_limit_reached_and_inserts_nothing() -> None:
    repo, uow = _repo(_Result([{"lock": None}]), _count(MAX_LIVE_PRESETS))
    with pytest.raises(PresetConflictError) as err:
        await repo.create(_OWNER, "p1", _fields())
    assert err.value.rule == "limit_reached" and uow.commits == 0
    assert "_INSERT" not in uow.session.executed


async def test_create_maps_a_unique_violation_to_name_taken() -> None:
    class _Raising(_Session):
        async def execute(
            self, stmt: sa.TextClause, params: dict[str, Any] | None = None
        ) -> _Result:
            if stmt is mod._INSERT:
                raise _err("23505", "ux_ip_name")
            return await super().execute(stmt, params)

    rel = _Rel()
    rel.uow.session = _Raising([_Result([{"lock": None}]), _count(0)])
    repo = mod.SqlAlchemyIndicatorPresetRepository(rel)  # type: ignore[arg-type]  # stub UoW
    with pytest.raises(PresetConflictError) as err:
        await repo.create(_OWNER, "p1", _fields())
    assert err.value.rule == "name_taken" and rel.uow.commits == 0


async def test_create_reraises_an_unmapped_integrity_error() -> None:
    class _Raising(_Session):
        async def execute(
            self, stmt: sa.TextClause, params: dict[str, Any] | None = None
        ) -> _Result:
            raise _err("23505", "indicator_presets_pkey")

    rel = _Rel()
    rel.uow.session = _Raising([])
    repo = mod.SqlAlchemyIndicatorPresetRepository(rel)  # type: ignore[arg-type]  # stub UoW
    with pytest.raises(IntegrityError):
        await repo.create(_OWNER, "p1", _fields())


async def test_update_writes_everything_but_the_code_and_misses_are_not_found() -> None:
    repo, uow = _repo(_Result([_mapping(name="Slow")]), _Result([]))
    row = await repo.update(_OWNER, "p1", _fields("Slow"))
    assert row.name == "Slow" and uow.commits == 1
    assert "indicator_code" not in uow.session.params[0]
    with pytest.raises(PresetNotFoundError):
        await repo.update(_OWNER, "p1", _fields("Slow"))
    assert uow.commits == 1


async def test_update_maps_a_unique_violation_to_name_taken() -> None:
    class _Raising(_Session):
        async def execute(
            self, stmt: sa.TextClause, params: dict[str, Any] | None = None
        ) -> _Result:
            raise _err("23505", "ux_ip_name")

    rel = _Rel()
    rel.uow.session = _Raising([])
    repo = mod.SqlAlchemyIndicatorPresetRepository(rel)  # type: ignore[arg-type]  # stub UoW
    with pytest.raises(PresetConflictError):
        await repo.update(_OWNER, "p1", _fields())


@pytest.mark.parametrize(("rowcount", "expected"), [(1, True), (0, False)])
async def test_soft_delete_reports_whether_a_live_row_was_hit(
    rowcount: int, expected: bool
) -> None:
    repo, uow = _repo(_Result([], rowcount=rowcount))
    assert await repo.soft_delete(_OWNER, "p1") is expected
    assert uow.session.executed == ["_SOFT_DELETE"] and uow.commits == 1


async def test_import_many_refuses_more_than_the_cap_before_touching_the_database() -> None:
    repo, uow = _repo()
    items = [(str(n), _fields(str(n))) for n in range(MAX_IMPORT_PRESETS + 1)]
    with pytest.raises(ValueError, match="at most"):
        await repo.import_many(_OWNER, items)
    assert uow.session.executed == []
    assert await repo.import_many(_OWNER, []) == []


async def test_import_many_past_the_live_cap_is_limit_reached_and_inserts_nothing() -> None:
    repo, uow = _repo(_Result([{"lock": None}]), _count(MAX_LIVE_PRESETS - 1))
    with pytest.raises(PresetConflictError) as err:
        await repo.import_many(_OWNER, [("a", _fields("A")), ("b", _fields("B"))])
    assert err.value.rule == "limit_reached" and uow.commits == 0
    assert uow.session.executed == ["_LOCK_OWNER", "_COUNT_OWN"]


def _sent(uow: _Uow, statement: str) -> list[dict[str, Any]]:
    """The bound parameters of each `statement` executed, in order."""
    session = uow.session
    return [p for n, p in zip(session.executed, session.params, strict=True) if n == statement]


def _inserts(uow: _Uow) -> list[tuple[str, str, str]]:
    """(id, indicator_code, name) of each `_INSERT`, in order."""
    return [(p["id"], p["indicator_code"], p["name"]) for p in _sent(uow, "_INSERT")]


async def test_import_many_renames_collisions_with_stored_and_earlier_items_never_overwrites() -> (
    None
):
    stored = _Result(
        [{"indicator_code": "ema", "name_key": "fast"}, {"indicator_code": "sma", "name_key": "x"}]
    )
    inserted = [_Result([_mapping(id=i, name=n)]) for i, n in
                (("a", "Fast (2)"), ("b", "fast (3)"), ("c", "Slow"), ("d", "Fast"))]  # fmt: skip
    repo, uow = _repo(_Result([{"lock": None}]), _count(2), stored, *inserted)
    items = [("a", _fields("Fast")), ("b", _fields("fast")), ("c", _fields("Slow")),
             ("d", _fields("Fast", code="rsi"))]  # fmt: skip
    rows = await repo.import_many(_OWNER, items)
    assert [r.id for r in rows] == ["a", "b", "c", "d"] and uow.commits == 1
    assert _inserts(uow) == [("a", "ema", "Fast (2)"), ("b", "ema", "fast (3)"),
                             ("c", "ema", "Slow"), ("d", "rsi", "Fast")]  # fmt: skip
    assert uow.session.executed == [
        "_LOCK_OWNER", "_COUNT_OWN", "_NAMES_OWN",
        "_FOLD", "_FOLD", "_INSERT",  # "Fast" is held: its candidates are folded next
        "_FOLD", "_FOLD", "_INSERT", "_FOLD", "_INSERT", "_FOLD", "_INSERT",
    ]  # fmt: skip
    candidates = [p["names"] for p in _sent(uow, "_FOLD")]
    assert candidates[:2] == [["Fast"], ["Fast", "Fast (2)", "Fast (3)"]]  # held keys + 2


async def test_import_many_folds_names_as_postgres_does_not_as_python_does() -> None:
    """`ux_ip_name` decides with Postgres's `lower()`, which folds U+0130 onto 'i' where
    Python's `str.lower` gives 'i' plus U+0307; the import takes every key from Postgres, so it
    renames what the index would refuse and keeps what the index admits."""
    stored = _Result([{"indicator_code": "ema", "name_key": _pg_lower(f"{_I_DOT}stanbul")},
                      {"indicator_code": "sma", "name_key": f"{_I_COMBINING}stanbul"}])  # fmt: skip
    assert f"{_I_DOT}stanbul".lower() == f"{_I_COMBINING}stanbul"  # where Python alone would go
    inserted = [_Result([_mapping(id="a")]), _Result([_mapping(id="b")])]
    repo, uow = _repo(_Result([{"lock": None}]), _count(2), stored, *inserted)
    items = [("a", _fields("istanbul")), ("b", _fields(f"{_I_DOT}stanbul", code="sma"))]
    await repo.import_many(_OWNER, items)
    assert _inserts(uow) == [("a", "ema", "istanbul (2)"), ("b", "sma", f"{_I_DOT}stanbul")]


async def test_import_many_maps_an_integrity_error_and_commits_nothing() -> None:
    class _Raising(_Folding):
        async def execute(
            self, stmt: sa.TextClause, params: dict[str, Any] | None = None
        ) -> _Result:
            if stmt is mod._INSERT:
                raise _err("23514", "ip_params_shape")
            return await super().execute(stmt, params)

    rel = _Rel()
    rel.uow.session = _Raising([_Result([{"lock": None}]), _count(0), _Result([])])
    repo = mod.SqlAlchemyIndicatorPresetRepository(rel)  # type: ignore[arg-type]  # stub UoW
    with pytest.raises(PresetShapeError):
        await repo.import_many(_OWNER, [("a", _fields())])
    assert rel.uow.commits == 0


async def test_count_live_by_builtin_reads_all_owners() -> None:
    repo, uow = _repo(_Result([{"is_builtin": True, "n": 18}, {"is_builtin": False, "n": 4}]))
    assert await repo.count_live_by_builtin() == {True: 18, False: 4}
    assert uow.session.executed == ["_COUNT_LIVE"]
