"""Order-entry gate for maintenance mode (E42-T03, M23).

Every submission that opens or increases exposure, and every risk-increasing amend, calls
`order_entry_refusal` before any OMS work (`24-internal-schemas.md` 8.10): `None` lets it
through, else the route returns `403 trading_disabled` with `reason: maintenance` (D5a).
Attaching a missing native SL, tightening a stop, or re-arming a protective trigger is never
gated; "trigger re-armed" means an exposure-increasing (entry) trigger. An amend with any
risk-increasing component is gated. The `MaintenanceGate` boolean is synchronous (C-2.21).
"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from candleviewer.admin.flags import MaintenanceGate


def order_entry_refusal(gate: MaintenanceGate) -> JSONResponse | None:
    if not gate.engaged:
        return None
    return JSONResponse(
        status_code=403,
        content={
            "type": "https://candleviewer.local/errors/trading_disabled",
            "title": "Order entry refused",  # the registry title of trading_disabled
            "status": 403,
            "code": "trading_disabled",
            "detail": "Order entry is paused.",
            "reason": "maintenance",
        },
        media_type="application/problem+json",
    )
