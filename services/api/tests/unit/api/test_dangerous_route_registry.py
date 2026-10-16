"""Deny-by-default for step-up gating (E09-S04 review finding): every mounted
write route whose path looks dangerous (users, keys, live enablement,
kill-switch, risk override, audit, backups) must be registered in
`DANGEROUS_ROUTES` or `HANDLER_GATED_ROUTES`, so a later ticket cannot mount
one ungated."""

from __future__ import annotations

import re

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from candleviewer.api.deny_by_default import served_operations
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
    ("POST", "/admin/audit/verify"),  # verifyAuditChain: `audit:read`, no step-up (04 row 49a)
    # Contract summaries name step-up for `restoreBackup` only (04 row 52 also lists these).
    ("POST", "/admin/backups"),  # createBackup: "Trigger a backup run"
    ("POST", "/admin/backups/{backupId}/verify"),  # verifyBackup: restores into a scratch namespace
}


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x1", path)


def _ungated(method: str, path: str) -> bool:
    if (method, path) in _NOT_DANGEROUS:
        return False
    if dangerous_action_class(method, _concrete(path)) is not None:
        return False
    return not any(m == method and p == path for m, p, _ in HANDLER_GATED_ROUTES)


def _ungated_dangerous_writes(app: FastAPI) -> list[tuple[str, str]]:
    # `served_operations` walks the included routers: on FastAPI 0.141 the top level of
    # `app.routes` holds `_IncludedRouter` wrappers, so an `APIRoute` filter there sees nothing.
    writes = sorted(op for op in served_operations(app) if op[0] in _WRITE)
    return [(m, p) for m, p in writes if DANGEROUS_PATH_PATTERN.match(p) and _ungated(m, p)]


def test_every_mounted_dangerous_write_route_is_gated() -> None:
    assert _ungated_dangerous_writes(create_app()) == []


def test_gate_sees_a_route_mounted_through_an_included_router() -> None:
    """Regression (#2751): the gate filtered the top level of `app.routes` for `APIRoute`,
    found none on FastAPI 0.141 and passed whatever was mounted (the ungated audit export)."""
    app = create_app()
    router = APIRouter(prefix="/admin/audit")

    @router.delete("/exports/{exportId}")
    async def unregistered() -> None: ...

    app.include_router(router)
    assert _ungated_dangerous_writes(app) == [("DELETE", "/admin/audit/exports/{exportId}")]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/admin/keys/{keyId}/reveal"),
        ("POST", "/admin/users/{userId}/disable"),
        ("POST", "/admin/live/enable"),
        ("DELETE", "/admin/kill/{id}"),
        ("PUT", "/users/{userId}/password"),
        ("DELETE", "/admin/audit/{eventId}"),
        ("DELETE", "/admin/backups/{backupId}"),  # deleteBackup: in no 04 §7.2.2 row yet
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
        ("PATCH", "/users/u", "users"),  # updateUser (04 row 38)
        ("DELETE", "/users/u", "users"),  # deleteUser (04 row 38)
        ("PUT", "/users/u/account-access", "users"),  # setUserAccountAccess (04 row 40)
        ("POST", "/admin/audit/export", "audit"),  # exportAuditLog (SR-025, 04 row 50)
        ("POST", "/admin/backups/b/restore", "backups"),  # restoreBackup (04 row 52)
    ],
)
def test_contract_dangerous_routes_map_to_action_class(
    method: str, path: str, action_class: str
) -> None:
    assert dangerous_action_class(method, path) == action_class


def test_safe_reads_are_not_gated() -> None:
    assert dangerous_action_class("GET", "/users/u/mfa/reset-preview") is None
    assert dangerous_action_class("GET", "/exchange-accounts/a/keys") is None
    assert dangerous_action_class("GET", "/users/u") is None
    assert dangerous_action_class("GET", "/admin/backups/b") is None
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


def test_recorder_purge_is_handler_gated_not_middleware_gated() -> None:
    """E16-T06 review (a): middleware step-up would pre-empt the handler's owner-only check."""
    assert dangerous_action_class("POST", "/admin/recorder/purge") is None
    assert ("POST", "/admin/recorder/purge", "recorder") in HANDLER_GATED_ROUTES
    assert not _ungated("POST", "/admin/recorder/purge")
