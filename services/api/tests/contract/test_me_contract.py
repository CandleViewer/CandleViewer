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
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError
from sqlalchemy import CheckConstraint

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.db.models import users
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


def _with_formats(schema: Any) -> Draft202012Validator:
    """Draft 2020-12 with `format` asserted, as the other contract suites build it:
    `jsonschema.validate` alone only annotates `format`, so a body that broke one would pass."""
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


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
    _with_formats(_response_schema(path, "200")).validate(body)
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


#: (address, stored). `users_email_fmt` is `position('@' in email) > 1`: the first `@` is not the
#: first character, and nothing is asked of the rest, which is why `.local` is valid data.
_EMAILS = [
    ("alice@example.com", True),
    ("owner@candleviewer.local", True),  # the operator's owner address: a special-use domain
    ("a@", True),  # the `@` in position 2 is the whole requirement
    ("owner.candleviewer.local", False),  # no `@`
    ("@candleviewer.local", False),  # the `@` in position 1
    ("@owner@candleviewer.local", False),  # the first `@` decides; a later one does not help
    ("", False),
]
_USER_ID = "00000000-0000-4000-8000-000000000001"  # fixed: nothing here is random (C-13.7)


def _accepts(model: type[BaseModel], data: dict[str, Any]) -> bool:
    try:
        model.model_validate(data)
    except ValidationError:
        return False
    return True


def test_the_format_helper_asserts_format_where_a_plain_validate_would_not() -> None:
    schema = {"type": "string", "format": "uuid"}
    jsonschema.validate("not-a-uuid", schema)  # `format` is only an annotation here
    assert not _with_formats(schema).is_valid("not-a-uuid")


def test_the_email_check_the_contract_mirrors_is_the_stored_one() -> None:
    """`User.email` copies the CHECK on `users.email` (`users_email_fmt`); a change to it must
    lead here, to the pattern in the contract and to the cases below."""
    checks = [
        str(c.sqltext)
        for c in users.constraints
        if isinstance(c, CheckConstraint) and "email" in str(c.sqltext)
    ]
    assert checks == ["position('@' in email) > 1"]


@pytest.mark.parametrize(("address", "stored"), _EMAILS)
def test_user_email_is_accepted_exactly_when_the_database_would_store_it(
    address: str, stored: bool
) -> None:
    """The contract, the generated model that serves `GET /me` and `users_email_fmt` agree on every
    address. An `EmailStr` model refuses `.local`; `format: email` accepts a leading `@`."""
    user = {
        "id": _USER_ID,
        "username": "owner",
        "email": address,
        "roles": ["owner"],
        "status": "active",
    }
    contract = _with_formats(deref(_SPEC, {"$ref": "#/components/schemas/User"}))
    verdicts = {
        "database": address.find("@") + 1 > 1,  # `position` counts from 1 and gives 0 for no match
        "contract": contract.is_valid(user),
        "model": _accepts(api.User, user),
    }
    assert verdicts == dict.fromkeys(verdicts, stored), address
