"""Contract, provider side (E29-Q02 #1147, C2; E29-TC-650, E29-TC-655): Schemathesis over the E29
operations, in process (C-6.2 names Schemathesis for a REST provider test; 03 asks for one per
endpoint). The operations come from 22 itself with every component kept; each case reaches the
real router of its operation through Schemathesis's ASGI client, with no socket (the network guard
stays on). Reads first, then each write. The routers run on the fakes of their own unit tests
(`_e29_oms_world`), not through `create_app()`: its fake backend composes no OMS, so each answers
`501` or `503` to a valid request (a position write refuses an invalid body first).

The hooks are the session's: the Owner's bearer, the SR-041 and arm tokens a request declares, a
fresh `Idempotency-Key` per request, and the world's id for a path parameter a case draws
well-formed. No hook maps or filters a body or a query; a case that broke a hooked member is
repaired (the guard is not under test here). A repeat under a key is a replay, whose
`Idempotency-Replayed` header 22 declares on none of `amendOrder`, `cancelOrder`,
`cancelAllOrders`, `closeAllPositions` and `setPositionLeverage`: the replay case is added once it
does. A key reused under another body is `closeAllPositions`' `500` where 22 lists `409` (F1,
#5855, fixed by #5873), pinned by the request sweep's `xfail`. No step-up is needed: `sl_loosen`, of
`setPositionTpSl`, is the one the E29 operations have.

Not driven: `setPositionTpSl` (`PUT /positions/{positionId}/tpsl`): no router serves it
(`rbac/matrix.yaml`: `not_mounted`), so there is no answer to judge and its step-up hook has
nothing to supply; `test_e29_the_one_operation_not_driven_is_not_mounted` fails once it is.

22 lists no `401` on `listOrders`, `getOrder`, `getOrderDiagnostics`, `listPositions`,
`getPosition`, `closePosition`, `reversePosition` and `setPositionLeverage` (its `info` says every
operation may answer one), so the copy of 22 here gives those the shared `Unauthorized`. It also
takes `"symbol": null` on `closeAllPositions` (`oneOf [Symbol, null]`): the route reads `null` as
no symbol, where 22 types a string alone (F2). #5868 declares it, which flips
`test_e29_22_declares_the_null_symbol_close_all_positions_takes`: delete `_null_symbol` and the
marker then.

Every built-in check runs but these, each left out for the reason given, which lies outside the
route's answer:

- `allow_header_conformance`: Starlette answers a method no route of a path serves from the first
  route that matched the path, so its `405` names that route's method alone (app-wide). It fails
  on six of the 15 operations only, but a list of six is one more to keep: all 15, as the
  user-settings module does.
- `positive_data_acceptance`, on `listOrders`, `listExecutions` and `listClosedPnl` (an issued
  cursor), `placeOrder`, `amendOrder`, `closePosition`, `reversePosition` and
  `setPositionLeverage` (a limit price, `pct` xor `qty`, a leverage inside the cap, a current
  `If-Match`, an algo that exists): 22 cannot say what a route also needs, so a request valid
  against 22 is refused by contract. The other seven operations keep it. (`reversePosition`
  passes at this seed, as no draw is a limit entry without its price: the rule stays true.)
- `missing_required_header`, on the writes: `X-CSRF-Token` is required, and SR-041's guard is the
  composed app's middleware, which these worlds do not run (the sweep drops `Idempotency-Key`).
- `unsupported_method`, on `cancelAllOrders` and `closeAllPositions`: their literal paths also
  match `/orders/{orderId}` and `/positions/{positionId}`, so `PATCH /orders/cancel-all` is
  `amendOrder`'s `400` (22's own path collision, the order the routers mount in).

`negative_data_rejection` expects 400, 401, 403 or 422: the hooks pin every well-formed path id to
the world's, so none is a `404`. The examples, coverage and fuzzing phases run, 25 fuzzed examples
per operation, derandomized with a fixed seed.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from collections.abc import Iterator, Sequence
from typing import Any, Final

import pytest
import schemathesis
import yaml
from hypothesis import settings
from jsonschema import Draft202012Validator
from schemathesis.specs.openapi.checks import (
    allow_header_conformance,
    missing_required_header,
    positive_data_acceptance,
    unsupported_method,
)
from starlette.routing import Match
from starlette.types import ASGIApp, Receive, Scope, Send

from tests.contract import _e29_oms_world as oms_world
from tests.contract._e29_oms_world import (
    ARM,
    GROUP_OF,
    OWNER,
    Served,
    build,
    fresh_key,
    parameters,
    supply,
    tokens,
)
from tests.contract._generated_contract import SPEC
from tests.contract.rbac.rbac_harness import MATRIX_PATH
from tests.unit.api import test_position_leverage_route as leverage_route

_READS: Final = (
    "listOrders", "getOrder", "getOrderDiagnostics", "listPositions", "getPosition",
    "listExecutions", "listClosedPnl",
)  # fmt: skip
_WRITES: Final = (
    "placeOrder", "amendOrder", "cancelOrder", "cancelAllOrders", "closePosition",
    "reversePosition", "closeAllPositions", "setPositionLeverage",
)  # fmt: skip
_NOT_DRIVEN: Final = ("setPositionTpSl",)
_NO_POSITIVE: Final = frozenset(
    {"listOrders", "listExecutions", "listClosedPnl", "placeOrder", "amendOrder", "closePosition",
     "reversePosition", "setPositionLeverage"}
)  # fmt: skip
_COLLIDING: Final = frozenset({"cancelAllOrders", "closeAllPositions"})
_CONFIG: Final = schemathesis.Config.from_str(
    "seed = 1147\n[checks]\nnegative_data_rejection.expected-statuses = [400, 401, 403, 422]\n"
)
#: The world's id of what a path parameter names, by operation (filled by the module fixture).
_PINS: Final[dict[str, dict[str, str]]] = {}


def _null_symbol(close_all: dict[str, Any]) -> None:
    """F2: `closeAllPositions` reads `"symbol": null` as no symbol, where 22 types it a string
    alone. #5868 declares `oneOf [Symbol, null]`, which makes this a no-op and flips the xfail
    below: delete both then."""
    members = close_all["requestBody"]["content"]["application/json"]["schema"]["properties"]
    if {"type": "null"} not in members["symbol"].get("oneOf", []):
        members["symbol"] = {"oneOf": [members["symbol"], {"type": "null"}]}


def _operations(operations: Sequence[str]) -> dict[str, Any]:
    """22, copied once (Schemathesis rewrites what it loads) and cut to `operations`; one that
    lists no `401` gets the shared response, and `closeAllPositions` takes a null `symbol`."""
    spec: dict[str, Any] = copy.deepcopy(SPEC)
    paths: dict[str, Any] = {}
    for path, item in spec["paths"].items():
        kept = {
            m: op
            for m, op in item.items()
            if isinstance(op, dict) and op.get("operationId") in operations
        }
        if kept:
            paths[path] = {**kept, "parameters": item.get("parameters", [])}
            for op in kept.values():
                op["responses"].setdefault("401", {"$ref": "#/components/responses/Unauthorized"})
                if op["operationId"] == "closeAllPositions":
                    _null_symbol(op)
    spec["paths"] = paths
    return spec


class _LateApp:
    """The ASGI app every case and probe reaches, bound at import as Schemathesis requires; it
    forwards to the worlds the module fixture builds, never at import, so their patch never
    reaches another module's collection. A request goes to the first world whose router serves its
    method and path (else to one that serves the path for another method, whose `405` it then is,
    else to the first, whose `404`), from the loopback peer every other client of a world uses."""

    served: Sequence[Served] = ()

    def _pick(self, scope: Scope) -> ASGIApp:
        assert self.served, "the module fixture binds the worlds first"
        other: ASGIApp | None = None
        for world in self.served:
            if scope["type"] != "http" or (world.methods and scope["method"] not in world.methods):
                continue
            found = {route.matches(scope)[0] for route in world.app.router.routes}
            if Match.FULL in found:
                return world.app
            if Match.PARTIAL in found and other is None:
                other = world.app
        return other or self.served[0].app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._pick(scope)({**scope, "client": ("127.0.0.1", 50000)}, receive, send)


_APP: Final = _LateApp()
#: One copy of 22 for both views, so a method no operation declares meets a `405` as the check
#: for it expects, whichever view probes it.
_SCHEMA: Final = schemathesis.openapi.from_dict(_operations((*_READS, *_WRITES)), config=_CONFIG)
reads: Final = _SCHEMA.include(operation_id=list(_READS))
writes: Final = _SCHEMA.include(operation_id=list(_WRITES))
reads.app = writes.app = _APP
#: The routes sit at the root, not under 22's `/api/v1` servers, hence the base URL.
_BASE_URL: Final = "http://testserver"


@pytest.fixture(scope="module", autouse=True)
def _world() -> Iterator[None]:
    """A world per group of operations, built for this module only; its patch is undone after it."""
    mp = pytest.MonkeyPatch()
    try:

        async def serve() -> dict[str, Served]:
            return {group: await build(group, mp) for group in dict.fromkeys(GROUP_OF.values())}

        worlds = asyncio.run(serve())
        _APP.served = list(worlds.values())
        _PINS.update({op: dict(worlds[group].pins) for op, group in GROUP_OF.items()})
        yield
    finally:
        _APP.served = ()
        _PINS.clear()
        mp.undo()


class _Owner:
    """The Owner's session: its bearer (`_hooks` adds the rest of what a write needs)."""

    def get(self, case: schemathesis.Case[Any], ctx: schemathesis.AuthContext) -> str:
        return OWNER

    def set(self, case: schemathesis.Case[Any], data: str, ctx: schemathesis.AuthContext) -> None:
        case.headers["Authorization"] = f"Bearer {data}"


reads.auth()(_Owner)
writes.auth()(_Owner)


def _well_formed(value: object) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


def _hooks(case: schemathesis.Case[Any]) -> str:
    """The hooks a case meets, then its operation's id: the SR-041 and arm tokens a request
    declares (a case that broke one is repaired), a fresh key in place of a well-formed one (a
    malformed or missing key is left for the route to refuse), and the world's id for each
    well-formed path parameter (a malformed one is left too)."""
    operation: str = case.operation.definition.raw["operationId"]
    declared = {header.name for header in case.operation.headers}
    case.headers.update(tokens(declared))
    if _well_formed(case.headers.get("Idempotency-Key")):
        case.headers["Idempotency-Key"] = fresh_key()
    for name, value in list(case.path_parameters.items()):
        if _well_formed(value):
            case.path_parameters[name] = _PINS[operation][name]
    return operation


def _excluded(operation: str) -> list[Any]:
    """The checks left out for `operation` (module docstring)."""
    return [
        allow_header_conformance,
        *([positive_data_acceptance] if operation in _NO_POSITIVE else []),
        *([missing_required_header] if operation in _WRITES else []),
        *([unsupported_method] if operation in _COLLIDING else []),
    ]


@reads.parametrize()
@settings(max_examples=25, derandomize=True, deadline=None, database=None)
def test_e29_reads_schemathesis_fuzz(case: schemathesis.Case[Any]) -> None:
    """Each generated request is answered with a status the operation declares, in its declared
    media type and schema, and a request outside the schema is refused (400, 401, 403, 422)."""
    case.call_and_validate(base_url=_BASE_URL, excluded_checks=_excluded(_hooks(case)))


@writes.parametrize()
@settings(max_examples=25, derandomize=True, deadline=None, database=None)
def test_e29_writes_schemathesis_fuzz(case: schemathesis.Case[Any]) -> None:
    """The same for each write, under the session's hooks."""
    case.call_and_validate(base_url=_BASE_URL, excluded_checks=_excluded(_hooks(case)))


def test_e29_every_operation_22_has_under_its_paths_is_driven_or_listed() -> None:
    """An operation of 22 under `/orders`, `/positions` or `/executions` that is neither driven
    here nor listed as not driven fails here."""
    declared = {
        op["operationId"]
        for path, item in SPEC["paths"].items()
        if path.startswith(("/orders", "/positions", "/executions"))
        for op in item.values()
        if isinstance(op, dict)
    }
    assert declared == {*_READS, *_WRITES, *_NOT_DRIVEN}
    assert set(GROUP_OF) == {*_READS, *_WRITES}


def test_e29_the_one_operation_not_driven_is_not_mounted() -> None:
    """`setPositionTpSl` has no router: the RBAC pack's matrix, run against the real app, says
    `not_mounted` and fails once the route appears."""
    rows = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))["operations"]
    assert rows["PUT /positions/{positionId}/tpsl"]["state"] == "not_mounted"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="F2: 22 types closeAllPositions.symbol a string alone; #5868 declares it nullable, "
    "which flips this: delete _null_symbol and the marker",
)
def test_e29_22_declares_the_null_symbol_close_all_positions_takes() -> None:
    """The route reads `"symbol": null` as no symbol, as `cancelAllOrders`' does and 22 declares
    there; `_operations` relaxes the member in its copy until 22 declares it here."""
    asked = oms_world.inline(oms_world.operation("closeAllPositions")[2]["requestBody"])
    symbol = asked["content"]["application/json"]["schema"]["properties"]["symbol"]
    assert Draft202012Validator(symbol).is_valid(None)


@pytest.mark.parametrize("operation", _WRITES)
def test_e29_the_hooks_supply_every_header_22_requires_of_a_write(operation: str) -> None:
    """A header 22 makes required of a write that the hooks do not supply fails here."""
    headers = [p for p in parameters(operation) if p["in"] == "header"]
    required = {p["name"] for p in headers if p.get("required")}
    assert required <= set(supply({p["name"] for p in headers}))


async def test_e29_the_arm_token_the_hooks_supply_is_the_one_a_live_account_takes() -> None:
    """The demo worlds never ask for the token; on a live account's leverage change the world's arm
    records pass `ARM` alone (22 `ArmToken`), so the hooks' value is no other."""
    world = leverage_route.World(environment="live")
    bare = await leverage_route.put(world, OWNER, leverage_route.ON_LIVE)
    armed = await leverage_route.put(world, OWNER, leverage_route.ON_LIVE, arm=ARM)
    refusal = (bare.status_code, bare.json()["code"])
    assert (refusal, armed.status_code) == ((403, "session_not_armed"), 200)
