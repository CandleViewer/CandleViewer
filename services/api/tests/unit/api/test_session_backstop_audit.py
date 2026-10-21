"""#3120: the writer side of the `require_active` backstop's audit port (`SessionBackstopAudit`).

`SessionService` calls it once per session it revoked as `user_disabled` and bounds the wait itself
(`tests/unit/auth/test_backstop_audit_port.py`). This side writes `auth.disabled_user_session_
revoked` through the app's shared `RefusalAuditTracker` (C-2.18): at most its cap in flight, never
cancelled mid-append (a shielded, tracked task), drained at shutdown. A write it cannot start or
finish raises, so the service logs the loss, and a record lost by any path adds one, once, to
`auth_audit_outcome_lost_total` (#3009 S4b-1c). `create_app` gives it `_LazyLaneEmitter`: the audit
lane's façade, or the writer while there is none (ADR-0037)."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.api.csrf import AuditEmitterLike, RefusalAuditTracker
from candleviewer.api.session_backstop_audit import (
    LATE_FAILURE_EVENT,
    BackstopAuditSaturated,
    SessionBackstopAudit,
)
from candleviewer.app import _LazyLaneEmitter, create_app
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.service import AuditService, LaneNotWired
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.models import UserStatus
from candleviewer.auth.session_service import BackstopRevocation
from candleviewer.settings import Environment, Settings
from tests.unit.audit.audit_fakes import FakeAuditRepository
from tests.unit.audit.audit_waits import virtual

_USER, _SESSION = uuid.uuid4(), uuid.uuid4()
_ACTION = "auth.disabled_user_session_revoked"


def _lost() -> float:
    """`auth_audit_outcome_lost_total` of the backstop's action."""
    sample = REGISTRY.get_sample_value("auth_audit_outcome_lost_total", {"action": _ACTION})
    return float(sample or 0.0)


class _Emitter:
    """The audit writer's `emit`: records the call, and can be held open or made to fail."""

    def __init__(self, failure: Exception | None = None, held: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.started = asyncio.Event()
        self.gate = asyncio.Event()
        self.failure, self.held = failure, held

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.started.set()
        if self.held:
            await self.gate.wait()
        if self.failure is not None:
            raise self.failure
        self.calls.append((action, kwargs))


def _call(
    emitter: AuditEmitterLike,
    tracker: RefusalAuditTracker,
    status: UserStatus | None = UserStatus.DISABLED,
) -> Any:
    return SessionBackstopAudit(emitter, tracker=tracker)(
        BackstopRevocation(_SESSION, _USER, status)
    )


@pytest.mark.parametrize(
    ("status", "read"),
    [(UserStatus.DISABLED, "disabled"), (None, "gone")],
    ids=["disabled", "gone"],
)
async def test_the_record_names_the_session_its_user_and_the_status_read(
    status: UserStatus | None, read: str
) -> None:
    emitter = _Emitter()

    await _call(emitter, RefusalAuditTracker(), status)

    assert emitter.calls == [
        (
            "auth.disabled_user_session_revoked",
            {
                "actor_label": str(_USER),
                "actor_user_id": _USER,
                "session_id": _SESSION,
                "object_kind": "session",
                "object_id": str(_SESSION),
                "outcome": AuditOutcome.SUCCESS,
                "severity": Severity.WARNING,
                "reason": "user_disabled",
                "after_state": {"user_status": read},
            },
        )
    ]


async def test_a_failed_write_reaches_the_caller_and_leaves_nothing_in_flight() -> None:
    tracker = RefusalAuditTracker()

    with pytest.raises(RuntimeError, match="wal unavailable"):
        await _call(_Emitter(RuntimeError("wal unavailable")), tracker)

    assert len(tracker) == 0


async def test_a_full_tracker_drops_the_record_before_any_write_starts() -> None:
    emitter, tracker, parked = _Emitter(), RefusalAuditTracker(cap=1), _Emitter(held=True)
    tracker.track(parked.emit("parked"))  # one write in flight fills the cap

    with pytest.raises(BackstopAuditSaturated):
        await _call(emitter, tracker)

    assert not emitter.started.is_set()
    parked.gate.set()
    assert await tracker.drain() == 0


async def test_cancelling_the_caller_never_cancels_the_write() -> None:
    """The service stops waiting at its bound, or the request is cancelled: the record lands, and
    shutdown can drain it while it runs."""
    emitter, tracker = _Emitter(held=True), RefusalAuditTracker()
    request = asyncio.create_task(_call(emitter, tracker))
    await asyncio.wait_for(emitter.started.wait(), 5.0)
    assert len(tracker) == 1

    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    emitter.gate.set()

    assert await tracker.drain() == 0
    assert len(emitter.calls) == 1


@pytest.mark.parametrize(
    "held", [True, False], ids=["after_the_cancel", "in_the_cancels_loop_turn"]
)
async def test_a_write_that_fails_after_its_caller_stopped_waiting_is_logged(held: bool) -> None:
    """The tracker logs the failure when the write ends, or at the hand-over if it ended first
    (#3054): one line, with the error class and no session, as the runbook says to count them."""
    emitter, tracker = _Emitter(RuntimeError("wal unavailable"), held), RefusalAuditTracker()
    request = asyncio.create_task(_call(emitter, tracker))
    if held:
        await asyncio.wait_for(emitter.started.wait(), 5.0)
    else:
        await asyncio.sleep(0)  # the request has started the write, which has not run yet

    with capture_logs() as logs:
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        emitter.gate.set()
        assert await tracker.drain() == 0

    late = [e for e in logs if e["event"] == LATE_FAILURE_EVENT]
    assert late == [{"event": LATE_FAILURE_EVENT, "log_level": "error", "error": "RuntimeError"}]


async def test_a_raising_log_never_replaces_the_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    """#3054: the write fails in the cancel's own loop iteration and the log pipeline raises: the
    cancel still propagates, and the log's error goes to the loop's handler, not to the caller."""
    unhandled: list[dict[str, Any]] = []
    asyncio.get_running_loop().set_exception_handler(lambda _loop, ctx: unhandled.append(ctx))
    monkeypatch.setattr("structlog.get_logger", Mock(side_effect=RuntimeError("log down")))
    request = asyncio.create_task(_call(_Emitter(RuntimeError("wal")), RefusalAuditTracker()))
    await asyncio.sleep(0)  # the request has started the write, which has not run yet
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert [str(c["exception"]) for c in unhandled] == ["log down"]


class _Audit:
    """`AuditService` as `_LazyLaneEmitter` reads it: `writer`, and `lane`, its façade, which raises
    `LaneNotWired` while there is none (before `start()`, once `stop()` began)."""

    def __init__(self, writer: _Emitter, lane: _Emitter | None = None) -> None:
        self.writer, self._lane = writer, lane

    @property
    def lane(self) -> _Emitter:
        if self._lane is None:
            raise LaneNotWired("no façade")
        return self._lane


class _BrokenLookup(_Audit):
    """`lane` fails with an error that is not `LaneNotWired` (a `RuntimeError` all the same)."""

    @property
    def lane(self) -> _Emitter:
        raise RuntimeError("the lane lookup is broken")


@virtual
async def test_through_the_real_facade_the_record_is_journaled_first(tmp_path: Path) -> None:
    """EX-08's exit (ADR-0037, #3009): the record is a `reserved` lane frame and the drain hands it
    to the chain once, after the lane's own two rows."""
    repo = FakeAuditRepository()
    audit = AuditService(repo, lane_keys=lambda: (bytes(range(32)), None))  # a test vector
    wal = str(tmp_path / "a.wal")
    settings = SimpleNamespace(audit_wal_path=wal, audit_page_structure_budget=50_000)
    await audit.start(cast(Any, SimpleNamespace(settings=settings)))
    await audit.lane.flush(60.0)  # fake seconds; the lane's own two rows reach the chain first
    lost = _lost()
    with capture_logs() as logs:
        await _call(_LazyLaneEmitter(audit), RefusalAuditTracker())
    await audit.lane.flush(60.0)
    await audit.stop(1.0)
    framed = [(e["cls"], e["action"]) for e in logs if e["event"] == "audit.lane.appended"]
    assert framed == [("reserved", _ACTION)] and _lost() == lost  # journaled: nothing lost
    assert [r["action"] for r in repo.rows] == ["audit.lane_started", "audit.lane_resumed", _ACTION]


@virtual
async def test_without_a_lane_facade_the_writer_takes_the_record_logged_once() -> None:
    """As under the test stack's writer stand-in (`tests/security/auth/test_backstop_audit_
    wiring.py`): today's path, and one warning per emitter, with the action alone."""
    writer, tracker = _Emitter(), RefusalAuditTracker()
    emitter = _LazyLaneEmitter(cast(Any, _Audit(writer)))
    with capture_logs() as logs:
        await _call(emitter, tracker)
        await _call(emitter, tracker)
    assert [action for action, _ in writer.calls] == [_ACTION, _ACTION]
    unwired = [e for e in logs if e["event"] == "audit.lane.unwired"]
    assert unwired == [{"event": "audit.lane.unwired", "log_level": "warning", "action": _ACTION}]


@virtual
async def test_without_a_lane_facade_a_failing_log_never_vetoes_the_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The once-only warning is a diagnostic and the record is the audit (C-2.9): a log pipeline
    that raises must not stop the writer from taking it."""
    monkeypatch.setattr("structlog.get_logger", Mock(side_effect=RuntimeError("log down")))
    writer = _Emitter()
    await _call(_LazyLaneEmitter(cast(Any, _Audit(writer))), RefusalAuditTracker())
    assert [action for action, _ in writer.calls] == [_ACTION]


@virtual
async def test_without_a_lane_facade_a_refusing_writer_raises_its_own_error_alone() -> None:
    """The writer is called outside the handler of the lookup's `LaneNotWired`: its refusal reaches
    the service as itself, not chained to the missing façade."""
    refusal = AuditUnavailable("the writer refused")
    emitter = _LazyLaneEmitter(cast(Any, _Audit(_Emitter(refusal))))
    with pytest.raises(AuditUnavailable) as raised:
        await _call(emitter, RefusalAuditTracker())
    assert raised.value is refusal and refusal.__context__ is None


@virtual
async def test_any_other_error_from_the_lane_lookup_propagates_and_nothing_is_written() -> None:
    """Only `LaneNotWired` means there is no façade. Another error of the lookup is a defect, even
    a `RuntimeError` (`LaneNotWired`'s base): it reaches the service, the writer is not called in
    its place, and no tracked write stays in flight."""
    writer, tracker = _Emitter(), RefusalAuditTracker()
    with pytest.raises(RuntimeError, match="the lane lookup is broken"):
        await _call(_LazyLaneEmitter(cast(Any, _BrokenLookup(writer))), tracker)
    assert writer.calls == [] and len(tracker) == 0


@virtual
async def test_a_record_the_lane_and_the_writer_both_refuse_still_raises_to_the_caller() -> None:
    """The façade refuses only once its writer fallback has refused too: the emitter never writes
    the record again, and the port raises to the service, which logs the loss, as before."""
    lane, writer = _Emitter(AuditUnavailable("the writer refused the fallback")), _Emitter()
    tracker, lost = RefusalAuditTracker(), _lost()
    with pytest.raises(AuditUnavailable):
        await _call(_LazyLaneEmitter(cast(Any, _Audit(writer, lane))), tracker)
    assert writer.calls == [] and len(tracker) == 0
    assert _lost() - lost == 1  # and the loss is counted, once


@virtual
async def test_a_record_the_real_lane_and_writer_both_refuse_is_counted_lost_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EX-08's alert half (#3009 S4b-1c): the lane refuses (`held`), the writer refuses its
    fallback, the façade raises to the service, and `auth_audit_outcome_lost_total` moves by one,
    which a later drain or a second look at the tracker does not repeat."""
    repo = FakeAuditRepository()
    audit = AuditService(repo, lane_keys=lambda: (bytes(range(32)), None))  # a test vector
    settings = SimpleNamespace(
        audit_wal_path=str(tmp_path / "a.wal"), audit_page_structure_budget=50_000
    )
    await audit.start(cast(Any, SimpleNamespace(settings=settings)))
    await audit.lane.flush(60.0)
    assert audit._lane is not None
    audit._lane.journal.hold()  # every append is refused `held`, so the façade falls back

    async def refused(record: Any) -> int:
        raise AuditUnavailable("the writer refused the fallback")

    monkeypatch.setattr(audit.writer, "ingest_counted", refused)
    tracker, lost = RefusalAuditTracker(), _lost()
    with pytest.raises(AuditUnavailable):
        await _call(_LazyLaneEmitter(audit), tracker)
    assert _lost() - lost == 1
    assert await tracker.drain() == 0 and len(tracker) == 0
    assert _lost() - lost == 1
    await audit.stop(1.0)


async def test_a_record_that_lands_counts_nothing_lost() -> None:
    emitter, tracker, lost = _Emitter(), RefusalAuditTracker(), _lost()
    await _call(emitter, tracker)
    assert len(emitter.calls) == 1 and await tracker.drain() == 0
    assert _lost() == lost


@pytest.mark.parametrize(
    "held", [True, False], ids=["after_the_cancel", "in_the_cancels_loop_turn"]
)
async def test_a_write_that_fails_after_its_caller_stopped_waiting_is_counted_lost_once(
    held: bool,
) -> None:
    """The tracker's late report calls the port's `on_lost`, whether the write is still running
    when the caller is cancelled or fails in the cancel's own loop turn (#3054)."""
    emitter, tracker = _Emitter(RuntimeError("wal unavailable"), held), RefusalAuditTracker()
    lost = _lost()
    request = asyncio.create_task(_call(emitter, tracker))
    if held:
        await asyncio.wait_for(emitter.started.wait(), 5.0)
    else:
        await asyncio.sleep(0)  # the request has started the write, which has not run yet
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    emitter.gate.set()
    assert await tracker.drain() == 0
    assert _lost() - lost == 1


async def test_a_write_that_lands_after_its_caller_stopped_waiting_counts_nothing_lost() -> None:
    emitter, tracker = _Emitter(held=True), RefusalAuditTracker()
    lost = _lost()
    request = asyncio.create_task(_call(emitter, tracker))
    await asyncio.wait_for(emitter.started.wait(), 5.0)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    emitter.gate.set()
    assert await tracker.drain() == 0 and len(emitter.calls) == 1
    assert _lost() == lost


@virtual
async def test_a_write_the_shutdown_drain_leaves_running_is_counted_lost_once() -> None:
    """`drain()` counts a write it gives up on (it may be lost); if that write then fails while its
    caller still waits, the caller's report is not a second count."""
    emitter, tracker = _Emitter(AuditUnavailable("refused"), held=True), RefusalAuditTracker()
    lost = _lost()
    request = asyncio.create_task(_call(emitter, tracker))
    await asyncio.wait_for(emitter.started.wait(), 5.0)
    assert await tracker.drain(1.0) == 1  # one fake second, then it gives up
    assert _lost() - lost == 1
    emitter.gate.set()
    with pytest.raises(AuditUnavailable):
        await request
    assert _lost() - lost == 1


async def test_a_record_dropped_at_the_in_flight_cap_is_counted_lost() -> None:
    emitter, tracker, parked = _Emitter(), RefusalAuditTracker(cap=1), _Emitter(held=True)
    tracker.track(parked.emit("parked"))  # one write in flight fills the cap
    lost = _lost()
    with pytest.raises(BackstopAuditSaturated):
        await _call(emitter, tracker)
    assert not emitter.started.is_set() and _lost() - lost == 1
    parked.gate.set()
    assert await tracker.drain() == 0


def test_create_app_hands_the_port_the_lane_emitter(monkeypatch: pytest.MonkeyPatch) -> None:
    ports: list[object] = []

    class _Spy(SessionBackstopAudit):
        def __init__(self, audit: AuditEmitterLike, *, tracker: RefusalAuditTracker) -> None:
            super().__init__(audit, tracker=tracker)
            ports.append(audit)

    monkeypatch.setattr("candleviewer.app.SessionBackstopAudit", _Spy)
    create_app(Settings(environment=Environment.DEMO))
    assert [type(port) for port in ports] == [_LazyLaneEmitter]
