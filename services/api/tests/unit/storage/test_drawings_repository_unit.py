"""Pure parts of the drawings repository (E14-T01): tokens, rows, ops, SQL scoping.

Real-DB behaviour lives in `tests/integration/storage/test_drawings_repository.py` (CI-only).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from candleviewer.storage.repositories import drawings_sqlalchemy as mod
from candleviewer.storage.repositories.drawings import (
    BatchOpFailed,
    BatchResult,
    CreateOp,
    DeleteOp,
    DrawingFields,
    UpdateOp,
    format_token,
)

_T = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def _fields() -> DrawingFields:
    return DrawingFields(
        "BTCUSDT", None, "trendline", {"points": []}, {}, None, False, True, 0, _T, _T
    )


def _mapping(**over: object) -> dict[str, object]:
    d: dict[str, object] = {
        "id": "i", "owner_user_id": "o", "symbol": "BTCUSDT", "layout_id": None,
        "tool": "trendline", "geometry": '{"points":[{"p":"1.10","t":"x"}]}', "style": {},
        "label": None, "locked": False, "visible": True, "z_index": 0,
        "created_at": _T, "updated_at": _T,
    }  # fmt: skip
    d.update(over)
    return d


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (_T, "2026-10-01T12:00:00.000000Z"),
        (_T.replace(microsecond=5), "2026-10-01T12:00:00.000005Z"),
        (_T.replace(microsecond=123456), "2026-10-01T12:00:00.123456Z"),
        (_T.astimezone(timezone(timedelta(hours=2))), "2026-10-01T12:00:00.000000Z"),
    ],
)
def test_format_token_always_six_fractional_digits_and_z(value: datetime, expected: str) -> None:
    assert format_token(value) == expected


def test_row_token_uses_updated_at() -> None:
    row = mod.to_row(_mapping())
    expected = "2026-10-01T12:00:00.000000Z"
    assert row.token == expected


def test_to_row_decodes_json_text_and_keeps_decimal_strings_verbatim() -> None:
    row = mod.to_row(_mapping())
    assert row.geometry == {"points": [{"p": "1.10", "t": "x"}]}
    assert row.style == {}


def test_to_row_accepts_already_decoded_json() -> None:
    assert mod.to_row(_mapping(geometry={"points": []})).geometry == {"points": []}


def test_json_is_canonical() -> None:
    assert mod._json({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'
    assert json.loads(mod._json({"p": "0.10"})) == {"p": "0.10"}


def test_params_cover_every_writable_column() -> None:
    assert set(mod._params(_fields())) == {
        "symbol", "layout", "tool", "geometry", "style", "label", "locked", "visible",
        "z_index", "anchor_start", "anchor_end",
    }  # fmt: skip


def test_ops_and_results_are_frozen_value_objects() -> None:
    f = _fields()
    assert CreateOp("a", f) == CreateOp("a", f)
    assert UpdateOp("a", _T, f).if_match == _T
    assert DeleteOp("a", _T).id == "a"
    assert BatchResult((), (), ()).deleted == ()
    with pytest.raises(AttributeError):
        DeleteOp("a", _T).id = "b"  # type: ignore[misc]


def test_batch_op_failed_carries_index_and_rule() -> None:
    err = BatchOpFailed(3, "target_unavailable")
    assert (err.index, err.rule) == (3, "target_unavailable")
    assert "operations.3" in str(err)


_STATEMENTS = {
    n: getattr(mod, n)
    for n in ("_INSERT", "_GET", "_EXISTS_OTHER", "_LIST", "_UPDATE", "_SOFT_DELETE",
              "_SNAPSHOT", "_PURGE")
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(_STATEMENTS))
def test_every_statement_is_owner_scoped_except_the_three_allowed(name: str) -> None:
    text = str(_STATEMENTS[name])
    if name in mod.UNSCOPED:
        assert name in {"_EXISTS_OTHER", "_SNAPSHOT", "_PURGE"}
    elif name == "_INSERT":  # no WHERE clause: the owner is written as a bound value
        assert "CAST(:owner AS uuid)" in text
    else:
        assert "owner_user_id = CAST(:owner AS uuid)" in text


def test_only_three_statements_are_unscoped() -> None:
    assert mod.UNSCOPED == {"_EXISTS_OTHER", "_SNAPSHOT", "_PURGE"}


def test_read_allow_list_excludes_internal_columns() -> None:
    for hidden in ("deleted_at", "anchor_", "alert_id", "interval_scope"):
        assert hidden not in mod.DRAWING_COLUMNS


@pytest.mark.parametrize("name", ["_UPDATE", "_SOFT_DELETE"])
def test_updates_bump_the_token_monotonically(name: str) -> None:
    assert "greatest(clock_timestamp(), updated_at + interval '1 microsecond')" in str(
        _STATEMENTS[name]
    )


def test_list_uses_the_index_friendly_shape() -> None:
    text = str(_STATEMENTS["_LIST"])
    assert "symbol = :symbol" in text and "ORDER BY id LIMIT :limit" in text
