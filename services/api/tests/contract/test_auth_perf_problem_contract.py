"""Contract (#2097): the refusals `GET /auth/_perf/argon2-params` serves conform to the responses
the contract declares for it.

The operation declares `401` and `403` as the shared `Unauthorized` and `Forbidden` responses,
whose body is `Problem`: `type`, `title`, `status` and the catalogued `code` are required. With no
principal resolver wired the route fails closed with `501`. No operation declares that status; the
registry (`x-error-codes`) catalogues `not_implemented` as it, so that body is checked against
`Problem` and the registry. Each refusal comes from the real router on a bare app with a fake
resolver; the real app's own 401 and 403 are pinned in
`tests/contract/rbac/test_auth_perf_matrix.py`. No network, no database (C-13.5).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import Response
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.auth_perf import make_auth_perf_router
from candleviewer.api.contract_conformance import load_openapi_spec

_BASE = "urn:cv:openapi"
_PATH = "/auth/_perf/argon2-params"
_PROBLEM = "application/problem+json"
_ERRORS = "https://candleviewer.local/errors/"  # `Problem.type` is this plus the `code`
_SPEC: Any = load_openapi_spec()
_RESPONSES: dict[str, Any] = _SPEC["paths"][_PATH]["get"]["responses"]


class _Principal:
    def __init__(self, *permissions: str) -> None:
        self._permissions = frozenset(permissions)

    def has(self, permission: str) -> bool:
        return permission in self._permissions


class _Resolver:
    def __init__(self, principal: _Principal | None) -> None:
        self._principal = principal

    async def resolve(self, request: Request) -> _Principal | None:
        return self._principal


def _refusal(status: int) -> Response:
    """The route's refusal with *status*, from the real router and the fake that provokes it."""
    resolvers = {
        401: _Resolver(None),  # a resolver that finds no verified session
        403: _Resolver(_Principal("accounts:read")),  # a session without `admin:read`
        501: None,  # no resolver wired at all
    }
    app = FastAPI()
    app.include_router(make_auth_perf_router(resolvers[status]))
    response: Response = TestClient(app).get(_PATH)
    return response


def _body_schema(status: int) -> dict[str, str]:
    """A `$ref` to the `application/problem+json` schema the contract declares for *status*
    on this operation; for a status it declares on no operation (501), to `Problem`."""
    declared = _RESPONSES.get(str(status))
    if declared is None:
        return {"$ref": f"{_BASE}#/components/schemas/Problem"}
    return {"$ref": f"{_BASE}{declared['$ref']}/content/application~1problem+json/schema"}


def _validator(schema: dict[str, str]) -> Draft202012Validator:
    resource = Resource.from_contents(_SPEC, default_specification=DRAFT202012)
    return Draft202012Validator(
        schema,
        registry=Registry().with_resource(_BASE, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def _catalogued(code: str) -> dict[str, Any]:
    (entry,) = (e for e in _SPEC["x-error-codes"] if e["code"] == code)
    return dict(entry)


def test_perf_params_declares_the_shared_401_and_403_responses() -> None:
    assert _RESPONSES["401"] == {"$ref": "#/components/responses/Unauthorized"}
    assert _RESPONSES["403"] == {"$ref": "#/components/responses/Forbidden"}


@pytest.mark.parametrize(
    ("status", "code"),
    [
        pytest.param(401, "unauthenticated", id="no_session"),
        pytest.param(403, "forbidden", id="missing_permission"),
        pytest.param(501, "not_implemented", id="no_resolver"),
    ],
)
def test_perf_params_refusal_conforms_to_the_declared_response(status: int, code: str) -> None:
    response = _refusal(status)
    assert (response.status_code, response.headers["content-type"]) == (status, _PROBLEM)
    body = response.json()
    _validator(_body_schema(status)).validate(body)
    assert (body["status"], body["code"], body["type"]) == (status, code, f"{_ERRORS}{code}")
    assert _catalogued(code)["status"] == status


def test_perf_params_refusal_without_a_code_does_not_conform() -> None:
    """The body these refusals first had (no `code`, an `about:blank` type): the declared
    schema rejects it, so the conformance check above can fail."""
    unconformed = {
        "type": "about:blank",
        "title": "Unauthorized",
        "status": 401,
        "detail": "no verified session for this request",
    }
    with pytest.raises(ValidationError, match="'code' is a required property"):
        _validator(_body_schema(401)).validate(unconformed)
