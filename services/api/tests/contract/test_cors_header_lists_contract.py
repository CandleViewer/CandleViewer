"""The CORS header lists follow the contract (ADR-0038 2b, #3519 S3a).

The runtime has only the pruned contract subset, so `api/cors.py` holds both lists as constants.
This dev-only walk derives them from every operation of `22-api-openapi.yaml` and fails on drift.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.cors import ALLOW_HEADERS, EXPOSE_HEADERS

_HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
#: The CORS-safelisted response headers (Fetch): a page reads them without being told.
_SAFELISTED = {
    "cache-control",
    "content-language",
    "content-length",
    "content-type",
    "expires",
    "last-modified",
    "pragma",
}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _resolve(spec: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """`node`, or the `components` entry its `$ref` names."""
    ref = node.get("$ref")
    if ref is None:
        return node
    target = spec
    for key in ref.removeprefix("#/").split("/"):
        target = target[key]
    return target


def _owners(spec: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every path item and every operation."""
    for item in spec["paths"].values():
        yield item
        yield from (op for method, op in item.items() if method in _HTTP_METHODS)


def _distinct(names: tuple[str, ...]) -> set[str]:
    """`names`, lowered; a name twice, in any case, or a `*` fails."""
    lowered = {name.lower() for name in names}
    assert len(lowered) == len(names)
    assert "*" not in lowered
    return lowered


def test_cors_allow_headers_equal_authorization_content_type_and_every_declared_header_parameter(
    spec: dict[str, Any],
) -> None:
    refs = [p for owner in _owners(spec) for p in owner.get("parameters", [])]
    parameters = [*(_resolve(spec, p) for p in refs), *spec["components"]["parameters"].values()]
    declared = {p["name"].lower() for p in parameters if p["in"] == "header"}

    assert _distinct(ALLOW_HEADERS) == {"authorization", "content-type"} | declared


def test_cors_expose_headers_equal_declared_response_headers_less_safelisted_plus_correlation_id(
    spec: dict[str, Any],
) -> None:
    """Every response header the contract declares, less the safelisted ones and `Set-Cookie`
    (script never reads it), plus `X-Correlation-Id`, which the contract's CORS paragraph adds."""
    refs = [r for owner in _owners(spec) for r in owner.get("responses", {}).values()]
    responses = [*(_resolve(spec, r) for r in refs), *spec["components"]["responses"].values()]
    # The wire names are the keys of a response's `headers` map, not the `components.headers` ids.
    headers = [header for r in responses for header in r.get("headers", {}).items()]
    declared = {name.lower() for name, _ in headers}
    exposed = {*declared - _SAFELISTED - {"set-cookie"}, "x-correlation-id"}

    assert _distinct(EXPOSE_HEADERS) == exposed
    assert {"retry-after", "x-csrf-token"} <= exposed
    # Every declared header object is reached by the walk, so no wire name can be missed.
    referenced = {header["$ref"] for _, header in headers if "$ref" in header}
    assert {f"#/components/headers/{name}" for name in spec["components"]["headers"]} <= referenced
