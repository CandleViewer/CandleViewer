"""Contract, request direction (E29-Q02 #1147, C2; E29-TC-650, E29-TC-655): what each E29
operation takes in. One sweep over the eight writes (`placeOrder`, `amendOrder`, `cancelOrder`,
`cancelAllOrders`, `closePosition`, `reversePosition`, `closeAllPositions`,
`setPositionLeverage`) and the four lists (`listOrders`, `listPositions`, `listExecutions`,
`listClosedPnl`), each named by its `operationId` in 22. Every request is derived from 22's own
schemas: the sample is the first request example of the operation (else the simplest value its
schema names; a world value where 22 cannot say what a route's rule needs), and each refused
request is that sample with one member made to break its schema: an unknown member (a write must
refuse one, C-6.3), a value of another type, a value one past a bound 22 declares (`maxItems`,
`uniqueItems`, `minimum`, `maximum`, `maxLength`), a required member left out, or the body 22
requires left out. The test first checks that 22 refuses the request (and, for a bound, takes the
value at it), then asks the route on the fakes of its unit tests (`_e29_oms_world`): the sample is
accepted (a `2xx` 22 lists), a broken one is refused with `400` or `422`, as 22 lists for the
operation, a code of `x-error-codes` with the status the registry pairs with it, and the `Problem`
body its response declares.

F6, ruled: `validation_failed` is `400` everywhere (22's registry). Until #5855's fix (item 3)
moves them, `closePosition`, `reversePosition`, `closeAllPositions` and `setPositionLeverage` refuse
a body `422 validation_failed`, as 22's `setPositionLeverage` prose still says; the pairing is
relaxed on those four routes (`_F6`) and on no other, and a strict `xfail` pins the `400`: its flip
deletes `_F6` and the marker.

Left out, each for its reason: `X-CSRF-Token` (required by 22, but SR-041's guard is the composed
app's middleware, which these worlds do not run, and it answers `403`); `If-Match` (a plain
string: nothing to break); `X-Arm-Token` (an empty one, or one over 256 characters, reads as none:
a demo account never needs one, a live one answers `403 session_not_armed`); an unknown query
member of a list (the router ignores it, as every list does, and 22 declares no refusal); the three
reads by id (a path, whose `400` `test_oms_read_routes_contract` has, and `getOrder`'s
`include_events`, unit-tested in `test_oms_reads_route`); `setPositionTpSl` (no router serves it:
`test_e29_oms_schemathesis_contract` pins that). 22's lookup members of `listOrders`
(`idempotency_key`, `order_link_id`) are read by no route yet, so their wrong-type cases are
`xfail` (strict) and their bounds wait: #5552 implements the lookup, and its change deletes the
marker.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Final

import httpx
import pytest
from jsonschema import Draft202012Validator

from tests.contract._e29_oms_world import (
    GROUP_OF,
    Served,
    build,
    inline,
    operation,
    parameters,
    supply,
)
from tests.contract._generated_contract import SPEC
from tests.unit.api.oms_reads_world import ACCOUNT_A

_WRITES: Final = (
    "placeOrder", "amendOrder", "cancelOrder", "cancelAllOrders", "closePosition",
    "reversePosition", "closeAllPositions", "setPositionLeverage",
)  # fmt: skip
_LISTS: Final = ("listOrders", "listPositions", "listExecutions", "listClosedPnl")
_FORMATS: Final = Draft202012Validator.FORMAT_CHECKER
_STATUS: Final = {entry["code"]: entry["status"] for entry in SPEC["x-error-codes"]}
_ABSENT: Final = object()  # a member left out of a request
#: What a route's rule needs and 22 cannot say: a leverage within the cap, the lists' account.
_LEVERAGE: Final = {"leverage": "12.5"}
_ACCOUNTS: Final = {"exchange_account_ids": [str(ACCOUNT_A)]}
#: A body member's break: a value of another type than it takes (the first 22 refuses).
_STRANGERS: Final[tuple[Any, ...]] = (12345, "x", True, [], {}, None)
#: What 22 can bound a member by: the value one past each is a break.
_BOUNDS: Final = ("maxItems", "uniqueItems", "minimum", "maximum", "maxLength")
#: F6 (module docstring): the routes that refuse a body `422` until #5855 (item 3) moves them to
#: the `400` the registry pairs with `validation_failed`.
_F6: Final = frozenset(
    {"closePosition", "reversePosition", "closeAllPositions", "setPositionLeverage"}
)
#: 22's lookup (#2303) names two members no route reads yet: a list ignores them. #5552 implements
#: it and flips their cases (strict `xfail`): its change deletes this set and the marker.
_UNREAD: Final = {
    ("listOrders", "query", "idempotency_key"),
    ("listOrders", "query", "order_link_id"),
}


def accepts(schema: Any, value: Any) -> bool:
    """Whether 22's `schema` takes `value`; a lone value of an array parameter is its one item."""
    if schema.get("type") == "array" and not isinstance(value, list):
        schema = schema["items"]
    return Draft202012Validator(schema, format_checker=_FORMATS).is_valid(value)


def sample(schema: Any) -> Any:
    """The simplest value `schema` names: its first example, constant, default or enum value, else
    the one its type needs (an object: its required members)."""
    if schema.get("examples"):
        return schema["examples"][0]
    for key in ("const", "default"):
        if key in schema:
            return schema[key]
    if schema.get("enum"):
        return schema["enum"][0]
    for option in [*schema.get("oneOf", []), *schema.get("anyOf", [])]:
        if option.get("type") != "null":
            return sample(option)
    kind = schema.get("type")
    if kind == "object":
        return {name: sample(schema["properties"][name]) for name in schema.get("required", [])}
    if kind == "array":
        return [sample(schema["items"])]
    if kind == "string":
        found = {
            "uuid": "00000000-0000-4000-8000-000000000001",
            "date-time": "2026-01-01T00:00:00Z",
        }
        return found.get(schema.get("format"), "")
    return {"integer": schema.get("minimum", 0), "number": 0, "boolean": False}.get(kind)


def body_of(operation_id: str) -> tuple[dict[str, Any], Any] | None:
    """The request body schema of an operation, inlined, with its first example (else `_ABSENT`)."""
    content = inline(operation(operation_id)[2].get("requestBody", {})).get("content")
    if content is None:
        return None
    (media,) = content.values()
    named = [example["value"] for example in media.get("examples", {}).values()]
    return media["schema"], named[0] if named else _ABSENT


def body_required(operation_id: str) -> bool:
    """Whether 22 requires the request body of an operation (`requestBody.required`)."""
    return bool(operation(operation_id)[2].get("requestBody", {}).get("required"))


@dataclass(frozen=True)
class Request:
    """One request as 22 splits it: path values, query, headers and the JSON body."""

    operation: str
    path_values: dict[str, str]
    query: dict[str, Any]
    headers: dict[str, str]
    body: Any = _ABSENT

    def with_member(self, place: str, name: str, value: Any) -> Request:
        """A copy with member `name` of `place` (`path`, `query`, `header` or `body`) set to
        `value`, or taken out when that is `_ABSENT`."""
        attr = {"path": "path_values", "query": "query", "header": "headers", "body": "body"}[place]
        held = {**getattr(self, attr), name: value}
        changes: dict[str, Any] = {attr: {k: v for k, v in held.items() if v is not _ABSENT}}
        return replace(self, **changes)

    def conforms(self) -> bool:
        """Whether 22 takes this request: each member sent meets its schema, each required one
        is sent, and so is the body when 22 requires it."""
        sent = {"path": self.path_values, "query": self.query, "header": self.headers}
        for param in parameters(self.operation):
            held = sent[param["in"]]
            if param["name"] in held:
                if not accepts(param["schema"], held[param["name"]]):
                    return False
            elif param.get("required"):
                return False
        if self.body is _ABSENT:
            return not body_required(self.operation)
        found = body_of(self.operation)
        return found is None or accepts(found[0], self.body)


def valid_request(operation_id: str, served: Served) -> Request:
    """The sample of an operation: each query parameter at its simplest value, the world's id for
    each path parameter, the session's headers (`supply`), and 22's first request example (else
    the simplest body its schema names)."""
    params, query = parameters(operation_id), {}
    for param in (p for p in params if p["in"] == "query" and p["name"] != "cursor"):
        if accepts(param["schema"], value := sample(param["schema"])):
            query[param["name"]] = value
    path_values = {p["name"]: served.pins[p["name"]] for p in params if p["in"] == "path"}
    headers = supply({p["name"] for p in params if p["in"] == "header"})
    body: Any = _ABSENT
    if (found := body_of(operation_id)) is not None:
        schema, example = found
        body = sample(schema) if example is _ABSENT else example
        body = {**body, **(_LEVERAGE if operation_id == "setPositionLeverage" else {})}
    query |= _ACCOUNTS if operation_id in _LISTS else {}
    return Request(operation_id, path_values, query, headers, body)


async def send(request: Request, served: Served, *, raise_faults: bool = True) -> httpx.Response:
    """`request` to its operation's route, at the path and method 22 gives it. A fault the route
    lets out is raised, unless `raise_faults` is off: then it is the answer a client reads."""
    path, method, _ = operation(request.operation)
    transport = httpx.ASGITransport(
        app=served.app, raise_app_exceptions=raise_faults, client=("127.0.0.1", 50000)
    )
    sent: dict[str, Any] = {} if request.body is _ABSENT else {"json": request.body}
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.request(
            method, path.format(**request.path_values), params=request.query,
            headers=request.headers, **sent,
        )  # fmt: skip


def refused(request: Request, answer: httpx.Response) -> None:
    """`answer` is a refusal as 22 declares it for the operation: a `400` or `422` it lists, a code
    of the registry with the status the registry pairs with it (but `422 validation_failed` on the
    `_F6` routes), and the `Problem` its response names."""
    responses = operation(request.operation)[2]["responses"]
    assert answer.status_code in (400, 422), answer.text
    assert str(answer.status_code) in responses, f"22 lists no {answer.status_code}"
    body = answer.json()
    code = body["code"]
    assert code in _STATUS, body
    f6 = code == "validation_failed" and request.operation in _F6  # the one pairing relaxed
    paired = {_STATUS[code], *([422] if f6 else [])}
    assert answer.status_code in paired, f"22 pairs {code} with {_STATUS[code]}: {answer.text}"
    assert answer.headers["content-type"].startswith("application/problem+json")
    (media,) = inline(responses[str(answer.status_code)])["content"].values()
    Draft202012Validator(media["schema"], format_checker=_FORMATS).validate(body)


# --- the breaks, each derived from 22 -------------------------------------------------------


def _strange(schema: Any, place: str) -> Any:
    """A value `schema` refuses: in a body, one of another type than it takes; on the wire (a
    path, a query or a header: text) `x`, else a string too long for it."""
    long = "x" * (schema.get("maxLength", 0) + 1)
    candidates = _STRANGERS if place == "body" else ("x", long)
    return next(value for value in candidates if not accepts(schema, value))


def _members(*, required: bool) -> list[Any]:
    """`(operation, place, name)` of each member the sweep breaks, each a `pytest.param`: for a
    wrong type every member of a body, each path or query parameter and the key; for a missing
    one each required member of a body and the key (never `X-CSRF-Token`, module docstring)."""
    unread = pytest.mark.xfail(
        strict=True, reason="22's lookup (#2303, implemented by #5552) is read by no route yet"
    )
    found: list[tuple[str, str, str]] = []
    for operation_id in (*_WRITES, *_LISTS):
        body = body_of(operation_id)
        names = body[0].get("required" if required else "properties", []) if body else []
        found += [(operation_id, "body", name) for name in names]
        for param in parameters(operation_id):
            keyed = param["in"] == "header" and param["name"] == "Idempotency-Key"
            if keyed or (not required and param["in"] in ("path", "query")):
                found.append((operation_id, param["in"], param["name"]))
    return [
        pytest.param(*member, id="-".join(member), marks=unread if member in _UNREAD else ())
        for member in found
    ]


def _schema_of(operation_id: str, place: str, name: str) -> Any:
    """The schema 22 gives member `name` of `place` of an operation."""
    found = body_of(operation_id)
    if place == "body":
        assert found is not None
        return found[0]["properties"][name]
    params = parameters(operation_id)
    return next(p["schema"] for p in params if (p["in"], p["name"]) == (place, name))


def _bounds() -> list[Any]:
    """`(operation, place, name, bound)` for each of `_BOUNDS` that 22 declares on a member the
    sweep breaks, each a `pytest.param` (the lookup members of `_UNREAD` wait for their route)."""
    found = []
    for member in _members(required=False):
        if member.values not in _UNREAD:
            schema = _schema_of(*member.values)
            found += [
                pytest.param(*member.values, bound, id=f"{member.id}-{bound}")
                for bound in _BOUNDS
                if schema.get(bound, False) is not False
            ]
    return found


def _uuids(count: int) -> list[str]:
    """`count` distinct ids, the items of the lists 22 bounds."""
    return [f"00000000-0000-4000-8000-{n:012d}" for n in range(1, count + 1)]


def _beside(schema: Any, bound: str) -> tuple[Any, Any]:
    """The value at the `bound` 22 declares on `schema` (22 takes it) and the first one past it."""
    assert "items" not in schema or schema["items"].get("format") == "uuid", "extend _uuids"
    limit = schema[bound]
    match bound:
        case "maxItems":
            return _uuids(limit), _uuids(limit + 1)
        case "uniqueItems":
            return _uuids(2), _uuids(1) * 2
        case "minimum":
            return limit, limit - 1
        case "maximum":
            return limit, limit + 1
        case _:  # maxLength
            return "x" * limit, "x" * (limit + 1)


async def _asked(operation_id: str, patched: pytest.MonkeyPatch) -> tuple[Request, Served]:
    """The sample of an operation, with the fresh world it is asked of."""
    served = await build(GROUP_OF[operation_id], patched)
    return valid_request(operation_id, served), served


def test_request_direction_sweeps_every_write_and_list_22_declares() -> None:
    """A write or a list of 22 under the E29 paths that is not swept fails here, but for
    `setPositionTpSl`, which no router serves."""
    held = [
        (path, method, op["operationId"])
        for path, item in SPEC["paths"].items()
        if path.startswith(("/orders", "/positions", "/executions"))
        for method, op in item.items()
        if isinstance(op, dict)
    ]
    writes = {name for _, method, name in held if method != "get"}
    lists = {name for path, method, name in held if method == "get" and "{" not in path}
    assert writes - {"setPositionTpSl"} == set(_WRITES)
    assert lists == set(_LISTS)


@pytest.mark.parametrize("operation_id", [*_WRITES, *_LISTS])
async def test_request_direction_a_valid_sample_is_accepted(
    operation_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, served = await _asked(operation_id, monkeypatch)
    assert request.conforms()
    answer = await send(request, served)
    assert 200 <= answer.status_code < 300, answer.text
    assert str(answer.status_code) in operation(operation_id)[2]["responses"]
    assert (operation_id not in _LISTS) or served.world.store.calls  # the list read its store


@pytest.mark.parametrize("operation_id", [op for op in _WRITES if body_of(op) is not None])
async def test_request_direction_an_unknown_body_member_is_refused(
    operation_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, served = await _asked(operation_id, monkeypatch)
    request = request.with_member("body", "unexpected_member", 1)
    assert not request.conforms()  # 22 closes each body: `additionalProperties: false`
    refused(request, await send(request, served))


@pytest.mark.parametrize(("operation_id", "place", "name"), _members(required=False))
async def test_request_direction_a_member_of_the_wrong_type_is_refused(
    operation_id: str, place: str, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, served = await _asked(operation_id, monkeypatch)
    schema = _schema_of(operation_id, place, name)
    request = request.with_member(place, name, _strange(schema, place))
    assert not request.conforms()
    refused(request, await send(request, served))
    assert (operation_id not in _LISTS) or served.world.store.calls == []  # a list read nothing


@pytest.mark.parametrize(("operation_id", "place", "name"), _members(required=True))
async def test_request_direction_a_missing_required_member_is_refused(
    operation_id: str, place: str, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, served = await _asked(operation_id, monkeypatch)
    request = request.with_member(place, name, _ABSENT)
    assert not request.conforms()
    refused(request, await send(request, served))


@pytest.mark.parametrize(("operation_id", "place", "name", "bound"), _bounds())
async def test_request_direction_a_value_past_a_bound_22_declares_is_refused(
    operation_id: str, place: str, name: str, bound: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E29-TC-655: more than 25 account ids, a `limit` outside its range, a note too long: a `400
    validation_failed` (for now a `422` on the `_F6` routes), with nothing read. 22 takes the value
    at the bound, so the bound is the only break."""
    request, served = await _asked(operation_id, monkeypatch)
    within, past = _beside(_schema_of(operation_id, place, name), bound)
    assert request.with_member(place, name, within).conforms()
    request = request.with_member(place, name, past)
    assert not request.conforms()
    refused(request, await send(request, served))
    assert (operation_id not in _LISTS) or served.world.store.calls == []  # a list read nothing


@pytest.mark.parametrize("operation_id", [op for op in _WRITES if body_required(op)])
async def test_request_direction_an_absent_body_is_refused(
    operation_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E29-TC-655: a write whose body 22 requires, sent with none, is refused."""
    request, served = await _asked(operation_id, monkeypatch)
    request = replace(request, body=_ABSENT)
    assert not request.conforms()
    refused(request, await send(request, served))


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="F6 (#5855 item 3): the four position writes refuse a body 422, where validation_failed "
    "is 400 everywhere; its fix flips this: delete _F6 and the marker",
)
@pytest.mark.parametrize("operation_id", sorted(_F6))
async def test_request_direction_the_position_writes_refuse_a_body_with_400(
    operation_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`validation_failed` is `400` (22's registry, F6 ruled): the four position writes answer a
    body they refuse as every other write does."""
    request, served = await _asked(operation_id, monkeypatch)
    answer = await send(request.with_member("body", "unexpected_member", 1), served)
    assert answer.status_code == 400, answer.text
    assert answer.json()["code"] == "validation_failed"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="F1 (#5855): close-all lets IdempotencyKeyReuse escape, a 500 where 22 lists 409; "
    "its fix deletes this marker",
)
async def test_request_direction_a_key_reused_for_another_body_of_close_all_is_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """22 lists `409 idempotency_key_reuse` for `closeAllPositions`: a key whose answer is stored,
    sent again with another body, as a client reads it behind the app's error handler."""
    request, served = await _asked("closeAllPositions", monkeypatch)
    symbol = sample(_schema_of(request.operation, "body", "symbol"))
    other = request.with_member("body", "symbol", symbol)
    await send(request, served)
    again = await send(other, served, raise_faults=False)
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "idempotency_key_reuse"
