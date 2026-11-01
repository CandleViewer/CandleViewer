"""The synchronous checks before each rule action (24 §11.5; E35-T10, #5002, BQ-1).

Every check reads memory and never awaits, so no switch is read from an interpreter (C-2.20,
C-2.21), and each answers a `blocked_by` or `None`, the first refusal winning in the ruled order:
checks 2 and 3 run before the routing emitter (check 4), and checks 5 to 8 in its sink,
`ActionExecutor.hand_over`, before the records written ahead, so a refusal writes `rules.blocked`
and never `rules.fired`. No switch, flag or setting turns a check off (C-4.14): each only refuses,
and a port the composition root has not bound refuses too.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Final
from uuid import UUID

from candleviewer.rules.executor.handlers import ENGINE_INTERNAL, HandlerSpec
from candleviewer.rules.executor.ports import PrincipalReads, PrincipalView, RuleSwitches
from candleviewer.rules.executor.results import BlockedBy
from candleviewer.rules.scope import ActionRequest

#: A principal snapshot older than this, in seconds, is a failed read (24 §11.5 "The principal";
#: the E35 threat model's §5): the executor holds the bound, so no binding widens it.
PRINCIPAL_MAX_AGE_S: Final = 1.0
#: The scope re-check's reasons that keep a `blocked_by` of their own (C-2.11).
_OWN_REASONS: Final[Mapping[str, BlockedBy]] = {
    "live_gate": "live_gate", "environment": "environment"
}  # fmt: skip
#: What an action's `targets` resolved to (24 §11.5): its accounts, in order (`None` alone for an
#: action that names none; empty for an `all_accounts` intersection that holds none), and whether
#: they are `all_accounts`'.
Targets = tuple[tuple[UUID | None, ...], bool]


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


def scope_refusal(reason: object) -> BlockedBy:
    """Check 4's `blocked_by` for the scope re-check's reason (24 §11.9): `live_gate` and
    `environment` keep their own (C-2.11), every other reason is `scope`."""
    return _OWN_REASONS.get(reason, "scope") if isinstance(reason, str) else "scope"


def _user(user_id: object) -> UUID | None:
    try:
        return UUID(str(user_id)) if user_id is not None else None
    except ValueError:
        return None


class Gates:
    """The checks' ports: the switches (`RuleSwitches`, closed while unbound) and the principal
    reads (`PrincipalReads`, unbound until E35-T11, so refusing)."""

    def __init__(
        self, *, switches: RuleSwitches | None = None, principal: PrincipalReads | None = None
    ) -> None:
        self._switches: RuleSwitches = _Closed() if switches is None else switches
        self._principal = principal

    def resolve_targets(self, req: ActionRequest, spec: HandlerSpec | None, now: float) -> Targets:
        """24 §11.5 (BQ-4): an engine-internal type names no account; `scope_accounts` and
        `originating_account` resolve to the firing instance's account; `all_accounts` to the
        intersection of the owner's and the armer's admitted accounts, sorted, each user's
        snapshot fresh and active, else to none. Check 4 still refuses an account outside the
        rule's scope."""
        if spec is not None and spec.capability in ENGINE_INTERNAL:
            return (None,), False
        if req.payload.targets != "all_accounts":
            return (req.instance.account_id,), False
        owner, armer = self._read(req.owner), self._read(req.armed_by)
        if not (_fresh(owner, now) and _fresh(armer, now)) or owner is None or armer is None:
            return (), True
        return tuple(sorted(owner.trade_accounts & armer.trade_accounts, key=str)), True

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

    def principal(
        self, req: ActionRequest, account_id: UUID | None, *, all_accounts: bool, now: float
    ) -> tuple[BlockedBy | None, PrincipalView | None, PrincipalView | None]:
        """Check 5 (`permission`; 24 §11.5, BQ-5) with the owner's and the armer's snapshots it
        read: refused when either is missing, older than `PRINCIPAL_MAX_AGE_S` or inactive, or
        does not admit the account; an action that names no account needs both active; and
        `all_accounts` needs the owner, the OMS principal, to hold the Owner role now."""
        owner, armer = self._read(req.owner), self._read(req.armed_by)
        admitted = (
            owner is not None
            and armer is not None
            and _fresh(owner, now)
            and _fresh(armer, now)
            and (account_id is None or account_id in owner.trade_accounts & armer.trade_accounts)
            and (owner.is_owner or not all_accounts)
        )
        return (None if admitted else "permission"), owner, armer

    def stop_check(self, spec: HandlerSpec) -> BlockedBy | None:
        """Check 8: a type refused for good (`widen_stop`) at its own slot, as `native_sl`."""
        return spec.refused_as

    def _read(self, user_id: object) -> PrincipalView | None:
        """A user's snapshot as the port gives it; `None` while unbound or unread."""
        user = _user(user_id)
        if self._principal is None or user is None:
            return None
        view = self._principal.principal(user)
        return None if view is None or view.user_id != user else view


def _fresh(view: PrincipalView | None, now: float) -> bool:
    """A snapshot that may serve check 5: read, active, and at most `PRINCIPAL_MAX_AGE_S` old."""
    return view is not None and view.active and now - view.read_at <= PRINCIPAL_MAX_AGE_S


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
