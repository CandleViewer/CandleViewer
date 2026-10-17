"""Deny-by-default for step-up gating (E09-S04 review finding): every mounted
write route whose path looks dangerous (users, keys, live enablement,
kill-switch, risk override, audit, backups, recorded-data retention and purge)
must be registered in `DANGEROUS_ROUTES` or `HANDLER_GATED_ROUTES`, so a later
ticket cannot mount one ungated."""

from __future__ import annotations

import functools
import re
from collections.abc import Sequence
from typing import Any, cast

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute, Host, Mount
from starlette.types import Receive, Scope, Send

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.step_up import (
    DANGEROUS_PATH_PATTERN,
    DANGEROUS_ROUTES,
    HANDLER_GATED_ROUTES,
    dangerous_action_class,
)
from candleviewer.app import create_app
from candleviewer.auth.step_up import ACTION_CLASSES, NO_GRACE_ACTION_CLASSES

_WRITE = {"POST", "PUT", "PATCH", "DELETE"}
#: Dangerous-looking writes that are deliberately not step-up gated.
_NOT_DANGEROUS = {
    ("POST", "/exchange-accounts/{accountId}/keys/{keyId}/test"),  # read-only probe
    ("POST", "/admin/audit/verify"),  # verifyAuditChain: `audit:read`, no step-up (04 row 49a)
    # Contract summaries name step-up for `restoreBackup` only (04 row 52 also lists these).
    ("POST", "/admin/backups"),  # createBackup: "Trigger a backup run"
    ("POST", "/admin/backups/{backupId}/verify"),  # verifyBackup: restores into a scratch namespace
    # #2738: `recording:write` without step-up for Owner and Manager (04 §7.2.2 row 51); neither
    # changes retention or deletes recorded data (addRecordedSymbol can: it is handler-gated).
    ("POST", "/admin/recorder/compact"),  # compactRecorder: merges cold-tier files
    ("POST", "/admin/recorder/import"),  # importTradeArchive: adds archive trades
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


def _dangerous_tail(path: str) -> bool:
    """The path, or any tail of it starting at a `/`, matches the pattern."""
    parts = path.split("/")
    tails = ("/" + "/".join(parts[i:]) for i in range(1, len(parts)))
    return any(DANGEROUS_PATH_PATTERN.match(tail) for tail in tails)


#: Sub-applications with no route list to inspect (static files, a third-party ASGI app): the
#: tripwire cannot see what they serve, so each needs an entry here with its reason.
_OPAQUE_MOUNTS: frozenset[str] = frozenset()


def _hidden_in_sub_apps(
    routes: Sequence[BaseRoute],
    prefix: str = "",
    inside: bool = False,
    opaque_ok: frozenset[str] = _OPAQUE_MOUNTS,
) -> list[str]:
    """Paths a `Mount` or `Host` sub-application may serve out of sight of the gate above.

    #2752 security re-review: `served_operations` does not descend into sub-applications,
    and the read-only guard classifies the whole routed path, so `/v2/recording/...` matches
    no `DANGEROUS_ROUTES` row: such a route would run ungated without the gate above seeing
    it. A sub-app with no routes to inspect is reported wherever it is mounted unless
    `opaque_ok` names it, and at a dangerous-looking mount path even then."""
    found: list[str] = []
    for route in routes:
        inner = getattr(route, "original_router", None)
        path = prefix + str(getattr(route, "path", ""))
        if inner is not None:  # a FastAPI 0.141 `include_router` wrapper, not a sub-app
            context = getattr(route, "include_context", None)
            nested = prefix + str(getattr(context, "prefix", "") or "")
            found += _hidden_in_sub_apps(inner.routes, nested, inside, opaque_ok)
        elif isinstance(route, Mount | Host):
            where = path or "/"
            if isinstance(route, Host):
                where += f" (host {route.host})"
            opaque = not route.routes and where not in opaque_ok
            found += [where] if opaque or _dangerous_tail(path) else []
            found += _hidden_in_sub_apps(route.routes, path, True, opaque_ok)
        elif inside and _dangerous_tail(path):
            found.append(path)
    return found


def test_no_sub_application_hides_a_dangerous_route() -> None:
    assert _hidden_in_sub_apps(create_app().routes) == []


async def _opaque_asgi(scope: Scope, receive: Receive, send: Send) -> None:
    """A sub-application with no `routes` to inspect."""


def test_sub_application_tripwire_catches_a_mounted_dangerous_route() -> None:
    sub = FastAPI()

    @sub.put("/recording/retention-policies")
    async def hidden() -> None: ...

    @sub.get("/health")
    async def health() -> None: ...

    app = FastAPI()
    app.mount("/v2", sub)
    app.mount("/admin/recorder", _opaque_asgi)
    app.mount("/static", _opaque_asgi)
    assert _ungated_dangerous_writes(app) == []  # the blind spot this tripwire covers
    found = ["/v2/recording/retention-policies", "/admin/recorder", "/static"]
    assert _hidden_in_sub_apps(app.routes) == found
    # Listing an opaque mount clears a harmless-looking path only (#2738 review).
    listed = frozenset({"/admin/recorder", "/static"})
    assert _hidden_in_sub_apps(app.routes, opaque_ok=listed) == found[:2]


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
        # #2738: the recording and recorder prefixes are swept whole, not only today's paths.
        ("POST", "/recording/symbols/{recordedSymbolId}/pin"),  # E16-T08 says POST; contract PUT
        ("DELETE", "/recording/retention-policies/{policyId}"),
        ("DELETE", "/recording/sessions/{sessionId}"),
        ("DELETE", "/recordings/{recordingId}"),
        ("POST", "/admin/recorder/purge-all"),
        ("DELETE", "/admin/recorder/jobs/{jobId}"),
        ("POST", "/admin/recording/wipe"),
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
        ("PUT", "/recording/retention-policies", "recorder"),  # setRetentionPolicies (04 row 9)
        ("PUT", "/recording/symbols/s/pin", "recorder"),  # pinRecordedSymbol (04 row 9)
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


def test_no_path_gated_row_names_a_no_grace_class() -> None:
    """A no-grace grant binds the request its handler validated (#2304), which a path cannot
    name: the guard fails closed on such a class, so a row naming one nothing can pass."""
    path_gated = {action_class for _method, _pattern, action_class in DANGEROUS_ROUTES}
    assert path_gated & NO_GRACE_ACTION_CLASSES == set()


def test_restore_backup_is_handler_gated_because_its_grant_binds_one_request() -> None:
    """04 §7.2.2 row 52 (#2751): `backups` is no-grace, so only the handler that validated the
    restore can gate it (the guard of #2813 spent the grant before the body was validated)."""
    path = "/admin/backups/{backupId}/restore"
    assert DANGEROUS_PATH_PATTERN.match(path)
    assert dangerous_action_class("POST", _concrete(path)) is None
    assert ("POST", path, "backups") in HANDLER_GATED_ROUTES
    assert "backups" in NO_GRACE_ACTION_CLASSES and not _ungated("POST", path)


def test_recorder_purge_is_handler_gated_not_middleware_gated() -> None:
    """E16-T06 review (a): middleware step-up would pre-empt the handler's owner-only check."""
    assert dangerous_action_class("POST", "/admin/recorder/purge") is None
    assert ("POST", "/admin/recorder/purge", "recorder") in HANDLER_GATED_ROUTES
    assert not _ungated("POST", "/admin/recorder/purge")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/recording/symbols"),
        ("PATCH", "/recording/symbols/{recordedSymbolId}"),
        ("DELETE", "/recording/symbols/{recordedSymbolId}"),
    ],
)
def test_recorded_symbol_writes_are_handler_gated(method: str, path: str) -> None:
    """#2738 (04 §7.2.2 rows 8, 9, 9a): only the body or query tells whether an add, PATCH or
    DELETE changes retention or deletes data (`pinned`, `retention_days`, `purge_data=true`),
    so the handler gates that branch with `recorder` and the guard lets the rest through."""
    assert DANGEROUS_PATH_PATTERN.match(path)
    assert dangerous_action_class(method, _concrete(path)) is None
    assert (method, path, "recorder") in HANDLER_GATED_ROUTES
    assert (method, path) not in _NOT_DANGEROUS


@pytest.mark.parametrize("path", ["/admin/recorder/compact", "/admin/recorder/import"])
def test_recording_writes_without_step_up_are_swept_and_allow_listed(path: str) -> None:
    assert DANGEROUS_PATH_PATTERN.match(path)
    assert ("POST", path) in _NOT_DANGEROUS
    assert dangerous_action_class("POST", path) is None


#: Handler-gated rows whose handler is not mounted yet (#2738): declarations nothing enforces.
#: The E16-T08 (#492) PR that mounts one removes it here and adds the handler test proving its
#: body- or query-aware `recorder` branch, and that the rest of the route passes; the restore
#: ticket (`restoreBackup`) adds the test that its handler gates the request it validated.
_PENDING_HANDLER_GATES = {
    ("POST", "/admin/backups/{backupId}/restore"),
    ("POST", "/recording/symbols"),
    ("PATCH", "/recording/symbols/{recordedSymbolId}"),
    ("DELETE", "/recording/symbols/{recordedSymbolId}"),
}


def _mounted_pending(app: FastAPI) -> list[tuple[str, str]]:
    return sorted(_PENDING_HANDLER_GATES & served_operations(app))


def test_pending_handler_gates_are_registered_and_not_mounted() -> None:
    """A mounted pending row would count as gated with no check behind it (#2738 review)."""
    assert _PENDING_HANDLER_GATES <= {(m, p) for m, p, _ in HANDLER_GATED_ROUTES}
    assert _mounted_pending(create_app()) == []


def test_mounting_a_pending_handler_gate_is_caught() -> None:
    app = FastAPI()
    router = APIRouter(prefix="/recording")

    @router.delete("/symbols/{recordedSymbolId}")
    async def stand_in() -> None: ...

    app.include_router(router)
    assert _mounted_pending(app) == [("DELETE", "/recording/symbols/{recordedSymbolId}")]


#: Every recording and recorder write in `22-api-openapi.yaml` -> how it is gated (#2738).
_RECORDING_WRITES: dict[str, tuple[str, str | None]] = {
    "setRetentionPolicies": ("path", "recorder"),  # 04 §7.2.2 row 9
    "pinRecordedSymbol": ("path", "recorder"),  # row 9
    "updateRecordedSymbol": ("handler", "recorder"),  # row 9 for pin / retention, else row 8
    # Stopping a pinned symbol may need it too: an open E16-T08 decision (see `step_up.py`).
    "removeRecordedSymbol": ("handler", "recorder"),  # row 9a with purge_data=true, else row 8
    "purgeRecordedData": ("handler", "recorder"),  # row 9a, owner-only before step-up
    "addRecordedSymbol": ("handler", "recorder"),  # row 9 for pin / retention, else row 8
    "compactRecorder": ("allow-listed", None),  # row 51
    "importTradeArchive": ("allow-listed", None),  # row 51
}


@functools.cache
def _contract_writes() -> dict[str, tuple[str, str]]:
    """operationId -> (METHOD, path) for every write in the contract."""
    paths = cast(dict[str, dict[str, Any]], load_openapi_spec()["paths"])
    return {
        op["operationId"]: (method.upper(), path)
        for path, item in paths.items()
        for method, op in item.items()
        if method.upper() in _WRITE and isinstance(op, dict)
    }


def _gating(method: str, path: str) -> tuple[str, str | None]:
    if not DANGEROUS_PATH_PATTERN.match(path):
        return ("not swept", None)
    path_class = dangerous_action_class(method, _concrete(path))
    if path_class is not None:
        return ("path", path_class)
    for m, p, handler_class in HANDLER_GATED_ROUTES:
        if (m, p) == (method, path):
            return ("handler", handler_class)
    return ("allow-listed", None) if (method, path) in _NOT_DANGEROUS else ("ungated", None)


def test_every_contract_recording_write_is_swept_and_classified() -> None:
    """SR-025 (#2738): a recording or recorder write added to the contract fails here
    until it is path-gated, handler-gated or allow-listed with its 04 §7.2.2 row."""
    swept = {
        operation_id: _gating(method, path)
        for operation_id, (method, path) in _contract_writes().items()
        if re.match(r"^/(admin/)?record", path)
    }
    assert swept == _RECORDING_WRITES


def test_every_registered_route_names_a_known_action_class() -> None:
    """`require_elevation` refuses an unknown class, so a row naming one would lock its
    route for everyone instead of gating it (#2738 aligns to the `recorder` class)."""
    named = {c for *_, c in DANGEROUS_ROUTES} | {c for *_, c in HANDLER_GATED_ROUTES}
    assert named <= ACTION_CLASSES
