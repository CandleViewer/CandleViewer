"""E42-T10 S13 (#2650, #965 O6): the anonymisation reaper's task. A run walks the due users once in
bounded batches off the request path, one transaction per user (the store's); a user that fails is
counted by its class and passed over, so it never holds back the users after it, and a failure
every later user would share ends the run; a session the anonymisation revoked ends on B16 after
the commit. One log line per batch, counts only. The task runs whatever `retention_enabled` says,
and `?purge=true` schedules through it only while it runs (orchestrator ruling, 2026-10-20); the
deployed app builds it, and the route's door, over one store on the real backend only."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy.exc import DBAPIError, IntegrityError
from structlog.testing import capture_logs

from candleviewer import app as appmod
from candleviewer.settings import Settings
from candleviewer.storage.repositories.user_purge import (
    Anonymised,
    DuePurge,
    PurgeAuditUnavailableError,
    PurgeSchedule,
    PurgeUnavailableError,
)
from candleviewer.storage.repositories.user_purge_sqlalchemy import (
    MAX_ANONYMISE_BATCH,
    SqlAlchemyUserPurgeStore,
)
from candleviewer.storage.retention import policy
from candleviewer.storage.retention.users_purge_tasks import MAX_BATCHES_PER_RUN, UsersPurgeTask
from candleviewer.user_cascade_wiring import PurgedSessions

_AT = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)


def _due(n: int, start: int = 0) -> tuple[DuePurge, ...]:
    """`n` due users in the store's order: one second apart, from `start` seconds after `_AT`."""
    return tuple(DuePurge(_AT + timedelta(seconds=start + i), uuid.uuid4()) for i in range(n))


def _ids(batch: Sequence[DuePurge]) -> list[uuid.UUID]:
    return [d.user_id for d in batch]


class _Store:
    """`due` hands out `batches` in turn (then none), noting the cursor it was given; `anonymise`
    answers from `outcomes`: an `Anonymised` (the default, with no session), `None` (its locked
    re-check skipped the user), or an error."""

    def __init__(
        self,
        batches: Sequence[tuple[DuePurge, ...] | Exception],
        outcomes: dict[uuid.UUID, Anonymised | Exception | None] | None = None,
    ) -> None:
        self.batches, self.outcomes = list(batches), outcomes or {}
        self.calls: list[tuple[str, object]] = []

    async def due(self, limit: int, *, after: DuePurge | None = None) -> tuple[DuePurge, ...]:
        self.calls.append(("due", (limit, after)))
        batch = self.batches.pop(0) if self.batches else ()
        if isinstance(batch, Exception):
            raise batch
        return batch

    async def anonymise(self, user_id: uuid.UUID) -> Anonymised | None:
        self.calls.append(("anonymise", user_id))
        outcome = self.outcomes.get(user_id, Anonymised(user_id, _AT))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def schedule(self, user_id: uuid.UUID, **who: Any) -> PurgeSchedule:
        self.calls.append(("schedule", (user_id, who)))
        return PurgeSchedule(user_id, _AT + timedelta(days=90), changed=True)

    def anonymised(self) -> list[object]:
        return [arg for call, arg in self.calls if call == "anonymise"]

    def reads(self) -> list[object]:
        return [arg for call, arg in self.calls if call == "due"]


class _Sessions:
    """`SessionEnder`: records each session it ends; `fail` raises for the ones it names."""

    def __init__(self, fail: dict[uuid.UUID, BaseException] | None = None) -> None:
        self.ended: list[tuple[uuid.UUID, datetime]] = []
        self.fail = fail or {}

    async def end(self, session_id: uuid.UUID, now: datetime) -> None:
        if session_id in self.fail:
            raise self.fail[session_id]
        self.ended.append((session_id, now))


def _task(store: _Store, sessions: _Sessions | None = None, **kw: Any) -> UsersPurgeTask:
    return UsersPurgeTask(store, sessions=sessions or _Sessions(), **kw)


async def _forever(_: float) -> None:
    """The loop's sleep, never ending: a started task stays running, and reads once."""
    await asyncio.Event().wait()


def _lines(logs: list[Any]) -> list[dict[str, Any]]:
    return [e for e in logs if e["event"] in ("users_anonymised", "users_purge_failed")]


def _line(anonymised: int, outcome: str = "ok", level: str = "info", **kw: Any) -> dict[str, Any]:
    """One batch line as the task logs it: counts and class names only."""
    return {
        "event": "users_anonymised",
        "anonymised": anonymised,
        "skipped": 0,
        "failed": 0,
        "errors": {},
        "sessions_ended": 0,
        "sessions_not_ended": 0,
        "session_errors": {},
        "outcome": outcome,
        "log_level": level,
    } | kw


def test_the_purge_window_is_ninety_days() -> None:
    assert policy.USERS_PURGE_AFTER_DAYS == 90  # US-ADMIN-001, O6


async def test_a_run_anonymises_each_due_user_and_drains_until_a_short_batch() -> None:
    """Each batch's users are anonymised one by one (one transaction each, the store's); the next
    read starts after the last user of the batch, and the run ends at the first short batch; one
    line per batch, counts only (never an id)."""
    full, short = _due(MAX_ANONYMISE_BATCH), _due(3, start=MAX_ANONYMISE_BATCH)
    store = _Store([full, short])
    with capture_logs() as logs:
        await _task(store).run_once()
    assert store.calls == [
        ("due", (MAX_ANONYMISE_BATCH, None)),
        *(("anonymise", u) for u in _ids(full)),
        ("due", (MAX_ANONYMISE_BATCH, full[-1])),
        *(("anonymise", u) for u in _ids(short)),
    ]
    assert _lines(logs) == [_line(MAX_ANONYMISE_BATCH), _line(3)]
    assert not [d for d in (*full, *short) if str(d.user_id) in repr(logs)]


async def test_batch_bounded() -> None:
    """UL4-T2: every read asks for at most `MAX_ANONYMISE_BATCH` users, and one run reads at most
    `MAX_BATCHES_PER_RUN` batches however long the backlog; the next run goes on with it."""
    batches = [_due(MAX_ANONYMISE_BATCH) for _ in range(MAX_BATCHES_PER_RUN + 3)]
    store = _Store(batches)
    await _task(store).run_once()
    assert [limit for limit, _ in store.reads()] == [MAX_ANONYMISE_BATCH] * MAX_BATCHES_PER_RUN
    assert len(store.anonymised()) == MAX_BATCHES_PER_RUN * MAX_ANONYMISE_BATCH


async def test_skipped_users_are_counted_and_the_run_reads_on_past_them() -> None:
    """A user the locked re-check skips (re-enabled, cancelled) is counted, not retried in the
    same run; a full batch of them no longer ends the run: the next read starts after them."""
    full, later = _due(MAX_ANONYMISE_BATCH), _due(2, start=MAX_ANONYMISE_BATCH)
    store = _Store([full, later], {u: None for u in _ids(full)})
    with capture_logs() as logs:
        await _task(store).run_once()
    assert store.reads() == [(MAX_ANONYMISE_BATCH, None), (MAX_ANONYMISE_BATCH, full[-1])]
    assert store.anonymised() == [*_ids(full), *_ids(later)]
    assert _lines(logs) == [_line(0, skipped=MAX_ANONYMISE_BATCH), _line(2)]


async def test_a_poisoned_user_is_counted_by_class_and_the_users_after_it_still_run() -> None:
    """Ruling 4 (a persistently failing row): the oldest due user fails on every run, as a
    username colliding with its surrogate would (the store rolled it back). It is counted by its
    class and passed over; every user after it, in its batch and the next, is anonymised in the
    same run, within the same bounds; the line names the class, never the row or driver text."""
    poisoned, *rest = _due(MAX_ANONYMISE_BATCH)
    later = _due(4, start=MAX_ANONYMISE_BATCH)
    secret = "postgresql://cv:" + "hunter2" + "@db/cv"
    collision = IntegrityError("UPDATE users ...", {}, Exception(secret))
    store = _Store([(poisoned, *rest), later], {poisoned.user_id: collision})
    with capture_logs() as logs:
        await _task(store).run_once()
    assert store.anonymised() == [poisoned.user_id, *_ids(rest), *_ids(later)]
    assert store.reads() == [(MAX_ANONYMISE_BATCH, None), (MAX_ANONYMISE_BATCH, rest[-1])]
    failed = {"failed": 1, "errors": {"IntegrityError": 1}}
    assert _lines(logs) == [
        _line(MAX_ANONYMISE_BATCH - 1, "partial", "error", **failed),
        _line(4),
    ]
    assert "hunter2" not in repr(logs) and str(poisoned.user_id) not in repr(logs)


async def test_the_next_run_retries_the_poisoned_user_first() -> None:
    """Passed over, never dropped: a later run reads it again, oldest first, and anonymises it once
    it no longer fails."""
    (poisoned,) = _due(1)
    store = _Store([(poisoned,), (poisoned,)], {poisoned.user_id: ValueError("check")})
    task = _task(store)
    await task.run_once()
    store.outcomes.clear()
    await task.run_once()
    assert store.anonymised() == [poisoned.user_id, poisoned.user_id]


@pytest.mark.parametrize(
    "error",
    [
        PurgeAuditUnavailableError("audit writer refused"),
        OSError("connection refused"),
        TimeoutError(),
        DBAPIError("SELECT 1", {}, Exception("gone"), connection_invalidated=True),
    ],
    ids=["audit-unavailable", "unreachable", "timeout", "connection-lost"],
)
async def test_a_failure_every_later_user_would_share_ends_the_run(error: Exception) -> None:
    """The audit writer refusing (or late), or the store unreachable, fails every later user the
    same way: the run ends at the first such failure, with what it already anonymised logged,
    and the next run starts again; nothing is read past it."""
    first, failing, later = _due(3)
    store = _Store([(first, failing, later), _due(2, start=3)], {failing.user_id: error})
    with capture_logs() as logs:
        await _task(store).run_once()
    assert store.anonymised() == [first.user_id, failing.user_id]
    assert len(store.reads()) == 1
    name = type(error).__name__
    assert _lines(logs) == [_line(1, "stopped", "error", failed=1, errors={name: 1})]


async def test_sessions_the_anonymisation_revoked_end_on_b16_after_its_commit() -> None:
    """The store revoked the user's live sessions in the anonymisation's transaction; once it has
    committed, each ends as a disable's does (`SessionEnder`: sockets closed, B16 REVOKE at the
    anonymisation's instant), bounded and isolated: one that fails is counted by its class and the
    others still end, and the user stays anonymised."""
    (user,) = _due(1)
    s1, s2, s3 = sorted(uuid.uuid4() for _ in range(3))
    done = Anonymised(user.user_id, _AT, (s1, s2, s3))
    store = _Store([(user,)], {user.user_id: done})
    sessions = _Sessions(fail={s2: LookupError("revoked session row not found")})
    with capture_logs() as logs:
        await _task(store, sessions).run_once()
    assert sessions.ended == [(s1, _AT), (s3, _AT)]
    unended = {"sessions_ended": 2, "sessions_not_ended": 1, "session_errors": {"LookupError": 1}}
    assert _lines(logs) == [_line(1, "partial", "error", **unended)]


async def test_a_session_end_that_hangs_is_cut_by_its_bound() -> None:
    (user,) = _due(1)
    (sid,) = (uuid.uuid4(),)
    store = _Store([(user,)], {user.user_id: Anonymised(user.user_id, _AT, (sid,))})

    class _Hung(_Sessions):
        async def end(self, session_id: uuid.UUID, now: datetime) -> None:
            await asyncio.Event().wait()

    with capture_logs() as logs:
        run = asyncio.create_task(_task(store, _Hung(), session_end_timeout_s=0).run_once())
        done, _ = await asyncio.wait({run}, timeout=5)
    assert run in done and run.exception() is None
    assert _lines(logs)[0]["session_errors"] == {"TimeoutError": 1}


async def test_a_failed_read_is_logged_and_the_loop_survives() -> None:
    store = _Store([OSError("connection refused"), _due(1)])
    ticks, done = 0, asyncio.Event()

    async def sleep(_: float) -> None:
        nonlocal ticks
        ticks += 1
        if ticks == 2:
            done.set()
        await asyncio.sleep(0)

    task = _task(store, sleep=sleep)
    with capture_logs() as logs:
        task.start()
        task.start()  # idempotent: one loop
        assert task.running
        await asyncio.wait_for(done.wait(), 2)
        await task.stop()
    assert _lines(logs)[:2] == [
        {"event": "users_purge_failed", "error": "OSError", "log_level": "error"},
        _line(1),
    ]
    assert not task.running
    await task.stop()  # stopped: a no-op


async def test_schedule_is_refused_unless_the_reaper_runs() -> None:
    """Ruling 2, UL4-D1: `?purge=true` schedules through the task, which refuses while its loop
    is not running (before `start`, after `stop`), with nothing read or written; while it runs,
    the store's `schedule` answers."""
    store, user, actor = _Store([]), uuid.uuid4(), uuid.uuid4()
    task = _task(store, sleep=_forever)
    with pytest.raises(PurgeUnavailableError):
        await task.schedule(user, actor_user_id=actor)
    assert store.calls == []
    task.start()
    scheduled = await task.schedule(user, actor_user_id=actor, request_id=None, session_id=None)
    assert scheduled.changed and store.calls[-1][0] == "schedule"
    await task.stop()
    calls = len(store.calls)
    with pytest.raises(PurgeUnavailableError):
        await task.schedule(user, actor_user_id=actor)
    assert len(store.calls) == calls


def _real(**kw: Any) -> Settings:
    return Settings(  # test-only values, not credentials
        storage_backend="real",
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
        auth_pepper=SecretStr("pepper"),
        **kw,
    )


def _routes(routes: Any) -> list[Any]:
    """Every route, the included routers' too (as the composition guard walks them)."""
    out: list[Any] = []
    for route in routes:
        inner = getattr(route, "original_router", None)
        out += _routes(inner.routes) if inner is not None else [route]
    return out


def _route_purge(app: Any) -> object:
    """The purge door `DELETE /users/{userId}` closes over (the route's `user_purge`)."""
    (route,) = [
        r
        for r in _routes(app.routes)
        if getattr(r, "path", "") == "/users/{userId}" and "DELETE" in getattr(r, "methods", ())
    ]
    cells = [c.cell_contents for c in route.endpoint.__closure__ or ()]
    (door,) = [c for c in cells if isinstance(c, UsersPurgeTask)]
    return door


def test_create_app_builds_the_reaper_and_its_route_door_on_the_real_backend() -> None:
    """The lifespan starts the task (`main.py`); `?purge=true` schedules through it, on the store
    its reaper reads, and its sessions end through the B16 adapter. The fake backend has neither:
    `?purge=true` answers `503 purge_unavailable` there."""
    app = appmod.create_app(_real())
    task = app.state.users_purge_task
    assert isinstance(task, UsersPurgeTask) and task is _route_purge(app)
    assert isinstance(task._store, SqlAlchemyUserPurgeStore)
    assert isinstance(task._sessions, PurgedSessions)
    assert appmod.create_app(Settings()).state.users_purge_task is None


@pytest.mark.parametrize("retention", [True, False], ids=["retention-on", "retention-off"])
async def test_reaper_ignores_retention_flag(retention: bool) -> None:
    """Ruling 1: the purge is a privacy promise, not optional retention. With retention on or
    off, the deployed app builds the reaper and it runs once started, so `?purge=true` is served."""
    task = appmod.create_app(_real(retention_enabled=retention)).state.users_purge_task
    assert isinstance(task, UsersPurgeTask)
    task._sleep, task._store = _forever, _Store([])  # no database: the loop reads a fake
    task.start()
    try:
        assert task.running
    finally:
        await task.stop()
