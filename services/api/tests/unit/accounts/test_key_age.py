"""E27-T04 key-age policy (US-ACCT-005): AC Key age warning, Overdue keys are never auto-disabled,
Policy change recomputes immediately. Age counts from the registration date, never the exchange
expiry, and the evaluator is pure, so nothing waits for a scheduled run."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.accounts.health import AccountHealthMonitor
from candleviewer.accounts.key_age import (
    KeyAgeNotices,
    KeyRotation,
    KeyRotationPolicy,
    RegisteredKey,
    RotationState,
)
from candleviewer.accounts.models import KeyStatus
from candleviewer.accounts.order_gate import AccountHealthCheck, KeyStanding
from candleviewer.domain.order_entry import REFUSAL_REASONS
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.observability.redaction import redact_structure
from candleviewer.settings import Settings
from tests.unit.accounts._fakes import ACC, DAY, Dms, FakeClock, Sizing, Standings

OK, WARN, OVERDUE = RotationState.OK, RotationState.WARN, RotationState.OVERDUE
_TICK = timedelta(microseconds=1)


def _aged(age: timedelta) -> tuple[datetime, datetime]:
    """A key registered now on the fake clock, and the clock's time once the key is `age` old."""
    clock = FakeClock()
    created = clock.now()
    clock.wall += age
    return created, clock.now()


@pytest.mark.parametrize(
    ("age", "state"),
    [(76 * DAY - _TICK, OK), (76 * DAY, WARN), (90 * DAY, WARN), (90 * DAY + _TICK, OVERDUE)],
)
def test_a_76_day_old_key_warns_under_90_days_and_turns_overdue_past_90(
    age: timedelta, state: RotationState
) -> None:
    created, now = _aged(age)
    rotation = KeyRotationPolicy(90, 14).evaluate(created, KeyStatus.ACTIVE, now=now)
    assert rotation == KeyRotation(created + 90 * DAY, state)


def test_an_overdue_key_is_reported_and_never_refuses_orders() -> None:
    created, now = _aged(400 * DAY)
    rotation = KeyRotationPolicy().evaluate(created, KeyStatus.ACTIVE, now=now)
    health = AccountHealthMonitor(FakeClock(), Dms())
    health.track(ACC)
    health.ws_heartbeat(ACC)
    check = AccountHealthCheck(health, Standings({ACC: KeyStanding(True)}), Sizing({ACC: True}))
    assert rotation.rotation_state is OVERDUE and check.refusal(ACC) is None
    assert not [reason for reason in REFUSAL_REASONS if "rotation" in reason]


def test_a_policy_change_recomputes_every_key_on_the_same_call() -> None:
    clock = FakeClock()
    now = clock.now()
    created = {age: now - age * DAY for age in (10, 80, 170)}

    def states(policy: KeyRotationPolicy) -> list[RotationState | None]:
        rotations = [policy.evaluate(c, KeyStatus.ACTIVE, now=now) for c in created.values()]
        return [r.rotation_state for r in rotations]

    assert states(KeyRotationPolicy(90, 14)) == [OK, WARN, OVERDUE]
    assert states(KeyRotationPolicy(180, 14)) == [OK, OK, WARN]
    moved = KeyRotationPolicy(180, 14).evaluate(created[170], KeyStatus.ACTIVE, now=now)
    assert moved.rotation_due_at == created[170] + 180 * DAY


@pytest.mark.parametrize("status", [s for s in KeyStatus if s is not KeyStatus.ACTIVE])
def test_a_key_that_is_not_active_has_no_rotation(status: KeyStatus) -> None:
    created, now = _aged(400 * DAY)
    assert KeyRotationPolicy().evaluate(created, status, now=now) == KeyRotation(None, None)


def test_the_policy_comes_from_settings() -> None:
    assert KeyRotationPolicy.from_settings(Settings()) == KeyRotationPolicy(90, 14)
    custom = Settings(CV_KEY_ROTATION_POLICY_DAYS=180, CV_KEY_ROTATION_WARN_DAYS=7)
    assert KeyRotationPolicy.from_settings(custom) == KeyRotationPolicy(180, 7)


@pytest.mark.parametrize(("policy", "warn"), [(14, 14), (14, 30), (90, 0)])
def test_the_policy_needs_a_warning_window_inside_it(policy: int, warn: int) -> None:
    with pytest.raises(ValueError, match="0 < warn_days < policy_days"):
        KeyRotationPolicy(policy, warn)


_POLICIES = st.integers(2, 365).flatmap(lambda p: st.tuples(st.just(p), st.integers(1, p - 1)))
_CREATED = st.datetimes(datetime(2020, 1, 1), datetime(2030, 1, 1), timezones=st.just(UTC))
_AGES = st.timedeltas(timedelta(0), 800 * DAY)
_ORDERED = {(a, b) for i, a in enumerate(RotationState) for b in list(RotationState)[i:]}


@settings(max_examples=300, deadline=None, derandomize=True)
@given(_POLICIES, _CREATED)
def test_the_state_changes_exactly_at_the_window_start_and_after_the_due_date(
    days: tuple[int, int], created: datetime
) -> None:
    policy = KeyRotationPolicy(*days)
    due = created + timedelta(days=policy.policy_days)
    start = due - timedelta(days=policy.warn_days)
    edges = (start - _TICK, start, due, due + _TICK)
    rotations = [policy.evaluate(created, KeyStatus.ACTIVE, now=edge) for edge in edges]
    assert rotations == [KeyRotation(due, state) for state in (OK, WARN, WARN, OVERDUE)]


@settings(max_examples=300, deadline=None, derandomize=True)
@given(_POLICIES, _CREATED, _AGES, _AGES)
def test_the_state_never_moves_back_as_a_key_ages(
    days: tuple[int, int], created: datetime, a: timedelta, b: timedelta
) -> None:
    policy = KeyRotationPolicy(*days)
    a, b = sorted((a, b))
    first, then = (policy.evaluate(created, KeyStatus.ACTIVE, now=created + t) for t in (a, b))
    assert first.rotation_due_at == then.rotation_due_at == created + policy.policy_days * DAY
    assert (first.rotation_state, then.rotation_state) in _ORDERED


NOTICES, STATES = "cv_key_rotation_notices_total", "cv_keys_rotation_state"


class _Job:
    """The key-age job on a fake clock and a registry of its own (#837 W6)."""

    def __init__(self, policy: KeyRotationPolicy | None = None) -> None:
        self.clock, self.metrics = FakeClock(), Metrics("demo")
        r0 = register_r0(self.metrics)
        job = KeyAgeNotices(
            policy or KeyRotationPolicy(), self.clock, notices=r0[NOTICES], states=r0[STATES]
        )
        self.run = job.observe

    def key(self, age_days: int, n: int = 1, status: KeyStatus = KeyStatus.ACTIVE) -> RegisteredKey:
        """Key `n`, registered `age_days` before the clock's time now."""
        return RegisteredKey(UUID(int=n), ACC, self.clock.now() - age_days * DAY, status)

    def read(self, name: str, *states: RotationState) -> list[float | None]:
        get = self.metrics.registry.get_sample_value
        return [get(name, {"env": "demo", "state": state.value}) for state in states]


def test_the_job_counts_a_key_entering_warn_once_and_logs_its_due_date() -> None:
    job = _Job()
    key = job.key(76)
    with capture_logs() as logs:
        for wait_s in (0.0, 15.0, DAY.total_seconds()):  # boot, the next read, a day on
            job.clock.advance(wait_s)
            job.run([key])
    due = (key.created_at + 90 * DAY).isoformat(timespec="seconds")
    fields = ("event", "state", "key_id", "account_id", "rotation_due_at")
    assert [tuple(e[field] for field in fields) for e in logs] == [
        ("account.key_rotation_notice", "warn", str(UUID(int=1)), str(ACC), due)
    ]
    assert job.read(NOTICES, WARN) == job.read(STATES, WARN) == [1]


def test_the_notice_keeps_its_due_date_through_the_log_redaction() -> None:
    """A stored `created_at` (`timestamptz`) carries microseconds: logged in full, the due date's
    6-digit run would read as a TOTP code and the redaction would replace the value (C-12.6)."""
    job = _Job()
    created = job.clock.now() - 80 * DAY - timedelta(microseconds=123_456)
    with capture_logs() as logs:
        job.run([RegisteredKey(UUID(int=1), ACC, created, KeyStatus.ACTIVE)])
    [event] = logs
    assert redact_structure(event) == event
    assert event["rotation_due_at"] == (created + 90 * DAY).isoformat(timespec="seconds")


def test_the_job_counts_an_overdue_key_once_a_day_and_never_disables_it() -> None:
    job = _Job()
    key = job.key(91)
    with capture_logs() as logs:
        for wait_s in (0.0, DAY.total_seconds() - 1):
            job.clock.advance(wait_s)
            job.run([key])
    assert [e["state"] for e in logs] == ["overdue"] and job.read(NOTICES, OVERDUE) == [1]
    job.clock.advance(1)
    job.run([key])
    assert job.read(NOTICES, OVERDUE) == [2]
    assert key.status is KeyStatus.ACTIVE  # it only reports: there is nothing to disable with


def test_the_job_sets_the_active_keys_per_state_and_counts_a_returning_key_again() -> None:
    job = _Job()
    keys = [job.key(10, 1), job.key(80, 2), job.key(100, 3), job.key(100, 4, KeyStatus.ROTATING)]
    job.run(keys)
    assert job.read(STATES, OK, WARN, OVERDUE) == [1, 1, 1]
    job.run([])  # every key gone, a rotation say
    assert job.read(STATES, OK, WARN, OVERDUE) == [0, 0, 0]
    job.run(keys)  # back: each is counted again, the overdue one at once
    assert job.read(NOTICES, WARN, OVERDUE) == [2, 2]


def test_a_policy_change_takes_effect_at_the_first_read_of_the_job_built_with_it() -> None:
    job = _Job(KeyRotationPolicy(180, 14))
    job.run([job.key(100)])  # overdue under 90 days, fine under 180
    assert job.read(STATES, OK, WARN, OVERDUE) == [1, 0, 0]
    assert job.read(NOTICES, WARN, OVERDUE) == [None, None]  # never counted
