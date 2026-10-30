"""B19's port into the pass (E29-T06 #914 PR 2a; 24-internal-schemas.md Sec.8.5's phase table;
`statechart/bindings/b19_reconciliation.JobPorts`). Plain code: B19's services and actions call it
by account id, and it holds what one account's pass carries from one phase to the next (its reads,
then its plan, then its report) in memory, one pass per account, as B19 runs one at a time.

* **fetch** (step 1) computes the window (`gap_window`: the stream's last message and the stored
  watermark, BQ-10) and fetches. Any failure of it, whatever its cause, is a failed fetch: the plain
  tracker judges it against the stale window and, once it is spent, sets the account's standing
  before it raises `FetchFailed`, the event that tells B19 (C-2.21). So the job's own faults
  escalate to `stale_lockout` rather than retrying forever (INV-B19-a).
* **diff** and **remediate** run the pass's phases on what the fetch read.
* **report** freezes the report, writes it as its `oms.reconcile` record (`stage: finished`, 24
  Sec.15.5) ahead of everything that follows from it (C-2.9), stores the watermark a clean enough
  pass earns (the upper bound step 1 read to, `watermark_us`), and computes the pass's notices
  (`pass_notices`). A record or a watermark that cannot be written is logged and paged and ends
  the pass all the same; the next pass reports again.
* The effects: `lock` sets the standing again (idempotent) as B19 records the lock, `unlock` clears
  it only as B19's `OPERATOR_RESOLVED` arm ends (BQ-5), `stale` pages the Owner and hands on
  `oms.account_stale`, the metrics are counted, and a retry is asked of the driver's host timer.

Unwired: nothing composes it yet (PR 2b). The notices are handed to `ReconcileNotices`, which the
wiring binds to the `system` topic; publishing is not this module's.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.domain.primitives import AccountId
from candleviewer.statechart.bindings.b19_reconciliation import FetchFailed

from .reconcile_report import (
    STALE_NOTICE,
    TRIGGERS,
    Notice,
    NoticeReason,
    NoticeSeverity,
    ReconcileMetrics,
    ReconcileReport,
    ReportDraft,
    Trigger,
    audit_state,
    pass_notices,
    watermark_us,
)
from .reconcile_standing import FailureTracker, ReconcileStanding
from .reconciler import Fetched, Pager, Plan, Reconciler, gap_window

__all__ = [
    "RECORD_TIMEOUT_S",
    "ReconcileNotices",
    "ReconcilePhases",
    "ReportRecords",
    "RetryTimer",
    "StreamMarks",
    "Watermarks",
]

#: Each record or watermark write, and the watermark's read (C-2.18).
RECORD_TIMEOUT_S: Final = 5.0
_KIND: Final = "oms.reconcile_job"
#: Each alert's summary: fixed text that names no account or value (C-12.6).
_ALERTS: Final[Mapping[str, str]] = {
    "stale": "Reconciliation has failed for 2 minutes: order entry on an account is refused.",
    "divergent": "Reconciliation left items for the Owner on an account.",
    "remediation_failed": "A reconciliation pass's remediation failed as a whole.",
    "kill_received": "A KILL reached a reconciliation job, which never takes one.",
    "report_unwritten": "A reconciliation report could not be written.",
}


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class StreamMarks(Protocol):
    """The private-stream consumer's last message of the account, in memory (24 Sec.8.12)."""

    def last_message_us(self, account_id: AccountId) -> int | None: ...


class Watermarks(Protocol):
    """`exchange_accounts.last_reconciled_at` (21 Sec.3.2.1), the stored half of `gap_from`."""

    async def last_reconciled_us(self, account_id: AccountId) -> int | None: ...

    async def advance(self, account_id: AccountId, to_us: int) -> None: ...


class ReportRecords(Protocol):
    """The pass's `oms.reconcile` record (`stage: finished`), as `system:oms` (24 Sec.15.5)."""

    async def finished(
        self, account_id: AccountId, *, pass_id: str, state: Mapping[str, object]
    ) -> None: ...


class ReconcileNotices(Protocol):
    """Hands one `account_notice` row on (23 Sec.15.9); the wiring publishes it (PR 2b)."""

    def publish(self, account_id: AccountId, notice: Notice) -> None: ...


class RetryTimer(Protocol):
    """The driver's host timer, which sends `RETRY_DUE` (24 Sec.8.5; A2: never an `after:`)."""

    def retry(self, account_id: AccountId, *, attempt: int) -> None: ...


@dataclass
class _Pass:
    """What one account's pass carries between its phases."""

    fetched: Fetched
    plan: Plan | None = None


def _account(text: str) -> AccountId:
    return AccountId(UUID(text))


def _trigger(text: str) -> Trigger:
    for trigger in TRIGGERS:
        if trigger == text:
            return trigger
    return "periodic"


async def _bounded[T](call: Awaitable[T]) -> T:
    async with asyncio.timeout(RECORD_TIMEOUT_S):
        return await call


class ReconcilePhases:
    """`b19_reconciliation.JobPorts` (module docstring): one for the process, every account's."""

    def __init__(
        self,
        reconciler: Reconciler,
        *,
        standing: ReconcileStanding,
        tracker: FailureTracker,
        marks: StreamMarks,
        watermarks: Watermarks,
        records: ReportRecords,
        notices: ReconcileNotices,
        retries: RetryTimer,
        metrics: ReconcileMetrics,
        pager: Pager,
        now_us: Callable[[], int],
    ) -> None:
        self._r, self._standing, self._tracker = reconciler, standing, tracker
        self._marks, self._watermarks, self._records = marks, watermarks, records
        self._notices, self._retries, self._metrics = notices, retries, metrics
        self._pager, self._now = pager, now_us
        self._passes: dict[AccountId, _Pass] = {}
        self._reports: dict[AccountId, ReconcileReport] = {}
        self._failures: dict[AccountId, tuple[str, str]] = {}

    def now_us(self) -> int:
        return self._now()

    # --- The phases (B19's services and `persist_report`) ---------------------------------------

    async def fetch(self, account_id: str, *, pass_id: str, trigger: str) -> Mapping[str, Any]:
        """Step 1; any failure is a failed fetch, judged by the tracker, the standing set before
        `FetchFailed` tells B19 when the stale window is spent (C-2.21, INV-B19-a)."""
        now = self._now()
        try:
            account = _account(account_id)
        except ValueError:  # no account to judge or to lock: the job is unusable, lock at once
            raise FetchFailed(
                "ValueError", failing_since_us=now, failed_at_us=now, window_us=0
            ) from None
        self._passes.pop(account, None)
        self._failures.pop(account, None)
        try:
            stored = await _bounded(self._watermarks.last_reconciled_us(account))
            window = gap_window(
                last_message_us=self._marks.last_message_us(account),
                last_reconciled_us=stored,
                now_us=now,
            )
            fetched = await self._r.fetch(
                account, pass_id=pass_id, trigger=_trigger(trigger), window=window
            )
        except Exception as exc:  # never a CancelledError
            kind = getattr(exc, "kind", None) or type(exc).__name__
            failure = self._tracker.failed(account, self._now())
            if failure.exhausted:
                self._standing.mark_stale(account)  # before B19 is told (C-2.21)
            _log().warning(
                "reconcile_fetch_failed", account_id=account_id, pass_id=pass_id, failure=kind,
                exhausted=failure.exhausted,
            )  # fmt: skip
            raise FetchFailed(
                str(kind),
                failing_since_us=failure.failing_since_us,
                failed_at_us=failure.failed_at_us,
                window_us=failure.window_us,
            ) from None
        self._passes[account] = _Pass(fetched)
        return {
            "orders": len(fetched.remote_open),
            "positions": len(fetched.positions),
            "executions": len(fetched.executions),
        }

    async def diff(self, account_id: str, *, pass_id: str) -> Mapping[str, Any]:
        state = self._pass(account_id, pass_id)
        try:
            state.plan = await self._r.diff(state.fetched)
        except Exception as exc:
            self._failures[state.fetched.account.account_id] = ("2", type(exc).__name__)
            raise
        return {"divergences": state.plan.divergences, "kinds": state.plan.kinds()}

    async def remediate(self, account_id: str, *, pass_id: str) -> Mapping[str, Any]:
        state = self._pass(account_id, pass_id)
        if state.plan is None:
            raise LookupError("the pass has no plan to apply")
        try:
            await self._r.remediate(state.plan)
        except Exception as exc:
            self._failures[state.fetched.account.account_id] = ("5", type(exc).__name__)
            raise
        return {"applied": state.plan.divergences, "kinds": state.plan.kinds()}

    async def report(
        self,
        account_id: str,
        *,
        pass_id: str,
        trigger: str,
        episode_open: bool,
        failure: str | None,
    ) -> Mapping[str, Any]:
        """The pass's report and its record, written ahead of its notices (C-2.9); never raises."""
        account = _account(account_id)
        report = self._freeze(account, pass_id, trigger, failure)
        self._reports[account] = report
        try:
            await _bounded(
                self._records.finished(account, pass_id=pass_id, state=audit_state(report))
            )
        except Exception as exc:  # the pass ends all the same; the next one reports again
            _log().error(
                "reconcile_report_unwritten", account_id=account_id, failure=type(exc).__name__
            )
            self._pager.raise_alert("page", _ALERTS["report_unwritten"], machine_kind=_KIND)
        mark = watermark_us(report)
        if mark is not None:
            try:
                await _bounded(self._watermarks.advance(account, mark))
            except Exception as exc:  # the window is read again next pass: never a gap
                _log().error(
                    "reconcile_watermark_unwritten",
                    account_id=account_id,
                    failure=type(exc).__name__,
                )
        notices = pass_notices(report, episode_open=episode_open)
        return {
            "unresolved": report.owner_items,
            "result": report.result,
            "notices": [[n.reason, n.severity] for n in notices.notices],
            "episode_open": notices.episode_open,
        }

    def _pass(self, account_id: str, pass_id: str) -> _Pass:
        state = self._passes.get(_account(account_id))
        if state is None or state.fetched.pass_id != pass_id:
            raise LookupError("no fetched pass of the account has this id")
        return state

    def _freeze(
        self, account: AccountId, pass_id: str, trigger: str, failure: str | None
    ) -> ReconcileReport:
        """The pass's report; one whose reads are gone (a restart mid-pass) reports its loss."""
        state = self._passes.pop(account, None)
        lost = self._failures.pop(account, None)
        if state is None or state.fetched.pass_id != pass_id:
            now = self._now()
            draft = ReportDraft(account, pass_id, _trigger(trigger), (now, now))
            draft.error("1", failure or "pass_lost")
            return draft.freeze(0)
        plan = state.plan or Plan(state.fetched, self._draft_of(state.fetched))
        if lost is not None:
            step, kind = lost
            plan.draft.error("2" if step == "2" else "5", kind)
        self._metrics.untracked(account, plan.untracked)
        return self._r.finish(plan)

    @staticmethod
    def _draft_of(fetched: Fetched) -> ReportDraft:
        draft = ReportDraft(
            fetched.account.account_id, fetched.pass_id, fetched.trigger, fetched.window
        )
        for entry_id in fetched.unreadable:
            draft.error("1", "handover_unreadable", str(entry_id))
        return draft

    # --- The effects (B19's actions; synchronous, never raising past `_effect`) ----------------

    def observe(self, account_id: str, *, pass_id: str) -> None:
        report = self._reports.pop(_account(account_id), None)
        if report is not None and report.pass_id == pass_id:
            self._metrics.observe(report)

    def publish(self, account_id: str, notices: Sequence[Sequence[str]]) -> None:
        account = _account(account_id)
        for reason, severity in notices:
            self._notices.publish(account, Notice(_reason(reason), _severity(severity)))

    def fetch_failed(self, account_id: str, *, trigger: str) -> None:
        self._metrics.ended(_trigger(trigger), "failed")

    def schedule_retry(self, account_id: str, *, attempt: int) -> None:
        self._retries.retry(_account(account_id), attempt=attempt)

    def lock(self, account_id: str, *, trigger: str) -> None:
        """B19 records the lock; the standing was set before it was told, and is set again."""
        self._standing.mark_stale(_account(account_id))
        self._metrics.ended(_trigger(trigger), "stale")

    def stale(self, account_id: str) -> None:
        """The stale episode: the Owner paged and `oms.account_stale` handed on (23 Sec.15.9)."""
        account = _account(account_id)
        _log().critical("reconcile_account_stale", account_id=account_id, cv_page=True)
        self._pager.raise_alert("page", _ALERTS["stale"], machine_kind=_KIND)
        self._notices.publish(account, STALE_NOTICE)

    def unlock(self, account_id: str) -> None:
        """Only as B19's `OPERATOR_RESOLVED` arm ends, after its record (BQ-5)."""
        self._standing.clear(_account(account_id))

    def reset_failures(self, account_id: str) -> None:
        self._tracker.reset(_account(account_id))

    def alert(self, account_id: str, *, reason: str, page: bool) -> None:
        summary = _ALERTS.get(reason, "A reconciliation job raised an alert.")
        _log().error("reconcile_job_alert", account_id=account_id, reason=reason)
        self._pager.raise_alert("page" if page else "alert", summary, machine_kind=_KIND)


_REASONS: Final[tuple[NoticeReason, ...]] = (
    "oms.account_desync",
    "oms.account_stale",
    "oms.account_synced",
)
_SEVERITIES: Final[tuple[NoticeSeverity, ...]] = ("info", "warning", "critical")


def _reason(text: str) -> NoticeReason:
    for reason in _REASONS:
        if reason == text:
            return reason
    raise ValueError("not a reconciliation notice")


def _severity(text: str) -> NoticeSeverity:
    for severity in _SEVERITIES:
        if severity == text:
            return severity
    raise ValueError("not a notice severity")
