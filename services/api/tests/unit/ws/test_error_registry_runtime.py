"""E17-T05: the runtime assertion - an uncatalogued WS error code can never be emitted (S10)."""

from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator

from candleviewer.ws._generated.error_codes import ERROR_META, WS_ERROR_CODES, ErrorCode
from candleviewer.ws.errors import UnknownErrorCode, build_ws_error
from tests.unit.ws._seq_support import _REGISTRY, validate

#: `p` of an `err` frame (§13): the shared helper checks only the envelope of `err` frames.
_ERROR = Draft202012Validator(
    {"$ref": "cv://ws/v1/common.schema.json#/$defs/error"}, registry=_REGISTRY
)


def test_build_ws_error_unknown_code_raises() -> None:
    with pytest.raises(UnknownErrorCode):
        build_ws_error("totally_made_up")


def test_build_ws_error_rest_only_code_raises() -> None:
    with pytest.raises(UnknownErrorCode):
        build_ws_error("validation_failed")


def test_build_ws_error_known_code_builds_frame() -> None:
    frame = build_ws_error("not_authenticated", id="c-1")
    assert frame["t"] == "err" and frame["id"] == "c-1"
    assert frame["p"]["code"] == "not_authenticated" and frame["p"]["retryable"] is False


def test_internal_error_carries_only_its_catalogue_title() -> None:
    """No caller text reaches a client on `internal_error`: only the generic title."""
    frame = build_ws_error("internal_error", message="boom: SELECT *", request_id="urn:x")
    assert frame["p"]["message"] == ERROR_META[ErrorCode.INTERNAL_ERROR].title
    assert frame["p"]["request_id"] == "urn:x"


def test_build_ws_error_defaults_the_message_to_the_catalogue_title() -> None:
    frame = build_ws_error("frame_malformed")
    assert frame["p"]["message"] == ERROR_META[ErrorCode.FRAME_MALFORMED].title != ""


def test_build_ws_error_carries_rs_only_beside_a_ch() -> None:
    """§7.5 (#3218): an `err` names a replay stream by `rs` beside its `ch`, never alone."""
    rs = "bb000000-0000-4000-8000-000000000001"
    assert build_ws_error("not_subscribed", ch="book.BTCUSDT.50", rs=rs)["rs"] == rs
    assert "rs" not in build_ws_error("not_subscribed", rs=rs)


def test_build_ws_error_keeps_a_call_site_message() -> None:
    frame = build_ws_error("invalid_options", message="depth must be one of 1, 50, 200, 500")
    assert frame["p"]["message"] == "depth must be one of 1, 50, 200, 500"


@pytest.mark.parametrize("code", sorted(WS_ERROR_CODES))
def test_every_ws_err_frame_validates_against_the_error_schema(code: ErrorCode) -> None:
    """#2395 (F1): `common#/$defs/error` requires `message` on every `err` frame."""
    frame = build_ws_error(code, id="c-1")
    validate(frame)
    assert [e.message for e in _ERROR.iter_errors(frame["p"])] == []


def test_catalogue_has_29_codes() -> None:
    assert len(WS_ERROR_CODES) == 29 and ErrorCode.FORBIDDEN in WS_ERROR_CODES
