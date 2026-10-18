"""SR-026 (#2573, #2632): a self-service route's query allow-list is exactly the query parameters
its contract operation declares (22-api-openapi.yaml, path-level and operation-level), and the
operation declares the 422 the refusal answers with (C-6.1). A parameter the contract adds is
accepted only once the handler is taught it. `DELETE /users/{userId}`, an owner route, keeps the
same allow-list (E42-T04 S7, #965)."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.api import alerts, me, onboarding, sessions, users
from candleviewer.api.contract_conformance import load_openapi_spec


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _declared_query(spec: dict[str, Any], path: str, method: str) -> frozenset[str]:
    item = spec["paths"][path]
    names: set[str] = set()
    for p in [*item.get("parameters", []), *item[method].get("parameters", [])]:
        if "$ref" in p:
            p = spec["components"]["parameters"][p["$ref"].rsplit("/", 1)[-1]]
        if p["in"] == "query":
            names.add(p["name"])
    return frozenset(names)


@pytest.mark.parametrize(
    ("method", "path", "allowed"),
    [
        ("post", "/auth/logout", sessions.LOGOUT_QUERY),
        ("delete", "/me/sessions/{sessionId}", sessions.REVOKE_MY_SESSION_QUERY),
        ("get", "/alerts", alerts.LIST_ALERTS_QUERY),
        ("get", "/alerts/{alertId}", alerts.GET_ALERT_QUERY),
        ("get", "/onboarding/checklist", onboarding.CHECKLIST_QUERY),
        ("get", "/me", me.GET_ME_QUERY),
        ("get", "/me/preferences", me.GET_MY_PREFERENCES_QUERY),
        ("get", "/me/keymap", me.GET_MY_KEYMAP_QUERY),
        ("delete", "/users/{userId}", users.DELETE_USER_QUERY),
    ],
)
def test_self_service_allow_list_is_the_operations_declared_query(
    spec: dict[str, Any], method: str, path: str, allowed: frozenset[str]
) -> None:
    assert _declared_query(spec, path, method) == allowed
    assert "422" in spec["paths"][path][method]["responses"], "the refusal is a declared response"
