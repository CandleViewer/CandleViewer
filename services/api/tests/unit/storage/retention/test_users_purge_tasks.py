"""E42-T10 S13 (#2650, #965 O6): the anonymisation reaper's task. Bounded batches off the request
path, one transaction per user (the store's), one log line per batch with counts only; its schedule
entry follows the retention flag like every retention task (UL4-D1); the deployed app builds it,
and the route's purge, over one store on the real backend only."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from candleviewer import app as appmod
from candleviewer.settings import Settings
from candleviewer.storage.repositories.user_purge_sqlalchemy import (
    MAX_ANONYMISE_BATCH,
    SqlAlchemyUserPurgeStore,
)
from candleviewer.storage.retention import policy
from candleviewer.storage.retention.schedule import RetentionSchedule
from candleviewer.storage.retention.users_purge_tasks import MAX_BATCHES_PER_RUN, UsersPurgeTask

_ON = RetentionSchedule.from_env({"CV_RETENTION_ENABLED": "true"})
_OFF = RetentionSchedule.from_env({})


def _ids(n: int) -> tuple[uuid.UUID, ...]:
    return tuple(uuid.uuid4() for _ in range(n))


class _Store:
    """`due` hands out `batches` in turn (then none); `anonymise` answers from `outcomes`: True
    (anonymised, the default), False (its locked re-check skipped the user), or an error."""

    def __init__(
        self,
        batches: Sequence[tuple[uuid.UUID, ...] | Exception],
        outcomes: dict[uuid.UUID, bool | Exception] | None = None,
    ) -> None:
        self.batches, self.outcomes = list(batches), outcomes or {}
        self.calls: list[tuple[str, object]] = []

    async def due(self, limit: int) -> tuple[uuid.UUID, ...]:
        self.calls.append(("due", limit))
        batch = self.batches.pop(0) if self.batches else ()
        if isinstance(batch, Exception):
            raise batch
        return batch

    async def anonymise(self, user_id: uuid.UUID) -> bool:
        self.calls.append(("anonymise", user_id))
        outcome = self.outcomes.get(user_id, True)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _lines(logs: list[Any]) -> list[dict[str, Any]]:
    return [e for e in logs if e["event"] in ("users_anonymised", "users_purge_failed")]


def test_the_schedule_entry_follows_the_retention_flag() -> None:
    assert _OFF.users_purge_jobs() == {}
    assert _ON.users_purge_jobs() == {"users_purge": "0 3 * * *"}
    assert policy.USERS_PURGE_AFTER_DAYS == 90  # US-ADMIN-001, O6


async def test_a_run_anonymises_each_due_user_and_drains_until_a_short_batch() -> None:
    """Each batch's users are anonymised one by one (one transaction each, the store's), and the
    run ends at the first short batch; one line per batch, counts only (never an id)."""
    full, short = _ids(MAX_ANONYMISE_BATCH), _ids(3)
    store = _Store([full, short])
    with capture_logs() as logs:
        await UsersPurgeTask(store, _ON).run_once()
    assert store.calls == [
        ("due", MAX_ANONYMISE_BATCH),
        *(("anonymise", u) for u in full),
        ("due", MAX_ANONYMISE_BATCH),
        *(("anonymise", u) for u in short),
    ]
    assert _lines(logs) == [
        {"event": "users_anonymised", "anonymised": n, "skipped": 0, "outcome": "ok",
         "log_level": "info"}
        for n in (MAX_ANONYMISE_BATCH, 3)
    ]  # fmt: skip
    assert not [u for u in (*full, *short) if str(u) in repr(logs)]


async def test_batch_bounded() -> None:
    """UL4-T2: every read asks for at most `MAX_ANONYMISE_BATCH` users, and one run reads at most
    `MAX_BATCHES_PER_RUN` batches however long the backlog; the next run goes on with it."""
    store = _Store([_ids(MAX_ANONYMISE_BATCH) for _ in range(MAX_BATCHES_PER_RUN + 3)])
    await UsersPurgeTask(store, _ON).run_once()
    reads = [limit for call, limit in store.calls if call == "due"]
    assert reads == [MAX_ANONYMISE_BATCH] * MAX_BATCHES_PER_RUN
    assert len(store.calls) == MAX_BATCHES_PER_RUN * (MAX_ANONYMISE_BATCH + 1)


async def test_skipped_users_are_counted_and_a_batch_with_no_progress_ends_the_run() -> None:
    """A user the locked re-check skips (re-enabled, cancelled) is counted, not retried in the
    same run; a full batch that anonymised no one ends the run, so it never spins on it."""
    full = _ids(MAX_ANONYMISE_BATCH)
    store = _Store([full, _ids(MAX_ANONYMISE_BATCH)], {u: False for u in full})
    with capture_logs() as logs:
        await UsersPurgeTask(store, _ON).run_once()
    assert [c for c, _ in store.calls].count("due") == 1
    assert _lines(logs) == [
        {"event": "users_anonymised", "anonymised": 0, "skipped": MAX_ANONYMISE_BATCH,
         "outcome": "ok", "log_level": "info"}
    ]  # fmt: skip


async def test_a_failure_ends_the_run_and_is_logged_by_class_only() -> None:
    """The first user that fails (audit down, a lock timeout) ends the run: it is rolled back by
    the store, the rest wait for the next run, and the line names the class, never driver text."""
    first, failing, later = _ids(3)
    secret = "postgresql://cv:" + "hunter2" + "@db/cv"
    store = _Store([(first, failing, later), _ids(2)], {failing: RuntimeError(secret)})
    with capture_logs() as logs:
        await UsersPurgeTask(store, _ON).run_once()
    assert store.calls == [
        ("due", MAX_ANONYMISE_BATCH),
        ("anonymise", first),
        ("anonymise", failing),
    ]
    assert _lines(logs) == [
        {"event": "users_anonymised", "anonymised": 1, "skipped": 0, "outcome": "failed",
         "error": "RuntimeError", "log_level": "error"}
    ]  # fmt: skip
    assert "hunter2" not in repr(logs)


async def test_a_failed_read_is_logged_and_the_loop_survives() -> None:
    store = _Store([OSError("connection refused"), _ids(1)])
    ticks, done = 0, asyncio.Event()

    async def sleep(_: float) -> None:
        nonlocal ticks
        ticks += 1
        if ticks == 2:
            done.set()
        await asyncio.sleep(0)

    task = UsersPurgeTask(store, _ON, sleep=sleep)
    with capture_logs() as logs:
        task.start()
        task.start()  # idempotent: one loop
        await asyncio.wait_for(done.wait(), 2)
        await task.stop()
    assert _lines(logs)[:2] == [
        {"event": "users_purge_failed", "error": "OSError", "log_level": "error"},
        {"event": "users_anonymised", "anonymised": 1, "skipped": 0, "outcome": "ok",
         "log_level": "info"},
    ]  # fmt: skip
    assert not task.running
    await task.stop()  # stopped: a no-op


async def test_a_disabled_schedule_never_starts() -> None:
    task = UsersPurgeTask(_Store([]), _OFF)
    task.start()
    assert not task.running


def _real() -> Settings:
    return Settings(  # test-only values, not credentials
        storage_backend="real",
        retention_enabled=True,
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
        auth_pepper=SecretStr("pepper"),
    )


def _routes(routes: Any) -> list[Any]:
    """Every route, the included routers' too (as the composition guard walks them)."""
    out: list[Any] = []
    for route in routes:
        inner = getattr(route, "original_router", None)
        out += _routes(inner.routes) if inner is not None else [route]
    return out


def _route_store(app: Any) -> object:
    """The purge store `DELETE /users/{userId}` closes over (the route's `user_purge`)."""
    (route,) = [
        r
        for r in _routes(app.routes)
        if getattr(r, "path", "") == "/users/{userId}" and "DELETE" in getattr(r, "methods", ())
    ]
    cells = [c.cell_contents for c in route.endpoint.__closure__ or ()]
    (store,) = [c for c in cells if isinstance(c, SqlAlchemyUserPurgeStore)]
    return store


def test_create_app_builds_the_reaper_and_the_route_over_one_store_on_the_real_backend() -> None:
    """The lifespan starts the task (`main.py`); `?purge=true` schedules on the store the reaper
    reads. The fake backend has neither: `?purge=true` answers 501 there."""
    app = appmod.create_app(_real())
    task = app.state.users_purge_task
    assert isinstance(task, UsersPurgeTask) and task._enabled
    assert task._store is _route_store(app)
    assert appmod.create_app(Settings(retention_enabled=True)).state.users_purge_task is None


@pytest.mark.parametrize("enabled", [True, False])
def test_the_task_follows_the_retention_flag_in_the_deployed_app(enabled: bool) -> None:
    settings = _real().model_copy(update={"retention_enabled": enabled})
    task = appmod.create_app(settings).state.users_purge_task
    assert isinstance(task, UsersPurgeTask) and task._enabled is enabled
