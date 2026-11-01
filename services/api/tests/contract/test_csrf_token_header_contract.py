"""The desktop CSRF token response header (ADR-0038 S1 and S4.1, #3519).

`components.headers.CsrfTokenIssued` is the `X-CSRF-Token` response header that gives the SR-041
token to a page that cannot read the backend's cookie. The contract (C-6.1) declares it on the
`200` of the seven operations that issue the token in code: `POST /auth/login` (its enrolment-only
answer), `POST /auth/mfa/verify`, `POST /auth/mfa/recovery`, `POST /auth/mfa/enroll/confirm`,
`POST /auth/refresh`, `PUT /auth/password` (#5292) and `GET /auth/session`. `POST /auth/step-up`,
which the contract says rotates both cookies, issues none in code yet; it gains the header in the
change that makes it issue one (ADR-0038 F5). `POST /auth/logout` expires the cookie and carries
none (ADR-0038 3b). A flag can withhold the header, and only a request whose `Origin` is listed
can get it, so it is never `required`; it takes the request header's schema and is sensitive in
logs (SR-006).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec

_REF = {"$ref": "#/components/headers/CsrfTokenIssued"}
_ISSUING = {
    ("post", "/auth/login", "200"),
    ("post", "/auth/mfa/verify", "200"),
    ("post", "/auth/mfa/recovery", "200"),
    ("post", "/auth/mfa/enroll/confirm", "200"),
    ("post", "/auth/refresh", "200"),
    ("put", "/auth/password", "200"),
    ("get", "/auth/session", "200"),
}
_AUDIENCE = "a request whose `Origin` is listed"
#: The `200`/`204` responses that declare the SR-041 cookie but not the header: an expiry carries
#: no token, and step-up's route does not rotate the session yet (#2101, ADR-0038 F5).
_COOKIE_WITHOUT_HEADER = {
    ("post", "/auth/logout", "204"),
    ("post", "/auth/step-up", "200"),
}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _header(response: dict[str, Any], name: str) -> Any:
    """The response's header object named *name*, matched case-insensitively."""
    headers: dict[str, Any] = response.get("headers", {})
    return next((h for key, h in headers.items() if key.lower() == name.lower()), None)


def _token_header(response: dict[str, Any]) -> Any:
    return _header(response, "X-CSRF-Token")


def _responses(spec: dict[str, Any]) -> Iterator[tuple[tuple[str, str, str], dict[str, Any]]]:
    """Every operation response as ((method, path, status), response)."""
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if isinstance(operation, dict) and "responses" in operation:
                for status, response in operation["responses"].items():
                    yield (method, path, status), response


def _declared_headers(spec: dict[str, Any]) -> dict[tuple[str, str, str], Any]:
    """The `X-CSRF-Token` header object of each operation response that declares one."""
    return {
        key: header
        for key, response in _responses(spec)
        if (header := _token_header(response)) is not None
    }


def _flat(text: str) -> str:
    return " ".join(text.split())


def _token_header_prose(spec: dict[str, Any]) -> str:
    """The CSRF section's "Token response header" bullet, on one line."""
    text = _flat(spec["info"]["description"])
    start = text.index("**Token response header (ADR-0038).**")
    return text[start : text.index("* **Client modes.**", start)]


def test_csrf_token_header_declared_on_exactly_the_issuing_operations(
    spec: dict[str, Any],
) -> None:
    declared = _declared_headers(spec)
    assert set(declared) == _ISSUING
    assert all(header == _REF for header in declared.values())
    assert not any(_token_header(r) for r in spec["components"]["responses"].values())


def test_csrf_token_header_is_optional_no_store_and_redacted(spec: dict[str, Any]) -> None:
    header = spec["components"]["headers"]["CsrfTokenIssued"]
    assert header.get("required", False) is False
    assert header["schema"] == spec["components"]["parameters"]["CsrfToken"]["schema"]
    description = _flat(header["description"])
    assert "`<nonce>.<mac>`" in description
    assert "`Cache-Control: no-store`" in description
    assert "Sensitive in logs (SR-006)" in description


def test_csrf_token_header_audience_is_a_listed_origin_in_the_prose_and_the_component(
    spec: dict[str, Any],
) -> None:
    assert _AUDIENCE in _token_header_prose(spec)
    assert _AUDIENCE in _flat(spec["components"]["headers"]["CsrfTokenIssued"]["description"])


def test_csrf_token_header_prose_names_every_issuing_operation_and_the_step_up_gap(
    spec: dict[str, Any],
) -> None:
    prose = _token_header_prose(spec)
    for method, path, _status in sorted(_ISSUING):
        assert f"`{method.upper()} {path}`" in prose
    assert "`POST /auth/step-up`" in prose
    assert "Today the seven operations" in prose  # the count the set above pins
    assert "(its enrolment-only answer" in prose  # which of login's two `200`s issues it


def test_csrf_token_header_is_declared_on_every_cookie_issuing_response_but_logout_and_step_up(
    spec: dict[str, Any],
) -> None:
    cookie = {
        key
        for key, response in _responses(spec)
        if "csrf" in str(_header(response, "Set-Cookie") or "").lower()
    }
    declared = set(_declared_headers(spec))
    assert declared <= cookie
    assert cookie - declared == _COOKIE_WITHOUT_HEADER
