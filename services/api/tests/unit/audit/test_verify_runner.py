"""The scheduled verify run's port (#2111): the request and outcome shapes, the scripted fake
runner, and the job's slot pattern on the query service's own slot. No sleeps: events and
scheduler turns only, each wait bounded so a regression fails instead of hanging."""

from __future__ import annotations

import asyncio
import dataclasses
import math
from collections.abc import Awaitable
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


async def _within[T](step: Awaitable[T]) -> T:
    return await asyncio.wait_for(step, 5)


def _outcome(kind: VerifyOutcomeKind | str, **fields: Any) -> VerifyOutcome:
    outcome: Any = kind  # plain strings are part of what is tested: the dataclass coerces them
    return VerifyOutcome(outcome=outcome, started_at=T0, ended_at=T1, entries_checked=10, **fields)


def test_the_outcome_kinds_are_pinned() -> None:
    assert [kind.value for kind in VerifyOutcomeKind] == ["ok", "mismatch", "stopped"]


def test_the_triggers_are_pinned() -> None:
    assert [trigger.value for trigger in VerifyTrigger] == ["scheduled", "startup"]


def test_the_stop_reasons_are_the_routes_record_reasons_plus_record_failed() -> None:
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


def test_a_sub_second_deadline_is_accepted() -> None:
    assert VerifyRunRequest(trigger=VerifyTrigger.STARTUP, deadline_s=0.001).deadline_s == 0.001


@pytest.mark.parametrize(
    "actor",
    [
        "owner",
        "",
        "system",
        "systemadmin",
        "system:",
        "system:retention",
        "System:cv-audit-verify",
        "system:cv-audit-verify\nforged",
    ],
)
def test_a_request_with_any_other_actor_is_refused(actor: str) -> None:
    with pytest.raises(ValueError, match="actor must be"):
        VerifyRunRequest(trigger=VerifyTrigger.SCHEDULED, deadline_s=60, actor=actor)


def test_a_plain_string_trigger_is_coerced_to_the_enum() -> None:
    trigger: Any = "startup"
    assert VerifyRunRequest(trigger=trigger, deadline_s=60).trigger is VerifyTrigger.STARTUP


def test_an_unknown_trigger_is_refused() -> None:
    trigger: Any = "bogus"
    with pytest.raises(ValueError, match="bogus"):
        VerifyRunRequest(trigger=trigger, deadline_s=60)


def test_plain_string_outcome_fields_are_coerced_to_the_enums() -> None:
    stopped = _outcome("stopped", stop_reason="timeout")
    assert stopped.outcome is STOPPED and stopped.stop_reason is VerifyStopReason.TIMEOUT


@pytest.mark.parametrize(("kind", "fields"), [("garbage", {}), (STOPPED, {"stop_reason": "nope"})])
def test_unknown_outcome_values_are_refused(kind: str, fields: Any) -> None:
    with pytest.raises(ValueError, match=r"garbage|nope"):
        _outcome(kind, **fields)


def test_a_pass_carries_neither_a_bad_id_nor_a_stop_reason() -> None:
    passed = _outcome(OK)
    assert passed.first_bad_id is None and passed.stop_reason is None


@pytest.mark.parametrize("first_bad_id", [1, 7])
def test_a_mismatch_names_its_first_bad_entry(first_bad_id: int) -> None:
    assert _outcome(MISMATCH, first_bad_id=first_bad_id).first_bad_id == first_bad_id


def test_a_stop_carries_its_reason() -> None:
    assert _outcome(STOPPED, stop_reason=VerifyStopReason.TIMEOUT).first_bad_id is None


def test_an_empty_chain_can_pass() -> None:
    empty = VerifyOutcome(outcome=OK, started_at=T0, ended_at=T1, entries_checked=0)
    assert empty.outcome is OK and empty.entries_checked == 0


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


def test_a_clock_that_stepped_back_is_clamped_so_a_break_still_builds() -> None:
    broken = VerifyOutcome(
        outcome=MISMATCH, started_at=T1, ended_at=T0, entries_checked=3, first_bad_id=2
    )
    assert broken.ended_at == broken.started_at == T1


def test_an_outcome_with_negative_entries_checked_is_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        VerifyOutcome(outcome=OK, started_at=T0, ended_at=T1, entries_checked=-1)


def test_a_request_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        NIGHTLY.deadline_s = 1  # type: ignore[misc]  # the point: frozen at runtime too


def test_an_outcome_cannot_be_relabelled_a_pass() -> None:
    stopped = _outcome(STOPPED, stop_reason=VerifyStopReason.TIMEOUT)
    with pytest.raises(dataclasses.FrozenInstanceError):
        stopped.outcome = OK  # type: ignore[misc]  # the point: frozen at runtime too
    with pytest.raises(ValueError, match="only then"):
        dataclasses.replace(stopped, outcome=OK)


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


async def test_the_fake_raises_a_scripted_cancellation() -> None:
    fake = FakeVerifyRunner(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await fake.run(NIGHTLY)


async def test_a_held_fake_run_finishes_once_released() -> None:
    hold, passed = asyncio.Event(), _outcome(OK)
    fake = FakeVerifyRunner(passed, hold=hold)
    run = asyncio.ensure_future(fake.run(NIGHTLY))
    await _within(fake.entered.wait())
    assert not run.done()
    hold.set()
    assert await _within(run) is passed


async def test_a_held_fake_run_can_be_cancelled_mid_run() -> None:
    fake = FakeVerifyRunner(_outcome(OK), hold=asyncio.Event())
    run = asyncio.ensure_future(fake.run(NIGHTLY))
    await _within(fake.entered.wait())
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
    """The #2111 job's shape: `acquire()` before the `try`, one `run()`, `release()` in the
    `finally`. An on-demand run (`try_acquire`) is refused while the scheduled run goes on."""
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
    await _within(fake.entered.wait())
    assert slot.held and not slot.try_acquire()  # an on-demand run now: 409
    hold.set()
    assert (await _within(job)).outcome is OK
    assert not slot.held and slot.try_acquire()
