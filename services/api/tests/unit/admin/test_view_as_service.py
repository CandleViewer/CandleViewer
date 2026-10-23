"""#3085 S4: `ViewAsService` reads a session's view-as context at the auth clock, ends it exactly
once with one keyed `admin.view_as_ended` it never waits on, and clears it (22 `endViewAs`,
"View-as session"). The store is the fake repository, and the audit writer's own harness stores a
record that must exist once. No sleep: the clock is fake and the test awaits each write's task."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Collection, Coroutine, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.view_as import Ineligible, ViewAsAudit, ViewAsService
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.writer import KEYED_ACTIONS, AuditUnavailable, AuditWriter
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.view_as import ViewAsEndReason, ViewAsPhase, ViewAsState
from candleviewer.observability.context import bind_context
from tests.unit.audit.audit_fakes import FakeAuditRepository, FakeClock
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.auth.test_step_up import _T0, _Clock, _session

_VIEWER, _TARGET = UUID(int=1), UUID(int=2)
_NAMES = {_VIEWER: "ana", _TARGET: "bo"}


def _at(minutes: int) -> datetime:
    return _T0 + timedelta(minutes=minutes)


class _Ports:
    """`AuditWriter.emit_keyed` and the eligibility, socket-closer and label ports, recording each
    call. A port named in `fails` raises that error; one in `holds` waits for a bound or cancel."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.reason: Ineligible | None = None
        self.asked, self.closing = 0, asyncio.Event()
        self.closed: list[tuple[str, str]] = []
        self.closed_contexts: list[UUID | None] = []  # the context each close names
        self.names: Mapping[UUID, str] = _NAMES
        self.fails: dict[str, Exception] = {}
        self.holds: set[str] = set()

    async def _answer[T](self, port: str, value: T) -> T:
        if port in self.holds:
            await asyncio.Event().wait()  # never set
        if port in self.fails:
            raise self.fails[port]
        return value

    async def emit_keyed(self, action: str, name: str, **kwargs: Any) -> None:
        call = {"action": action, "name": name, **kwargs}
        self.calls.append(await self._answer("emit_keyed", call))

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.calls.append(await self._answer("emit", {"action": action, **kwargs}))

    async def ineligible(self, viewer: SessionRecord, target_user_id: UUID) -> Ineligible | None:
        self.asked += 1
        return await self._answer("ineligible", self.reason)

    async def close_family(self, session_id: str, *, context_id: UUID | None, reason: str) -> None:
        self.closed.append((session_id, reason))
        self.closed_contexts.append(context_id)
        self.closing.set()
        await self._answer("close_family", None)

    async def usernames(self, user_ids: Collection[UUID]) -> Mapping[UUID, str]:
        return await self._answer("usernames", self.names)


class _Runner:
    """The app's `RefusalAuditTracker`: each write a task it keeps, none while `full`; `lose` is
    its shutdown drain giving a write up, which it reports through the write's `on_lost`."""

    def __init__(self) -> None:
        self.full = self.lose = False
        self.tasks: list[asyncio.Task[None]] = []

    def track(
        self, coro: Coroutine[Any, Any, None], *, on_lost: Callable[[], None] | None = None
    ) -> None:
        assert on_lost is not None  # a write the shutdown drain abandons is reported
        if self.lose:
            coro.close()
            on_lost()
        else:
            self.tasks.append(asyncio.create_task(coro))


class _Interleaved(FakeSessionRepository):
    """Each end yields before its conditional write, so concurrent ends all reach the store; while
    `mark_fails`, a mark raises (a crash between a record and its mark)."""

    mark_fails = False

    async def end_view_as(self, *args: Any, **kwargs: Any) -> SessionRecord | None:
        await asyncio.sleep(0)
        return await super().end_view_as(*args, **kwargs)

    async def mark_view_as_recorded(self, *args: Any, **kwargs: Any) -> SessionRecord | None:
        if self.mark_fails:
            raise ConnectionError("session store unreachable")
        return await super().mark_view_as_recorded(*args, **kwargs)


class _Rig:
    def __init__(
        self,
        audit: ViewAsAudit | None = None,
        *,
        repo: FakeSessionRepository | None = None,
        **bounds: float,  # `record_timeout_s`, `close_timeout_s`
    ) -> None:
        self.repo = repo or FakeSessionRepository()
        self.runner, self.ports, self.clock = _Runner(), _Ports(), _Clock()
        self.service = ViewAsService(
            self.repo,
            audit or self.ports,
            runner=self.runner,
            eligibility=self.ports,
            sockets=self.ports,
            labels=self.ports,
            clock=self.clock,
            **bounds,
        )

    async def viewing(self) -> SessionRecord:
        """A session of `_VIEWER` holding a live context on `_TARGET`, started at `_T0`."""
        state = ViewAsState.start(uuid4(), _TARGET, now=_T0)
        record = SessionRecord.model_validate({**dict(_session(_VIEWER)), "view_as": state})
        assert await self.repo.create_session(record) is not None
        return record

    def held(self, record: SessionRecord) -> ViewAsState:
        state = self.repo.sessions[str(record.id)].view_as
        assert state is not None
        return state

    async def settled(self) -> None:
        await asyncio.gather(*self.runner.tasks)


async def test_end_exactly_one_record_keyed(tmp_path: Path) -> None:
    """Two concurrent ends of one context: one store apply, one socket close and one record, keyed
    by the context. A crash before its mark leaves the end pending, and writing it again (the
    sweeper's late path) stores no second row: the first written stays."""
    rows = FakeAuditRepository()
    wal = str(tmp_path / "audit.wal")
    writer = AuditWriter(rows, wal, clock=FakeClock(), sleep=rows.retry_sleep)
    await writer.start()
    rig = _Rig(writer, repo=(store := _Interleaved()))
    record = await rig.viewing()
    store.mark_fails = True

    ends = (rig.service.end(record, reason=ViewAsEndReason.ENDED, now=_at(5)) for _ in range(2))
    assert sorted(await asyncio.gather(*ends)) == [False, True]
    await rig.settled()
    assert rig.ports.closed == [(str(record.id), "view_as_changed")] and len(rig.runner.tasks) == 1
    assert rig.held(record).end_pending
    store.mark_fails = False
    assert await rig.service.write_end_record(rig.repo.sessions[str(record.id)], late=True)
    await writer.flush(5)
    await writer.stop(1)

    key = uuid5(KEYED_ACTIONS["admin.view_as_ended"], str(rig.held(record).context_id))
    ended = json.dumps({"ended_at": _at(5).isoformat()})
    assert [(r["record_id"], r["after_state"]) for r in rows.rows] == [(str(key), ended)]
    assert rig.held(record).ended_at == _at(5) and not rig.held(record).end_pending


@pytest.mark.parametrize(
    ("names", "labels"), [(_NAMES, ("ana", "bo")), ({}, (str(_VIEWER), None))], ids=["on", "gone"]
)
async def test_end_record_names_the_viewer_and_no_session_in_its_states(
    names: Mapping[UUID, str], labels: tuple[str, str | None]
) -> None:
    """The record's exact shape. A user whose row is gone has no username: the viewer's id stands
    in for its label and the target has none, so the record never stays pending for want of one."""
    rig = _Rig()
    record = await rig.viewing()
    rig.clock.now, rig.ports.names = _at(6), names
    assert await rig.service.end(record, reason=ViewAsEndReason.ENDED, now=_at(5))
    await rig.settled()

    assert rig.ports.calls == [
        {
            "action": "admin.view_as_ended",
            "name": str(rig.held(record).context_id),
            "actor_label": labels[0],
            "actor_user_id": _VIEWER,
            "session_id": record.id,
            "object_kind": "user",
            "object_id": str(_TARGET),
            "object_label": labels[1],
            "outcome": AuditOutcome.SUCCESS,
            "severity": Severity.WARNING,
            "reason": "ended",
            "before_state": {
                "target_user_id": str(_TARGET),
                "started_at": _T0.isoformat(),
                "expires_at": _at(30).isoformat(),
            },
            "after_state": {"ended_at": _at(5).isoformat()},
            "request_id": None,  # no request is bound here
        }
    ]
    states = json.dumps([rig.ports.calls[0]["before_state"], rig.ports.calls[0]["after_state"]])
    assert str(record.id) not in states and "session" not in states
    assert rig.held(record).end_recorded_at == _at(6)


async def test_end_record_carries_the_id_of_the_request_that_ended_it() -> None:
    """#3990: the record's `request_id` is the id the correlation middleware bound for the ending
    request; the tracked write inherits it."""
    rig = _Rig()
    record = await rig.viewing()
    bound = uuid4()
    with bind_context(request_id=str(bound)):
        assert await rig.service.end(record, reason=ViewAsEndReason.ENDED, now=_at(5))
    await rig.settled()
    assert [call["request_id"] for call in rig.ports.calls] == [bound]


async def _ends_ineligible(reason: Ineligible) -> None:
    rig = _Rig()
    record = await rig.viewing()
    rig.ports.reason = reason

    binding = await rig.service.evaluate(record, now=_at(5))
    await rig.settled()

    assert binding is not None and binding.phase is ViewAsPhase.HELD
    assert (rig.held(record).ended_at, rig.held(record).end_reason) == (_at(5), reason)
    assert rig.ports.closed == [(str(record.id), "view_as_expired")]
    assert [call["reason"] for call in rig.ports.calls] == [reason.value]


async def test_target_promoted_ends_target_ineligible() -> None:
    await _ends_ineligible(ViewAsEndReason.TARGET_INELIGIBLE)


async def test_viewer_without_users_write_ends_viewer_ineligible() -> None:
    await _ends_ineligible(ViewAsEndReason.VIEWER_INELIGIBLE)


async def test_a_failed_eligibility_read_raises_and_ends_nothing() -> None:
    """Fail closed (plan 1.4, C-12.4): a read the port cannot make raises, never answers live."""
    rig = _Rig()
    record = await rig.viewing()
    rig.ports.fails["ineligible"] = ConnectionError("identity store unreachable")
    with pytest.raises(ConnectionError):
        await rig.service.evaluate(record, now=_at(5))
    assert (rig.held(record).ended_at, rig.ports.closed, rig.runner.tasks) == (None, [], [])


async def test_a_revoked_row_evaluates_none_and_only_end_ends_its_context() -> None:
    """A rotated row keeps a copy of the context its successor carries: `evaluate` neither asks
    about nor ends a revoked row's, so that copy never spends the context's one record. `end`, the
    sweeper's path for a revoked session's context, still ends it."""
    rig = _Rig()
    record = await rig.viewing()
    rig.ports.reason = ViewAsEndReason.TARGET_INELIGIBLE
    rotated = await rig.repo.revoke(str(record.id), reason="rotated", now=_at(1))
    assert rotated is not None
    assert await rig.service.evaluate(rotated, now=_at(5)) is None
    assert (rig.ports.asked, rig.ports.closed, rig.held(record).ended_at) == (0, [], None)
    assert await rig.service.end(rotated, reason=ViewAsEndReason.SESSION_ENDED, now=_at(5))
    await rig.settled()
    assert rig.held(record).end_reason == "session_ended" and len(rig.ports.calls) == 1


async def test_expired_context_evaluates_held_writes_nothing_and_ends_expired() -> None:
    """An expiry is read, never written by `evaluate`; an end asked after it is `expired`, at
    `expires_at`, and closes the sockets as a server end."""
    rig = _Rig()
    record = await rig.viewing()
    assert await rig.service.evaluate(_session(_VIEWER), now=_at(1)) is None

    live = await rig.service.evaluate(record, now=_at(30) - timedelta(microseconds=1))
    held = await rig.service.evaluate(record, now=_at(30))
    assert live is not None and live.phase is ViewAsPhase.LIVE
    assert held is not None and held.phase is ViewAsPhase.HELD
    assert rig.ports.asked == 1 and rig.repo.sessions[str(record.id)] == record
    assert (rig.ports.calls, rig.ports.closed, rig.runner.tasks) == ([], [], [])

    assert await rig.service.end(record, reason=ViewAsEndReason.ENDED, now=_at(31))
    await rig.settled()
    assert (rig.held(record).ended_at, rig.held(record).end_reason) == (_at(30), "expired")
    assert [(c["reason"], c["after_state"]) for c in rig.ports.calls] == [
        ("expired", {"ended_at": _at(30).isoformat()})
    ]
    assert rig.ports.closed == [(str(record.id), "view_as_expired")]


_FAILED = {"raises": "AuditUnavailable", "hangs": "TimeoutError", "labels": "ConnectionError"}


@pytest.mark.parametrize("failure", [*_FAILED, "tracker_full", "lost_at_shutdown"])
async def test_failed_or_hung_record_leaves_the_end_pending(failure: str) -> None:
    """`end` returns before its record runs. One that fails (its label read too), outlasts its
    bound, finds the tracker full or is given up by the tracker's shutdown drain leaves the end
    pending on the row, for the sweeper's late write (S5)."""
    rig = _Rig(record_timeout_s=0)
    record = await rig.viewing()
    if failure == "raises":
        rig.ports.fails["emit_keyed"] = AuditUnavailable("audit WAL unavailable")
    if failure == "labels":
        rig.ports.fails["usernames"] = ConnectionError("users store unreachable")
    if failure == "hangs":
        rig.ports.holds.add("emit_keyed")  # only the bound ends the write
    rig.runner.full, rig.runner.lose = failure == "tracker_full", failure == "lost_at_shutdown"

    with capture_logs() as logs:
        assert await rig.service.end(record, reason=ViewAsEndReason.ENDED, now=_at(5))
        assert not any(task.done() for task in rig.runner.tasks)  # it did not wait
        await rig.settled()

    assert rig.held(record).end_pending and rig.ports.calls == []
    assert rig.ports.closed == [(str(record.id), "view_as_changed")]
    context = str(rig.held(record).context_id)
    assert [(log["event"], log["context_id"], log["error"]) for log in logs] == [
        ("admin.view_as_ended.record_pending", context, _FAILED.get(failure, failure))
    ]


async def test_late_record_writes_recorded_late_and_marks_it_recorded() -> None:
    rig = _Rig()
    record = await rig.viewing()
    rig.runner.full = True  # the end's own record never starts: it stays pending
    assert await rig.service.end(record, reason=ViewAsEndReason.ENDED, now=_at(5))
    rig.clock.now = _at(7)

    assert await rig.service.write_end_record(rig.repo.sessions[str(record.id)], late=True)

    late = {"ended_at": _at(5).isoformat(), "recorded_late": True}
    assert [call["after_state"] for call in rig.ports.calls] == [late]
    assert rig.held(record).end_recorded_at == _at(7)
    with pytest.raises(ValueError, match="ended"):
        await rig.service.write_end_record(record, late=True)  # a live context has no end yet


async def test_an_end_that_lost_to_an_earlier_one_closes_nothing_and_records_nothing() -> None:
    rig = _Rig()
    record = await rig.viewing()  # a snapshot read before the end below
    rig.runner.full = True
    assert await rig.service.end(record, reason=ViewAsEndReason.ENDED, now=_at(5))
    ended = rig.repo.sessions[str(record.id)]

    assert not await rig.service.end(record, reason=ViewAsEndReason.SESSION_ENDED, now=_at(6))
    assert not await rig.service.end(ended, reason=ViewAsEndReason.SESSION_ENDED, now=_at(6))

    assert len(rig.ports.closed) == 1 and rig.runner.tasks == []
    assert rig.held(record).end_pending


@pytest.mark.parametrize(
    ("close", "error"), [("raises", "ConnectionError"), ("hangs", "TimeoutError"), ("cancel", "")]
)
async def test_the_record_follows_a_failed_hung_or_cancelled_close(close: str, error: str) -> None:
    """The close is bounded and never fails the end: one that fails or hangs is logged by its
    context, never a session id. A caller cancelled during the close still hands the record over."""
    rig = _Rig(close_timeout_s=0 if close == "hangs" else 2.0)
    record = await rig.viewing()
    if close == "raises":
        rig.ports.fails["close_family"] = ConnectionError("hub unreachable")
    else:
        rig.ports.holds.add("close_family")  # only the bound or the cancel ends the close

    with capture_logs() as logs:
        end = rig.service.end(record, reason=ViewAsEndReason.ENDED, now=_at(5))
        ending = asyncio.create_task(end)
        await asyncio.wait_for(rig.ports.closing.wait(), 5)
        if close == "cancel":
            ending.cancel()
        await asyncio.wait({ending}, timeout=5)  # a guard only: the bound ends a hung close
        await rig.settled()

    assert ending.cancelled() if close == "cancel" else ending.result()
    assert [(log["event"], log["context_id"], log["error"]) for log in logs] == (
        [("admin.view_as.close_failed", str(rig.held(record).context_id), error)] if error else []
    )
    assert str(record.id) not in json.dumps(logs)
    assert len(rig.ports.calls) == 1 and not rig.held(record).end_pending


@pytest.mark.parametrize(("left", "ended", "reason"), [(5, 5, "ended"), (31, 30, "expired")])
async def test_leave_ends_and_clears_in_one_write_with_one_record(
    left: int, ended: int, reason: str
) -> None:
    """The viewer leaves: one write ends the context (`expired` at `expires_at` once that passed)
    and clears it, the sockets close `view_as_changed` and one record follows; a second leave of
    that snapshot changes nothing."""
    rig = _Rig()
    record = await rig.viewing()
    rig.clock.now = _at(40)

    row = await rig.service.leave(record, now=_at(left))
    assert await rig.service.leave(record, now=_at(left)) is None
    await rig.settled()

    held = rig.held(record)
    assert row is not None and row.view_as is not None and row.view_as.cleared_at == _at(left)
    assert (held.ended_at, held.end_reason, held.cleared_at) == (_at(ended), reason, _at(left))
    assert held.end_recorded_at == _at(40) and held.phase(now=_at(left)) is ViewAsPhase.NONE
    assert rig.ports.closed == [(str(record.id), "view_as_changed")]
    assert [call["reason"] for call in rig.ports.calls] == [reason]


async def test_leave_a_held_context_clears_it_and_keeps_its_pending_end() -> None:
    """A context the server ended, its record not yet written: leaving clears it, closes and
    writes nothing more, and the end stays pending for the late write."""
    rig = _Rig()
    record = await rig.viewing()
    rig.runner.full = True  # the server end's record never starts: it stays pending
    assert await rig.service.end(record, reason=ViewAsEndReason.SESSION_ENDED, now=_at(5))
    rig.runner.full = False

    assert await rig.service.leave(rig.repo.sessions[str(record.id)], now=_at(6)) is not None
    assert await rig.service.leave(rig.repo.sessions[str(record.id)], now=_at(7)) is None

    held = rig.held(record)
    assert (held.end_reason, held.cleared_at, held.end_pending) == ("session_ended", _at(6), True)
    assert rig.ports.closed == [(str(record.id), "view_as_expired")]
    assert (rig.ports.calls, rig.runner.tasks) == ([], [])


async def test_an_end_tells_the_closer_which_context_ended() -> None:
    """Only the sockets bound to the ended context close (`HubSocketCloser`): the closer is given
    its id, never only the session's."""
    rig = _Rig()
    record = await rig.viewing()
    assert record.view_as is not None
    assert await rig.service.end(record, reason=ViewAsEndReason.ENDED, now=_at(5))
    await rig.settled()
    assert rig.ports.closed_contexts == [record.view_as.context_id]
