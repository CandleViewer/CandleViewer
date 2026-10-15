"""Step-up session rotation contract (SR-013, #2101), slice 1/3: contract only (C-6.1).

Pins the `POST /auth/step-up` `200` that the rotation slice implements: the body gains `tokens`,
the `TokenBundle` that `POST /auth/mfa/verify` returns, and the response sets the rotated
`cv_refresh` and `__Host-cv_csrf` cookies exactly as `POST /auth/refresh` does. Also pins the
approved rotation rules (the replacement keeps the absolute expiry and idle timeout, carries the
live grants over and drops the pending challenge; the old session is revoked as `rotated` inside
the refresh-token family). The route answers the old body until the rotation slice lands;
`tests/unit/api/test_step_up_router.py` pins that runtime and this slice leaves it alone.
"""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec

_BASE = "urn:cv:openapi"
_STEP_UP_OK = "/paths/~1auth~1step-up/post/responses/200/content/application~1json/schema"
_TOKEN_BUNDLE = {"$ref": "#/components/schemas/TokenBundle"}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _ok(spec: dict[str, Any], path: str) -> dict[str, Any]:
    response: dict[str, Any] = spec["paths"][path]["post"]["responses"]["200"]
    return response


def _body(spec: dict[str, Any], path: str) -> dict[str, Any]:
    schema: dict[str, Any] = _ok(spec, path)["content"]["application/json"]["schema"]
    return schema


def _validator(spec: dict[str, Any]) -> Draft202012Validator:
    resource = Resource.from_contents(spec, default_specification=DRAFT202012)
    return Draft202012Validator(
        {"$ref": f"{_BASE}#{_STEP_UP_OK}"},
        registry=Registry().with_resource(_BASE, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def _granted(spec: dict[str, Any]) -> dict[str, Any]:
    """A rotated step-up body; `tokens` reuses the contract's documented login bundle."""
    login = _ok(spec, "/auth/login")["content"]["application/json"]["examples"]
    return {
        "elevated_until": "2026-10-15T12:05:00Z",
        "action_class": "users",
        "single_use": False,
        "step_up_expires_at": "2026-10-15T12:05:00Z",
        "tokens": login["authenticated"]["value"]["tokens"],
    }


def _flat(text: str) -> str:
    """Collapse YAML line wrapping so prose pins survive a re-wrap."""
    return " ".join(text.split())


def test_step_up_ok_requires_the_token_bundle_that_mfa_verify_returns(
    spec: dict[str, Any],
) -> None:
    verify = _body(spec, "/auth/mfa/verify")
    assert verify == {"$ref": "#/components/schemas/AuthenticatedResponse"}
    authenticated = spec["components"]["schemas"]["AuthenticatedResponse"]
    assert authenticated["properties"]["tokens"] == _TOKEN_BUNDLE
    body = _body(spec, "/auth/step-up")
    assert body["properties"]["tokens"] == _TOKEN_BUNDLE
    assert set(body["required"]) == {"elevated_until", "action_class", "single_use", "tokens"}


def test_step_up_ok_sets_the_rotated_cookies_exactly_as_refresh(spec: dict[str, Any]) -> None:
    headers = _ok(spec, "/auth/step-up")["headers"]
    assert set(headers) == {"Set-Cookie"}
    assert headers == _ok(spec, "/auth/refresh")["headers"]


def test_step_up_ok_body_with_rotated_tokens_conforms(spec: dict[str, Any]) -> None:
    _validator(spec).validate(_granted(spec))


def test_step_up_ok_body_without_tokens_no_longer_conforms(spec: dict[str, Any]) -> None:
    pre_rotation = {k: v for k, v in _granted(spec).items() if k != "tokens"}
    with pytest.raises(ValidationError, match="'tokens' is a required property"):
        _validator(spec).validate(pre_rotation)


@pytest.mark.parametrize(
    "rule",
    [
        "A successful step-up also rotates the session",
        "keeps the old session's absolute expiry and idle timeout",
        "carries over the live step-up grants, including the one just granted",
        "drops the pending challenge",
        "revoked as `rotated` and linked into the refresh-token family",
        "its access and refresh tokens stop working at once",
    ],
)
def test_step_up_description_states_the_approved_rotation_rule(
    spec: dict[str, Any], rule: str
) -> None:
    assert rule in _flat(spec["paths"]["/auth/step-up"]["post"]["description"])


def test_csrf_section_lists_step_up_as_a_rotation_point(spec: dict[str, Any]) -> None:
    info = _flat(spec["info"]["description"])
    start = info.index("**Issue, rotate and re-issue.**")
    bullet = info[start : info.index("**Multi-tab.**", start)]
    assert "A successful `POST /auth/step-up` rotates the session (SR-013)" in bullet


def test_csrf_cookie_scheme_lists_step_up_as_a_rotation_point(spec: dict[str, Any]) -> None:
    scheme = _flat(spec["components"]["securitySchemes"]["csrfCookie"]["description"])
    assert "rotated on every `/auth/refresh` and on a successful `/auth/step-up`" in scheme
