"""Provider contract tests (#2713): `getMe`, `getMyPreferences` and `getMyKeymap` over HTTP.

The real `create_app()` (the RBAC pack's world: identity and session store faked, no network)
answers every role. Each answer validates against the schema `22-api-openapi.yaml` declares for
that status, the 200 bodies round-trip through the generated models, and every status the
routes can answer is one the operation declares (C-6.1, C-6.2)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import jsonschema
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from tests.contract.rbac.rbac_harness import ACTORS, World, bearer, build_world
from tests.openapi_helpers import deref

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
#: path -> (operationId, generated model of the 200 body; `getMyKeymap`'s is an inline schema)
_OPERATIONS: dict[str, tuple[str, type[BaseModel] | None]] = {
    "/me": ("getMe", api.Me),
    "/me/preferences": ("getMyPreferences", api.Settings),
    "/me/keymap": ("getMyKeymap", None),
}
_PATHS = list(_OPERATIONS)
_ROLES = ACTORS[:4]  # every authenticated actor
#: Every status the three routes answer. 403: no `settings:read`, or no live role for `/me`.
#: 501: the session backend is active but no identity provider is wired, answered after
#: authenticating. The app wires both or neither (pinned in `test_me_router.py`), so only a router
#: built by hand answers it, and the fake storage backend, which has no session backend, answers
#: 503 first. 503: the session backend is not active, or raised `RuntimeError` under the
#: authentication call.
_ANSWERED = {"200", "401", "403", "422", "501", "503"}


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        yield build_world(mp)
    finally:
        mp.undo()


def _operation(path: str) -> dict[str, Any]:
    operation: dict[str, Any] = _SPEC["paths"][path]["get"]
    return operation


def _response_schema(path: str, status: str) -> Any:
    content = deref(_SPEC, _operation(path)["responses"][status])["content"]
    return next(iter(content.values()))["schema"]


@pytest.mark.parametrize("path", _PATHS)
def test_the_operation_declares_every_status_the_route_can_answer(path: str) -> None:
    declared = set(_operation(path)["responses"])
    assert declared >= _ANSWERED, f"{path}: the contract lacks {sorted(_ANSWERED - declared)}"
    assert _operation(path)["operationId"] == _OPERATIONS[path][0]


@pytest.mark.parametrize("actor", _ROLES)
@pytest.mark.parametrize("path", _PATHS)
def test_the_200_body_validates_against_the_contract_schema(
    world: World, path: str, actor: str
) -> None:
    resp = world.client.get(path, headers=bearer(actor))
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/json"
    body = resp.json()
    jsonschema.validate(body, _response_schema(path, "200"))
    model = _OPERATIONS[path][1]
    if model is not None:  # `getMyKeymap`'s response is an inline schema with no generated model
        dumped = model.model_validate(body).model_dump(
            mode="json", by_alias=True, exclude_unset=True
        )
        assert dumped == body


@pytest.mark.parametrize("path", _PATHS)
def test_an_unauthenticated_call_is_the_contracts_401_problem(world: World, path: str) -> None:
    anonymous = TestClient(world.app, client=("127.0.0.7", 50000), raise_server_exceptions=False)
    resp = anonymous.get(path, headers=bearer("unauthenticated"))
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    jsonschema.validate(resp.json(), _response_schema(path, "401"))
    assert resp.json()["code"] == "unauthenticated"


@pytest.mark.parametrize("path", _PATHS)
def test_a_target_user_parameter_is_the_contracts_422_problem(world: World, path: str) -> None:
    resp = world.client.get(path, params={"user_id": "someone-else"}, headers=bearer("viewer"))
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
    jsonschema.validate(resp.json(), _response_schema(path, "422"))
    assert resp.json()["code"] == "validation_failed"


@pytest.mark.parametrize("path", _PATHS)
def test_no_role_gets_a_status_the_operation_does_not_declare(world: World, path: str) -> None:
    declared = set(_operation(path)["responses"])
    seen = {str(world.client.get(path, headers=bearer(actor)).status_code) for actor in _ROLES} | {
        str(world.client.get(path, params={"x": "1"}, headers=bearer("owner")).status_code)
    }
    assert seen <= declared, f"{path} answered {sorted(seen - declared)} outside {sorted(declared)}"


def test_session_environment_is_the_deployments_environment_not_the_default() -> None:
    """The shell's LIVE/DEMO/TESTNET badge comes from `Me.session.environment` alone, so a
    testnet deployment must answer `testnet`; the shared world runs on the default (`demo`),
    which a hard-coded value would also satisfy."""
    mp = pytest.MonkeyPatch()
    try:
        mp.setenv("CV_ENVIRONMENT", "testnet")
        resp = build_world(mp).client.get("/me", headers=bearer("owner"))
    finally:
        mp.undo()
    assert resp.status_code == 200, resp.text
    assert resp.json()["session"]["environment"] == "testnet"
