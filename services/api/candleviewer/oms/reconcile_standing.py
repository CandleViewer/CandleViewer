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
* **Heard as it is gained** (E29-S07, 23 Sec.15.9). Its one listener (`listen`, the runtime's)
  hears each account the set gains, after the set holds it, on the writer's thread, so a lock with
  no notice of its own (a restored one, or one set ahead of B19's) reaches the sockets already
  open. A listener that raises is logged by its class and never reaches the writer: the lock
  stands either way.
* **Pre-marked, unheard, at a start** (`premark`, 24 Sec.8.5): the start refuses each account it
  is to open before its first open, and only that open clears the mark (`restored`). The mark is
  no lock, so the listener never hears it and the replay never reads it (`stale_accounts`): a
  socket open during the start sees no transient `oms.account_stale`. It refuses entry as a lock
  does, and a lock gained over it (a restored `stale_lockout`, a refused snapshot, the account's
  start failing) is heard and replayed: `mark_stale` promotes the pre-mark to the lock, the lock
  held before the pre-mark lifts, so the account is never in neither set (C-2.21).

It is neither account health nor B20's risk lockout, and protective paths (a stop attach, restore
or tightening, a cancel, a close) never consult it (C-2.6): only the order-entry gate does.

`FailureTracker` keeps, per account, the time of the first failed fetch since the run began (the
run ends at a reported pass or the operator's unlock, B19's `reset_failures`), and judges a failure
against the stale window with B19's own rule (`b19.window_elapsed`), so the guard and the tracker
never disagree. Times are the OMS clock's, in microseconds.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import structlog

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
    "LockGained",
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
#: The standing's listener (E29-S07): called with each account the set gains, once it holds it.
LockGained = Callable[[AccountId], None]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class ReconcileStanding:
    """The stale flag per account (module docstring); the gate's `account_stale` check."""

    def __init__(self) -> None:
        self._stale: set[AccountId] = set()
        #: The start's pre-marks (`premark`): refused as stale, never heard nor replayed.
        self._premarked: set[AccountId] = set()
        self._held = False
        self._gained: LockGained | None = None

    def listen(self, gained: LockGained | None) -> None:
        """The one listener of each account the set gains (module docstring), or None for none."""
        self._gained = gained

    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        """`OrderEntryCheck`: refuses a stale account's entry with `account_stale` (24 Sec.8.10),
        and every account's while the standing is held. A set read and a flag read, O(1) and in
        memory, from the serving loop, while the order lane writes the set (C-2.20, C-2.21)."""
        if account_id in self._stale or account_id in self._premarked:
            return OrderEntryRefusal("account_stale", STALE_DETAIL)
        if self._held:
            return OrderEntryRefusal("account_stale", UNSTARTED_DETAIL)
        return None

    def is_stale(self, account_id: AccountId) -> bool:
        """Refused as stale: a lock or a start's pre-mark."""
        return account_id in self._stale or account_id in self._premarked

    def stale_accounts(self) -> frozenset[AccountId]:
        """The accounts held stale now, one copy of the set made in one call, for the replay of
        23 Sec.15.9 (E29-S07): read on the serving loop as `refusal` is, while the order lane
        writes the set. E29-T08 (#916 BQ-2): a copy of the stale accounts, which the stuck-order
        detector reads for its `account_stale` incidents and never writes; no second tracker
        exists."""
        return frozenset(self._stale)

    def mark_stale(self, account_id: AccountId) -> None:
        """Before B19 is told (C-2.21); idempotent, so the listener hears a gain only. A pre-mark
        it meets becomes the lock: lifted only once the lock holds (never in neither set), and
        heard as a gain, as the replay now reads it (23 Sec.15.9)."""
        if account_id in self._stale:
            self._premarked.discard(account_id)
            return
        self._stale.add(account_id)
        self._premarked.discard(account_id)  # after the add: refused throughout (C-2.21)
        if self._gained is not None:
            try:
                self._gained(account_id)
            except Exception as exc:  # the lock stands; the writer never hears of it
                _log().error(
                    "reconcile_standing_listener_failed",
                    account_id=str(account_id),
                    error=type(exc).__name__,
                )

    def premark(self, account_id: AccountId) -> None:
        """The start's mark before an account's first open (module docstring): refused as stale,
        the listener not called. Only `restored` (the open) or `clear` lifts it. Idempotent."""
        self._premarked.add(account_id)

    def clear(self, account_id: AccountId) -> None:
        """Only after B19 recorded `OPERATOR_RESOLVED` (BQ-5)."""
        self._stale.discard(account_id)
        self._premarked.discard(account_id)

    def restored(self, account_id: AccountId, state: str) -> None:
        """Start-up: the account's restored B19 leaf state decides, as no entry action re-ran;
        it lifts the start's pre-mark, and a restored lock is heard as a gain. A restored lock
        holds before the pre-mark lifts (`mark_stale`), so a read on the serving loop never finds
        the account in neither set (C-2.21)."""
        if state == STALE_STATE:
            self.mark_stale(account_id)
        else:
            self._stale.discard(account_id)
            self._premarked.discard(account_id)

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
        """`oms_stale_accounts` (20 Sec.12.1), which the job driver sets (PR 2b): every account
        refused as stale, a start's pre-marks included."""
        return len(self._stale | self._premarked)


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
