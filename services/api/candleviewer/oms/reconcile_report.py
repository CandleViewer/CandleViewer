"""The reconciliation pass's report, its notices, its watermark and its metrics (E29-T06 #914
PR 2a; 24-internal-schemas.md Sec.8.5 "The report", 23-ws-protocol.md Sec.15.9, 20-architecture.md
Sec.12.1). Pure, but for `ReconcileMetrics`, which only counts: no I/O, no clock, no interpreter.

`ReconcileReport` holds 24's fifteen fields, with `trigger`, `pass_id`, `duration_ms` and `errors`,
keyed by `account_id`. Its lists hold ids, symbols and `exec_id`s only, and `errors` each error's
step, kind and subject, never a value, a payload or a credential (C-12.6). What the record of a
pass, its notices and its metrics need is derived here, once:

* **Corrections** (`applied`): a step sent to an order, a position corrected, a stop attached or
  restored, an order recorded; never an item left for the Owner and never an error.
* **Owner items** (`owner_items`): `anomalies`, `unpaired`, `held`, `sl_restore_refused` and
  `sl_tighter`, which send B19 to `divergent` (24 Sec.8.5's phase table).
* **Standing items** (`STANDING_ITEMS`, a closed list): `no_record_in_force` (BQ-9),
  `handover_unreadable` and `untracked_fills_unread` (an `untracked` row's `fills_unread`, the
  orchestrator's ruling of 2026-10-31), states every later pass finds again from its own reads.
  They never hold the watermark back; any other error does, an `unknown` or `quarantined` row's
  `fills_unread` among them, so the next pass reads that window again.
* **The watermark** (`watermark_us`): the upper bound step 1 read to, never the report's instant,
  so a slow pass leaves no unread slice (the security delta's L4), and only after a pass whose
  `errors` hold standing items alone (BQ-10).
* **The notices** (BQ-6, BQ-9; `pass_notices`): `oms.account_desync` once per pass that applied a
  correction, `warning`, or `critical` for a pass that found an open position with no stop and no
  record in force; such a pass sends it at `critical` even when that is its only finding, as 23
  Sec.15.9 says, and is never clean. `oms.account_synced` once, on the first clean pass after a
  desync or stale episode: a clean pass applied nothing, left nothing for the Owner and listed no
  error. The notices are the pass's output; publishing them is the wiring's (PR 2b).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from decimal import Decimal
from typing import Final, Literal, get_args

from candleviewer.domain.primitives import AccountId, TsUs
from candleviewer.observability.metrics import BoundedMetric, MetricChild, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE

from .push_mapping import money_text

__all__ = [
    "CORRECTION_KINDS", "EMPTY_TEXT", "FILLS_UNREAD", "HANDOVER_UNREADABLE", "NO_RECORD_IN_FORCE",
    "OWNER_FIELDS", "PASS_RESULTS", "REPEATING_FIELDS", "STALE_NOTICE", "STANDING_ITEMS", "STEPS",
    "TRIGGERS", "UNTRACKED_FILLS_UNREAD",
    "CorrectionKind", "Notice", "NoticeReason", "NoticeSeverity", "PassError", "PassNotices",
    "PassResult", "PositionDrift", "ReconcileMetrics", "ReconcileReport", "ReportDraft", "Step",
    "Trigger", "audit_state", "pass_notices", "watermark_us",
]  # fmt: skip

#: What started a pass (24 Sec.8.5's trigger table), the label of 20 Sec.12.1's two series.
Trigger = Literal["startup", "reconnect", "periodic", "manual", "unknown"]
TRIGGERS: Final[tuple[Trigger, ...]] = get_args(Trigger)
#: How a pass ended, `oms_reconcile_passes_total{result}` (20 Sec.12.1): the four a reported pass
#: takes, and the two of a fetch that failed (`failed`) or locked the account (`stale`).
PassResult = Literal["clean", "corrected", "divergent", "errored", "failed", "stale"]
PASS_RESULTS: Final[tuple[PassResult, ...]] = get_args(PassResult)
#: The report's lists a correction lands in, `oms_reconcile_corrections_total{kind}`.
CorrectionKind = Literal[
    "corrected", "resolved_from_history", "abandoned", "newly_unknown", "untracked", "held",
    "foreign_stops", "position_drift", "sl_repaired", "sl_restored",
]  # fmt: skip
CORRECTION_KINDS: Final[tuple[CorrectionKind, ...]] = get_args(CorrectionKind)
#: The step of 24 Sec.8.5 an error was met in.
Step = Literal["1", "2", "3a", "3b", "3c", "3d", "4", "5"]
STEPS: Final[tuple[Step, ...]] = get_args(Step)
#: The standing items, a closed list (24 Sec.8.5): a state every later pass finds again from its
#: own reads, whatever its window, so it never holds the watermark back.
NO_RECORD_IN_FORCE: Final = "no_record_in_force"
HANDOVER_UNREADABLE: Final = "handover_unreadable"
#: A found row the pass sends no finding, as the fills it read are not the venue's totals or
#: cannot close it (`reconciler.found_sends`). An `untracked` row's stands: its fills sit in the
#: hand-over store, and B1 chart version 8 closes it (the orchestrator's ruling of 2026-10-31). An
#: `unknown` or `quarantined` row's holds the watermark, so the next pass reads the window again.
FILLS_UNREAD: Final = "fills_unread"
UNTRACKED_FILLS_UNREAD: Final = "untracked_fills_unread"
STANDING_ITEMS: Final = frozenset({NO_RECORD_IN_FORCE, HANDOVER_UNREADABLE, UNTRACKED_FILLS_UNREAD})
#: The items a pass leaves for the Owner (B19's `divergent`, 24 Sec.8.5's phase table).
OWNER_FIELDS: Final = ("anomalies", "unpaired", "held", "sl_restore_refused", "sl_tighter")
#: The fields a second pass run back to back reports again, until the Owner resolves them; every
#: other field of that second report is empty (24 Sec.8.5).
REPEATING_FIELDS: Final = ("anomalies", "unpaired", "sl_tighter", "sl_restore_refused", "errors")
#: The longest subject an error names: an order link id, an exchange order id or an `exec_id`.
_MAX_SUBJECT: Final = 64
#: What `ReportDraft.error` lists for an empty kind or subject: a name, never a value.
EMPTY_TEXT: Final = "(empty)"


def _capped(text: str) -> str:
    """A kind or a subject cut to the cap, an empty one named (`ReportDraft.error`)."""
    return text[:_MAX_SUBJECT] or EMPTY_TEXT


NoticeReason = Literal["oms.account_desync", "oms.account_stale", "oms.account_synced"]
NoticeSeverity = Literal["info", "warning", "critical"]


@dataclass(frozen=True, slots=True)
class PassError:
    """What a phase could not plan or apply (24 Sec.8.5 `errors`): its step, its kind (an error's
    class name, or a standing item's name) and what it concerned (an id, a symbol, an `exec_id` or
    a hand-over entry's id), never a value."""

    step: Step
    kind: str
    subject: str | None = None

    def __post_init__(self) -> None:
        if self.step not in STEPS:
            raise ValueError("an error names one of 24 Sec.8.5's steps")
        if not self.kind or len(self.kind) > _MAX_SUBJECT:
            raise ValueError("an error's kind is a short name")
        if self.subject is not None and not 0 < len(self.subject) <= _MAX_SUBJECT:
            raise ValueError("an error's subject is an id, never a payload")

    @property
    def standing(self) -> bool:
        return self.kind in STANDING_ITEMS


@dataclass(frozen=True, slots=True)
class PositionDrift:
    """Step 4's correction of one position, with both values (scenario S3): the side and size the
    OMS held before (none for a position it held no row of) and the exchange's."""

    symbol: str
    position_idx: int
    side_before: str | None
    qty_before: Decimal | None
    side_after: str | None
    qty_after: Decimal


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    """One pass's report (24 Sec.8.5 "The report"), as `persist_report` writes it (`oms.reconcile`,
    `stage: finished`, 24 Sec.15.5)."""

    account_id: AccountId
    pass_id: str
    trigger: Trigger
    gap_window: tuple[TsUs, TsUs]
    duration_ms: int = 0
    corrected: tuple[str, ...] = ()
    resolved_from_history: tuple[str, ...] = ()
    abandoned: tuple[str, ...] = ()
    newly_unknown: tuple[str, ...] = ()
    untracked: tuple[str, ...] = ()
    anomalies: tuple[str, ...] = ()
    held: tuple[str, ...] = ()
    foreign_stops: tuple[str, ...] = ()
    unpaired: tuple[str, ...] = ()
    position_drift: tuple[PositionDrift, ...] = ()
    sl_repaired: tuple[str, ...] = ()
    sl_restored: tuple[str, ...] = ()
    sl_restore_refused: tuple[str, ...] = ()
    sl_tighter: tuple[str, ...] = ()
    errors: tuple[PassError, ...] = ()

    def __post_init__(self) -> None:
        if self.trigger not in TRIGGERS:
            raise ValueError("a report's trigger is one of 24 Sec.8.5's five")
        if self.gap_window[0] > self.gap_window[1] or self.duration_ms < 0:
            raise ValueError("a report's window and run time are ordered and not negative")

    def corrections(self) -> Mapping[CorrectionKind, int]:
        """The corrections by kind: each list's length, `oms_reconcile_corrections_total`."""
        return {kind: len(getattr(self, kind)) for kind in CORRECTION_KINDS}

    @property
    def applied(self) -> int:
        """The corrections the pass applied to tracked state (BQ-6)."""
        return sum(self.corrections().values())

    @property
    def owner_items(self) -> int:
        """The items left for the Owner, which send B19 to `divergent`."""
        return sum(len(getattr(self, name)) for name in OWNER_FIELDS)

    @property
    def naked_without_record(self) -> bool:
        """An open position with no stop and no record in force was found (BQ-9)."""
        return any(e.kind == NO_RECORD_IN_FORCE for e in self.errors)

    @property
    def clean(self) -> bool:
        """Applied no correction, left nothing for the Owner and listed no error (23 Sec.15.9)."""
        return self.applied == 0 and self.owner_items == 0 and not self.errors

    @property
    def result(self) -> PassResult:
        """`oms_reconcile_passes_total{result}` of a reported pass."""
        if self.owner_items:
            return "divergent"
        if self.errors:
            return "errored"
        return "corrected" if self.applied else "clean"


@dataclass
class ReportDraft:
    """The report a pass fills in as it plans and applies; `freeze` makes the record."""

    account_id: AccountId
    pass_id: str
    trigger: Trigger
    gap_window: tuple[TsUs, TsUs]
    corrected: list[str] = field(default_factory=list)
    resolved_from_history: list[str] = field(default_factory=list)
    abandoned: list[str] = field(default_factory=list)
    newly_unknown: list[str] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)
    foreign_stops: list[str] = field(default_factory=list)
    unpaired: list[str] = field(default_factory=list)
    position_drift: list[PositionDrift] = field(default_factory=list)
    sl_repaired: list[str] = field(default_factory=list)
    sl_restored: list[str] = field(default_factory=list)
    sl_restore_refused: list[str] = field(default_factory=list)
    sl_tighter: list[str] = field(default_factory=list)
    errors: list[PassError] = field(default_factory=list)

    def error(self, step: Step, kind: str, subject: str | None = None) -> None:
        """Lists an error. The phases call it inside their failure handlers, so it never raises
        over what it names (BQ-18): a kind or a subject past the cap is cut to it, and an empty
        one is named `EMPTY_TEXT`. `PassError` itself keeps the cap."""
        named = None if subject is None else _capped(subject)
        self.errors.append(PassError(step, _capped(kind), named))

    def freeze(self, duration_ms: int) -> ReconcileReport:
        lists = {
            f.name: tuple(getattr(self, f.name))
            for f in fields(self)
            if isinstance(getattr(self, f.name), list)
        }
        return ReconcileReport(
            account_id=self.account_id,
            pass_id=self.pass_id,
            trigger=self.trigger,
            gap_window=self.gap_window,
            duration_ms=duration_ms,
            **lists,
        )


@dataclass(frozen=True, slots=True)
class Notice:
    """One `account_notice` row of 23 Sec.15.9: its reason and the severity this pass gives it."""

    reason: NoticeReason
    severity: NoticeSeverity


#: The stale row (23 Sec.15.9), sent once per episode as B19 locks the account.
STALE_NOTICE: Final = Notice("oms.account_stale", "critical")
_SYNCED: Final = Notice("oms.account_synced", "info")


@dataclass(frozen=True, slots=True)
class PassNotices:
    """A pass's notices and whether a desync or stale episode is open after it."""

    notices: tuple[Notice, ...]
    episode_open: bool


def pass_notices(report: ReconcileReport, *, episode_open: bool) -> PassNotices:
    """BQ-6 and BQ-9 (23 Sec.15.9): the desync row once for a pass that applied a correction, at
    `critical` when the pass found a naked position with no record in force, which alone sends it
    at `critical` too; the synced row once, on the first clean pass of an open episode."""
    critical = report.naked_without_record
    if report.applied or critical:
        severity: NoticeSeverity = "critical" if critical else "warning"
        return PassNotices((Notice("oms.account_desync", severity),), episode_open=True)
    if report.clean and episode_open:
        return PassNotices((_SYNCED,), episode_open=False)
    return PassNotices((), episode_open=episode_open)


def watermark_us(report: ReconcileReport) -> TsUs | None:
    """`exchange_accounts.last_reconciled_at` after this pass (24 Sec.8.5 `gap_from`, BQ-10): the
    upper bound step 1 read to, once every error is a standing item; None holds the watermark, so
    the next pass reads the window again."""
    if all(e.standing for e in report.errors):
        return report.gap_window[1]
    return None


def audit_state(report: ReconcileReport) -> dict[str, object]:
    """The `after_state` of the pass's `oms.reconcile` record (`stage: finished`, 24 Sec.15.5):
    every field, as JSON, money as exact decimal text; ids, symbols and `exec_id`s only."""
    state: dict[str, object] = {
        "stage": "finished",
        "pass_id": report.pass_id,
        "trigger": report.trigger,
        "duration_ms": report.duration_ms,
        "gap_window": list(report.gap_window),
        "result": report.result,
    }
    for f in fields(report):
        value = getattr(report, f.name)
        if f.name == "position_drift":
            state[f.name] = [_drift(d) for d in value]
        elif f.name == "errors":
            state[f.name] = [{"step": e.step, "kind": e.kind, "subject": e.subject} for e in value]
        elif isinstance(value, tuple) and f.name != "gap_window":
            state[f.name] = list(value)
    return state


def _drift(d: PositionDrift) -> dict[str, object]:
    before = None if d.qty_before is None else money_text(d.qty_before)
    return {
        "symbol": d.symbol,
        "position_idx": d.position_idx,
        "side_before": d.side_before,
        "qty_before": before,
        "side_after": d.side_after,
        "qty_after": money_text(d.qty_after),
    }


class ReconcileMetrics:
    """20 Sec.12.1's reconciliation series (BQ-11), registered from their catalogue entries, with
    no account label: the logs name the account. `naked_position_alerts_total` counts each naked
    position step 5 attaches a recorded stop to (BQ-9). `oms_untracked_orders` sums the latest
    count each account's pass reported; `oms_stale_accounts` is the job driver's (PR 2b)."""

    def __init__(self, metrics: Metrics) -> None:
        specs = {spec.name: spec for spec in CATALOGUE}

        def made(name: str) -> BoundedMetric:
            spec = specs[name]
            if spec.kind == "histogram":
                return metrics.histogram(
                    name,
                    spec.help,
                    spec.labels,
                    buckets=spec.buckets or (),
                    max_series=spec.max_series,
                )
            make = metrics.counter if spec.kind == "counter" else metrics.gauge
            return make(name, spec.help, spec.labels, max_series=spec.max_series)

        self._seconds = made("oms_reconcile_seconds")
        self._passes = made("oms_reconcile_passes_total")
        self._corrections = made("oms_reconcile_corrections_total")
        self._untracked: MetricChild = made("oms_untracked_orders").child()
        self._naked: MetricChild = made("naked_position_alerts_total").child()
        self._untracked_by_account: dict[AccountId, int] = {}

    def observe(self, report: ReconcileReport) -> None:
        """A reported pass: its run time, its result and its corrections by kind."""
        self._seconds.labels(report.trigger).observe(report.duration_ms / 1000)
        self._passes.labels(report.trigger, report.result).inc()
        for kind, count in report.corrections().items():
            if count:
                self._corrections.labels(kind).inc(count)

    def ended(self, trigger: Trigger, result: Literal["failed", "stale"]) -> None:
        """A pass whose fetch failed (`failed`), or failed for the stale window (`stale`)."""
        self._passes.labels(trigger, result).inc()

    def untracked(self, account_id: AccountId, count: int) -> None:
        """The account's `untracked` rows after its pass; the gauge is every account's sum."""
        self._untracked_by_account[account_id] = max(count, 0)
        self._untracked.set(sum(self._untracked_by_account.values()))

    def naked(self) -> None:
        self._naked.inc()
