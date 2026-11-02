"""E12-Q04 (#420): `/market/klines` and `/market/bars` against `22-api-openapi.yaml`, with cases
generated from the contract at collection: the parameter matrix (`BarType` x getBars's param table,
`KlineInterval` x `price_type`, `BarLimit`), every documented status and error code, every
response validated against its raw schema, the members the server sends against those 22 declares
(both ways), `x-rbac`, the input bounds and SR-054. The server is `_market_world`'s app over
recorded data only (C-13.5).

One run of `_CASES` per module (`run`) feeds the checks, so each holds over the whole run whatever
order the tests run in; `test_contract_market_seeded_mutation_fails` runs them again over a
deliberately broken server, which each must refuse.

A documented value the server does not serve is pinned as the refusal it answers, naming the
alternative (`_AS_BUILT`, the one table of them), never skipped: a new documented value fails until
the server serves it or a row here says how it is refused.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from candleviewer.api import market, market_bars, market_response
from candleviewer.api.market import make_market_router
from candleviewer.api.market_bars import _BAR_TYPES
from candleviewer.bars.spec import WIRE_BAR_TYPES
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.klines import PATH, BybitKlineFetcher
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.ingestion.kline_backfill import KlineBackfillService
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.kline_read import KlineReadService
from tests._corpus import rest
from tests.contract._generated_contract import _REGISTRY, _URI, SPEC, _at, _deref, _members
from tests.contract._market_world import (
    BASE,
    KLINES_NOW_US,
    NO_SESSION,
    OPERATIONS,
    OTHER,
    READER,
    T0,
    MarketWorld,
    Resolver,
    bar_type_params,
    operation,
    required_permissions,
    response_ceiling,
)
from tests.contract.test_market_bars_contract import _iso
from tests.contract.test_market_klines_contract import _Hot

_HOUR_US: Final = 3_600_000_000
_CODES: Final = {e["code"]: e["status"] for e in SPEC["x-error-codes"]}
_SCHEMAS: Final = SPEC["components"]["schemas"]
_WS_BUNDLE: Final = Path(__file__).resolve().parents[4] / "docs" / "plan" / "ws-schema.json"
#: As built (#420 decisions D5, D6): `(parameter, value)` -> the alternative its 422
#: `validation_failed` names. getBars: ADR-0033 R1 builds no point-and-figure or Heikin-Ashi bars
#: and no ATR-sized renko bricks (OD6; G-E1, #535); `atr:` matches as a prefix. getKlines: only
#: trade klines are recorded (Q4). A row goes when the server serves its value.
_AS_BUILT: Final[Mapping[tuple[str, str], str]] = {
    ("bar_type", "pnf"): "bar_type=time",
    ("bar_type", "heikin_ashi"): "bar_type=time",
    ("param", "atr:"): "bar_type=time",
    ("price_type", "mark"): "price_type=trade",
    ("price_type", "index"): "price_type=trade",
    ("price_type", "premium_index"): "price_type=trade",
}
#: C2: the `code` each shared refusal carries for a market read where no route text names one
#: (`test_contract_market_c2_defaults_are_codes_of_their_shared_responses` ties each to 22).
_C2_DEFAULTS: Final = {
    400: "validation_failed",
    401: "unauthenticated",
    403: "forbidden",
    503: "store_unavailable",
}
#: Members 22 declares that no response of the run sends, each with the reason it is never sent
#: (`test_contract_market_dead_member_allowlist_is_justified_and_current`).
_DEAD_ALLOWED: Final = {
    "KlineResponse.meta.total": (
        "PageMeta: present only where a cheap exact count exists; neither route counts its "
        "window (`market_response.build_meta`)"
    ),
    **{
        member: (
            "#5396 contract first (C-6.1): declared before the server sends it; #5396's "
            "follow-up serves it and removes this row"
        )
        for member in (
            "KlineResponse.bars[].gap_before",
            "KlineResponse.bars[].partial",
            "KlineResponse.meta.spec_hash",
            "KlineResponse.meta.build_version",
            "KlineResponse.meta.stale",
        )
    },
}


def _alternative(query: Mapping[str, object]) -> str | None:
    """The alternative an as-built refusal of `query` names; None when the query is served."""
    for (name, value), alternative in _AS_BUILT.items():
        sent = str(query.get(name, ""))
        if sent.startswith(value) if name == "param" else sent == value:
            return alternative
    return None


def _parameter(op: str, name: str) -> dict[str, Any]:
    """The parameter `name` of `op`, `$ref` followed."""
    for entry in operation(op)[1]["parameters"]:
        param = _at(_deref(entry["$ref"].removeprefix("#"))) if "$ref" in entry else entry
        if param["name"] == name:
            return cast(dict[str, Any], param)
    raise LookupError(f"{op} has no parameter {name}")


def _query(op: str, **over: object) -> dict[str, object]:
    """`op`'s 200 base query (getBars: tick bars of 100 prints), `over` applied; None drops one."""
    series = {"bar_type": "tick", "param": "100"} if op == "getBars" else {}
    return {k: v for k, v in {**BASE[op], **series, **over}.items() if v is not None}


#: The one-minute time series of each operation: the window caps, not the recording start, judge
#: a long window of it (a non-time window before recording is `no_data_recorded` first).
_TIME_SERIES: Final[Mapping[str, Mapping[str, str]]] = {
    "getBars": {"bar_type": "time", "param": "1"},
    "getKlines": {"interval": "1"},
}


@dataclass(frozen=True)
class Case:
    """One request of the run, and the status and `Problem.code` the contract gives it."""

    id: str
    op: str
    query: Mapping[str, object]
    status: int = 200
    code: str | None = None
    headers: Mapping[str, str] = field(default_factory=lambda: dict(READER))
    outage: bool = False
    ceiling: int | None = None  # `RESPONSE_MAX_BYTES` for this request (`response_ceiling`)
    pages: int = 1  # pages read by following `meta.next_cursor`, each one reached


def _documented(case_id: str, op: str, query: Mapping[str, object]) -> Case:
    """A documented value's case: served (200), or refused as built (`_AS_BUILT`)."""
    if _alternative(query) is None:
        return Case(case_id, op, query)
    return Case(case_id, op, query, 422, "validation_failed")


def _matrix() -> Iterator[Case]:
    """`BarType` x getBars's param table; `KlineInterval` x `price_type`; `BarLimit`'s bounds."""
    for bar_type, param in bar_type_params():
        query = _query("getBars", bar_type=bar_type, param=param, include_open="true")
        yield _documented(f"getBars:{bar_type}:{param}", "getBars", query)
    for interval in _SCHEMAS["KlineInterval"]["enum"]:
        for price_type in _parameter("getKlines", "price_type")["schema"]["enum"]:
            query = _query("getKlines", interval=interval, price_type=price_type, limit=50)
            yield _documented(f"getKlines:{interval}:{price_type}", "getKlines", query)
    for op in OPERATIONS:
        bounds = _parameter(op, "limit")["schema"]
        low, high = bounds["minimum"], bounds["maximum"]
        for limit in (low, high):
            yield Case(f"{op}:limit-{limit}", op, _query(op, limit=limit))
        for limit in (low - 1, high + 1):
            yield Case(f"{op}:limit-{limit}", op, _query(op, limit=limit), 422, "validation_failed")


def _statuses() -> Iterator[Case]:
    """A case for each documented status and code the matrix does not reach."""
    before = _iso(T0 - _HOUR_US)
    for op in OPERATIONS:
        yield Case(f"{op}:missing-from", op, _query(op, **{"from": None}), 400, "validation_failed")
        yield Case(f"{op}:foreign-cursor", op, _query(op, cursor="nope"), 400, "invalid_cursor")
        yield Case(f"{op}:no-session", op, _query(op), 401, "unauthenticated", NO_SESSION)
        yield Case(f"{op}:other-permissions", op, _query(op), 403, "forbidden", OTHER)
        over_cap = _query(op, **{"from": "2020-01-01T00:00:00Z"}, **_TIME_SERIES[op])
        yield Case(f"{op}:window-over-cap", op, over_cap, 422, "bar_window_too_large")
        yield Case(f"{op}:over-ceiling", op, _query(op), 422, "response_too_large", ceiling=256)
        unlisted = _query(op, symbol="NOPEUSDT")
        yield Case(f"{op}:unlisted-symbol", op, unlisted, 422, "validation_failed")
        yield Case(f"{op}:store-down", op, _query(op), 503, "store_unavailable", outage=True)
    yield Case("getBars:malformed-param", "getBars", _query("getBars", param="abc"), 400,
               "validation_failed")  # fmt: skip
    month = _query("getBars", bar_type="time", param="M")  # D3: a time param takes no `M`
    yield Case("getBars:time-month", "getBars", month, 400, "validation_failed")
    pre = _query("getBars", **{"from": before})
    yield Case("getBars:pre-recording", "getBars", pre, 422, "no_data_recorded")
    yield Case("getKlines:unknown-interval", "getKlines", _query("getKlines", interval="7"), 400,
               "validation_failed")  # fmt: skip


def _served() -> Iterator[Case]:
    """200s for the switches and the paths the matrix does not take: paging, order flow on and
    off, the forming bar and a window after the server's now (`meta.coverage_holes`)."""
    yield Case("getBars:paged", "getBars", _query("getBars", limit=2), pages=3)
    yield Case("getBars:no-order-flow", "getBars", _query("getBars", include_delta="false"))
    yield Case("getKlines:paged", "getKlines", _query("getKlines", limit=7), pages=3)
    yield Case("getKlines:order-flow", "getKlines", _query("getKlines", include_delta="true"))
    yield Case("getKlines:forming", "getKlines", _query("getKlines", include_open="true"))
    after = {"from": "2023-11-16T03:00:00Z", "to": "2023-11-16T04:00:00Z"}
    yield Case("getKlines:after-now", "getKlines", _query("getKlines", **after))


_CASES: Final = (*_matrix(), *_statuses(), *_served())


@dataclass(frozen=True)
class Seen:
    """One response of the run."""

    case: Case
    status: int
    media_type: str
    body: Any


def _send(world: MarketWorld, case: Case) -> list[Seen]:
    seen: list[Seen] = []
    query = dict(case.query)
    with response_ceiling(case.ceiling):
        for _ in range(case.pages):
            resp = world.get(case.op, query, case.headers)
            media = resp.headers["content-type"].partition(";")[0]
            seen.append(Seen(case, resp.status_code, media, resp.json()))
            cursor = seen[-1].body.get("meta", {}).get("next_cursor")
            if cursor is None:
                break
            query = {**case.query, "cursor": cursor}
    return seen


def _observe(cases: Iterable[Case]) -> dict[str, list[Seen]]:
    """Each case's responses, the outage ones from a world whose stores are down."""
    worlds = {False: MarketWorld(), True: MarketWorld(outage=True)}
    return {case.id: _send(worlds[case.outage], case) for case in cases}


@pytest.fixture(scope="module")
def run() -> dict[str, list[Seen]]:
    return _observe(_CASES)


def _all(run: Mapping[str, list[Seen]]) -> list[Seen]:
    return [seen for responses in run.values() for seen in responses]


# -- the checks: each raises `AssertionError` naming what broke ------------------------------------

_KLINE_RESPONSE: Final = "/components/schemas/KlineResponse"


def _response(op: str, status: int) -> dict[str, Any]:
    """The response 22 declares for `op`'s `status`, `$ref` followed."""
    response: dict[str, Any] = operation(op)[1]["responses"][str(status)]
    ref = response.get("$ref", "")
    return cast(dict[str, Any], _at(_deref(ref.removeprefix("#")))) if ref else response


def _response_schema(op: str, status: int) -> tuple[str, list[str]]:
    """`(media type, schemas)` of what 22 declares for `op`'s `status`: the schema a body must
    match, or each of the `anyOf` it must match one of (403: `Problem` or its trading form)."""
    ((media, content),) = _response(op, status)["content"].items()
    schema = content["schema"]
    return media, [b["$ref"].removeprefix("#") for b in schema.get("anyOf", [schema])]


@cache
def _validator(pointer: str) -> Draft202012Validator:
    """22's schema at `pointer`, its `format`s asserted where the checker knows them (`date-time`
    with `rfc3339-validator`): a timestamp must be RFC 3339, not only a string."""
    format_checker = Draft202012Validator.FORMAT_CHECKER
    ref = {"$ref": f"{_URI}#{pointer}"}
    return Draft202012Validator(ref, registry=_REGISTRY, format_checker=format_checker)


def _schema_errors(pointer: str, body: object) -> list[str]:
    return sorted(f"{e.json_path}: {e.message}" for e in _validator(pointer).iter_errors(body))


def _violations(seen: Seen) -> list[str]:
    """`seen` against 22: its status declared, its media type, and its body against the raw
    schema (JSON Schema 2020-12 over the contract itself, not the generated models, which ignore
    members they lack), each failure with its JSON path."""
    if str(seen.status) not in operation(seen.case.op)[1]["responses"]:
        return [f"{seen.case.id}: {seen.status} is not declared on {seen.case.op}"]
    media, schemas = _response_schema(seen.case.op, seen.status)
    found = [f"{seen.case.id}: sent {seen.media_type}, not {media}"] * (seen.media_type != media)
    errors = min((_schema_errors(pointer, seen.body) for pointer in schemas), key=len)
    return found + [f"{seen.case.id}: {error}" for error in errors]


def _check_valid(seen: Iterable[Seen]) -> None:
    found = [v for s in seen for v in _violations(s)]
    assert not found, "\n".join(found[:5])


def _variants(pointer: str) -> list[str]:
    """The schemas a value at `pointer` may match: itself, or each of its `anyOf`/`oneOf`."""
    pointer = _deref(pointer)
    node = _at(pointer)
    combiners = ((k, len(node.get(k, ()))) for k in ("anyOf", "oneOf"))
    branches = [f"{pointer}/{k}/{i}" for k, n in combiners for i in range(n)]
    return [v for branch in branches for v in _variants(branch)] or [pointer]


def _declared(variants: Iterable[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for variant in variants:
        found = _members(variant) | found
    return found


def _undeclared(value: object, schemas: list[str], path: str) -> Iterator[str]:
    """Each member of `value` (at JSON path `path`) that none of `schemas` declares."""
    variants = [variant for schema in schemas for variant in _variants(schema)]
    if isinstance(value, dict) and (declared := _declared(variants)):
        for name, member in value.items():
            if name not in declared:
                yield f"{path}.{name}: not declared by {' | '.join(variants)}"
                continue
            yield from _undeclared(member, [declared[name]], f"{path}.{name}")
    elif isinstance(value, list):
        items = [f"{v}/items" for v in variants if isinstance(_at(v).get("items"), dict)]
        for i, member in enumerate(value):
            yield from _undeclared(member, items[:1], f"{path}[{i}]")


def _check_declared(seen: Iterable[Seen]) -> None:
    """Emitted ⊆ declared: every member sent is in the schema of its status."""
    found = [
        f"{s.case.id}: {m}"
        for s in seen
        if str(s.status) in operation(s.case.op)[1]["responses"]
        for m in _undeclared(s.body, _response_schema(s.case.op, s.status)[1], "$")
    ]
    assert not found, "\n".join(found[:5])


def _declared_paths(pointer: str, prefix: str) -> set[str]:
    found: set[str] = set()
    for variant in _variants(pointer):
        for name, member in _members(variant).items():
            found |= {f"{prefix}.{name}", *_declared_paths(member, f"{prefix}.{name}")}
        if isinstance(_at(variant).get("items"), dict):
            found |= _declared_paths(f"{variant}/items", f"{prefix}[]")
    return found


def _sent_paths(value: object, prefix: str) -> set[str]:
    """The member paths `value` holds (`null` counts: the member was sent)."""
    if isinstance(value, dict):
        paths = ((f"{prefix}.{k}", v) for k, v in value.items())
        return {p for path, v in paths for p in (path, *_sent_paths(v, path))}
    if isinstance(value, list):
        return {p for v in value for p in _sent_paths(v, f"{prefix}[]")}
    return set()


def _dead_members(seen: Iterable[Seen]) -> list[str]:
    """The `KlineResponse` members 22 declares that no 200 of `seen` sent."""
    bodies = (s.body for s in seen if s.status == 200)
    sent = set[str]().union(*(_sent_paths(body, "KlineResponse") for body in bodies))
    return sorted(_declared_paths(_KLINE_RESPONSE, "KlineResponse") - sent)


def _check_no_dead_member(seen: Iterable[Seen]) -> None:
    """Declared ⊆ emitted, but for the justified `_DEAD_ALLOWED`."""
    dead = [m for m in _dead_members(seen) if m not in _DEAD_ALLOWED]
    assert not dead, f"22 declares members no response of the run sends: {dead}"


def _documented_codes(op: str) -> list[str]:
    """The codes 22 names for `op`: each catalogued slug its text and its parameters' cite, and
    C2's default of each refusal status it declares."""
    spec_op = operation(op)[1]
    params = [_at(_deref(p["$ref"].removeprefix("#"))) if "$ref" in p else p
              for p in spec_op["parameters"]]  # fmt: skip
    texts = [spec_op["description"], *(p.get("description", "") for p in params)]
    named = {slug for text in texts for slug in re.findall(r"`([a-z_]+)`", text) if slug in _CODES}
    defaults = {_C2_DEFAULTS[int(s)] for s in spec_op["responses"] if int(s) in _C2_DEFAULTS}
    return sorted(named | defaults)


def _catalogued(code: str) -> set[int]:
    """The statuses `code` may carry: its catalogue status, and 422 for `validation_failed` (the
    shared `UnprocessableEntity` example and the server serve it there too, until #2088)."""
    return {_CODES[code]} | ({422} if code == "validation_failed" else set())


# -- AC1: every documented response, status and code ---------------------------------------------


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.id)
def test_contract_market_every_documented_response_validates(
    run: dict[str, list[Seen]], case: Case
) -> None:
    """AC1: each response of the matrix and of the refusals is one 22 declares for its operation,
    in its declared media type, valid against its raw schema (formats included), with the case's
    status and code; a paged case reaches every page it asks for."""
    seen = run[case.id]
    _check_valid(seen)
    assert [(s.status, s.body.get("code")) for s in seen] == [(case.status, case.code)] * case.pages


@pytest.mark.parametrize("op", OPERATIONS)
def test_contract_market_every_documented_status_code_is_observed(
    run: dict[str, list[Seen]], op: str
) -> None:
    """AC1: the run observes exactly the statuses 22 documents for `op`: one never observed fails,
    and so does one it does not document (a 404, 405, 500 or 501)."""
    documented = {int(status) for status in operation(op)[1]["responses"]}
    assert {s.status for s in _all(run) if s.case.op == op} == documented


@pytest.mark.parametrize(
    ("op", "code"), [(op, code) for op in OPERATIONS for code in _documented_codes(op)]
)
def test_contract_market_every_documented_error_code_is_observed(
    run: dict[str, list[Seen]], op: str, code: str
) -> None:
    """Every code 22 names for `op` is observed by its code string, at its catalogue status."""
    found = {s.status for s in _all(run) if s.case.op == op and s.body.get("code") == code}
    assert found and found <= _catalogued(code), (code, found)


@pytest.mark.parametrize("status", sorted(_C2_DEFAULTS))
def test_contract_market_c2_defaults_are_codes_of_their_shared_responses(status: int) -> None:
    """Each C2 default is catalogued at its status and is an example code of the response both
    operations declare for that status."""
    examples = {
        example["value"]["code"]
        for op in OPERATIONS
        for content in _response(op, status)["content"].values()
        for example in content.get("examples", {}).values()
    }
    assert _CODES[_C2_DEFAULTS[status]] == status and _C2_DEFAULTS[status] in examples


# -- the parameter matrix, generated from 22 ------------------------------------------------------


def _answer(seen: Seen, alternative: str | None) -> tuple[object, ...]:
    """A matrix cell as asserted: a 200's status, the series it echoes, the tiers it names and
    whether it holds bars; a refusal's status, code and whether its detail names `alternative`."""
    body = seen.body
    if seen.status == 200:
        series = (body["bar_type"], body["interval"], body["meta"]["sources"], bool(body["bars"]))
        return (200, *series)
    return (seen.status, body["code"], alternative is not None and alternative in body["detail"])


def _cell(op: str, query: Mapping[str, object], served: tuple[object, ...]) -> tuple[object, ...]:
    return served if _alternative(query) is None else (422, "validation_failed", True)


_BAR_CELLS: Final = [
    pytest.param(bar_type, param, _cell("getBars", {"bar_type": bar_type, "param": param},
                                        (200, bar_type, param, ["tape"], True)),
                 id=f"{bar_type}-{param}")
    for bar_type, param in bar_type_params()
]  # fmt: skip
_KLINE_CELLS: Final = [
    pytest.param(interval, price_type, _cell("getKlines", {"price_type": price_type},
                                             (200, "time", interval, ["questdb"], True)),
                 id=f"{interval}-{price_type}")
    for interval in _SCHEMAS["KlineInterval"]["enum"]
    for price_type in _parameter("getKlines", "price_type")["schema"]["enum"]
]  # fmt: skip


@pytest.mark.parametrize(("bar_type", "param", "expected"), _BAR_CELLS)
def test_contract_market_bar_type_matrix(
    run: dict[str, list[Seen]], bar_type: str, param: str, expected: tuple[object, ...]
) -> None:
    """Every `BarType` with each example `param` of its row in the table: served from the tape,
    echoing the series; or refused as built, naming the alternative (`_AS_BUILT`)."""
    (seen,) = run[f"getBars:{bar_type}:{param}"]
    assert _answer(seen, _alternative({"bar_type": bar_type, "param": param})) == expected


@pytest.mark.parametrize(("interval", "price_type", "expected"), _KLINE_CELLS)
def test_contract_market_kline_matrix(
    run: dict[str, list[Seen]], interval: str, price_type: str, expected: tuple[object, ...]
) -> None:
    """Every `KlineInterval` with every `price_type`: served from the recorded klines, echoing
    the interval; or refused as built, naming the alternative (`_AS_BUILT`)."""
    (seen,) = run[f"getKlines:{interval}:{price_type}"]
    assert _answer(seen, _alternative({"price_type": price_type})) == expected


def test_contract_market_bar_types_agree_in_22_23_and_the_server() -> None:
    """22's `BarType`, 23's `barType` (the bundle the WS harness validates against) and the
    server's two lists (`bars.spec`, `api.market_bars`) name the same values, 22 and 23 in one
    order."""
    common = json.loads(_WS_BUNDLE.read_text(encoding="utf-8"))["schemas"]
    ws = common["cv://ws/v1/common.schema.json"]["$defs"]["barType"]["enum"]
    rest_types = _SCHEMAS["BarType"]["enum"]
    server = (set(WIRE_BAR_TYPES), set(_BAR_TYPES))
    assert (rest_types, set(rest_types), set(rest_types)) == (ws, *server)


# -- the drift guard, both ways -------------------------------------------------------------------


def test_contract_market_responses_declare_every_member_they_send(
    run: dict[str, list[Seen]],
) -> None:
    """Emitted ⊆ declared: no member of any response of the run is missing from the schema its
    status declares, each named with its JSON path and component (D1: a `no_data_recorded`
    refusal's `recording_started_at` is declared on `Problem`)."""
    _check_declared(_all(run))


def test_contract_market_kline_response_has_no_dead_member(run: dict[str, list[Seen]]) -> None:
    """Declared ⊆ emitted: every `KlineResponse` member 22 declares is sent by some 200 of the
    run (`null` counts), but for the justified `_DEAD_ALLOWED`."""
    _check_no_dead_member(_all(run))


@pytest.mark.parametrize("member", sorted(_DEAD_ALLOWED))
def test_contract_market_dead_member_allowlist_is_justified_and_current(
    run: dict[str, list[Seen]], member: str
) -> None:
    """Each allowlisted member says why, is still declared and is still never sent."""
    assert _DEAD_ALLOWED[member].strip() and member in _dead_members(_all(run))


# -- AC4: the pre-recording window on a non-time bar type ----------------------------------------


def test_contract_market_pre_recording_window_on_a_non_time_bar_type(
    run: dict[str, list[Seen]],
) -> None:
    """AC4: `bar_type=tick` from before `recording_started_at` is 422 `no_data_recorded`, the
    problem carrying `recording_started_at` and no `bars` or `meta` (so no REST kline substitution
    in `meta.sources`), and nothing is read; a non-time 200 names the tape as its only source."""
    world = MarketWorld()
    resp = world.get("getBars", _query("getBars", **{"from": _iso(T0 - _HOUR_US)}))
    body = resp.json()
    refused = (resp.status_code, body["code"], body.get("recording_started_at"), world.reads)
    assert refused == (422, "no_data_recorded", market_response.iso_us(T0), 0)
    assert not {"bars", "meta"} & set(body)
    served = (s for s in _all(run) if s.status == 200)
    non_time = [s for s in served if s.body["bar_type"] != "time"]
    assert non_time and {tuple(s.body["meta"]["sources"]) for s in non_time} == {("tape",)}


# -- security notes: x-rbac, the input bounds, SR-054 ---------------------------------------------

_ACTORS: Final = {"no-session": NO_SESSION, "other": OTHER, "reader": READER}
#: Per actor: status, code, data sent (`bars` and `meta`), storage read, the permission named.
_RBAC: Final = {
    "no-session": (401, "unauthenticated", False, False, False),
    "other": (403, "forbidden", False, False, True),
    "reader": (200, None, True, True, False),
}


@pytest.mark.parametrize("actor", list(_ACTORS))
@pytest.mark.parametrize("op", OPERATIONS)
def test_contract_market_x_rbac_is_enforced(op: str, actor: str) -> None:
    """22's `x-rbac`, server-side: no session is 401 `unauthenticated` and a session without the
    permission 403 `forbidden` naming it, neither given data nor a read; the permission alone
    (`Bearer reader` holds nothing else) is enough."""
    world = MarketWorld()
    resp = world.get(op, _query(op), _ACTORS[actor])
    body = resp.json()
    named = all(perm in body.get("detail", "") for perm in required_permissions())
    data = {"bars", "meta"} <= set(body)
    got = (resp.status_code, body.get("code"), data, world.reads > 0, named)
    assert got == _RBAC[actor]


def _too_long(bar_type: str) -> tuple[int, str]:
    """A `param` one character over `maxLength`: 400 naming the bound, or, for a type the server
    does not build, its as-built 422 first (`parse_bar_request`'s order)."""
    bound = _parameter("getBars", "param")["schema"]["maxLength"]
    alternative = _alternative({"bar_type": bar_type})
    return (400, f"at most {bound}") if alternative is None else (422, alternative)


@pytest.mark.parametrize(
    ("bar_type", "expected"), [(t, _too_long(t)) for t in _SCHEMAS["BarType"]["enum"]]
)
def test_contract_market_param_longer_than_max_length_is_refused(
    bar_type: str, expected: tuple[int, str]
) -> None:
    """`param`'s `maxLength` (22) holds server-side, before any read, for every `BarType`."""
    world = MarketWorld()
    too_long = "1" * (_parameter("getBars", "param")["schema"]["maxLength"] + 1)
    resp = world.get("getBars", _query("getBars", bar_type=bar_type, param=too_long))
    body = resp.json()
    status, named = expected
    got = (resp.status_code, body["code"], named in body["detail"], too_long in resp.text)
    assert (*got, world.reads) == (status, "validation_failed", True, False, 0)


@pytest.mark.parametrize("op", OPERATIONS)
def test_contract_market_limit_above_the_maximum_is_refused(op: str) -> None:
    """`BarLimit`'s maximum (22) is a hard bound, not a hint (SR-042 class): one over is 422
    `validation_failed` naming `query.limit`, the value never echoed; the maximum is served."""
    high = _parameter(op, "limit")["schema"]["maximum"]
    world = MarketWorld()
    over, at = (world.get(op, _query(op, limit=limit)) for limit in (high + 1, high))
    fields = [error["field"] for error in over.json().get("errors", [])]
    got = (over.status_code, over.json()["code"], fields, str(high + 1) in over.text)
    assert (*got, at.status_code) == (422, "validation_failed", ["query.limit"], False, 200)


class _Venue:
    """The governed REST client's `get_public`, recording each call and answering it from the
    recorded BTCUSDT 1m kline pages (`rest/kline_BTCUSDT_1_page{0,1,2}.json`) as the venue pages:
    the rows opening in `[start, end]`, newest first, at most `limit`."""

    def __init__(self) -> None:
        pages = [rest(f"rest/kline_BTCUSDT_1_page{i}.json") for i in range(3)]
        self._page = pages[0]
        rows = {row[0]: row for page in pages for row in page["result"]["list"]}
        self._rows = sorted(rows.values(), key=lambda row: -int(row[0]))
        self.calls: list[tuple[str, dict[str, Any], EndpointClass]] = []

    async def get_public(
        self, path: str, *, params: dict[str, Any], endpoint_class: EndpointClass
    ) -> dict[str, Any]:
        self.calls.append((path, dict(params), endpoint_class))
        rows = [r for r in self._rows if params["start"] <= int(r[0]) <= params["end"]]
        return {**self._page, "result": {**self._page["result"], "list": rows[: params["limit"]]}}


class _Cache:
    """The backfill's kline cache: empty (the window is a hot hole), keeping what a job writes."""

    def __init__(self) -> None:
        self.rows: list[object] = []

    async def read_klines(
        self, sym: str, interval: str, rng: Range, tier: str = "auto"
    ) -> list[Any]:
        return []

    async def write_klines(self, rows: Iterable[object]) -> None:
        self.rows += rows


async def _no_wait(_seconds: float) -> None: ...


def test_contract_klines_backfill_calls_carry_category_linear() -> None:
    """SR-054: a `/market/klines` window the hot tier lacks starts the exchange backfill, and every
    upstream call it makes, until the job ends, names `category=linear` in the `MARKET_DATA`
    bucket (C-12.7)."""
    venue, cache = _Venue(), _Cache()
    fetch = BybitKlineFetcher(cast(BybitRestClient, venue))
    backfill = KlineBackfillService(
        fetch_klines=fetch, cache=cache, sleep=_no_wait, now_us=lambda: KLINES_NOW_US
    )
    service = KlineReadService(_Hot([]), backfill=backfill)
    app = FastAPI()
    app.include_router(
        make_market_router(
            lambda: _Hot([]), principal_resolver=Resolver(), read_service_provider=lambda: service,
            symbol_listed=lambda symbol: symbol == "BTCUSDT", now_us=lambda: KLINES_NOW_US,
        )
    )  # fmt: skip
    query = _query("getKlines")
    window = Range(*(market_bars._ts_us(str(query[k])) or 0 for k in ("from", "to")))

    async def join() -> object:
        return await backfill.start_backfill("BTCUSDT", "1", window)

    with TestClient(app) as client:
        resp = client.get("/market/klines", params=query, headers=dict(READER))
        assert client.portal is not None
        client.portal.call(join)
    shapes = {(path, params["category"], bucket) for path, params, bucket in venue.calls}
    assert (resp.status_code, bool(cache.rows)) == (200, True)
    assert shapes == {(PATH, "linear", EndpointClass.MARKET_DATA)}


# -- the seeded mutations: each check above must refuse a broken server ---------------------------


def _drop_recording_started_at(mp: pytest.MonkeyPatch) -> None:
    """`meta.recording_started_at` dropped from every page both routes build."""

    def build_meta(**kw: Any) -> dict[str, object]:
        meta = market_response.build_meta(**kw)
        del meta["recording_started_at"]
        return meta

    mp.setattr(market, "build_meta", build_meta)
    mp.setattr(market_bars, "build_meta", build_meta)


def _numeric_price(mp: pytest.MonkeyPatch) -> None:
    """A bar's open sent as a JSON number, its value right (float serialisation, C6)."""

    def serialize_bar(row: Any, *, include_delta: bool) -> dict[str, object]:
        bar = market_response.serialize_bar(row, include_delta=include_delta)
        bar["o"] = float(str(bar["o"]))
        return bar

    mp.setattr(market_bars, "serialize_bar", serialize_bar)


def _naive_time(mp: pytest.MonkeyPatch) -> None:
    """Each bar's times sent with no offset (`2023-11-14T22:15:00`): a string still, but not the
    RFC 3339 `date-time` 22 declares."""

    def iso_naive(ts_us: int) -> str:
        return datetime.fromtimestamp(ts_us / 1_000_000, UTC).replace(tzinfo=None).isoformat()

    mp.setattr(market_response, "iso_us", iso_naive)


#: Mutation -> (how it is seeded, the check that must refuse it, what its failure names).
_MUTATIONS: Final[Mapping[str, tuple[Callable[[pytest.MonkeyPatch], None],
                                     Callable[[Iterable[Seen]], None], str]]] = {
    "drop-meta-recording_started_at": (
        _drop_recording_started_at, _check_no_dead_member,
        re.escape("KlineResponse.meta.recording_started_at"),
    ),
    "numeric-price": (
        _numeric_price, _check_valid, r"\$\.bars\[0\]\.o: [0-9.]+ is not of type 'string'"
    ),
    "naive-time": (
        _naive_time, _check_valid, r"\$\.bars\[0\]\.t: '[0-9T:.-]+' is not a 'date-time'"
    ),
}  # fmt: skip


@pytest.mark.parametrize("mutation", list(_MUTATIONS))
def test_contract_market_seeded_mutation_fails(
    mutation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ticket's negative self-test, REST half: over a server seeded with each mutation, the
    check that guards it fails, naming the member or the JSON path (the `close_t_ms` one is WS)."""
    seed, check, named = _MUTATIONS[mutation]
    seed(monkeypatch)
    served = _observe(case for case in _CASES if case.status == 200)
    with pytest.raises(AssertionError, match=named):
        check(_all(served))


# -- the conformance report's baseline (Q8) --------------------------------------------------------

_CASE_LIST: Final = Path(__file__).with_name("e12_q04_cases.txt")
_API: Final = Path(__file__).resolve().parents[2]


def test_contract_e12_q04_expected_cases_are_the_tests() -> None:
    """The committed case list (`e12_q04_cases.txt`, which `conftest.py`'s conformance report
    diffs each run against) names exactly the test functions its modules define: a listed case
    with no test fails here, and so does a test the list lacks."""
    lines = (line.partition("#")[0].strip() for line in _CASE_LIST.read_text("utf-8").splitlines())
    listed = {line for line in lines if line}
    defined = {
        f"{module}::{node.name}"
        for module in {case.partition("::")[0] for case in listed}
        for node in ast.parse((_API / module).read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }
    assert sorted(listed ^ defined) == []


def _report_plugin() -> Any:
    """`conftest.py`, loaded apart from pytest's own copy, so that its report hook can be called."""
    path = _CASE_LIST.with_name("conftest.py")
    spec = importlib.util.spec_from_file_location("e12_q04_report", path)
    assert spec is not None and spec.loader is not None
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    return plugin


class _Reporter:
    """The part of the terminal reporter the hook uses: outcomes in, lines out."""

    def __init__(self, passed: list[str]) -> None:
        self.stats = {"passed": [SimpleNamespace(nodeid=nodeid) for nodeid in passed]}
        self.lines: list[str] = []

    def section(self, title: str) -> None:
        self.lines.append(title)

    def write_line(self, line: str) -> None:
        self.lines.append(line)


def test_contract_e12_q04_report_prints_only_when_a_case_ran(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run that collected the E12-Q04 cases and ran none (a lane whose markers deselect them)
    prints nothing; once one ran, the matrix lists every case, the others as `NOT RUN`."""
    for name in ("CV_CONFORMANCE_REPORT_DIR", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(name, raising=False)
    plugin = _report_plugin()
    config = SimpleNamespace(stash=pytest.Stash())
    config.stash[plugin._COLLECTED] = set(plugin.expected_cases())
    first, *others = plugin.expected_cases()
    deselected = _Reporter(["tests/contract/test_market_tickers_contract.py::test_x"])
    ran = _Reporter([f"{first}[a-case]"])
    for reporter in (deselected, ran):
        plugin.pytest_terminal_summary(reporter, config)
    statuses = [line[:8].strip() for line in ran.lines[1:] if not line.startswith("::")]
    assert (deselected.lines, statuses) == ([], ["PASSED"] + ["NOT RUN"] * len(others))
