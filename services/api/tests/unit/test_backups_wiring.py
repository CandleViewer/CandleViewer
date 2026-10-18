"""Unit (E42-T05, #966 BK-7): the backups composition: stable job codes (C-12.6), unknown
positions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.backups.ports import BackupJobError, JobEnd, JobErrorCode, OpenPositions
from candleviewer.admin.errors import PositionsUnknownError
from candleviewer.api.recorder_admin import AdminJobStore
from candleviewer.backups_wiring import AdminJobRunner, UnknownOpenPositions

_PATH = "/srv/cv/backups/2026-10-18/pg_dump.age"


async def _failed(raised: Exception) -> tuple[dict[str, object], list[JobEnd]]:
    """The view of a backups job whose work raised `raised`, and what its `on_done` got."""
    store, ends, settled, job_id = AdminJobStore(), list[JobEnd](), asyncio.Event(), uuid4()

    async def work(progress: Callable[[float], None]) -> dict[str, object]:
        raise raised

    async def done(end: JobEnd) -> None:
        ends.append(end)

    AdminJobRunner(store).submit("backup_verify", job_id, work, done, settled.set)
    for _ in range(10):  # scheduler turns: the job fails in its first step, then settles
        await asyncio.sleep(0)
    job = store.get(str(job_id))
    assert settled.is_set() and job is not None
    return job.view(), ends


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        (BackupJobError("checksum_mismatch"), "checksum_mismatch"),
        (BackupJobError(cast(JobErrorCode, f"{_PATH} vanished")), "internal_error"),
        (FileNotFoundError(_PATH), "internal_error"),
        (PositionsUnknownError(_PATH), "internal_error"),  # another module's typed `code`
    ],
    ids=["closed-set", "foreign-code", "os-error", "typed-error-of-another-module"],
)
async def test_job_errors_are_stable_codes_never_class_names_or_messages(
    raised: Exception, code: str
) -> None:
    with capture_logs() as logs:
        view, ends = await _failed(raised)
    assert (view["status"], view["error"], ends) == ("failed", code, [JobEnd("failed", None, code)])
    assert type(raised).__name__ not in str(view) and _PATH not in f"{view}{logs}"
    failed = {"event": "backups.job_failed", "kind": "backup_verify", "job_id": view["id"]}
    failed |= {"error": type(raised).__name__, "log_level": "error"}  # the operator's, alone
    assert logs == ([failed] if code == "internal_error" else [])


async def test_a_failing_logger_never_replaces_the_closed_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def down(*args: object, **kwargs: object) -> None:
        raise RuntimeError("log sink down")

    logger = SimpleNamespace(error=down)
    monkeypatch.setattr("candleviewer.backups_wiring.structlog.get_logger", lambda *_: logger)
    view, ends = await _failed(FileNotFoundError(_PATH))
    assert (view["error"], ends) == ("internal_error", [JobEnd("failed", None, "internal_error")])


async def test_unknown_positions_are_none_never_zero() -> None:
    positions: OpenPositions = UnknownOpenPositions()
    assert (positions.source, await positions.count_open()) == ("not_deployed", None)
