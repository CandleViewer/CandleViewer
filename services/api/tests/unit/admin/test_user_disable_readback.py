"""#3445 (#2710 option C, R5): `UserDisableService` after a COMMIT that raised, over the S3 store
and the fake unit of work of `test_user_disable.py`. The read-back's bound: the store's tests and
`test_user_lifecycle_pg.py`; the real B16 chart and sockets: `test_disable_commit_readback.py`."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import partial
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.lifecycle_metrics import user_lifecycle_total
from candleviewer.admin.user_disable import DisableResult
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.models import SessionRecord
from candleviewer.observability.context import bind_context
from candleviewer.storage.repositories import owner_floor_sqlalchemy as f
from candleviewer.storage.repositories import user_lifecycle_sqlalchemy as m
from candleviewer.storage.repositories.user_lifecycle import UserStatusChange
from tests.unit.admin.test_user_disable import (
    _OPEN,
    _OWNER,
    _RID,
    _TARGET,
    _UNKNOWN,
    _records,
    _steps,
    _World,
)
from tests.unit.storage.test_user_lifecycle_sqlalchemy import _GUARD_S, _S1, _S2, _Rel

_RECOVERED = ("success", "recovered_after_commit_error", "disabled")
_STEPS_RUN = (  # every step after the commit, for the lost world's two sessions and no rule
    *("socket:user_disabled", "socket:user_disabled", "socket:user", "sweep:user_disabled"),
    *("b16:user_disabled", "b16:user_disabled", "scope", "rules", "rules"),
)
_Append = Callable[[], Awaitable[None]]  # the recovered record's own append


def _landed(rel: _Lost) -> None:
    """All of it landed: the user reads disabled, its sessions revoked at the disable's instant."""
    rel.committed = True
    rel.rows[f.LOCK_USER] = [("disabled",)]
    rel.rows[m._REVOKED_AT] = list(rel.rows[m._REVOKE_SESSIONS])


def _rolled_back(rel: _Lost) -> None:
    """Nothing landed: the user still reads active."""


def _another_disable(rel: _Lost) -> None:
    """This change rolled back and a concurrent disable of the user committed at its own instant."""
    rel.rows[f.LOCK_USER] = [("disabled",)]


class _Lost(_Rel):
    """The S3 store's unit of work, whose COMMIT runs `land`, then raises (lost on the wire). The
    statement after it, the read-back's first, raises `fault` instead, once."""

    def __init__(
        self, land: Callable[[_Lost], None] = _landed, fault: Exception | None = None, **kw: Any
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


def _disables(result: str) -> float:  # `cv_user_lifecycle_total`, read as a delta
    return float(user_lifecycle_total.labels(action="disable", result=result)._value.get())


def _read_back(logs: list[dict[str, Any]]) -> dict[str, Any]:
    (line,) = [e for e in logs if e["event"] == "users.disable.read_back"]
    return line


async def test_lost_commit_that_landed_is_read_back_and_its_sessions_get_the_steps() -> None:
    """AC1, AC2, R5: in a second transaction the user reads back disabled with the two sessions the
    hook saw. `users.disable` `success`, reason `recovered_after_commit_error`, follows
    `outcome_unknown` and goes ahead of the steps, which run for exactly those two (a close and a
    B16 REVOKE each), then close every socket of the user. The call answers as a change (204)."""
    sockets, b16 = list[str](), list[str]()

    async def publish(session_id: str, reason: str) -> None:
        sockets.append(session_id)
        await w.publish(session_id, reason)

    async def revoke(record: SessionRecord, now: object, reason: str) -> None:
        b16.append(str(record.id))
        await w.record(record, now, reason)

    chart = SimpleNamespace(revoke=revoke)
    w = _World(_Lost(sessions=(_S2, _S1)), armed=("r1",), publish=publish, chart=chart)
    disabled, errors = _disables("disabled"), _disables("error")
    with bind_context(request_id=str(_RID)), capture_logs() as logs:
        assert await w.disable() == DisableResult(changed=True)
    assert w.rel.units == 2 and _records(w) == [_OPEN, _UNKNOWN, _RECOVERED]
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
    assert (_disables("disabled"), _disables("error")) == (disabled + 1, errors)


@pytest.mark.parametrize(
    "fault", [OSError("read-back refused"), LookupError("no row")], ids=["store_down", "defect"]
)
async def test_failed_read_back_keeps_the_error_and_a_repeat_is_the_noop(fault: Exception) -> None:
    """AC5: a read-back that raises (a timeout too) leaves today's answer: the commit's own error
    (the route's 503), `outcome_unknown` last, no step. The repeat is AC5's no-op: no record, every
    socket of the user closed, and no session ids for B16."""
    w, errors = _World(_Lost(fault=fault)), _disables("error")
    with capture_logs() as logs, pytest.raises(OSError, match="commit lost"):
        await w.disable()
    assert w.rel.units == 2 and _records(w) == [_OPEN, _UNKNOWN] and w.post_commit() == []
    line = _read_back(logs)
    assert (line["outcome"], line["error"]) == ("failed", type(fault).__name__)
    assert _disables("error") == errors + 1
    assert await w.disable() == DisableResult(changed=False)
    assert _records(w) == [_OPEN, _UNKNOWN] and w.post_commit() == [
        *("socket:user", "sweep:user_disabled", "scope", "rules", "rules"),
    ]


@pytest.mark.parametrize(
    ("land", "outcome"),
    [(_rolled_back, "not_disabled"), (_another_disable, "other_sessions")],
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


async def _hang(*_: Any, **__: Any) -> None:
    await asyncio.Event().wait()


async def _refuse(_: _Append) -> None:
    raise AuditUnavailable("down")


async def _hang_unwritten(_: _Append) -> None:
    await _hang()


async def _hang_appended(append: _Append) -> None:
    await append()  # `AuditWriter.emit` finishes an append that started, whoever stops waiting
    await _hang()


@pytest.mark.parametrize(
    ("recover", "records"),
    [
        (_refuse, [_OPEN, _UNKNOWN]),
        (_hang_unwritten, [_OPEN, _UNKNOWN]),
        (_hang_appended, [_OPEN, _UNKNOWN, _RECOVERED]),
    ],
    ids=["refused", "hung", "appended_then_hung"],
)
async def test_recovered_record_not_confirmed_still_runs_the_steps(
    recover: Callable[[_Append], Awaitable[None]],
    records: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2.9, R5: once the read-back found the change, its steps run even if the recovered record
    is refused or not confirmed within the closing bound, an append that started included: the
    write-ahead record is durable and each step writes its own ahead. That record is a failed
    `closing_record` step, the read-back's line says `record_failed`, and the call is a 204."""
    w = _World(_Lost(), closing_timeout_s=0)
    real = w.emit

    async def emit(action: str, **kwargs: Any) -> None:
        if kwargs.get("reason") == "recovered_after_commit_error":
            return await recover(partial(real, action, **kwargs))
        return await real(action, **kwargs)

    monkeypatch.setattr(w, "emit", emit)
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
    gate = asyncio.Event()
    w = _World(_Lost())
    real = w.emit

    async def emit(action: str, **kwargs: Any) -> None:
        await real(action, **kwargs)
        if kwargs.get("reason") == "recovered_after_commit_error":  # appended; the caller goes
            call.cancel()
            await gate.wait()

    monkeypatch.setattr(w, "emit", emit)
    call = asyncio.create_task(w.disable())
    with pytest.raises(asyncio.CancelledError):
        await call
    gate.set()
    await asyncio.wait_for(w.svc.drain(), _GUARD_S)
    assert _records(w) == [_OPEN, _UNKNOWN, _RECOVERED] and w.post_commit() == [*_STEPS_RUN]


async def test_refused_closing_record_does_not_hold_back_the_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The recovery does not depend on the `outcome_unknown` record: refused, it is missing between
    the two `success` records and an error-level `closing_record` line says so; the read-back still
    finds the change, whose record and steps follow (the trail stays true: the change applied)."""
    w = _World(_Lost())
    real = w.emit

    async def emit(action: str, **kwargs: Any) -> None:
        if kwargs.get("reason") == "outcome_unknown":
            raise AuditUnavailable("down")
        await real(action, **kwargs)

    monkeypatch.setattr(w, "emit", emit)
    with capture_logs() as logs:
        assert await w.disable() == DisableResult(changed=True)
    assert _records(w) == [_OPEN, _RECOVERED] and w.post_commit() == [*_STEPS_RUN]
    closing = [(e["outcome"], e["log_level"]) for e in logs if e.get("step") == "closing_record"]
    assert closing == [("failed", "error"), ("ok", "info")]


async def test_without_sessions_a_concurrent_disable_passes_for_this_one() -> None:
    """The limit UL1-R1 (R5) keeps: with no session there are no ids to tell this change, rolled
    back, from a concurrent disable that committed, so the call is recorded as recovered (204).
    The user is disabled either way and the other call has its own record; only the transaction's
    id would tell them apart."""
    w = _World(_Lost(_another_disable, sessions=()))
    with capture_logs() as logs:
        assert await w.disable() == DisableResult(changed=True)
    assert _records(w) == [_OPEN, _UNKNOWN, _RECOVERED]
    assert _read_back(logs)["outcome"] == "recovered"


async def test_cancelled_commit_is_not_read_back() -> None:
    """Only an error is read back: a cancellation during the commit (the request gone, or a
    shutdown) starts no new work, and `outcome_unknown` stands."""
    committing = asyncio.Event()

    async def commit_hangs(*_: Any, audit: Any, **__: Any) -> Any:
        await audit(UserStatusChange(_TARGET, "active", "disabled", frozenset({"manager"}), (_S1,)))
        committing.set()  # the hook returned: the store sends its commit
        return await _hang()

    read_back = AsyncMock(return_value=(_S1,))
    w = _World(store=SimpleNamespace(disable=commit_hangs, read_back_disable=read_back))
    call = asyncio.create_task(w.disable())
    await asyncio.wait_for(committing.wait(), _GUARD_S)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    assert _records(w) == [_OPEN, _UNKNOWN] and read_back.await_count == 0
