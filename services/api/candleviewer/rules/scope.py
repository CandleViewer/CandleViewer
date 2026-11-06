"""Runtime rule-scope enforcement (E35-S04; US-RULE-007; 24-internal-schemas.md 11.5 E6/E11/E12).

Resolution runs twice per fire: once to build instances, again right before each action.
State comes from an in-memory snapshot (grants/accounts/freeze) behind ``ScopeState``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Container, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Literal, Protocol
from uuid import UUID

from candleviewer.rules.errors import ScopeForbiddenError
from candleviewer.rules.evaluator.engine import (
    BEFORE_SCOPE_GATE,
    EvaluationResult,
    parse_instance,
    scope_instance,
)
from candleviewer.rules.ir.models import Action, RuleScope

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
#: The cause a `rule_action_scope_denied` record names for an evaluation skipped because the
#: instance may not read a metric ref its rule names (`EvaluationResult.binding_refused`): an
#: evaluation skip, not a refusal by the scope gate, so it is not one of the `Reason`s.
BINDING_CAUSE = "metric_ref_binding"
EntityKind = Literal["open_position", "pending_order", "account"]
#: The entity a scope instance stands for, by its rule's `applies_to` (#5817): the open positions
#: or the pending orders on the instance's symbol and account, or else the account itself.
_INSTANCE_ENTITY: Final[Mapping[str, EntityKind]] = MappingProxyType(
    {
        "open_positions": "open_position",
        "pending_orders": "pending_order",
        "account": "account",
        "any": "account",
    }
)
#: The modes the evaluator runs a rule in (`rules.manager` imports it from here). A rule's mode is
#: its stored row's, never the IR's own `mode` field, which can be stale (E35-S03, BQ-12).
EvaluableMode = Literal["simulate", "armed"]


@dataclass(frozen=True, slots=True)
class AccountState:
    environment: str
    enabled: bool = True
    frozen: bool = False  # the reading owner's own grant is frozen: per (owner, account)
    allowed_symbols: frozenset[str] | None = None  # None = no profile restriction (E28)


class ScopeState(Protocol):
    """Current-state reads; implementations are in-memory, invalidated on auth/account events."""

    def granted_accounts(self, owner: UUID) -> frozenset[UUID]: ...
    def account(self, owner: UUID, account_id: UUID) -> AccountState | None: ...  # owner's view
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
        acct = st.account(owner, account_id)
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
            acct_state = self._state.account(owner, acct)
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
        entity: EntityKind | None = None,
        *,
        is_algo_child: bool = False,
    ) -> Reason | None:
        """Second resolution, before each action. None = it passes, else the suppression reason.

        `entity` is the kind of entity the action touches, judged against `applies_to`: an entity
        is always judged. A check that names none (`None`) judges the entity the scope instance
        stands for (`instance_entity`): the tick's gate, which runs before the rule has an action,
        and the re-checks of an action's instance before its dispatch and before its retry. So an
        instance of the rule is never refused for its own `applies_to`, and a named entity
        outside it is (#5817)."""
        if entity is None:
            entity = instance_entity(scope)
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
            if acct not in granted or self._state.account(caller, acct) is None:
                await self._audit(
                    "rule_scope_denied", {"caller": str(caller), "account": str(acct)}
                )
                raise ScopeForbiddenError(ScopeForbiddenError.message)

    def listable_accounts(self, caller: UUID) -> list[UUID]:
        granted = self._state.granted_accounts(caller)
        known = ((a, self._state.account(caller, a)) for a in granted)
        # Not a frozen grant: it is no access (C-12.4); `granted_accounts` keeps it for the runtime.
        return sorted((a for a, s in known if s is not None and not s.frozen), key=str)

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


def instance_entity(scope: RuleScope) -> EntityKind:
    """The entity a scope instance of `scope` stands for, which its `applies_to` names: the one a
    check judges when it resolves no entity of its own (`ScopeResolver.check_action`)."""
    return _INSTANCE_ENTITY[scope.applies_to]


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
        ref = instance_ref(instance_key)
        current = scope() if callable(scope) else scope  # runtime scope change: no restart
        return resolver.check_action(current, owner, environment, ref)

    return gate


def instance_ref(instance_key: str) -> ScopeInstanceRef:
    """The `ScopeInstanceRef` of a scope instance key (`parse_instance`): a ``*`` or empty part is
    None, which the resolver refuses as it refuses no account (fail closed)."""
    sym, acct = parse_instance(instance_key)
    return ScopeInstanceRef(instance_key, sym, None if acct is None else UUID(acct))


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
    entity: EntityKind | None = None,
    is_algo_child: bool = False,
) -> FireOutcome:
    """Action-dispatch gate: the second resolution runs immediately before EVERY action.

    A live trigger for an instance whose scope no longer holds (revoked grant, freeze, closed
    live gate...) is skipped with ``skipped_reason="scope"`` and counted; nothing is dispatched.
    `entity` is the kind the action touches; `None` is the instance's own (`check_action`).
    """
    reason = resolver.check_action(
        scope, owner, environment, instance, entity, is_algo_child=is_algo_child
    )
    if reason is not None:
        return FireOutcome(False, 0, reason, SKIPPED_REASON)
    await dispatch(instance)
    return FireOutcome(True, 1)


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionRequest:
    """One action of one fire on its way from the evaluator to dispatch (24 §11.9)."""

    rule_scope: RuleScope
    owner: UUID  # the rule's owner: the principal an order is sent as (24 §11.5)
    environment: str
    instance: ScopeInstanceRef
    action_type: str
    payload: Action
    #: The stored row's mode when the rule was evaluated: required, with no default.
    mode: EvaluableMode
    rule_id: str
    version: int
    ir_hash: str  # the version's content hash
    run_id: UUID  # the fire's id, shared by its actions
    armed_by: str | None  # the row's; `None` unless the row is armed


ActionSink = Callable[[ActionRequest], Awaitable[None]]
#: An emitter's `emit` (`ScopedActionEmitter.emit`): whether the action passed its re-check.
_Emit = Callable[[ActionRequest], Awaitable[bool]]


class DenialEpisodes:
    """The tick gate's refusals of each (rule, instance), recorded once per episode (#5817).

    A refusal opens an episode, which its first evaluation records; the same refusal on the
    instance's later evaluations holds it: counted as every refusal is, and not recorded again. A
    refusal for another reason, or under another version of the rule, opens a new episode. An
    episode ends when the gate passes the instance, when its rule leaves the work list (`retain`),
    or when its record job is shed, its write fails or its re-check passes (`forget`): the next
    evaluation that holds the refusal then opens one and records it. A skip decided before the gate
    (`BEFORE_SCOPE_GATE`) neither opens nor ends one. One map per running evaluator
    (`RulesService._start_evaluator`), holding the open episodes of the rules on its work list."""

    def __init__(self) -> None:
        #: (rule id, instance) -> (rule version, reason) of its open episode.
        self._open: dict[tuple[str, str], tuple[int, str]] = {}

    def first(self, result: EvaluationResult) -> bool:
        """Whether `result` opens an episode of the gate's refusals, so its refusal is recorded."""
        if result.skipped_reason in BEFORE_SCOPE_GATE:
            return False
        key = (result.rule_id, result.scope_instance)
        if result.scope_refusal is None:
            self._open.pop(key, None)  # the gate passed the instance: its episode ends
            return False
        episode = (result.rule_version, result.scope_refusal)
        if self._open.get(key) == episode:
            return False
        self._open[key] = episode
        return True

    def forget(self, result: EvaluationResult) -> None:
        """Ends the episode `result` opened while it still holds: its records were shed or not
        written, so the next evaluation that holds the refusal records it."""
        key = (result.rule_id, result.scope_instance)
        if self._open.get(key) == (result.rule_version, result.scope_refusal):
            del self._open[key]

    def retain(self, rule_ids: Container[str]) -> None:
        """Ends the episodes of every rule outside `rule_ids`, the work list's: a rule that leaves
        it keeps none, and records its refusal again if it returns."""
        for key in [key for key in self._open if key[0] not in rule_ids]:
            del self._open[key]

    def ending_on_failure(self, result: EvaluationResult, emit: _Emit) -> _Emit:
        """`emit` for the record job of the episode `result` opened: a write that raises, or that
        a timeout or a stop cuts short, ends the episode (`forget`), and so does an emit that
        answers passed, which writes no record."""

        async def emitting(req: ActionRequest) -> bool:
            try:
                passed = await emit(req)
            except BaseException:  # re-raised: the record is not written, so its episode ends
                self.forget(result)
                raise
            if passed:  # its re-check passed: no record is written, so its episode ends
                self.forget(result)
            return passed

        return emitting


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

    async def binding_skipped(self, req: ActionRequest) -> bool:
        """The one record of an episode of evaluations skipped because the instance may not read
        a metric ref the rule names (`BINDING_CAUSE`): its cause and the instance it names, never
        a metric value or another account (so not the rule's scope either). Nothing is sent and
        no action is refused: the rule was not evaluated. Not counted in `denied_total`, which
        counts the gate's refusals."""
        await self._audit(
            "rule_action_scope_denied",
            {
                "caller": str(req.owner),
                "reason": BINDING_CAUSE,
                "rule_id": req.rule_id,
                "account": str(req.instance.account_id),
                "symbol": str(req.instance.symbol),
            },
        )
        return False
