"""A rule save refuses what compile refuses, and the rule write routes cap the body they read.

Compile and `POST /rules/validate` hold a document to `check_bounds` (`MAX_ITEMS` values,
`MAX_DEPTH` levels). Every save applies the same bounds before the schema walks the document and
answers as it answers a schema error (422 `rule_ir_invalid`), storing nothing. The write routes,
validate and compile read the body under `MAX_RULE_BODY_BYTES` (413 `payload_too_large`) before it
is buffered whole, and leave it readable for a later reader. A note, a reason or a mode Postgres
cannot store, and a body nested deeper than a rule needs, are 400s. Inputs are built from those
constants.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from candleviewer.api.rule_body import MAX_RULE_BODY_BYTES, read_object
from candleviewer.domain.text import UNSTORABLE_TEXT
from candleviewer.rules.compiler.common import MAX_DEPTH, MAX_ITEMS, check_bounds
from candleviewer.rules.issues import RuleCompileError
from candleviewer.rules.manager import RuleError, is_reserved_name
from tests.rules.test_rules_manager import OWNER, _mgr
from tests.rules.test_rules_routes import A1, A2, _Env, _ir, _scoped
from tests.rules.test_scope_crud import A, C, _setup
from tests.rules.test_validator_endpoints import _P, RULE_ID, _client

CORPUS = Path(__file__).parents[1] / "fixtures/rule_corpus"
GOLDEN = json.loads((CORPUS / "golden_hashes.json").read_text(encoding="utf-8"))["hashes"]
RULES = {
    p.name: json.loads(p.read_text(encoding="utf-8"), parse_float=Decimal)
    for p in sorted(CORPUS.glob("[0-9][0-9]_*.json"))
}
#: The one corpus rule the save step refuses, bounds or not: it needs an Owner-only permission.
OWNER_ONLY = "20_widen_stop_through_funding_owner.json"
KINDS = pytest.mark.parametrize("kind", ["values", "depth"])
BOUNDS = [("$", "schema_error", "syntax")]
LIMITS = f"(limit {MAX_ITEMS} values, {MAX_DEPTH} levels)"
JSON = {"content-type": "application/json"}
#: A body nested past what the JSON decoder can recurse, still under the ceiling.
NESTING = MAX_RULE_BODY_BYTES // 2 - 16
#: The reader's own 400: a rule within the bounds nests `MAX_DEPTH + 2` levels in its body.
DEEPER = f"JSON nesting is deeper than {MAX_DEPTH + 2} levels."
WRITES = pytest.mark.parametrize("route", ["", "/{rid}", "/{rid}/active-version", "/{rid}/mode"])
CHECKS = pytest.mark.parametrize("path", ["/rules/validate", f"/rules/{RULE_ID}/compile"])


def _values(doc: Any) -> int:
    """Values as the bounds count them: every object, array and scalar, the document included."""
    stack, n = [doc], 0
    while stack:
        cur = stack.pop()
        n += 1
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return n


def _sized(values: int, **over: Any) -> dict[str, Any]:
    """A valid rule of exactly `values` values, the rest held in its free-form `graph_layout`."""
    doc = _ir(graph_layout={"pad": []}, **over)
    doc["graph_layout"]["pad"] = [0] * (values - _values(doc))
    return doc


def _nested(depth: int, **over: Any) -> dict[str, Any]:
    """A valid rule whose deepest value is `depth` levels down (`graph_layout` is level 1)."""
    leaf: Any = 0
    for _ in range(depth - 2):
        leaf = [leaf]
    return _ir(graph_layout={"pad": leaf}, **over)


def _over(kind: str, **over: Any) -> dict[str, Any]:
    """One past a bound: `MAX_ITEMS + 1` values, or a value `MAX_DEPTH + 1` levels down."""
    return _sized(MAX_ITEMS + 1, **over) if kind == "values" else _nested(MAX_DEPTH + 1, **over)


def _at(kind: str) -> dict[str, Any]:
    return _sized(MAX_ITEMS) if kind == "values" else _nested(MAX_DEPTH)


class _Unwalked(list[Any]):
    """A list the test fails on if anything iterates it: the bounds refuse it by its length."""

    def __iter__(self) -> Any:
        raise AssertionError("a container over the bound was walked")


def _issues(issues: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    return [(i["path"], i["code"], i["class"]) for i in issues]


def _bounds_problem(r: httpx.Response) -> None:
    assert r.status_code == 422, r.text[:300]
    body = r.json()
    assert body["code"] == "rule_ir_invalid" and _issues(body["issues"]) == BOUNDS
    assert LIMITS in body["detail"]


def _padded(size: int) -> bytes:
    """A valid create body, padded with whitespace to `size` bytes."""
    text = json.dumps({"ir": _ir()})
    return (text[:-1] + " " * (size - len(text)) + "}").encode()


def _too_large(r: httpx.Response) -> None:
    assert r.status_code == 413, r.text[:300]
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json() == {
        "type": "https://candleviewer.local/errors/payload_too_large",
        "title": "Request body or batch exceeds the operation's size ceiling",
        "status": 413,
        "code": "payload_too_large",
        "detail": f"The request body exceeds {MAX_RULE_BODY_BYTES} bytes.",
    }


def _deep(levels: int) -> bytes:
    """A body whose deepest array sits `levels` deep, the body's own object included."""
    return ('{"ir":' + "[" * (levels - 1) + "]" * (levels - 1) + "}").encode()


def _write(c: TestClient, route: str, rid: str, content: bytes) -> httpx.Response:
    """POST `/rules`, or a PUT to the write `route` names; raw bytes, so `\\u` escapes survive."""
    hdr = {**JSON, "If-Match": "1", "Idempotency-Key": "k"}
    url = "/rules" + route.format(rid=rid)
    return c.request("PUT" if route else "POST", url, content=content, headers=hdr)


# ----- the manager: every save -------------------------------------------------------------


@KINDS
async def test_create_document_over_a_bound_is_refused_and_stores_nothing(kind: str) -> None:
    m, audits, _ = _mgr()
    with pytest.raises(RuleError) as refused:
        await m.create(_over(kind), OWNER)
    assert (refused.value.status, refused.value.code) == (422, "rule_ir_invalid")
    assert _issues(refused.value.extra["issues"]) == BOUNDS and LIMITS in refused.value.message
    assert (await m.list_rules(OWNER))["items"] == [] and audits == []


@KINDS
async def test_update_document_over_a_bound_is_refused_and_writes_no_version(kind: str) -> None:
    m, audits, _ = _mgr()
    rid = (await m.create(_ir(), OWNER))["id"]
    with pytest.raises(RuleError) as refused:
        await m.update(rid, _over(kind, threshold="2"), 1, OWNER)
    assert (refused.value.status, refused.value.code) == (422, "rule_ir_invalid")
    assert _issues(refused.value.extra["issues"]) == BOUNDS
    assert [v["version"] for v in await m.versions(rid)] == [1]
    assert [a for a, _ in audits] == ["rule.created"]


@KINDS
async def test_save_document_at_the_bounds_is_stored(kind: str) -> None:
    m, _, _ = _mgr()
    rid = (await m.create(_at(kind), OWNER))["id"]
    renamed = {**_at(kind), "name": "renamed"}
    assert (await m.update(rid, renamed, 1, OWNER))["version"]["version"] == 2


def test_check_bounds_wide_container_over_the_bound_is_refused_before_it_is_walked() -> None:
    check_bounds({"pad": [0] * (MAX_ITEMS - 2)}, "rule")  # exactly at the bound: no refusal
    with pytest.raises(RuleCompileError, match="too large"):
        check_bounds({"pad": _Unwalked([0] * (MAX_ITEMS + 1))}, "rule")


async def test_import_rule_over_a_bound_is_refused_before_the_bundle_is_walked() -> None:
    m, audits, _ = _mgr()
    ir = _ir(graph_layout={"pad": _Unwalked([0] * (MAX_ITEMS + 1))})
    with pytest.raises(RuleError) as refused:
        await m.import_rule({"format": "cv-rule-bundle/1", "ir": ir}, OWNER)
    assert (refused.value.status, refused.value.code) == (422, "rule_ir_invalid")
    assert (await m.list_rules(OWNER))["items"] == [] and audits == []


async def test_create_over_a_bound_and_schema_invalid_answers_the_bounds_first() -> None:
    m, audits, _ = _mgr()
    with pytest.raises(RuleError) as refused:  # the same value count, and a schema error too
        await m.create({**_over("values"), "name": 123}, OWNER)
    assert _issues(refused.value.extra["issues"]) == BOUNDS and audits == []


@pytest.mark.parametrize("name", sorted(RULES))
async def test_save_corpus_rule_within_the_bounds_keeps_its_golden_hash(name: str) -> None:
    """No `ir_hash` moves: the step every save runs, bounds first, hashes each corpus rule to its
    golden, and each one the reserved names allow is stored."""
    doc, (m, _, _) = RULES[name], _mgr()
    if name == OWNER_ONLY:  # refused by the validator for a permission, never by the bounds
        with pytest.raises(RuleError) as refused:
            m._validated(doc, doc["rule_id"])
        assert [i["code"] for i in refused.value.extra["issues"]] == ["permission_required"]
        return
    assert m._validated(doc, doc["rule_id"])[1] == GOLDEN[name]
    if not is_reserved_name(doc["name"]):
        assert (await m.create(doc, OWNER))["version"]["version"] == 1


# ----- the routes: POST /rules and the version write ---------------------------------------


@KINDS
def test_post_rules_document_over_a_bound_is_422_and_stores_nothing(kind: str) -> None:
    e = _Env()
    _bounds_problem(e.c.post("/rules", json={"ir": _over(kind)}))
    assert e.c.get("/rules").json()["items"] == [] and e.audits == []


@KINDS
def test_put_rule_document_over_a_bound_is_422_and_writes_no_version(kind: str) -> None:
    e = _Env()
    rid = e.create()
    hdr, doc = {"If-Match": "1"}, _over(kind, threshold="2")
    _bounds_problem(e.c.put(f"/rules/{rid}", json={"ir": doc}, headers=hdr))
    assert e.c.get(f"/rules/{rid}/versions").json()["meta"]["count"] == 1
    assert [a for a, _ in e.audits] == ["rule.created"]


def test_post_rules_body_at_the_ceiling_is_read_and_one_byte_more_is_413() -> None:
    at, over, cap = _Env(), _Env(), MAX_RULE_BODY_BYTES
    body = _padded(cap)
    assert len(body) == cap and at.c.post("/rules", content=body, headers=JSON).status_code == 201
    _too_large(over.c.post("/rules", content=_padded(cap + 1), headers=JSON))
    assert over.c.get("/rules").json()["items"] == [] and over.audits == []


def test_post_rules_declared_length_over_the_ceiling_is_413_unread() -> None:
    e, cap = _Env(), MAX_RULE_BODY_BYTES
    small = json.dumps({"ir": _ir()}).encode()  # a valid body, its declared length over the ceiling
    _too_large(e.c.post("/rules", content=small, headers={**JSON, "content-length": str(cap + 1)}))
    assert e.c.get("/rules").json()["items"] == [] and e.audits == []


async def test_post_rules_streamed_body_over_the_ceiling_is_413_before_it_is_buffered() -> None:
    """No `Content-Length`: the stream is read one chunk past the ceiling, never to its end."""
    e, cap, pulled = _Env(), MAX_RULE_BODY_BYTES, []
    parts = [json.dumps({"ir": _ir()})[:-1].encode(), *[b" " * (cap // 16)] * 32, b"}"]

    async def chunks() -> AsyncIterator[bytes]:
        for part in parts:
            pulled.append(part)
            yield part

    transport = httpx.ASGITransport(app=e.c.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post("/rules", content=chunks(), headers=JSON)
    _too_large(r)
    assert "content-length" not in r.request.headers
    assert len(pulled) <= 16 + 2 < len(parts)
    assert (await e.mgr.list_rules(OWNER))["items"] == [] and e.audits == []


@pytest.mark.parametrize("route", ["", "/active-version", "/mode"])
def test_put_rule_body_over_the_ceiling_is_413_and_changes_nothing(route: str) -> None:
    e, cap = _Env(), MAX_RULE_BODY_BYTES
    rid = e.create()
    hdr = {**JSON, "If-Match": "1", "Idempotency-Key": "k"}
    _too_large(e.c.put(f"/rules/{rid}{route}", content=_padded(cap + 1), headers=hdr))
    assert e.c.get(f"/rules/{rid}").json()["latest_version"] == 1
    assert [a for a, _ in e.audits] == ["rule.created"]


def test_read_object_leaves_the_body_readable_for_a_later_reader() -> None:
    """Live arming's step-up reads the same request's JSON after the capped reader has run."""
    app = FastAPI()

    @app.post("/read")
    async def read(request: Request) -> JSONResponse:
        first = await read_object(request, lambda detail: JSONResponse({"detail": detail}, 400))
        return JSONResponse({"first": first, "again": await request.json()})

    r = TestClient(app).post("/read", json={"a": 1})
    assert r.json() == {"first": {"a": 1}, "again": {"a": 1}}


def test_post_rules_non_ascii_text_round_trips_and_a_body_not_utf8_is_400() -> None:
    e, name = _Env(), "règle-日本"
    sent = json.dumps({"ir": _ir(name=name), "note": "é"}, ensure_ascii=False).encode()
    r = e.c.post("/rules", content=sent, headers=JSON)
    assert (r.status_code, r.json()["name"], r.json()["version"]["notes"]) == (201, name, "é")
    bad = sent.replace("é".encode(), b"\xe9")  # one Latin-1 byte: not UTF-8
    assert e.c.post("/rules", content=bad, headers=JSON).status_code == 400
    assert len(e.c.get("/rules").json()["items"]) == 1


def test_post_rules_indented_document_at_the_value_bound_is_201_under_the_ceiling() -> None:
    assert MAX_RULE_BODY_BYTES == MAX_ITEMS * 100  # the derivation in `api/rule_body.py`
    doc = _ir(graph_layout={"pad": []})
    nodes = (MAX_ITEMS - _values(doc)) // 5  # five values each: the object and its four members
    pad = [{"id": f"n{i}", "type": "comparison", "x": 120, "y": 80} for i in range(nodes)]
    doc["graph_layout"]["pad"] = pad + [0] * (MAX_ITEMS - _values(doc) - 5 * nodes)
    body = json.dumps({"ir": doc}, indent=2).encode()
    assert _values(doc) == MAX_ITEMS
    assert _Env().c.post("/rules", content=body, headers=JSON).status_code == 201


@pytest.mark.parametrize(
    "value", [chr(0xD800), chr(0xDC00), chr(0), 7, None], ids=["high", "low", "nul", "int", "null"]
)
@pytest.mark.parametrize(
    ("route", "field", "sent"),
    [("", "note", {"ir": _ir("2", name="other")}), ("/{rid}", "note", {"ir": _ir("2")}),
     ("/{rid}/active-version", "note", {}), ("/{rid}/mode", "reason", {"mode": "simulate"})],
    ids=["create", "update", "active-version", "mode"],
)  # fmt: skip
def test_rule_write_note_or_reason_not_storable_text_is_400_and_changes_nothing(
    route: str, field: str, sent: dict[str, Any], value: Any
) -> None:
    e, text = _Env(), isinstance(value, str)
    rid, before = e.create(), e.c.get("/rules").json()
    body = {**sent, field: f"a{value}b" if text else value}
    if route.endswith("active-version"):
        body["version_id"] = before["items"][0]["active_version_id"]
    r = _write(e.c, route, rid, json.dumps(body).encode())
    assert r.status_code == 400, r.text[:300]
    why = UNSTORABLE_TEXT if text else "must be a string"
    assert (r.json()["code"], r.json()["detail"]) == ("validation_failed", f"'{field}' {why}")
    assert e.c.get("/rules").json() == before and [a for a, _ in e.audits] == ["rule.created"]


@pytest.mark.parametrize("ch", [chr(0xD800), chr(0xDC00), chr(0)], ids=["high", "low", "nul"])
def test_put_rule_mode_value_not_storable_text_is_400_and_audits_nothing(ch: str) -> None:
    e = _Env()
    r = _write(e.c, "/{rid}/mode", e.create(), json.dumps({"mode": f"a{ch}b"}).encode())
    assert (r.status_code, r.json()["detail"]) == (400, f"'mode' {UNSTORABLE_TEXT}"), r.text[:300]
    assert [a for a, _ in e.audits] == ["rule.created"]


@pytest.mark.parametrize("where", ["name", "body-name", "description", "action", "metric"])
def test_post_rules_unstorable_text_in_the_document_is_422_storing_nothing(where: str) -> None:
    e, text, ir = _Env(), f"a{chr(0)}b", _ir()
    body = {"ir": ir, "name": text} if where == "body-name" else {"ir": ir}
    if where == "action":
        ir["actions"][0]["params"]["template"] = text
    elif where == "metric":
        ir["conditions"]["left"]["params"]["source"] = text
    elif where != "body-name":
        ir[where] = text
    r = _write(e.c, "", "", json.dumps(body).encode())
    assert r.status_code == 422, r.text[:300]
    assert (r.json()["code"], UNSTORABLE_TEXT in r.json()["detail"]) == ("rule_ir_invalid", True)
    assert e.c.get("/rules").json()["items"] == [] and e.audits == []


@WRITES
def test_rule_write_body_nested_past_the_limit_is_the_readers_400_never_a_500(route: str) -> None:
    e = _Env()
    rid, c = e.create(), TestClient(e.c.app, raise_server_exceptions=False)
    for levels in (MAX_DEPTH + 3, NESTING):  # one past the reader's limit, and past the decoder's
        r = _write(c, route, rid, _deep(levels))
        assert (r.status_code, r.json().get("detail")) == (400, DEEPER), r.text[:300]
    assert DEEPER not in _write(c, route, rid, _deep(MAX_DEPTH + 2)).text  # the limit passes
    assert [a for a, _ in e.audits] == ["rule.created"]


@CHECKS
def test_rule_validation_body_over_the_ceiling_is_413_with_or_without_a_length(path: str) -> None:
    c, body = _client(), _padded(MAX_RULE_BODY_BYTES + 1)
    _too_large(c.post(path, content=body, headers=JSON))
    r = c.post(path, content=iter([body]), headers=JSON)  # streamed: no `Content-Length`
    assert "content-length" not in r.request.headers
    _too_large(r)


@CHECKS
def test_rule_validation_body_nested_past_the_limit_is_the_readers_400(path: str) -> None:
    c = TestClient(_client().app, raise_server_exceptions=False)
    for levels in (MAX_DEPTH + 3, NESTING):
        r = c.post(path, content=_deep(levels), headers=JSON)
        assert (r.status_code, r.json().get("detail")) == (400, DEEPER), r.text[:300]
    assert DEEPER not in c.post(path, content=_deep(MAX_DEPTH + 2), headers=JSON).text


# ----- C-12.4: the forbidden-role and cross-account answers stay first ---------------------


@WRITES
def test_rule_write_without_the_write_grant_is_403_before_the_body_is_read(route: str) -> None:
    owner = _Env()
    rid = owner.create()
    viewer = _Env({"rules:read"}, mgr=owner.mgr)
    for body in (_padded(MAX_RULE_BODY_BYTES + 1), json.dumps({"ir": _over("values")}).encode()):
        r = _write(viewer.c, route, rid, body)
        assert (r.status_code, r.json()["detail"]) == (403, "requires rules:write")
    assert [i["latest_version"] for i in owner.c.get("/rules").json()["items"]] == [1]
    assert [a for a, _ in owner.audits] == ["rule.created"]


@CHECKS
def test_rule_validation_without_the_read_grant_is_403_before_the_body_is_read(path: str) -> None:
    r = _client(_P()).post(path, content=_padded(MAX_RULE_BODY_BYTES + 1), headers=JSON)
    assert r.status_code == 403, r.text[:300]


def test_put_rule_cross_account_keeps_its_audited_404_over_a_bound() -> None:
    owner = _Env()
    rid = owner.create(**_scoped(A2))
    manager = _Env(owner=False, granted=frozenset({A1}), mgr=owner.mgr)
    for doc in (_ir(**_scoped(A1)), _over("values"), _over("depth")):
        r = manager.c.put(f"/rules/{rid}", json={"ir": doc}, headers={"If-Match": "1"})
        assert r.status_code == 404
    refused = [p["reason"] for a, p in owner.audits if a == "rule.scope_refused"]
    assert refused == ["rule_not_visible"] * 3
    assert owner.c.get(f"/rules/{rid}").json()["latest_version"] == 1


@KINDS
@pytest.mark.parametrize("method", ["POST", "PUT"])
def test_rule_save_over_a_bound_is_the_bounds_422_before_the_scope_check(
    method: str, kind: str
) -> None:
    """After the permission gate and the rule's visibility, the bounds come before the scope check
    reads the document's scope: an ungranted account in it is never looked up."""
    c, audits, _src, _m = _setup()
    rid = c.post("/rules", json={"ir": _ir(scope={"level": "account", "account_ids": [str(A)]})})
    doc = _over(kind, scope={"level": "account", "account_ids": [str(C)]})
    url = "/rules" + (f"/{rid.json()['id']}" if method == "PUT" else "")
    _bounds_problem(c.request(method, url, json={"ir": doc}, headers={"If-Match": "1"}))
    assert audits == [] and len(c.get("/rules").json()["items"]) == 1
