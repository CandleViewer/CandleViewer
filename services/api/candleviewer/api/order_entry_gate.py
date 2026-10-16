"""The order-entry gate at the API edge (#837 Q5, E42-T03, M23).

The composition root builds one `OrderEntryGate(maintenance_gate, *account_checks)` (the
`MaintenanceGate`, a `GlobalOrderEntryCheck`, first, then the E27-T04 account checks) and every
submit route calls `order_entry_refusal(gate, account_id)`. `None` lets the order through;
otherwise the route returns the problem it gives back. Obligations for every submit route (E29):

1. **Order of operations.** Authenticate, check RBAC, then resolve the target account within the
   caller's scope (`404 not_found` when it is out of scope, so account health never leaks across
   scopes, C-12.4), then call the gate, then the OMS. Maintenance is global, but
   `refusal(account_id)` takes the resolved account, so the route resolves scope first. The B18
   kill switch (FREEZE) and the live-not-enabled refusal are separate synchronous checks ahead of
   the gate, after the same steps. A trade-group submit consults the gate once per leg's account,
   as each leg is sent: a refused leg is a failed leg under the group's `leg_failure_policy`.
2. **Audit.** The refused submit attempt is audited write-ahead at the submit route, like an
   accepted one (C-2.9, #837 Q6); the gate itself writes no audit.
3. **Second check.** The OMS intake re-checks the same composed gate synchronously, immediately
   before signing, so a state that changes between the route's check and the exchange call still
   refuses the order (C-2.21).

**Scope** (`24-internal-schemas.md` 8.10 is the single source). The gate runs at the OMS
submission choke point for every submission that opens or increases exposure: REST order and
trade-group submits, rule and paper legs, and emulated-algo child orders. Risk-increasing amends
(quantity up, stop loosened, trigger re-armed) are refused the same way. Cancels, `closePosition`,
`closeAllPositions`, quantity-reducing and stop-tightening amends never are (C-2.6), so they keep
working while order entry is paused. Attaching a missing native SL, tightening a stop, or
re-arming a protective trigger is never gated; "trigger re-armed" above means an
exposure-increasing (entry) trigger. An amend with any risk-increasing component is gated. A
`placeOrder` with `reduce_only` is a submission and is gated; closing goes through the close
routes. A take-profit change is never a risk-increasing component, the SL component of a
`trading-stop` write is never refused, and a protective stop is never sent as a gated
`placeOrder`. The C-2.6 carve-out binds every synchronous refusal, not just the gate. The gate
never inspects the order: the caller classifies the operation.

A refusal is the existing `403 trading_disabled` problem plus a `reason` extension member from
the closed `REFUSAL_REASONS` set. Each refusal is logged (`order_entry_refused`, with `reason`
and `account_id`, never `detail`) and counted in `cv_order_entry_refusals_total{reason}`; an
admitted order is neither. The gate is synchronous and never flag-gated (C-2.21, C-4.14). A check
that raises propagates and the route answers a redacted 500; it never admits.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi.responses import JSONResponse

from candleviewer.admin.flags import order_entry_refusals_total
from candleviewer.domain.order_entry import (
    REFUSAL_REASONS,
    GlobalOrderEntryCheck,
    OrderEntryCheck,
    OrderEntryGate,
    OrderEntryRefusal,
    RefusalReason,
)

__all__ = [
    "REFUSAL_REASONS",
    "GlobalOrderEntryCheck",
    "OrderEntryCheck",
    "OrderEntryGate",
    "OrderEntryRefusal",
    "RefusalReason",
    "order_entry_refusal",
    "refusal_problem",
]

#: The `x-error-codes` title of `trading_disabled` (`22-api-openapi.yaml`).
_TITLE = "Order entry refused"


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


def refusal_problem(refusal: OrderEntryRefusal) -> JSONResponse:
    """The `403 trading_disabled` problem for one refusal, with its `reason` member."""
    return JSONResponse(
        status_code=403,
        content={
            "type": "https://candleviewer.local/errors/trading_disabled",
            "title": _TITLE,
            "status": 403,
            "code": "trading_disabled",
            "detail": refusal.detail,
            "reason": refusal.reason,
        },
        media_type="application/problem+json",
    )


def order_entry_refusal(gate: OrderEntryGate, account_id: UUID) -> JSONResponse | None:
    """`None` when every check lets the order through, else the first refusal's problem."""
    refusal = gate.refusal(account_id)
    if refusal is None:
        return None
    order_entry_refusals_total.labels(reason=refusal.reason).inc()
    logger().info("order_entry_refused", reason=refusal.reason, account_id=str(account_id))
    return refusal_problem(refusal)
