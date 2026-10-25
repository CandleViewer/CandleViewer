"""#902 (E27-X03): `authz_denied_by_route_total{permission, route, role}`, and the per-call cost
of scope resolution (`-m perf -s` prints it): in memory, never a database walk."""

from __future__ import annotations

import contextlib
import time
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from candleviewer.accounts.key_import import Importer
from candleviewer.api.exchange_accounts import _not_owner as accounts_not_owner
from candleviewer.api.exchange_keys import _not_owner as keys_not_owner
from candleviewer.api.profiles import not_owner as profiles_not_owner
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import count_authz_denial
from candleviewer.auth.scopes import AccountGrant, ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.auth.view_as import ViewAsPhase, ViewAsRequestContext, bound_view_as
from candleviewer.observability.authz_denials import METRIC_NAME, AuthzDenialMiddleware
from candleviewer.observability.metrics import Metrics

TEMPLATE = "/v1/accounts/{accountId}"
ROUTED = {"type": "http", "method": "GET", "route": SimpleNamespace(path=TEMPLATE)}
MANAGER, OWNER = frozenset({"manager", "viewer"}), frozenset({"owner"})
AUDIT_DOWN = SimpleNamespace(emit=AsyncMock(side_effect=RuntimeError("audit store down")))


async def _run(
    scope: dict[str, Any], *principals: frozenset[str], cap: int = 1000, fail: bool = False
) -> Metrics:
    """One request or connection: `enforce(orders:write)` once per principal; owner is allowed."""
    m = Metrics("demo")
    counter = m.counter(METRIC_NAME, "t", ("permission", "route", "role"), max_series=cap)

    async def app(*_: Any) -> None:
        for roles in principals:
            perms = frozenset(Permission) if roles == OWNER else frozenset()
            with contextlib.suppress(ForbiddenError, RuntimeError):  # every audit write fails
                await enforce(PrincipalSnapshot(uuid.uuid4(), roles, perms),
                              Permission.ORDERS_WRITE, emitter=AUDIT_DOWN)  # fmt: skip
        if fail:
            raise KeyError("downstream")

    with contextlib.suppress(KeyError):  # `fail`: the app raises after the denial
        await AuthzDenialMiddleware(app, counter=counter)(scope, None, None)
    return m


def _get(m: Metrics, route: str, role: str) -> float:
    labels = {"env": "demo", "permission": "orders:write", "route": route, "role": role}
    return m.registry.get_sample_value(METRIC_NAME, labels) or 0.0


async def test_a_denied_request_counts_once_by_template_and_an_allowed_one_not_at_all() -> None:
    m = await _run(ROUTED, OWNER, MANAGER, MANAGER)  # the audit writes failing changes nothing
    assert _get(m, TEMPLATE, "manager") == 1.0 and m.get(METRIC_NAME).series_count == 1


async def test_unmatched_ws_role_clamping_and_view_as() -> None:
    assert _get(await _run({"type": "http"}, MANAGER, MANAGER), "unmatched", "manager") == 1.0
    assert _get(await _run({"type": "websocket"}, MANAGER, MANAGER), "ws", "manager") == 2.0
    assert _get(await _run({"type": "websocket"}, frozenset()), "ws", "other") == 1.0
    target = uuid.uuid4()  # under view-as, the viewer's role: an Owner
    with bound_view_as(ViewAsRequestContext(
        viewer_user_id=uuid.uuid4(), viewer_session_id=uuid.uuid4(), viewer_label="o",
        target_user_id=target, context_id=uuid.uuid4(), subject_user_id=target,
        phase=ViewAsPhase.LIVE,
    )):  # fmt: skip
        assert _get(await _run(ROUTED, MANAGER), TEMPLATE, "owner") == 1.0


async def test_a_downstream_exception_is_still_counted_and_lifespan_passes_through() -> None:
    assert _get(await _run(ROUTED, MANAGER, fail=True), TEMPLATE, "manager") == 1.0
    assert _get(await _run({"type": "lifespan"}, MANAGER), TEMPLATE, "manager") == 0.0


_SITES = ("admin", "orders", "view_as", "accounts", "keys", "profiles")


@pytest.mark.parametrize("site", _SITES)
async def test_every_denial_site_counts_the_actors_role_and_route(site: str) -> None:
    """The real refusal helpers for accounts, keys and profiles; the rest (a closure, a
    dependency, a 40-line guard) through `count_authz_denial` with the arguments the site passes."""
    req: Any = SimpleNamespace(scope={"type": "http"})
    uid, perm = uuid.uuid4(), Permission.KEYS_READ
    snap = PrincipalSnapshot(uid, MANAGER, frozenset())
    audit: Any = AUDIT_DOWN
    calls: dict[str, Any] = {
        "admin": lambda: count_authz_denial(perm, ()),  # the admin principal has no roles
        "orders": lambda: count_authz_denial(perm, snap.roles),
        "view_as": lambda: count_authz_denial(perm, ("owner",), route="/v1/x"),
        "accounts": lambda: accounts_not_owner(audit, snap, perm, Scope.GRANTED_ACCOUNTS, req),
        "keys": lambda: keys_not_owner(audit, Importer(uid, ",".join(sorted(MANAGER))), uid),
        "profiles": lambda: profiles_not_owner(
            audit, snap, uid, permission=perm, ip=None, request_id=None
        ),
    }
    route, role = {"admin": (TEMPLATE, "other"), "view_as": ("/v1/x", "owner")}.get(
        site, (TEMPLATE, "manager")
    )
    m = Metrics("demo")
    counter = m.counter(METRIC_NAME, "t", ("permission", "route", "role"), max_series=1000)

    async def app(*_: Any) -> None:
        result = calls[site]()
        if result is not None:
            await result

    await AuthzDenialMiddleware(app, counter=counter)(ROUTED, None, None)
    labels = {"env": "demo", "permission": "keys:read", "route": route, "role": role}
    assert m.registry.get_sample_value(METRIC_NAME, labels) == 1.0


async def test_past_the_cap_the_increment_is_dropped_without_error() -> None:
    m = await _run({"type": "websocket"}, MANAGER, frozenset(), cap=1)  # a second series
    breaches = {"env": "demo", "metric": METRIC_NAME}
    assert m.registry.get_sample_value("metric_cardinality_breach_total", breaches) == 1.0
    assert _get(m, "ws", "manager") == 1.0 and m.get(METRIC_NAME).series_count == 1


@pytest.mark.perf
async def test_scope_resolution_per_call_stays_in_memory() -> None:
    grants = tuple(AccountGrant(uuid.uuid4(), True, True, False) for _ in range(20))
    manager = PrincipalSnapshot(uuid.uuid4(), MANAGER, frozenset(Permission), grants)
    acc, store = grants[-1].exchange_account_id, AsyncMock()  # an allowed call never audits
    best = float("inf")
    for _ in range(7):  # best of 7 x 2000; the account asked for is the last of 20 grants
        start = time.perf_counter_ns()
        for _ in range(2_000):
            await enforce(manager, Permission.ORDERS_WRITE, scope=Scope.GRANTED_ACCOUNTS,
                          exchange_account_id=acc, requires_trade=True, emitter=store)  # fmt: skip
        best = min(best, (time.perf_counter_ns() - start) / 2_000)
    print(f"\nscope resolution (enforce + decide) per call: {best:.0f} ns")
    assert best < 50_000 and not store.mock_calls  # one Postgres round trip: ~100 us or more
