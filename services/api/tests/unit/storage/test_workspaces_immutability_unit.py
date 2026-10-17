"""Moves are impossible through the repository: no statement rewrites an ownership column.

The composite FKs (D27) keep owners consistent but do not stop a move; the only protection is that
the application never writes `user_id`, `owner_user_id`, `workspace_id` or `layout_id` after insert.
"""

from __future__ import annotations

import re

import pytest
import sqlalchemy as sa

from candleviewer.storage.repositories import workspaces_sqlalchemy as mod

_STATEMENTS = {n: str(v) for n, v in vars(mod).items() if isinstance(v, sa.TextClause)}
_OWNERSHIP = ("user_id", "owner_user_id", "workspace_id", "layout_id")


def _set_columns(text: str) -> set[str]:
    clause = re.search(r"\bSET\b(.*?)\bWHERE\b", text, re.S)
    assert clause is not None, text
    return set(re.findall(r"(\w+)\s*=", clause.group(1)))


_UPDATES = {n: t for n, t in _STATEMENTS.items() if t.startswith("UPDATE ")}


def test_the_update_set_is_pinned() -> None:
    assert set(_UPDATES) == {
        "_WS_CLEAR_DEFAULT", "_WS_UPDATE", "_WS_SOFT_DELETE", "_LAYS_SOFT_DELETE",
        "_LAY_SOFT_DELETE", "_DRAWINGS_SOFT_DELETE", "_LAY_CLEAR_DEFAULT", "_LAY_UPDATE",
    }  # fmt: skip


@pytest.mark.parametrize("name", sorted(_UPDATES))
def test_no_update_writes_an_ownership_column(name: str) -> None:
    assert _set_columns(_UPDATES[name]).isdisjoint(_OWNERSHIP)


def test_layout_panes_are_never_updated_only_deleted_and_inserted() -> None:
    assert not any("UPDATE layout_panes" in t for t in _STATEMENTS.values())
    assert _STATEMENTS["_PANES_DELETE"].startswith("DELETE FROM layout_panes")
    assert _STATEMENTS["_PANES_INSERT"].startswith("INSERT INTO layout_panes")


@pytest.mark.parametrize("name", ["_PANES_DELETE", "_PANES_INSERT"])
def test_pane_writes_re_check_that_the_layout_belongs_to_the_caller(name: str) -> None:
    text = _STATEMENTS[name]
    assert "owner_user_id = CAST(:owner AS uuid)" in text
    assert "CAST(:lid AS uuid)" in text


def test_pane_writes_follow_the_workspace_lock_and_layout_lock_in_replace_and_create() -> None:
    import inspect

    pairs = (("replace_layout", "_LAY_REPLACE_LOCK"), ("create_layout", "_LAY_INSERT"))
    for method, first in pairs:
        src = inspect.getsource(getattr(mod.SqlAlchemyWorkspaceRepository, method))
        assert src.index("_lock_workspace") < src.index(first) < src.index("_write_panes")
