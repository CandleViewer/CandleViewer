"""Contract (E29-T07 #915, PR 2): #915's Gherkin scenario "Contract conformance" for
`setPositionLeverage`. Every answer the route gives, on the fakes of
`tests/unit/api/test_position_leverage_route.py`, is a status 22 declares for the operation, with
a body its response schema accepts (the same `deref` and JSON Schema 2020-12 the other order
contract tests use; 401 is the session layer's, declared once in `info`)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.position_leverage import LEVERAGE_PATH, make_position_leverage_router
from candleviewer.exchange.base.errors import InsufficientMarginError
from candleviewer.observability.metrics import Metrics
from tests.openapi_helpers import deref
from tests.unit.api.oms_reads_world import MISSING
from tests.unit.api.test_position_leverage_route import (
    ON_A,
    ON_B,
    ON_LIVE,
    World,
    headers,
)

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_OPERATION = _SPEC["paths"][LEVERAGE_PATH]["put"]
_KEEP: Callable[[World], None] = lambda w: None  # noqa: E731


def _venue_refuses(world: World) -> None:
    world.port.script("set_leverage", InsufficientMarginError("no", exchange_ret_code=7))


def _declared(status: int) -> Any:
    responses = _OPERATION["responses"]
    assert str(status) in responses, f"setPositionLeverage answers {status}, undeclared in 22"
    [media] = deref(_SPEC, responses[str(status)])["content"].values()
    return media["schema"]


#: (case, status, world, world change, caller, position, body, header changes)
_CASES: list[tuple[str, int, Callable[[], World], Callable[[World], None], str, str, Any, Any]] = [
    ("ok", 200, World, _KEEP, "owner", ON_A, {"leverage": "12.5"}, {}),
    ("bad_id", 400, World, _KEEP, "owner", "x", {"leverage": "12"}, {}),
    ("no_key", 400, World, _KEEP, "owner", ON_A, {"leverage": "12"}, {"idempotency-key": None}),
    ("forbidden", 403, World, _KEEP, "viewer", ON_A, {"leverage": "12"}, {}),
    ("read_only", 403, World, _KEEP, "reader", ON_A, {"leverage": "12"}, {}),
    ("not_armed", 403, lambda: World(environment="live"), _KEEP, "owner", ON_LIVE,
     {"leverage": "12"}, {}),
    ("flag", 403, lambda: World(oms_enabled=False), _KEEP, "owner", ON_A, {"leverage": "12"}, {}),
    ("owner_only", 403, World, _KEEP, "manager", ON_A, {"leverage": "12"}, {}),
    ("foreign", 404, World, _KEEP, "scoped", ON_B, {"leverage": "12"}, {}),
    ("reuse", 409, World, _KEEP, "owner", ON_A, {"leverage": "12"}, {}),
    ("missing", 404, World, _KEEP, "owner", str(MISSING), {"leverage": "12"}, {}),
    ("body", 422, World, _KEEP, "owner", ON_A, {"leverage": 12}, {}),
    ("bound", 422, World, _KEEP, "owner", ON_A, {"leverage": "26"}, {}),
    ("rate", 429, lambda: World(rate=1), _KEEP, "owner", ON_A, {"leverage": "12"}, {}),
    ("no_oms", 501, lambda: World(composed=False), _KEEP, "owner", ON_A, {"leverage": "12"}, {}),
    ("venue", 502, World, _venue_refuses, "owner", ON_A, {"leverage": "12"}, {}),
    ("not_ready", 503, lambda: World(readiness="starting"), _KEEP, "owner", ON_A,
     {"leverage": "12"}, {}),
    ("audit", 503, World, lambda w: setattr(w.records, "fail", True), "owner", ON_A,
     {"leverage": "12"}, {}),
]  # fmt: skip


@pytest.mark.parametrize(
    ("case", "status", "make", "change", "who", "position", "body", "extra"),
    [pytest.param(*c, id=c[0]) for c in _CASES],
)
async def test_contract_conformance(
    case: str, status: int, make: Callable[[], World], change: Callable[[World], None], who: str,
    position: str, body: Any, extra: dict[str, str | None],
) -> None:  # fmt: skip
    """Gherkin "Contract conformance": each answer is a status 22 declares for
    `setPositionLeverage`, with a body its response schema accepts."""
    world = make()
    change(world)
    sent = {k: v for k, v in (headers(who) | extra).items() if v is not None}
    path = LEVERAGE_PATH.replace("{positionId}", position)
    async with world.client() as client:
        if case in ("rate", "reuse"):  # the minute's one change, or the key's first body
            first = sent if case == "reuse" else headers(who)
            assert (await client.put(path, json={"leverage": "11"}, headers=first)).is_success
        answer = await client.put(path, json=body, headers=sent)
    assert answer.status_code == status, (case, answer.text)
    media = answer.headers["content-type"]
    assert media.startswith("application/json" if status < 400 else "application/problem+json")
    validator = Draft202012Validator(
        _declared(status), format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    errors = [error.message for error in validator.iter_errors(answer.json())]
    assert errors == [], (case, errors)
    if status in (429, 503) and case in ("rate", "not_ready"):
        assert int(answer.headers["retry-after"]) >= 1


def test_contract_conformance_covers_the_operation_this_pr_serves() -> None:
    """The router serves exactly 22's `setPositionLeverage`, its declared statuses each driven."""
    router = make_position_leverage_router(
        None, lambda: None, None, audit=World().audit, records=World().records,
        oms_enabled=lambda: True, metrics=Metrics("demo"),
    )  # fmt: skip
    served = {(next(iter(r.methods)), r.path) for r in router.routes}  # type: ignore[attr-defined]  # APIRoute
    assert served == {("PUT", LEVERAGE_PATH)}
    assert _OPERATION["operationId"] == "setPositionLeverage"
    assert "ArmToken" in str(_OPERATION["parameters"])
    declared = {int(s) for s in _OPERATION["responses"]}
    assert declared == {status for _, status, *_ in _CASES}
