"""Driver-free workspaces repository surface (E15-T01): tokens, rows, typed errors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from candleviewer.storage.repositories.workspaces import (
    LayoutFields,
    LayoutRow,
    PaneFields,
    WorkspaceConflictError,
    WorkspaceFields,
    WorkspaceNotFoundError,
    WorkspaceRow,
    format_token,
)

_T = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def _pane(slot: int = 0) -> PaneFields:
    return PaneFields(slot, "chart", "BTCUSDT", "time:1m", None, (), {"settings": {}}, "auto")


def _lay_fields(*panes: PaneFields) -> LayoutFields:
    return LayoutFields("L", "1x1", None, True, False, False, None, False, panes)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (_T, "2026-10-01T12:00:00.000000Z"),
        (_T.replace(microsecond=5), "2026-10-01T12:00:00.000005Z"),
        (_T.astimezone(timezone(timedelta(hours=2))), "2026-10-01T12:00:00.000000Z"),
    ],
)
def test_format_token_always_six_fractional_digits_and_z(value: datetime, expected: str) -> None:
    assert format_token(value) == expected


def test_row_tokens_use_updated_at() -> None:
    ws = WorkspaceRow("i", "o", "n", False, "t", 0, 0, _T, _T.replace(microsecond=7))
    expected_ws = "2026-10-01T12:00:00.000007Z"
    assert ws.token == expected_ws
    assert ws.to_fields() == WorkspaceFields("n", False, "t", 0)
    lay = LayoutRow("i", "w", "L", "1x1", None, True, False, False, None, False, (), _T, _T)
    expected_lay = "2026-10-01T12:00:00.000000Z"
    assert lay.token == expected_lay
    assert lay.to_fields() == _lay_fields()


def test_typed_errors_carry_their_context() -> None:
    err = WorkspaceConflictError("name_taken", "name")
    assert (err.rule, err.field) == ("name_taken", "name")
    assert WorkspaceConflictError("limit_reached", None).field is None
    assert WorkspaceNotFoundError("layout").kind == "layout"
