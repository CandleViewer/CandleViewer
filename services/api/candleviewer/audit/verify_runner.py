"""The scheduled audit chain verify run (E42-T02, for #2111): the port the start-up and nightly
verify job calls, and the outcome it reads back.

How the job runs:
- Each run takes the single-flight slot first, as `AuditService.query.verify_slot`. Resolve the
  slot per run, because a restarted `AuditService` builds a new one.
- Call `await slot.acquire()` *before* the `try`, then make the one `VerifyRunner.run()` call
  inside it, and call `slot.release()` in its `finally`. A wait cancelled inside the `try` would
  otherwise release a slot another run holds.
- A scheduled run waits and is never skipped. The job keeps at most one run in flight per
  trigger and never queues a second run of the same trigger, so the slot's waiters stay bounded.

The runner owns everything a run records:
- the write-ahead `admin.audit_verify` `started` record, then the result or stop record, all
  with the `system:` actor label and no `actor_user_id`, `session_id` or `actor_ip`;
- the chain gauge and the failure counter;
- the `audit_chain_break` system event (contract #2392/#2446, E42-T02 design D6).

So the job writes no audit record and sets none of those series. The E42-T02 verify chain
supplies the real runner (from `candleviewer.api`). Until the composition root wires one, the
job has no runner and stays inert.

Outcome rules (fail closed):
- `ok` only when the run walked the whole chain, genesis to the head read when it started,
  found no break, and its result record was written. An empty log with no checkpoint above
  its head is a pass with `entries_checked=0`.
- A break is `mismatch` whether or not its record was written. Its counter, gauge and event do
  not depend on the record.
- Any other end is `stopped` with its reason, and is never a success. `entry_too_large` stays
  until the cap is raised, so a retry cannot pass it.
- A run cancelled while it walks raises `CancelledError`, which is never swallowed, and leaves
  only its `started` record.

Compare `outcome` with `VerifyOutcomeKind.OK`. Every member is truthy.
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
    """Why the run started. The runner carries it in the run's records and logs."""

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
    cap, so it has no range to set. A plain string for `trigger` is coerced to the enum, and
    an unknown one is refused."""

    trigger: VerifyTrigger
    #: The walk stops with `timeout` after this many seconds. The job passes its
    #: `audit_verify_nightly_deadline_s` (#2111).
    deadline_s: float
    #: The `actor_label` of the run's records. Only the verify job's own system actor is
    #: accepted.
    actor: str = VERIFY_JOB_ACTOR

    def __post_init__(self) -> None:
        object.__setattr__(self, "trigger", VerifyTrigger(self.trigger))
        if not math.isfinite(self.deadline_s) or self.deadline_s <= 0:
            raise ValueError("deadline_s must be a finite number of seconds above 0")
        if self.actor != VERIFY_JOB_ACTOR:
            raise ValueError(f"a scheduled verify run's actor must be {VERIFY_JOB_ACTOR!r}")


@dataclass(frozen=True, slots=True)
class VerifyOutcome:
    """How one run ended, as `VerifyRunner.run()` returns it.

    Only a consistent shape can be built:
    - a stop reason only on `stopped`, and a first bad id only on `mismatch`;
    - UTC times;
    - plain strings coerced to the enums, and unknown ones refused.

    A clock that stepped back between the two stamps is clamped (`ended_at` = `started_at`)
    rather than refused, so a found break never turns into an exception. `entries_checked` is
    the progress at the end, also on a stop."""

    outcome: VerifyOutcomeKind
    started_at: datetime
    ended_at: datetime
    entries_checked: int
    #: The first divergent entry. Set on `mismatch`, and only then.
    first_bad_id: int | None = None
    #: Set on `stopped`, and only then.
    stop_reason: VerifyStopReason | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", VerifyOutcomeKind(self.outcome))
        if self.stop_reason is not None:
            object.__setattr__(self, "stop_reason", VerifyStopReason(self.stop_reason))
        for stamp in (self.started_at, self.ended_at):
            if stamp.utcoffset() != timedelta(0):
                raise ValueError("started_at and ended_at must be tz-aware UTC")
        if self.ended_at < self.started_at:
            object.__setattr__(self, "ended_at", self.started_at)
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
