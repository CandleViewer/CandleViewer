"""#3120: the writer side of the `require_active` backstop's audit port (`SessionBackstopAudit`).

`SessionService` calls it once per session it revoked as `user_disabled` and bounds the wait itself
(`tests/unit/auth/test_backstop_audit_port.py`). This side writes `auth.disabled_user_session_
revoked` through the app's shared `RefusalAuditTracker` (C-2.18): at most its cap in flight, never
cancelled mid-append (a shielded, tracked task), drained at shutdown. A write it cannot start or
finish raises, so the service logs the loss."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import Mock

import pytest
from structlog.testing import capture_logs

from candleviewer.api.csrf import RefusalAuditTracker
from candleviewer.api.session_backstop_audit import (
    LATE_FAILURE_EVENT,
    BackstopAuditSaturated,
    SessionBackstopAudit,
)
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.models import UserStatus
from candleviewer.auth.session_service import BackstopRevocation

_USER, _SESSION = uuid.uuid4(), uuid.uuid4()


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
    emitter: _Emitter, tracker: RefusalAuditTracker, status: UserStatus | None = UserStatus.DISABLED
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
