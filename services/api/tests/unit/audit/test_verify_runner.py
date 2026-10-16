"""The scheduled verify run's port (#2111): the request and outcome shapes, the scripted fake
runner, and the job's slot pattern on the query service's own slot. No sleeps: events and
scheduler turns only."""

from __future__ import annotations

import asyncio
import dataclasses
import math
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository
from verify_fakes import FakeVerifyRunner

from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.verify_runner import (
    VERIFY_JOB_ACTOR,
    VerifyOutcome,
    VerifyOutcomeKind,
    VerifyRunner,
    VerifyRunRequest,
    VerifyStopReason,
    VerifyTrigger,
)
from candleviewer.audit.verify_slot import VerifySlot

OK, MISMATCH, STOPPED = VerifyOutcomeKind.OK, VerifyOutcomeKind.MISMATCH, VerifyOutcomeKind.STOPPED
T0 = datetime(2026, 10, 16, 4, 0, tzinfo=UTC)
T1 = T0 + timedelta(seconds=90)
NIGHTLY = VerifyRunRequest(trigger=VerifyTrigger.SCHEDULED, deadline_s=1800)


def _outcome(kind: VerifyOutcomeKind, **fields: Any) -> VerifyOutcome:
    return VerifyOutcome(outcome=kind, started_at=T0, ended_at=T1, entries_checked=10, **fields)


def test_the_wire_names_are_pinned() -> None:
    assert [kind.value for kind in VerifyOutcomeKind] == ["ok", "mismatch", "stopped"]
    assert [trigger.value for trigger in VerifyTrigger] == ["scheduled", "startup"]
    # The stop record reasons of the on-demand route, plus `record_failed`, which has none.
    assert [reason.value for reason in VerifyStopReason] == [
        "timeout",
        "hasher_busy",
        "entry_too_large",
        "store_unavailable",
        "internal_error",
        "record_failed",
    ]


def test_a_request_defaults_to_the_job_actor() -> None:
    assert NIGHTLY.actor == VERIFY_JOB_ACTOR == "system:cv-audit-verify"


@pytest.mark.parametrize("deadline_s", [0.0, -1.0, math.inf, math.nan])
def test_a_request_without_a_finite_positive_deadline_is_refused(deadline_s: float) -> None:
    with pytest.raises(ValueError, match="deadline_s"):
        VerifyRunRequest(trigger=VerifyTrigger.STARTUP, deadline_s=deadline_s)


@pytest.mark.parametrize("actor", ["owner", "", "user:system:x", "System:cv-audit-verify"])
def test_a_request_with_a_non_system_actor_is_refused(actor: str) -> None:
    with pytest.raises(ValueError, match="system"):
        VerifyRunRequest(trigger=VerifyTrigger.SCHEDULED, deadline_s=60, actor=actor)


def test_each_consistent_outcome_builds() -> None:
    assert _outcome(OK).first_bad_id is None and _outcome(OK).stop_reason is None
    assert _outcome(MISMATCH, first_bad_id=7).first_bad_id == 7
    stopped = _outcome(STOPPED, stop_reason=VerifyStopReason.TIMEOUT)
    assert stopped.stop_reason is VerifyStopReason.TIMEOUT and stopped.first_bad_id is None


def test_an_empty_chain_can_pass() -> None:
    empty = VerifyOutcome(outcome=OK, started_at=T0, ended_at=T0, entries_checked=0)
    assert empty.outcome is OK


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        (OK, {"first_bad_id": 7}),
        (OK, {"stop_reason": VerifyStopReason.TIMEOUT}),
        (MISMATCH, {}),
        (MISMATCH, {"first_bad_id": 7, "stop_reason": VerifyStopReason.TIMEOUT}),
        (STOPPED, {}),
        (STOPPED, {"stop_reason": VerifyStopReason.TIMEOUT, "first_bad_id": 7}),
    ],
)
def test_an_inconsistent_outcome_is_refused(kind: VerifyOutcomeKind, fields: Any) -> None:
    with pytest.raises(ValueError, match="only then"):
        _outcome(kind, **fields)


@pytest.mark.parametrize("first_bad_id", [0, -3])
def test_a_mismatch_names_a_real_entry(first_bad_id: int) -> None:
    with pytest.raises(ValueError, match="entry id"):
        _outcome(MISMATCH, first_bad_id=first_bad_id)


@pytest.mark.parametrize(
    ("started_at", "ended_at"),
    [
        (T0.replace(tzinfo=None), T1),
        (T0, T1.replace(tzinfo=None)),
        (T0.astimezone(timezone(timedelta(hours=2))), T1),
    ],
)
def test_an_outcome_with_naive_or_non_utc_times_is_refused(
    started_at: datetime, ended_at: datetime
) -> None:
    with pytest.raises(ValueError, match="UTC"):
        VerifyOutcome(outcome=OK, started_at=started_at, ended_at=ended_at, entries_checked=0)


def test_an_outcome_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(ValueError, match="before"):
        VerifyOutcome(outcome=OK, started_at=T1, ended_at=T0, entries_checked=0)


def test_an_outcome_with_negative_entries_checked_is_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        VerifyOutcome(outcome=OK, started_at=T0, ended_at=T1, entries_checked=-1)


def test_requests_and_outcomes_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        NIGHTLY.deadline_s = 1  # type: ignore[misc]  # the point: frozen at runtime too
    with pytest.raises(dataclasses.FrozenInstanceError):
        _outcome(OK).outcome = STOPPED  # type: ignore[misc]  # the point: frozen at runtime too


async def test_the_fake_returns_its_script_in_order_and_records_each_request() -> None:
    passed, stopped = _outcome(OK), _outcome(STOPPED, stop_reason=VerifyStopReason.TIMEOUT)
    fake = FakeVerifyRunner(passed, stopped)
    runner: VerifyRunner = fake  # the fake satisfies the port (mypy checks this line)
    startup = VerifyRunRequest(trigger=VerifyTrigger.STARTUP, deadline_s=1800)
    assert await runner.run(startup) is passed
    assert await runner.run(NIGHTLY) is stopped
    assert fake.requests == [startup, NIGHTLY]


async def test_the_fake_raises_a_scripted_exception() -> None:
    fake = FakeVerifyRunner(RuntimeError("store gone"))
    with pytest.raises(RuntimeError, match="store gone"):
        await fake.run(NIGHTLY)
    assert fake.requests == [NIGHTLY]


async def test_a_held_fake_run_finishes_once_released() -> None:
    hold, passed = asyncio.Event(), _outcome(OK)
    fake = FakeVerifyRunner(passed, hold=hold)
    run = asyncio.ensure_future(fake.run(NIGHTLY))
    await fake.entered.wait()
    assert not run.done()
    hold.set()
    assert await run is passed


async def test_a_held_fake_run_can_be_cancelled_mid_run() -> None:
    fake = FakeVerifyRunner(_outcome(OK), hold=asyncio.Event())
    run = asyncio.ensure_future(fake.run(NIGHTLY))
    await fake.entered.wait()
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert fake.requests == [NIGHTLY]


def test_the_query_service_owns_one_verify_slot() -> None:
    service = AuditQueryService(FakeAuditRepository())
    assert isinstance(service.verify_slot, VerifySlot)
    assert service.verify_slot is service.verify_slot
    assert AuditQueryService(FakeAuditRepository()).verify_slot is not service.verify_slot


async def test_a_scheduled_run_holds_the_query_service_slot_for_the_whole_run() -> None:
    """The #2111 job's shape: `acquire()`, one `run()`, `release()` in a `finally`. An
    on-demand run (`try_acquire`) is refused for as long as the scheduled run is going."""
    slot = AuditQueryService(FakeAuditRepository()).verify_slot
    hold = asyncio.Event()
    fake = FakeVerifyRunner(_outcome(OK), hold=hold)

    async def scheduled() -> VerifyOutcome:
        await slot.acquire()
        try:
            return await fake.run(NIGHTLY)
        finally:
            slot.release()

    job = asyncio.ensure_future(scheduled())
    await fake.entered.wait()
    assert slot.held and not slot.try_acquire()  # an on-demand run now: 409
    hold.set()
    assert (await job).outcome is OK
    assert not slot.held and slot.try_acquire()
