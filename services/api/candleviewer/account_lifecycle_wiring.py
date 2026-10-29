"""Composition-root adapter (not a module): the rule disarm that follows an account's disable,
its delete or the revoke of its last signable key (E27-S04 B3b1, #898; 22 `OpenExposure`).

`AccountRuleDisarmer` lists the armed rules that cover the account with the consequence read's
own predicate (`ArmedRules.covering`, the R10 `_ARMED_ON`: every armed rule whose active version
lists the account or lists none), so the disarm acts on the list the dialog showed. Each is
disarmed as `user_cascade_wiring.RuleDisarmAdapter` disarms a disabled user's: through
`RulesManager.set_mode` (B9 `DISARM`, `rule.disarmed` written ahead, C-2.9), under the same
per-rule lock, as the acting Owner (`_acting_owner`), with a key that names the action's
instant. The #898 B3 rulings:

1. It disarms what the predicate lists, global rules included: over-disarming is the fail-closed
   side of a lifecycle event, and the Owner re-arms deliberately. Each disarm record says
   `scope: global` (the rule lists no account, so it stops for every account) or
   `scope: account`.
2. It executes as the Owner, protective, but the record keeps the initiating actor (a Manager
   who disabled the account) as `actor`, with `actor_role` and `executed_as: owner`.
3. A failure never blocks the action it follows, which is already stored: it is logged, paged
   critically (`account.rule_not_disarmed`) and listed as not disarmed. That is safe because the
   key standing's hold already refuses every order on the account (24 §8.4.1), so a rule still
   armed cannot act on it.

Before each disarm, under the rule's lock, it reads the rule's row again and checks that the
active version still covers the account by the same predicate: a rule whose new version left the
account meanwhile is not disarmed (SEC-02), and one gone is skipped. A rule already disarmed is
`set_mode`'s state-based no-op, with no record. Neither its log lines nor its page ever raise
(CR-01): a log line that fails never withholds the page. A cancellation passes through.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal, Protocol

import structlog

from candleviewer.accounts.consequences import ARMED_LISTED
from candleviewer.accounts.lifecycle import (
    AccountLifecycle,
    DisableReason,
    LifecycleStore,
    Standings,
    Streams,
    Subscriptions,
)
from candleviewer.accounts.profile_repository import ArmedRule
from candleviewer.rules.manager import RuleRow, RulesManager, RuleStore
from candleviewer.statechart.plugins import LogPager, Pager
from candleviewer.user_cascade_wiring import DISARMED, RulesNotRunning, _acting_owner, _disarm_lock

__all__ = [
    "DISABLE_REASONS",
    "PAGE_EVENT",
    "AccountRuleDisarmer",
    "CoveringRules",
    "Disarmed",
    "account_disarm_key",
    "coverage",
    "wire_account_lifecycle",
]

#: `cv_account_disabled_total{reason}`'s closed set, every child bound at zero.
DISABLE_REASONS: Final[tuple[DisableReason, ...]] = ("flat", "leave_positions", "flattened", "dead")

#: The page's event (ticket tech notes: "critical when rule disarm fails").
PAGE_EVENT: Final = "account.rule_not_disarmed"
#: The pager's `machine_kind`: the B9 chart whose `DISARM` did not happen.
MACHINE_KIND: Final = "rule_instance"

type Lifecycle = Literal["account_disabled", "account_deleted", "key_revoked"]
type Coverage = Literal["global", "account"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class CoveringRules(Protocol):
    """`ArmedRules.covering` (the R10 predicate), bound in the composition root."""

    async def covering(self, account_id: uuid.UUID, *, limit: int) -> tuple[ArmedRule, ...]: ...


@dataclass(frozen=True, slots=True)
class Disarmed:
    """What one disarm did: the names of the rules it disarmed and of those it did not. `listed`
    is `False` when the armed rules could not be read, or more were armed than one listing
    holds, so the account may hold armed rules it never saw."""

    disarmed: tuple[str, ...]
    failed: tuple[str, ...]
    listed: bool = True


def account_disarm_key(
    lifecycle: Lifecycle, account_id: uuid.UUID, rule_id: str, at: datetime
) -> str:
    """One rule's `Idempotency-Key` in one action on the account: a pure function of the action,
    the account, the rule and the action's instant, as `disarm_key` is in a user's disable.
    `set_mode` replays the first answer for a key it has seen, so without the instant a second
    disable would skip a rule re-armed since the first (CR-02)."""
    stamp = at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{lifecycle}:{account_id}:{uuid.UUID(rule_id)}:{stamp}"


def coverage(row: RuleRow | None, account_id: uuid.UUID) -> Coverage | None:
    """How the row's active version covers the account, by `_ARMED_ON`'s predicate: `global`
    when its scope lists no account (or no list), `account` when it lists this one or an entry
    that is no UUID (counted as covering, fail closed), `None` when it lists only others, has no
    active version or the row is gone."""
    if row is None or row.deleted:
        return None
    version = next((v for v in row.versions if v.id == row.active_version_id), None)
    if version is None:
        return None
    scope = version.ir.get("scope")
    listed = scope.get("account_ids") if isinstance(scope, dict) else None
    if not isinstance(listed, list) or not listed:
        return "global"
    for entry in listed:
        try:
            if not isinstance(entry, str) or uuid.UUID(entry) == account_id:
                return "account"
        except ValueError:
            return "account"
    return None


class AccountRuleDisarmer:
    """Disarms the armed rules covering one account over `RulesManager` (module docstring)."""

    def __init__(
        self,
        rules: CoveringRules,
        store: RuleStore,
        manager: Callable[[], RulesManager | None],
        pager: Pager | None = None,
    ) -> None:
        self._rules, self._store, self._manager = rules, store, manager
        self._pager: Pager = LogPager() if pager is None else pager

    async def disarm(
        self,
        account_id: uuid.UUID,
        *,
        lifecycle: Lifecycle,
        actor: uuid.UUID,
        role: str,
        at: datetime,
    ) -> Disarmed:
        """Disarm every armed rule covering `account_id` after `lifecycle`, which `actor` (in
        `role`) stored at `at`. Never raises but a cancellation: what was not disarmed is logged,
        paged once and named in the answer."""
        try:
            listed = await self._rules.covering(account_id, limit=ARMED_LISTED + 1)
        except Exception as exc:
            self._failed("accounts.rules_not_read", account_id, exc)
            self._page(f"{PAGE_EVENT}: account {account_id}'s armed rules could not be read")
            return Disarmed((), (), listed=False)
        whole = len(listed) <= ARMED_LISTED
        disarmed: list[str] = []
        failed: list[str] = []
        for rule in listed[:ARMED_LISTED]:
            try:
                if await self._one(rule, account_id, lifecycle, actor, role, at):
                    disarmed.append(rule.name)
            except Exception as exc:
                failed.append(rule.name)
                self._failed(PAGE_EVENT, account_id, exc, rule_id=str(rule.rule_id))
        if failed or not whole:
            more = "" if whole else f"; more than {ARMED_LISTED} armed, the rest not listed"
            self._page(f"{PAGE_EVENT}: account {account_id}, {len(failed)} not disarmed{more}")
        return Disarmed(tuple(disarmed), tuple(failed), listed=whole)

    async def _one(
        self,
        rule: ArmedRule,
        account_id: uuid.UUID,
        lifecycle: Lifecycle,
        actor: uuid.UUID,
        role: str,
        at: datetime,
    ) -> bool:
        """One rule, under its lock: `True` once disarmed (or already), `False` when it no
        longer covers the account or is gone (logged, not paged)."""
        rule_id = str(rule.rule_id)
        async with _disarm_lock(rule_id):
            manager = self._manager()
            if manager is None:
                raise RulesNotRunning(rule_id)
            scope = coverage(await self._store.get(rule_id), account_id)
            if scope is None:
                with contextlib.suppress(Exception):
                    _log().info(
                        "accounts.rule_disarm_skipped", account_id=str(account_id), rule_id=rule_id
                    )
                return False
            record = {"scope": scope, "executed_as": "owner", "actor_role": role}
            key = account_disarm_key(lifecycle, account_id, rule_id, at)
            await manager.set_mode(rule_id, DISARMED, _acting_owner(actor), key, record=record)
        return True

    @staticmethod
    def _failed(event: str, account_id: uuid.UUID, exc: Exception, **ids: str) -> None:
        """Log a failure by its error type and code only; a logger that fails is ignored."""
        with contextlib.suppress(Exception):
            _log().error(
                event,
                account_id=str(account_id),
                error=type(exc).__name__,
                code=getattr(exc, "code", None),
                **ids,
            )

    def _page(self, summary: str) -> None:
        """Page critically; a pager that fails is logged, and a logger that fails is ignored."""
        try:
            self._pager.raise_alert("page", summary, machine_kind=MACHINE_KIND)
        except Exception as exc:
            with contextlib.suppress(Exception):
                _log().critical(
                    "accounts.disarm_page_failed", event=PAGE_EVENT, error=type(exc).__name__
                )


class _Counter(Protocol):
    def labels(self, *values: str) -> Any: ...


class _Rules(Protocol):
    """`profiles_wiring.ProfilesWiring`'s armed-rule read."""

    @property
    def rules(self) -> CoveringRules: ...


def wire_account_lifecycle(
    store: LifecycleStore | None,
    profiles: _Rules | None,
    *,
    standings: Standings,
    subscriptions: Subscriptions,
    rule_store: RuleStore,
    manager: Callable[[], RulesManager | None],
    streams: Streams,
    disabled: _Counter,
) -> AccountLifecycle | None:
    """The account lifecycle `updateExchangeAccount` stores through (E27-S04 B3b2, #898), over the
    accounts store and the profile wiring's R10 armed-rule read (`None` without either: the fake
    backend, whose route answers 503; the store is checked first, so a profile wiring is read only
    with it), the key standing, the WS revoke, the rule disarm and the adapter's private-stream
    close; each stored disable is counted by its reason, every child bound at 0."""
    if store is None or profiles is None:
        return None
    rules = profiles.rules
    for reason in DISABLE_REASONS:
        disabled.labels(reason)
    disarmer = AccountRuleDisarmer(rules, rule_store, manager)
    return AccountLifecycle(
        store, standings, subscriptions, disarmer, streams,
        count=lambda reason: disabled.labels(reason).inc(),
    )  # fmt: skip
