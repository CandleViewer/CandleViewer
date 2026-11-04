"""Contract (E29-T07 #915, PR 2): #915's Gherkin scenario "Contract conformance" for
`closePosition`, `reversePosition` and `closeAllPositions` as #5013 amended them. Every answer the
routes give on the fakes of `tests/unit/api/position_writes_world.py` is a status 22 declares for
the operation, with a body its response schema accepts (the same `deref` and JSON Schema 2020-12
the other order contract tests use; a `401` is step 1's, the shared `Unauthorized`)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.position_close import CLOSE_ALL_PATH, CLOSE_PATH, CloseAllBody, close_all_body
from candleviewer.api.position_reverse import REVERSE_PATH
from candleviewer.oms.errors import (
    ExchangeRejected,
    FieldError,
    OrderInvalid,
    PositionChanged,
    TradingDisabled,
)
from candleviewer.oms.idempotency import InFlight
from candleviewer.oms.position_writes import reversal_refs
from candleviewer.oms.submit import SubmitOutcome
from tests.openapi_helpers import deref
from tests.unit.api.oms_reads_world import MISSING
from tests.unit.api.position_writes_world import (
    FLAT,
    ON_A,
    ON_B,
    ON_LIVE,
    World,
    headers,
    on,
    post,
)
from tests.unit.oms.submit_rig import instrument

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_KEY = uuid.UUID("9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59")
_FULL = {"order_type": "market", "pct": "100"}


def _keep(world: World) -> None:
    return None


def _close_rejected(world: World) -> None:
    world.pipeline.close = SubmitOutcome(502, uuid.uuid4(), uuid.uuid4(), code="exchange_error",
                                         ret_code=110017)  # fmt: skip


def _close_rate(world: World) -> None:
    world.pipeline.close = SubmitOutcome(429, uuid.uuid4(), uuid.uuid4(),
                                         code="exchange_rate_limited", retry_after_s=2)  # fmt: skip


def _in_flight(operation: str, ref: uuid.UUID) -> Callable[[World], None]:
    def change(world: World) -> None:
        world.anchors.answers[(operation, ref)] = InFlight(1)

    return change


def _no_stop(world: World) -> None:
    stop = FieldError("stop_loss", "native_stop_required", "No stop.")
    world.positions.stop_refusal = OrderInvalid("No stop.", errors=(stop,))


def _set(name: str, value: object) -> Callable[[World], None]:
    def change(world: World) -> None:
        setattr(world, name, value)

    return change


def _switch_off(world: World) -> None:
    world.route.switches.refusal_of = TradingDisabled()


def _dusty(world: World) -> None:
    """E29-S03: a minimum of 0.150, so 75 % of 0.200 leaves dust."""
    world.positions.listed["BTCUSDT"] = instrument(min_order_qty=Decimal("0.150"))


def _venue_changed(world: World) -> None:
    """E29-S03 BQ-7: the pipeline's read of the venue showed the position smaller."""
    shrunk = FieldError("qty", "exceeds_position", "The position is now smaller than the close.")
    world.pipeline.close = PositionChanged(shrunk.message, errors=(shrunk,))


#: (case, method path template, status, world, caller, position, body, header changes)
_CASES: list[tuple[str, str, int, Callable[[World], None], str, str, Any, dict[str, Any]]] = [
    ("close_ok", CLOSE_PATH, 202, _keep, "owner", ON_A, _FULL, {}),
    ("close_bad_id", CLOSE_PATH, 400, _keep, "owner", "x", _FULL, {}),
    ("close_no_session", CLOSE_PATH, 401, _keep, "nobody", ON_A, _FULL, {}),
    ("close_no_key", CLOSE_PATH, 400, _keep, "owner", ON_A, _FULL, {"idempotency-key": None}),
    ("close_forbidden", CLOSE_PATH, 403, _keep, "viewer", ON_A, _FULL, {}),
    ("close_read_only", CLOSE_PATH, 403, _keep, "reader", ON_A, _FULL, {}),
    ("close_switch_carved_out", CLOSE_PATH, 202, _switch_off, "owner", ON_A, _FULL, {}),  # C-2.6
    ("close_foreign", CLOSE_PATH, 404, _keep, "manager", ON_B, _FULL, {}),
    ("close_missing", CLOSE_PATH, 404, _keep, "owner", str(MISSING), _FULL, {}),
    ("close_in_flight", CLOSE_PATH, 409, _in_flight("closePosition", _KEY), "owner", ON_A, _FULL,
     {}),
    ("close_body", CLOSE_PATH, 422, _keep, "owner", ON_A, {"order_type": "market"}, {}),
    ("close_flat", CLOSE_PATH, 422, _keep, "owner", FLAT, _FULL, {}),
    ("close_dust", CLOSE_PATH, 422, _dusty, "owner", ON_A, {"order_type": "market", "pct": "75"},
     {}),
    ("close_below_minimum", CLOSE_PATH, 422, _keep, "owner", ON_A,
     {"order_type": "market", "pct": "0.4"}, {}),
    ("close_venue_changed", CLOSE_PATH, 422, _venue_changed, "owner", ON_A, _FULL, {}),
    ("close_rate", CLOSE_PATH, 429, World.exhaust, "owner", ON_A, _FULL, {}),
    ("close_send_rate", CLOSE_PATH, 429, _close_rate, "owner", ON_A, _FULL, {}),
    ("close_no_oms", CLOSE_PATH, 501, _set("composed", False), "owner", ON_A, _FULL, {}),
    ("close_venue", CLOSE_PATH, 502, _close_rejected, "owner", ON_A, _FULL, {}),
    ("close_no_reads", CLOSE_PATH, 503, _set("reads_composed", False), "owner", ON_A, _FULL, {}),
    ("reverse_ok", REVERSE_PATH, 202, _keep, "owner", ON_A, None, {}),
    ("reverse_unfilled", REVERSE_PATH, 202, lambda w: setattr(w.positions, "fill", "unfilled"),
     "owner", ON_A, None, {}),
    ("reverse_entry_refused", REVERSE_PATH, 202,
     lambda w: setattr(w.pipeline, "entry", ExchangeRejected(ret_code=110007)), "owner", ON_A,
     None, {}),
    ("reverse_no_key", REVERSE_PATH, 400, _keep, "owner", ON_A, None, {"idempotency-key": None}),
    ("reverse_no_session", REVERSE_PATH, 401, _keep, "nobody", ON_A, None, {}),
    ("reverse_not_armed", REVERSE_PATH, 403, _set("environment", "live"), "owner", ON_LIVE, None,
     {}),
    ("reverse_flag", REVERSE_PATH, 403, _set("oms_enabled", False), "owner", ON_A, None, {}),
    ("reverse_foreign", REVERSE_PATH, 404, _keep, "manager", ON_B, None, {}),
    ("reverse_in_flight", REVERSE_PATH, 409,
     _in_flight("reversePosition", reversal_refs(_KEY)[0]), "owner", ON_A, None, {}),
    ("reverse_no_stop", REVERSE_PATH, 422, _no_stop, "owner", ON_A, None, {}),
    ("reverse_body", REVERSE_PATH, 422, _keep, "owner", ON_A, {"size_mode": "same"}, {}),
    ("reverse_rate", REVERSE_PATH, 429, World.exhaust, "owner", ON_A, None, {}),
    ("reverse_no_oms", REVERSE_PATH, 501, _set("composed", False), "owner", ON_A, None, {}),
    ("reverse_close_rejected", REVERSE_PATH, 502, _close_rejected, "owner", ON_A, None, {}),
    ("reverse_not_ready", REVERSE_PATH, 503, _set("readiness", "starting"), "owner", ON_A, None,
     {}),
    ("all_ok", CLOSE_ALL_PATH, 200, _keep, "owner", "", {}, {}),
    ("all_null_symbol", CLOSE_ALL_PATH, 200, _keep, "owner", "", {"symbol": None}, {}),
    ("all_no_key", CLOSE_ALL_PATH, 400, _keep, "owner", "", {}, {"idempotency-key": None}),
    ("all_no_session", CLOSE_ALL_PATH, 401, _keep, "nobody", "", {}, {}),
    ("all_forbidden", CLOSE_ALL_PATH, 403, _keep, "viewer", "", {}, {}),
    ("all_scope", CLOSE_ALL_PATH, 403, _keep, "manager", "",
     {"exchange_account_ids": [str(MISSING)]}, {}),
    ("all_body", CLOSE_ALL_PATH, 422, _keep, "owner", "", {"symbol": "btc"}, {}),
    ("all_rate", CLOSE_ALL_PATH, 429, World.exhaust, "owner", "", {}, {}),
    ("all_no_oms", CLOSE_ALL_PATH, 501, _set("composed", False), "owner", "", {}, {}),
    ("all_not_ready", CLOSE_ALL_PATH, 503, _set("readiness", "starting"), "owner", "", {}, {}),
]  # fmt: skip


def _declared(path: str, status: int) -> Any:
    operation = _SPEC["paths"][path]["post"]
    responses = operation["responses"]
    assert str(status) in responses, f"{operation['operationId']} answers {status}, undeclared"
    [media] = deref(_SPEC, responses[str(status)])["content"].values()
    return media["schema"]


def _declared_headers(path: str, status: int) -> set[str]:
    """The response headers 22 names for `status` on `path`'s POST, lower-cased as sent."""
    response = deref(_SPEC, _SPEC["paths"][path]["post"]["responses"][str(status)])
    return {name.lower() for name in response.get("headers", {})}


def _close_all_members() -> Any:
    """The members of `closeAllPositions`' request body, as 22 declares them."""
    body = _SPEC["paths"][CLOSE_ALL_PATH]["post"]["requestBody"]["content"]["application/json"]
    return deref(_SPEC, body["schema"])["properties"]


def _named(count: int) -> dict[str, Any]:
    """A close-all body naming `count` accounts, none of which exists."""
    return {"exchange_account_ids": [str(uuid.uuid4()) for _ in range(count)]}


@pytest.mark.parametrize(
    ("case", "path", "status", "change", "who", "position", "body", "changes"),
    _CASES, ids=[c[0] for c in _CASES],
)  # fmt: skip
async def test_position_writes_contract_every_answer_is_declared_and_shaped(
    case: str, path: str, status: int, change: Callable[[World], None], who: str, position: str,
    body: Any, changes: dict[str, Any],
) -> None:  # fmt: skip
    world = World()
    change(world)
    world.route.environment = world.cancel_all.environment = world.environment
    sent = headers(who, key=_KEY)
    for name, value in changes.items():
        if value is None:
            sent.pop(name)
    async with world.client() as client:
        answer = await client.post(on(path, position), json=body, headers=sent)
    assert answer.status_code == status, f"{case}: {answer.text}"
    schema = _declared(path, status)
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(
        answer.json()
    )
    if "idempotency-replayed" in answer.headers:  # sent only where 22 declares it
        assert "idempotency-replayed" in _declared_headers(path, status), case


def test_position_writes_contract_each_declares_the_shared_unauthorized_for_no_session() -> None:
    """Step 1's `401` is the one shared `Unauthorized` on `closePosition`, `reversePosition` and
    `closeAllPositions` (E29-Q02, #1147); the `*_no_session` cases above drive it."""
    shared = {"$ref": "#/components/responses/Unauthorized"}
    for path in (CLOSE_PATH, REVERSE_PATH, CLOSE_ALL_PATH):
        assert _SPEC["paths"][path]["post"]["responses"].get("401") == shared, path


async def test_position_writes_contract_a_close_all_replay_carries_the_declared_header() -> None:
    """The same key and body answers the stored `200` with `Idempotency-Replayed: true`, a header
    22 declares on `closeAllPositions`' `200`; the first answer carries none."""
    world = World()
    first = await post(world, CLOSE_ALL_PATH, "owner", {}, key=_KEY)
    again = await post(world, CLOSE_ALL_PATH, "owner", {}, key=_KEY)
    assert (first.status_code, again.status_code) == (200, 200)
    assert "idempotency-replayed" not in first.headers
    assert again.headers["idempotency-replayed"] == "true" and again.json() == first.json()
    assert "idempotency-replayed" in _declared_headers(CLOSE_ALL_PATH, 200)
    declared = _SPEC["paths"][CLOSE_ALL_PATH]["post"]["responses"]["200"]["headers"]
    assert declared["Idempotency-Replayed"] == {"$ref": "#/components/headers/IdempotencyReplayed"}


async def test_position_writes_contract_close_all_refuses_more_ids_than_22_declares() -> None:
    """`exchange_account_ids` declares `maxItems`, the route's cap: that many ids is no refusal
    of the body's size (these ids name no account, so the scope refuses them, `403`), one more is
    refused as `validation_failed` naming the member, in a problem body 22 declares for the
    status it answers, and nothing is sent."""
    cap = _close_all_members()["exchange_account_ids"]["maxItems"]
    taken = close_all_body(json.dumps(_named(cap)).encode())
    assert isinstance(taken, CloseAllBody) and len(taken.exchange_account_ids) == cap
    refused = close_all_body(json.dumps(_named(cap + 1)).encode())
    assert not isinstance(refused, CloseAllBody) and refused[0].field == "exchange_account_ids"
    world = World()
    at_cap = await post(world, CLOSE_ALL_PATH, "owner", _named(cap))
    assert (at_cap.status_code, at_cap.json()["code"]) == (403, "account_scope_denied")
    over = await post(world, CLOSE_ALL_PATH, "owner", _named(cap + 1))
    assert over.json()["code"] == "validation_failed"
    assert over.json()["errors"][0]["field"] == "exchange_account_ids"
    Draft202012Validator(
        _declared(CLOSE_ALL_PATH, over.status_code),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(over.json())
    assert world.submitted() == []


async def test_position_writes_contract_close_all_symbol_null_is_no_symbol() -> None:
    """`symbol` is `oneOf [Symbol, null]` in 22, and `null` means what omitting it does: every
    symbol. The declared body accepts it, and the route sends the same closes either way."""
    symbol = _close_all_members()["symbol"]
    validator = Draft202012Validator(symbol, format_checker=Draft202012Validator.FORMAT_CHECKER)
    assert [e.message for e in validator.iter_errors(None)] == []
    assert [e.message for e in validator.iter_errors("BTCUSDT")] == []
    assert [e.message for e in validator.iter_errors("btc")] != []  # still a symbol when set
    omitted, nulled = World(), World()
    assert (await post(omitted, CLOSE_ALL_PATH, "owner", {})).status_code == 200
    assert (await post(nulled, CLOSE_ALL_PATH, "owner", {"symbol": None})).status_code == 200
    assert nulled.submitted() == omitted.submitted() != []
