"""Deny-by-default for step-up gating (E09-S04 review finding): every mounted
write route whose path looks dangerous (users, keys, live enablement,
kill-switch, risk override, audit, backups, recorded-data retention and purge,
feature flags) must be registered in `DANGEROUS_ROUTES` or `HANDLER_GATED_ROUTES`,
so a later ticket cannot mount one ungated.

#3083 (AD-F01): the path pattern alone missed the flag write and, being a write
sweep, every GET. The contract sweep below derives its candidates from the contract
for every method: an operation needing a permission `auth/rbac_seed.json` seeds
`dangerous`, or one whose contract text names a step-up."""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute, Host, Mount
from starlette.types import Receive, Scope, Send

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.rbac_conformance import RBAC_SEED_PATH
from candleviewer.api.step_up import (
    DANGEROUS_PATH_PATTERN,
    DANGEROUS_ROUTES,
    HANDLER_GATED_ROUTES,
    dangerous_action_class,
)
from candleviewer.app import create_app
from candleviewer.auth.step_up import ACTION_CLASSES, NO_GRACE_ACTION_CLASSES

_WRITE = {"POST", "PUT", "PATCH", "DELETE"}
#: Operations a sweep below flags that are deliberately not step-up gated -> why (#3083: the
#: reason is data, so no entry is without one). A contract operation listed here must not name
#: a step-up class in its text (`test_allow_listed_operations_name_no_step_up_class`).
_NOT_DANGEROUS: dict[tuple[str, str], str] = {
    ("POST", "/exchange-accounts/{accountId}/keys/{keyId}/test"): "testApiKey: read-only probe",
    ("POST", "/admin/audit/verify"): "verifyAuditChain: `audit:read`, no step-up (04 row 49a)",
    # 04 row 52 gates restore and delete only (`restoreBackup`, `deleteBackup`).
    ("POST", "/admin/backups"): "createBackup: triggers a backup run",
    ("POST", "/admin/backups/{backupId}/verify"): "verifyBackup: restores into a scratch namespace",
    # #2738: `recording:write` without step-up for Owner and Manager (04 §7.2.2 row 51); neither
    # changes retention or deletes recorded data (addRecordedSymbol can: it is handler-gated).
    ("POST", "/admin/recorder/compact"): "compactRecorder: merges cold-tier files (04 row 51)",
    ("POST", "/admin/recorder/import"): "importTradeArchive: adds archive trades (04 row 51)",
    # #3083: mounted operations the contract sweep flags that nothing step-up gates.
    ("GET", "/auth/session"): "authGetSession: reads the session's own `step_up_expires_at`",
    ("GET", "/me"): "getMe: reads the session's own `elevated_until`",
    ("GET", "/users/invites"): "listPendingInvites: a read; the invite writes are gated (`users`)",
    ("GET", "/users/{userId}/mfa/reset-preview"): "previewMfaReset: a read; the reset is gated",
    ("PUT", "/admin/capacity/subaccount-tier"): "setSubaccountTier: the contract says No step-up",
    # #3085 (D1): ending one's own view-as only lowers capability, so it never needs a step-up.
    ("DELETE", "/auth/session/view-as"): "endViewAs: the contract says no step-up",
    # 04 row 22 (own rules, no step-up). Rows 26 (raising an action budget, loosening a stop) and
    # 27 (import) mark step-up, but the contract documents none for `updateRule` or `createRule`:
    # `Problem.action_summary` says `rules:write` changes a rule without one and hands the rule
    # questions that raises to the route slice of #2304. That slice settles rows 26 and 27; its PR
    # deletes each rule row below that it gates and makes this note cite 04 for any it keeps.
    ("POST", "/rules"): "createRule: stored `disabled`; arming is `setRuleMode`, gated",
    ("PUT", "/rules/{ruleId}"): "updateRule: the contract (`Problem`) says no step-up",
    ("DELETE", "/rules/{ruleId}"): "deleteRule: refused while the rule is `armed`",
    ("PUT", "/rules/{ruleId}/active-version"): "setActiveRuleVersion: `Problem` says no step-up",
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


# -- #3083 (AD-F01): the contract sweep, every method -------------------------------------------

_STEP_UP_TEXT = re.compile(r"step[-_ ]up", re.IGNORECASE)
#: `authStepUp` answers the challenges; it names every no-grace class and can never need a
#: step-up itself (`_WRITE_EXEMPT_PATHS` in `api/step_up.py`).
_ELEVATION = ("POST", "/auth/step-up")
#: The OpenAPI path-item fields that are operations. The others (`parameters`, `servers`,
#: `summary`, `description`, `$ref` and `x-` extensions) are not, whatever their type.
_HTTP_METHODS = frozenset({"get", "put", "post", "patch", "delete", "head", "options", "trace"})


def _operations(spec: Mapping[str, object]) -> dict[tuple[str, str], dict[str, Any]]:
    """(METHOD, path) -> operation, for every operation in `spec`."""
    paths = cast(dict[str, dict[str, Any]], spec["paths"])
    return {
        (method.upper(), path): op
        for path, item in paths.items()
        for method, op in item.items()
        if method in _HTTP_METHODS
    }


@functools.cache
def _contract_operations() -> dict[tuple[str, str], dict[str, Any]]:
    """(METHOD, path) -> operation, for every operation in the contract."""
    return _operations(load_openapi_spec())


def _operation(operation_id: str) -> tuple[tuple[str, str], dict[str, Any]]:
    (found,) = [
        (k, op) for k, op in _contract_operations().items() if op["operationId"] == operation_id
    ]
    return found


@functools.cache
def _contract_classes() -> frozenset[str]:
    """The `action_class` enum of `POST /auth/step-up`."""
    _, op = _operation("authStepUp")
    schema = op["requestBody"]["content"]["application/json"]["schema"]
    return frozenset(schema["properties"]["action_class"]["enum"])


@functools.cache
def _dangerous_permissions() -> frozenset[str]:
    seed = json.loads(RBAC_SEED_PATH.read_text(encoding="utf-8"))
    return frozenset(p["code"] for p in seed["permissions"] if p["dangerous"])


def _text(op: dict[str, Any]) -> str:
    return f"{op.get('summary', '')}\n{op.get('description', '')}"


def _documented_classes(op: dict[str, Any]) -> frozenset[str]:
    """The step-up classes an operation's contract text names, when that text names a step-up."""
    text = _text(op)
    if not _STEP_UP_TEXT.search(text):
        return frozenset()
    return frozenset(c for c in _contract_classes() if f"`{c}`" in text)


@functools.cache
def _step_up_candidates() -> frozenset[tuple[str, str]]:
    """Every contract operation, whatever its method, that needs a permission the seed marks
    `dangerous` or whose text names a step-up."""
    dangerous = _dangerous_permissions()
    return frozenset(
        key
        for key, op in _contract_operations().items()
        if key != _ELEVATION
        and (set(op["x-rbac"]["permissions"]) & dangerous or _STEP_UP_TEXT.search(_text(op)))
    )


def _registered_classes(method: str, path: str) -> frozenset[str]:
    """The classes the registry gates an operation with: its path row and its handler rows."""
    path_class = dangerous_action_class(method, _concrete(path))
    handler = {c for m, p, c in HANDLER_GATED_ROUTES if (m, p) == (method, path)}
    return frozenset(handler if path_class is None else handler | {path_class})


def _step_up_findings(app: FastAPI) -> list[tuple[str, str, str]]:
    """Mounted candidates the registry does not prove gated, whatever their method: `ungated`
    (no registry row, not allow-listed) or `pending` (a handler gate declared for a handler
    that is not written yet, so nothing enforces it)."""
    found: list[tuple[str, str, str]] = []
    for method, path in sorted(served_operations(app) & _step_up_candidates()):
        if not _registered_classes(method, path):
            if (method, path) not in _NOT_DANGEROUS:
                found.append((method, path, "ungated"))
        elif (method, path) in _PENDING_HANDLER_GATES:
            found.append((method, path, "pending"))
    return found


def test_every_mounted_step_up_operation_is_gated_or_allow_listed() -> None:
    assert _step_up_findings(create_app()) == []


async def _stand_in() -> None:
    """A handler with no step-up gate."""


@pytest.mark.parametrize(
    ("method", "prefix", "route"),
    [
        ("PUT", "/admin/feature-flags", "/{flagKey}"),  # setFeatureFlag
        ("GET", "/admin/audit", "/exports/{jobId}"),  # downloadAuditExport: a GET
    ],
)
def test_mounting_a_step_up_operation_without_its_gate_is_caught(
    method: str, prefix: str, route: str
) -> None:
    """On `main` neither was registered and the write-only path sweep saw neither (#3083)."""
    app = create_app()
    router = APIRouter(prefix=prefix)
    router.add_api_route(route, _stand_in, methods=[method])
    app.include_router(router)
    assert _step_up_findings(app) == [(method, prefix + route, "pending")]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/me"),  # a read: the write-only path sweep #3083 replaced never saw one
        ("PUT", "/admin/capacity/subaccount-tier"),
    ],
)
def test_a_mounted_candidate_in_no_registry_and_no_allow_list_is_reported_ungated(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    """The `ungated` branch's self-test (#3083 review): without its allow-list row, a mounted
    candidate that no registry row gates is reported, whatever its method."""
    monkeypatch.delitem(_NOT_DANGEROUS, (method, path))
    assert _step_up_findings(create_app()) == [(method, path, "ungated")]


def test_the_contract_sweep_covers_reads() -> None:
    """A GET needing a dangerous permission is a candidate like any write."""
    candidates = _step_up_candidates()
    assert ("GET", "/admin/audit/exports/{jobId}") in candidates  # `audit:export`
    assert ("GET", "/users/{userId}/mfa/reset-preview") in candidates  # `users:write`
    assert _ELEVATION not in candidates


def test_a_path_level_extension_object_is_not_read_as_an_operation() -> None:
    """Only the method fields of a path item are operations (#3083 review): read as one, an
    `x-` extension object would fail the sweep with a KeyError on `x-rbac` or `operationId`."""
    get = {"operationId": "getThing", "x-rbac": {"permissions": ["flags:read"]}}
    item = {"summary": "s", "parameters": [], "x-cv-owner": {"lane": "auth-rbac"}, "get": get}
    assert _operations({"paths": {"/thing": item}}) == {("GET", "/thing"): get}


@pytest.mark.parametrize(
    ("operation_id", "classes"),
    [
        # Under the row lock, by key and stored value: releasing a kill-switch-class flag needs
        # `killswitch`, `trading.live_enabled: true` needs `live_enablement`, any other write
        # `flags` (22-api-openapi.yaml, `setFeatureFlag` write rules).
        ("setFeatureFlag", {"flags", "killswitch", "live_enablement"}),
        # Checked by the operation itself, after the requester check (`exportAuditLog`, Download).
        ("downloadAuditExport", {"audit"}),
    ],
)
def test_ad_f01_operations_are_handler_gated_with_their_documented_classes(
    operation_id: str, classes: set[str]
) -> None:
    (method, path), op = _operation(operation_id)
    assert _documented_classes(op) == classes
    assert dangerous_action_class(method, _concrete(path)) is None  # the guard must not pre-empt
    assert _registered_classes(method, path) == classes
    assert (method, path) in _PENDING_HANDLER_GATES


def test_every_contract_flag_write_is_registered() -> None:
    """Any operation needing `flags:write` - today `setFeatureFlag` only - is step-up gated."""
    flag_writes = [
        key
        for key, op in _contract_operations().items()
        if "flags:write" in op["x-rbac"]["permissions"]
    ]
    assert flag_writes
    assert all(_registered_classes(*key) for key in flag_writes)


def test_registered_classes_are_the_documented_classes() -> None:
    """A registered operation is gated with exactly the classes its contract text names or, where
    that text names a step-up and no class, the class pinned by hand (#3210)."""
    drift = {
        op["operationId"]: (sorted(registered), sorted(documented))
        for key, op in _contract_operations().items()
        if (registered := _registered_classes(*key))
        and (documented := _documented_or_pinned_classes(op))
        and registered != documented
    }
    assert drift == {}


def test_allow_listed_operations_name_no_step_up_class() -> None:
    """Every allow-list entry has a reason, is a contract operation in no registry, and is not
    one the contract says needs a step-up class."""
    operations = _contract_operations()
    for (method, path), reason in _NOT_DANGEROUS.items():
        assert reason.strip(), (method, path)
        assert (method, path) in operations, (method, path)
        assert not _registered_classes(method, path), (method, path)
        assert not _documented_classes(operations[method, path]), (method, path)


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
        # #3083: the flag prefix is swept too, not only the one write the contract has.
        ("DELETE", "/admin/feature-flags/{flagKey}"),
        ("POST", "/admin/feature-flags/{flagKey}/overrides"),
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
#: #3083: likewise the E42-T03 (#964) PR for the flag write (the class each branch demands,
#: decided under the row lock) and the E42-T02 (#889) PR for the export download (`audit`,
#: after the requester check).
_PENDING_HANDLER_GATES = {
    ("POST", "/admin/backups/{backupId}/restore"),
    ("POST", "/recording/symbols"),
    ("PATCH", "/recording/symbols/{recordedSymbolId}"),
    ("DELETE", "/recording/symbols/{recordedSymbolId}"),
    ("PUT", "/admin/feature-flags/{flagKey}"),
    ("GET", "/admin/audit/exports/{jobId}"),
    ("POST", "/admin/view-as"),  # #3085: its server slice mounts it and drops this row
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


# -- #3210: the operations whose contract text names a step-up and no class ----------------------

#: Operations whose text names a step-up but backticks no class of the `authStepUp` enum, so
#: `_documented_classes` reads nothing from them -> why they name none. Such an operation passes
#: the sweep above unread: `test_every_operation_the_parser_cannot_read_is_classified` fails until
#: a new one is listed here, and when a listed one leaves the contract or starts to name a class.
_UNPARSED_STEP_UP_TEXT: dict[str, str] = {
    # Reads of the caller's own state: they report a step-up deadline and demand none.
    "authGetSession": "reads the session's own `step_up_expires_at`; demands no step-up",
    "getMe": "reads the session's own `elevated_until`, the step-up grace expiry; demands none",
    # A read of another user's sessions: only revoking one is gated (`users`, 04 row 40a).
    "listUserSessions": "a read: the contract says listing needs no step-up (04 row 40a)",
    # The lock lift is no elevation: it takes the password only and restores no grant.
    "authUnlock": "lifts the idle lock with the password only; restores no step-up (#2290)",
    # The contract rules a step-up out in so many words.
    "setSubaccountTier": "the contract says No step-up: `admin:write` is no SR-025 action class",
    # Gated, but the text demands the step-up and names no class: each class is pinned below.
    "overrideRiskLockout": "owner-only and step-up-gated (04 row 34)",
    "setSessionEnvironment": "switching to `live` needs an elevation (04 row 11)",
}

#: The listed operations the registry gates, each with its class pinned by hand -> the contract
#: line that demands the step-up. `_documented_or_pinned_classes` reads the pin, so
#: `test_registered_classes_are_the_documented_classes` checks the registry against it, and
#: `test_a_pinned_contract_line_is_in_the_operations_text` fails when the contract rewords the
#: line, so the pin is read again against the new wording.
_PINNED_STEP_UP_CLASSES: dict[str, tuple[str, str]] = {
    # 04 §7.2.2 row 34 (Owner, step-up): the registry gates the route with `risk_caps`.
    "overrideRiskLockout": ("risk_caps", "an owner-only, step-up-gated, always-audited action"),
    # 04 §7.2.2 row 11 (step-up to enable live): the registry gates the switch to `live` with the
    # no-grace `live_enablement`.
    "setSessionEnvironment": ("live_enablement", "requires an elevated session (`/auth/step-up`)"),
}

_Operations = Mapping[tuple[str, str], dict[str, Any]]


def _squash(text: str) -> str:
    """`text` with each run of whitespace as one space, as a folded contract block reads."""
    return " ".join(text.split())


def _documented_or_pinned_classes(op: dict[str, Any]) -> frozenset[str]:
    """The classes the contract documents for an operation: the ones its text names or, where
    that text names a step-up and no class, the one pinned by hand."""
    documented = _documented_classes(op)
    pinned = _PINNED_STEP_UP_CLASSES.get(op["operationId"])
    if documented or pinned is None:
        return documented
    return frozenset({pinned[0]})


def _unparsed_step_up_operations(operations: _Operations) -> frozenset[str]:
    """The operationIds of the operations whose text names a step-up and no class."""
    return frozenset(
        op["operationId"]
        for op in operations.values()
        if _STEP_UP_TEXT.search(_text(op)) and not _documented_classes(op)
    )


def _classification_drift(
    operations: _Operations, classification: Mapping[str, str]
) -> dict[str, list[str]]:
    """The unparsed operations `classification` lacks, and its entries for operations that are no
    longer unparsed: gone from the contract, or its text now names a class."""
    unparsed = _unparsed_step_up_operations(operations)
    classified = set(classification)
    return {"unclassified": sorted(unparsed - classified), "stale": sorted(classified - unparsed)}


def test_every_operation_the_parser_cannot_read_is_classified() -> None:
    """#3210: an operation whose text names a step-up and no class would pass the sweep unread.
    A new one fails here until `_UNPARSED_STEP_UP_TEXT` gives its reason (and
    `_PINNED_STEP_UP_CLASSES` its class, if the registry gates it); a listed one that leaves the
    contract, or whose text now names a class, fails until its entries are dropped."""
    drift = _classification_drift(_contract_operations(), _UNPARSED_STEP_UP_TEXT)
    assert drift == {"unclassified": [], "stale": []}


#: Synthetic operations for the self-tests below: `unread` names a step-up and no class, `named`
#: its class, `field` a step-up only in a field name, `silent` neither.
_SYNTHETIC: _Operations = {
    ("GET", "/unread"): {"operationId": "unread", "description": "Needs a step-up."},
    ("GET", "/named"): {"operationId": "named", "description": "Needs a step-up: `users`."},
    ("GET", "/field"): {"operationId": "field", "summary": "Reports step_up_expires_at."},
    ("GET", "/silent"): {"operationId": "silent", "description": "Needs `users` access."},
}


def test_unparsed_operations_are_those_that_name_a_step_up_and_no_class() -> None:
    assert _unparsed_step_up_operations(_SYNTHETIC) == {"unread", "field"}


def test_an_unparsed_operation_with_no_entry_is_reported_unclassified() -> None:
    """Stands for an operation added to the contract with no entry (#3210)."""
    drift = _classification_drift(_SYNTHETIC, {"field": "reason"})
    assert drift == {"unclassified": ["unread"], "stale": []}


def test_an_entry_for_an_operation_gone_or_now_naming_its_class_is_reported_stale() -> None:
    """`gone` is not in the contract; the text of `named` backticks its class, so the parse reads
    it and its entry (and pin) must go (#3210)."""
    classification = dict.fromkeys(["unread", "field", "named", "gone"], "reason")
    drift = _classification_drift(_SYNTHETIC, classification)
    assert drift == {"unclassified": [], "stale": ["gone", "named"]}


def test_every_classified_operation_has_a_reason() -> None:
    assert [op for op, reason in _UNPARSED_STEP_UP_TEXT.items() if not reason.strip()] == []


def test_registered_unparsed_operations_are_exactly_the_pinned_ones() -> None:
    """The cross-check against the registry reads a documented class, so a registered operation
    with none would pass it unread (#3210): one the registry gates needs its class pinned, and a
    pin needs an operation the registry gates."""
    registered = {
        op["operationId"]
        for key, op in _contract_operations().items()
        if op["operationId"] in _UNPARSED_STEP_UP_TEXT and _registered_classes(*key)
    }
    assert registered == set(_PINNED_STEP_UP_CLASSES)


@pytest.mark.parametrize("operation_id", sorted(_PINNED_STEP_UP_CLASSES))
def test_a_pinned_class_is_the_class_the_registry_gates_the_operation_with(
    operation_id: str,
) -> None:
    key, op = _operation(operation_id)
    action_class, _line = _PINNED_STEP_UP_CLASSES[operation_id]
    assert _documented_or_pinned_classes(op) == {action_class}
    assert _registered_classes(*key) == {action_class}


@pytest.mark.parametrize("operation_id", sorted(_PINNED_STEP_UP_CLASSES))
def test_a_pinned_contract_line_is_in_the_operations_text(operation_id: str) -> None:
    _, op = _operation(operation_id)
    _action_class, line = _PINNED_STEP_UP_CLASSES[operation_id]
    assert line in _squash(_text(op))
