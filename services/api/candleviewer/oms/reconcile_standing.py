"""The account's reconciliation standing and the fetch-failure tracker (E29-T06 #914 PR 2a;
24-internal-schemas.md Sec.8.5 "The stale rule", Sec.8.10; BQ-4, BQ-5; C-2.21).

`ReconcileStanding` is a plain flag per account in memory: synchronous, O(1), no I/O, and it never
queries an interpreter (C-2.20). It is the order-entry gate's `account_stale` check
(`OrderEntryCheck`, `domain.order_entry`): the gate's call site is the wiring's (PR 2b). B19
records; this enforces:

* **Set before B19 is told.** The OMS's fetch phase sets it when the tracker finds the stale window
  spent, then raises the `FetchFailed` that tells B19, so the refusal takes effect before the event
  that records it is processed. B19's `stale_lockout` entry sets it again, idempotent.
* **Cleared only after B19 records the unlock.** Only B19's `unlock_account_for_new_orders`, the
  last action of the `OPERATOR_RESOLVED` arm, clears it, after `audit_operator_resolved`. A good
  pass never clears it, nor does a reconnect (INV-B19-b; E45-T02's "one good pass" would reverse
  #2204).
* **Rebuilt at start-up** from each account's restored B19 state (`restored`), as a static restore
  runs no entry action: a restart never unlocks a stale account.
* **Held whole while the jobs cannot start** (`hold`, 24 Sec.8.5, INV-B19-a): a start that fails
  before any job opens rebuilds no account's standing, so every account is refused until a retry
  starts the jobs (`release`); a restored lock is then in place before the hold lifts.

It is neither account health nor B20's risk lockout, and protective paths (a stop attach, restore
or tightening, a cancel, a close) never consult it (C-2.6): only the order-entry gate does.

`FailureTracker` keeps, per account, the time of the first failed fetch since the run began (the
run ends at a reported pass or the operator's unlock, B19's `reset_failures`), and judges a failure
against the stale window with B19's own rule (`b19.window_elapsed`), so the guard and the tracker
never disagree. Times are the OMS clock's, in microseconds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.domain.primitives import AccountId
from candleviewer.statechart.bindings.b19_reconciliation import window_elapsed

__all__ = [
    "STALE_AFTER_S",
    "STALE_DETAIL",
    "STALE_STATE",
    "UNSTARTED_DETAIL",
    "Failure",
    "FailureTracker",
    "ReconcileStanding",
]

#: `CV_OMS_STALE_AFTER_S`'s default (#914 Technical notes): 2 minutes of failed fetches.
STALE_AFTER_S: Final = 120.0
#: B19's lock (28 B19.2), the one restored state that rebuilds a stale standing.
STALE_STATE: Final = "stale_lockout"
#: The refusal's human text: a constant, never an id or a value (`OrderEntryRefusal`).
STALE_DETAIL: Final = (
    "Order entry on this account is paused: reconciliation has failed for 2 minutes."
)
#: The refusal's text while the jobs could not start (`hold`), a constant likewise.
UNSTARTED_DETAIL: Final = "Order entry is paused: reconciliation has not started yet."


class ReconcileStanding:
    """The stale flag per account (module docstring); the gate's `account_stale` check."""

    def __init__(self) -> None:
        self._stale: set[AccountId] = set()
        self._held = False

    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        """`OrderEntryCheck`: refuses a stale account's entry with `account_stale` (24 Sec.8.10),
        and every account's while the standing is held. A set read and a flag read, O(1) and in
        memory, from the serving loop, while the order lane writes the set (C-2.20, C-2.21)."""
        if account_id in self._stale:
            return OrderEntryRefusal("account_stale", STALE_DETAIL)
        if self._held:
            return OrderEntryRefusal("account_stale", UNSTARTED_DETAIL)
        return None

    def is_stale(self, account_id: AccountId) -> bool:
        return account_id in self._stale

    def mark_stale(self, account_id: AccountId) -> None:
        """Before B19 is told (C-2.21); idempotent."""
        self._stale.add(account_id)

    def clear(self, account_id: AccountId) -> None:
        """Only after B19 recorded `OPERATOR_RESOLVED` (BQ-5)."""
        self._stale.discard(account_id)

    def restored(self, account_id: AccountId, state: str) -> None:
        """Start-up: the account's restored B19 leaf state decides, as no entry action re-ran."""
        if state == STALE_STATE:
            self._stale.add(account_id)
        else:
            self._stale.discard(account_id)

    def hold(self) -> None:
        """Every account refused until `release`: the jobs could not start, so no account's
        standing was rebuilt from its restored state (24 Sec.8.5, INV-B19-a). Idempotent."""
        self._held = True

    def release(self) -> None:
        """The jobs started, each account's standing rebuilt: the hold lifts. Idempotent."""
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    @property
    def stale_count(self) -> int:
        """`oms_stale_accounts` (20 Sec.12.1), which the job driver sets (PR 2b)."""
        return len(self._stale)


@dataclass(frozen=True, slots=True)
class Failure:
    """One failed fetch, judged: when the run began, this failure's time and the window."""

    failing_since_us: int
    failed_at_us: int
    window_us: int

    @property
    def exhausted(self) -> bool:
        return window_elapsed(self.failing_since_us, self.failed_at_us, self.window_us)


class FailureTracker:
    """The plain-code failure run per account (BQ-4): a failure is a failed fetch."""

    def __init__(self, *, window_s: float = STALE_AFTER_S) -> None:
        if isinstance(window_s, bool) or not math.isfinite(window_s) or window_s <= 0:
            raise ValueError("the stale window is a finite number of seconds above zero")
        self._window_us = round(window_s * 1_000_000)
        self._since: dict[AccountId, int] = {}

    def failed(self, account_id: AccountId, at_us: int) -> Failure:
        """Records a failed fetch at `at_us` and judges it; a run begins at its first failure."""
        since = self._since.setdefault(account_id, at_us)
        return Failure(since, at_us, self._window_us)

    def reset(self, account_id: AccountId) -> None:
        """Ends the account's run (B19's `reset_failures`)."""
        self._since.pop(account_id, None)

    def failing_since(self, account_id: AccountId) -> int | None:
        return self._since.get(account_id)
