"""Global deny-by-default wiring (QA #1648 d3)."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.deny_by_default import (
    UndeclaredRouteAtBuildError,
    assert_app_routes_declared,
    declared_operations,
    make_deny_undeclared_dependency,
    rbac_permissions,
)
from candleviewer.app import create_app
from candleviewer.auth.generated_permissions import Permission


def test_build_fails_for_route_without_declaration() -> None:
    app = FastAPI()

    @app.get("/widgets")
    async def widgets() -> dict[str, str]:
        return {}

    with pytest.raises(UndeclaredRouteAtBuildError, match="GET /widgets"):
        assert_app_routes_declared(app, load_openapi_spec())


def test_runtime_denies_undeclared_route_with_403() -> None:
    app = FastAPI(dependencies=[Depends(make_deny_undeclared_dependency(set()))])

    @app.get("/widgets")
    async def widgets() -> dict[str, str]:
        return {"ok": "yes"}

    assert TestClient(app).get("/widgets").status_code == 403


def test_real_app_builds_and_declared_routes_are_not_blanket_denied() -> None:
    app = create_app()
    declared = declared_operations(load_openapi_spec())
    assert ("PUT", "/users/{userId}/roles") in declared
    assert TestClient(app, client=("127.0.0.1", 50000)).get("/healthz").status_code == 200


def test_unmatched_route_is_404_and_never_reaches_a_handler() -> None:
    reached: list[str] = []

    async def spy() -> None:
        reached.append("dep")

    app = FastAPI(dependencies=[Depends(make_deny_undeclared_dependency(set()))])

    @app.get("/widgets")
    async def widgets() -> dict[str, str]:
        reached.append("handler")
        return {}

    resp = TestClient(app).get("/no-such-route")
    assert resp.status_code == 404
    assert reached == []
    assert TestClient(create_app(), client=("127.0.0.1", 50000)).get("/nope").status_code == 404


def test_rbac_permissions_maps_each_operation_to_the_permissions_its_x_rbac_names() -> None:
    """An operation naming none is absent: the view-as guard refuses to build on a protective
    write that is (`test_view_as_gate.py`)."""
    spec = {
        "paths": {
            "/x": {
                "get": {"x-rbac": {"permissions": ["orders:read"], "scope": "none"}},
                "post": {"x-rbac": {"permissions": [], "scope": "self"}},
                "put": {"security": []},
            }
        }
    }
    assert rbac_permissions(spec) == {("GET", "/x"): frozenset({Permission.ORDERS_READ})}


def test_rbac_permissions_refuses_a_code_outside_the_vocabulary() -> None:
    """The build fails rather than drop it, which would leave the guard nothing to check."""
    spec = {"paths": {"/x": {"post": {"x-rbac": {"permissions": ["not:a_code"]}}}}}
    with pytest.raises(ValueError, match="not:a_code"):
        rbac_permissions(spec)
