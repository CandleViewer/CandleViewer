"""The desktop CSRF token response header (ADR-0038 S1, #3519).

`components.headers.CsrfTokenIssued` is the `X-CSRF-Token` response header that gives the SR-041
token to a page that cannot read the backend's cookie. The contract (C-6.1) declares it only on the
`200` of the three operations that issue the token in code; each other operation in the CSRF issue
list gains it in the change that makes it issue one (ADR-0038 F5). A flag can withhold it, so it is
never `required`; it takes the request header's schema and is sensitive in logs (SR-006).
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec

_REF = {"$ref": "#/components/headers/CsrfTokenIssued"}
_ISSUING = {
    ("post", "/auth/mfa/verify", "200"),
    ("post", "/auth/refresh", "200"),
    ("get", "/auth/session", "200"),
}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _token_header(response: dict[str, Any]) -> Any:
    headers: dict[str, Any] = response.get("headers", {})
    return next((h for name, h in headers.items() if name.lower() == "x-csrf-token"), None)


def test_csrf_token_header_declared_on_exactly_the_issuing_operations(
    spec: dict[str, Any],
) -> None:
    declared = {
        (method, path, status): header
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if isinstance(operation, dict) and "responses" in operation
        for status, response in operation["responses"].items()
        if (header := _token_header(response)) is not None
    }
    assert set(declared) == _ISSUING
    assert all(header == _REF for header in declared.values())
    assert not any(_token_header(r) for r in spec["components"]["responses"].values())


def test_csrf_token_header_is_optional_no_store_and_redacted(spec: dict[str, Any]) -> None:
    header = spec["components"]["headers"]["CsrfTokenIssued"]
    assert header.get("required", False) is False
    assert header["schema"] == spec["components"]["parameters"]["CsrfToken"]["schema"]
    description = " ".join(header["description"].split())
    assert "`<nonce>.<mac>`" in description
    assert "`Cache-Control: no-store`" in description
    assert "Sensitive in logs (SR-006)" in description
