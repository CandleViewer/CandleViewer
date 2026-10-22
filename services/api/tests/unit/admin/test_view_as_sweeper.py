"""#3085: the view-as sweeper ends what no request ends and writes a pending end's record late, and
a role change ends what it makes ineligible before the WebSocket registry re-evaluates (plan 1.2,
1.7). The store is the fake repository and the ports the service tests' recording fakes. No sleep:
the clock is fake, so is the loop's sleep, and each test awaits the records' tasks."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.admin.view_as_sweeper import LIST_LIMIT, ViewAsSweeper
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.view_as import ViewAsEndReason, ViewAsState
from candleviewer.view_as_wiring import RoleChangeNotifier
from tests.unit.admin.test_view_as_service import _TARGET, _VIEWER, _at, _Rig
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.auth.test_step_up import _T0, _session

_GRACE = timedelta(seconds=600)
_QUIET = timedelta(seconds=34)  # the rig's 2 s close and 2 s record, then the 30 s write margin


def _sweeper(rig: _Rig, **kwargs: Any) -> ViewAsSweeper:
    kwargs = {"clock": rig.clock, "interval_s": 5.0, "rotated_grace": _GRACE, **kwargs}
    return ViewAsSweeper(rig.service, rig.repo, **kwargs)


async def _tick(rig: _Rig, sweeper: ViewAsSweeper, at: datetime) -> None:
    rig.clock.now = at
    await sweeper.tick()
    await rig.settled()


def _end(rig: _Rig, record: SessionRecord) -> tuple[datetime | None, str | None]:
    return rig.held(record).ended_at, rig.held(record).end_reason


def _reasons(rig: _Rig) -> list[str | None]:
    return [None if s.view_as is None else s.view_as.end_reason for s in rig.repo.sessions.values()]


async def test_expiry_ends_without_any_request() -> None:
    """At `expires_at` a tick ends the context `expired`, closes its sockets, writes its record."""
    rig = _Rig()
    record = await rig.viewing()
    sweeper = _sweeper(rig)
    await _tick(rig, sweeper, _at(30) - timedelta(microseconds=1))
    assert rig.held(record).ended_at is None
    await _tick(rig, sweeper, _at(31))
    assert _end(rig, record) == (_at(30), "expired") and rig.held(record).end_recorded_at == _at(31)
    assert rig.ports.closed == [(str(record.id), "view_as_expired")]
    assert [c["after_state"] for c in rig.ports.calls] == [{"ended_at": _at(30).isoformat()}]


async def test_pending_end_written_late_recorded_late() -> None:
    """An end whose record found the tracker full stays pending: the next tick writes it late and
    marks it. The gauge reads the pending rows each tick saw."""
    seen: list[float] = []
    rig = _Rig()
    record = await rig.viewing()
    rig.runner.full = True
    assert await rig.service.end(record, reason=ViewAsEndReason.ENDED, now=_at(5))
    rig.runner.full = False
    sweeper = _sweeper(rig, pending=seen.append)
    await _tick(rig, sweeper, _at(6))
    await _tick(rig, sweeper, _at(7))
    late = {"ended_at": _at(5).isoformat(), "recorded_late": True}
    assert [c["after_state"] for c in rig.ports.calls] == [late]
    assert rig.held(record).end_recorded_at == _at(6) and seen == [1, 0]


@pytest.mark.parametrize("made", ["by_a_request", "by_a_leave_after_expiry", "by_the_sweeper"])
async def test_a_late_write_waits_until_the_ends_own_record_cannot_land(made: str) -> None:
    """F9: an end's own record may land until its bounded close and write have run after the end was
    written; a late write before then could race it and stamp `recorded_late` on a record that was
    not late. The wait runs from the end's stamp and adds a margin for its write: `ended_at` (an
    expired end's is `expires_at`), a leave's `cleared_at` or the sweeper's own end."""
    rig = _Rig()
    record = await rig.viewing()
    sweeper = _sweeper(rig)
    rig.runner.full = True  # each end's own record stays pending
    written = _at(5) if made == "by_a_request" else _at(31)
    if made == "by_a_request":
        assert await rig.service.end(record, reason=ViewAsEndReason.ENDED, now=written)
    elif made == "by_a_leave_after_expiry":
        assert await rig.service.leave(record, now=written) is not None
    else:
        await _tick(rig, sweeper, written)
    rig.runner.full = False
    await _tick(rig, sweeper, written + _QUIET - timedelta(microseconds=1))
    assert rig.ports.calls == [] and rig.held(record).end_pending
    await _tick(rig, sweeper, written + _QUIET)
    assert [c["after_state"].get("recorded_late") for c in rig.ports.calls] == [True]


async def test_logout_ends_session_ended() -> None:
    rig = _Rig()
    record = await rig.viewing()
    assert await rig.repo.revoke(str(record.id), reason="logout", now=_at(5)) is not None
    await _tick(rig, _sweeper(rig), _at(6))
    assert _end(rig, record) == (_at(6), "session_ended")
    assert [c["reason"] for c in rig.ports.calls] == ["session_ended"]


async def test_an_absolute_expired_session_ends_session_ended() -> None:
    rig = _Rig()
    record = await rig.viewing()
    rig.repo.sessions[str(record.id)] = record.model_copy(update={"expires_at": _at(10)})
    await _tick(rig, _sweeper(rig), _at(11))
    assert _end(rig, record) == (_at(11), "session_ended")


async def test_rotated_with_successor_not_ended() -> None:
    """A refresh rotated the row and its successor carries the context: past the grace too, the
    rotated copy is not due and the successor's context stays live."""
    rig = _Rig()
    record = await rig.viewing()
    successor = SessionRecord.model_validate({**dict(_session(_VIEWER)), "view_as": record.view_as})
    assert await rig.repo.create_session(successor) is not None
    assert await rig.repo.revoke(str(record.id), reason="rotated", now=_at(1)) is not None
    await _tick(rig, _sweeper(rig), _at(1) + _GRACE + timedelta(minutes=1))
    assert _reasons(rig) == [None, None] and (rig.ports.calls, rig.ports.closed) == ([], [])


async def test_an_orphaned_rotated_row_ends_session_ended_only_after_the_grace() -> None:
    """No successor carries the context (its insert never came): the grace must pass first."""
    rig = _Rig()
    record = await rig.viewing()
    assert await rig.repo.revoke(str(record.id), reason="rotated", now=_at(1)) is not None
    sweeper = _sweeper(rig)
    await _tick(rig, sweeper, _at(1) + _GRACE - timedelta(microseconds=1))
    assert rig.held(record).ended_at is None
    await _tick(rig, sweeper, _at(1) + _GRACE)
    assert _end(rig, record) == (_at(11), "session_ended")


async def test_the_eligibility_pass_ends_a_disabled_targets_context_within_one_tick() -> None:
    rig = _Rig()
    record = await rig.viewing()
    rig.ports.reason = ViewAsEndReason.TARGET_INELIGIBLE  # the port's answer for a disabled target
    await _tick(rig, _sweeper(rig), _at(5))
    assert _end(rig, record) == (_at(5), "target_ineligible")


class _Failing(FakeSessionRepository):
    """An end of a row in `fails` raises: the store fails for that row alone."""

    def __init__(self) -> None:
        super().__init__()
        self.fails: set[str] = set()

    async def end_view_as(self, session_id: str, *args: Any, **kwargs: Any) -> SessionRecord | None:
        if session_id in self.fails:
            raise ConnectionError("session store unreachable")
        return await super().end_view_as(session_id, *args, **kwargs)


async def test_a_failing_row_does_not_stop_the_tick() -> None:
    """It is logged by its context id, never a session id, and the next tick retries it."""
    rig = _Rig(repo=(store := _Failing()))
    first = await rig.viewing()
    await rig.viewing()
    store.fails.add(str(first.id))
    sweeper = _sweeper(rig)
    with capture_logs() as logs:
        await _tick(rig, sweeper, _at(31))
    assert _reasons(rig) == [None, "expired"]
    failed = [
        (e["context_id"], e["error"]) for e in logs if e["event"] == "admin.view_as.sweep_failed"
    ]
    assert failed == [(str(rig.held(first).context_id), "ConnectionError")]
    assert str(first.id) not in json.dumps(logs)
    store.fails.clear()
    await _tick(rig, sweeper, _at(32))
    assert _reasons(rig) == ["expired", "expired"]


async def test_the_tick_is_bounded_and_a_backlog_drains_over_ticks() -> None:
    rig = _Rig()
    for _ in range(3):
        await rig.viewing()
    sweeper = _sweeper(rig, limit=2)
    await _tick(rig, sweeper, _at(31))
    assert sorted(map(str, _reasons(rig))) == ["None", "expired", "expired"]
    await _tick(rig, sweeper, _at(32))
    assert _reasons(rig) == ["expired"] * 3


async def test_a_hung_read_is_cut_at_the_step_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cut read is logged, and the eligibility pass still runs in the same tick."""
    monkeypatch.setattr("candleviewer.admin.view_as_sweeper.STEP_TIMEOUT_S", 0.01)
    rig = _Rig()
    await rig.viewing()
    monkeypatch.setattr(rig.repo, "list_view_as_due", lambda **_: asyncio.Event().wait())
    with capture_logs() as logs:
        await asyncio.wait_for(_tick(rig, _sweeper(rig), _at(5)), 5)  # a guard only
    assert [(e["read"], e["error"]) for e in logs] == [("due", "TimeoutError")]
    assert rig.ports.asked == 1


async def test_the_default_sink_is_the_pending_end_gauge() -> None:
    """A sweeper built with no sink sets `auth_view_as_pending_end_rows`, the series that shows a
    stuck end record."""
    rig = _Rig()
    record = await rig.viewing()
    rig.runner.full = True  # the end's own record stays pending
    assert await rig.service.end(record, reason=ViewAsEndReason.ENDED, now=_at(5))
    await _tick(rig, _sweeper(rig), _at(6))
    assert REGISTRY.get_sample_value("auth_view_as_pending_end_rows") == 1


async def test_a_failed_due_read_keeps_the_gauge(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[float] = []
    rig = _Rig()
    monkeypatch.setattr(rig.repo, "list_view_as_due", AsyncMock(side_effect=OSError("down")))
    await _tick(rig, _sweeper(rig, pending=seen.append), _at(5))
    assert seen == []  # not written: the gauge keeps its last value


async def test_a_role_change_evaluates_the_users_own_and_targeting_contexts_only() -> None:
    """A change of the viewer evaluates the contexts they view from, one of the target those that
    name them; a context of neither is never asked about."""
    rig = _Rig()
    await rig.viewing()  # _VIEWER on _TARGET
    other = ViewAsState.start(uuid4(), UUID(int=4), now=_T0)
    stranger = SessionRecord.model_validate({**dict(_session(UUID(int=3))), "view_as": other})
    assert await rig.repo.create_session(stranger) is not None
    await rig.service.on_roles_changed(_VIEWER)  # still eligible: evaluated, nothing ends
    rig.ports.reason = ViewAsEndReason.TARGET_INELIGIBLE  # the target became an Owner
    await rig.service.on_roles_changed(_TARGET)
    await rig.settled()
    assert _reasons(rig) == ["target_ineligible", None] and rig.ports.asked == 2
    assert [c["reason"] for c in rig.ports.calls] == ["target_ineligible"]


class _Registry:
    """The WebSocket registry's `roles_changed`: it notes what has ended when it runs."""

    def __init__(self, rig: _Rig) -> None:
        self.rig = rig
        self.seen: list[tuple[UUID, list[str | None]]] = []

    async def roles_changed(self, user_id: UUID) -> None:
        self.seen.append((user_id, _reasons(self.rig)))


async def test_the_composite_notifier_runs_the_view_as_hook_before_the_registry() -> None:
    """When the registry re-evaluates the user's sockets, the context the change made ineligible
    has ended."""
    rig = _Rig()
    await rig.viewing()
    registry = _Registry(rig)
    rig.ports.reason = ViewAsEndReason.VIEWER_INELIGIBLE
    await RoleChangeNotifier(rig.service, registry).roles_changed(_VIEWER)
    await rig.settled()
    assert registry.seen == [(_VIEWER, ["viewer_ineligible"])]


async def test_a_failing_hook_still_lets_the_registry_run_and_is_raised_after() -> None:
    """A hook that fails still lets the registry run, and its error is raised after it for the
    route to count (`users.update.step`); the sweeper evaluates the row again."""
    rig = _Rig()
    await rig.viewing()
    registry = _Registry(rig)
    rig.ports.fails["ineligible"] = ConnectionError("identity store unreachable")
    with pytest.raises(ConnectionError):
        await RoleChangeNotifier(rig.service, registry).roles_changed(_VIEWER)
    assert registry.seen == [(_VIEWER, [None])]


async def test_a_hook_that_outlasts_its_bound_still_lets_the_registry_run() -> None:
    """The bound cuts a hook that never answers: the registry runs, then the bound's
    `TimeoutError` is raised for the route to count."""
    rig = _Rig()
    await rig.viewing()
    registry = _Registry(rig)
    rig.ports.holds.add("ineligible")  # the eligibility read never answers
    notifier = RoleChangeNotifier(rig.service, registry, timeout_s=0)
    async with asyncio.timeout(5):  # a guard only: without the bound it fires, outside the raises
        with pytest.raises(TimeoutError):
            await notifier.roles_changed(_VIEWER)
    await rig.settled()
    assert registry.seen == [(_VIEWER, [None])]


async def test_a_cancelled_role_change_still_pushes_and_stays_cancelled() -> None:
    """The registry runs when the request is cancelled inside the hook, and a registry failure
    then is logged by class, never raised in the cancellation's place."""
    rig = _Rig()
    await rig.viewing()
    pushed: list[UUID] = []

    class _Failing:
        async def roles_changed(self, user_id: UUID) -> None:
            pushed.append(user_id)
            raise RuntimeError("identity store unreachable")

    rig.ports.holds.add("ineligible")
    task = asyncio.create_task(RoleChangeNotifier(rig.service, _Failing()).roles_changed(_VIEWER))
    for _ in range(50):  # yield until the hook waits on the eligibility read
        if rig.ports.asked:
            break
        await asyncio.sleep(0)
    with capture_logs() as logs:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert task.cancelled() and pushed == [_VIEWER]
    assert logs == [
        {
            "event": "admin.view_as.registry_push_failed",
            "error": "RuntimeError",
            "log_level": "error",
        }
    ]


async def test_a_role_change_ends_a_failing_rows_siblings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row whose evaluation fails leaves the others to end; its failure is raised after them."""
    rig = _Rig()
    await rig.viewing()
    await rig.viewing()
    rig.ports.reason = ViewAsEndReason.VIEWER_INELIGIBLE
    real, calls = rig.ports.ineligible, [0]

    async def first_fails(viewer: SessionRecord, target_user_id: UUID) -> Any:
        calls[0] += 1
        if calls[0] == 1:
            raise ConnectionError("one row's read")
        return await real(viewer, target_user_id)

    monkeypatch.setattr(rig.ports, "ineligible", first_fails)  # a fault on the first call only
    with pytest.raises(ConnectionError):
        await rig.service.on_roles_changed(_VIEWER)
    await rig.settled()
    assert calls == [2] and sorted(_reasons(rig), key=str) == [None, "viewer_ineligible"]


async def test_a_role_change_reads_the_viewers_contexts_past_any_list_limit() -> None:
    """The viewer's contexts are read by viewer, not picked from a bounded list that other
    viewers' earlier-expiring contexts can fill."""
    rig = _Rig()
    for n in range(LIST_LIMIT + 1):
        other = ViewAsState.start(uuid4(), UUID(int=4), now=_T0 - timedelta(minutes=1))
        row = SessionRecord.model_validate({**dict(_session(UUID(int=1000 + n))), "view_as": other})
        assert await rig.repo.create_session(row) is not None
    await rig.viewing()
    rig.ports.reason = ViewAsEndReason.VIEWER_INELIGIBLE
    await rig.service.on_roles_changed(_VIEWER)
    await rig.settled()
    assert rig.ports.asked == 1 and _reasons(rig).count("viewer_ineligible") == 1


async def test_a_role_change_whose_first_read_fails_still_reads_the_targets_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read that fails leaves the other to run: the target's contexts still end, and the
    failure is raised after them."""
    rig = _Rig()
    await rig.viewing()  # _VIEWER on _TARGET
    down = AsyncMock(side_effect=ConnectionError("by-viewer read"))
    monkeypatch.setattr(rig.repo, "list_live_view_as_by_viewer", down)
    rig.ports.reason = ViewAsEndReason.TARGET_INELIGIBLE
    with pytest.raises(ConnectionError):
        await rig.service.on_roles_changed(_TARGET)
    await rig.settled()
    assert _reasons(rig) == ["target_ineligible"] and down.await_count == 1


async def test_startup_runs_one_tick_then_every_interval_until_stopped() -> None:
    rig = _Rig()
    record = await rig.viewing()
    rig.clock.now = _at(31)
    slept: list[float] = []
    asleep = asyncio.Event()

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        asleep.set()
        await asyncio.Event().wait()  # until the stop cancels the loop

    sweeper = _sweeper(rig, sleep=sleep)
    sweeper.start()
    sweeper.start()  # idempotent: one loop
    await asyncio.wait_for(asleep.wait(), 5)
    assert rig.held(record).end_reason == "expired" and slept == [5.0]
    await sweeper.stop()
    await rig.settled()
    assert [t for t in asyncio.all_tasks() if t.get_name() == "view-as-sweeper"] == []


async def test_a_tick_that_fails_outside_a_step_is_logged_and_the_next_tick_runs() -> None:
    rig = _Rig()
    record = await rig.viewing()
    clock = Mock(side_effect=[OSError("offset file unreadable"), _at(31)])  # read outside any step
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError])
    with capture_logs() as logs, pytest.raises(asyncio.CancelledError):
        await _sweeper(rig, clock=clock, sleep=sleep)._loop()
    await rig.settled()
    failed = {"event": "admin.view_as.tick_failed", "error": "OSError", "log_level": "error"}
    assert logs == [failed] and rig.held(record).end_reason == "expired"


async def test_shutdown_mid_tick_leaves_the_ends_record_to_the_tracker_drain() -> None:
    """The stop cancels a tick inside an end's socket close: the end stands and its record is with
    the tracker, which the lifespan drains next, before audit stops."""
    rig = _Rig()
    record = await rig.viewing()
    rig.clock.now = _at(31)
    rig.ports.holds.add("close_family")
    sweeper = _sweeper(rig)
    sweeper.start()
    await asyncio.wait_for(rig.ports.closing.wait(), 5)
    await sweeper.stop()
    assert len(rig.runner.tasks) == 1
    await rig.settled()  # the drain
    assert rig.held(record).end_recorded_at == _at(31)
    assert [c["reason"] for c in rig.ports.calls] == ["expired"]
