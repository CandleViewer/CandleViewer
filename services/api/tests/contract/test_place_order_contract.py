"""Contract, provider side (E29-T04 #913 slice 3G): each answer 22 lists for `placeOrder`, given by
the mounted route on fakes with no Postgres (`test_orders_route.World`: F's router over recording
doubles of the runtime, its pipeline, its anchors and its reads), meets 22 for its status: its media
type, its body against the schema 22 declares there (2020-12, format checker), and each header it
sends declared there, with its type. `Idempotency-Replayed: true` comes on every repeat and
`Retry-After` where 22 promises it, equal to `retry_after_seconds`; neither comes anywhere else, but
the store and audit `503`s may carry `Retry-After`, which `ServiceUnavailable` declares (equal too).
No answer carries `ETag` until `amendOrder` checks it (slice 4). Each body meets its narrower schema
too: the gate's `403` is a `TradingDisabledProblem`, every other `trading_disabled` a plain
`Problem` with no `reason`, and the `502` an `OrderExchangeProblem` whose `exchange` is the return
code alone. Left out, as no answer of this route: the `422` 22 lists (its examples predate the
registry statuses, `400` and `403`, 22 `UnprocessableEntity`; the listing test tolerates it), the
per-user `429 rate_limited` of every route (the rate limiter's, Q14), and the middleware's `403`s in
front of the route (CSRF, the view-as guard, MFA enrolment)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any, NamedTuple

import httpx
import pytest
from jsonschema.exceptions import ValidationError

from candleviewer.oms.errors import (
    ClockDriftBlocked,
    ExchangeUnavailable,
    LotSizeViolation,
    OmsError,
    OrderEntryRefused,
    OrderLinkIdExhausted,
    ProfileNotFound,
    RateBudgetExceeded,
    RiskRefused,
    StopRequestPending,
    TickSizeViolation,
    TradingDisabled,
)
from candleviewer.oms.idempotency import InFlight, KeyReuse
from candleviewer.oms.submit import SubmitOutcome
from tests.contract._admin_support import SPEC, validate_example
from tests.unit.api.test_order_acceptance import (
    first_entry,
    first_reduce_only,
    read_entry,
    replay_of,
)
from tests.unit.api.test_orders_route import (
    _REDUCE,
    BODY,
    FOREIGN,
    GATE,
    KEY,
    MANAGER,
    World,
    _anchor,
    _live,
    _replay,
    post,
)

_PLACE: Any = SPEC["paths"]["/orders"]["post"]
#: A business rejection's first answer, and the send's refusal at the rate budget (24 Sec.8.4).
_REJECTED = SubmitOutcome(502, KEY, MANAGER, None, "rejected", "exchange_error", ret_code=110007)
_SHED = replace(
    first_entry(), status=429, lifecycle="rejected", code="exchange_rate_limited", retry_after_s=3
)


def _declared(status: int) -> tuple[str, dict[str, Any]]:
    """The JSON pointer of 22's `placeOrder` response for `status`, and that response, read
    through the shared response it names."""
    pointer, response = f"/paths/~1orders/post/responses/{status}", _PLACE["responses"][str(status)]
    if "$ref" in response:
        pointer = response["$ref"].removeprefix("#")
        response = SPEC["components"]["responses"][pointer.rsplit("/", 1)[1]]
    return pointer, response


def conforms(answer: httpx.Response) -> dict[str, Any]:
    """`answer`'s body once its media type, its body and each header it sends are those 22
    declares for its status; a `Retry-After` equals the body's `retry_after_seconds`."""
    pointer, response = _declared(answer.status_code)
    (media,) = response["content"]
    assert answer.headers["content-type"].partition(";")[0] == media
    body: dict[str, Any] = answer.json()
    validate_example(f"{pointer}/content/{media.replace('/', '~1')}/schema", body)
    declared = {name.lower(): spec for name, spec in response.get("headers", {}).items()}
    sent = {"retry-after", "idempotency-replayed", "etag"} & set(answer.headers)
    assert sent <= set(declared), f"{answer.status_code} sends {sent - set(declared)} undeclared"
    for name in sent:
        schema = declared[name]["$ref"].removeprefix("#") + "/schema"
        validate_example(schema, json.loads(answer.headers[name]))
    if "retry-after" in sent:
        assert int(answer.headers["retry-after"]) == body["retry_after_seconds"]
    return body


def _as_is(world: World) -> None:
    """F's `World` unchanged: the pipeline answers an entry's first `202`."""


def _raises(error: OmsError) -> Callable[[World], None]:
    """The pipeline refuses with `error`, recorded by it before it raises (24 Sec.8.4)."""
    return lambda world: setattr(world.oms.submission, "error", error)


def _answers(outcome: SubmitOutcome) -> Callable[[World], None]:
    return lambda world: setattr(world.oms.submission, "outcome", outcome)


def _replays(outcome: SubmitOutcome) -> Callable[[World], None]:
    """Step 8 meets a decided anchor, whose repeat the pipeline answers with `outcome`."""
    return lambda world: _replay(world, outcome)


def _replayed_entry(world: World) -> None:
    """A decided anchor's entry, its order `unknown` as read now (`reconciling`)."""
    first = first_entry()
    row, found = read_entry(first, state="unknown", lifecycle_state="unknown")
    world.oms.route.orders.rows[row.id], world.oms.route.groups.found = row, found
    _replay(world, replay_of(first, "unknown"))


def _audit_down(world: World) -> None:
    """The flag refuses, and that refusal's record cannot be written (C-2.9)."""
    world.flag, world.audit.fail = False, True


class Case(NamedTuple):
    """One answer: the world it is given in, its status, code and narrower schema, and whether it
    carries `Retry-After` (None: it may) and `Idempotency-Replayed`."""

    arrange: Callable[[World], None]
    status: int
    code: str | None
    schema: str = "Problem"
    retry_after: bool | None = False
    replayed: bool = False
    who: str = "owner"
    body: object = None


CASES: dict[str, Case] = {
    "202_entry": Case(_as_is, 202, None, "OrderAcceptance"),
    "202_reduce_only": Case(_answers(first_reduce_only()), 202, None, "OrderAcceptance",
                            body=_REDUCE),
    "202_anchor_replay": Case(_replayed_entry, 202, None, "OrderAcceptance", replayed=True),
    "400_validation_failed": Case(_as_is, 400, "validation_failed", body=BODY | {"price": None}),
    "400_tick_size": Case(_raises(TickSizeViolation()), 400, "tick_size_violation"),
    "400_lot_size": Case(_raises(LotSizeViolation()), 400, "lot_size_violation"),
    "403_forbidden": Case(_as_is, 403, "forbidden", who="viewer"),
    "403_scope": Case(_as_is, 403, "account_scope_denied", who="manager",
                      body=BODY | {"exchange_account_id": str(FOREIGN)}),
    "403_not_armed": Case(_live, 403, "session_not_armed"),
    "403_flag": Case(lambda w: setattr(w, "flag", False), 403, "trading_disabled"),
    "403_gate": Case(lambda w: setattr(w.oms.route.switches, "refuses", OrderEntryRefused(GATE)),
                     403, "trading_disabled", "TradingDisabledProblem"),
    "403_risk": Case(_raises(RiskRefused()), 403, "risk_limit_breached"),
    "404_profile": Case(_raises(ProfileNotFound()), 404, "not_found"),
    "409_reuse": Case(lambda w: _anchor(w, KeyReuse()), 409, "idempotency_key_reuse"),
    "409_in_flight": Case(lambda w: _anchor(w, InFlight(1)), 409, "idempotency_in_flight",
                          retry_after=True),
    "409_stop_request": Case(_raises(StopRequestPending(retry_after_s=1)), 409,
                             "stop_request_in_flight", retry_after=True),
    "429_headroom": Case(_raises(RateBudgetExceeded(retry_after_s=2)), 429,
                         "exchange_rate_limited", retry_after=True),
    "429_send": Case(_answers(_SHED), 429, "exchange_rate_limited", retry_after=True),
    "429_replayed": Case(_replays(replace(_SHED, written=None, retry_after_s=None, replayed=True)),
                         429, "exchange_rate_limited", replayed=True),
    "500_link_id_spent": Case(_raises(OrderLinkIdExhausted(first="a", last="b")), 500,
                              "internal_error"),
    "501_no_runtime": Case(lambda w: setattr(w, "runtime", None), 501, "not_implemented"),
    "501_no_principal_source": Case(lambda w: setattr(w, "principals", None), 501,
                                    "not_implemented"),
    "502_rejected": Case(_answers(_REJECTED), 502, "exchange_error", "OrderExchangeProblem"),
    "502_replayed": Case(_replays(replace(_REJECTED, replayed=True)), 502, "exchange_error",
                         "OrderExchangeProblem", replayed=True),
    "503_not_ready": Case(lambda w: setattr(w.oms, "state", "starting"), 503, "oms_not_ready",
                          retry_after=True),
    "503_store": Case(lambda w: setattr(w.oms.route.accounts, "fail", True), 503,
                      "store_unavailable", retry_after=None),
    "503_audit": Case(_audit_down, 503, "audit_unavailable", retry_after=None),
    "503_clock_drift": Case(_raises(ClockDriftBlocked(retry_after_s=5)), 503, "clock_drift",
                            retry_after=True),
    "503_exchange": Case(_raises(ExchangeUnavailable(retry_after_s=2)), 503,
                         "exchange_unavailable", retry_after=True),
}  # fmt: skip


@pytest.mark.parametrize("case", list(CASES.values()), ids=list(CASES))
async def test_each_answer_meets_the_schema_and_headers_22_declares_for_its_status(
    case: Case,
) -> None:
    world = World()
    case.arrange(world)
    answer = await post(world, case.who, case.body)
    body = conforms(answer)
    validate_example(f"/components/schemas/{case.schema}", body)
    assert (answer.status_code, body.get("code")) == (case.status, case.code)
    sent = "retry-after" in answer.headers  # equal to `retry_after_seconds` when it is: `conforms`
    assert case.retry_after is None or case.retry_after == sent
    assert answer.headers.get("idempotency-replayed") == ("true" if case.replayed else None)
    assert "etag" not in answer.headers  # until `amendOrder` checks it (#913 slice 4, Q11)


def test_every_status_22_lists_for_place_order_has_a_case_but_the_422() -> None:
    """22 `UnprocessableEntity`: the order routes answer `validation_failed` with `400` and
    `risk_limit_breached` with `403`, so the route gives no `422`."""
    listed = {int(status) for status in _PLACE["responses"]}
    assert listed - {case.status for case in CASES.values()} <= {422}


async def test_a_repeat_from_the_24h_record_is_the_first_202_replayed() -> None:
    world = World()
    first, repeat = await post(world), await post(world)
    conforms(first)
    assert conforms(repeat) == first.json() and repeat.content == first.content
    assert repeat.headers["idempotency-replayed"] == "true"
    assert "idempotency-replayed" not in first.headers


@pytest.mark.parametrize(
    "arrange",
    [
        lambda w: setattr(w, "flag", False),
        lambda w: setattr(w.oms.route.switches, "refuses", TradingDisabled()),
    ],
    ids=["oms_flag", "live_or_kill_switch"],
)
async def test_a_trading_disabled_without_the_gate_is_no_trading_disabled_problem(
    arrange: Callable[[World], None],
) -> None:
    """22 `Forbidden`: a client tells the gate's refusal by its `reason`, which only the gate's
    `403` carries."""
    world = World()
    arrange(world)
    body = conforms(await post(world))
    assert (body["code"], "reason" in body) == ("trading_disabled", False)
    with pytest.raises(ValidationError):
        validate_example("/components/schemas/TradingDisabledProblem", body)


async def test_a_502_carries_the_exchanges_return_code_alone() -> None:
    """SR-E29-09: never `ret_msg`, `endpoint` or `request_id`."""
    world = World()
    _answers(_REJECTED)(world)
    assert conforms(await post(world))["exchange"] == {"ret_code": 110007}
