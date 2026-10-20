"""Contract (E16-D02, #323; E16-T08, #492): the recorder status fields are additive (C-6.3).
The amended REST examples validate; a `recorder` WS frame validates with and without them, nulls
included; the closed sets and the closed row, `storage` and `policy` objects refuse what they do
not name; REST and WS agree; the open-ended sets say so; and 24 §13.1 lists the same closed sets."""

from __future__ import annotations

from itertools import dropwhile, takewhile
from typing import Any

import pytest

from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH, load_openapi_spec
from tests.contract._admin_support import example_cases, validate_example
from tests.contract.ws._harness import SCHEMAS, check_schema

_REC = "cv://ws/v1/recorder.schema.json"
_SPEC: dict[str, Any] = load_openapi_spec()
_REST: dict[str, Any] = _SPEC["components"]["schemas"]
_OPS = [("/recording/symbols", "get"), ("/recording/status", "get"), ("/recording/storage", "get")]
_EXAMPLES = [case for case in example_cases(_OPS) if " 200 " in case[0]]
_ROW = {"symbol": "ETHUSDT", "state": "recording", "reason": "chart_open"}
_GATE = {"write_gate": "closed", "write_gate_reason": "disk_halt"}
_STATUS = _SPEC["paths"]["/recording/status"]["get"]["responses"]["200"]["content"]
_POLICY: dict[str, Any] = _STATUS["application/json"]["examples"]["healthy"]["value"]["policy"]
_FRAME: dict[str, Any] = {
    "overall": "degraded",
    "policy": _POLICY,
    "symbols": [
        _ROW | {"lingering": True, "linger_until_ms": 1_790_000_000_000},
        _ROW | {"symbol": "SOLUSDT", "state": "idle", "refusal": "symbol_cap"},
        _ROW | {"symbol": "XRPUSDT", "reason": "position_open", "refusal": "position_open"},
    ],
    "storage": {"cap_bytes": 6 * 10**11, "used_bytes": 5 * 10**11, "level": 3} | _GATE,
}
_QUIET: dict[str, Any] = {
    "overall": "healthy",
    "role_restricted": True,  # a role-reduced frame: no `position_open` refusal (R-I2)
    "symbols": [_ROW | {"lingering": False, "linger_until_ms": None, "refusal": None}],
    "storage": {
        "level": 0,
        "write_gate": "open",
        "write_gate_reason": None,
        "accelerate_retention": True,  # the ladder's own flag outlives level 2
    },
}


@pytest.mark.parametrize(("case", "pointer", "value"), _EXAMPLES, ids=[c[0] for c in _EXAMPLES])
def test_every_documented_example_validates(case: str, pointer: str, value: Any) -> None:
    validate_example(pointer, value)


@pytest.mark.parametrize(
    "frame",
    [{"overall": "healthy", "symbols": [_ROW]}, _FRAME, _QUIET],
    ids=["pre_existing", "with_new_fields", "explicit_nulls"],
)
def test_recorder_frames_validate_with_and_without_the_new_fields(frame: dict[str, Any]) -> None:
    check_schema(_REC, frame, "recorder")


@pytest.mark.parametrize(
    "patch",
    [
        {"role_restricted": "yes"},
        {"symbols": [_ROW | {"refusal": "nope"}]},
        {"symbols": [_ROW | {"linger_until": 1}]},  # the REST spelling is not a WS field
        {"storage": {"level": 4}},
        {"storage": {"write_gate": "ajar"}},
        {"storage": {"write_gate_reason": "full"}},
        {"policy": _POLICY | {"halt_pct": 101}},
        {"policy": _POLICY | {"cap_bytes": 1}},  # dropped from the policy: `storage` carries it
        {"storage": {"used_bytes": -1}},
    ],
    ids=["flag", "refusal", "unnamed", "level_4", "ajar", "reason", "pct_101", "pol_cap", "used"],
)
def test_recorder_frames_refuse_unlisted_values_and_unnamed_fields(patch: dict[str, Any]) -> None:
    with pytest.raises(AssertionError, match="violates"):
        check_schema(_REC, _FRAME | patch, "recorder")


def test_rest_and_ws_carry_the_same_policy_fields_sent_whole() -> None:
    rest, ws = _REST["RecorderPolicySettings"], SCHEMAS[_REC]["properties"]["policy"]
    assert rest["properties"] == ws["properties"]
    assert set(rest["required"]) == set(ws["required"]) == set(rest["properties"]) == set(_POLICY)
    with pytest.raises(AssertionError, match="required"):
        check_schema(_REC, _FRAME | {"policy": {"max_symbols": 2}}, "recorder")


@pytest.mark.parametrize("field", ["level", "write_gate", "write_gate_reason"])
def test_rest_and_ws_storage_name_the_same_values(field: str) -> None:
    ws = SCHEMAS[_REC]["properties"]["storage"]["properties"][field]["enum"]
    assert _REST["StorageUsage"]["properties"][field]["enum"] == ws


def test_the_open_ended_sets_say_so() -> None:
    ws = SCHEMAS[_REC]["properties"]
    gap = _REST["DataCoverage"]["properties"]["streams"]["items"]["properties"]["gaps"]["items"]
    for schema in (
        _REST["RecordRefusal"],
        _REST["StorageUsage"]["properties"]["write_gate_reason"],
        gap["properties"]["reason"],
        ws["symbols"]["items"]["properties"]["refusal"],
        ws["storage"]["properties"]["write_gate_reason"],
    ):
        assert "open-ended for readers" in " ".join(schema["description"].split()).lower()


def test_the_internal_schema_lists_the_same_closed_sets() -> None:
    doc = (OPENAPI_SPEC_PATH.parent / "24-internal-schemas.md").read_text(encoding="utf-8")
    tail = doc.split("**Recorder status closed sets**", 1)[1].split("\n")
    after = dropwhile(lambda line: not line.startswith("|"), tail)
    table = list(takewhile(lambda line: line.startswith("|"), after))
    rows = [[cell.strip(" `") for cell in line.split("|")[1:3]] for line in table[2:]]
    ws, gate = SCHEMAS[_REC]["properties"], "write_gate_reason"
    for field, *enums in [
        ("refusal", _REST["RecordRefusal"], ws["symbols"]["items"]["properties"]["refusal"]),
        (gate, _REST["StorageUsage"]["properties"][gate], ws["storage"]["properties"][gate]),
    ]:
        for enum in enums:
            assert [v for v in enum["enum"] if v] == [v for v, f in rows if f == field], field
