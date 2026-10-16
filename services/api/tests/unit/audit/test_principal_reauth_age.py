"""#2754: the verified principal carries the session's last step-up instant, and `reauth_age_s`
turns it into whole seconds against the clock the caller injects.

This is read-only observability for the `reauth_age_s` key of `admin.area_entered`. Nothing here
may decide what a caller can do: step-up stays enforced by the `DANGEROUS_ROUTES` middleware."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from candleviewer.audit.access import AuditAccessDenied, AuditPrincipal, AuditView, authorize

_STEPPED = datetime(2026, 10, 16, 9, 0, 0, tzinfo=UTC)


def _principal(
    last_step_up_at: datetime | None = None, *perms: str, owner: bool = False
) -> AuditPrincipal:
    return AuditPrincipal(
        user_id=uuid.uuid4(),
        username="u",
        permissions=frozenset(perms),
        is_owner=owner,
        last_step_up_at=last_step_up_at,
    )


def test_reauth_age_is_none_before_any_step_up() -> None:
    assert _principal().reauth_age_s(_STEPPED) is None


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        (timedelta(0), 0),
        (timedelta(milliseconds=999), 0),
        (timedelta(seconds=1), 1),
        (timedelta(seconds=1, milliseconds=999), 1),
        (timedelta(minutes=5), 300),
        (timedelta(minutes=5, microseconds=1), 300),
        (timedelta(minutes=5, seconds=1), 301),
        (timedelta(hours=2, seconds=3), 7203),
    ],
)
def test_reauth_age_is_whole_seconds_rounded_down(elapsed: timedelta, expected: int) -> None:
    age = _principal(_STEPPED).reauth_age_s(_STEPPED + elapsed)
    assert age == expected
    assert type(age) is int


@pytest.mark.parametrize("year", [2001, 2031])
def test_reauth_age_reads_only_the_clock_it_is_given(year: int) -> None:
    """Far from any wall clock, so an age taken from `datetime.now()` cannot equal 42."""
    now = datetime(year, 1, 1, tzinfo=UTC)
    assert _principal(now - timedelta(seconds=42)).reauth_age_s(now) == 42


def test_reauth_age_is_never_negative_when_the_clock_steps_back() -> None:
    assert _principal(_STEPPED).reauth_age_s(_STEPPED - timedelta(seconds=7)) == 0


def test_reauth_age_is_unknown_for_a_naive_datetime_never_a_guess() -> None:
    naive = datetime(2026, 10, 16, 9, 0, 0)  # no tzinfo: the point of the test
    assert _principal(naive).reauth_age_s(_STEPPED) is None
    assert _principal(_STEPPED).reauth_age_s(naive) is None


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append((action, kw))


_STEP_UP_STATES = [None, _STEPPED, _STEPPED - timedelta(days=30)]


@pytest.mark.parametrize("stepped", _STEP_UP_STATES)
async def test_a_step_up_never_changes_what_a_principal_may_do(stepped: datetime | None) -> None:
    holder = _principal(stepped, "audit:read")
    assert holder.has("audit:read") and not holder.has("audit:export")
    assert not _principal(stepped).has("audit:read")
    rec = _Recorder()
    assert await authorize(_principal(stepped, "audit:read", owner=True), "query", rec) is (
        AuditView.RAW
    )
    assert await authorize(_principal(stepped, "audit:read"), "query", rec) is (
        AuditView.OWN_REDACTED
    )
    with pytest.raises(AuditAccessDenied):
        await authorize(_principal(stepped, "audit:read"), "verify", rec)
    with pytest.raises(AuditAccessDenied):
        await authorize(_principal(stepped), "query", rec)
