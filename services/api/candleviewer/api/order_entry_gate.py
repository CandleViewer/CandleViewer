"""The order-entry gate at the API edge (#837 Q5, E42-T03, M23).

Every order-submit route calls `order_entry_refusal(checks, account_id)` first, before any OMS work,
in the same shape as `require_elevation_for`: `None` lets the order through, otherwise the route
returns the problem it gives back. The composition root builds `checks` once, with the maintenance
gate first and the account checks (E27-T04) after it; the first refusal wins.

A refusal is the existing `403 trading_disabled` problem plus a `reason` extension member, the
closed set of `candleviewer.domain.order_entry.REFUSAL_REASONS`. The gate is synchronous and never
flag-gated (C-2.21, C-4.14), and it belongs on submit routes only: never on cancel, flatten or a
stop-loss amend, which must keep working while order entry is paused (C-2.6).
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from fastapi.responses import JSONResponse

from candleviewer.domain.order_entry import (
    REFUSAL_REASONS,
    OrderEntryCheck,
    OrderEntryRefusal,
    RefusalReason,
    first_refusal,
)

__all__ = [
    "REFUSAL_REASONS",
    "OrderEntryCheck",
    "OrderEntryRefusal",
    "RefusalReason",
    "first_refusal",
    "order_entry_refusal",
    "refusal_problem",
]

#: The `x-error-codes` title of `trading_disabled` (`22-api-openapi.yaml`).
_TITLE = "Kill-switch or maintenance mode engaged, or live trading not enabled for this deployment"


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


def order_entry_refusal(
    checks: Iterable[OrderEntryCheck], account_id: UUID | None
) -> JSONResponse | None:
    """`None` when every check lets the order through, else the first refusal's problem."""
    refusal = first_refusal(checks, account_id)
    return None if refusal is None else refusal_problem(refusal)
