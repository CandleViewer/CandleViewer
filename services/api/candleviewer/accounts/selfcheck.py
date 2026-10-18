"""Stored-key self-check: the boot assertion and the hourly re-check (E27-T03 slice 2a, #836).

Every usable stored key of the process environment (`active` or `rotating`, not revoked, account
not deleted) goes through the key-import `verify()` once before the app serves, then every
`interval_s` (C-2.8; C-12.2: at least hourly), one key at a time off the request path, never on
another environment (C-2.11). Outcomes (threat model `E27-accounts.md` D7, SR-E27-18; SR-032):

- pass: a write-ahead `account.tested`, then the verified `api_keys` columns are refreshed. Only
  a recorded pass moves the key's last pass.
- failure: the process read-only gate latches first, for the whole system. A write-ahead
  `account.tested` covers `last_error_*` (the failing rule). The account is force-disabled
  whatever the audit sink does (C-2.8 enforcement before the C-2.9 record, as `secrets`
  degrades), and the rule's code and the time commit with the disarm, which is then owed its
  `account.disabled_by_policy` (the rule; the message stays verbatim on the standing result for
  display). The record follows the conditional update that reports the disarm, and its mark
  follows the record; a refused record is logged critical, stays owed and is re-sent on the next
  pass. The key's status never changes, so reads continue. The record names the disarm's time
  (`disarmed_at`), however late it is sent. `security.key_policy_violation` (`policy_violation`,
  decision 12 on #836) comes last, after the code and the disarm with its record, so it never
  delays the force-disable or withholds the code. A borrow that M2's C-2.8 re-check refuses
  (SR-E27-14) is a `key_withdraw_permission` failure.
- inconclusive (no verdict): logged; nothing is disabled or refreshed. Only a verdict replaces a
  key's standing result: a failure stays in force with its rule in `last_error_*` (the ticket's
  chaos rule); otherwise `last_error_*` takes the code. A key whose last pass is older than
  `interval_s` plus `FRESHNESS_GRACE` latches the gate as stale.

Audit records hold rule codes and the verified permission facts (SR-031), never an IP or a message
naming one, and never an exchange UID: Viewers read the audit log (C-12.4), while the key's
whitelist, the egress IP and the UID are Confidential and keys:read-gated. They stay in the
`api_keys` columns and the standing result (decision 4b on #836).

What cannot be checked latches the gate too and disables nothing: keys found while no egress IP is
configured, a key list that cannot be read (at boot, or once a known key is past its window), a
row the model refuses or of another environment, a key's check past its overall deadline and a
dead loop. A latch never replaces a more specific one (another module's, or this job's failure by
a weaker code), so a repeat notifies nobody. Every external await is bounded: a timed-out write is
a refused one (any latch due came first). Each key's standing result is kept with its time for
display (US-ACCT-003 NFR).

Restarts: the latch and the standing results live in memory. A rule code found in
`last_error_code` for a key the job holds no result for is a standing failure (decision 3 on #836):
a check with no verdict keeps it in force, logs it critical and latches again, and only a pass,
whose write clears `last_error_*`, ends it. The code follows its write-ahead `account.tested`, so
one double fault remains: a failure whose record or code write was refused, then a restart whose
boot check has no verdict, latches nothing for that key until its last pass leaves the window (at
most one interval plus 15 minutes). The account stays disarmed only if its disarm committed. The
disarm waits for that record and that code (at most two bounds, one when only the audit sink
hangs), so a stop or the boot deadline inside that wait, or a store fault that refuses the disarm
too, leaves the account armed until the window ends. The verified columns and a committed disarm
(`trading_enabled` false, with its rule code and time) persist too. A disarm whose record
is not marked written is owed in the store, so the boot pass, like every pass, sends it before it
checks a key (decision 5 on #836). The audit sink cannot dedup it (`AuditWriter.emit` mints a fresh
`record_id`), so it can be written twice, never zero times, in two windows: a crash between the
record and its mark, and an emit cut by its bound once the writer has started the append (the
writer keeps that append; the job counts the emit refused, so the record stays owed). A record
sent but not yet marked is kept in memory, so a failed mark is retried alone.

Freshness (SR-E27-18): `is_fresh` is the one window rule, here and at order admission (#837 W3).
`watch()` is the watchdog. The accounts row-gauge loop, a task this job does not own, runs it each
minute, so a job that stalls or dies still latches `STALE` once a key's last pass is past its
window; if that loop dies, `watch_ended()` latches `UNAVAILABLE`. It counts missed runs and
publishes the oldest key's age and the soonest expiry. `/readyz` is anonymous (SR-010), so it gets
the key count and the oldest age only (`ages()`, no key id); each key's age goes to the debug log,
never to a series labelled by key (decision 13 on #836). `key_selfcheck_wiring` builds the job on
the real backend.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.errors import WithdrawPermissionError
from candleviewer.accounts.models import ExchangeAccount
from candleviewer.accounts.verification import (
    KeyFacts,
    ProbeFacts,
    Rule,
    VerificationFailure,
    VerificationInconclusive,
    VerificationPolicy,
    VerificationResult,
    verify,
)
from candleviewer.observability import spawn
from candleviewer.storage.repositories.accounts import (
    KeySelfCheckStore,
    PolicyDisarm,
    SelfCheckTargetRow,
    VerifiedKey,
)

if TYPE_CHECKING:
    from candleviewer.observability.metrics import Metrics

#: C-12.2: withdrawal rights and the allowlist are re-checked at least hourly.
MAX_INTERVAL_S: Final = 3600.0
#: Each pass audits and signs for every key: a shorter cadence floods both, so it is refused.
MIN_INTERVAL_S: Final = 60.0
#: SR-E27-18: how long a key stays green past one interval without a fresh pass.
FRESHNESS_GRACE: Final = timedelta(minutes=15)
#: Ticket performance notes: 12 s overall per key; each signed call has its own 5 s bound.
KEY_DEADLINE_S: Final = 12.0
#: Bound on every other external await: the key list, a client's close, each audit or write.
READ_TIMEOUT_S: Final = 10.0
#: One key's whole check: `verify()`, the close and at most six audit or store steps (the last is
#: the policy violation's record, after the disarm's record and its mark), plus one step of
#: margin. The deadline derives from the wired bounds, so it cuts only an unbounded await.
CHECK_STEPS: Final = 8
#: The boot assertion as a whole: past it the job fails closed and start-up goes on (#836). It
#: is fixed, not scaled by the key count, because the API serves nothing, `/healthz` included,
#: until it ends (the compose healthcheck reports unhealthy after about 100 s). At SCR-126's 3 s
#: round trip a healthy pass of up to about 19 keys fits (20 take exactly the bound); in an
#: outage each key waits out a 5 s call bound, so past about ten keys an outage at start-up
#: latches `UNAVAILABLE` until a restart (runbook). An IP-level rate-limit hold costs no wait:
#: the adapter refuses each call at once.
BOOT_DEADLINE_S: Final = 60.0
ACTOR: Final = "system:key-selfcheck"
DISABLED_BY_POLICY: Final = "account.disabled_by_policy"
FAILED: Final = "accounts.key_selfcheck_failed"
STALE: Final = "accounts.key_verification_stale"
UNAVAILABLE: Final = "accounts.key_selfcheck_unavailable"
_REASON_TEXT: Final = {
    FAILED: "A stored API key failed its self-check.",
    STALE: "A stored API key has no recent passing self-check.",
    UNAVAILABLE: "The stored API keys could not be checked.",
}
#: Latch precedence: a failure replaces a weaker latch of this job's. Another module's latch (the
#: KEK's: no key can be verified without it) is never replaced.
_RANK: Final = {UNAVAILABLE: 0, STALE: 0, FAILED: 1}
#: `last_error_code` holds a fixed code, never text: a rule, a `KeyProbeError` name or a job code.
_CODE: Final = re.compile(r"[a-z0-9_]{1,40}")
#: A verdict's codes: one found in `last_error_code` is a standing failure (decision 3 on #836).
_RULES: Final = frozenset(rule.value for rule in Rule)
POLICY_VIOLATION: Final = "security.key_policy_violation"
#: A disarm's code when a rule code would not fit `ea_disarm_code_fmt` (`_CODE`), so that CHECK
#: never refuses a force-disable (C-2.8).
_DISARM_FALLBACK: Final = "key_policy_violation"
#: M2's borrow re-check refused the stored row (SR-E27-14): a verdict, never `check_error`.
_ROW_REFUSED: Final = VerificationResult(
    False,
    failures=(
        VerificationFailure(
            Rule.WITHDRAW_PERMISSION, "the stored permission record fails the withdrawal check"
        ),
    ),
)

Outcome = Literal["passed", "failed", "inconclusive"]
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
    #: The failing rule (a verdict) or the inconclusive code; `None` on a pass.
    code: str | None
    #: `None` when this process holds no verdict: an inconclusive check, or a failure restored from
    #: its stored rule code after a restart (outcome `failed`, decision 3).
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
        "uta": int(result.uta),
        "permissions": {group: list(rights) for group, rights in result.permissions.items()},
        "ips": list(result.ip_whitelist),
        "expiredAt": None if expiry is None else expiry.isoformat(),
    }


def is_fresh(last_pass_at: datetime, *, now: datetime, interval_s: float) -> bool:
    """SR-E27-18: a key is green only while its last pass is at most one self-check interval plus
    `FRESHNESS_GRACE` old; an inconclusive check never moves it."""
    return now - last_pass_at <= timedelta(seconds=interval_s) + FRESHNESS_GRACE


def policy_violation(
    verdict: VerificationResult, *, key_id: UUID | None, account_id: UUID
) -> dict[str, object]:
    """`security.key_policy_violation {rule, key_id}`'s fields for a failing verdict (decision 12
    on #836): its first rule, and the account standing in for a key that is not stored (a refused
    import). Critical when the key can move funds (C-2.8): a withdraw or transfer right, or a fiat
    or card right (`withdraw_enabled`, as `account.tested` shows it). Never key material."""
    rule = verdict.failures[0].rule
    if key_id is not None:
        kind, field, subject = "api_key", "key_id", key_id
    else:
        kind, field, subject = "exchange_account", "account_id", account_id
    funds = rule is Rule.WITHDRAW_PERMISSION or verdict.withdraw_enabled
    return {
        "object_kind": kind,
        "object_id": str(subject),
        "outcome": "denied",
        "severity": "critical" if funds else "error",
        "reason": rule.value,
        "after_state": {"rule": rule.value, field: str(subject)},
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
        metrics: Metrics,
        interval_s: float = MAX_INTERVAL_S,
        timeout_s: float = READ_TIMEOUT_S,
        key_deadline_s: float = KEY_DEADLINE_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        boot_deadline_s: float = BOOT_DEADLINE_S,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not interval_s <= MAX_INTERVAL_S:
            raise ValueError("the key self-check runs at least hourly (C-12.2)")
        if not interval_s >= MIN_INTERVAL_S:
            raise ValueError("the key self-check runs at most once a minute")
        self._store, self._calls, self._gate, self._audit = store, calls, gate, audit
        self._policy, self._env, self._clock, self._sleep = policy, env, clock, sleep
        self._interval_s, self._deadline_s = interval_s, key_deadline_s + CHECK_STEPS * timeout_s
        self._timeout_s, self._key_deadline_s = timeout_s, key_deadline_s
        self._boot_deadline_s = boot_deadline_s
        self._m, self._monotonic = metrics, monotonic
        #: The watchdog's inputs: when the last run began, the runs since counted as missed, and
        #: the soonest expiry in the last key list read.
        self._ran_at: datetime | None = None
        self._missed = 0
        self._expiry: datetime | None = None
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._booted = False
        #: Disarms whose record was written but not marked, by account: only the mark is retried.
        self._unmarked: dict[UUID, datetime] = {}
        #: The standing result of each key in the last key list read.
        self.results: dict[UUID, KeyCheck] = {}

    @property
    def failing(self) -> int:
        # A snapshot: `/readyz` counts this on a worker thread while the loop stores results,
        # and iterating the live dict could raise "dictionary changed size during iteration".
        return sum(check.outcome == "failed" for check in tuple(self.results.values()))

    @property
    def fault(self) -> str | None:
        """Why the job reads DEGRADED, `None` while it does not: a key fails, the job holds a
        fail-closed latch (its own, not another module's) or its loop has ended."""
        if failing := self.failing:
            return f"{failing} stored key(s) fail the self-check"
        if (held := self._gate.latched_reason_code) in _RANK:
            return f"the stored-key self-check holds the read-only latch {held}"
        if self._task is not None and self._task.done():
            return "the stored-key self-check loop ended"
        return None

    def watch(self) -> None:
        """The freshness watchdog (SR-E27-18), run each minute by the accounts row-gauge loop:
        `STALE` once a known key's last pass is past its window, one missed run per interval
        past `FRESHNESS_GRACE` with no run begun, the oldest key's age and the soonest expiry."""
        now, checks, interval = self._clock(), tuple(self.results.values()), self._interval_s
        stale = [c for c in checks if not is_fresh(c.last_pass_at, now=now, interval_s=interval)]
        if stale and self._latch(STALE):
            logger().critical("key_selfcheck_stale", key_ids=[str(c.key_id) for c in stale])
        ages = {str(c.key_id): (now - c.last_pass_at).total_seconds() for c in checks}
        logger().debug("key_selfcheck_ages", ages=ages)  # per key: kept off the anonymous /readyz
        self._m.get("cv_key_verification_age_seconds").child().set(max(ages.values(), default=0.0))
        expiry = math.inf if self._expiry is None else (self._expiry - now).total_seconds()
        self._m.get("cv_key_soonest_expiry_seconds").child().set(expiry)
        if self._ran_at is not None:
            due = (now - self._ran_at - FRESHNESS_GRACE) // timedelta(seconds=interval)
            if due > self._missed:
                logger().error("key_selfcheck_run_missed", missed=due)
                self._m.get("cv_key_selfcheck_missed_runs_total").child().inc(due - self._missed)
                self._missed = due

    def watch_ended(self) -> None:
        """The loop that runs `watch()` died: no watchdog vouches for freshness, so this fails
        closed as the job's own loop does (AGENTS.md §5.2: no silent task)."""
        logger().error("key_selfcheck_watchdog_died")
        self._latch(UNAVAILABLE)

    def ages(self) -> str:
        """For the anonymous `/readyz` (SR-010): how many keys were checked and the oldest last
        pass, never a key id or a per-key list (key metadata is keys:read, 04 §7.2.2 row 42)."""
        now, checks = self._clock(), tuple(self.results.values())
        if not checks:
            return ""
        oldest = max((now - c.last_pass_at).total_seconds() for c in checks)
        return f"{len(checks)} key(s) checked, oldest last pass {oldest:.0f}s ago"

    async def start(self) -> None:
        """The boot assertion, awaited so it ends before the app serves, then the loop. The whole
        boot pass is bounded: past `boot_deadline_s` the job fails closed and start-up goes on."""
        if self._task is None:
            try:
                async with asyncio.timeout(self._boot_deadline_s):
                    await self.run_once()
            except TimeoutError:
                logger().critical("key_selfcheck_boot_unfinished")
                self._latch(UNAVAILABLE)
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

    def _latch(self, code: str) -> bool:
        """Latch the gate unless it holds an equal or more specific latch already: the published
        reason (and its remediation) is never buried, and a repeat notifies nobody."""
        held = self._gate.latched_reason_code
        if held is not None and (held not in _RANK or _RANK[held] >= _RANK[code]):
            return False
        text = f"{_REASON_TEXT[code]} Order entry stays off until a restart passes the check."
        self._gate.latch(reason_code=code, reason_text=text)
        return True

    async def run_once(self) -> None:
        """One pass over every target; only cancellation escapes. A key list that cannot be read
        fails closed at boot, and later once a known key is past its window."""
        async with self._lock:
            booting, self._booted = not self._booted, True
            self._ran_at, self._missed = self._clock(), 0
            await self._settle_owed()
            try:
                async with asyncio.timeout(self._timeout_s):
                    targets = await self._store.targets()
            except Exception as exc:  # TimeoutError included; cancellation propagates
                logger().error("key_selfcheck_targets_failed", error=type(exc).__name__)
                now, interval = self._clock(), self._interval_s
                if booting or any(
                    not is_fresh(c.last_pass_at, now=now, interval_s=interval)
                    for c in self.results.values()
                ):
                    self._latch(UNAVAILABLE)
                self._ran("error")
                return
            self.results = {t.key_id: c for t in targets if (c := self.results.get(t.key_id))}
            self._expiry = min(
                (t.expires_at for t in targets if t.expires_at is not None), default=None
            )
            if not targets:
                logger().warning("key_selfcheck_no_keys", env=self._env)
            elif self._policy.egress_ip is None:
                logger().critical("key_selfcheck_no_egress_ip", keys=len(targets))
                self._latch(UNAVAILABLE)
                self._ran("error")
                return
            outcomes: list[Outcome | None] = []
            for target in targets:
                try:
                    async with asyncio.timeout(self._deadline_s):
                        outcomes.append(await self._check(target, self._clock()))
                except Exception as exc:  # a row the model refuses, or a check past its deadline
                    logger().error(
                        "key_selfcheck_unfinished",
                        key_id=str(target.key_id),
                        error=type(exc).__name__,
                    )
                    self._latch(UNAVAILABLE)
                    outcomes.append(None)
            if None in outcomes:
                self._ran("error")
            else:
                self._ran(next((o for o in ("failed", "inconclusive") if o in outcomes), "passed"))

    def _ran(self, result: str) -> None:
        """Count the run, and publish each rule's failing keys (every rule, 0 when none)."""
        self._m.get("cv_key_selfcheck_runs_total").labels(result).inc()
        codes = [c.code for c in tuple(self.results.values()) if c.outcome == "failed"]
        for rule in Rule:
            self._m.get("cv_keys_failing_policy").labels(rule.value).set(codes.count(rule.value))

    async def _check(self, target: SelfCheckTargetRow, now: datetime) -> Outcome | None:
        account = ExchangeAccount.model_validate(target.account, from_attributes=True)
        if account.env.value != self._env:  # the store is env-bound: a refused row (C-2.11)
            logger().error("key_selfcheck_env_mismatch", key_id=str(target.key_id))
            self._latch(UNAVAILABLE)
            return None
        started = self._monotonic()
        verdict = await self._verify(target, account, now)
        elapsed, rule = self._monotonic() - started, "none"
        outcome: Outcome
        if isinstance(verdict, str):
            outcome = "inconclusive"
            await self._inconclusive(target, account.id, verdict, now)
        elif verdict.passed:
            outcome = "passed"
            await self._passed(target, account.id, verdict, now)
        else:
            outcome, rule = "failed", verdict.failures[0].rule.value
            await self._failed(target, account.id, verdict, now)
        # Counted once the verdict is handled: a metrics fault never withholds a record or disarm.
        self._m.get("cv_key_verification_seconds").child().observe(elapsed)
        self._m.get("cv_key_verification_total").labels(outcome, rule).inc()
        return outcome

    async def _inconclusive(
        self, target: SelfCheckTargetRow, account_id: UUID, code: str, now: datetime
    ) -> None:
        """No verdict: nothing is disabled or refreshed, and the standing result stays. A rule
        code the store holds is a standing failure for a key with no result (decision 3)."""
        key, last_pass, egress = target.key_id, target.verified_at, self._policy.egress_ip
        logger().warning("key_selfcheck_inconclusive", key_id=str(key), code=code)
        prior = self.results.get(key)
        if prior is None and target.last_error_code in _RULES:
            rule = target.last_error_code
            prior = KeyCheck(key, account_id, now, "failed", rule, None, last_pass, egress)
            self.results[key] = prior
            logger().critical("key_selfcheck_failed", key_id=str(key), rules=[rule], restored=True)
        if prior is not None and prior.outcome == "failed":
            self._latch(FAILED)  # a failure stays in force, its rule on display, across restarts
            return
        if not is_fresh(last_pass, now=now, interval_s=self._interval_s):
            self._latch(STALE)
        if prior is None or prior.outcome == "inconclusive":
            check = KeyCheck(key, account_id, now, "inconclusive", code, None, last_pass, egress)
            self.results[key] = check
        await self._write(key, lambda: self._store.record_error(key, code=code, at=now))

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
        """Latch first; then the verdict's record and its rule code, the force-disable whatever
        they did, and the policy-violation record last (decision 2 on #836: enforcement first)."""
        key, rule, egress = target.key_id, verdict.failures[0].rule.value, self._policy.egress_ip
        self._latch(FAILED)
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
        await self._disarm(PolicyDisarm(account_id, rule, now))
        await self._violation(key, account_id, verdict)

    async def _violation(self, key: UUID, account_id: UUID, verdict: VerificationResult) -> None:
        """`security.key_policy_violation`, after the rule code and the disarm: a refused or
        timed-out record is logged, never raised, so it delays and withholds nothing (decision 12
        on #836)."""
        record = policy_violation(verdict, key_id=key, account_id=account_id)
        try:
            async with asyncio.timeout(self._timeout_s):
                await self._audit.emit(POLICY_VIOLATION, actor_label=ACTOR, env=self._env, **record)
        except Exception as exc:  # TimeoutError included; cancellation propagates
            logger().error("key_selfcheck_record_failed", key_id=str(key), error=type(exc).__name__)

    async def _disarm(self, disarm: PolicyDisarm) -> None:
        """The force-disable runs whatever the audit sink does (C-2.8 enforcement first, decision
        2 on #836), its rule code and time in the same conditional update. Its record follows
        once that update reports a disarm. A disable that times out or raises may have applied
        (outcome unknown): if it did, its record is owed in the store and the next pass sends it."""
        if not _CODE.fullmatch(disarm.code):  # `ea_disarm_code_fmt` would refuse the disarm too
            logger().error("key_selfcheck_disarm_code_replaced", account_id=str(disarm.account_id))
            disarm = PolicyDisarm(disarm.account_id, _DISARM_FALLBACK, disarm.at)
        try:
            async with asyncio.timeout(self._timeout_s):
                disarmed = await self._store.disable_trading(
                    disarm.account_id, code=disarm.code, at=disarm.at
                )
        except Exception as exc:  # TimeoutError included; cancellation propagates
            logger().critical(
                "key_selfcheck_disable_failed",
                account_id=str(disarm.account_id),
                error=type(exc).__name__,
                outcome_unknown=True,
            )
            return
        if disarmed:
            await self._settle(disarm)

    async def _settle_owed(self) -> None:
        """Send the record of every disarm still owed in the store: after a restart, a refused
        record, or a disable whose outcome was unknown. An unreadable list waits for the next
        pass."""
        try:
            async with asyncio.timeout(self._timeout_s):
                owed = await self._store.owed_disarms()
        except Exception as exc:  # TimeoutError included; cancellation propagates
            logger().error("key_selfcheck_owed_unread", error=type(exc).__name__)
            return
        for disarm in owed:
            await self._settle(disarm)

    async def _settle(self, disarm: PolicyDisarm) -> None:
        """Send one disarm's `account.disabled_by_policy`, then mark it written. A refused record
        stays owed (logged critical); a written one whose mark failed is not sent again."""
        account_id = disarm.account_id
        if self._unmarked.get(account_id) != disarm.at:
            record = {
                "before_state": {"trading_enabled": True},
                "after_state": {"trading_enabled": False, "disarmed_at": disarm.at.isoformat()},
                "severity": "critical",
                "reason": disarm.code,
            }
            try:
                async with asyncio.timeout(self._timeout_s):
                    await self._emit(DISABLED_BY_POLICY, "exchange_account", account_id, **record)
            except Exception as exc:  # TimeoutError included; cancellation propagates
                logger().critical(
                    "key_selfcheck_disable_unaudited",
                    account_id=str(account_id),
                    error=type(exc).__name__,
                )
                return
            self._unmarked[account_id] = disarm.at
        try:
            async with asyncio.timeout(self._timeout_s):
                marked = await self._store.mark_disarm_audited(disarm, at=self._clock())
        except Exception as exc:  # TimeoutError included; cancellation propagates
            logger().error(
                "key_selfcheck_disable_unmarked",
                account_id=str(account_id),
                error=type(exc).__name__,
            )
            return
        if not marked:  # no longer owed as read: a later disarm, or a mismatch that re-sends it
            logger().error("key_selfcheck_disable_mark_unchanged", account_id=str(account_id))
        del self._unmarked[account_id]

    async def _verify(
        self, target: SelfCheckTargetRow, account: ExchangeAccount, now: datetime
    ) -> VerificationResult | str:
        """The pipeline's result within the key's deadline, or the code of an inconclusive check
        (no verdict); the key's client is always closed."""
        try:
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
        except VerificationInconclusive as exc:
            return str(exc) if _CODE.fullmatch(str(exc)) else "inconclusive"
        except WithdrawPermissionError:  # M2's borrow re-check refused the stored row (SR-E27-14)
            return _ROW_REFUSED
        except TimeoutError:
            return "timeout"
        except Exception as exc:  # a signing or programming error is no verdict either
            logger().error(
                "key_selfcheck_error", key_id=str(target.key_id), error=type(exc).__name__
            )
            return "check_error"

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
        when that call returned them (a refusal fetched none), without the whitelist or the
        exchange UID."""
        summary: dict[str, object] = {
            "warnings": [str(w) for w in result.warnings],
            "failures": [str(f.rule) for f in result.failures],
        }
        if result.key_info_ret_code == 0:
            hidden = {"ips", "uid", "uta"}
            summary |= {k: v for k, v in _facts(result, now).items() if k not in hidden}
            summary |= {"uta": result.uta, "withdraw_enabled": result.withdraw_enabled}
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
