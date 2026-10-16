"""TOTP clock-skew reporting (E09-Q05 gap #2146): `detect_skew`, `TotpSkewReporter` and the three
verification surfaces that use it.

A rejected code that is the right code for a step 2..10 steps away, and newer than the method's
last accepted code, is held until it can no longer be accepted, then raised as one `totp_clock_skew`
system event and a move of `auth_totp_clock_skew_total`. Reporting only observes: the caller gets
the same refusal as for a wrong code, the attempt still counts, a replay is no skew, and the sink
changes none of it. Fixed secrets and clocks, in-memory fakes, no network, no sleeps.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from unittest.mock import AsyncMock

import pytest
import structlog
from prometheus_client import REGISTRY, generate_latest
from pydantic import SecretStr

from candleviewer.app import build_auth_service
from candleviewer.auth.errors import MfaChallengeLocked, MfaCodeInvalid, StepUpCodeInvalid
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.metrics import (
    AUTH_EXPORTED_NAMES,
    auth_totp_clock_skew_total,
    export_auth_metrics,
)
from candleviewer.auth.mfa_service import CHALLENGE_ATTEMPT_CAP
from candleviewer.auth.service import AuthService
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import StepUpService
from candleviewer.auth.totp import (
    TOTP_SKEW_DIAGNOSTIC_STEPS,
    TOTP_STEP_SECONDS,
    detect_skew,
    generate_code,
    time_step_for,
    verify_code,
)
from candleviewer.auth.totp_skew import SKEW_HOLD_S, TotpSkewReporter
from candleviewer.health_wiring import PgSystemEventWriter
from candleviewer.observability.health_probes import SystemEventWriter
from candleviewer.observability.metrics import CollectorRegistry
from candleviewer.settings import Settings

from .auth_fakes import FakeUserRepository, make_user
from .mfa_fakes import FakeMfaRepository, RecordingSystemEvents, SkewRig, StalledSystemEvents
from .session_fakes import FakeSessionRepository

#: Their codes for steps -30..+40 around `NOW` and around the rig's clock (the tests move it at most
#: a dozen steps) are pairwise distinct and never "000000" or "123456": a "wrong" code cannot read
#: as skew, and a skewed one cannot be accepted, by chance.
SECRET, OTHER = bytes(range(1, 21)), bytes(range(2, 22))
NOW = 1_800_000_000.0
CURRENT = time_step_for(NOW)
BEHIND, AHEAD = "authenticator_behind", "authenticator_ahead"
FRESH = ((SECRET, None),)  # one method that never accepted a code
PASSWORD = "correct horse battery staple"


def _code_at(offset: int) -> str:
    return generate_code(SECRET, CURRENT + offset)


def _counter(*kinds: str) -> float:
    return sum(
        REGISTRY.get_sample_value("auth_totp_clock_skew_total", {"kind": k}) or 0
        for k in kinds or (BEHIND, AHEAD)
    )


async def _report(sink: SystemEventWriter | None, code: str, *, timeout_s: float = 1.0) -> None:
    """Refuse `code`, let its hold elapse, publish."""
    reporter = TotpSkewReporter(sink, timeout_s=timeout_s)
    reporter.report_rejection(FRESH, code, unix_time=NOW)
    await reporter.publish_due(NOW + SKEW_HOLD_S)


@pytest.fixture
async def rig() -> SkewRig:
    """A rig whose user has one confirmed method for `SECRET`."""
    rig = SkewRig()
    await rig.add_method(SECRET)
    return rig


# -- detect_skew -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("offset", "floor", "want"),
    [(o, None, o) for o in (-10, -3, -2, 2, 3, 10)]
    + [(o, None, None) for o in (-12, -11, -1, 0, 1, 11, 12)]
    # `floor` (steps from now) is the last accepted step: a code at or below it is a replay.
    + [(-3, -4, -3), (-3, -3, None), (-3, 1, None), (3, 2, 3), (3, 3, None)],
)
def test_detect_skew_names_a_new_step(offset: int, floor: int | None, want: int | None) -> None:
    floor_step = None if floor is None else CURRENT + floor
    assert detect_skew(SECRET, _code_at(offset), unix_time=NOW, floor=floor_step) == want


@pytest.mark.parametrize("code", ["000000", "123456", "", "12345", "1234567", "12345a", "١٢٣٤٥٦"])
def test_detect_skew_ignores_a_code_that_is_wrong_or_malformed(code: str) -> None:
    assert detect_skew(SECRET, code, unix_time=NOW) is None


def test_detect_skew_never_tries_a_negative_time_step() -> None:
    # unix_time 0 is step 0, so step -2 does not exist: only the +2 side can match.
    assert detect_skew(SECRET, generate_code(SECRET, 2), unix_time=0.0) == 2


# -- TotpSkewReporter --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("offset", "kind", "side"), [(-3, BEHIND, "behind"), (2, AHEAD, "ahead of")]
)
async def test_a_skewed_code_is_held_then_one_event_and_metric_move(
    offset: int, kind: str, side: str
) -> None:
    events, before, code = RecordingSystemEvents(), _counter(kind), _code_at(offset)
    reporter = TotpSkewReporter(events)
    methods = [(OTHER, None), *FRESH, *FRESH]  # every method is checked; one report
    reporter.report_rejection(methods, code, unix_time=NOW)
    await reporter.publish_due(NOW + SKEW_HOLD_S - 1)
    assert _counter(kind) == before and events.written == []  # the hold has not elapsed
    await reporter.publish_due(NOW + SKEW_HOLD_S)
    await reporter.publish_due(NOW + 2 * SKEW_HOLD_S)  # nothing is published twice
    assert _counter(kind) == before + 1
    (event,) = events.written
    assert (event.component, event.kind, event.severity) == ("auth", "totp_clock_skew", "warning")
    refused_at = "2027-01-15T08:00:00+00:00"  # NOW
    assert event.message == (
        f"clock skew: the authenticator is {abs(offset)} steps ({abs(offset) * 30} s) {side} the "
        f"server clock; its code was refused at {refused_at} (accepted: +/-1 step)"
    )
    assert event.details == {"kind": kind, "offset_steps": str(offset), "refused_at": refused_at}
    assert event.correlation_id is None
    rendered = repr(event)  # no code, no secret
    assert code not in rendered and SECRET.hex() not in rendered and repr(SECRET) not in rendered


def test_the_hold_is_the_shortest_that_outlives_every_reportable_code() -> None:
    refused = (CURRENT + 1) * TOTP_STEP_SECONDS - 0.5  # the last instant of the refusal's step
    reportable = [_code_at(o) for o in range(2, TOTP_SKEW_DIAGNOSTIC_STEPS + 1)]
    assert all(verify_code(SECRET, c, unix_time=refused + SKEW_HOLD_S) is None for c in reportable)
    furthest = verify_code(SECRET, reportable[-1], unix_time=refused + SKEW_HOLD_S - 30)
    assert furthest == CURRENT + TOTP_SKEW_DIAGNOSTIC_STEPS  # one step less and it still verifies


async def test_a_full_hold_drops_the_newest_report_and_counts_it() -> None:
    before, reporter = _counter(BEHIND), TotpSkewReporter(max_held=1)  # no sink: still counts
    reporter.report_rejection(FRESH, _code_at(-3), unix_time=NOW)
    reporter.report_rejection(FRESH, _code_at(-4), unix_time=NOW)  # dropped
    with structlog.testing.capture_logs() as logs:
        await reporter.publish_due(NOW + SKEW_HOLD_S)
    assert _counter(BEHIND) == before + 1
    assert [e["count"] for e in logs if e["event"] == "auth.totp_clock_skew_dropped"] == [1]


async def test_the_publisher_task_publishes_what_is_due_and_stop_discards_the_rest() -> None:
    now, wrote, events = [NOW], asyncio.Event(), AsyncMock()
    events.write.side_effect = lambda _event: wrote.set()
    reporter = TotpSkewReporter(events, clock=lambda: now[0], tick_s=0.0)
    reporter.report_rejection(FRESH, _code_at(-3), unix_time=NOW)
    reporter.start()
    reporter.start()  # idempotent: one task
    now[0] = NOW + SKEW_HOLD_S
    async with asyncio.timeout(5):  # a task that never publishes fails here instead of hanging
        await wrote.wait()
    reporter.report_rejection(FRESH, _code_at(3), unix_time=now[0])  # still held
    await reporter.stop()
    await reporter.stop()  # idempotent
    await reporter.publish_due(now[0] + SKEW_HOLD_S)  # stop discarded the second report
    assert events.write.await_count == 1


@pytest.mark.parametrize(
    ("sink", "error"),
    [
        (lambda: RecordingSystemEvents(fail_with=RuntimeError("db down")), "RuntimeError"),
        (lambda: RecordingSystemEvents(fail_with=TimeoutError()), "TimeoutError"),
        (StalledSystemEvents, "TimeoutError"),  # cut off by the reporter's own deadline
    ],
)
async def test_a_failing_or_stalled_sink_is_logged_by_class_and_never_raised(
    sink: Callable[[], SystemEventWriter], error: str
) -> None:
    before = _counter(BEHIND)
    with structlog.testing.capture_logs() as logs:
        async with asyncio.timeout(5):  # an unbounded wait on the stalled sink fails here
            await _report(sink(), _code_at(-3), timeout_s=0.0)  # a deadline already due
    assert _counter(BEHIND) == before + 1  # the metric does not need the sink
    errors = [e["error"] for e in logs if e["event"] == "auth.totp_clock_skew_event_failed"]
    assert errors == [error] and "db down" not in repr(logs)


async def test_cancellation_is_never_swallowed() -> None:
    events = RecordingSystemEvents(fail_with=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await _report(events, _code_at(-3))


# -- login (`MfaService.verify`) ---------------------------------------------------------------


async def test_login_skewed_code_is_refused_like_a_wrong_code_and_reported(rig: SkewRig) -> None:
    before = _counter()
    with pytest.raises(MfaCodeInvalid) as skewed_error:
        await rig.verify("t-skew", rig.code(SECRET, -3))
    with pytest.raises(MfaCodeInvalid) as wrong_error:
        await rig.verify("t-wrong", "000000")
    assert str(skewed_error.value) == str(wrong_error.value)  # no skew-specific answer: no oracle
    assert [c.attempts for c in rig.repo.challenges.values()] == [1, 1]  # the cap still applies
    assert rig.events.written == [] and _counter() == before  # held: nothing shows yet
    await rig.flush()
    assert _counter() == before + 1  # the wrong code moved nothing
    (event,) = rig.events.written
    assert event.details["offset_steps"] == "-3"


async def test_login_fifth_failed_attempt_still_reports_before_it_locks(rig: SkewRig) -> None:
    for _ in range(CHALLENGE_ATTEMPT_CAP - 1):
        with pytest.raises(MfaCodeInvalid):
            await rig.verify("t", "000000")
    with pytest.raises(MfaChallengeLocked):
        await rig.verify("t", rig.code(SECRET, -3))
    await rig.flush()
    assert [e.details["offset_steps"] for e in rig.events.written] == ["-3"]


async def test_login_with_a_stalled_event_sink_answers_at_once_and_counts_the_attempt() -> None:
    rig = SkewRig(StalledSystemEvents())
    await rig.add_method(SECRET)
    async with asyncio.timeout(5):  # a reporter that awaited its sink would hang here
        with pytest.raises(MfaCodeInvalid, match="invalid TOTP code"):
            await rig.verify("t", rig.code(SECRET, -3))
    assert [c.attempts for c in rig.repo.challenges.values()] == [1]


async def test_login_with_two_methods_applies_each_methods_own_replay_floor() -> None:
    rig = SkewRig()
    first, second = await rig.add_method(SECRET), await rig.add_method(OTHER)
    step = time_step_for(rig.now.timestamp())
    await rig.repo.record_time_step(first, time_step=step - 7)  # below the -6 code below
    await rig.repo.record_time_step(second, time_step=step)  # above it: only `first`'s counts
    with pytest.raises(MfaCodeInvalid):
        await rig.verify("t", rig.code(SECRET, -6))
    await rig.flush()
    assert [e.details["offset_steps"] for e in rig.events.written] == ["-6"]


@pytest.mark.parametrize("steps_later", [2, 5])
async def test_login_replay_of_an_accepted_code_is_not_skew(rig: SkewRig, steps_later: int) -> None:
    accepted = rig.code(SECRET)
    await rig.verify("t-first", accepted)
    rig.advance(steps_later)  # beyond +/-1: refused, and it would read as `steps_later` behind
    before = _counter()
    with pytest.raises(MfaCodeInvalid):
        await rig.verify("t-replay", accepted)
    await rig.flush()
    assert rig.events.written == [] and _counter() == before


# -- enrolment confirm (`MfaService.confirm_enrollment`) ---------------------------------------


async def test_enrolment_confirm_with_a_skewed_code_is_refused_and_reported() -> None:
    rig = SkewRig()
    method_id = await rig.add_method(SECRET, confirmed=False)
    with pytest.raises(MfaCodeInvalid, match="invalid TOTP code"):
        code = rig.code(SECRET, 4)
        await rig.svc.confirm_enrollment(str(rig.user), method_id=method_id, code=code)
    assert rig.repo.methods[method_id].confirmed_at is None  # still pending
    await rig.flush()
    (event,) = rig.events.written
    assert event.details["offset_steps"] == "4"


# -- step-up (`StepUpService`) -----------------------------------------------------------------


async def test_step_up_reports_a_skewed_code_but_not_the_replay_of_an_accepted_one(
    rig: SkewRig,
) -> None:
    sessions, users, hasher = FakeSessionRepository(), FakeUserRepository(), Hasher()
    user = make_user(password_hash=await hasher.hash(PASSWORD)).model_copy(update={"id": rig.user})
    users.add(user)
    minted = await SessionService(sessions, hasher, clock=rig.clock).mint(str(rig.user))
    service = StepUpService(
        rig.repo, sessions, rig.enc, users, hasher, clock=rig.clock, skew_reporter=rig.reporter
    )
    uid, sid, accepted = str(rig.user), str(minted.session_id), rig.code(SECRET)
    await service.step_up(uid, sid, "keys", accepted, PASSWORD)
    rig.advance(2)  # beyond +/-1: the replay is refused, and would read as 2 steps behind
    with pytest.raises(StepUpCodeInvalid) as skewed:
        await service.step_up(uid, sid, "keys", rig.code(SECRET, 3), PASSWORD)
    with pytest.raises(StepUpCodeInvalid) as replay:
        await service.step_up(uid, sid, "keys", accepted, PASSWORD)
    assert (skewed.value.failures_remaining, replay.value.failures_remaining) == (2, 1)  # alike
    await rig.flush()
    (event,) = rig.events.written  # the skewed code only
    assert event.details["offset_steps"] == "3"


# -- wiring and the metric ---------------------------------------------------------------------


async def test_auth_service_gives_login_and_step_up_one_reporter_and_runs_its_publisher() -> None:
    events = RecordingSystemEvents()
    service = AuthService(
        FakeUserRepository(),
        pepper="pepper",
        mfa_repository=FakeMfaRepository(),
        totp_encryption_key=os.urandom(32),
        session_repository=FakeSessionRepository(),
        system_events=events,
    )
    await service.start(ctx=None)  # type: ignore[arg-type]  # the key is given: ctx is not read
    reporter = service.mfa._skew_reporter
    assert reporter._events is events and service.step_up._skew_reporter is reporter
    assert reporter._task is not None and not reporter._task.done()
    await service.stop(1.0)
    assert reporter._task is None  # the publisher ends with the module


def test_build_auth_service_wires_the_system_event_writer_on_the_real_backend_only() -> None:
    real = build_auth_service(
        Settings(
            storage_backend="real",
            auth_totp_key_hex=SecretStr("11" * 32),
            auth_recovery_hmac_key_hex=SecretStr("22" * 32),
            auth_pepper=SecretStr("pepper"),
        )
    )
    assert isinstance(real._system_events, PgSystemEventWriter)
    assert build_auth_service(Settings())._system_events is None


def test_the_skew_counter_is_served_on_the_scraped_registry_with_env() -> None:
    registry = CollectorRegistry()
    collector = export_auth_metrics(registry, env="demo")
    try:
        auth_totp_clock_skew_total.labels(kind=BEHIND).inc(0)
        text = generate_latest(registry).decode()
    finally:
        collector.close()
    assert "auth_totp_clock_skew_total" in AUTH_EXPORTED_NAMES
    assert 'auth_totp_clock_skew_total{env="demo",kind="authenticator_behind"}' in text
