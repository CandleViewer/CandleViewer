"""#3990 (found by the #1026 DAST gate): every audit record an admin or users route writes carries
the id `CorrelationMiddleware` bound for that request, never one read from a request header.

The real `create_app()` of the E42-X03 world (`_world.py`), the elevation state `fresh`. Each cell's
requests are stamped with an `X-Correlation-Id` of the test's choosing, so what the middleware bound
is known without reading the response: a record whose `request_id` is NULL, or any other id, fails.

The route's own step-up records, the challenge (`auth.step_up_required`) and the grace use
(`auth.step_up_grace_used`), which B16's chart writes, are checked like any other; the stale state's
challenges are `test_audit_request_id_stale.py`'s. The step-up exchange's own records (`POST
/auth/step-up`, which the cells send without a stamped id) are not the route's. The cells'
presence and status expectations stay in `_cells.py`.
"""

from __future__ import annotations

import pytest

from tests.security.admin import _cells as cells
from tests.security.admin._world import AdminWorld

STATE = "fresh"
#: The named families, each one cell: (the route, the caller, the record its guard owes).
FAMILIES = {
    "admin area": ("GET /admin/overview", "viewer", "admin.area_entered"),
    "support bundle": ("POST /admin/support-bundle", "viewer", "health.diagnostics_exported"),
    "recorder": ("POST /admin/recorder/import", "viewer", "recorder.import"),
    "retention": ("POST /admin/recorder/purge", "viewer", "retention.purge"),
    "invites owner check": ("POST /users", "viewer", "rbac.denied"),
    "role change": ("PUT /users/{userId}/roles", "viewer", "rbac.denied"),
    "mfa reset preview": ("GET /users/{userId}/mfa/reset-preview", "viewer", "rbac.denied"),
}


def _unnamed(world: AdminWorld, op: cells.Op, actor: str, sent: list[str]) -> list[str]:
    """`action: request_id` of each record of the cell that does not carry a stamped id."""
    start = len(sent)
    seen = cells.observe(world, op, actor, STATE)
    stamped = set(sent[start:])
    return [
        f"{r['action']}: {r.get('request_id')}"
        for r in cells.route_records(seen.records)
        if str(r.get("request_id")) not in stamped
    ]


@pytest.mark.parametrize(
    ("op", "actor"),
    [
        pytest.param(op, a, id=f"{op.key}|{a}")
        for op in cells.ops_for(STATE)
        for a in cells.callers_for(op, STATE)
    ],
)
def test_every_record_of_the_request_carries_the_id_the_middleware_bound(
    world: AdminWorld, sent: list[str], op: cells.Op, actor: str
) -> None:
    assert _unnamed(world, op, actor, sent) == []


@pytest.mark.parametrize(("key", "actor", "action"), list(FAMILIES.values()), ids=list(FAMILIES))
def test_each_family_writes_its_guard_record_with_the_bound_id(
    world: AdminWorld, sent: list[str], key: str, actor: str, action: str
) -> None:
    op = next(o for o in cells.ALL_OPS if o.key == key)
    start = len(sent)
    seen = cells.observe(world, op, actor, STATE, cell=f"3990|{key}|{actor}")  # its own exchange
    written = [r for r in seen.records if r["action"] == action]
    assert written, f"{key} as {actor}: no {action} among {[r['action'] for r in seen.records]}"
    assert {str(r.get("request_id")) for r in written} <= set(sent[start:])
