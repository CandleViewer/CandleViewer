"""E14-Q04 (#431) contract harness for `/drawings`; `22-api-openapi.yaml` is normative. Each
request body is validated against its operation's `requestBody` schema before it is sent
(`invalid=True` asserts the opposite), each response must be one its operation documents for that
status and media type, with a valid body (`$ref`s resolved, formats checked), and a problem body
must carry its catalogued `code` and echo no id it was not sent. Fixtures come from the schema
(tool enum, per-tool point counts and `text` rule, examples), so a new tool widens the pack.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from functools import cache
from typing import Any

import httpx
from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.drawings_models import DrawingIn
from candleviewer.storage.repositories.drawings import DrawingFields
from tests.contract.rbac.rbac_harness import World, bearer, user_id_of
from tests.drawings._drawings_api_env import FakeDrawingRepo

SPEC: dict[str, Any] = load_openapi_spec()
SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
CODES = {e["code"]: e["status"] for e in SPEC["x-error-codes"]}
#: operationId -> (METHOD, path) for every `/drawings*` operation of the contract.
OPS = {
    op["operationId"]: (method.upper(), path)
    for path, item in SPEC["paths"].items() if path.startswith("/drawings")
    for method, op in item.items() if method in ("get", "put", "post", "delete", "patch")
}  # fmt: skip
TOOLS: list[str] = SCHEMAS["DrawingTool"]["enum"]
_RULES = SCHEMAS["DrawingTool"]["description"]
#: tool -> the smallest point count its description allows ("exactly N" or "N..M").
MIN_POINTS = {
    tool: int(exact or low)
    for exact, low, names in re.findall(r"(?:exactly (\d+)|(\d+)\.\.\d+):((?:\s*`\w+`,?)+)", _RULES)
    for tool in re.findall(r"`(\w+)`", names)
}  # fmt: skip
_TEXT = re.search(r"`text` is required for ((?:`\w+`(?: and |, )?)+)", _RULES)
TEXT_TOOLS = frozenset(re.findall(r"`(\w+)`", _TEXT.group(1) if _TEXT else ""))
SYMBOLS: list[str] = SCHEMAS["DrawingInput"]["properties"]["symbol"]["examples"]
MISSING = "00000000-0000-4000-8000-0000000000ff"
_POINT = SCHEMAS["DrawingPoint"]["properties"]
_BASE = "urn:cv:22-api-openapi"
_REGISTRY: Registry[Any] = Registry().with_resource(_BASE, DRAFT202012.create_resource(SPEC))
_UUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")


def drawing(tool: str = "trendline", **over: Any) -> dict[str, Any]:
    """The smallest valid `DrawingInput` for `tool` (a fresh object on every call)."""
    examples = list(zip(_POINT["t"]["examples"], _POINT["p"]["examples"], strict=True))
    points = [dict(zip("tp", examples[i % 2], strict=True)) for i in range(MIN_POINTS[tool])]
    geometry = {"points": points} | ({"text": "note"} if tool in TEXT_TOOLS else {})
    return {"symbol": SYMBOLS[0], "tool": tool, "geometry": geometry} | over


def _pointer(*parts: str) -> str:
    return "".join("/" + p.replace("~", "~0").replace("/", "~1") for p in parts)


@cache
def _validator(pointer: str) -> Draft202012Validator:
    schema = {"$ref": f"{_BASE}#{pointer}"}
    fmt = Draft202012Validator.FORMAT_CHECKER
    return Draft202012Validator(schema, registry=_REGISTRY, format_checker=fmt)


def schema_errors(pointer: str, doc: Any) -> list[str]:
    return sorted(e.message for e in _validator(pointer).iter_errors(doc))


def _node(pointer: str) -> Any:
    node: Any = SPEC
    for part in pointer.split("/")[1:]:
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def conforms(op: str, r: httpx.Response, sent: str = "") -> None:
    """`r` is a documented response of `op`; `sent` is the request text ids may be echoed from."""
    method, path = OPS[op]
    responses = SPEC["paths"][path][method.lower()]["responses"]
    status, cid = str(r.status_code), r.headers.get("x-correlation-id")
    where = f"{method} {path} -> {status} (x-correlation-id {cid}): {r.text[:300]}"
    assert status in responses, f"undocumented status, documented {sorted(responses)}: {where}"
    inline = "#" + _pointer("paths", path, method.lower(), "responses", status)
    pointer = responses[status].get("$ref", inline)[1:]  # a shared response or the inline one
    documented = _node(pointer)
    if "content" not in documented:
        assert r.text == "", f"documented without a body: {where}"
        return
    media = r.headers.get("content-type", "").split(";")[0]
    assert media in documented["content"], f"{media} is not documented: {where}"
    body = r.json()
    errors = schema_errors(pointer + _pointer("content", media, "schema"), body)
    assert not errors, f"body violates the contract {errors[:3]}: {where}"
    if "ETag" in documented.get("headers", {}):
        assert r.headers.get("etag") == f'"{body["updated_at"]}"', where
    if media == "application/problem+json":
        code = body["code"]  # `validation_failed` is catalogued 400 but served 422 app-wide
        allowed = {CODES.get(code)} | ({422} if code == "validation_failed" else set())
        assert r.status_code in allowed, f"{code} is catalogued at {CODES.get(code)}: {where}"
        echoed = set(_UUID.findall(json.dumps({k: v for k, v in body.items() if k != "instance"})))
        assert echoed <= set(_UUID.findall(sent)), f"echoes ids it was not sent: {where}"
        assert "Traceback" not in r.text, where


class Api:
    """Calls a contract operation as an RBAC-pack actor through the real app; see the module doc."""

    def __init__(self, world: World, repo: FakeDrawingRepo) -> None:
        self.world, self.repo = world, repo

    def send(self, actor: str, op: str, body: Any = None, *, drawing_id: str = "",
             invalid: bool = False, **kw: Any) -> httpx.Response:  # fmt: skip
        """`kw`: `params`, `headers` and `content` as `TestClient.request` takes them."""
        method, path = OPS[op]
        if body is not None:
            schema = _pointer("paths", path, method.lower(), "requestBody", "content")
            errors = schema_errors(schema + _pointer("application/json", "schema"), body)
            assert bool(errors) == invalid, f"{op} request fixture: {errors or 'schema-valid'}"
        url, headers = path.replace("{drawingId}", drawing_id), kw.pop("headers", {})
        r: httpx.Response = self.world.client.request(
            method, url, json=body, headers=bearer(actor) | headers, **kw
        )
        conforms(op, r, sent=f"{url} {json.dumps(body)} {kw} {headers}")
        return r

    def create(self, actor: str, **over: Any) -> dict[str, Any]:
        r = self.send(actor, "createDrawing", drawing(**over))
        assert r.status_code == 201, r.text
        return dict(r.json())

    def listed(self, actor: str, symbol: str = SYMBOLS[0], limit: int = 500) -> list[Any]:
        r = self.send(actor, "listDrawings", params={"symbol": symbol, "limit": limit})
        assert r.status_code == 200, r.text
        return list(r.json()["items"])

    def seed(self, actor: str, **over: Any) -> str:
        """A live drawing of `actor` stored directly: viewers cannot write; layouts need E15-T01."""
        values = DrawingIn.model_validate(drawing(**over)).db_values()
        fields = DrawingFields(**(values | {"layout_id": over.get("layout_id")}))
        drawing_id = str(uuid.uuid4())
        asyncio.run(self.repo.create(str(user_id_of(actor)), drawing_id, fields))
        return drawing_id
