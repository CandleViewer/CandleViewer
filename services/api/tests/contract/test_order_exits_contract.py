"""Contract, provider side (E29-Q02 #1147, C1): each status 22 declares for `amendOrder`,
`cancelOrder` and `cancelAllOrders`, given by the mounted routes on the fakes of their unit tests
(`test_order_exits_route`, `test_order_amend_route`, `test_order_cancel_all_route`). An answer
meets 22 for its status as a client sees it: the media type, the body against the schema (2020-12,
format checker) with no member the schema leaves undeclared, each of `Retry-After`,
`Idempotency-Replayed` and `ETag` that it sends declared there with its type, `Retry-After` equal
to `retry_after_seconds`, and a problem's `code` the registry's for that status (E29-TC-650,
E29-TC-655); a status case also pins which answers carry `Retry-After`. The unit tests keep the
behaviour (what was sent, what was audited); a case here asserts what a client reads. Every status
22 declares has a case, each reachable on the fakes (the coverage test pins it).
`e29_q02_cases.txt` maps each test to the client-visible half of its plan cases
(`docs/qa/e29-oms-test-plan.md`). Not driven here, left to the unit tests: a Manager's request on a
recorded stop's row (E29-TC-107) and on an `unknown` order it placed (E29-TC-652)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from decimal import Decimal
from functools import cache, partial
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from jsonschema import Draft202012Validator

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.order_etag import order_etag
from candleviewer.api.order_exits import make_order_exits_router
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.observability.metrics import Metrics
from candleviewer.oms import commands as oc
from tests.openapi_helpers import deref
from tests.unit.api import test_order_amend_route as am
from tests.unit.api import test_order_cancel_all_route as ca
from tests.unit.api import test_order_exits_route as er
from tests.unit.api.test_order_acceptance import ACCOUNT
from tests.unit.api.test_orders_route import FOREIGN, KEY, MANAGER, SESSION
from tests.unit.oms import submit_rig as sr
from tests.unit.oms import test_exits as tx
from tests.unit.oms.submit_rig import SubmitRig

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_CODE_STATUS: dict[str, int] = {e["code"]: e["status"] for e in _SPEC["x-error-codes"]}
_FORMATS = Draft202012Validator.FORMAT_CHECKER
_ROUTES = {
    "amendOrder": ("/orders/{orderId}", "patch"),
    "cancelOrder": ("/orders/{orderId}", "delete"),
    "cancelAllOrders": ("/orders/cancel-all", "post"),
}
_MISSING = UUID("0e000000-0000-4000-8000-0000000000ee")  # no order, no account
_SENT_HEADERS = frozenset({"retry-after", "idempotency-replayed", "etag"})
# The unit tests' private names this module drives, bound once: a rename there fails here, at
# import, and not at a use site below.
_GONE, _RATE, _VENUE, _no, _TRADE = er._GONE, er._RATE, er._VENUE, er._no, er._TRADE
_CUT, _claimed = am._CUT, am._claimed
_full, _refused, _row, _stored = ca._full, ca._refused, ca._row, ca._stored
Drive = Callable[[], Awaitable[httpx.Response]]


@cache
def declared(operation: str) -> dict[str, Any]:
    """22's answers of `operation` by status, each with its `$ref`s inlined."""
    path, method = _ROUTES[operation]
    responses = _SPEC["paths"][path][method]["responses"]
    return {status: deref(_SPEC, response) for status, response in responses.items()}


def _undeclared(value: Any, schema: Any, path: str) -> Iterator[str]:
    """Each member of `value` that `schema` (inlined, its `allOf`, `anyOf` and `oneOf` read as one)
    does not declare, by its JSON path: `Problem` and `Order` admit extra members, which E29-TC-650
    still fails."""
    branches = [
        schema,
        *schema.get("allOf", []),
        *schema.get("anyOf", []),
        *schema.get("oneOf", []),
    ]
    members = {
        name: node for branch in branches for name, node in branch.get("properties", {}).items()
    }
    if isinstance(value, dict) and members:
        for name, member in value.items():
            if name in members:
                yield from _undeclared(member, members[name], f"{path}.{name}")
            else:
                yield f"{path}.{name}"
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, member in enumerate(value):
            yield from _undeclared(member, schema["items"], f"{path}[{index}]")


def conforms(operation: str, answer: httpx.Response) -> dict[str, Any]:
    """`answer`'s body once the answer meets what 22 declares for `operation` at its status."""
    response = declared(operation).get(str(answer.status_code))
    assert response is not None, f"{operation} answered {answer.status_code}: {answer.text}"
    [(media, content)] = response["content"].items()
    assert answer.headers["content-type"].partition(";")[0] == media
    body: dict[str, Any] = answer.json()
    schema = content["schema"]
    errors = [
        e.message for e in Draft202012Validator(schema, format_checker=_FORMATS).iter_errors(body)
    ]
    assert errors + [f"{p} is undeclared" for p in _undeclared(body, schema, "$")] == []
    headers = {
        name.lower(): header["schema"] for name, header in response.get("headers", {}).items()
    }
    sent = _SENT_HEADERS & set(answer.headers)
    assert sent <= set(headers), f"{answer.status_code} sends {sorted(sent - set(headers))}"
    for name in sent:  # an `ETag` is a quoted string as sent, every other header a JSON value
        value = answer.headers[name] if name == "etag" else json.loads(answer.headers[name])
        Draft202012Validator(headers[name], format_checker=_FORMATS).validate(value)
    retry = answer.headers.get("retry-after")
    assert body.get("retry_after_seconds") == (None if retry is None else int(retry))
    if answer.status_code >= 400:
        assert _CODE_STATUS.get(body["code"]) == answer.status_code, body["code"]
    return body


# --- each operation's cases: a status 22 declares, and the request that draws it ------------------


async def _cancel(
    held: str | None = "submitted", *settles: str | BaseException, who: str = "owner",
    order: str = "row", key: object = KEY, change: Callable[[er.World], None] | None = None,
    refuse: BaseException | None = None, **over: Any,
) -> httpx.Response:  # fmt: skip
    """`cancelOrder` on S4-C's scripted facade: B1 holds the order `held`, each of `settles` is one
    settle it answers, `refuse` is what its command raises, `over` replaces the exit service's
    dependencies (`er.scripted_world`)."""
    world, machines, row, _ = await er.scripted_world(held, *settles, **over)
    machines.refuse = refuse
    if change is not None:
        change(world)
    target = {"row": row.id, "missing": _MISSING}.get(order, order)
    return await er.delete(world, target, who, key)


async def _amend(
    held: str | None = "submitted", *settles: str, body: object = _CUT, who: str = "owner",
    order: str = "row", stale: bool = False, change: Callable[[er.World], None] | None = None,
    refuse: BaseException | None = None, **over: Any,
) -> httpx.Response:  # fmt: skip
    """`amendOrder` on the same facade, taking the `AMEND`; `stale` names the order's next version
    in `If-Match` (the facade's is 7)."""
    world, machines, row, _ = await er.scripted_world(held, *settles, **over)
    machines.refuse = refuse
    with pytest.MonkeyPatch.context() as patched:
        am.amending(machines, patched)
        am.routed(world, versions=machines)
        if change is not None:
            change(world)
        target = {"row": row.id, "missing": _MISSING}.get(order, order)
        tag = (("if-match", order_etag(row.id, 8)),) if stale else ()
        return await am.patch(world, target, body, who, fields=tag)


async def _cancel_all(
    who: str = "owner", body: object = None, key: object = KEY,
    change: Callable[[ca.World], None] | None = None,
) -> httpx.Response:  # fmt: skip
    """`cancelAllOrders` over the recording store: an Owner's two accounts, one open order each."""
    world = ca.World()
    if change is not None:
        change(world)
    return await ca.post(world, who, body, key)


def _scope_down(world: ca.World) -> None:
    """The store cannot be read for the scope: E29-TC-655."""
    world.oms.exits.scope_down = True


_DENIED = _no(oc.STORE_UNAVAILABLE)
_REFUSED = _no(_VENUE, exchange_ret_code=110003)
_NO_TOKEN = _no(_RATE, retry_after_s=4)


def _unwired(world: er.World) -> None:
    """No OMS composed (the fake backend): E29-TC-655."""
    world.composed = False


#: Each status 22 declares for an operation: the `code` its problem carries (None: no problem) and
#: the request that draws it, on the fakes of the unit tests.
Case = tuple[str | None, Drive]
_CANCEL: dict[str, Case] = {
    "202": (None, partial(_cancel, "submitted", "cancelled")),
    "400": ("validation_failed", partial(_cancel, order="not-a-uuid")),
    "401": ("unauthenticated", partial(_cancel, who="nobody")),
    "403": ("forbidden", partial(_cancel, who="viewer")),
    "404": ("not_found", partial(_cancel, order="missing")),
    "409": ("conflict", partial(_cancel, "unknown")),  # reconciliation decides an `unknown` order
    "429": ("exchange_rate_limited", partial(_cancel, "submitted", "submitted", answer=_NO_TOKEN)),
    "500": ("internal_error", partial(_cancel, refuse=RuntimeError("a defect at the facade"))),
    "501": ("not_implemented", partial(_cancel, change=_unwired)),
    "502": ("exchange_error", partial(_cancel, "submitted", "submitted", answer=_REFUSED)),
    "503": ("store_unavailable", partial(_cancel, "submitted", "submitted", answer=_DENIED)),
}
_AMEND: dict[str, Case] = {
    "202": (None, partial(_amend, "submitted", "submitted")),
    "400": ("validation_failed", partial(_amend, body={"qty": "0.005", "side": "sell"})),
    "401": ("unauthenticated", partial(_amend, who="nobody")),
    "403": ("forbidden", partial(_amend, who="viewer")),
    "404": ("not_found", partial(_amend, order="missing")),
    "409": ("idempotency_in_flight", partial(_amend, change=_claimed(KEY))),  # E29-TC-111
    "412": ("version_conflict", partial(_amend, stale=True)),  # E29-TC-111, E29-TC-509
    "422": ("order_not_amendable", partial(_amend, "cancel_pending")),  # E29-TC-509
    "429": ("exchange_rate_limited", partial(_amend, "submitted", "submitted", answer=_NO_TOKEN)),
    "500": ("internal_error", partial(_amend, refuse=RuntimeError("a defect at the facade"))),
    "501": ("not_implemented", partial(_amend, change=_unwired)),
    "502": ("exchange_error", partial(_amend, "submitted", "submitted", answer=_REFUSED)),
    "503": ("store_unavailable", partial(_amend, "submitted", "submitted", answer=_DENIED)),
}
_CANCEL_ALL: dict[str, Case] = {
    "200": (None, partial(_cancel_all)),
    "400": ("validation_failed", partial(_cancel_all, body={"accounts": []})),
    "401": ("unauthenticated", partial(_cancel_all, who="nobody")),
    "403": ("forbidden", partial(_cancel_all, who="viewer")),
    "409": ("idempotency_key_reuse", partial(_cancel_all, change=_stored)),
    "429": ("rate_limited", partial(_cancel_all, change=_full)),  # the guard holds all its keys
    "500": (
        "internal_error",
        partial(_cancel_all, change=lambda w: setattr(w.oms, "broken", True)),
    ),
    "501": ("not_implemented", partial(_cancel_all, change=lambda w: setattr(w, "runtime", None))),
    "503": ("store_unavailable", partial(_cancel_all, change=_scope_down)),
}
_TABLES = {"amendOrder": _AMEND, "cancelOrder": _CANCEL, "cancelAllOrders": _CANCEL_ALL}
#: The cases whose answer 22 gives a `Retry-After` (its prose on each operation, and
#: `ServiceUnavailable` for a cancel-all's scope outage): an amend's `idempotency_in_flight` 409,
#: each 429 and each 503 `store_unavailable`. The other 26 carry none; a cancel's `conflict` and a
#: cancel-all's `idempotency_key_reuse` 409s are no wait.
_RETRY = frozenset({
    ("amendOrder", "409"), ("amendOrder", "429"), ("amendOrder", "503"),
    ("cancelOrder", "429"), ("cancelOrder", "503"),
    ("cancelAllOrders", "429"), ("cancelAllOrders", "503"),
})  # fmt: skip


async def _answers(operation: str, status: str) -> dict[str, Any]:
    code, drive = _TABLES[operation][status]
    answer = await drive()
    assert answer.status_code == int(status), f"{operation}: {answer.status_code} {answer.text}"
    body = conforms(operation, answer)
    assert body.get("code") == code
    assert ("retry-after" in answer.headers) == ((operation, status) in _RETRY)
    return body


@pytest.mark.parametrize("status", _AMEND)
async def test_amend_order_each_declared_status_answers_as_22_declares_it(status: str) -> None:
    await _answers("amendOrder", status)


@pytest.mark.parametrize("status", _CANCEL)
async def test_cancel_order_each_declared_status_answers_as_22_declares_it(status: str) -> None:
    await _answers("cancelOrder", status)


@pytest.mark.parametrize("status", _CANCEL_ALL)
async def test_cancel_all_orders_each_declared_status_answers_as_22_declares_it(
    status: str,
) -> None:
    await _answers("cancelAllOrders", status)


@pytest.mark.parametrize("operation", _ROUTES)
def test_order_exits_every_status_22_declares_has_a_case(operation: str) -> None:
    """A status 22 declares with no case fails here, and so does a case for one it does not."""
    path, method = _ROUTES[operation]
    assert _SPEC["paths"][path][method]["operationId"] == operation
    assert sorted(set(_TABLES[operation]) ^ set(declared(operation))) == []


def test_order_exits_the_routers_serve_exactly_the_operations_driven_here() -> None:
    """A third operation on either router fails here until it has its cases (the docs routes of
    a bare app are no operation of the contract)."""
    exits = FastAPI()
    exits.include_router(
        make_order_exits_router(None, lambda: None, audit=er.Emitted(), metrics=Metrics("demo"))
    )
    served = served_operations(exits) | served_operations(ca.World().app())
    assert {op for op in served if op[1].startswith("/orders")} == {
        (method.upper(), path) for path, method in _ROUTES.values()
    }


# --- the plan's cases (E29-TC-nnn, docs/qa/e29-oms-test-plan.md) read as a client reads them ------


@pytest.fixture
async def rig() -> AsyncIterator[SubmitRig]:
    async with sr.rigged() as built:
        built.store.seed_owner(er.OWNER)
        yield built


async def test_cancel_order_of_a_final_order_is_202_with_the_order_as_it_stands() -> None:
    """E29-TC-652: no error, again under another key too, and nothing sent."""
    world, machines, row, _ = await er.scripted_world(None, stored="filled")
    for key in (KEY, ca.OTHER_KEY):
        answer = await er.delete(world, row.id, key=key)
        body = conforms("cancelOrder", answer)
        assert (answer.status_code, body["lifecycle_state"]) == (202, "filled")
    assert machines.sent == []


async def test_cancel_order_whose_record_cannot_be_written_is_503_audit_unavailable() -> None:
    """E29-TC-652 (C-2.9): the cancel of a final order is recorded ahead of its answer."""
    world, machines, row, port = await er.scripted_world(None, stored="filled")
    port.audits.refuse = RuntimeError("the audit WAL refused the record")
    answer = await er.delete(world, row.id)
    assert (answer.status_code, conforms("cancelOrder", answer)["code"]) == (
        503, "audit_unavailable",
    )  # fmt: skip
    assert machines.sent == []


async def test_cancel_order_the_exchange_reports_already_terminal_is_202_with_it_unknown() -> None:
    """E29-TC-104 (b): `110001` is no refusal (SR-E29-09): the order `unknown` until
    reconciliation ends it, and none of the exchange's text in the body."""
    answer = await _cancel("submitted", "unknown", answer=_GONE)
    body = conforms("cancelOrder", answer)
    assert (answer.status_code, body["lifecycle_state"]) == (202, "unknown")
    assert "exchange" not in body and "110001" not in answer.text


@pytest.mark.parametrize(
    ("settles", "stored", "state"),
    [
        (("cancelled",), "submitted", "cancelled"),
        ((TimeoutError(),), "cancel_pending", "cancel_pending"),
    ],
    ids=["settled_inside_the_wait", "still_in_flight_after_it"],
)
async def test_cancel_order_repeated_while_its_cancel_is_in_flight_is_202_as_it_then_stands(
    settles: tuple[str | BaseException, ...], stored: str, state: str
) -> None:
    """E29-TC-107: a repeat cancel answers the settled row, or `cancel_pending` when the first is
    still in flight after the 10 s wait (22 `cancelOrder`)."""
    answer = await _cancel("cancel_pending", *settles, stored=stored)
    body = conforms("cancelOrder", answer)
    assert (answer.status_code, body["lifecycle_state"]) == (202, state)


_SCOPE = [  # a Manager of the rig's account: who it is, what 22 answers it
    ("creator", 202, None), ("other", 403, "forbidden"), ("view_only", 403, "account_scope_denied"),
    ("ungranted", 404, "not_found"),
]  # fmt: skip


@pytest.mark.parametrize("operation", ["amendOrder", "cancelOrder"])
@pytest.mark.parametrize(("who", "status", "code"), _SCOPE, ids=[case[0] for case in _SCOPE])
async def test_order_exit_by_a_manager_answers_the_status_its_scope_gives_it(
    rig: SubmitRig, operation: str, who: str, status: int, code: str | None
) -> None:
    """E29-TC-107 (the creator rule) and the cross-account case (SR-E29-13): a Manager exits the
    orders it created; an order of an account it holds no grant on is `404`, as a missing one."""
    if operation == "amendOrder":
        world, row = await am.amendable(rig, who)
        answer = await am.patch(world, row.id, {"price": "60100"}, who)
    else:
        row = await tx.placed(rig)
        answer = await er.delete(er.granted(rig, who), row.id, who)
    body = conforms(operation, answer)
    assert (answer.status_code, body.get("code")) == (status, code)


async def test_amend_order_that_re_pairs_a_tp_sl_pair_is_202_with_both_sides_and_its_etag(
    rig: SubmitRig,
) -> None:
    """E29-TC-509: the stop tightened beside a new price, under `If-Match`, goes to the venue as one
    amend carrying the new price, the new stop and the take-profit at its current value (the pair
    re-sent whole), and the order answers 202 with its `ETag` and both sides."""
    world, row = await am.amendable(rig)
    version = rig.machines.version(row.id)
    assert version is not None
    body = {"price": "60100", "stop_loss": {"unit": "price", "value": "58500"}}
    answer = await am.patch(world, row.id, body, if_match=order_etag(row.id, version))
    order = conforms("amendOrder", answer)
    assert answer.status_code == 202 and "etag" in answer.headers
    [sent] = am.amends(rig)
    assert (sent.price, sent.stop_loss, sent.take_profit) == (60100, 58500, 64000)
    assert [Decimal(order[side]) for side in ("price", "stop_loss", "take_profit")] == [
        Decimal("60100"), Decimal("58500"), Decimal("64000"),
    ]  # fmt: skip


async def test_cancel_all_orders_failing_two_of_five_accounts_is_200_with_a_result_each() -> None:
    """E29-TC-105: an account's failure is its result, never a status; `requested`, `succeeded`."""
    world, accounts = ca.World(), [UUID(int=0xA000 + n) for n in range(5)]
    world.oms.exits.accounts = tuple(accounts)
    world.oms.store.rows = [_row(n, account) for n, account in enumerate(accounts, 1)]
    world.oms.exits.outcomes = {
        UUID(int=2): _refused("exchange_error", 502, ret_code=110017),
        UUID(int=4): _refused("store_unavailable", 503),
    }  # fmt: skip
    answer = await ca.post(world)
    body = conforms("cancelAllOrders", answer)
    assert (answer.status_code, body["requested"], body["succeeded"]) == (200, 5, 3)
    assert [r["exchange_account_id"] for r in body["results"]] == [str(a) for a in accounts]
    errors = [r["error"] for r in body["results"] if not r["ok"]]
    assert [(e["code"], e["retryable"]) for e in errors] == [
        ("exchange_error", False), ("store_unavailable", True),
    ]  # fmt: skip
    assert errors[0]["exchange_ret_code"] == 110017


def _managing(*accounts: UUID) -> Callable[[ca.World], None]:
    """The Manager granted `accounts` for trading, in its principal and in the store's rows."""

    def grant(world: ca.World) -> None:
        rows = tuple(AccountGrant(account, True, True, False) for account in accounts)
        snapshot = PrincipalSnapshot(MANAGER, frozenset({"manager"}), _TRADE, rows)
        assert world.principals is not None
        world.principals.tokens["manager"] = TradingPrincipal(SESSION, snapshot)
        world.oms.exits.grants[MANAGER] = rows

    return grant


#: E29-TC-110's accounts: the Manager is granted A, and B when it is granted both; a second account
#: that it is not granted (the plan's C) is refused. (who, grants, the ids named) -> (status, code,
#: results).
_A, _B, _DENY = ACCOUNT, FOREIGN, "account_scope_denied"
_ACCOUNTS = [
    ("a_and_c", "manager", (_A,), (_A, _B), 403, _DENY, None),
    ("a_and_b", "manager", (_A, _B), (_A, _B), 200, None, 2),
    ("no_ids", "manager", (_A,), (), 200, None, 1),
    ("missing_id", "manager", (_A,), (_A, ca.MISSING), 403, _DENY, None),
    ("viewer", "viewer", (_A,), (), 403, "forbidden", None),
]  # fmt: skip


@pytest.mark.parametrize(
    ("who", "grants", "ids", "status", "code", "results"),
    [case[1:] for case in _ACCOUNTS], ids=[case[0] for case in _ACCOUNTS],
)  # fmt: skip
async def test_cancel_all_orders_by_a_manager_answers_the_status_its_scope_gives_it(
    who: str, grants: tuple[UUID, ...], ids: tuple[UUID, ...], status: int, code: str | None,
    results: int | None,
) -> None:  # fmt: skip
    """E29-TC-110: a listed account outside the grants refuses the whole request; none listed is
    the granted accounts alone; no answer names an account the Manager may not trade."""
    world = ca.World()
    _managing(*grants)(world)
    answer = await ca.post(world, who, {"exchange_account_ids": [str(i) for i in ids]})
    body = conforms("cancelAllOrders", answer)
    assert (answer.status_code, body.get("code")) == (status, code)
    assert results is None or len(body["results"]) == results
    assert _B in grants or str(_B) not in answer.text  # only a granted account is named


async def test_cancel_all_orders_counts_in_affected_only_the_orders_its_selection_takes() -> None:
    """E29-TC-114 (the REST half): a reduce-only order only with `exclude_reduce_only: false`,
    never a recorded stop's row, never an order whose amend is in flight (C-2.6)."""
    world = ca.World()
    world.oms.store.rows = [
        _row(1),
        _row(2, intent="take_profit", reduce_only=True),
        _row(3, provenance="recorded_stop", intent="stop_loss", reduce_only=True),
        _row(4, intent="take_profit", reduce_only=True, lifecycle_state="amend_pending"),
    ]  # fmt: skip
    affected = []
    for exclude, key in ((True, KEY), (False, ca.OTHER_KEY)):
        body = {"exchange_account_ids": [str(ACCOUNT)], "exclude_reduce_only": exclude}
        answer = await ca.post(world, "owner", body, key)
        result = conforms("cancelAllOrders", answer)["results"][0]
        affected.append((answer.status_code, result["affected"]))
    assert affected == [(200, 1), (200, 2)]
