"""The synchronous checks before each rule action (24 §11.5; E35-T10, #5002, BQ-1).

Every check reads memory and never awaits, so no switch is read from an interpreter (C-2.20,
C-2.21), and each answers a `blocked_by` or `None`, the first refusal winning in the ruled order:
checks 2 and 3 run before the routing emitter (check 4), and checks 5 to 8 in its sink,
`ActionExecutor.hand_over`, before the records written ahead, so a refusal writes `rules.blocked`
and never `rules.fired`. No switch, flag or setting turns a check off (C-4.14): each only refuses,
and a port the composition root has not bound refuses too.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from candleviewer.rules.executor.handlers import ENGINE_INTERNAL, HandlerSpec
from candleviewer.rules.executor.ports import RuleSwitches
from candleviewer.rules.executor.results import BlockedBy


class _Closed:
    """The switches while the composition root has bound none: each reads closed."""

    def rules_enabled(self) -> bool:
        return False

    def order_entry_killed(self) -> bool:
        return True

    def kill_switch_engaged(self, account_id: UUID | None) -> bool:
        return True

    def oms_actions(self) -> bool:
        return False


def scope_refusal(reason: str) -> BlockedBy:
    """Check 4's `blocked_by` for the scope re-check's reason (24 §11.9): `live_gate` and
    `environment` keep their own (C-2.11), every other reason is `scope`."""
    return (
        "live_gate"
        if reason == "live_gate"
        else ("environment" if reason == "environment" else "scope")
    )


class Gates:
    """The checks' ports: the switches (`RuleSwitches`, closed while unbound)."""

    def __init__(self, *, switches: RuleSwitches | None = None) -> None:
        self._switches: RuleSwitches = _Closed() if switches is None else switches

    def before_scope(
        self, spec: HandlerSpec | None, account_id: UUID | None, *, stand_in: bool
    ) -> BlockedBy | None:
        """Checks 2 and 3 for one action on one account (`None` for an action that names none,
        which asks B18's global verdict): the master switch (`rules_disabled`), then whether the
        action can run (`unavailable`), then both kill switches (`kill_switch`). Maintenance mode
        is never read here: it stays the OMS's `order_entry`."""
        switches = self._switches
        if not switches.rules_enabled():
            return "rules_disabled"
        if _unavailable(spec, stand_in=stand_in, rollout=switches.oms_actions):
            return "unavailable"
        if switches.order_entry_killed() or switches.kill_switch_engaged(account_id):
            return "kill_switch"
        return None

    def after_scope(self, spec: HandlerSpec) -> BlockedBy | None:
        """Checks 5 to 8 for one action on one account, in the emitter's sink. Check 8: a type
        refused for good (`widen_stop`) at its own slot, as `native_sl`."""
        return spec.refused_as


def _unavailable(spec: HandlerSpec | None, *, stand_in: bool, rollout: Callable[[], bool]) -> bool:
    """Check 2's second half: no handler is bound (and, for an engine-internal capability, no
    stand-in sink either), or the capability reaches past the engine while the rollout port reads
    off. A type refused for good is refused at check 8 instead, by type."""
    if spec is None:
        return True
    if spec.refused_as is not None:
        return False
    internal = spec.capability in ENGINE_INTERNAL
    if spec.handler is None and not (internal and stand_in):
        return True
    return not internal and not rollout()
