"""Deny-by-default for step-up gating (E09-S04 review finding): every mounted
write route whose path looks dangerous (users, keys, live enablement,
kill-switch, risk override) must be registered in `DANGEROUS_ROUTES` or
`HANDLER_GATED_ROUTES`, so a later ticket cannot mount one ungated."""

from __future__ import annotations

import re

import pytest
from fastapi.routing import APIRoute

from candleviewer.api.step_up import (
    DANGEROUS_PATH_PATTERN,
    DANGEROUS_ROUTES,
    HANDLER_GATED_ROUTES,
    dangerous_action_class,
)
from candleviewer.app import create_app

_WRITE = {"POST", "PUT", "PATCH", "DELETE"}
#: Dangerous-looking writes that are deliberately not step-up gated.
_NOT_DANGEROUS = {
    ("POST", "/exchange-accounts/{accountId}/keys/{keyId}/test"),  # read-only probe
}


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x1", path)


def _ungated(method: str, path: str) -> bool:
    if (method, path) in _NOT_DANGEROUS:
        return False
    if dangerous_action_class(method, _concrete(path)) is not None:
        return False
    return not any(m == method and p == path for m, p, _ in HANDLER_GATED_ROUTES)


def test_every_mounted_dangerous_write_route_is_gated() -> None:
    app = create_app()
    missing = [
        (m, r.path)
        for r in app.routes
        if isinstance(r, APIRoute) and DANGEROUS_PATH_PATTERN.match(r.path)
        for m in r.methods & _WRITE
        if _ungated(m, r.path)
    ]
    assert missing == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/admin/keys/{keyId}/reveal"),
        ("POST", "/admin/users/{userId}/disable"),
        ("POST", "/admin/live/enable"),
        ("DELETE", "/admin/kill/{id}"),
        ("PATCH", "/users/{userId}"),
    ],
)
def test_future_unregistered_dangerous_route_is_flagged(method: str, path: str) -> None:
    """The fixture a later ticket would trip: a new route under the
    dangerous prefixes is matched by the pattern and reported ungated."""
    assert DANGEROUS_PATH_PATTERN.match(path)
    assert _ungated(method, path)


@pytest.mark.parametrize(
    ("method", "path", "action_class"),
    [
        ("PUT", "/users/u/roles", "users"),
        ("POST", "/users", "users"),
        ("POST", "/users/u/invite", "users"),
        ("DELETE", "/users/u/invite", "users"),
        ("POST", "/users/u/mfa/reset", "users"),
        ("POST", "/exchange-accounts/a/keys", "keys"),
        ("POST", "/exchange-accounts/a/keys/k/rotate", "keys"),
        ("DELETE", "/exchange-accounts/a/keys/k", "keys"),
        ("POST", "/risk/lockouts/a/override", "risk_caps"),
        ("POST", "/admin/recorder/purge", "recorder"),
    ],
)
def test_contract_dangerous_routes_map_to_action_class(
    method: str, path: str, action_class: str
) -> None:
    assert dangerous_action_class(method, path) == action_class


def test_safe_reads_are_not_gated() -> None:
    assert dangerous_action_class("GET", "/users/u/mfa/reset-preview") is None
    assert dangerous_action_class("GET", "/exchange-accounts/a/keys") is None
    assert len(DANGEROUS_ROUTES) >= 7


def test_invites_router_write_routes_are_gated() -> None:
    """The default create_app() does not mount the invite router, so build it
    directly and assert every owner write route is registered (review finding)."""
    from candleviewer.api.invites import make_invites_router

    class _Auth:  # route registration only; never called
        invites_is_active = False

    router = make_invites_router(_Auth(), object(), lambda *_a, **_k: None, audit_ready=bool)  # type: ignore[arg-type]  # registration-only stub
    missing = [
        (m, r.path)
        for r in router.routes
        if isinstance(r, APIRoute) and DANGEROUS_PATH_PATTERN.match(r.path)
        for m in r.methods & _WRITE
        if _ungated(m, r.path)
    ]
    assert missing == []
