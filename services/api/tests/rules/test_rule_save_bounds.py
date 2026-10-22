"""A rule save refuses what compile refuses, and the rule write routes cap the body they read.

Compile and `POST /rules/validate` hold a document to `check_bounds` (`MAX_ITEMS` values,
`MAX_DEPTH` levels). Every save applies the same bounds before the schema walks the document and
answers as it answers a schema error (422 `rule_ir_invalid`), storing nothing. The write routes
read the body under `MAX_RULE_BODY_BYTES` (413 `payload_too_large`) before it is buffered whole.
A note or a reason Postgres cannot store, and a body nested deeper than a rule needs, are 400s.
Inputs are built from those constants.
"""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from candleviewer.api import rules_crud
from candleviewer.domain.text import UNSTORABLE_TEXT
from candleviewer.rules.compiler.common import MAX_DEPTH, MAX_ITEMS
from candleviewer.rules.manager import RuleError, is_reserved_name
from tests.rules.test_rules_manager import OWNER, _mgr
from tests.rules.test_rules_routes import A1, A2, _Env, _ir, _scoped
from tests.rules.test_scope_crud import C, _setup

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
#: A body nested past what the JSON decoder can recurse, from the interpreter's own limit.
NESTING = 100 * sys.getrecursionlimit()
WRITES = pytest.mark.parametrize("route", ["", "/{rid}", "/{rid}/active-version", "/{rid}/mode"])


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
    detail = f"The request body exceeds {rules_crud.MAX_RULE_BODY_BYTES} bytes."
    assert (r.json()["code"], r.json()["detail"]) == ("payload_too_large", detail)


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
    assert len(RULES) == 30 and m._validated(doc, doc["rule_id"])[1] == GOLDEN[name]
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
    at, over, cap = _Env(), _Env(), rules_crud.MAX_RULE_BODY_BYTES
    body = _padded(cap)
    assert len(body) == cap and at.c.post("/rules", content=body, headers=JSON).status_code == 201
    _too_large(over.c.post("/rules", content=_padded(cap + 1), headers=JSON))
    assert over.c.get("/rules").json()["items"] == [] and over.audits == []


def test_post_rules_declared_length_over_the_ceiling_is_413_unread() -> None:
    e, cap = _Env(), rules_crud.MAX_RULE_BODY_BYTES
    small = json.dumps({"ir": _ir()}).encode()  # a valid body, its declared length over the ceiling
    _too_large(e.c.post("/rules", content=small, headers={**JSON, "content-length": str(cap + 1)}))
    assert e.c.get("/rules").json()["items"] == [] and e.audits == []


async def test_post_rules_streamed_body_over_the_ceiling_is_413_before_it_is_buffered() -> None:
    """No `Content-Length`: the stream is read one chunk past the ceiling, never to its end."""
    e, cap, pulled = _Env(), rules_crud.MAX_RULE_BODY_BYTES, []
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
    e, cap = _Env(), rules_crud.MAX_RULE_BODY_BYTES
    rid = e.create()
    hdr = {**JSON, "If-Match": "1", "Idempotency-Key": "k"}
    _too_large(e.c.put(f"/rules/{rid}{route}", content=_padded(cap + 1), headers=hdr))
    assert e.c.get(f"/rules/{rid}").json()["latest_version"] == 1
    assert [a for a, _ in e.audits] == ["rule.created"]


@pytest.mark.parametrize("ch", [chr(0xD800), chr(0xDC00), chr(0)], ids=["high", "low", "nul"])
@pytest.mark.parametrize(
    ("route", "field", "sent"),
    [("", "note", {"ir": _ir("2", name="other")}), ("/{rid}", "note", {"ir": _ir("2")}),
     ("/{rid}/active-version", "note", {}), ("/{rid}/mode", "reason", {"mode": "simulate"})],
    ids=["create", "update", "active-version", "mode"],
)  # fmt: skip
def test_rule_write_unstorable_note_or_reason_is_400_and_changes_nothing(
    route: str, field: str, sent: dict[str, Any], ch: str
) -> None:
    e = _Env()
    rid, before = e.create(), e.c.get("/rules").json()
    body = {**sent, field: f"a{ch}b"}
    if route.endswith("active-version"):
        body["version_id"] = before["items"][0]["active_version_id"]
    r = _write(e.c, route, rid, json.dumps(body).encode())
    assert r.status_code == 400, r.text[:300]
    want = ("validation_failed", f"'{field}' {UNSTORABLE_TEXT}")
    assert (r.json()["code"], r.json()["detail"]) == want
    assert e.c.get("/rules").json() == before and [a for a, _ in e.audits] == ["rule.created"]


@WRITES
def test_rule_write_body_nested_past_the_decoder_is_400_not_500(route: str) -> None:
    e = _Env()
    rid, c = e.create(), TestClient(e.c.app, raise_server_exceptions=False)
    body = ('{"ir":' + "[" * NESTING + "]" * NESTING + "}").encode()
    r = _write(c, route, rid, body)
    assert len(body) <= rules_crud.MAX_RULE_BODY_BYTES and r.status_code == 400, r.text[:300]
    assert r.json()["code"] == "validation_failed"
    assert [a for a, _ in e.audits] == ["rule.created"]


# ----- C-12.4: the forbidden-role and cross-account answers stay first ---------------------


def test_rule_writes_forbidden_role_keep_their_403_over_a_bound_or_the_ceiling() -> None:
    owner, cap = _Env(), rules_crud.MAX_RULE_BODY_BYTES
    rid = owner.create()
    viewer = _Env({"rules:read"}, mgr=owner.mgr)
    big = {"content": _padded(cap + 1), "headers": {**JSON, "If-Match": "1"}}
    for r in (
        viewer.c.post("/rules", json={"ir": _over("values")}),
        viewer.c.post("/rules", json={"ir": _over("depth")}),
        viewer.c.post("/rules", **big),
        viewer.c.put(f"/rules/{rid}", json={"ir": _over("values")}, headers={"If-Match": "1"}),
        viewer.c.put(f"/rules/{rid}", **big),
    ):
        assert (r.status_code, r.json()["detail"]) == (403, "requires rules:write")
    assert [i["latest_version"] for i in owner.c.get("/rules").json()["items"]] == [1]
    assert [a for a, _ in owner.audits] == ["rule.created"]


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
def test_post_rules_cross_account_keeps_its_audited_403_over_a_bound(kind: str) -> None:
    c, audits, _src, _m = _setup()
    scope = {"level": "account", "account_ids": [str(C)]}
    assert c.post("/rules", json={"ir": _over(kind, scope=scope)}).status_code == 403
    assert audits == ["rule_scope_denied"]
    assert c.get("/rules").json()["items"] == []
