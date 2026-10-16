"""The order-entry gate at the API edge (#837 Q5, E42-T03, M23).

The composition root builds one `OrderEntryGate(maintenance_gate, *account_checks)` (the
`MaintenanceGate` first, then the E27-T04 account checks) and every order-submit route calls
`order_entry_refusal(gate, account_id)`. `None` lets the order through; otherwise the route returns
the problem it gives back. Obligations for every submit route (the E29 wiring):

1. **Order of operations.** Authenticate, then resolve the target account within the caller's
   scope (`404 not_found` when it is out of scope, so account health never leaks across scopes,
   C-12.4), then call the gate, then the OMS. The maintenance check is global and may also run
   before the account is resolved.
2. **Audit.** The refused submit attempt is audited write-ahead at the submit route, like an
   accepted one (C-2.9, #837 Q6); the gate itself writes no audit.
3. **Second check.** The OMS intake re-checks the same composed gate synchronously, immediately
   before signing, so a state that changes between the route's check and the exchange call still
   refuses the order (C-2.21).

A refusal is the existing `403 trading_disabled` problem plus a `reason` extension member from
the closed `REFUSAL_REASONS` set. Each refusal is logged (`order_entry_refused`, with `reason`
and `account_id`, never `detail`) and counted in `cv_order_entry_refusals_total{reason}`. The
gate is synchronous and never flag-gated (C-2.21, C-4.14), and it belongs on submit routes only:
never on cancel, flatten or a stop-loss amend, which keep working while order entry is paused
(C-2.6). A check that raises propagates and the route answers a redacted 500; it never admits.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi.responses import JSONResponse

from candleviewer.admin.flags.metrics import order_entry_refusals_total
from candleviewer.domain.order_entry import (
    REFUSAL_REASONS,
    OrderEntryCheck,
    OrderEntryGate,
    OrderEntryRefusal,
    RefusalReason,
)

__all__ = [
    "REFUSAL_REASONS",
    "OrderEntryCheck",
    "OrderEntryGate",
    "OrderEntryRefusal",
    "RefusalReason",
    "order_entry_refusal",
    "refusal_problem",
]

#: The `x-error-codes` title of `trading_disabled` (`22-api-openapi.yaml`).
_TITLE = "Kill-switch or maintenance mode engaged, or live trading not enabled for this deployment"


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
