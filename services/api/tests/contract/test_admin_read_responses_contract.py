"""`getHealth` and `listIncidents` declare every status they answer (E42-T05, #966).

`22-api-openapi.yaml` is the contract (C-6.1). Behind the audited admin guard the two reads answer,
besides their `200` and the guard's `401` and `403`: `501 not_implemented` (no principal resolver
wired, or no provider behind the read model) and `503` (no audit backend, `audit_unavailable`, or a
source that is unavailable, `store_unavailable` with `Retry-After`). `listIncidents` also answers
`400 invalid_cursor` and `422` (a bad `status`, an out-of-range `limit` or an oversized `cursor`).
Declaring a status is additive (C-6.3), so nothing is removed or narrowed.

This pins the exact status set of each operation, that every failure is a `Problem` document of the
shape the contract gives its status (the shared `Unauthorized`, `Forbidden`,
`UnprocessableEntity`, `NotImplemented` and `ServiceUnavailable` responses, and the inline
`invalid_cursor` `400` that the served paged lists declare for themselves), and that the codes
involved are registered with those statuses (C-6.5). It reads the contract only and drives no
route.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.contract._admin_support import SPEC, text, validate_example

_PROBLEM = {"$ref": "#/components/schemas/Problem"}
_RESPONSES: dict[str, Any] = SPEC["components"]["responses"]
_REGISTRY: dict[str, dict[str, Any]] = {entry["code"]: entry for entry in SPEC["x-error-codes"]}

#: The statuses each operation declares, exactly. A status added or dropped here is a contract
#: change (C-6.1; C-6.3: declaring one is additive).
_DECLARED: dict[str, frozenset[int]] = {
    "getHealth": frozenset({200, 401, 403, 501, 503}),
    "listIncidents": frozenset({200, 400, 401, 403, 422, 501, 503}),
}
#: The shared response (`components.responses`) each failure status reuses. The `400` is not here:
#: the served paged lists (`listWorkspaces`, `listLayouts`, `listDrawings`, `listLayoutPresets`)
#: each declare their own `invalid_cursor` response, and so does `listIncidents`.
_SHARED = {
    401: "Unauthorized",
    403: "Forbidden",
    422: "UnprocessableEntity",
    501: "NotImplemented",
    503: "ServiceUnavailable",
}
_INLINE: dict[str, frozenset[int]] = {"getHealth": frozenset(), "listIncidents": frozenset({400})}
_FAILURES = [
    (operation_id, status)
    for operation_id, statuses in _DECLARED.items()
    for status in sorted(statuses)
    if status >= 400
]


def _operation(operation_id: str) -> dict[str, Any]:
    (operation,) = [
        operation
        for item in SPEC["paths"].values()
        for operation in item.values()
        if isinstance(operation, dict) and operation.get("operationId") == operation_id
    ]
    return operation


def _response(operation_id: str, status: int) -> dict[str, Any]:
    """The response an operation declares for `status`, as written (a `$ref` is not followed)."""
    response: dict[str, Any] | None = _operation(operation_id)["responses"].get(str(status))
    assert response is not None, f"{operation_id} does not declare {status}"
    return response


def _resolved(response: dict[str, Any]) -> dict[str, Any]:
    """The response object, following a shared `$ref`."""
    ref = response.get("$ref")
    return response if ref is None else _RESPONSES[ref.rsplit("/", 1)[1]]


@pytest.mark.parametrize("operation_id", _DECLARED)
def test_admin_read_declares_exactly_the_statuses_it_answers(operation_id: str) -> None:
    declared = {int(code) for code in _operation(operation_id)["responses"]}
    assert declared == _DECLARED[operation_id]


@pytest.mark.parametrize("operation_id", _DECLARED)
def test_admin_read_failure_reuses_the_shared_response_of_its_status(operation_id: str) -> None:
    failures = {
        int(code): response
        for code, response in _operation(operation_id)["responses"].items()
        if int(code) >= 400
    }
    shared = {status: response for status, response in failures.items() if "$ref" in response}
    assert shared == {
        status: {"$ref": f"#/components/responses/{_SHARED[status]}"} for status in shared
    }
    assert set(failures) - set(shared) == _INLINE[operation_id]


@pytest.mark.parametrize(
    ("operation_id", "status"), _FAILURES, ids=[f"{op}-{status}" for op, status in _FAILURES]
)
def test_admin_read_failure_is_a_problem_document(operation_id: str, status: int) -> None:
    response = _resolved(_response(operation_id, status))
    ((media, body),) = response["content"].items()
    assert media == "application/problem+json"
    assert _PROBLEM in body["schema"].get("anyOf", [body["schema"]])  # `Forbidden` is a union


def test_list_incidents_400_names_invalid_cursor_as_the_other_served_lists_do() -> None:
    description = text(_response("listIncidents", 400)["description"])
    assert "`code: invalid_cursor` signals a malformed, foreign or expired `cursor`" in description
    assert "issued for a different `status` filter" in description


def test_not_implemented_response_is_the_registered_problem_and_not_retryable() -> None:
    response = _RESPONSES["NotImplemented"]
    assert "headers" not in response  # retrying does not help, so no `Retry-After`
    example = response["content"]["application/problem+json"]["examples"]["notWired"]["value"]
    assert (example["status"], example["code"]) == (501, "not_implemented")
    assert example["type"] == "https://candleviewer.local/errors/not_implemented"
    assert "detail" not in example  # the canonical example names no wiring internals
    validate_example("/components/schemas/Problem", example)


def test_service_unavailable_response_carries_the_shared_retry_after_header() -> None:
    headers = _RESPONSES["ServiceUnavailable"]["headers"]
    assert headers == {"Retry-After": {"$ref": "#/components/headers/RetryAfter"}}


@pytest.mark.parametrize(
    ("code", "status", "retryable"),
    [
        ("invalid_cursor", 400, False),
        ("not_implemented", 501, False),
        ("store_unavailable", 503, True),
        ("audit_unavailable", 503, True),
    ],
)
def test_code_an_admin_read_answers_is_registered_with_its_status(
    code: str, status: int, retryable: bool
) -> None:
    assert (_REGISTRY[code]["status"], _REGISTRY[code]["retryable"]) == (status, retryable)
