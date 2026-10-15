"""Runtime rule-scope enforcement (E35-S04; US-RULE-007; 24-internal-schemas.md 11.5 E6/E11/E12).

Resolution runs twice per fire: once to build instances, again right before each action.
State comes from an in-memory snapshot (grants/accounts/freeze) behind ``ScopeState``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

from candleviewer.rules.errors import ScopeForbiddenError
from candleviewer.rules.evaluator.engine import scope_instance
from candleviewer.rules.ir.models import RuleScope

SKIPPED_REASON = "scope"
Reason = Literal[
    "grant_revoked",
    "account_disabled",
    "manager_frozen",
    "environment",
    "live_gate",
    "symbol_not_allowed",
    "applies_to",
    "algo_child",
    "out_of_scope",
]
EntityKind = Literal["open_position", "pending_order", "account"]


@dataclass(frozen=True, slots=True)
class AccountState:
    environment: str
    enabled: bool = True
    frozen: bool = False
    allowed_symbols: frozenset[str] | None = None  # None = no profile restriction (E28)


class ScopeState(Protocol):
    """Current-state reads; implementations are in-memory, invalidated on auth/account events."""

    def granted_accounts(self, owner: UUID) -> frozenset[UUID]: ...
    def account(self, account_id: UUID) -> AccountState | None: ...
    def owner_frozen(self, owner: UUID) -> bool: ...  # E39 manager freeze / kill switch
    def live_gate_open(self) -> bool: ...  # M1 backend configuration layer
    def can_arm_live(self, owner: UUID) -> bool: ...  # seeded rules:arm_live permission


@dataclass(frozen=True, slots=True)
class ScopeInstanceRef:
    key: str
    symbol: str | None
    account_id: UUID | None


@dataclass(frozen=True, slots=True)
class Suppression:
    instance: ScopeInstanceRef
    reason: Reason
    skipped_reason: str = SKIPPED_REASON


@dataclass(slots=True)
class Resolution:
    instances: list[ScopeInstanceRef] = field(default_factory=list)
    suppressed: list[Suppression] = field(default_factory=list)
    env_skipped: bool = False


AuditSink = Callable[[str, dict[str, str]], Awaitable[None]]  # required: C-2.9, no silent default


class ScopeResolver:
    def __init__(
        self,
        state: ScopeState,
        audit: AuditSink,
    ) -> None:
        self._state = state
        self._audit = audit
        self.suppressions_total: Counter[str] = Counter()  # rule_scope_suppressions_total{reason}
        self.env_skips_total = 0

    def _account_reason(self, owner: UUID, account_id: UUID, symbol: str | None) -> Reason | None:
        st = self._state
        if st.owner_frozen(owner):
            return "manager_frozen"
        if account_id not in st.granted_accounts(owner):
            return "grant_revoked"
        acct = st.account(account_id)
        if acct is None or not acct.enabled:
            return "account_disabled"
        if acct.frozen:
            return "manager_frozen"
        if (
            symbol is not None
            and acct.allowed_symbols is not None
            and symbol not in acct.allowed_symbols
        ):
            return "symbol_not_allowed"
        return None

    def _env_ok(self, scope: RuleScope, owner: UUID, environment: str) -> bool:
        if environment not in scope.environments:
            return False
        if environment == "live":
            return self._state.live_gate_open() and self._state.can_arm_live(owner)
        return True

    def resolve(
        self, scope: RuleScope, owner: UUID, environment: str, *, symbols: Iterable[str] = ()
    ) -> Resolution:
        """First resolution: expand scope into independent per-(symbol, account) instances."""
        res = Resolution()
        if not self._env_ok(scope, owner, environment):
            res.env_skipped = True
            self.env_skips_total += 1
            return res
        accounts = (
            [UUID(str(a)) for a in scope.account_ids]
            if scope.account_ids
            else sorted(self._state.granted_accounts(owner), key=str)
        )
        syms: list[str | None] = list(scope.symbols) or list(symbols) or [None]
        for acct in accounts:
            acct_state = self._state.account(acct)
            if acct_state is not None and acct_state.environment != environment:
                continue  # account belongs to another environment
            for sym in syms:
                ref = ScopeInstanceRef(scope_instance(sym, str(acct)), sym, acct)
                reason = self._account_reason(owner, acct, sym)
                if reason is None:
                    res.instances.append(ref)
                else:
                    res.suppressed.append(Suppression(ref, reason))
                    self.suppressions_total[reason] += 1
        return res

    def check_action(
        self,
        scope: RuleScope,
        owner: UUID,
        environment: str,
        instance: ScopeInstanceRef,
        entity: EntityKind = "account",
        *,
        is_algo_child: bool = False,
    ) -> Reason | None:
        """Second resolution, before each action. None = allowed, else suppression reason."""
        reason: Reason | None
        if not self._env_ok(scope, owner, environment):
            reason = "live_gate" if environment == "live" else "environment"
        elif instance.account_id is None:
            reason = "grant_revoked"
        else:
            reason = self._account_reason(owner, instance.account_id, instance.symbol)
        if reason is None and _outside_scope(scope, instance):
            reason = "out_of_scope"  # action targets an account/symbol outside the rule's scope
        if reason is None:
            if scope.exclude_algo_children and is_algo_child:
                reason = "algo_child"
            elif not _applies(scope.applies_to, entity):
                reason = "applies_to"
        if reason is not None:
            self.suppressions_total[reason] += 1
        return reason

    async def authorize_accounts(self, caller: UUID, account_ids: Iterable[UUID]) -> None:
        """403 for any account the caller cannot see; absent == not granted (no leak)."""
        granted = self._state.granted_accounts(caller)
        for acct in account_ids:
            if acct not in granted or self._state.account(acct) is None:
                await self._audit(
                    "rule_scope_denied", {"caller": str(caller), "account": str(acct)}
                )
                raise ScopeForbiddenError(ScopeForbiddenError.message)

    def listable_accounts(self, caller: UUID) -> list[UUID]:
        granted = self._state.granted_accounts(caller)
        return sorted((a for a in granted if self._state.account(a) is not None), key=str)

    async def authorize_environments(
        self, caller: UUID, scope: RuleScope, *, audit_armed: bool = True
    ) -> None:
        """Including live needs rules:arm_live; denial is always audited, the high-severity
        `rule_live_scope_armed` only when `audit_armed` (the real arm transition / dry run)."""
        if "live" in scope.environments:
            if not self._state.can_arm_live(caller):
                await self._audit(
                    "rule_scope_denied", {"caller": str(caller), "environment": "live"}
                )
                raise ScopeForbiddenError(ScopeForbiddenError.message)
            if audit_armed:
                await self._audit(
                    "rule_live_scope_armed", {"caller": str(caller), "severity": "high"}
                )


def _outside_scope(scope: RuleScope, instance: ScopeInstanceRef) -> bool:
    accounts = {str(a) for a in scope.account_ids}
    if accounts and str(instance.account_id) not in accounts:
        return True
    return bool(scope.symbols and instance.symbol and instance.symbol not in scope.symbols)


def _applies(applies_to: str, entity: EntityKind) -> bool:
    return {
        "any": True,
        "account": True,
        "open_positions": entity == "open_position",
        "pending_orders": entity == "pending_order",
    }[applies_to]


def summarize_scope(scope: RuleScope, *, account_count: int | None = None) -> str:
    """Server-derived header chip, e.g. ``2 accounts · BTCUSDT · open positions only · demo``."""
    n = len(scope.account_ids) if scope.account_ids else account_count
    accounts = "all permitted accounts" if n is None else f"{n} account{'s' if n != 1 else ''}"
    syms = ", ".join(scope.symbols) if scope.symbols else "all symbols"
    what = {
        "open_positions": "open positions only",
        "pending_orders": "pending orders only",
        "account": "account level",
        "any": "any positions and orders",
    }[scope.applies_to]
    return f"{accounts} · {syms} · {what} · {' and '.join(scope.environments)}"


def make_scope_gate(
    resolver: ScopeResolver,
    scope: RuleScope | Callable[[], RuleScope],
    owner: UUID,
    environment: str,
) -> Callable[[str], str | None]:
    """Evaluator ``scope_gate``: re-resolves scope on every trigger; reason => skipped "scope"."""

    def gate(instance_key: str) -> str | None:
        sym, _, acct = instance_key.partition("@")
        ref = ScopeInstanceRef(
            instance_key, None if sym == "*" else sym, None if acct == "*" else UUID(acct)
        )
        current = scope() if callable(scope) else scope  # runtime scope change: no restart
        return resolver.check_action(current, owner, environment, ref)

    return gate


ActionDispatch = Callable[[ScopeInstanceRef], Awaitable[None]]


@dataclass(slots=True)
class FireOutcome:
    fired: bool
    dispatched: int = 0
    suppressed: Reason | None = None
    skipped_reason: str | None = None


async def fire_scoped(
    resolver: ScopeResolver,
    scope: RuleScope,
    owner: UUID,
    environment: str,
    instance: ScopeInstanceRef,
    dispatch: ActionDispatch,
    *,
    entity: EntityKind = "account",
    is_algo_child: bool = False,
) -> FireOutcome:
    """Action-dispatch gate: the second resolution runs immediately before EVERY action.

    A live trigger for an instance whose scope no longer holds (revoked grant, freeze, closed
    live gate...) is skipped with ``skipped_reason="scope"`` and counted; nothing is dispatched.
    """
    reason = resolver.check_action(
        scope, owner, environment, instance, entity, is_algo_child=is_algo_child
    )
    if reason is not None:
        return FireOutcome(False, 0, reason, SKIPPED_REASON)
    await dispatch(instance)
    return FireOutcome(True, 1)


@dataclass(frozen=True, slots=True)
class ActionRequest:
    rule_scope: RuleScope
    owner: UUID
    environment: str
    instance: ScopeInstanceRef
    action_type: str
    payload: object = None


ActionSink = Callable[[ActionRequest], Awaitable[None]]


class ScopedActionEmitter:
    """Single evaluator-output boundary: every action passes the scope gate BEFORE the sink."""

    def __init__(self, resolver: ScopeResolver, audit: AuditSink, sink: ActionSink) -> None:
        self._resolver, self._audit, self._sink = resolver, audit, sink
        self.denied_total = 0  # rule_action_scope_denied_total

    async def emit(self, req: ActionRequest) -> bool:
        reason = self._resolver.check_action(
            req.rule_scope, req.owner, req.environment, req.instance
        )
        if reason is not None:
            self.denied_total += 1
            await self._audit(
                "rule_action_scope_denied",
                {
                    "caller": str(req.owner),
                    "reason": reason,
                    "action": req.action_type,
                    "account": str(req.instance.account_id),
                    "symbol": str(req.instance.symbol),
                    "scope_before": req.rule_scope.model_dump_json(),
                },
            )
            return False
        await self._sink(req)
        return True
