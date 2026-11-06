"""The synchronous checks before each rule action (24 §11.5; E35-T10, #5002, BQ-1).

No check reads an interpreter (C-2.21), and each answers its refusal or `None`, the first refusal
winning in the ruled order. Checks 2 and 3 read memory and never await (C-2.20); they run before
the routing emitter (check 4), and checks 5 to 8 in its sink, `ActionExecutor.hand_over`, in the
dispatch worker and never on the evaluation tick, before the records written ahead, so a refusal
writes `rules.blocked` and never `rules.fired`. Of those, only two reads are awaited, each bounded:
check 6's day rebuild here, and check 7's in `budget.py`. No switch, flag or setting turns a check
off (C-4.14): each only refuses, and a port the composition root has not bound refuses too.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

import structlog

from candleviewer.rules.executor.handlers import ENGINE_INTERNAL, HandlerSpec
from candleviewer.rules.executor.ports import (
    NotionalRebuild,
    PrincipalReads,
    PrincipalView,
    RuleSwitches,
    StopCheck,
)
from candleviewer.rules.executor.results import BlockedBy, RuleLimit
from candleviewer.rules.ir.models import RuleLimits
from candleviewer.rules.scope import ActionRequest

#: A principal snapshot older than this, in seconds, is a failed read (24 §11.5 "The principal";
#: the E35 threat model's §5): the executor holds the bound, so no binding widens it.
PRINCIPAL_MAX_AGE_S: Final = 1.0
#: How far ahead of the executor's clock a snapshot may be stamped: the clock is read before the
#: port, so a read stamped as it is read lands a little ahead; one further ahead is a failed read,
#: so a binding on another clock base never reads fresh for good.
PRINCIPAL_AHEAD_S: Final = 0.1
#: The scope re-check's reasons that keep a `blocked_by` of their own (C-2.11).
_OWN_REASONS: Final[Mapping[str, BlockedBy]] = {
    "live_gate": "live_gate", "environment": "environment"
}  # fmt: skip
#: The bound on the day's notional rebuild (24 §11.7), a write ahead's.
NOTIONAL_REBUILD_TIMEOUT_S: Final = 2.0
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


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class Halts:
    """The trip and kill times per rule (24 §11.5, §11.7; BQ-8, BQ-9), on the service's monotonic
    clock, which each fire's offer time shares: a fire offered before its rule's trip time is
    refused whole at dispatch (`circuit_breaker`), and one offered before its kill time
    (`kill_switch`), even after a re-arm."""

    def __init__(self) -> None:
        self.tripped: dict[str, float] = {}
        self.killed: dict[str, float] = {}

    def block(self, rule_id: str, offered_at: float) -> BlockedBy | None:
        trip, kill = self.tripped.get(rule_id), self.killed.get(rule_id)
        if trip is not None and offered_at <= trip:
            return "circuit_breaker"
        return "kill_switch" if kill is not None and offered_at <= kill else None


class Allowance:
    """Check 6's notional allowance for an entry (24 §11.7, C-12.5; BQ-11): the smaller of the
    fire's and the UTC day's remainders, refused (`cap`, naming the limit) once spent and never
    clamped, else the ceiling `Handler.prepare` gets. The ledger is fed from an accepted answer's
    `notional_usd`; a rule's day is rebuilt through `NotionalRebuild` at its first entry of the
    day, and while that port is unbound or its read fails or runs late, an entry of a rule with
    `max_daily_notional` set is refused."""

    def __init__(
        self, rebuild: NotionalRebuild | None = None, wall: Callable[[], float] = time.time
    ) -> None:
        self._rebuild, self._wall = rebuild, wall
        self._day: date | None = None
        self._days: dict[str, Decimal] = {}  # per rule: what it sent today, once rebuilt
        self._fires: dict[UUID, Decimal] = {}  # per fire running: what it sent

    async def remainder(
        self, rule_id: str, run_id: UUID, limits: RuleLimits
    ) -> tuple[RuleLimit | None, Decimal | None]:
        """`(limit, None)` when the limit's allowance is spent or the day's is not confirmed;
        else `(None, ceiling)`, the ceiling `None` when the rule sets no notional limit."""
        left: list[tuple[Decimal, RuleLimit]] = []
        if limits.max_notional_per_fire is not None:
            spent = self._fires.get(run_id, Decimal(0))
            left.append((limits.max_notional_per_fire - spent, "max_notional_per_fire"))
        if limits.max_daily_notional is not None:
            today = await self._today(rule_id)
            if today is None:
                return "max_daily_notional", None
            left.append((limits.max_daily_notional - today, "max_daily_notional"))
        if not left:
            return None, None
        remainder, limit = min(left, key=lambda pair: pair[0])
        return (limit, None) if remainder <= 0 else (None, remainder)

    def spend(self, rule_id: str, run_id: UUID, notional: Decimal) -> None:
        """An accepted entry's notional, on its fire and, once rebuilt, on its rule's day."""
        self._fires[run_id] = self._fires.get(run_id, Decimal(0)) + notional
        if rule_id in self._days:
            self._days[rule_id] += notional

    def ended(self, run_id: UUID) -> None:
        self._fires.pop(run_id, None)

    async def _today(self, rule_id: str) -> Decimal | None:
        today = datetime.fromtimestamp(self._wall(), UTC).date()
        if today != self._day:
            self._day, self._days = today, {}
        if rule_id not in self._days:
            if self._rebuild is None:
                return None
            try:
                async with asyncio.timeout(NOTIONAL_REBUILD_TIMEOUT_S):
                    self._days[rule_id] = await self._rebuild.day_notional(rule_id, today)
            except Exception as lost:  # never `CancelledError`, which is no `Exception`
                _log().warning(
                    "rules.notional_unrebuilt", rule_id=rule_id, error=type(lost).__name__
                )
                return None
        return self._days[rule_id]


def _user(user_id: object) -> UUID | None:
    try:
        return UUID(str(user_id)) if user_id is not None else None
    except ValueError:
        return None


class Gates:
    """The checks' ports: the switches (`RuleSwitches`, closed while unbound), the principal
    reads (`PrincipalReads`, unbound until E35-T11, so refusing), the allowance's day rebuild
    (`NotionalRebuild`, E35-T11's) and the stop check (`StopCheck`, E35-T12's)."""

    def __init__(
        self,
        *,
        switches: RuleSwitches | None = None,
        principal: PrincipalReads | None = None,
        notional: NotionalRebuild | None = None,
        stop: StopCheck | None = None,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self._switches: RuleSwitches = _Closed() if switches is None else switches
        self._principal, self._stop = principal, stop
        self.allowance = Allowance(notional, wall)

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
        self,
        spec: HandlerSpec | None,
        account_id: UUID | None,
        *,
        stand_in: bool,
        dry_run: bool = False,
    ) -> BlockedBy | None:
        """Checks 2 and 3 for one action on one account (`None` for an action that names none,
        which asks B18's global verdict): the master switch (`rules_disabled`), then whether the
        action can run (`unavailable`, never for a `dry_run` action, which no handler serves),
        then both kill switches (`kill_switch`). Maintenance mode is never read here: it stays the
        OMS's `order_entry`."""
        switches = self._switches
        if not switches.rules_enabled():
            return "rules_disabled"
        if not dry_run and _unavailable(spec, stand_in=stand_in, rollout=switches.oms_actions):
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

    @staticmethod
    def per_fire(position: int, limits: RuleLimits) -> RuleLimit | None:
        """Check 6's first half: `max_actions_per_fire`, by the action's 1-based IR position."""
        return "max_actions_per_fire" if position > limits.max_actions_per_fire else None

    def stop_check(
        self, spec: HandlerSpec, req: ActionRequest, account_id: UUID | None
    ) -> BlockedBy | None:
        """Check 8 (`native_sl`; 24 §11.5, BQ-12): a type refused for good (`widen_stop`) at its
        own slot; a stop action the recorded-stop writer's comparison does not admit, or that no
        port judges while it is unbound."""
        if spec.refused_as is not None:
            return spec.refused_as
        if spec.touches_stop and (self._stop is None or not self._stop.admits(req, account_id)):
            return "native_sl"
        return None

    def _read(self, user_id: object) -> PrincipalView | None:
        """A user's snapshot as the port gives it; `None` while unbound or unread."""
        user = _user(user_id)
        if self._principal is None or user is None:
            return None
        view = self._principal.principal(user)
        return None if view is None or view.user_id != user else view


def _fresh(view: PrincipalView | None, now: float) -> bool:
    """A snapshot that may serve check 5: read, active, at most `PRINCIPAL_MAX_AGE_S` old and at
    most `PRINCIPAL_AHEAD_S` ahead of the executor's clock."""
    return (
        view is not None
        and view.active
        and -PRINCIPAL_AHEAD_S <= now - view.read_at <= PRINCIPAL_MAX_AGE_S
    )


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
