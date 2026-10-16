"""SQL-shape guards for the SQLAlchemy workspaces repository (E15-T01).

Real-DB behaviour lives in `tests/integration/storage/test_workspaces_repository.py` (CI-only).
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa

from candleviewer.storage.repositories import workspaces_sqlalchemy as mod

# Self-discovering: a statement added later cannot dodge the owner-filter guard.
_STATEMENTS = {n: v for n, v in vars(mod).items() if isinstance(v, sa.TextClause)}
#: Statements whose owner scoping is by a bound value or a join rather than `= :owner`.
_OWNER_MARKERS = ("= CAST(:owner AS uuid)", "CAST(:owner AS uuid), :name", "CAST(:owner AS text)")


def test_the_statement_set_is_pinned() -> None:
    assert set(_STATEMENTS) == {
        "_LOCK_USER", "_WS_LOCK", "_WS_COUNT", "_WS_CLEAR_DEFAULT", "_WS_INSERT", "_WS_UPDATE",
        "_WS_GET", "_WS_LIST", "_WS_SOFT_DELETE", "_LAYS_SOFT_DELETE", "_LAY_SOFT_DELETE",
        "_DRAWINGS_SOFT_DELETE", "_WS_LIVE", "_LAY_COUNT", "_LAY_LOCK", "_LAY_CLEAR_DEFAULT",
        "_LAY_INSERT", "_LAY_UPDATE", "_LAY_GET", "_LAY_LIST", "_PANES", "_PANES_DELETE",
        "_PANES_INSERT", "_IS_LIVE_LAYOUT", "_EXISTS_OTHER_WS", "_EXISTS_OTHER_LAY",
        "_CHART_OPEN", "_CHART_SYMBOLS", "_PURGE_LAYOUTS", "_PURGE_WORKSPACES",
    }  # fmt: skip


@pytest.mark.parametrize("name", sorted(_STATEMENTS))
def test_every_statement_is_owner_scoped_except_the_unscoped_ones(name: str) -> None:
    text = str(_STATEMENTS[name])
    if name in mod.UNSCOPED:
        assert ":owner" not in text or "<> CAST(:owner AS uuid)" in text
    else:
        assert any(m in text for m in _OWNER_MARKERS), text


def test_unscoped_statements_are_exactly_the_documented_six() -> None:
    assert mod.UNSCOPED == {
        "_EXISTS_OTHER_WS", "_EXISTS_OTHER_LAY", "_CHART_OPEN", "_CHART_SYMBOLS",
        "_PURGE_LAYOUTS", "_PURGE_WORKSPACES",
    }  # fmt: skip
    assert set(mod.UNSCOPED) <= set(_STATEMENTS)


@pytest.mark.parametrize("name", ["_LAY_LOCK", "_PANES", "_LAY_LIST", "_WS_LIST"])
def test_multi_row_reads_and_locks_are_ordered(name: str) -> None:
    assert "ORDER BY" in str(_STATEMENTS[name])
    if name == "_LAY_LOCK":
        assert "ORDER BY id FOR UPDATE" in str(_STATEMENTS[name])


@pytest.mark.parametrize(
    "name",
    ["_WS_CLEAR_DEFAULT", "_WS_UPDATE", "_WS_SOFT_DELETE", "_LAYS_SOFT_DELETE", "_LAY_UPDATE",
     "_LAY_CLEAR_DEFAULT", "_LAY_SOFT_DELETE", "_DRAWINGS_SOFT_DELETE"],
)  # fmt: skip
def test_updates_bump_the_token_monotonically(name: str) -> None:
    assert "greatest(clock_timestamp(), updated_at + interval '1 microsecond')" in str(
        _STATEMENTS[name]
    )


def test_user_lock_precedes_nothing_else_and_workspace_lock_is_no_key_update() -> None:
    assert "pg_advisory_xact_lock(hashtextextended('cv.workspaces:'" in str(_LOCK)
    assert str(_STATEMENTS["_WS_LOCK"]).endswith("FOR NO KEY UPDATE")


_LOCK = _STATEMENTS["_LOCK_USER"]


def test_recorder_probe_uses_the_symbol_equality_shape() -> None:
    text = str(_STATEMENTS["_CHART_OPEN"])
    assert "lp.symbol = :symbol" in text and "l.deleted_at IS NULL" in text


def test_no_statement_interpolates_values() -> None:
    for text in map(str, _STATEMENTS.values()):
        assert "{" not in text and "%s" not in text


@pytest.mark.parametrize(
    ("days", "limit"),
    [(0, 10), (-1, 10), (90, 0), (90, -5), (90, mod.MAX_PURGE_BATCH + 1)],
)
async def test_purge_rejects_unsafe_arguments_before_touching_the_database(
    days: int, limit: int
) -> None:
    unused: Any = object()  # never touched: the ValueError fires first
    with pytest.raises(ValueError, match="purge needs"):
        await mod.SqlAlchemyWorkspaceRepository(unused).purge_deleted(days, limit)
