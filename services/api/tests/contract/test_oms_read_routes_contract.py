"""Contract (E29-T07 #915, PR 1): #915's Gherkin scenario "Contract conformance" for the read
operations this PR serves. Every answer each route gives, on the fakes of
`tests/unit/api/oms_reads_world.py`, is validated against the response 22 declares for that
operation and status (the same `deref` and JSON Schema 2020-12 the other order contract tests
use), and every status a route answers is one 22 declares for it (401 is the session layer's,
declared once in `info`). The RBAC cells are `tests/contract/rbac/matrix.yaml`'s; the
`contract` CI job runs both, under no new check name (BQ-11)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from candleviewer.api.contract_conformance import load_openapi_spec
from tests.openapi_helpers import deref
from tests.unit.api.oms_reads_world import ACCOUNT_B, MISSING, World, bearer

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_A1 = "00000000-0000-0000-0000-000000000a01"
_LIVE = "00000000-0000-0000-0000-000000000a05"
_POSITION = "00000000-0000-0000-0000-000000000d01"
_ROUTES: dict[str, tuple[str, str]] = {
    "listOrders": ("/orders", "/orders"),
    "getOrder": ("/orders/{orderId}", f"/orders/{_A1}"),
    "getOrderDiagnostics": ("/orders/{orderId}/diagnostics", f"/orders/{_A1}/diagnostics"),
    "listPositions": ("/positions", "/positions"),
    "getPosition": ("/positions/{positionId}", f"/positions/{_POSITION}"),
    "listExecutions": ("/executions", "/executions"),
    "listClosedPnl": ("/executions/closed-pnl", "/executions/closed-pnl"),
}
_SCOPED = {"listOrders", "listPositions", "listExecutions", "listClosedPnl"}
_LISTS = {"listOrders", "listExecutions", "listClosedPnl"}


def _declared(operation: str, status: int) -> Any:
    """The schema 22 declares for `operation`'s `status` answer, inlined."""
    template, _ = _ROUTES[operation]
    responses = _SPEC["paths"][template]["get"]["responses"]
    assert str(status) in responses, f"{operation} answers {status}, which 22 does not declare"
    response = deref(_SPEC, responses[str(status)])
    [media] = response["content"].values()
    return media["schema"]


def _cases(operation: str) -> list[tuple[str, int, Callable[[World], None], str, dict[str, Any]]]:
    """(case, status, world change, caller, params) for each answer the route gives."""
    _, path = _ROUTES[operation]
    keep: Callable[[World], None] = lambda w: None  # noqa: E731
    cases = [
        ("ok", 200, keep, "owner", {}),
        ("forbidden", 403, keep, "bare", {}),
        ("store", 503, lambda w: setattr(w.store, "fail", True), "owner", {}),
        ("unwired", 503, lambda w: setattr(w, "composed", False), "owner", {}),
    ]
    if operation == "getOrder":
        cases += [("events", 200, keep, "owner", {"include_events": "true"})]
    if operation == "listPositions":
        cases += [("aggregate", 200, keep, "owner", {"aggregate": "true", "open_only": "false"})]
    if operation in _SCOPED:
        cases += [("scope", 403, keep, "manager", {"exchange_account_ids": str(ACCOUNT_B)})]
        cases += [("params", 400, keep, "owner", {"symbol": "nope"})]
    if operation in _LISTS:
        cases += [("cursor", 400, keep, "owner", {"cursor": "AAAA"})]
        cases += [("paged", 200, keep, "owner", {"limit": "1"})]
    if operation in {"getOrder", "getPosition", "getOrderDiagnostics"}:
        cases += [
            (
                "missing",
                404,
                keep,
                "owner",
                {"_path": path.replace(path.split("/")[2], str(MISSING))},
            )
        ]
        cases += [("bad_id", 400, keep, "owner", {"_path": path.replace(path.split("/")[2], "x")})]
    if operation == "getOrderDiagnostics":
        cases += [("manager", 403, keep, "manager", {})]
        cases += [("live", 404, keep, "owner", {"_path": f"/orders/{_LIVE}/diagnostics"})]
        cases += [("unaudited", 503, lambda w: setattr(w.audit, "fail", True), "owner", {})]
    return cases


_ALL = [pytest.param(op, *case, id=f"{op}-{case[0]}") for op in _ROUTES for case in _cases(op)]


@pytest.mark.parametrize(("operation", "case", "status", "change", "who", "params"), _ALL)
async def test_contract_conformance(
    operation: str, case: str, status: int, change: Callable[[World], None], who: str,
    params: dict[str, Any],
) -> None:  # fmt: skip
    """Gherkin "Contract conformance": each read answers a status 22 declares for it, with a body
    its response schema accepts, `additionalProperties: false` members included."""
    world, params = World(), dict(params)
    change(world)
    path = params.pop("_path", _ROUTES[operation][1])
    async with world.client() as client:
        answer = await client.get(path, params=params, headers=bearer(who))
    assert answer.status_code == status, (case, answer.text)
    media = answer.headers["content-type"]
    assert media.startswith("application/json" if status < 400 else "application/problem+json")
    validator = Draft202012Validator(
        _declared(operation, status), format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    errors = [error.message for error in validator.iter_errors(answer.json())]
    assert errors == [], (case, errors)


def test_contract_conformance_covers_every_read_this_pr_serves() -> None:
    """Every operation the router serves is driven above, and each is the contract's GET."""
    from candleviewer.api.oms_reads import make_oms_reads_router

    served = {
        (next(iter(route.methods)), route.path)  # type: ignore[attr-defined]  # APIRoute
        for route in make_oms_reads_router(None, None, audit=World().audit).routes
    }
    assert served == {("GET", template) for template, _ in _ROUTES.values()}
    for operation, (template, _) in _ROUTES.items():
        assert _SPEC["paths"][template]["get"]["operationId"] == operation
