"""Order-acceptance gate for maintenance mode (E42-T03, M23).

Every order-accepting route calls `order_entry_refusal` first, before any OMS work, in the same
shape as `require_elevation_for`: `None` lets the order through, otherwise the route returns the
`403 trading_disabled` problem. The gate is the synchronous `MaintenanceGate` boolean, so the
refusal is immediate once maintenance mode is on (C-2.21: synchronous code enforces).
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
            "title": "Kill-switch engaged or live trading not enabled for this deployment",
            "status": 403,
            "code": "trading_disabled",
            "detail": "Maintenance mode is on; order entry is paused.",
        },
        media_type="application/problem+json",
    )
