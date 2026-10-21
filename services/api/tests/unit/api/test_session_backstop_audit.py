"""#3120: the writer side of the `require_active` backstop's audit port (`SessionBackstopAudit`).

`SessionService` calls it once per session it revoked as `user_disabled` and bounds the wait itself
(`tests/unit/auth/test_backstop_audit_port.py`). This side writes `auth.disabled_user_session_
revoked` through the app's shared `RefusalAuditTracker` (C-2.18): at most its cap in flight, never
cancelled mid-append (a shielded, tracked task), drained at shutdown. A write it cannot start or
finish raises, so the service logs the loss. `create_app` gives it `_LazyLaneEmitter`: the audit
lane's façade, or the writer while there is none (ADR-0037)."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
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
from candleviewer.observability.context import bind_context
from candleviewer.settings import Environment, Settings
from tests.unit.audit.audit_fakes import FakeAuditRepository
from tests.unit.audit.audit_waits import virtual

_USER, _SESSION = uuid.uuid4(), uuid.uuid4()
_ACTION = "auth.disabled_user_session_revoked"


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
                "request_id": None,  # no request is bound here (#3990)
            },
        )
    ]


async def test_the_record_carries_the_id_the_correlation_middleware_bound() -> None:
    emitter, bound = _Emitter(), uuid.uuid4()

    with bind_context(request_id=str(bound)):  # as `CorrelationMiddleware` binds it
        await _call(emitter, RefusalAuditTracker())

    assert [kwargs["request_id"] for _, kwargs in emitter.calls] == [bound]


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


@pytest.mark.parametrize("journal_first", [True, False], ids=["flag_on", "flag_off"])
@virtual
async def test_through_the_real_facade_the_record_is_journaled_first_only_with_the_flag_on(
    journal_first: bool, tmp_path: Path
) -> None:
    """EX-08's exit (ADR-0037, #3009): with the flag on the record is a `reserved` lane frame and
    the drain hands it to the chain once; off, the default until S4b-1c, the façade hands it to the
    writer, no lane frame is written for it, and the same three rows reach the sink."""
    repo = FakeAuditRepository()
    audit = AuditService(repo, lane_keys=lambda: (bytes(range(32)), None))  # a test vector
    audit.use_lane_flag(lambda: journal_first)  # S4b-1c deletes this line and the parameter
    wal = str(tmp_path / "a.wal")
    settings = SimpleNamespace(audit_wal_path=wal, audit_page_structure_budget=50_000)
    await audit.start(cast(Any, SimpleNamespace(settings=settings)))
    await audit.lane.flush(60.0)  # fake seconds; the lane's own two rows reach the chain first
    with capture_logs() as logs:
        await _call(_LazyLaneEmitter(audit), RefusalAuditTracker())
    await audit.lane.flush(60.0)
    await audit.stop(1.0)
    framed = [(e["cls"], e["action"]) for e in logs if e["event"] == "audit.lane.appended"]
    assert framed == ([("reserved", _ACTION)] if journal_first else [])
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
    tracker = RefusalAuditTracker()
    with pytest.raises(AuditUnavailable):
        await _call(_LazyLaneEmitter(cast(Any, _Audit(writer, lane))), tracker)
    assert writer.calls == [] and len(tracker) == 0


def test_create_app_hands_the_port_the_lane_emitter(monkeypatch: pytest.MonkeyPatch) -> None:
    ports: list[object] = []

    class _Spy(SessionBackstopAudit):
        def __init__(self, audit: AuditEmitterLike, *, tracker: RefusalAuditTracker) -> None:
            super().__init__(audit, tracker=tracker)
            ports.append(audit)

    monkeypatch.setattr("candleviewer.app.SessionBackstopAudit", _Spy)
    create_app(Settings(environment=Environment.DEMO))
    assert [type(port) for port in ports] == [_LazyLaneEmitter]
