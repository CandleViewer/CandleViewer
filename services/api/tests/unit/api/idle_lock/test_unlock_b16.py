"""`POST /auth/unlock`'s steps on B16 (#2300; B16.7, C-2.21): the lock is recorded before
`unlock()` runs, each outcome is recorded as `UNLOCK_OK` or `UNLOCK_FAILED`, never `REQUEST`,
and a step the chart misses after the session service committed never changes the answer.
A chart that may have recorded a stale row (the session changed under the request) is
dropped, so it never stays locked over an unlocked row."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_chart import SessionChartError
from candleviewer.statechart.bindings import b16_session
from candleviewer.statechart.gateway import (
    GatewayError,
    GatewayOverloadedError,
    LoopAffinityError,
    UnknownMachineError,
)
from tests.conftest import RecordingAuditSink

from ._world import _WRONG, World, _bearer, _FailingB16Sink, _Identity, _open, _unlock

#: What the statechart gateway refuses a send with: an unknown key, the wrong loop, a full inbox.
_REFUSALS = [
    UnknownMachineError("s"),
    LoopAffinityError("s"),
    GatewayOverloadedError("s", "control"),
]


def _miss_once(
    w: World, monkeypatch: pytest.MonkeyPatch, missed: str, error: Exception | None = None
) -> None:
    """B16 fails to record the next *missed* event (*error*, else `SessionChartError`):
    the chart never sees it."""
    record = w.step_up.chart.record
    misses = [missed]

    async def flaky(row: SessionRecord, at: datetime, event: str, **payload: Any) -> None:
        if event in misses:
            misses.remove(event)
            raise error or SessionChartError(f"B16 {event}: test")
        await record(row, at, event, **payload)

    monkeypatch.setattr(w.step_up.chart, "record", flaky)


def _stall_first_observe(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> tuple[asyncio.Event, asyncio.Event]:
    """The first `observe` waits until released, with the row its request read before."""
    observe = w.step_up.chart.observe
    reached, release = asyncio.Event(), asyncio.Event()
    stalls = [True]

    async def late(row: SessionRecord, at: datetime) -> None:
        if stalls:
            stalls.pop()
            reached.set()
            await release.wait()
        await observe(row, at)

    monkeypatch.setattr(w.step_up.chart, "observe", late)
    return reached, release


async def test_lock_record_failing_is_503_with_the_row_still_locked_and_no_password_check(
    b16_audit: RecordingAuditSink,
) -> None:
    """B16.7 regression (b): `auth.idle_locked` is recorded before `unlock()` runs."""
    sink = _FailingB16Sink("auth.idle_locked")
    b16_session.set_audit_sink(sink)
    w = await _open(sink)
    try:
        uid = await w.add_user()
        minted = await w.mint(uid)
        w.lock()
        r = await _unlock(w, _bearer(minted))
        assert r.status_code == 503
        assert (await w.row(minted)).is_idle_locked(now=w.clock.now)
        assert w.failed_logins(uid) == 0 and w.audit.writer.records == []
        sink.fail_on = set()
        retry = await _unlock(w, _bearer(minted))
        assert retry.status_code == 200, retry.text
        assert sink.actions() == ["auth.idle_locked"]
    finally:
        await w.client.aclose()
        await w.step_up.stop()


@pytest.mark.parametrize("refusal", _REFUSALS, ids=lambda refusal: type(refusal).__name__)
async def test_a_gateway_refusal_of_the_lock_record_is_503_with_the_row_still_locked(
    w: World, monkeypatch: pytest.MonkeyPatch, refusal: GatewayError
) -> None:
    """B16.7: the lock is recorded before `unlock()` runs, and a record that cannot be written
    answers 503 with the row still locked. The statechart gateway refusing that step is such a
    failure, never a 500: nothing is checked or audited, the miss is logged, and a retry the
    gateway accepts unlocks."""
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.lock()
    observe, refusals = w.step_up.chart.observe, [refusal]

    async def refuse_once(row: SessionRecord, at: datetime) -> None:
        if refusals:
            raise refusals.pop()
        await observe(row, at)

    monkeypatch.setattr(w.step_up.chart, "observe", refuse_once)
    with capture_logs() as logs:
        r = await _unlock(w, _bearer(minted))
    assert r.status_code == 503
    assert (await w.row(minted)).is_idle_locked(now=w.clock.now)
    assert w.failed_logins(uid) == 0 and w.audit.writer.records == []
    failed = [e for e in logs if e["event"] == "auth.unlock.chart_failed"]
    assert [(e["b16_event"], e["error"]) for e in failed] == [
        ("IDLE_DEADLINE", type(refusal).__name__)
    ]
    assert (await _unlock(w, _bearer(minted))).status_code == 200


async def test_unlock_brings_b16_up_to_the_lock_and_never_sends_request(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B16.7 ("the route records `UNLOCK_OK` or `UNLOCK_FAILED`, never `REQUEST`"): the lock
    is recorded by `observe` before `unlock()` runs, then the unlock itself."""
    minted = await w.mint(await w.add_user())
    w.lock()
    events: list[str] = []
    record = w.step_up.chart.record

    async def spy(row: SessionRecord, at: datetime, event: str, **payload: Any) -> None:
        events.append(event)
        await record(row, at, event, **payload)

    monkeypatch.setattr(w.step_up.chart, "record", spy)
    assert (await _unlock(w, _bearer(minted))).status_code == 200
    assert events == ["UNLOCK_OK"]
    assert w.b16.actions() == ["auth.idle_locked"]
    assert w.chart_state(minted) >= {"auth.active", "elevation.normal"}


async def test_every_wrong_password_is_recorded_as_unlock_failed_the_revoking_one_replayed(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B16.7: each failure is `UNLOCK_FAILED`, which the chart counts while it stays locked;
    the one that revoked the session carries `revoked` (the guard reads it, never the count)
    and `replay` (the route already wrote `auth.session_revoked`)."""
    minted = await w.mint(await w.add_user())
    w.lock()
    sent: list[tuple[str, dict[str, Any]]] = []
    record = w.step_up.chart.record

    async def spy(row: SessionRecord, at: datetime, event: str, **payload: Any) -> None:
        sent.append((event, payload))
        await record(row, at, event, **payload)

    monkeypatch.setattr(w.step_up.chart, "record", spy)
    for _ in range(4):
        await _unlock(w, _bearer(minted), _WRONG)
    chart = w.step_up.chart.interpreter(str(minted.session_id))
    assert chart is not None and chart.context["unlock_attempts"] == 4
    assert "auth.idle_locked" in w.chart_state(minted)
    await _unlock(w, _bearer(minted), _WRONG)
    assert sent == [("UNLOCK_FAILED", {})] * 4 + [
        ("UNLOCK_FAILED", {"revoked": True, "replay": True})
    ]


async def test_an_unlock_the_chart_misses_answers_200_and_the_chart_is_rebuilt_from_the_row(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lift committed with `auth.session_unlocked` written ahead, so a failed `UNLOCK_OK`
    step answers the committed state, 200 and unlocked, never 503 (B16 only records,
    C-2.21). The chart is dropped and rebuilt from the row: the next lock is recorded."""
    minted = await w.mint(await w.add_user())
    w.lock()
    _miss_once(w, monkeypatch, "UNLOCK_OK")
    with capture_logs() as logs:
        r = await _unlock(w, _bearer(minted))
    assert r.status_code == 200, r.text
    assert r.json()["session"]["locked"] is False
    assert w.audit.writer.actions() == ["auth.session_unlocked"]
    failed = [e for e in logs if e["event"] == "auth.unlock.chart_failed"]
    assert [(e["b16_event"], e["error"]) for e in failed] == [("UNLOCK_OK", "SessionChartError")]
    assert w.step_up.chart.interpreter(str(minted.session_id)) is None
    w.lock()
    assert (await _unlock(w, _bearer(minted))).status_code == 200
    assert w.b16.actions() == ["auth.idle_locked", "auth.idle_locked"]


async def test_an_unlock_cancelled_during_its_b16_step_drops_the_chart_and_stays_cancelled(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client goes away while `UNLOCK_OK` is recorded, after `unlock()` committed: the
    cancellation goes on, and the chart is dropped as for a failed step, so it is rebuilt
    from the row and the next lock is recorded."""
    minted = await w.mint(await w.add_user())
    w.lock()
    record = w.step_up.chart.record
    pending, stalls = asyncio.Event(), ["UNLOCK_OK"]

    async def stall(row: SessionRecord, at: datetime, event: str, **payload: Any) -> None:
        if event in stalls:
            stalls.remove(event)
            pending.set()
            await asyncio.Event().wait()  # until the request is cancelled
        await record(row, at, event, **payload)

    monkeypatch.setattr(w.step_up.chart, "record", stall)
    request = asyncio.create_task(_unlock(w, _bearer(minted)))
    await pending.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert not (await w.row(minted)).is_idle_locked(now=w.clock.now)
    assert w.audit.writer.actions() == ["auth.session_unlocked"]
    assert w.step_up.chart.interpreter(str(minted.session_id)) is None
    w.lock()
    assert (await _unlock(w, _bearer(minted))).status_code == 200
    assert w.b16.actions() == ["auth.idle_locked", "auth.idle_locked"]


@pytest.mark.parametrize(
    ("earlier", "code", "revoked_reason"),
    [(0, "unlock_invalid", None), (4, "session_revoked", "unlock_attempts_exceeded")],
)
async def test_a_failure_the_chart_misses_still_answers_what_was_committed(
    w: World,
    monkeypatch: pytest.MonkeyPatch,
    earlier: int,
    code: str,
    revoked_reason: str | None,
) -> None:
    """The wrong password is counted and audited ahead, and the fifth also revoked the
    session: a failed `UNLOCK_FAILED` step answers that, never 503, and drops the chart."""
    minted = await w.mint(await w.add_user())
    w.lock()
    for _ in range(earlier):
        await _unlock(w, _bearer(minted), _WRONG)
    _miss_once(w, monkeypatch, "UNLOCK_FAILED")
    r = await _unlock(w, _bearer(minted), _WRONG)
    assert (r.status_code, r.json()["code"]) == (401, code)
    assert w.audit.writer.actions().count("auth.unlock_failed") == earlier + 1
    assert (await w.row(minted)).revoked_reason == revoked_reason
    assert w.step_up.chart.interpreter(str(minted.session_id)) is None


async def test_an_unlock_overtaken_by_a_concurrent_one_is_409_and_leaves_no_stale_lock(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A double submit: the late request read the row while locked and the other one lifted
    the lock before the late `observe`, which records the lock again. `unlock()` answers 409,
    and the chart, otherwise locked over an unlocked row, is dropped: the next lock is
    recorded."""
    minted = await w.mint(await w.add_user())
    w.lock()
    reached, release = _stall_first_observe(w, monkeypatch)
    late = asyncio.create_task(_unlock(w, _bearer(minted)))
    await reached.wait()
    assert (await _unlock(w, _bearer(minted))).status_code == 200
    release.set()
    r = await late
    assert (r.status_code, r.json()["code"]) == (409, "conflict")
    assert w.audit.writer.actions() == ["auth.session_unlocked"]
    assert w.step_up.chart.interpreter(str(minted.session_id)) is None
    locks = w.b16.actions().count("auth.idle_locked")
    w.lock()
    assert (await _unlock(w, _bearer(minted))).status_code == 200
    assert w.b16.actions().count("auth.idle_locked") == locks + 1
    assert "auth.active" in w.chart_state(minted)


async def _revoke(w: World, session_id: str) -> None:
    await w.sessions.revoke(session_id, reason="logout")


async def _remove(w: World, session_id: str) -> None:
    del w.repo.sessions[session_id]


@pytest.mark.parametrize(
    ("meanwhile", "answer"),
    [(_revoke, (401, "session_revoked", "revoked")), (_remove, (401, None, None))],
    ids=["revoked", "gone"],
)
async def test_an_unlock_of_a_session_ended_meanwhile_checks_nothing_and_drops_the_chart(
    w: World,
    monkeypatch: pytest.MonkeyPatch,
    meanwhile: Callable[[World, str], Awaitable[None]],
    answer: tuple[int, str | None, str | None],
) -> None:
    """Revoked by something else (cause undisclosed), or gone, after the route read the row:
    `unlock()` refuses before any password check, nothing is audited, and the chart `observe`
    built from the stale row is dropped."""
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.lock()
    reached, release = _stall_first_observe(w, monkeypatch)
    late = asyncio.create_task(_unlock(w, _bearer(minted)))
    await reached.wait()
    await meanwhile(w, str(minted.session_id))
    release.set()
    r = await late
    assert (r.status_code, r.json().get("code"), r.json().get("revoked_reason")) == answer
    assert w.failed_logins(uid) == 0 and w.audit.writer.records == []
    assert w.step_up.chart.interpreter(str(minted.session_id)) is None


@pytest.mark.parametrize("refusal", _REFUSALS, ids=lambda refusal: type(refusal).__name__)
async def test_a_gateway_refusal_after_the_commit_answers_200_and_drops_the_chart(
    w: World, monkeypatch: pytest.MonkeyPatch, refusal: GatewayError
) -> None:
    """The statechart gateway refuses `UNLOCK_OK` after the lift committed (an unknown key,
    the wrong loop, a full inbox): the committed unlock is the answer, never 500 or 503,
    the miss is logged, and the chart is dropped as for a step the chart itself failed."""
    minted = await w.mint(await w.add_user())
    w.lock()
    _miss_once(w, monkeypatch, "UNLOCK_OK", refusal)
    with capture_logs() as logs:
        r = await _unlock(w, _bearer(minted))
    assert r.status_code == 200, r.text
    assert r.json()["session"]["locked"] is False
    failed = [e for e in logs if e["event"] == "auth.unlock.chart_failed"]
    assert [(e["b16_event"], e["error"]) for e in failed] == [("UNLOCK_OK", type(refusal).__name__)]
    assert w.step_up.chart.interpreter(str(minted.session_id)) is None


async def test_a_user_removed_after_the_unlock_committed_is_401_never_a_500(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lift committed (`auth.session_unlocked` written ahead), then the user row was gone
    when `SessionInfo` was built: the uniform 401 `/me` answers for a user the identity store no
    longer has, not a 500. The row stays unlocked, and its next use meets #2911's backstop."""
    minted = await w.mint(await w.add_user())
    w.lock()

    async def gone(self: _Identity, user_id: str) -> dict[str, Any]:
        raise LookupError("unknown user")

    monkeypatch.setattr(_Identity, "user", gone)
    r = await _unlock(w, _bearer(minted))
    assert (r.status_code, r.json()["title"]) == (401, "Unauthorized")
    assert w.audit.writer.actions() == ["auth.session_unlocked"]
    assert not (await w.row(minted)).is_idle_locked(now=w.clock.now)
