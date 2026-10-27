"""The exposure read's concurrency and deadline (E27-S04 B2a, #898): CR-01 and CR-02.

CR-01: one hung key never sinks the read. The first key that reads both calls decides (22 Order
(1)) and the others are cancelled; only while no key has read does the read wait, up to its one
deadline, and a key still pending then is a `timeout`, so the request fails closed with a 503.
CR-02: nothing here depends on wall time. Fake readers park on `asyncio.Event` barriers the test
releases, and the deadline is a fake whose expiry is an event the test sets; a deadline the test
never fires proves the read returned without spending it. `REPEAT` (environment
`CV_EXPOSURE_REPEAT`, default 1) repeats every test for the PR's looped run.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from candleviewer.accounts.exposure import (
    ExposureFailed,
    ExposureKnown,
    ExposureRead,
    ExposureUnknown,
    KeyExposure,
    KeyReadFailed,
)
from candleviewer.accounts.models import (
    AccountKind,
    ApiKeyMetadata,
    ExchangeAccount,
    ExchangeEnv,
    KeyStatus,
    PermissionSnapshot,
)

REPEAT = range(int(os.environ.get("CV_EXPOSURE_REPEAT", "1")))
NOW = datetime(2026, 10, 27, tzinfo=UTC)
ACCOUNT = ExchangeAccount(
    id=UUID(int=500), env=ExchangeEnv.DEMO, kind=AccountKind.MAIN, exchange_uid="1000001",
    label="fx-demo", created_at=NOW, updated_at=NOW,
)  # fmt: skip
K1, K2, K3 = UUID(int=1), UUID(int=2), UUID(int=3)
READ = KeyExposure((), 1)
pytestmark = pytest.mark.parametrize("_round", REPEAT)


def key(
    key_id: UUID, status: KeyStatus = KeyStatus.ACTIVE, account: UUID = ACCOUNT.id
) -> ApiKeyMetadata:
    snapshot = PermissionSnapshot.model_validate(
        {"fetched_at": NOW, "uid": "1000001", "permissions": {}}
    )
    return ApiKeyMetadata(
        id=key_id, exchange_account_id=account, label="k", key_id_last4="AbC1",
        permission_snapshot=snapshot, permission_snapshot_at=NOW, created_at=NOW, status=status,
    )  # fmt: skip


@dataclass
class Script:
    """One key's read: it starts, waits for `release`, then answers `result`."""

    result: KeyExposure | KeyReadFailed | BaseException
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: bool = False
    cleanup_entered: asyncio.Event | None = None  # with `cleanup`: gate the cancel's cleanup
    cleanup: asyncio.Event | None = None


class FakeReader:
    def __init__(self, **scripts: Script) -> None:
        self.scripts = {UUID(int=int(name[1:])): s for name, s in scripts.items()}
        self.calls: list[UUID] = []

    async def read(self, account: ExchangeAccount, key_id: UUID) -> KeyExposure:
        assert account is ACCOUNT
        self.calls.append(key_id)
        script = self.scripts[key_id]
        script.started.set()
        try:
            await script.release.wait()
        except asyncio.CancelledError:
            script.cancelled = True
            if script.cleanup_entered is not None and script.cleanup is not None:
                script.cleanup_entered.set()
                await script.cleanup.wait()
            raise
        finally:
            script.finished.set()
        if isinstance(script.result, BaseException):
            raise script.result
        return script.result


class FakeDeadline:
    """`asyncio.timeout` whose expiry is `fire`, set by the test: never wall time."""

    def __init__(self) -> None:
        self.fire, self.limits = asyncio.Event(), list[float]()

    @contextlib.asynccontextmanager
    async def __call__(self, limit: float) -> AsyncIterator[None]:
        self.limits.append(limit)
        async with asyncio.timeout(None) as timer:

            async def expire() -> None:
                await self.fire.wait()
                timer.reschedule(asyncio.get_running_loop().time())

            watcher = asyncio.create_task(expire())
            try:
                yield
            finally:
                watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watcher


def _read(reader: FakeReader, deadline: FakeDeadline, **kw: Any) -> ExposureRead:
    return ExposureRead(reader, env="demo", deadline=deadline, **kw)


async def _settle() -> None:
    """Let every ready task run (loop turns, no wall time)."""
    for _ in range(20):
        await asyncio.sleep(0)


async def test_first_key_wins_hung_key_returns_without_spending_deadline(_round: int) -> None:
    hung, answers = Script(READ), Script(KeyExposure((), 3))
    reader, deadline = FakeReader(k1=hung, k2=answers), FakeDeadline()
    task = asyncio.create_task(_read(reader, deadline).read(ACCOUNT, [key(K1), key(K2)]))
    await hung.started.wait()
    await answers.started.wait()
    answers.release.set()
    assert await task == ExposureKnown(K2, (), 3)
    assert hung.cancelled and not deadline.fire.is_set() and deadline.limits == [0.9]


async def test_first_key_failure_first_then_read_still_wins(_round: int) -> None:
    refused, answers = Script(KeyReadFailed("auth_error")), Script(READ)
    reader, deadline = FakeReader(k1=refused, k2=answers), FakeDeadline()
    task = asyncio.create_task(_read(reader, deadline).read(ACCOUNT, [key(K1), key(K2)]))
    refused.release.set()
    await refused.finished.wait()
    await _settle()
    assert not task.done()
    answers.release.set()
    assert await task == ExposureKnown(K2, (), 1)


async def test_first_key_refusal_next_to_hung_key_503_timeout_never_remedy(_round: int) -> None:
    refused, hung = Script(KeyReadFailed("auth_error", 10003)), Script(READ)
    reader, deadline = FakeReader(k1=refused, k2=hung), FakeDeadline()
    task = asyncio.create_task(_read(reader, deadline).read(ACCOUNT, [key(K1), key(K2)]))
    refused.release.set()
    await refused.finished.wait()
    await hung.started.wait()
    deadline.fire.set()
    got = await task
    assert got == ExposureFailed(503, "timeout", None, ((K1, "auth_error"), (K2, "timeout")))
    assert hung.cancelled


async def test_first_key_all_hung_every_key_timeout_at_deadline(_round: int) -> None:
    a, b = Script(READ), Script(READ)
    reader, deadline = FakeReader(k1=a, k2=b), FakeDeadline()
    task = asyncio.create_task(_read(reader, deadline).read(ACCOUNT, [key(K2), key(K1)]))
    await a.started.wait()
    await b.started.wait()
    deadline.fire.set()
    assert await task == ExposureFailed(503, "timeout", None, ((K1, "timeout"), (K2, "timeout")))
    assert a.cancelled and b.cancelled


@pytest.mark.parametrize(("within", "limit"), [(None, 0.9), (0.4, 0.4), (5.0, 0.9)])
async def test_read_deadline_is_remaining_budget_capped(
    _round: int, within: float | None, limit: float
) -> None:
    reader, deadline = FakeReader(k1=Script(READ)), FakeDeadline()
    reader.scripts[K1].release.set()
    await _read(reader, deadline).read(ACCOUNT, [key(K1)], within_s=within)
    assert deadline.limits == [limit]


async def test_read_no_budget_left_reads_nothing_timeout(_round: int) -> None:
    reader, deadline = FakeReader(k1=Script(READ)), FakeDeadline()
    got = await _read(reader, deadline).read(ACCOUNT, [key(K1)], within_s=0.0)
    assert got == ExposureFailed(503, "timeout", None, ((K1, "timeout"),))
    assert reader.calls == [] and deadline.limits == []


@pytest.mark.parametrize(
    "status", [KeyStatus.PENDING, KeyStatus.EXPIRED, KeyStatus.INVALID, KeyStatus.REVOKED]
)
async def test_read_unsignable_keys_never_read_dead(_round: int, status: KeyStatus) -> None:
    reader, deadline = FakeReader(k1=Script(READ)), FakeDeadline()
    got = await _read(reader, deadline).read(ACCOUNT, [key(K1, status)])
    assert got == ExposureUnknown("leave_positions", ()) and reader.calls == []


async def test_read_rotating_key_is_signable(_round: int) -> None:
    reader, deadline = FakeReader(k1=Script(READ)), FakeDeadline()
    reader.scripts[K1].release.set()
    got = await _read(reader, deadline).read(ACCOUNT, [key(K1, KeyStatus.ROTATING)])
    assert got == ExposureKnown(K1, (), 1)


async def test_read_bounded_concurrency_third_key_waits_for_a_slot(_round: int) -> None:
    a, b, c = Script(KeyReadFailed("timeout")), Script(READ), Script(KeyExposure((), 7))
    reader, deadline = FakeReader(k1=a, k2=b, k3=c), FakeDeadline()
    read = _read(reader, deadline, max_keys=2)
    task = asyncio.create_task(read.read(ACCOUNT, [key(K1), key(K2), key(K3)]))
    await a.started.wait()
    await b.started.wait()
    await _settle()
    assert reader.calls == [K1, K2] and not c.started.is_set()
    a.release.set()
    await c.started.wait()
    c.release.set()
    assert await task == ExposureKnown(K3, (), 7)
    assert b.cancelled


async def test_read_caller_cancelled_cancels_every_key(_round: int) -> None:
    a, b = Script(READ), Script(READ)
    reader, deadline = FakeReader(k1=a, k2=b), FakeDeadline()
    task = asyncio.create_task(_read(reader, deadline).read(ACCOUNT, [key(K1), key(K2)]))
    await a.started.wait()
    await b.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert a.cancelled and b.cancelled


async def test_read_caller_cancel_in_the_wait_is_not_swallowed(_round: int) -> None:
    a = Script(READ)
    reader, deadline = FakeReader(k1=a), FakeDeadline()
    task = asyncio.create_task(_read(reader, deadline).read(ACCOUNT, [key(K1)]))
    await a.started.wait()
    a.release.set()  # the key reads and wins in the same loop turn as the caller's cancel
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_read_caller_cancel_during_loser_cleanup_after_a_win_is_not_swallowed(
    _round: int,
) -> None:
    loser = Script(READ, cleanup_entered=asyncio.Event(), cleanup=asyncio.Event())
    winner = Script(KeyExposure((), 4))
    reader, deadline = FakeReader(k1=loser, k2=winner), FakeDeadline()
    task = asyncio.create_task(_read(reader, deadline).read(ACCOUNT, [key(K1), key(K2)]))
    await loser.started.wait()
    await winner.started.wait()
    winner.release.set()  # the parent raises the win, then waits in the group for the loser
    assert loser.cleanup_entered is not None and loser.cleanup is not None
    await loser.cleanup_entered.wait()
    task.cancel()  # lands on the parent inside the group's exit
    loser.cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not deadline.fire.is_set()


async def test_read_stale_cancel_count_at_entry_is_not_a_cancel(_round: int) -> None:
    a = Script(READ)
    a.release.set()
    reader, deadline = FakeReader(k1=a), FakeDeadline()
    parked, stale = asyncio.Event(), asyncio.Event()

    async def caller() -> object:
        asyncio.current_task().cancel()  # type: ignore[union-attr]  # running inside a task
        try:
            await parked.wait()
        except asyncio.CancelledError:
            stale.set()  # swallowed without uncancel(): cancelling() stays 1
        return await _read(reader, deadline).read(ACCOUNT, [key(K1)])

    assert await asyncio.create_task(caller()) == ExposureKnown(K1, (), 1)
    assert stale.is_set()


async def test_read_reader_defect_propagates(_round: int) -> None:
    reader, deadline = FakeReader(k1=Script(RuntimeError("defect"))), FakeDeadline()
    reader.scripts[K1].release.set()
    with pytest.raises(ExceptionGroup) as caught:
        await _read(reader, deadline).read(ACCOUNT, [key(K1)])
    assert caught.group_contains(RuntimeError)


async def test_read_other_environment_or_foreign_key_refused(_round: int) -> None:
    read = ExposureRead(FakeReader(), env="live", deadline=FakeDeadline())
    with pytest.raises(ValueError, match="environment"):
        await read.read(ACCOUNT, [key(K1)])
    read = ExposureRead(FakeReader(), env="demo", deadline=FakeDeadline())
    with pytest.raises(ValueError, match="another account"):
        await read.read(ACCOUNT, [key(K1, account=UUID(int=9))])


def test_read_constructor_refuses_no_deadline_or_no_slot(_round: int) -> None:
    with pytest.raises(ValueError):
        ExposureRead(FakeReader(), env="demo", deadline_s=0)
    with pytest.raises(ValueError):
        ExposureRead(FakeReader(), env="demo", max_keys=0)
