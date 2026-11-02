"""#5396, contract first (C-6.1): bar flags and REST bars build provenance are declared, optional
and additive (C-6.3) in `22-api-openapi.yaml` and `23-ws-protocol.md`.

- 22 `Bar` and the 23 §14.3 bar item declare `gap_before`, `partial` and `tape_gap`: booleans,
  default `false`, never required.
- 22 `KlineResponse.meta` is `BarsMeta`, `DataMeta` plus `spec_hash` and `build_version` (named and
  bounded as the WS `bars` snapshot's `meta`, 23 §13 `snapMeta`) and REST's own `stale_build`, none
  required. REST has no `stale`: one key, one meaning (WS `meta.stale` is a feed behind).
- An answer without any of them (a server that predates them) still validates, and the generated
  models read it as unflagged and not stale_build.
- CVWB kind 4 carries the flags in `flags` bits 1-3 with no stride change: the reference decoders
  read `confirm` from bit0 alone, so a frame with them set decodes as before.

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
from candleviewer.ws.binary import decode, encode
from candleviewer.ws.cvwb_vectors import structured, vector_frames
from tests.contract._generated_contract import _REGISTRY, _URI, SPEC, _members

_SCHEMAS: Final = SPEC["components"]["schemas"]
_FLAGS: Final = ("gap_before", "partial", "tape_gap")
#: Shared with the WS snapshot meta, by name and shape; `stale_build` is REST's own.
_SHARED: Final = ("spec_hash", "build_version")
_PROVENANCE: Final = (*_SHARED, "stale_build")
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
    """`spec_hash` and `build_version`: same names, types and bounds as 23 §13 `snapMeta`."""
    rest, ws = _bars_meta_own()["properties"], _snap_meta()
    for name in _SHARED:
        shape = {k: v for k, v in rest[name].items() if k != "description"}
        assert shape == {k: v for k, v in ws[name].items() if k != "description"}, name


def test_contract_bars_meta_stale_build_is_rest_only_and_rest_has_no_stale() -> None:
    """One key, one meaning: REST's `stale_build` is an optional boolean defaulting to false, the
    WS snapshot meta has no `stale_build`, and REST declares no `stale` (WS's feed-behind key)."""
    rest = _bars_meta_own()["properties"]
    assert {k: v for k, v in rest["stale_build"].items() if k != "description"} == {
        "type": "boolean",
        "default": False,
    }
    assert "stale_build" not in _snap_meta()
    assert "stale" not in _members("/components/schemas/BarsMeta")


def test_contract_kline_response_without_the_new_members_still_validates() -> None:
    assert _rest_errors(_REST_PAGE) == []


def test_contract_kline_response_with_the_new_members_validates() -> None:
    bar = {**_REST_PAGE["bars"][0], "gap_before": True, "partial": False, "tape_gap": True}
    meta = {**_REST_PAGE["meta"], "spec_hash": _HASH, "build_version": 1, "stale_build": True}
    assert _rest_errors({**_REST_PAGE, "bars": [bar], "meta": meta}) == []


@pytest.mark.parametrize(
    ("where", "member", "value"),
    [
        ("bar", "gap_before", "true"),
        ("bar", "partial", 1),
        ("meta", "spec_hash", "ABC"),
        ("meta", "build_version", 0),
        ("bar", "tape_gap", "no"),
        ("meta", "stale_build", None),
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
    flagged = {**_WS_ITEM, "gap_before": True, "partial": True, "tape_gap": True}
    assert _ws_errors({**base, "bars": [_WS_ITEM, flagged]}) == []
    assert _ws_errors({**base, "bars": [{**_WS_ITEM, "partial": "yes"}]})


def test_contract_generated_models_read_an_old_answer_as_unflagged_and_not_stale() -> None:
    page = api.KlineResponse.model_validate(_REST_PAGE)
    (bar,) = page.bars
    assert (bar.gap_before, bar.partial, bar.tape_gap) == (False, False, False)
    assert isinstance(page.meta, api.BarsMeta)
    meta = page.meta
    assert (meta.spec_hash, meta.build_version, meta.stale_build) == (None, None, False)


@pytest.mark.parametrize(
    ("name", "flags", "confirm"),
    [("bars_flags_gap_partial", 0b0000_1110, False), ("bars_flags_reserved_bits", 0xF1, True)],
)
def test_contract_kind4_flag_vectors_leave_confirm_on_bit0(
    name: str, flags: int, confirm: bool
) -> None:
    """The shared golden vectors (`cvwb_vectors`, read by the TS decoder too): bits 1-3
    (`gap_before`, `partial`, `tape_gap`) and reserved bits 4-7 decode as before, same 85-byte
    stride, no `format_version` change (23 §3.4); `confirm` stays bit0."""
    frame = decode(encode(dict(vector_frames())[name]))
    assert frame.records[0][-1] == flags
    assert [b["confirm"] for b in structured(frame)["bars"]] == [confirm]
