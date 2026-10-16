"""#2551: `app.openapi()` publishes the contract's operations for the raw-body routers.

A fake router reads raw bodies the way the drawings and workspaces routers do, so FastAPI
generates its operations without parameters, bodies or documented status codes. The wrapper
must replace exactly the raw-body operations of the generated document with the contract's
(from the packaged subset), merge exactly the components they reference, leave everything else
as generated, and let FastAPI own the cache.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.openapi.utils import get_openapi
from fastapi.testclient import TestClient
from pydantic import BaseModel

from candleviewer.api import openapi_publish
from candleviewer.api.contract_conformance import (
    assert_spec_is_valid,
    component_closure,
    load_contract_subset,
    under_raw_body_prefix,
)
from candleviewer.api.openapi_publish import (
    ContractPublishError,
    install_contract_openapi,
    publish_raw_body_operations,
)
from candleviewer.app import create_app
from candleviewer.settings import Settings

SUBSET: dict[str, Any] = load_contract_subset()
#: The contract operations the fake raw-body router serves in its schema.
PUBLISHED = (("get", "/drawings"), ("post", "/drawings"), ("delete", "/drawings/{drawingId}"))


class Thing(BaseModel):
    name: str


def _raw_body_router() -> APIRouter:
    """Raw-body handlers like the drawings router's: three contract operations, one contract
    operation hidden from the schema, and one path the contract lacks."""
    router = APIRouter()

    @router.get("/drawings")
    async def list_drawings(request: Request) -> Response:
        return Response(status_code=200)

    @router.post("/drawings")
    async def create_drawing(request: Request) -> Response:
        await request.body()
        return Response(status_code=201)

    @router.delete("/drawings/{drawingId}")
    async def delete_drawing(request: Request) -> Response:
        return Response(status_code=204)

    @router.put("/drawings/{drawingId}", include_in_schema=False)
    async def update_drawing(request: Request) -> Response:
        return Response(status_code=200)

    @router.get("/drawings/{drawingId}/preview")
    async def preview_drawing(drawingId: str) -> Response:
        return Response(status_code=200)

    return router


def _app(*, raw_body: bool = True) -> FastAPI:
    """The fake routes, nothing installed: the raw-body router, `GET /instruments` (a contract
    operation outside the prefixes) and an ordinary model-backed route."""
    app = FastAPI(title="probe", version="0")
    if raw_body:
        app.include_router(_raw_body_router())

    @app.get("/instruments")
    async def list_instruments(request: Request) -> Response:
        return Response(status_code=200)

    @app.get("/things/{name}", response_model=Thing)
    async def get_thing(name: str) -> Thing:
        return Thing(name=name)

    return app


def _published(contract: Mapping[str, object] = SUBSET) -> FastAPI:
    app = _app()
    install_contract_openapi(app, contract)
    return app


def test_a_raw_body_router_publishes_the_contract_operations() -> None:
    generated = _app().openapi()["paths"]["/drawings"]["post"]
    assert "requestBody" not in generated and set(generated["responses"]) == {"200"}

    paths = _published().openapi()["paths"]
    for method, path in PUBLISHED:
        assert paths[path][method] == SUBSET["paths"][path][method], f"{method} {path}"
    item = SUBSET["paths"]["/drawings/{drawingId}"]
    assert paths["/drawings/{drawingId}"]["parameters"] == item["parameters"]


def test_an_unmounted_contract_path_is_absent() -> None:
    paths = _published().openapi()["paths"]
    assert "/drawings/batch" in SUBSET["paths"] and "/drawings/batch" not in paths
    assert not any(path.startswith(("/workspaces", "/layout-presets")) for path in paths)


def test_a_route_hidden_from_the_schema_is_not_published() -> None:
    """`PUT /drawings/{drawingId}` is served with `include_in_schema=False`."""
    assert "put" in SUBSET["paths"]["/drawings/{drawingId}"]
    assert "put" not in _published().openapi()["paths"]["/drawings/{drawingId}"]


def test_a_raw_body_path_the_contract_lacks_keeps_its_generated_form() -> None:
    path = "/drawings/{drawingId}/preview"
    assert path not in SUBSET["paths"]
    assert _published().openapi()["paths"][path] == _app().openapi()["paths"][path]


def test_a_served_operation_the_contract_lacks_keeps_its_generated_form() -> None:
    contract = copy.deepcopy(SUBSET)
    del contract["paths"]["/drawings"]["post"]
    generated = _app().openapi()["paths"]["/drawings"]["post"]
    assert _published(contract).openapi()["paths"]["/drawings"]["post"] == generated


def test_a_contract_operation_outside_the_prefixes_stays_as_generated() -> None:
    assert "get" in SUBSET["paths"]["/instruments"]
    published = _published().openapi()["paths"]["/instruments"]
    assert published == _app().openapi()["paths"]["/instruments"]
    assert published["get"] != SUBSET["paths"]["/instruments"]["get"]


def test_routes_outside_the_raw_body_prefixes_are_unchanged() -> None:
    plain, published = _app().openapi(), _published().openapi()
    for path, item in plain["paths"].items():
        if not under_raw_body_prefix(path):
            assert published["paths"][path] == item, path
    for name, schema in plain["components"]["schemas"].items():
        assert published["components"]["schemas"][name] == schema, name
    assert {k: v for k, v in published.items() if k not in ("paths", "components")} == {
        k: v for k, v in plain.items() if k not in ("paths", "components")
    }


def test_the_merged_components_are_exactly_the_closure_of_the_published_operations() -> None:
    roots = [
        [SUBSET["paths"][path][method], SUBSET["paths"][path].get("parameters", [])]
        for method, path in PUBLISHED
    ]
    expected = copy.deepcopy(_app().openapi()["components"])
    for kind, entries in component_closure(SUBSET["components"], roots).items():
        expected.setdefault(kind, {}).update(entries)
    assert _published().openapi()["components"] == expected


def test_a_document_without_raw_body_operations_comes_back_unchanged() -> None:
    doc = _app(raw_body=False).openapi()
    before = copy.deepcopy(doc)
    assert publish_raw_body_operations(doc, SUBSET) == before


def test_a_document_or_contract_without_paths_is_returned_as_is() -> None:
    assert publish_raw_body_operations({"openapi": "3.1.0"}, SUBSET) == {"openapi": "3.1.0"}
    doc = _app().openapi()
    before = copy.deepcopy(doc)
    assert publish_raw_body_operations(doc, {"components": {}}) == before


def test_the_merged_document_validates_and_resolves_every_reference() -> None:
    doc = _published().openapi()
    assert_spec_is_valid(doc)
    responses = doc["paths"]["/drawings"]["post"]["responses"]
    assert "201" in responses and any(code.startswith("4") for code in responses)


def _contract_with(thing: dict[str, Any]) -> dict[str, Any]:
    """A contract whose `GET /drawings` returns a `Thing` defined as `thing`."""
    contract = copy.deepcopy(SUBSET)
    body = {"application/json": {"schema": {"$ref": "#/components/schemas/Thing"}}}
    contract["paths"]["/drawings"]["get"]["responses"] = {
        "200": {"description": "ok", "content": body}
    }
    contract["components"]["schemas"]["Thing"] = thing
    return contract


def test_an_identical_generated_component_is_shared() -> None:
    generated = _app().openapi()["components"]["schemas"]["Thing"]
    doc = _published(_contract_with(copy.deepcopy(generated))).openapi()
    assert doc["components"]["schemas"]["Thing"] == generated


def test_a_conflicting_generated_component_is_refused_and_never_cached() -> None:
    app = _published(_contract_with({"type": "object", "properties": {"id": {"type": "integer"}}}))
    for _ in range(2):  # the second call regenerates and refuses again
        with pytest.raises(ContractPublishError, match=r"components\.schemas\.Thing"):
            app.openapi()
        assert app.openapi_schema is None


def test_a_dangling_reference_is_refused_and_never_cached() -> None:
    contract = copy.deepcopy(SUBSET)
    missing = {"$ref": "#/components/responses/Missing"}
    contract["paths"]["/drawings"]["get"]["responses"] = {"200": missing}
    app = _published(contract)
    for _ in range(2):  # the second call regenerates and refuses again
        with pytest.raises(ValueError, match="dangling reference"):
            app.openapi()
        assert app.openapi_schema is None


def test_the_document_is_built_and_published_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    publish = openapi_publish.publish_raw_body_operations

    def spy(doc: dict[str, object], contract: Mapping[str, object]) -> dict[str, object]:
        calls.append(1)
        return publish(doc, contract)

    monkeypatch.setattr(openapi_publish, "publish_raw_body_operations", spy)
    app = _published()
    first = app.openapi()
    assert app.openapi() is first is app.openapi_schema
    assert calls == [1]


def test_a_regenerated_document_is_published_again() -> None:
    """FastAPI owns the cache: a route added after the first build changes its routes version,
    so its own `openapi()` regenerates, with no cache cleared, and the new document is
    published too. A wrapper that served `app.openapi_schema` itself kept the stale one."""
    app = _published()
    first = app.openapi()

    @app.post("/drawings/batch")
    async def batch(request: Request) -> Response:
        return Response(status_code=200)

    second = app.openapi()
    assert second is not first
    batch_op = SUBSET["paths"]["/drawings/batch"]["post"]
    assert second["paths"]["/drawings/batch"]["post"] == batch_op


def test_publishing_copies_every_merged_piece() -> None:
    contract = copy.deepcopy(SUBSET)  # this test's own copy: a failure must not leak to others
    before = copy.deepcopy(contract)
    doc = _published(contract).openapi()
    for method, path in PUBLISHED:
        doc["paths"][path][method].clear()
    doc["paths"]["/drawings/{drawingId}"]["parameters"].clear()
    for entries in doc["components"].values():
        for component in entries.values():
            component.clear()
    assert before == contract


def test_a_refused_document_is_left_unchanged() -> None:
    """`ContractPublishError` comes before anything is replaced or merged."""
    contract = _contract_with({"type": "object", "properties": {"id": {"type": "integer"}}})
    doc = _app().openapi()
    before = copy.deepcopy(doc)
    with pytest.raises(ContractPublishError, match=r"components\.schemas\.Thing"):
        publish_raw_body_operations(doc, contract)
    assert doc == before


def test_openapi_json_serves_the_published_operation() -> None:
    response = TestClient(_published()).get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["paths"]["/drawings"]["post"] == SUBSET["paths"]["/drawings"]["post"]


def test_the_app_publishes_only_its_schema_routes_and_validates() -> None:
    """The real app: the raw-body operations in its document are exactly the served routes
    FastAPI puts in the schema (`include_in_schema=False` ones excluded), each carrying the
    contract's operation (on `main` no raw-body router is mounted yet, so none is published)."""
    app = create_app(Settings(git_sha="test", version="0.0.0-test"))
    doc = app.openapi()
    assert_spec_is_valid(doc)
    schema_paths = get_openapi(title=app.title, version=app.version, routes=app.routes)["paths"]
    served = {(m, p) for p, item in schema_paths.items() if under_raw_body_prefix(p) for m in item}
    published = {
        (m, p)
        for p, item in doc["paths"].items()
        if under_raw_body_prefix(p)
        for m in item
        if m != "parameters"
    }
    assert published == served
    for method, path in served:
        assert doc["paths"][path][method] == SUBSET["paths"][path][method]
