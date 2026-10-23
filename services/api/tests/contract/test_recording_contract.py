"""Contract (E16-T08, #492): every response example of the `recording` operations and
`getDataCoverage` validates; every problem code an operation names is catalogued at the status it
states, which it declares; the `recorder` step-up is named where a write can change retention
(#2880); every operation declares 401, 403 and 503, every write takes an `Idempotency-Key` and
answers `Forbidden`, the rate-limited ones 429; and the ruled stop, pin and retention text stays."""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.contract._admin_support import SPEC, example_cases, text, validate_example

_OPS: dict[str, tuple[str, str]] = {
    op["operationId"]: (path, method)
    for path, item in SPEC["paths"].items()
    for method, op in item.items()
    if isinstance(op, dict) and ("recording" in op.get("tags", []) or path.endswith("-coverage"))
}
#: `validation_failed` may also be a 422 (`test_openapi_conformance.py:173-182`).
_UP, _BAD = (403, "step_up_required"), (422, "validation_failed")
#: operationId -> the problem codes its text names, at the status it states.
_NAMED: dict[str, set[tuple[int, str]]] = {
    "listRecordedSymbols": {(400, "invalid_cursor")},
    "listRecordingSessions": {(400, "invalid_cursor")},
    "getRecordedSymbol": {(404, "not_found")},
    "addRecordedSymbol": {_UP, _BAD, (422, "recorder_symbol_limit")},
    "updateRecordedSymbol": {_UP},
    "pinRecordedSymbol": {_UP},
    "removeRecordedSymbol": {(409, "conflict"), _BAD},
    "setRetentionPolicies": {_UP, _BAD, (409, "job_running"), (409, "conflict")}
    | {(422, "retention_invalid_policy"), (503, "audit_unavailable")},
    "getDataCoverage": {(400, "validation_failed"), _BAD},
    "compactRecorder": {(409, "job_running"), (422, "idempotency_key_reused")},
    "importTradeArchive": {(409, "job_running"), (422, "import_range_invalid")}
    | {(422, "idempotency_key_reused")},
    "purgeRecordedData": {_UP, _BAD, (409, "job_running"), (422, "idempotency_key_reused")}
    | {(422, "purge_confirmation_mismatch"), (422, "retention_pinned_refused")},
}
_NOT_LIMITED = {"importTradeArchive", "purgeRecordedData"}  # the other writes declare 429
_FORBIDDEN = {"$ref": "#/components/responses/Forbidden"}  # also `forbidden` and `step_up_required`
#: statuses an operation declares beyond 401, 403 and 503 that no named code pins.
_ALSO = {
    "addRecordedSymbol": {"409"},
    "updateRecordedSymbol": {"409", "422"},
    "pinRecordedSymbol": {"409", "422"},
    "compactRecorder": {"400"},
}
_CATALOGUE = {(entry["status"], entry["code"]) for entry in SPEC["x-error-codes"]}
_EXAMPLES = example_cases(list(_OPS.values()))


def _op(operation_id: str) -> Any:
    path, method = _OPS[operation_id]
    return SPEC["paths"][path][method]


def _ref(node: Any, kind: str) -> Any:
    ref = node.get("$ref")
    return SPEC["components"][kind][ref.rsplit("/", 1)[1]] if ref else node


@pytest.mark.parametrize(("case", "pointer", "value"), _EXAMPLES, ids=[c[0] for c in _EXAMPLES])
def test_every_documented_example_validates(case: str, pointer: str, value: Any) -> None:
    validate_example(pointer, value)


@pytest.mark.parametrize("operation_id", sorted(_OPS))
def test_every_code_an_operation_names_is_catalogued_at_its_status(operation_id: str) -> None:
    op, named = _op(operation_id), _NAMED.get(operation_id, set())
    for status, code in sorted(named):
        assert (status, code) in _CATALOGUE | {_BAD}, f"{code} is not catalogued at {status}"
        assert str(status) in op["responses"], f"{code} is named but {status} is not declared"
        response = _ref(op["responses"][str(status)], "responses")
        said = text(" ".join([op.get("description", ""), response.get("description", "")]))
        assert re.search(rf"`(?:{status} )?{code}`", said), f"{code} is not named"
    inline = [r["description"] for r in op["responses"].values() if "$ref" not in r]
    own = text(" ".join([op.get("description", ""), *inline]))
    ticked = set(re.findall(r"`(?:\d{3} )?([a-z][a-z0-9_]*)`", own))
    assert ticked & {code for _, code in _CATALOGUE} <= {code for _, code in named}
    assert ("`recorder` step-up" in own) is (_UP in named)


@pytest.mark.parametrize("operation_id", sorted(_OPS))
def test_every_operation_declares_401_403_and_503(operation_id: str) -> None:
    declared = set(_op(operation_id)["responses"])
    assert {"401", "403", "503"} | _ALSO.get(operation_id, set()) <= declared


@pytest.mark.parametrize("operation_id", sorted(o for o, (_, m) in _OPS.items() if m != "get"))
def test_every_write_takes_the_key_and_answers_forbidden(operation_id: str) -> None:
    op = _op(operation_id)
    assert "Idempotency-Key" in {_ref(p, "parameters")["name"] for p in op["parameters"]}
    assert ("429" in op["responses"]) is (operation_id not in _NOT_LIMITED)
    assert op["responses"]["403"] == _FORBIDDEN


def test_purge_data_is_deprecated_for_the_purge_route() -> None:
    op = _op("removeRecordedSymbol")
    flags = [p.get("deprecated") for p in op["parameters"] if p.get("name") == "purge_data"]
    assert flags == [True]
    assert "rule `use_purge_route`" in text(op["description"])


@pytest.mark.parametrize(
    ("operation_id", "phrase"),
    [
        ("removeRecordedSymbol", "Within 5 s the row reads `lingering: true`"),
        ("removeRecordedSymbol", "A pinned symbol keeps its row and pin"),
        ("pinRecordedSymbol", "Unpinning a stopped symbol removes its row"),
        ("setRetentionPolicies", "`retain_days` is, for `archive_parquet`"),
        ("setRetentionPolicies", "A refused request stores nothing"),
    ],
)
def test_the_ruled_stop_pin_and_retention_text_stays(operation_id: str, phrase: str) -> None:
    assert phrase in text(_op(operation_id)["description"])
