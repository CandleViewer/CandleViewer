"""Pure guards and mappings for the admin ops surfaces (E42-T05, module M21).

- `check_restore`: the restore preconditions. They live in the service layer, never the router,
  so every caller inherits them, and nothing is trusted from the client: maintenance mode must be
  on, and open positions need an explicit acknowledgement. An open-position count that could not
  be read counts as open (fail closed). A refusal raises before any job exists.
- `system_health_frame`: E04's `HealthSnapshot` in the `system` topic's vocabulary
  (`23-ws-protocol.md` 15.9). Names pass through, unknown ones included; `not_deployed` exists
  only in the REST report, so it is sent as `healthy` with `detail: "not deployed"`.
"""

from __future__ import annotations

from typing import Any, Final, Literal

from candleviewer.admin.errors import AdminError
from candleviewer.observability.health_probes import ComponentState, HealthSnapshot

RestoreRule = Literal["maintenance_mode_required", "open_positions_unacknowledged"]
NOT_DEPLOYED_DETAIL: Final = "not deployed"


class RestoreRefusedError(AdminError):
    """A restore precondition is not met: `409 conflict` naming `rule`; no job is created."""

    def __init__(self, rule: RestoreRule, field: str, detail: str) -> None:
        super().__init__(detail)
        self.rule: RestoreRule = rule
        self.field = field
        self.detail = detail


def check_restore(
    *, maintenance_mode: bool, open_positions: int | None, acknowledge_open_positions: bool
) -> None:
    """Raise `RestoreRefusedError` unless a restore may start (maintenance is checked first)."""
    if not maintenance_mode:
        raise RestoreRefusedError(
            "maintenance_mode_required",
            "maintenance.mode",
            "Restore requires maintenance mode to be on.",
        )
    if acknowledge_open_positions or open_positions == 0:
        return
    shown = (
        "Open positions are unknown"
        if open_positions is None
        else f"{open_positions} positions are open"
    )
    raise RestoreRefusedError(
        "open_positions_unacknowledged",
        "acknowledge_open_positions",
        f"{shown}; acknowledge them to restore.",
    )


def _wire_state(state: ComponentState) -> str:
    return ComponentState.HEALTHY.value if state is ComponentState.NOT_DEPLOYED else state.value


def _wire_detail(state: ComponentState, detail: str) -> str:
    return NOT_DEPLOYED_DETAIL if state is ComponentState.NOT_DEPLOYED else detail


def system_health_frame(snapshot: HealthSnapshot) -> dict[str, Any]:
    """The `system` payload of `kind: "health"` for one snapshot; every component is kept."""
    return {
        "kind": "health",
        "health": _wire_state(snapshot.overall),
        "components": [
            {
                "name": c.name,
                "state": _wire_state(c.state),
                "detail": _wire_detail(c.state, c.detail),
            }
            for c in snapshot.components
        ],
    }
