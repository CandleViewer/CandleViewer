"""E27-T04 key-age policy (US-ACCT-005): AC Key age warning, Overdue keys are never auto-disabled,
Policy change recomputes immediately. Age counts from the registration date, never the exchange
expiry, and the evaluator is pure, so nothing waits for a scheduled run."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, get_args

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.accounts.key_age import KeyRotation, KeyRotationPolicy, RotationState
from candleviewer.accounts.models import KeyStatus
from candleviewer.accounts.order_gate import OrderEntryReason
from candleviewer.settings import Settings
from tests.unit.accounts._fakes import DAY, FakeClock

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
    assert rotation.rotation_state is OVERDUE
    assert not [reason for reason in get_args(OrderEntryReason) if "rotation" in reason]


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
    custom = Settings(key_rotation_policy_days=180, key_rotation_warn_days=7)
    assert KeyRotationPolicy.from_settings(custom) == KeyRotationPolicy(180, 7)


@pytest.mark.parametrize(
    "bad",
    [
        {"key_rotation_policy_days": 366},
        {"key_rotation_policy_days": 1},
        {"key_rotation_warn_days": 0},
        {"key_rotation_warn_days": 365},
    ],
)
def test_no_rotation_setting_switches_the_reminder_off(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Settings(**bad)


@pytest.mark.parametrize(("policy", "warn"), [(14, 14), (2, 14), (90, 364)])
def test_settings_reject_a_warning_window_not_inside_the_policy(policy: int, warn: int) -> None:
    with pytest.raises(ValidationError, match="CV_KEY_ROTATION_WARN_DAYS must be less than"):
        Settings(key_rotation_policy_days=policy, key_rotation_warn_days=warn)


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
