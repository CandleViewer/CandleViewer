"""E08-T09 (#4708) contract harness for `/scanner`, `/scanner/criteria` and `/scanner/presets*`;
`22-api-openapi.yaml` is normative.
Each request body is validated against its operation's `requestBody` schema before it is sent
(`invalid=True` asserts the opposite); each response must be one its operation documents for that
status and media type, with a valid body (`$ref`s resolved, formats checked); a problem body must
carry its catalogued `code`, echo no id it was not sent and hold no traceback. The indicator
presets pack's pattern (`tests/contract/indicator_presets/_presets_contract.py`)."""

from __future__ import annotations

import json
import re
from functools import cache
from typing import Any

import httpx
from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from tests.contract.rbac.rbac_harness import World, bearer
from tests.scanner_presets._scanner_env import FakeScannerRepo

SPEC: dict[str, Any] = load_openapi_spec()
CODES = {e["code"]: e["status"] for e in SPEC["x-error-codes"]}
_PREFIXES = ("/scanner/presets", "/scanner/criteria")
#: operationId -> (METHOD, path) for `/scanner` (an exact path: a prefix would take in every
#: `/scanner*` one), `/scanner/criteria` and every `/scanner/presets*` operation.
OPS = {
    op["operationId"]: (method.upper(), path)
    for path, item in SPEC["paths"].items() if path.startswith(_PREFIXES) or path == "/scanner"
    for method, op in item.items() if method in ("get", "put", "post", "delete", "patch")
}  # fmt: skip
#: The contract's own create example (`momentum`), the base of every request fixture.
EXAMPLE: dict[str, Any] = dict(
    SPEC["paths"]["/scanner/presets"]["post"]["requestBody"]["content"]["application/json"][
        "examples"
    ]["momentum"]["value"]
)
MISSING = "00000000-0000-4000-8000-0000000000ff"
_BASE = "urn:cv:22-api-openapi"
_REGISTRY: Registry[Any] = Registry().with_resource(_BASE, DRAFT202012.create_resource(SPEC))
_UUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")


def preset(**over: Any) -> dict[str, Any]:
    """The contract's example with `over` applied (a fresh object on every call)."""
    return dict(EXAMPLE) | over


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
    status = str(r.status_code)
    where = f"{method} {path} -> {status}: {r.text[:300]}"
    assert status in responses, f"undocumented status, documented {sorted(responses)}: {where}"
    inline = "#" + _pointer("paths", path, method.lower(), "responses", status)
    pointer = responses[status].get("$ref", inline)[1:]
    documented = _node(pointer)
    if "content" not in documented:
        assert r.text == "", f"documented without a body: {where}"
        return
    media = r.headers.get("content-type", "").split(";")[0]
    assert media in documented["content"], f"{media} is not documented: {where}"
    body = r.json()
    errors = schema_errors(pointer + _pointer("content", media, "schema"), body)
    assert not errors, f"body violates the contract {errors[:3]}: {where}"
    if media == "application/problem+json":
        code = body["code"]  # `validation_failed` is catalogued 400 but served 422 app-wide
        allowed = {CODES.get(code)} | ({422} if code == "validation_failed" else set())
        assert r.status_code in allowed, f"{code} is catalogued at {CODES.get(code)}: {where}"
        echoed = set(_UUID.findall(json.dumps({k: v for k, v in body.items() if k != "instance"})))
        assert echoed <= set(_UUID.findall(sent)), f"echoes ids it was not sent: {where}"
        assert "Traceback" not in r.text, where


class Api:
    """Calls a contract operation as an RBAC-pack actor through the real app."""

    def __init__(self, world: World, repo: FakeScannerRepo) -> None:
        self.world, self.repo = world, repo

    def send(self, actor: str, op: str, body: Any = None, *, preset_id: str = "",
             invalid: bool = False, **kw: Any) -> httpx.Response:  # fmt: skip
        """`kw`: `params`, `headers` and `content` as `TestClient.request` takes them."""
        method, path = OPS[op]
        if body is not None:
            schema = _pointer("paths", path, method.lower(), "requestBody", "content")
            errors = schema_errors(schema + _pointer("application/json", "schema"), body)
            assert bool(errors) == invalid, f"{op} request fixture: {errors or 'schema-valid'}"
        url, headers = path.replace("{presetId}", preset_id), kw.pop("headers", {})
        r: httpx.Response = self.world.client.request(
            method, url, json=body, headers=bearer(actor) | headers, **kw
        )
        conforms(op, r, sent=f"{url} {json.dumps(body)} {kw} {headers}")
        return r

    def create(self, actor: str, **over: Any) -> dict[str, Any]:
        r = self.send(actor, "createScannerPreset", preset(**over))
        assert r.status_code == 201, r.text
        return dict(r.json())
