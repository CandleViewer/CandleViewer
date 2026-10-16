"""Stored-key self-check: the boot assertion and the hourly re-check (E27-T03 slice 2a, #836).

Every usable stored key of the process environment (`active` or `rotating`, not revoked, account
not deleted) goes through the key-import `verify()` once before the app serves, then every
`interval_s` (C-2.8; C-12.2: at least hourly), one key at a time off the request path, never on
another environment (C-2.11). Outcomes (threat model `E27-accounts.md` D7, SR-E27-18; SR-032):

- pass: a write-ahead `account.tested`, then the verified `api_keys` columns are refreshed.
- verdict failure: the process read-only gate latches first, for the whole system, until a restart
  whose boot check passes. Then `account.tested` and `last_error_*` record the failing rule, and an
  armed account is force-disabled (`account.disabled_by_policy` carries the reason verbatim). The
  key's status never changes, so reads continue.
- inconclusive (no verdict): nothing is disabled or refreshed; only `last_error_*` is written. A key
  whose last pass is older than `interval_s` plus `FRESHNESS_GRACE` latches the gate as stale.

Keys found while no egress IP is configured are not judged: the gate latches, nothing is disabled.
Each key's latest `KeyCheck` is kept with its time for display (US-ACCT-003 NFR).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.models import ExchangeAccount
from candleviewer.accounts.verification import (
    KeyFacts,
    ProbeFacts,
    VerificationInconclusive,
    VerificationPolicy,
    VerificationResult,
    verify,
)
from candleviewer.observability import spawn
from candleviewer.storage.repositories.accounts import (
    KeySelfCheckStore,
    SelfCheckTargetRow,
    VerifiedKey,
)

#: C-12.2: withdrawal rights and the allowlist are re-checked at least hourly.
MAX_INTERVAL_S: Final = 3600.0
#: SR-E27-18: how long a key stays green past one interval without a fresh pass.
FRESHNESS_GRACE: Final = timedelta(minutes=15)
#: Ticket performance notes: 12 s overall per key; each signed call has its own 5 s bound.
KEY_DEADLINE_S: Final = 12.0
READ_TIMEOUT_S: Final = 10.0
ACTOR: Final = "system:key-selfcheck"
FAILED: Final = "accounts.key_selfcheck_failed"
STALE: Final = "accounts.key_verification_stale"
UNAVAILABLE: Final = "accounts.key_selfcheck_unavailable"
_REASON_TEXT: Final = {
    FAILED: "A stored API key failed its self-check.",
    STALE: "A stored API key has no recent passing self-check.",
    UNAVAILABLE: "The stored API keys could not be checked.",
}
#: `last_error_code` holds a fixed code (a rule, a venue code or a taxonomy code), never text.
_CODE: Final = re.compile(r"[a-z0-9_]{1,40}")

Outcome = Literal["passed", "failed", "inconclusive"]
Step = Callable[[], Awaitable[object]]


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class SelfCheckCalls(Protocol):
    """One key's signed calls on the job's host: `KeyRefused` or `VerificationInconclusive`."""

    async def key_info(self) -> KeyFacts: ...
    async def probe(self) -> ProbeFacts: ...
    async def aclose(self) -> None: ...


class ReadOnlyLatch(Protocol):
    """The process read-only gate (`net.ReadOnlyGate`): a latch holds until a restart."""

    def latch(self, *, reason_code: str, reason_text: str) -> None: ...


class AuditEmitter(Protocol):
    """`AuditWriter.emit`: durable when it returns, raises otherwise (C-2.9)."""

    async def emit(self, action: str, **kwargs: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class KeyCheck:
    """One key's latest self-check (US-ACCT-003 NFR: cached with its time)."""

    key_id: UUID
    account_id: UUID
    checked_at: datetime
    outcome: Outcome
    #: The failing rule (a verdict) or the inconclusive code; `None` on a pass.
    code: str | None
    #: `None` when inconclusive: there was no verdict.
    result: VerificationResult | None
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
    """The boot assertion plus the periodic loop over the environment's stored keys."""

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
        interval_s: float = MAX_INTERVAL_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not 0 < interval_s <= MAX_INTERVAL_S:
            raise ValueError("the key self-check runs at least hourly (C-12.2)")
        self._store, self._calls, self._gate, self._audit = store, calls, gate, audit
        self._policy, self._env, self._clock, self._sleep = policy, env, clock, sleep
        self._interval_s = interval_s
        self._window = timedelta(seconds=interval_s) + FRESHNESS_GRACE
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._booted = False
        #: The latest check of each key in the last key list read.
        self.results: dict[UUID, KeyCheck] = {}

    @property
    def failing(self) -> int:
        return sum(check.outcome == "failed" for check in self.results.values())

    async def start(self) -> None:
        """The boot assertion, awaited so it ends before the app serves, then the loop."""
        if self._task is None:
            await self.run_once()
            self._task = spawn(self._loop(), name="key-selfcheck")
            self._task.add_done_callback(self._loop_ended)

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            await self._sleep(self._interval_s)
            await self.run_once()

    def _loop_ended(self, task: asyncio.Task[None]) -> None:
        """A dead loop re-checks no key, so it fails closed (AGENTS.md §5.2: no silent task)."""
        if not task.cancelled() and task.exception() is not None:
            logger().error("key_selfcheck_loop_died")
            self._latch(UNAVAILABLE)

    def _latch(self, code: str) -> None:
        text = f"{_REASON_TEXT[code]} Order entry stays off until a restart passes the check."
        self._gate.latch(reason_code=code, reason_text=text)

    async def run_once(self) -> None:
        """One pass over every target; only cancellation escapes. A key list that cannot be read
        fails closed at boot, and later once a known key is past its window."""
        async with self._lock:
            booting, self._booted = not self._booted, True
            try:
                async with asyncio.timeout(READ_TIMEOUT_S):
                    targets = await self._store.targets()
            except Exception as exc:  # TimeoutError included; cancellation propagates
                logger().error("key_selfcheck_targets_failed", error=type(exc).__name__)
                now = self._clock()
                if booting or any(
                    now - c.last_pass_at > self._window for c in self.results.values()
                ):
                    self._latch(UNAVAILABLE)
                return
            self.results = {t.key_id: c for t in targets if (c := self.results.get(t.key_id))}
            if targets and self._policy.egress_ip is None:
                logger().critical("key_selfcheck_no_egress_ip", keys=len(targets))
                self._latch(UNAVAILABLE)
                return
            for target in targets:
                try:
                    await self._check(target, self._clock())
                except Exception as exc:  # a row the model refuses: no verdict, fail closed
                    logger().error("key_selfcheck_bad_row", error=type(exc).__name__)
                    self._latch(UNAVAILABLE)

    async def _check(self, target: SelfCheckTargetRow, now: datetime) -> None:
        account = ExchangeAccount.model_validate(target.account, from_attributes=True)
        if account.env.value != self._env:  # the store is env-bound; never cross it (C-2.11)
            logger().error("key_selfcheck_env_mismatch", key_id=str(target.key_id))
            return
        key, egress, last_pass = target.key_id, self._policy.egress_ip, target.verified_at
        verdict = await self._verify(target, account, now)
        if isinstance(verdict, str):
            code = verdict
            check = KeyCheck(key, account.id, now, "inconclusive", code, None, last_pass, egress)
            if now - last_pass > self._window:
                self._latch(STALE)
            await self._record(key, lambda: self._store.record_error(key, code=code, at=now))
        elif verdict.passed:
            check = KeyCheck(key, account.id, now, "passed", None, verdict, now, egress)
            summary, facts = self._summary(verdict, now), _facts(verdict, now)
            verified = VerifiedKey(
                facts,
                verdict.can_trade,
                verdict.read_only,
                verdict.ip_whitelist,
                verdict.expires_at,
                now,
            )
            await self._record(
                key,
                lambda: self._emit("account.tested", "api_key", key, after_state=summary),
                lambda: self._store.record_pass(key, verified),
            )
        else:
            rule, reason = verdict.failures[0].rule.value, verdict.failures[0].message
            check = KeyCheck(key, account.id, now, "failed", rule, verdict, last_pass, egress)
            self._latch(FAILED)
            logger().critical("key_selfcheck_failed", key_id=str(key), rule=rule)
            crit, summary = {"severity": "critical", "reason": rule}, self._summary(verdict, now)
            tested = {"outcome": "failure", "after_state": summary, **crit}
            await self._record(
                key,
                lambda: self._emit("account.tested", "api_key", key, **tested),
                lambda: self._store.record_error(key, code=rule, at=now),
            )
            if account.trading_enabled:
                disabled = {"after_state": {"trading_enabled": False, "reason": reason}, **crit}
                await self._record(
                    key,
                    lambda: self._emit(
                        "account.disabled_by_policy", "exchange_account", account.id, **disabled
                    ),
                    lambda: self._store.disable_trading(account.id),
                )
        self.results[key] = check

    async def _verify(
        self, target: SelfCheckTargetRow, account: ExchangeAccount, now: datetime
    ) -> VerificationResult | str:
        """The pipeline's result, or the code of an inconclusive check (no verdict)."""
        try:
            calls = self._calls(target.key_id, account.exchange_uid)
            try:
                async with asyncio.timeout(KEY_DEADLINE_S):
                    return await verify(
                        account,
                        read_only=target.read_only,
                        key_info=calls.key_info,
                        probe=calls.probe,
                        policy=self._policy,
                        now=now,
                    )
            finally:
                await calls.aclose()
        except VerificationInconclusive as exc:
            return str(exc) if _CODE.fullmatch(str(exc)) else "inconclusive"
        except TimeoutError:
            return "timeout"
        except Exception as exc:  # a signing or programming error is no verdict either
            logger().error(
                "key_selfcheck_error", key_id=str(target.key_id), error=type(exc).__name__
            )
            return "check_error"

    def _summary(self, result: VerificationResult, now: datetime) -> dict[str, object]:
        """A verdict's audit record (SR-031): the verified facts and the fixed messages only."""
        return {
            **_facts(result, now),
            "uta": result.unified,
            "withdraw_enabled": result.withdraw_enabled,
            "egress_ip": self._policy.egress_ip,
            "warnings": [str(w) for w in result.warnings],
            "failures": [{"rule": str(f.rule), "message": f.message} for f in result.failures],
        }

    async def _emit(self, action: str, kind: str, object_id: UUID, **fields: Any) -> None:
        await self._audit.emit(
            action,
            actor_label=ACTOR,
            object_kind=kind,
            object_id=str(object_id),
            env=self._env,
            **fields,
        )

    async def _record(self, key_id: UUID, *steps: Step) -> None:
        """Run the steps in order (the audit first: C-2.9 write-ahead); the first failure stops
        the rest and is logged. The gate latched before any of them where it had to."""
        try:
            for step in steps:
                await step()
        except Exception as exc:  # cancellation propagates
            logger().error(
                "key_selfcheck_record_failed", key_id=str(key_id), error=type(exc).__name__
            )
