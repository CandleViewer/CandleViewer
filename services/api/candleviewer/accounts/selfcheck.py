"""Stored-key self-check: the verdicts (E27-T03 slice 2a1, #836).

Every usable stored key of the process environment (`active` or `rotating`, not revoked, account
not deleted) goes through the key-import `verify()`, one key at a time off the request path, never
on another environment (C-2.11). Its verdict is acted on (threat model `E27-accounts.md` D7,
SR-E27-18; SR-032):

- pass: a write-ahead `account.tested`, then the verified `api_keys` columns are refreshed. Only
  a recorded pass moves the key's last pass.
- failure: the process read-only gate latches first, for the whole system. A write-ahead
  `account.tested` covers `last_error_*` (the failing rule). The key's status never changes, so
  reads continue.

Audit records hold rule codes and the verified permission facts (SR-031), never an IP or a message
naming one: Viewers read the audit log (C-12.4), while the key's whitelist and the egress IP are
Confidential and keys:read-gated. They stay in the `api_keys` columns and the standing result.

A latch never replaces one already held (another module's, the KEK's, keeps its reason), so a
repeat notifies nobody. Every external await is bounded: a timed-out write is a refused one (the
latch came first). Each key's standing result is kept with its time for display (US-ACCT-003 NFR).

Restarts: the latch and the standing results live in memory, so a restart forgets a failure and
the next check judges the key afresh. `last_error_*` and the verified columns persist; slice 2b
decides how a boot check treats a persisted failure.

Until slice 2a2 (#836), a check without a verdict, an unreadable key list and a refused row raise
out of `run_once()`; 2a2 adds the fail-closed outcomes, the loop and the force-disable. Nothing
runs this before slice 2b.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.models import ExchangeAccount
from candleviewer.accounts.verification import (
    KeyFacts,
    ProbeFacts,
    VerificationPolicy,
    VerificationResult,
    verify,
)
from candleviewer.storage.repositories.accounts import (
    KeySelfCheckStore,
    SelfCheckTargetRow,
    VerifiedKey,
)

#: Ticket performance notes: 12 s overall per key; each signed call has its own 5 s bound.
KEY_DEADLINE_S: Final = 12.0
#: Bound on every other external await: the key list, a client's close, each audit or write.
READ_TIMEOUT_S: Final = 10.0
ACTOR: Final = "system:key-selfcheck"
FAILED: Final = "accounts.key_selfcheck_failed"
_FAILED_TEXT: Final = (
    "A stored API key failed its self-check. "
    "Order entry stays off until a restart passes the check."
)

Outcome = Literal["passed", "failed"]
Step = Callable[[], Awaitable[object]]


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class SelfCheckCalls(Protocol):
    """One key's signed calls on the job's host: `KeyRefused` or `VerificationInconclusive`.

    Both calls draw from the `poll` rate-limit bucket, never `critical`, which stays reserved for
    stops, cancels and flattens (C-12.7, KV-D01, SR-E27-05)."""

    async def key_info(self) -> KeyFacts: ...
    async def probe(self) -> ProbeFacts: ...
    async def aclose(self) -> None: ...


class ReadOnlyLatch(Protocol):
    """The process read-only gate (`net.ReadOnlyGate`): a latch holds until a restart."""

    @property
    def latched_reason_code(self) -> str | None: ...

    def latch(self, *, reason_code: str, reason_text: str) -> None: ...


class AuditEmitter(Protocol):
    """`AuditWriter.emit`: durable when it returns, raises otherwise (C-2.9)."""

    async def emit(self, action: str, **kwargs: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class KeyCheck:
    """One key's standing self-check result (US-ACCT-003 NFR: cached with its time)."""

    key_id: UUID
    account_id: UUID
    checked_at: datetime
    outcome: Outcome
    #: The failing rule; `None` on a pass.
    code: str | None
    result: VerificationResult
    last_pass_at: datetime
    #: The configured egress IP, for copying into the exchange's key whitelist.
    egress_ip: str | None


def _facts(result: VerificationResult, now: datetime) -> dict[str, object]:
    """The verified key-info fields in `permission_snapshot`'s shape (21 §3.2.2)."""
    expiry = result.expires_at
    return {
        "fetched_at": now.isoformat(),
        "uid": result.uid,
        "readOnly": int(result.read_only),
        "permissions": {group: list(rights) for group, rights in result.permissions.items()},
        "ips": list(result.ip_whitelist),
        "expiredAt": None if expiry is None else expiry.isoformat(),
    }


class KeySelfCheck:
    """One pass over the environment's stored keys, acting on each key's verdict."""

    def __init__(
        self,
        store: KeySelfCheckStore,
        calls: Callable[[UUID, str], SelfCheckCalls],
        *,
        gate: ReadOnlyLatch,
        audit: AuditEmitter,
        policy: VerificationPolicy,
        env: str,
        clock: Callable[[], datetime],
        timeout_s: float = READ_TIMEOUT_S,
        key_deadline_s: float = KEY_DEADLINE_S,
    ) -> None:
        self._store, self._calls, self._gate, self._audit = store, calls, gate, audit
        self._policy, self._env, self._clock = policy, env, clock
        self._timeout_s, self._key_deadline_s = timeout_s, key_deadline_s
        self._lock = asyncio.Lock()
        #: The standing result of each key in the last key list read.
        self.results: dict[UUID, KeyCheck] = {}

    def _latch(self) -> None:
        """Latch the gate unless a latch is held already: another module's (the KEK's) keeps its
        published reason and remediation, and a repeat notifies nobody."""
        if self._gate.latched_reason_code is None:
            self._gate.latch(reason_code=FAILED, reason_text=_FAILED_TEXT)

    async def run_once(self) -> None:
        """One pass over every target. Until slice 2a2, a check that reaches no verdict, a key
        list that cannot be read and a row the model refuses raise."""
        async with self._lock:
            async with asyncio.timeout(self._timeout_s):
                targets = await self._store.targets()
            self.results = {t.key_id: c for t in targets if (c := self.results.get(t.key_id))}
            for target in targets:
                await self._check(target, self._clock())

    async def _check(self, target: SelfCheckTargetRow, now: datetime) -> None:
        account = ExchangeAccount.model_validate(target.account, from_attributes=True)
        if account.env.value != self._env:  # the store is env-bound; never cross it (C-2.11)
            logger().error("key_selfcheck_env_mismatch", key_id=str(target.key_id))
            return
        verdict = await self._verify(target, account, now)
        if verdict.passed:
            await self._passed(target, account.id, verdict, now)
        else:
            await self._failed(target, account.id, verdict, now)

    async def _passed(
        self,
        target: SelfCheckTargetRow,
        account_id: UUID,
        verdict: VerificationResult,
        now: datetime,
    ) -> None:
        """A write-ahead `account.tested`, then the verified columns."""
        key, summary = target.key_id, self._summary(verdict, now)
        verified = VerifiedKey(
            _facts(verdict, now),
            verdict.can_trade,
            verdict.read_only,
            verdict.ip_whitelist,
            verdict.expires_at,
            now,
        )
        recorded = await self._write(
            key,
            lambda: self._emit("account.tested", "api_key", key, after_state=summary),
            lambda: self._store.record_pass(key, verified),
        )
        last_pass, egress = now if recorded else target.verified_at, self._policy.egress_ip
        self.results[key] = KeyCheck(
            key, account_id, now, "passed", None, verdict, last_pass, egress
        )

    async def _failed(
        self,
        target: SelfCheckTargetRow,
        account_id: UUID,
        verdict: VerificationResult,
        now: datetime,
    ) -> None:
        """Latch first; then the verdict's write-ahead record and the failing rule."""
        key, first, egress = target.key_id, verdict.failures[0], self._policy.egress_ip
        rule = first.rule.value
        self._latch()
        check = KeyCheck(key, account_id, now, "failed", rule, verdict, target.verified_at, egress)
        self.results[key] = check
        rules = [failure.rule.value for failure in verdict.failures]
        logger().critical("key_selfcheck_failed", key_id=str(key), rules=rules)
        crit, summary = {"severity": "critical", "reason": rule}, self._summary(verdict, now)
        tested = {"outcome": "failure", "after_state": summary, **crit}
        await self._write(
            key,
            lambda: self._emit("account.tested", "api_key", key, **tested),
            lambda: self._store.record_error(key, code=rule, at=now),
        )

    async def _verify(
        self, target: SelfCheckTargetRow, account: ExchangeAccount, now: datetime
    ) -> VerificationResult:
        """The pipeline's verdict within the key's deadline; the key's client is always closed."""
        calls = self._calls(target.key_id, account.exchange_uid)
        try:
            async with asyncio.timeout(self._key_deadline_s):
                return await verify(
                    account,
                    read_only=target.read_only,
                    key_info=calls.key_info,
                    probe=calls.probe,
                    policy=self._policy,
                    now=now,
                )
        finally:
            await self._close(target.key_id, calls)

    async def _close(self, key_id: UUID, calls: SelfCheckCalls) -> None:
        """Close one key's client, bounded. It never raises, so it never changes the verdict."""
        try:
            async with asyncio.timeout(self._timeout_s):
                await calls.aclose()
        except Exception as exc:  # TimeoutError included; cancellation propagates
            logger().warning(
                "key_selfcheck_close_failed", key_id=str(key_id), error=type(exc).__name__
            )

    @staticmethod
    def _summary(result: VerificationResult, now: datetime) -> dict[str, object]:
        """A verdict's audit record (SR-031): the rule and warning codes, and the key-info facts
        when that call returned them (a refusal fetched none), without the whitelist."""
        summary: dict[str, object] = {
            "warnings": [str(w) for w in result.warnings],
            "failures": [str(f.rule) for f in result.failures],
        }
        if result.key_info_ret_code == 0:
            summary |= {k: v for k, v in _facts(result, now).items() if k != "ips"}
            summary |= {"uta": result.unified, "withdraw_enabled": result.withdraw_enabled}
        return summary

    async def _emit(self, action: str, kind: str, object_id: UUID, **fields: Any) -> None:
        await self._audit.emit(
            action,
            actor_label=ACTOR,
            object_kind=kind,
            object_id=str(object_id),
            env=self._env,
            **fields,
        )

    async def _write(self, key_id: UUID, *steps: Step) -> bool:
        """Run the steps in order, each bounded; an audit first is write-ahead (C-2.9), so a
        refusal or a timeout stops the rest. `True` when the last write changed a row; a refusal,
        a timeout or an unchanged row is logged and gives `False`."""
        changed: object = None
        try:
            for step in steps:
                async with asyncio.timeout(self._timeout_s):
                    changed = await step()
        except Exception as exc:  # TimeoutError included; cancellation propagates
            logger().error(
                "key_selfcheck_record_failed", key_id=str(key_id), error=type(exc).__name__
            )
            return False
        if changed is not True:
            logger().warning("key_selfcheck_record_unchanged", key_id=str(key_id))
        return changed is True
