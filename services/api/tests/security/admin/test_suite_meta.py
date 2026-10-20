"""E42-X03 (#1026): the admin RBAC suite maintains itself and fails when a control goes.

- Every admin or users route the app serves is classified: on `admin_router`, whose `admin_area`
  dependency names its permission, or listed in `_cells.OWN_GUARD` with the record its own guard
  writes. A new route in neither fails here, naming it, and its cells fail too.
- The permission an `admin_router` guard checks is the contract's `x-rbac` permission for each of
  its routes. Only the Owner holds `admin:*`, so the role matrix alone cannot tell `admin:read`
  from `admin:write`.
- The cells cover every executed admin and users row, the served `not_executable` rows are each
  in `PATH_GATED_ONLY` or `NO_CELL`, and the handler-gated cells reach their gate.
- Shown in memory: the suite fails against an unguarded admin route, against an admin route whose
  audit entry is missing, and against an `admin_router` guard whose permission drifts from the
  contract. Each change to the module-scoped world is undone, so the tests hold in any order.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from candleviewer.admin.http import admin_area
from candleviewer.api.step_up import HANDLER_GATED_ROUTES
from candleviewer.auth.generated_permissions import Permission
from tests.security.admin import _cells as cells
from tests.security.admin._world import AdminWorld

STATE = "none"
_ENTER = f"{admin_area.__qualname__}.<locals>.enter"
#: Declared in the contract and `not_mounted` in the matrix: a probe mounted here passes the
#: deny-by-default check as the owning ticket's route would (E43-S02's `getSecuritySummary`).
_PROBE = "GET /admin/security/summary"
#: The route whose guard the drift control edits, and the permission it is given instead.
_DRIFTED, _WRONG = "GET /admin/overview", Permission.ADMIN_WRITE


def _routes(routes: Any, prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    """Every (METHOD /path, route), as `deny_by_default.served_operations` walks them."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            ctx_prefix = getattr(getattr(route, "include_context", None), "prefix", "") or ""
            yield from _routes(inner.routes, prefix + ctx_prefix)
        elif isinstance(route, APIRoute):
            for method in sorted((route.methods or set()) - {"HEAD"}):
                yield f"{method} {prefix}{route.path}", route


def _guard(route: APIRoute) -> Any:
    """The route's `admin_area` dependency (its `enter` closure), or None if it has none."""
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        call = dep.call
        if call is not None and getattr(call, "__qualname__", "") == _ENTER:
            return call
        stack.extend(dep.dependencies)
    return None


def _guard_permission(route: APIRoute) -> str | None:
    """The permission the route's `admin_area` dependency checks, or None if it has none."""
    enter = _guard(route)
    if enter is None:
        return None
    permission = inspect.getclosurevars(enter).nonlocals["permission"]
    return str(getattr(permission, "value", permission))


def _served(app: FastAPI) -> dict[str, APIRoute]:
    return {key: route for key, route in _routes(app.routes) if cells.is_admin(key)}


def _unclassified(app: FastAPI) -> list[str]:
    served = _served(app)
    return sorted(
        k for k, r in served.items() if _guard_permission(r) is None and k not in cells.OWN_GUARD
    )


def _assert_guards_match_the_contract(world: AdminWorld) -> None:
    guarded = {
        key: permission
        for key, route in _served(world.app).items()
        if (permission := _guard_permission(route)) is not None
    }
    assert guarded, "no admin_router route found: the guard detection is broken"
    wrong: dict[str, tuple[str, list[str]]] = {}
    for key, permission in guarded.items():
        method, path = key.split(" ", 1)
        declared = world.spec["paths"][path][method.lower()]["x-rbac"]["permissions"]
        if [permission] != declared:
            wrong[key] = (permission, declared)
    assert not wrong, f"admin_router permission differs from the contract's x-rbac: {wrong}"


def test_every_admin_route_is_classified(world: AdminWorld) -> None:
    served = _served(world.app)
    assert not _unclassified(world.app), (
        "admin or users routes with no admin_router guard and no OWN_GUARD entry (put them on "
        f"admin_router, or list their own guard with its reason): {_unclassified(world.app)}"
    )
    stale = sorted(k for k in cells.OWN_GUARD if k not in served)
    assert not stale, f"OWN_GUARD entries for routes no longer served: {stale}"
    guarded = sorted(k for k in cells.OWN_GUARD if _guard_permission(served[k]) is not None)
    assert not guarded, f"OWN_GUARD entries now on admin_router, drop them: {guarded}"


def test_guard_permission_matches_the_contract(world: AdminWorld) -> None:
    _assert_guards_match_the_contract(world)


def test_the_cells_cover_every_served_admin_route(world: AdminWorld) -> None:
    rows = cells.matrix_rows()
    served = set(_served(world.app))
    executed = {k for k in served if rows[k]["state"] == "executed"}
    assert executed == {op.key for op in cells.OPS}
    parked = served - executed
    assert all(rows[k]["state"] == "not_executable" for k in parked), sorted(parked)
    assert parked == set(cells.PATH_GATED_ONLY) | set(cells.NO_CELL), (
        "a served not_executable row needs PATH_GATED_ONLY cells or a NO_CELL reason: "
        f"{sorted(parked ^ (set(cells.PATH_GATED_ONLY) | set(cells.NO_CELL)))}"
    )
    assert not set(cells.PATH_GATED_ONLY) & set(cells.NO_CELL)
    for op in cells.GATE_ONLY_OPS:  # their none and stale cells rest on the path guard alone
        assert op.gate is not None and op.gate.where == "path", op.key


def test_every_handler_gated_cell_has_its_class_and_its_request() -> None:
    gated = {op.key: op for op in cells.OPS if op.gate is not None and op.gate.where == "handler"}
    assert gated, "no handler-gated route among the cells"
    for key, op in gated.items():
        classes = {c for m, p, c in HANDLER_GATED_ROUTES if f"{m} {p}" == key}
        assert len(classes) == 1 or key in cells.GATE_CLASS, f"{key}: name its cell's class"
        assert op.gate is not None and op.gate.action_class in classes, key
    assert set(cells.GATE_REQUESTS) <= set(gated), "a gate request for a route that is not gated"
    assert set(cells.BEFORE_GATE) <= set(gated), "a BEFORE_GATE row for a route that is not gated"


@pytest.fixture
def probe(world: AdminWorld) -> Iterator[cells.Op]:
    """`_PROBE` mounted on a plain router with no guard, as a ticket might forget to guard it.
    The app router's routes and lifespan are restored by identity afterwards (CR-1)."""
    app_router = world.app.router
    routes, lifespan = list(app_router.routes), app_router.lifespan_context
    router = APIRouter(prefix="/admin")

    @router.get("/security/summary")
    async def summary() -> dict[str, str]:
        return {"state": "leaked"}

    world.app.include_router(router)
    try:
        yield cells._op(_PROBE, cells.matrix_rows()[_PROBE])
    finally:
        app_router.routes[:] = routes
        app_router.lifespan_context = lifespan
    assert _PROBE not in _served(world.app), "the probe is still mounted"


def test_an_unguarded_admin_route_fails_the_suite(world: AdminWorld, probe: cells.Op) -> None:
    assert _unclassified(world.app) == [_PROBE]  # the classification names it
    for actor in ("manager_with_grant", "viewer"):
        cell = f"meta|probe|{actor}"
        with pytest.raises(AssertionError, match="expected a 403 denial"):
            cells.assert_status(world, probe, actor, STATE, cell=cell)
        with pytest.raises(AssertionError, match=r"admin\.area_entered"):
            cells.assert_records(world, probe, actor, STATE, cell=cell)
        assert world.observed[cell].status == 200  # what the missing guard let through


def test_a_missing_audit_entry_fails_the_suite(
    world: AdminWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    [op] = [o for o in cells.OPS if o.key == "GET /admin/overview"]
    cells.assert_records(world, op, "viewer", STATE, cell="meta|control")  # the guard records it
    real = world.audit.emit

    async def drop_area_entered(action: str, **kw: Any) -> None:
        if action != "admin.area_entered":
            await real(action, **kw)

    monkeypatch.setattr(world.audit, "emit", drop_area_entered)
    cells.assert_status(world, op, "viewer", STATE, cell="meta|silent")  # still refused
    with pytest.raises(AssertionError, match=re.escape("no [Record(action='admin.area_entered'")):
        cells.assert_records(world, op, "viewer", STATE, cell="meta|silent")


def test_a_guard_permission_that_drifts_from_the_contract_fails_the_suite(
    world: AdminWorld,
) -> None:
    enter = _guard(_served(world.app)[_DRIFTED])
    assert enter is not None
    cell = enter.__closure__[enter.__code__.co_freevars.index("permission")]
    kept = cell.cell_contents
    assert kept != _WRONG
    cell.cell_contents = _WRONG  # the guard now checks another permission than the contract's
    try:
        with pytest.raises(AssertionError, match=re.escape(_DRIFTED)):
            _assert_guards_match_the_contract(world)
    finally:
        cell.cell_contents = kept
    _assert_guards_match_the_contract(world)  # and holds again once restored
