"""E15-T01 lock order (#402, S5 review): a writer that updates more than one layout row locks
those rows first, in id order, the order the drawings layout check takes its `FOR SHARE` locks in,
so a workspace soft delete or a default-moving layout replace cannot deadlock a drawings write.

A recording stub unit of work answers each statement by name; the real lock semantics are raced
by the CI-only `tests/integration/storage/test_drawings_layout_race.py`.
"""

from __future__ import annotations

import traceback
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.errors import StorageConstraintViolated
from candleviewer.storage.repositories import workspaces_sqlalchemy as mod
from candleviewer.storage.repositories.workspaces import (
    MAX_DELETED_LAYOUTS,
    MAX_DELETED_WORKSPACES,
    LayoutFields,
    WorkspaceConflictError,
    WorkspaceDeletion,
    WorkspaceFields,
    WorkspaceNotFoundError,
)

_T = datetime(2026, 10, 15, tzinfo=UTC)
_NAMES = {id(v): k for k, v in vars(mod).items() if isinstance(v, sa.TextClause)}
Rows = list[dict[str, object]]
_WS = {"name": "w", "is_default": False, "icon_token": "workspace.default", "sort_order": 0,
       "updated_at": _T}  # fmt: skip
_LAYOUT = {"id": "l1", "workspace_id": "w", "name": "old", "grid_preset": "1x1", "grid_spec": {},
           "crosshair_sync": True, "level_sync": False, "symbol_sync": False, "hotkey_slot": None,
           "is_default": False, "created_at": _T, "updated_at": _T}  # fmt: skip


class _Scalars:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _Result:
    def __init__(self, rows: Rows) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def first(self) -> dict[str, object] | None:
        return self._rows[0] if self._rows else None

    def one(self) -> dict[str, object]:
        (row,) = self._rows
        return row

    def scalar_one(self) -> object:
        return next(iter(self.one().values()))

    def scalars(self) -> _Scalars:
        return _Scalars([next(iter(r.values())) for r in self._rows])

    def all(self) -> list[tuple[object, ...]]:
        return [tuple(r.values()) for r in self._rows]

    def __iter__(self) -> Any:
        return iter(self._rows)


class _Rel:
    """`unit_of_work()` factory recording every statement; `rows` answers them by name, unless
    the database refuses every statement with `error`."""

    def __init__(self, rows: dict[str, Rows], error: Exception | None = None) -> None:
        self.rows, self.calls = rows, list[tuple[str, dict[str, Any]]]()
        self.commits, self.error = 0, error
        self.session = self

    def unit_of_work(self) -> _Rel:
        return self

    async def __aenter__(self) -> _Rel:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def execute(self, stmt: sa.TextClause, params: dict[str, Any]) -> _Result:
        self.calls.append((_NAMES[id(stmt)], params))
        if self.error is not None:
            raise self.error
        return _Result(self.rows.get(_NAMES[id(stmt)], []))

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


def _repo(rel: _Rel) -> mod.SqlAlchemyWorkspaceRepository:
    return mod.SqlAlchemyWorkspaceRepository(rel)  # type: ignore[arg-type]  # stub UoW factory


def _fields(is_default: bool) -> LayoutFields:
    return LayoutFields("new", "1x1", None, True, False, False, None, is_default, ())


_ROW = "canary-2748-row"  # a value the server's DETAIL would quote
_WS_FIELDS = WorkspaceFields("w", False, "workspace.default", 0)
_WRITES: dict[str, Callable[[mod.SqlAlchemyWorkspaceRepository], Awaitable[object]]] = {
    "create_workspace": lambda r: r.create_workspace("o", "w", _WS_FIELDS),
    "update_workspace": lambda r: r.update_workspace("o", "w", _WS_FIELDS, if_match=None),
    "create_layout": lambda r: r.create_layout("o", "w", "l1", _fields(False)),
    "replace_layout": lambda r: r.replace_layout("o", "w", "l1", _fields(False), if_match=None),
}


class _Driver(Exception):
    """asyncpg's unique violation: the index it names, and the failing row in its text."""

    def __init__(self, constraint: str) -> None:
        super().__init__(f"Failing row contains ({_ROW})")
        self.sqlstate, self.constraint_name = "23505", constraint


@pytest.mark.parametrize(
    ("constraint", "refusal"),
    [("ux_ws_name", WorkspaceConflictError), ("ux_lp_slot", StorageConstraintViolated)],
)
@pytest.mark.parametrize("write", list(_WRITES))
async def test_a_refused_write_is_typed_and_chains_nothing(
    write: str, constraint: str, refusal: type[Exception]
) -> None:
    """#2748: an index the router answers is its conflict (409), any other the typed
    `StorageConstraintViolated` (500); neither chains the driver error, whose text is the row."""
    rel = _Rel({}, IntegrityError("stmt", {}, _Driver(constraint)))
    with pytest.raises(refusal) as err:
        await _WRITES[write](_repo(rel))
    assert err.value.__cause__ is None and err.value.__suppress_context__ and rel.commits == 0
    assert _ROW not in "".join(traceback.format_exception(err.value))
    if isinstance(err.value, StorageConstraintViolated):
        assert (err.value.sqlstate, err.value.constraint) == ("23505", constraint)


async def _no_record(_deletion: WorkspaceDeletion) -> None:
    return None


async def test_workspace_soft_delete_locks_its_layouts_in_id_order_before_any_write() -> None:
    rel = _Rel({"_WS_LOCK": [_WS], "_WS_COUNT": [{"n": 2}], "_LAYS_LOCK": [{"id": "a"}],
                "_WS_SOFT_DELETE": [{"ts": _T}], "_LAYS_SOFT_DELETE": [{"id": "a"}]})  # fmt: skip
    await _repo(rel).soft_delete_workspace("o", "w", write_ahead=_no_record)
    assert rel.names() == ["_LOCK_USER", "_WS_LOCK", "_WS_COUNT", "_LAYS_LOCK", "_WS_SOFT_DELETE",
                           "_LAYS_SOFT_DELETE", "_DRAWINGS_SOFT_DELETE", "_PURGE_EARLY_WORKSPACES",
                           "_PURGE_EARLY_LAYOUTS"]  # fmt: skip
    assert rel.calls[3][1] == {"wid": "w", "owner": "o"} and rel.commits == 1


async def test_last_workspace_refusal_locks_no_layout() -> None:
    rel = _Rel({"_WS_LOCK": [_WS], "_WS_COUNT": [{"n": 1}]})
    with pytest.raises(WorkspaceConflictError):
        await _repo(rel).soft_delete_workspace("o", "w", write_ahead=_no_record)
    assert rel.names() == ["_LOCK_USER", "_WS_LOCK", "_WS_COUNT"] and rel.commits == 0


@pytest.mark.parametrize("is_default", [True, False])
async def test_replace_locks_its_target_and_the_default_it_takes_over_first(
    is_default: bool,
) -> None:
    locked = [{"target": False}, {"target": True}]  # the current default sorts first here
    rel = _Rel({"_WS_LOCK": [_WS], "_LAY_REPLACE_LOCK": locked, "_LAY_GET": [_LAYOUT]})
    await _repo(rel).replace_layout("o", "w", "l1", _fields(is_default), if_match=None)
    clear = ["_LAY_CLEAR_DEFAULT"] if is_default else []
    assert rel.names() == ["_WS_LOCK", "_LAY_REPLACE_LOCK", "_LAY_GET", "_PANES", *clear,
                           "_PANES_DELETE", "_LAY_UPDATE", "_LAY_GET", "_PANES"]  # fmt: skip
    lock = {"wid": "w", "owner": "o", "lid": "l1", "with_default": is_default}
    assert rel.calls[1][1] == lock and rel.commits == 1


@pytest.mark.parametrize("locked", [[], [{"target": False}]])  # nothing, or only the default
async def test_replace_of_a_missing_layout_is_a_404_before_any_read(locked: Rows) -> None:
    rel = _Rel({"_WS_LOCK": [_WS], "_LAY_REPLACE_LOCK": locked})
    with pytest.raises(WorkspaceNotFoundError):
        await _repo(rel).replace_layout("o", "w", "l1", _fields(True), if_match=None)
    assert rel.names() == ["_WS_LOCK", "_LAY_REPLACE_LOCK"] and rel.commits == 0


async def test_workspace_delete_purges_past_the_deleted_bounds_then_awaits_its_record() -> None:
    """SR-E15-05 and C-2.9: the purge statements run in the deleting transaction with the
    caller's bounds, and the record sees their counts before anything commits; `purged_layouts`
    counts the layouts a purged workspace takes with it as well as those purged on their own."""
    rel = _Rel({"_WS_LOCK": [_WS], "_WS_COUNT": [{"n": 2}], "_LAYS_LOCK": [{"id": "b"}],
                "_WS_SOFT_DELETE": [{"ts": _T}], "_LAYS_SOFT_DELETE": [{"id": "b"}, {"id": "a"}],
                "_PURGE_EARLY_WORKSPACES": [{"id": "old", "layouts": 3}],
                "_PURGE_EARLY_LAYOUTS": [{"id": "x"}, {"id": "y"}]})  # fmt: skip
    seen: list[tuple[WorkspaceDeletion, int, int]] = []

    async def record(d: WorkspaceDeletion) -> None:
        seen.append((d, len(rel.calls), rel.commits))

    done = await _repo(rel).soft_delete_workspace("o", "w", write_ahead=record)
    assert done == WorkspaceDeletion("w", ("a", "b"), 0, 1, 5)
    assert seen == [(done, len(rel.calls), 0)] and rel.commits == 1
    params = dict(rel.calls[-2:])
    assert params == {
        "_PURGE_EARLY_WORKSPACES": {"owner": "o", "keep": MAX_DELETED_WORKSPACES},
        "_PURGE_EARLY_LAYOUTS": {"owner": "o", "keep": MAX_DELETED_LAYOUTS},
    }


async def test_workspace_delete_whose_record_raises_never_commits() -> None:
    rel = _Rel({"_WS_LOCK": [_WS], "_WS_COUNT": [{"n": 2}], "_WS_SOFT_DELETE": [{"ts": _T}]})

    async def refused(_d: WorkspaceDeletion) -> None:
        raise RuntimeError("no audit writer")

    with pytest.raises(RuntimeError):
        await _repo(rel).soft_delete_workspace("o", "w", write_ahead=refused)
    assert rel.commits == 0


async def test_layout_delete_takes_the_user_lock_and_purges_past_the_deleted_bound() -> None:
    rel = _Rel({"_WS_LOCK": [_WS], "_LAY_LOCK": [{"id": "l1"}], "_LAY_SOFT_DELETE": [{"ts": _T}],
                "_PURGE_EARLY_LAYOUTS": [{"id": "x"}, {"id": "y"}]})  # fmt: skip
    assert await _repo(rel).soft_delete_layout("o", "w", "l1") == 2  # the early-purge count
    assert rel.names() == ["_LOCK_USER", "_WS_LOCK", "_LAY_LOCK", "_LAY_SOFT_DELETE",
                           "_DRAWINGS_SOFT_DELETE", "_PURGE_EARLY_LAYOUTS"]  # fmt: skip
    assert rel.calls[-1][1] == {"owner": "o", "keep": MAX_DELETED_LAYOUTS} and rel.commits == 1
