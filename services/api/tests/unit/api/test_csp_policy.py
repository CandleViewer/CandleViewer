"""E43-T01 (SR-112, C-12.10): the API's CSP header is the shared policy. This mirror, the Electron
one and the web meta all equal `packages/config/src/csp-policy.golden.json`; the header rides every
HTTP answer of the deployed app, a refusal and a `404` included."""

from __future__ import annotations

import json
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import candleviewer.app as appmod
from candleviewer.api.csp import (
    CspConfigError,
    build_csp_policy,
    build_reporting_endpoints,
    parse_tailnet_host,
    resolve_backend_origin,
    tailnet_host_from,
)
from candleviewer.api.response_headers import ContentSecurityPolicy
from candleviewer.settings import Settings

ROOT = Path(__file__).resolve().parents[5]
GOLDEN: dict[str, Any] = json.loads(
    (ROOT / "packages/config/src/csp-policy.golden.json").read_text(encoding="utf-8")
)


def test_the_default_policy_equals_the_golden_header() -> None:
    assert build_csp_policy() == GOLDEN["header"]
    assert build_reporting_endpoints() == GOLDEN["reporting_endpoints"]


def test_every_golden_variant_matches() -> None:
    assert build_csp_policy(tailnet_host="Box.tail1234.ts.net") == GOLDEN["tailnet"]
    assert build_csp_policy(tailnet_host="box.tail1234.ts.net:8443") == GOLDEN["tailnet_port"]
    assert build_csp_policy("https://localhost:9000") == GOLDEN["https_loopback_origin"]
    assert build_csp_policy("http://evil.example") == GOLDEN["non_loopback_origin_falls_back"]


@pytest.mark.parametrize("host", GOLDEN["invalid_tailnet_hosts"])
def test_an_invalid_tailnet_host_is_ignored_by_the_builder(host: str) -> None:
    assert parse_tailnet_host(host) is None
    assert build_csp_policy(tailnet_host=host) == GOLDEN["header"]


@pytest.mark.parametrize("host", GOLDEN["invalid_tailnet_hosts"][:-1])
def test_an_invalid_configured_tailnet_host_refuses_startup(host: str) -> None:
    with pytest.raises(CspConfigError):
        tailnet_host_from(Settings(csp_tailnet_host=host))


def test_an_unset_or_blank_tailnet_host_means_loopback_only() -> None:
    assert tailnet_host_from(Settings()) is None
    assert tailnet_host_from(Settings(csp_tailnet_host="  ")) is None
    assert tailnet_host_from(Settings(csp_tailnet_host="Box.tail1234.ts.net")) == (
        "box.tail1234.ts.net"
    )


def test_no_unsafe_source_and_no_wildcard_in_any_variant() -> None:
    for policy in (GOLDEN["header"], GOLDEN["tailnet"], GOLDEN["tailnet_port"]):
        assert "unsafe-" not in policy
        assert "*" not in policy
        assert "style-src 'self';" in policy
        assert "worker-src 'self' blob:;" in policy


def test_origin_resolution_is_loopback_only() -> None:
    assert resolve_backend_origin("http://localhost:9000/x") == "http://localhost:9000"
    assert resolve_backend_origin("http://[::1]:9000") == "http://[::1]:9000"
    assert resolve_backend_origin("http://127.0.0.1:80") == "http://127.0.0.1"
    for raw in ("not a url", "ftp://127.0.0.1", "http://[bad", "http://127.0.0.1:x", "//x"):
        assert resolve_backend_origin(raw) == "http://127.0.0.1:8000"


def test_the_header_is_set_on_every_answer_replacing_a_route_value() -> None:
    app = FastAPI()
    app.add_api_route("/ok", lambda: JSONResponse({}, headers={"Content-Security-Policy": "x"}))

    def boom() -> None:
        raise RuntimeError("unhandled")

    app.add_api_route("/boom", boom)
    client = TestClient(
        ContentSecurityPolicy(app, policy="P", reporting_endpoints="R"),
        raise_server_exceptions=False,
    )
    for path in ("/ok", "/boom", "/missing"):
        r = client.get(path)
        assert r.headers.get_list("content-security-policy") == ["P"]
        assert r.headers.get_list("reporting-endpoints") == ["R"]


@pytest.mark.parametrize("path", ["/health/live", "/admin/overview", "/nope"])
def test_the_deployed_app_sends_the_policy_on_every_answer(path: str) -> None:
    app = appmod.create_app(Settings())
    r = TestClient(app, client=("127.0.0.1", 50000)).get(path)
    assert r.headers.get_list("content-security-policy") == [GOLDEN["header"]]
    assert r.headers.get_list("reporting-endpoints") == [GOLDEN["reporting_endpoints"]]


def test_the_deployed_app_adds_the_configured_tailnet_host() -> None:
    app = appmod.create_app(Settings(csp_tailnet_host="box.tail1234.ts.net"))
    r = TestClient(app, client=("127.0.0.1", 50000)).get("/health/live")
    assert r.headers["content-security-policy"] == GOLDEN["tailnet"]


async def test_a_non_http_scope_is_not_stamped() -> None:
    seen: list[str] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    async def receive() -> MutableMapping[str, Any]:
        return {}

    async def send(message: MutableMapping[str, Any]) -> None:
        return None

    stamped = ContentSecurityPolicy(inner, policy="P", reporting_endpoints="R")
    await stamped({"type": "lifespan"}, receive, send)
    assert seen == ["lifespan"]
