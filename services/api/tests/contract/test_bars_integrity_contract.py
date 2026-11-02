"""#5396, contract first (C-6.1): bar flags and REST bars build provenance are declared, optional
and additive (C-6.3) in `22-api-openapi.yaml` and `23-ws-protocol.md`.

- 22 `Bar` and the 23 §14.3 bar item declare `gap_before` and `partial`: booleans, default
  `false`, never required.
- 22 `KlineResponse.meta` is `BarsMeta`, `DataMeta` plus `spec_hash`, `build_version` and
  `stale`, named and bounded as the WS `bars` snapshot's `meta` (23 §13 `snapMeta`), none required.
- An answer without any of them (a server that predates them) still validates, and the generated
  models read it as unflagged and not stale.
- CVWB kind 4 carries the flags in `flags` bits 1 and 2 with no stride change: the reference
  decoder reads `confirm` from bit0 alone, so a frame with them set decodes as before.

The server does not send these members yet; the E12-Q04 drift guards list them as declared and not
yet sent until #5396's follow-up serves them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from candleviewer.api._generated import openapi_models as api
from candleviewer.ws.binary import BARS, Frame, decode, encode
from candleviewer.ws.cvwb_vectors import structured
from tests.contract._generated_contract import _REGISTRY, _URI, SPEC, _members

_SCHEMAS: Final = SPEC["components"]["schemas"]
_FLAGS: Final = ("gap_before", "partial")
_PROVENANCE: Final = ("spec_hash", "build_version", "stale")
_WS_BUNDLE: Final = Path(__file__).resolve().parents[4] / "docs" / "plan" / "ws-schema.json"
_WS: Final[dict[str, Any]] = json.loads(_WS_BUNDLE.read_text(encoding="utf-8"))["schemas"]
_WS_REGISTRY: Final = Registry().with_resources(
    (sid, Resource.from_contents(body)) for sid, body in _WS.items()
)
_BARS_ID: Final = "cv://ws/v1/bars.schema.json"
_BAR: Final[dict[str, Any]] = {"t": "2026-09-14T10:28:00Z", "o": "1", "h": "2", "l": "1", "c": "2"}
_REST_PAGE: Final[dict[str, Any]] = {
    "symbol": "BTCUSDT",
    "bar_type": "tick",
    "bars": [{**_BAR, "v": "3", "generation": 1, "index": 0, "confirm": True}],
    "meta": {"has_more": False, "count": 1, "next_cursor": None},
}
_WS_ITEM: Final[dict[str, Any]] = {
    "generation": 1,
    "index": 0,
    "t_ms": 1_789_132_200_000,
    "o": "1",
    "h": "2",
    "l": "1",
    "c": "2",
    "v": "3",
    "confirm": True,
}
_HASH: Final = "5b1e0c7d9a4f2e3b8c6d0a1f9e2b7c4d3a6f8e1b0c9d2a5f7e4b3c8d1a0f6e9b"


def _rest_errors(body: object) -> list[str]:
    ref = {"$ref": f"{_URI}#/components/schemas/KlineResponse"}
    return [e.message for e in Draft202012Validator(ref, registry=_REGISTRY).iter_errors(body)]


def _ws_errors(payload: object) -> list[str]:
    validator = Draft202012Validator(_WS[_BARS_ID], registry=_WS_REGISTRY)
    return [e.message for e in validator.iter_errors(payload)]


def _ws_item_schema() -> dict[str, Any]:
    return dict(_WS[_BARS_ID]["properties"]["bars"]["items"])


def _snap_meta() -> dict[str, Any]:
    return dict(_WS["cv://ws/v1/common.schema.json"]["$defs"]["snapMeta"]["properties"])


def _bars_meta_own() -> dict[str, Any]:
    (base, own) = _SCHEMAS["BarsMeta"]["allOf"]
    assert base == {"$ref": "#/components/schemas/DataMeta"}
    return dict(own)


@pytest.mark.parametrize("flag", _FLAGS)
def test_contract_rest_bar_flag_is_an_optional_boolean_defaulting_false(flag: str) -> None:
    bar = _SCHEMAS["Bar"]
    assert (bar["properties"][flag]["type"], bar["properties"][flag]["default"]) == (
        "boolean",
        False,
    )
    assert flag not in bar["required"]


@pytest.mark.parametrize("flag", _FLAGS)
def test_contract_ws_bar_item_flag_is_an_optional_boolean_defaulting_false(flag: str) -> None:
    item = _ws_item_schema()
    assert (item["properties"][flag]["type"], item["properties"][flag]["default"]) == (
        "boolean",
        False,
    )
    assert flag not in item["required"] and item["additionalProperties"] is False


def test_contract_kline_response_meta_is_bars_meta_over_data_meta() -> None:
    assert _SCHEMAS["KlineResponse"]["properties"]["meta"] == {
        "$ref": "#/components/schemas/BarsMeta"
    }
    members = set(_members("/components/schemas/BarsMeta"))
    assert set(_PROVENANCE) | set(_members("/components/schemas/DataMeta")) == members
    assert "required" not in _bars_meta_own()


def test_contract_bars_meta_provenance_matches_the_ws_snapshot_meta() -> None:
    """Same names, types and bounds as 23 §13 `snapMeta`: no parallel vocabulary."""
    rest, ws = _bars_meta_own()["properties"], _snap_meta()
    for name in _PROVENANCE:
        shape = {k: v for k, v in rest[name].items() if k != "description"}
        assert shape == {k: v for k, v in ws[name].items() if k != "description"}, name


def test_contract_kline_response_without_the_new_members_still_validates() -> None:
    assert _rest_errors(_REST_PAGE) == []


def test_contract_kline_response_with_the_new_members_validates() -> None:
    bar = {**_REST_PAGE["bars"][0], "gap_before": True, "partial": False}
    meta = {**_REST_PAGE["meta"], "spec_hash": _HASH, "build_version": 1, "stale": True}
    assert _rest_errors({**_REST_PAGE, "bars": [bar], "meta": meta}) == []


@pytest.mark.parametrize(
    ("where", "member", "value"),
    [
        ("bar", "gap_before", "true"),
        ("bar", "partial", 1),
        ("meta", "spec_hash", "ABC"),
        ("meta", "build_version", 0),
        ("meta", "stale", None),
    ],
)
def test_contract_kline_response_with_a_mistyped_new_member_is_refused(
    where: str, member: str, value: object
) -> None:
    bar, meta = dict(_REST_PAGE["bars"][0]), dict(_REST_PAGE["meta"])
    (bar if where == "bar" else meta)[member] = value
    assert _rest_errors({**_REST_PAGE, "bars": [bar], "meta": meta})


def test_contract_ws_bars_item_with_and_without_the_flags_validates() -> None:
    base = {"symbol": "BTCUSDT", "bar_type": "tick", "param": "100"}
    flagged = {**_WS_ITEM, "gap_before": True, "partial": True}
    assert _ws_errors({**base, "bars": [_WS_ITEM, flagged]}) == []
    assert _ws_errors({**base, "bars": [{**_WS_ITEM, "partial": "yes"}]})


def test_contract_generated_models_read_an_old_answer_as_unflagged_and_not_stale() -> None:
    page = api.KlineResponse.model_validate(_REST_PAGE)
    (bar,) = page.bars
    assert (bar.gap_before, bar.partial) == (False, False)
    assert isinstance(page.meta, api.BarsMeta)
    assert (page.meta.spec_hash, page.meta.build_version, page.meta.stale) == (None, None, False)


def test_contract_kind4_flags_bits_1_and_2_leave_confirm_on_bit0() -> None:
    """A decoder that reads bit0 alone stays correct with `gap_before` (bit1) and `partial`
    (bit2) set: same 85-byte stride, no `format_version` change (23 §3.4)."""
    bars = [(7, i, 0, 1, 2, 0, 1, 1, 1, 1, 0, flags) for i, flags in enumerate((0b110, 0b111))]
    frame = decode(encode(Frame(BARS, tuple(bars), 0, 0, 0, 0)))
    assert [b["confirm"] for b in structured(frame)["bars"]] == [False, True]
    assert [r[-1] for r in frame.records] == [0b110, 0b111]
