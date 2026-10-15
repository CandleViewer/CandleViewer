"""#2551: `app.openapi()` publishes the contract's operations for the raw-body routers.

A fake router reads raw bodies the way the drawings and workspaces routers do, so FastAPI
generates its operations without parameters, bodies or documented status codes. The wrapper
must replace exactly the served raw-body operations with the contract's, from the packaged
subset, merge the components they reference, and leave everything else as generated.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, Request, Response
from pydantic import BaseModel

from candleviewer.api.contract_conformance import (
    assert_spec_is_valid,
    load_contract_subset,
    under_raw_body_prefix,
)
from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.openapi_publish import (
    ContractPublishError,
    install_contract_openapi,
    publish_raw_body_operations,
)
from candleviewer.app import create_app
from candleviewer.settings import Settings

SUBSET = load_contract_subset()


class Thing(BaseModel):
    name: str


def _raw_body_router() -> APIRouter:
    """Three of the five drawings operations, reading raw bodies (no models, no parameters)."""
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

    return router


def _app(contract: dict[str, Any] | None = SUBSET, *, publish: bool = True) -> FastAPI:
    app = FastAPI(title="probe", version="0")
    app.include_router(_raw_body_router())

    @app.get("/things/{name}", response_model=Thing)
    async def get_thing(name: str) -> Thing:
        return Thing(name=name)

    if publish and contract is not None:
        install_contract_openapi(app, contract)
    return app


def test_a_raw_body_router_publishes_the_contract_operations() -> None:
    generated = _app(publish=False).openapi()["paths"]["/drawings"]["post"]
    assert "requestBody" not in generated and set(generated["responses"]) == {"200"}

    paths = _app().openapi()["paths"]
    for method, path in (("get", "/drawings"), ("post", "/drawings")):
        assert paths[path][method] == SUBSET["paths"][path][method], f"{method} {path}"
    item = SUBSET["paths"]["/drawings/{drawingId}"]
    assert paths["/drawings/{drawingId}"] == {
        "delete": item["delete"],
        "parameters": item["parameters"],
    }


def test_an_unmounted_contract_path_or_method_is_absent() -> None:
    paths = _app().openapi()["paths"]
    assert "put" in SUBSET["paths"]["/drawings/{drawingId}"]
    assert "put" not in paths["/drawings/{drawingId}"]
    assert "/drawings/batch" in SUBSET["paths"] and "/drawings/batch" not in paths
    assert not any(path.startswith("/workspaces") for path in paths)


def test_routes_outside_the_raw_body_prefixes_are_unchanged() -> None:
    plain, published = _app(publish=False).openapi(), _app().openapi()
    for path, item in plain["paths"].items():
        if not under_raw_body_prefix(path):
            assert published["paths"][path] == item, path
    for name, schema in plain["components"]["schemas"].items():
        assert published["components"]["schemas"][name] == schema, name
    assert {k: v for k, v in published.items() if k not in ("paths", "components")} == {
        k: v for k, v in plain.items() if k not in ("paths", "components")
    }


def test_the_merged_document_validates_and_resolves_every_reference() -> None:
    doc = _app().openapi()
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
    generated = _app(publish=False).openapi()["components"]["schemas"]["Thing"]
    doc = _app(_contract_with(copy.deepcopy(generated))).openapi()
    assert doc["components"]["schemas"]["Thing"] == generated


def test_a_conflicting_generated_component_is_refused_and_never_cached() -> None:
    app = _app(_contract_with({"type": "object", "properties": {"id": {"type": "integer"}}}))
    for _ in range(2):  # the second call regenerates and refuses again
        with pytest.raises(ContractPublishError, match=r"components\.schemas\.Thing"):
            app.openapi()
        assert app.openapi_schema is None


def test_the_document_is_built_once_and_cached() -> None:
    app = _app()
    assert app.openapi() is app.openapi() is app.openapi_schema


def test_a_served_operation_the_contract_lacks_keeps_its_generated_form() -> None:
    contract = copy.deepcopy(SUBSET)
    del contract["paths"]["/drawings"]["post"]
    generated = _app(publish=False).openapi()["paths"]["/drawings"]["post"]
    assert _app(contract).openapi()["paths"]["/drawings"]["post"] == generated


def test_publishing_leaves_the_contract_untouched() -> None:
    before = copy.deepcopy(SUBSET)
    doc = publish_raw_body_operations(
        _app(publish=False).openapi(), SUBSET, {("POST", "/drawings"), ("GET", "/things/{name}")}
    )
    doc["paths"]["/drawings"]["post"]["responses"].clear()
    assert before == SUBSET


def test_the_app_publishes_only_what_it_serves_and_validates() -> None:
    """The real app: every raw-body path in its document is served and carries the contract's
    operation (on `main` no raw-body router is mounted yet, so none is published)."""
    app = create_app(Settings(git_sha="test", version="0.0.0-test"))
    doc = app.openapi()
    assert_spec_is_valid(doc)
    served = {(m.lower(), p) for m, p in served_operations(app) if under_raw_body_prefix(p)}
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
