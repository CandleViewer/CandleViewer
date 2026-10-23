"""Contract (E16-T08, #492): every example of the `recording` operations and `getDataCoverage`
validates; every problem code an operation names is catalogued at the status it states, which it
declares; the `recorder` step-up is named where a write can change retention (#2880); every write
takes an `Idempotency-Key` and declares 401, 403 and 503, and the rate-limited ones 429."""

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
_UP, _BAD = (403, "step_up_required"), (422, "validation_failed")  # a 422 conformance allows
#: operationId -> the problem codes its text names, at the status it states.
_NAMED: dict[str, set[tuple[int, str]]] = {
    "listRecordedSymbols": {(400, "invalid_cursor")},
    "listRecordingSessions": {(400, "invalid_cursor")},
    "addRecordedSymbol": {_UP, _BAD, (422, "recorder_symbol_limit")},
    "updateRecordedSymbol": {_UP},
    "pinRecordedSymbol": {_UP},
    "removeRecordedSymbol": {(409, "conflict"), _BAD},
    "setRetentionPolicies": {_UP, _BAD, (409, "job_running"), (409, "conflict")}
    | {(422, "retention_invalid_policy")},
    "getDataCoverage": {(400, "validation_failed"), _BAD},
    "compactRecorder": {(409, "job_running"), (422, "idempotency_key_reused")},
    "importTradeArchive": {(409, "job_running"), (422, "import_range_invalid")},
    "purgeRecordedData": {_UP, _BAD, (409, "job_running"), (422, "idempotency_key_reused")}
    | {(422, "purge_confirmation_mismatch"), (422, "retention_pinned_refused")},
}
_NOT_LIMITED = {"importTradeArchive", "purgeRecordedData"}  # the other writes declare 429
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
        assert (status, code) in _CATALOGUE | {_BAD} and str(status) in op["responses"], code
        response = _ref(op["responses"][str(status)], "responses")
        said = text(" ".join([op.get("description", ""), response.get("description", "")]))
        assert re.search(rf"`(?:{status} )?{code}`", said), f"{code} is not named"
    inline = [r["description"] for r in op["responses"].values() if "$ref" not in r]
    own = text(" ".join([op.get("description", ""), *inline]))
    ticked = set(re.findall(r"`(?:\d{3} )?([a-z][a-z0-9_]*)`", own))
    assert ticked & {code for _, code in _CATALOGUE} <= {code for _, code in named}
    assert ("`recorder` step-up" in own) is (_UP in named)


@pytest.mark.parametrize("operation_id", sorted(o for o, (_, m) in _OPS.items() if m != "get"))
def test_every_write_takes_the_key_and_declares_401_403_and_503(operation_id: str) -> None:
    op = _op(operation_id)
    assert "Idempotency-Key" in {_ref(p, "parameters")["name"] for p in op["parameters"]}
    limited = set() if operation_id in _NOT_LIMITED else {"429"}
    assert {"401", "403", "503"} | limited <= set(op["responses"])


def test_purge_data_is_deprecated_for_the_purge_route() -> None:
    op = _op("removeRecordedSymbol")
    flags = [p.get("deprecated") for p in op["parameters"] if p.get("name") == "purge_data"]
    assert flags == [True]
    assert "rule `use_purge_route`" in text(op["description"])
