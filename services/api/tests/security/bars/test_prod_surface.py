"""E12-X02 production surface (#452; X01 AC-12, BR-26, SR-E12-16): the app `create_app()` builds
mounts no probe, debug, diagnostics, test or e2e route (beyond operations 22 documents behind a
permission), and the setting that would serve a
fixture-driven test clock is off by default and refused outside testnet.

The bundle half (no `SCR-046` / probe code in a production web build) is E12-X03's gate
(`docs/plan/security/ci-gates-e12.md`, Semgrep `cv-no-debug-probe-in-prod`); it is cited, not
repeated.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from functools import cache
from typing import Any, Final

import pytest
from pydantic import ValidationError

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.deny_by_default import rbac_permissions, served_operations
from candleviewer.app import create_app
from candleviewer.settings import Environment, Settings

_DEBUG: Final = re.compile(r"probe|debug|diag|__test|test[-_]clock|e2e|fixture", re.IGNORECASE)


def _paths(routes: list[Any], prefix: str = "") -> Iterator[str]:
    """Every route path: included routers (FastAPI keeps them as `original_router`), mounted
    sub-applications and WebSocket routes included, as `served_operations` walks them."""
    for route in routes:
        if (inner := getattr(route, "original_router", None)) is not None:
            ctx = getattr(getattr(route, "include_context", None), "prefix", "") or ""
            yield from _paths(list(inner.routes), prefix + ctx)
            continue
        path = prefix + str(getattr(route, "path", ""))
        yield path
        yield from _paths(list(getattr(route, "routes", []) or []), path)


@cache
def _served() -> frozenset[str]:
    return frozenset(_paths(list(create_app().routes)))


def test_prod_surface_scan_sees_every_served_route_so_it_is_not_vacuous() -> None:
    assert {path for _, path in served_operations(create_app())} <= _served()
    assert {"/market/bars", "/market/klines"} <= _served()


def test_prod_surface_no_probe_or_debug_route_is_mounted() -> None:
    """A path matching the pattern is allowed only as an operation 22 documents behind a
    permission (`getOrderDiagnostics`, an order's lifecycle trace, is one): never a probe."""
    gated = {path for _, path in rbac_permissions(load_openapi_spec())}
    assert sorted(p for p in _served() if _DEBUG.search(p) and p not in gated) == []


def test_prod_surface_test_clock_is_off_by_default() -> None:
    assert Settings.model_fields["test_clock"].default is False


@pytest.mark.parametrize("environment", [Environment.LIVE, Environment.DEMO])
def test_prod_surface_test_clock_is_refused_outside_testnet(environment: Environment) -> None:
    with pytest.raises(ValidationError, match="CV_TEST_CLOCK"):
        Settings.model_validate({"environment": environment, "test_clock": True})  # no .env read
