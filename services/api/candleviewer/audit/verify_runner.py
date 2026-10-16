"""The scheduled audit chain verify run (E42-T02, for #2111): the port the start-up and nightly
verify job calls, and the outcome it reads back.

The job takes the single-flight slot first. It awaits `acquire()` on
`AuditService.query.verify_slot`, so it is never skipped. It calls `VerifyRunner.run()` once,
then gives the slot back with `release()` in a `finally`.

The runner owns everything a run records:
- the write-ahead `admin.audit_verify` `started` record, then the result or stop record;
- the chain gauge and the failure counter;
- the `audit_chain_break` system event (contract #2392/#2446, E42-T02 design D6).

So the job writes no audit record and sets none of those series. The E42-T02 verify chain
supplies the real runner (from `candleviewer.api`). Until the composition root wires one, the
job has no runner and stays inert.

Outcome rules (fail closed):
- `ok` only when the run walked the whole chain, genesis to the head, found no break, and its
  result record was written.
- A break is `mismatch` whether or not its record was written. Its counter, gauge and event
  never wait on the record.
- Any other end is `stopped` with its reason, and is never a success.
- A cancelled run raises `CancelledError`, which is never swallowed. It leaves only its
  `started` record, as an on-demand run does.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol

#: The `actor_label` of a scheduled run's records, like `system:retention` for retention.
VERIFY_JOB_ACTOR: Final = "system:cv-audit-verify"


class VerifyTrigger(StrEnum):
    SCHEDULED = "scheduled"
    STARTUP = "startup"


class VerifyOutcomeKind(StrEnum):
    #: The whole chain passed and the result record was written.
    OK = "ok"
    #: A break was found: `first_bad_id` names the first divergent entry.
    MISMATCH = "mismatch"
    #: The run ended without a result (`stop_reason`). This is never a success.
    STOPPED = "stopped"


class VerifyStopReason(StrEnum):
    """Why a run stopped. All but `record_failed` are its stop record's `reason`. For an
    entry over the cap, that reason also names the entry (`entry_too_large@<id>`)."""

    #: The walk ran past the request's `deadline_s`.
    TIMEOUT = "timeout"
    #: The chain hasher's bounded queue was full.
    HASHER_BUSY = "hasher_busy"
    #: An entry is over the per-entry fetch cap. It was not checked, so the run is not a pass.
    ENTRY_TOO_LARGE = "entry_too_large"
    #: The audit store could not be read.
    STORE_UNAVAILABLE = "store_unavailable"
    #: Anything unexpected.
    INTERNAL_ERROR = "internal_error"
    #: A record of the run could not be written. Either the `started` record failed, so the
    #: run never walked, or a pass's result record failed. No stop record exists for this one.
    RECORD_FAILED = "record_failed"


@dataclass(frozen=True, slots=True)
class VerifyRunRequest:
    """One scheduled run. It always covers the whole chain, genesis to the head, with no span
    cap, so it has no range to set."""

    trigger: VerifyTrigger
    #: The walk stops with `timeout` after this many seconds. The job passes its
    #: `audit_verify_nightly_deadline_s` (#2111).
    deadline_s: float
    #: The `actor_label` of the run's records. Always a `system:` actor, never a user.
    actor: str = VERIFY_JOB_ACTOR

    def __post_init__(self) -> None:
        if not math.isfinite(self.deadline_s) or self.deadline_s <= 0:
            raise ValueError("deadline_s must be a finite number of seconds above 0")
        if not self.actor.startswith("system:"):
            raise ValueError("a scheduled verify run's actor must be a `system:` actor")


@dataclass(frozen=True, slots=True)
class VerifyOutcome:
    """How one run ended, as `VerifyRunner.run()` returns it. Only a consistent shape can be
    built: a stop reason only on `stopped`, a first bad id only on `mismatch`, UTC times in
    order."""

    outcome: VerifyOutcomeKind
    started_at: datetime
    ended_at: datetime
    entries_checked: int
    #: The first divergent entry. Set on `mismatch`, and only then.
    first_bad_id: int | None = None
    #: Set on `stopped`, and only then.
    stop_reason: VerifyStopReason | None = None

    def __post_init__(self) -> None:
        for stamp in (self.started_at, self.ended_at):
            if stamp.utcoffset() != timedelta(0):
                raise ValueError("started_at and ended_at must be tz-aware UTC")
        if self.ended_at < self.started_at:
            raise ValueError("ended_at is before started_at")
        if self.entries_checked < 0:
            raise ValueError("entries_checked must not be negative")
        mismatch = self.outcome is VerifyOutcomeKind.MISMATCH
        if (self.first_bad_id is not None) != mismatch:
            raise ValueError("first_bad_id is set on a mismatch, and only then")
        if self.first_bad_id is not None and self.first_bad_id < 1:
            raise ValueError("first_bad_id must be an entry id (1 or above)")
        if (self.stop_reason is not None) != (self.outcome is VerifyOutcomeKind.STOPPED):
            raise ValueError("stop_reason is set on a stopped run, and only then")


class VerifyRunner(Protocol):
    async def run(self, request: VerifyRunRequest) -> VerifyOutcome:
        """One whole-chain run, recorded as the module docstring says. The caller holds the
        verify slot for the whole call."""
