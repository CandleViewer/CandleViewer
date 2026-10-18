"""#3445 (#2710 option C, R5): `UserDisableService` after a COMMIT that raised, over the S3 store
and the fake unit of work of `test_user_disable.py`. The bound and the SQL: the store's tests and
`test_user_lifecycle_pg.py`; the real B16 chart: `test_disable_commit_readback.py`."""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from contextlib import asynccontextmanager
from datetime import timedelta
from functools import partial
from types import SimpleNamespace
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.user_disable import DisableResult
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.models import SessionRecord
from candleviewer.observability.context import bind_context
from candleviewer.storage.repositories import owner_floor_sqlalchemy as f
from candleviewer.storage.repositories import user_lifecycle_sqlalchemy as m
from tests.unit.admin.test_user_disable import (
    _OPEN,
    _OWNER,
    _RID,
    _STEPS,
    _TARGET,
    _UNKNOWN,
    _calls,
    _hang,
    _records,
    _steps,
    _World,
)
from tests.unit.auth.test_step_up import _T0 as _NOW
from tests.unit.storage.test_user_lifecycle_sqlalchemy import _GUARD_S, _S1, _S2, _Rel

_REASON = "recovered_after_commit_error"
_RECOVERED = ("success", _REASON, "disabled")
_STEPS_RUN = (  # every step after the commit, for the lost world's two sessions and no rule
    *("socket:user_disabled", "socket:user_disabled", "socket:user", "sweep:user_disabled"),
    *("b16:user_disabled", "b16:user_disabled", "scope", "rules", "rules"),
)
_Append = Callable[[], Awaitable[None]]  # an audit record's own append
_Act = Callable[[_Append], Awaitable[None]]


def _around(w: _World, monkeypatch: pytest.MonkeyPatch, reason: str, act: _Act) -> None:
    """The audit record of `w` with `reason` goes to `act`, given its own append; the rest pass."""
    real = w.emit

    async def emit(action: str, **kwargs: Any) -> None:
        if kwargs.get("reason") == reason:
            return await act(partial(real, action, **kwargs))
        return await real(action, **kwargs)

    monkeypatch.setattr(w, "emit", emit)


def _landed(rel: _Lost) -> None:
    """All of it landed: the user reads disabled, its sessions revoked at the disable's instant."""
    rel.committed = True
    rel.rows[f.LOCK_USER] = [("disabled",)]
    rel.rows[m._REVOKED_AT] = list(rel.rows[m._REVOKE_SESSIONS])


def _another_disable(rel: _Lost) -> None:
    """This change rolled back and a concurrent disable of the user committed at its own instant."""
    rel.rows[f.LOCK_USER] = [("disabled",)]


class _Lost(_Rel):
    """The S3 store's unit of work, whose COMMIT runs `land`, then raises (lost on the wire). The
    statement after it, the read-back's first, raises `fault` instead, once."""

    def __init__(
        self, land: Callable[[_Lost], None] = _landed, fault: BaseException | None = None, **kw: Any
    ) -> None:
        super().__init__(**kw)
        self.land, self.fault, self.armed, self.units = land, fault, False, 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        self.units += 1  # the transactions opened
        async with super().unit_of_work() as uow:

            async def execute(stmt: Any, params: Any = None) -> Any:
                armed, self.armed = self.armed, False
                if armed and self.fault is not None:
                    raise self.fault
                return await uow.session.execute(stmt, params)

            async def commit() -> None:
                self.land(self)
                self.armed = True
                raise OSError("commit lost")

            yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _read_back(logs: list[MutableMapping[str, Any]]) -> MutableMapping[str, Any]:
    (line,) = [e for e in logs if e["event"] == "users.disable.read_back"]
    return line


async def test_lost_commit_that_landed_is_read_back_and_its_sessions_get_the_steps() -> None:
    """AC1, AC2, R5: a second transaction reads the user back disabled with the two sessions the
    hook saw. `users.disable` `success`, reason `recovered_after_commit_error`, follows
    `outcome_unknown`, ahead of the steps: a close and a B16 REVOKE for exactly those two, then
    every socket of the user. The call answers as a change (204)."""
    sockets, b16 = list[str](), list[str]()

    async def publish(session_id: str, reason: str) -> None:
        sockets.append(session_id)
        await w.publish(session_id, reason)

    async def revoke(record: SessionRecord, now: object, reason: str) -> None:
        b16.append(str(record.id))
        await w.record(record, now, reason)

    chart = SimpleNamespace(revoke=revoke)
    rel = _Lost(sessions=(_S2, _S1))
    w = _World(rel, armed=("r1",), publish=publish, chart=chart)
    disabled, errors = _calls("disabled"), _calls("error")
    with bind_context(request_id=str(_RID)), capture_logs() as logs:
        assert await w.disable() == DisableResult(changed=True)
    assert rel.units == 2 and _records(w) == [_OPEN, _UNKNOWN, _RECOVERED]
    assert w.log == [
        *("positions", "orders", "users.disable", "users.disable", "users.disable"),
        *("socket:user_disabled", "socket:user_disabled", "socket:user", "sweep:user_disabled"),
        *("b16:user_disabled", "b16:user_disabled", "scope", "rules", "disarm:r1", "rules"),
    ]
    assert sockets == b16 == [str(_S1), str(_S2)] and w.socket_users == [_TARGET]
    who = {"actor_label": str(_OWNER.user_id), "actor_user_id": _OWNER.user_id, "request_id": _RID}
    who |= {"action": "users.disable", "object_kind": "user", "object_id": str(_TARGET)}
    state = {"status": "active", "roles": ["manager"]}
    assert w.calls[2] == who | {
        "outcome": "success",
        "severity": "warning",
        "reason": "recovered_after_commit_error",
        "before_state": state,
        "after_state": state | {"status": "disabled", "sessions_revoked": 2},
    }
    line = _read_back(logs)
    got = (line["outcome"], line["sessions"], line["commit_error"], line["log_level"])
    assert got == ("recovered", 2, "OSError", "warning")
    assert (_calls("disabled"), _calls("error")) == (disabled + 1, errors)


@pytest.mark.parametrize(
    "fault", [OSError("read-back refused"), LookupError("no row")], ids=["store_down", "defect"]
)
async def test_failed_read_back_keeps_the_error_and_a_repeat_is_the_noop(fault: Exception) -> None:
    """AC5: a read-back that raises (a timeout too) leaves the commit's own error (the route's 503),
    `outcome_unknown` last, no step. The repeat is AC5's no-op: no record, every socket of the user
    closed, no session ids for B16."""
    rel, errors = _Lost(fault=fault), _calls("error")
    w = _World(rel)
    with capture_logs() as logs, pytest.raises(OSError, match="commit lost"):
        await w.disable()
    assert rel.units == 2 and _records(w) == [_OPEN, _UNKNOWN] and w.post_commit() == []
    line = _read_back(logs)
    assert (line["outcome"], line["error"]) == ("failed", type(fault).__name__)
    assert _calls("error") == errors + 1
    assert await w.disable() == DisableResult(changed=False)
    assert _records(w) == [_OPEN, _UNKNOWN] and w.post_commit() == [
        *("socket:user", "sweep:user_disabled", "scope", "rules", "rules"),
    ]


async def test_cancelled_read_back_reaches_the_caller() -> None:
    """A cancellation during the read-back is raised, not swallowed: `outcome_unknown` stands."""
    w = _World(_Lost(fault=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await w.disable()
    assert _records(w) == [_OPEN, _UNKNOWN] and w.post_commit() == []


@pytest.mark.parametrize(
    ("land", "outcome"),
    [(lambda _: None, "not_disabled"), (_another_disable, "other_sessions")],  # nothing landed
    ids=["not_disabled", "other_sessions"],
)
async def test_read_back_that_does_not_find_this_change_keeps_the_error(
    land: Callable[[_Lost], None], outcome: str
) -> None:
    """A user that reads back active, or disabled without the sessions this change revoked at its
    instant (a concurrent disable won), is not this change: no `success` record and no step."""
    w = _World(_Lost(land))
    with capture_logs() as logs, pytest.raises(OSError, match="commit lost"):
        await w.disable()
    assert _records(w) == [_OPEN, _UNKNOWN] and w.post_commit() == []
    assert _read_back(logs)["outcome"] == outcome


async def test_read_back_asks_for_the_instant_the_disable_was_made_at() -> None:
    """The read-back asks for the instant the disable ended its sessions at (`now`, read once), not
    for the clock's reading by then, which has moved on: no row carries it."""
    instants = (_NOW + timedelta(seconds=n) for n in itertools.count(1))
    w = _World(_Lost(), clock=partial(next, instants))
    assert await w.disable() == DisableResult(changed=True)
    ran = dict(w.rel.ran)
    assert ran[m._REVOKED_AT]["at"] == ran[m._REVOKE_SESSIONS]["now"] == _NOW + timedelta(seconds=1)


async def _refuse(_: _Append) -> None:
    raise AuditUnavailable("down")


async def _hang_appended(append: _Append) -> None:
    await append()  # `AuditWriter.emit` finishes an append that started, whoever stops waiting
    await _hang()


@pytest.mark.parametrize(
    ("recover", "records"),
    [
        (_refuse, [_OPEN, _UNKNOWN]),
        (_hang, [_OPEN, _UNKNOWN]),
        (_hang_appended, [_OPEN, _UNKNOWN, _RECOVERED]),
    ],
    ids=["refused", "hung", "appended_then_hung"],
)
async def test_recovered_record_not_confirmed_still_runs_the_steps(
    recover: _Act, records: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.9, R5: once the read-back found the change, its steps run even if the recovered record
    is refused or not confirmed within the closing bound, an append that started included: the
    write-ahead record is durable. That record is a failed `closing_record` step, the read-back's
    line says `record_failed`, and the call is a 204."""
    w = _World(_Lost(), closing_timeout_s=0)
    _around(w, monkeypatch, _REASON, recover)
    failed = _steps("closing_record", "failed")
    with capture_logs() as logs:
        assert await asyncio.wait_for(w.disable(), _GUARD_S) == DisableResult(changed=True)
    assert _records(w) == records and w.post_commit() == [*_STEPS_RUN]
    line = _read_back(logs)
    got = (line["outcome"], line["log_level"], _steps("closing_record", "failed"))
    assert got == ("record_failed", "error", failed + 1)


async def test_caller_cancelled_during_the_recovered_record_leaves_the_steps_to_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R7, C-2.9: the recovered record runs in the steps' shielded task, ahead of them, so a caller
    cancelled once it is appended (the request gone, or a shutdown) cannot leave it in the trail
    with no step after it: the steps run, and `drain` waits for them."""
    gate, w = asyncio.Event(), _World(_Lost())

    async def appended_then_cancelled(append: _Append) -> None:
        await append()
        call.cancel()  # the record is appended; the caller goes
        await gate.wait()

    _around(w, monkeypatch, _REASON, appended_then_cancelled)
    call = asyncio.create_task(w.disable())
    with pytest.raises(asyncio.CancelledError):
        await call
    gate.set()
    await asyncio.wait_for(w.svc.drain(), _GUARD_S)
    assert _records(w) == [_OPEN, _UNKNOWN, _RECOVERED] and w.post_commit() == [*_STEPS_RUN]


async def test_recovered_record_is_not_charged_to_the_steps_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R7, C-2.18: the record has its own closing bound and runs before the steps' deadline starts,
    so a slow one leaves them the whole deadline. Here that deadline is due at once and the record
    waits a turn of the loop: inside it, it would be cut off, and every step with it."""

    async def slow(append: _Append) -> None:
        await asyncio.sleep(0)  # the record is not instant
        await append()

    w = _World(_Lost(), deadline_s=0)
    _around(w, monkeypatch, _REASON, slow)
    assert await w.disable() == DisableResult(changed=True)
    assert _records(w) == [_OPEN, _UNKNOWN, _RECOVERED] and w.post_commit() == [*_STEPS_RUN]


async def test_cancelled_while_the_recovered_record_is_written_fails_every_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R7: the record is inside the steps' `try`, so a cancellation of their task (a shutdown) while
    it is written counts every step as failed, as one during a step does, and reaches the caller."""

    async def cancelled(_: _Append) -> None:
        (steps,) = [t for t in asyncio.all_tasks() if t.get_name() == "user-disable-steps"]
        steps.cancel()
        await _hang()

    w = _World(_Lost(status="invited"))
    _around(w, monkeypatch, _REASON, cancelled)
    with capture_logs() as logs, pytest.raises(asyncio.CancelledError):
        await w.disable()
    lines = [(e["step"], e["outcome"], e["error"]) for e in logs if e.get("step") in _STEPS]
    assert lines == [(step, "failed", "CancelledError") for step in _STEPS]


async def test_refused_closing_record_does_not_hold_back_the_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The recovery does not depend on the `outcome_unknown` record: refused, it is missing between
    the two `success` records and an error-level `closing_record` line says so; the read-back still
    finds the change, whose record and steps follow (the trail stays true: the change applied)."""
    w = _World(_Lost())
    _around(w, monkeypatch, "outcome_unknown", _refuse)
    with capture_logs() as logs:
        assert await w.disable() == DisableResult(changed=True)
    assert _records(w) == [_OPEN, _RECOVERED] and w.post_commit() == [*_STEPS_RUN]
    closing = [(e["outcome"], e["log_level"]) for e in logs if e.get("step") == "closing_record"]
    assert closing == [("failed", "error"), ("ok", "info")]


async def test_without_sessions_a_concurrent_disable_passes_for_this_one() -> None:
    """The limit UL1-R1 (R5) keeps: with no session there are no ids to tell this change, rolled
    back, from a concurrent disable that committed, so the call is recorded as recovered (204). The
    user is disabled either way and the other call has its own record."""
    w = _World(_Lost(_another_disable, sessions=()))
    with capture_logs() as logs:
        assert await w.disable() == DisableResult(changed=True)
    assert _records(w) == [_OPEN, _UNKNOWN, _RECOVERED]
    assert _read_back(logs)["outcome"] == "recovered"
