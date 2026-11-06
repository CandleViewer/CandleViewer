"""Contract (E29-Q02, #1147; the orchestrator's F6 ruling (iii) of 2026-11-04): `validation_failed`
is `400` when the request is malformed (an unparseable body, a bad query parameter or cursor) and
`422` when a well-formed body fails semantic validation, and an operation's declared responses name
which. 22 states it once, in `Problem`, beside the registry its `code` mirrors; the registry keeps
`status: 400` for the malformed case, and no operation's declared statuses move.

Everything is read off the YAML, none of it from a list of the places that were checked:

- the statement is in `Problem` and nowhere else;
- every declared response that names the code is a `400` or a `422`, and an example in it carries
  the status of the response it sits in;
- an operation's own prose that puts a status next to the code names one the operation declares,
  and an operation that names the code at all declares a `400` or a `422`.

An operation whose prose names a status it does not declare is a strict xfail with its reason, so
the disagreement is on record and the marker must go when the text or the declaration is fixed.
What a shared response says (the `UnprocessableEntity` note on the order routes, #2088) is shared
text about other operations, and is read as none of theirs.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_CODE = "validation_failed"
_ALLOWED = frozenset({"400", "422"})
_METHODS = frozenset({"get", "put", "post", "patch", "delete"})
_CONVENTION = (
    "`validation_failed` is 400 when the request is malformed (unparseable body, a bad query "
    "parameter or cursor) and 422 when a well-formed body fails semantic validation; an "
    "operation's declared responses name which."
)
#: A status written next to the code: "`422 validation_failed`", "400 `validation_failed`",
#: "`400` with (or for) `validation_failed`", or "`validation_failed` with `422`". A status that
#: only sits in the same sentence, or belongs to the next code in a list, is not one.
_PAIRED = re.compile(
    rf"(?P<before>\b[1-5]\d\d\b)[`\s]*(?:with\s+|as\s+|for\s+)?`?{_CODE}"
    rf"|{_CODE}`?\s+(?:with|as|is|answers)\s+`?(?P<after>\b[1-5]\d\d\b)"
)

#: The operations whose prose names a status they do not declare, today: each is reported to the
#: lane, and none is fixed here (a declared status is not this check's to change, and each sentence
#: is pinned by the test the reason names).
_KNOWN = {
    "POST /rules": (
        "E35: a `note` that is not storable text 'stays `400 validation_failed`', and the "
        "operation declares no `400` (test_rule_authoring_limits_contract pins the sentence)"
    ),
    "PUT /rules/{ruleId}/active-version": (
        "E35: a `note` that is not storable text 'stays `400 validation_failed`', and the "
        "operation declares no `400` (test_rule_authoring_limits_contract pins the sentence)"
    ),
    "PUT /positions/{positionId}/tpsl": (
        "E32 mounts the route: its `400 validation_failed` trail refusal is pinned by "
        "test_stop_loosen_contract and 24 section 8.8 rule 5, and the operation declares `422`"
    ),
}


def _words(text: str) -> str:
    return " ".join(text.split())


def _strings(node: Any) -> Iterator[str]:
    """Every string under `node`; a `$ref` is a string too, and names no code."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, Mapping):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _mappings(node: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(node, Mapping):
        yield node
        for value in node.values():
            yield from _mappings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _mappings(value)


def _names_code(node: Mapping[str, Any]) -> bool:
    """A problem body, as an example gives one: its `code`, or its `type` URI, is the code."""
    return node.get("code") == _CODE or str(node.get("type", "")).endswith(f"/{_CODE}")


def _resolved(response: Any) -> Any:
    """A response as declared: the shared one a `$ref` names, else the inline one."""
    if "$ref" in response:
        kind, name = str(response["$ref"]).split("/")[-2:]
        return _SPEC["components"][kind][name]
    return response


def _declared(operation: Any) -> dict[str, Any]:
    """The statuses an operation declares, each with its response resolved."""
    return {str(status): _resolved(r) for status, r in operation.get("responses", {}).items()}


def _examples(response: Any) -> list[Mapping[str, Any]]:
    """The problem bodies in a response's examples that name the code and give a status."""
    return [n for n in _mappings(response.get("content", {})) if _names_code(n) and "status" in n]


def _names_the_code(response: Any) -> bool:
    """A declared response that carries the code: its text says so, or an example does."""
    return _CODE in response.get("description", "") or any(
        _names_code(n) for n in _mappings(response.get("content", {}))
    )


def _paired(operation: Any) -> set[str]:
    """The statuses an operation's own text writes next to the code (a `$ref` is not followed)."""
    found = (_PAIRED.finditer(_words(text)) for text in _strings(operation))
    return {m["before"] or m["after"] for matches in found for m in matches}


def _response_slips(operation: Any) -> list[str]:
    """The declared responses that name the code under a status that is not 400 or 422."""
    named = {s: r for s, r in _declared(operation).items() if _names_the_code(r)}
    return [status for status in named if status not in _ALLOWED]


def _example_slips(operation: Any) -> list[tuple[str, Any]]:
    """(the response's status, the example's) wherever the two differ."""
    return [
        (status, example["status"])
        for status, response in _declared(operation).items()
        for example in _examples(response)
        if str(example["status"]) != status
    ]


def _prose_slips(operation: Any) -> set[str]:
    """The statuses the prose puts next to the code that the operation does not declare as a
    400 or a 422."""
    return _paired(operation) - (set(_declared(operation)) & _ALLOWED)


def _operations() -> Iterator[tuple[str, Any]]:
    for path, item in _SPEC["paths"].items():
        for method, operation in item.items():
            if method in _METHODS:
                yield f"{method.upper()} {path}", operation


_OPERATIONS = dict(_operations())
_PAIRING = [name for name, operation in _OPERATIONS.items() if _paired(operation)]


def test_problem_states_the_validation_failed_convention_once() -> None:
    """The statement is in `Problem`, where `code` is said to mirror the registry, and is in no
    other string of 22."""
    assert _CONVENTION in _words(_SPEC["components"]["schemas"]["Problem"]["description"])
    assert sum(_words(text).count(_CONVENTION) for text in _strings(_SPEC)) == 1


def test_registry_keeps_validation_failed_at_400_once() -> None:
    assert [e["status"] for e in _SPEC["x-error-codes"] if e["code"] == _CODE] == [400]


def test_every_declared_validation_failed_response_is_400_or_422() -> None:
    assert {n: s for n, op in _OPERATIONS.items() if (s := _response_slips(op))} == {}
    named = {
        status
        for operation in _OPERATIONS.values()
        for status, response in _declared(operation).items()
        if _names_the_code(response)
    }
    assert named == _ALLOWED  # and the walk reaches both families


def test_every_validation_failed_example_carries_the_status_of_its_response() -> None:
    assert {n: s for n, op in _OPERATIONS.items() if (s := _example_slips(op))} == {}
    assert any(_examples(r) for op in _OPERATIONS.values() for r in _declared(op).values())


def test_every_operation_naming_validation_failed_declares_400_or_422() -> None:
    naming = [
        name
        for name, operation in _OPERATIONS.items()
        if any(_CODE in text for text in _strings(operation))
        or any(_names_the_code(response) for response in _declared(operation).values())
    ]
    assert naming  # the walk reaches operations
    assert [n for n in naming if not set(_declared(_OPERATIONS[n])) & _ALLOWED] == []


@pytest.mark.parametrize(
    "name",
    [
        pytest.param(n, id=n, marks=[pytest.mark.xfail(strict=True, reason=_KNOWN[n])])
        if n in _KNOWN
        else pytest.param(n, id=n)
        for n in _PAIRING
    ],
)
def test_operation_prose_pairs_validation_failed_only_with_a_declared_status(name: str) -> None:
    """A `400` or a `422` that an operation's prose puts next to the code is one it declares."""
    declared = sorted(_declared(_OPERATIONS[name]))
    assert _prose_slips(_OPERATIONS[name]) == set(), (name, declared)


def test_the_disagreements_on_record_are_operations_whose_prose_pairs_the_code() -> None:
    """A recorded disagreement for an operation that is gone, or no longer pairs the code, would
    sit unread: its xfail never runs."""
    assert set(_KNOWN) <= set(_PAIRING)


def test_the_scan_reads_each_form_a_status_sits_next_to_the_code() -> None:
    """The checks above are not vacuous: each form they read is found, and a status that belongs
    to another code in the sentence is not."""
    forms = (
        "It is `422 validation_failed`, or 400 `validation_failed`, or `400` with "
        "`validation_failed`, or `400` for `validation_failed`, or `validation_failed` with `422`."
    )
    assert [m["before"] or m["after"] for m in _PAIRED.finditer(forms)] == [
        "422",
        "400",
        "400",
        "400",
        "422",
    ]
    other = "A `422 rule_ir_invalid` or `validation_failed`, `422 validation_failed`, `503 other`."
    assert [m["before"] or m["after"] for m in _PAIRED.finditer(other)] == ["422"]


def test_the_scan_finds_each_way_an_operation_can_disagree() -> None:
    """A status the prose names and the operation does not declare; a response that names the code
    under another status; an example whose status is not its response's; and an operation that
    agrees with itself is clean."""

    def problem(status: int) -> dict[str, Any]:
        body = {"examples": {"e": {"value": {"code": _CODE, "status": status}}}}
        return {"description": "ok", "content": {"application/problem+json": body}}

    prose = {"description": "It is `422 validation_failed`.", "responses": {"400": problem(400)}}
    assert _prose_slips(prose) == {"422"}
    assert _response_slips({"responses": {"409": problem(409)}}) == ["409"]
    assert _example_slips({"responses": {"422": problem(400)}}) == [("422", 400)]
    clean = {"description": "It is `422 validation_failed`.", "responses": {"422": problem(422)}}
    assert (_prose_slips(clean), _response_slips(clean), _example_slips(clean)) == (set(), [], [])
