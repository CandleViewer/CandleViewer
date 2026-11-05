"""E29-Q02 (#1147, C2): what the E29 request-direction sweep and Schemathesis module share: 22's
operations as they split a request, and the E29 routers on the fakes of their own unit tests.

`create_app()` composes these routes with no OMS on its fake backend (`oms_runtime` and `oms_reads`
are `None` there), so each answers `501` or `503` to a valid request (a position write refuses an
invalid body first: `closeAllPositions` parses it at `position_close.py:681`, before `runtime()` at
`:697`): the routes are driven as their own tests drive them, one app per group of operations, each
the real router over the doubles of its unit tests (the exits' scripted facade, the read world's
in-memory store, the position worlds' pipelines). `build` reaches into those doubles (`_Endless`,
`world.principals`, `rig.Risk`): a change to one fails the valid-sample tests, loudly. The session
is the hooks' (`supply`): the Owner's bearer,
the SR-041 token a write declares, the arm token a live order takes and a fresh `Idempotency-Key`.
No operation of 22 takes a step-up but `setPositionTpSl` (`sl_loosen`), which no router serves.
A support module (no `test_` prefix): pytest collects nothing from it.
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, SupportsIndex

import pytest
from fastapi import FastAPI

from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.api.recording_writes import WriteLimiter
from candleviewer.oms.ports import InterimRiskGate
from tests.contract import test_order_exits_contract as exits_contract
from tests.contract._generated_contract import SPEC
from tests.unit.api import oms_reads_world as reads_world
from tests.unit.api import position_writes_world as position_world
from tests.unit.api import test_order_amend_route as amend_route
from tests.unit.api import test_order_cancel_all_route as cancel_all_route
from tests.unit.api import test_order_exits_route as exits_route
from tests.unit.api import test_orders_route as orders_route
from tests.unit.api import test_position_leverage_route as leverage_route
from tests.unit.oms import submit_rig as rig

#: The group of each operation of 22 that a router serves here; `setPositionTpSl` has none.
GROUP_OF: Final = {
    **dict.fromkeys(
        ("listOrders", "getOrder", "getOrderDiagnostics", "listPositions", "getPosition",
         "listExecutions", "listClosedPnl"), "reads",
    ),
    "placeOrder": "place",
    "amendOrder": "amend",
    "cancelOrder": "cancel",
    "cancelAllOrders": "cancel_all",
    **dict.fromkeys(("closePosition", "reversePosition", "closeAllPositions"), "positions"),
    "setPositionLeverage": "leverage",
}  # fmt: skip
OWNER: Final = "owner"  # the bearer of the Owner's session, the one session every world knows
CSRF: Final = "csrf"  # the world has no CSRF guard (the composed app's middleware): any token
ARM: Final = "armed"  # the token the worlds' arm records pass on a live account
_UNLIMITED: Final = 10**6  # writes a minute: the fuzz outruns the worlds' limits (429 is C1's)
_NOW: Final = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
_KEYS: Final = itertools.count(1)
#: C1's walk of the members of an answer that its schema leaves undeclared (E29-TC-650).
undeclared: Final = exits_contract._undeclared


def inline(node: Any) -> Any:
    """`node` with every component `$ref` inlined and its `examples` kept (`deref` drops them)."""
    if isinstance(node, dict):
        if "$ref" in node:
            kind, name = node["$ref"].split("/")[-2:]
            return inline(SPEC["components"][kind][name])
        return {key: inline(value) for key, value in node.items()}
    return [inline(value) for value in node] if isinstance(node, list) else node


def operation(operation_id: str) -> tuple[str, str, dict[str, Any]]:
    """The path, upper-case method and operation of `operation_id` in 22, its parameters those
    of its path item too."""
    for path, item in SPEC["paths"].items():
        for method, op in item.items():
            if isinstance(op, dict) and op.get("operationId") == operation_id:
                held = [*item.get("parameters", []), *op.get("parameters", [])]
                return path, method.upper(), {**op, "parameters": held}
    raise LookupError(f"22 has no operation {operation_id}")


def parameters(operation_id: str) -> list[dict[str, Any]]:
    """The parameters of `operation_id` in 22, each with its schema inlined."""
    return [inline(param) for param in operation(operation_id)[2]["parameters"]]


def fresh_key() -> str:
    """An `Idempotency-Key` no other request of the process sent: a repeat under another body is
    the hand-built modules' case (409), but for the sweep's pin of F1 (`closeAllPositions`)."""
    return str(uuid.UUID(int=next(_KEYS)))


def tokens(declared: Collection[str]) -> dict[str, str]:
    """The SR-041 and arm tokens a request declaring the headers `declared` carries."""
    held = {"X-CSRF-Token": CSRF, "X-Arm-Token": ARM}
    return {name: value for name, value in held.items() if name in declared}


def supply(declared: Collection[str]) -> dict[str, str]:
    """The session hooks: the headers a request declaring `declared` carries."""
    held = {"Authorization": f"Bearer {OWNER}", **tokens(declared)}
    return held | ({"Idempotency-Key": fresh_key()} if "Idempotency-Key" in declared else {})


@dataclass(frozen=True)
class Served:
    """One group's app, the ids its world holds (22's path parameter name to value), the methods
    it is asked for (none: every one its router serves) and the world itself, for what a test
    reads off it."""

    app: FastAPI
    pins: Mapping[str, str]
    methods: frozenset[str] = frozenset()
    world: Any = None


class _OwnerOnly(exits_route.Principals):
    """The exit worlds' source reads any bearer but `nobody` as a Manager: only the Owner's
    bearer is a session here, as in the other worlds."""

    async def resolve(self, request: Any) -> TradingPrincipal | None:
        if request.headers.get("authorization") != f"Bearer {OWNER}":
            return None
        return await super().resolve(request)


class _Endless(list[str | BaseException]):
    """A scripted facade's settles that never run out: each answers `state`."""

    def __init__(self, state: str) -> None:
        super().__init__()
        self.state = state

    def pop(self, index: SupportsIndex = -1, /) -> str | BaseException:
        return self.state


def _served(app: FastAPI, pins: Mapping[str, str], *methods: str, world: Any = None) -> Served:
    install_error_redaction(app)  # as `create_app` does: a fault is the 500 a client reads
    return Served(app, pins, frozenset(methods), world)


async def build(group: str, patched: pytest.MonkeyPatch) -> Served:
    """A fresh world of `group` (`GROUP_OF`'s); `patched` holds the exits' facade patch."""
    if group == "reads":
        pins = {"orderId": str(reads_world.order(1, reads_world.ACCOUNT_A).id),
                "positionId": position_world.ON_A}  # fmt: skip
        reads = reads_world.World()
        return _served(reads.app(), pins, world=reads)
    if group == "place":
        return _served(orders_route.World().app(), {})
    if group == "cancel_all":
        return _served(cancel_all_route.World().app(), {})
    if group == "positions":
        limiter = WriteLimiter(rate_per_minute=_UNLIMITED, clock=lambda: 0.0)
        return _served(position_world.World(limiter=limiter).app(),
                       {"positionId": position_world.ON_A})  # fmt: skip
    if group == "leverage":
        return _served(leverage_route.World(rate=_UNLIMITED).app(),
                       {"positionId": leverage_route.ON_A})  # fmt: skip
    amend = group == "amend"
    gate = rig.Risk(InterimRiskGate(now=lambda: _NOW))  # the facade's own wraps none
    world, machines, row, _ = await exits_route.scripted_world("submitted", risk_gate=gate)
    machines.settles = _Endless("submitted" if amend else "cancelled")
    world.principals = _OwnerOnly()
    if amend:
        amend_route.routed(world, versions=machines)
        amend_route.amending(machines, patched)
    return _served(world.app(), {"orderId": str(row.id)}, "PATCH" if amend else "DELETE")
