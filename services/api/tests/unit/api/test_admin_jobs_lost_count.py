"""Unit (E42-T05, #966 Q10, SR-BK7-02): `cv_admin_jobs_lost_on_restart_total` counts the jobs a
restart loses. A clean stop saves how many the store holds, finished ones included; the next boot
adds that once; a crash adds nothing; a count that cannot be read adds 0, is logged and removed."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from candleviewer.api.admin_jobs import LostJobsCount
from candleviewer.api.recorder_admin import AdminJobStore

_FILE = Path("admin-jobs") / "lost-on-restart"


def _counter() -> Any:
    counted: list[float] = []
    return SimpleNamespace(counted=counted, inc=counted.append)


async def _store_holding(finished: int) -> AdminJobStore:
    store = AdminJobStore()

    async def work(progress: Callable[[float], None]) -> dict[str, object]:
        return {}

    async def done(job: object) -> None:
        return None

    for _ in range(finished):
        store.submit("retention_sweep", ("u", str(uuid4()), "h"), work, done)
        await asyncio.sleep(0)  # a scheduler turn: the job runs to its end, the store keeps it
    return store


async def _boot(data_dir: Path) -> list[float]:
    counter = _counter()
    await LostJobsCount(data_dir, AdminJobStore(), counter).load()
    return list(counter.counted)


async def test_a_clean_stop_with_n_held_jobs_adds_n_at_the_next_boot_only(tmp_path: Path) -> None:
    await LostJobsCount(tmp_path, await _store_holding(3), _counter()).save()
    saved = tmp_path / _FILE
    assert (saved.read_bytes(), saved.stat().st_mode & 0o777) == (b"3", 0o600)
    assert [entry.name for entry in saved.parent.iterdir()] == [saved.name]  # no temporary left
    assert await _boot(tmp_path) == [3]
    assert (saved.exists(), await _boot(tmp_path)) == (False, [0])  # a second restart adds 0


async def test_a_crash_saves_nothing_so_the_next_boot_adds_0(tmp_path: Path) -> None:
    with capture_logs() as logs:
        assert await _boot(tmp_path) == [0]  # no `save` ran: nothing to read, nothing to log
    assert logs == []


def _plant(saved: Path, kind: str) -> None:
    saved.parent.mkdir(parents=True)
    if kind == "symlink":
        (saved.parent / "elsewhere").write_bytes(b"7")
        saved.symlink_to(saved.parent / "elsewhere")  # never followed
    elif kind == "directory":
        saved.mkdir()  # not a count, and `unlink` cannot remove it
    else:
        saved.write_bytes({"not-a-count": b"three", "empty": b""}[kind])


@pytest.mark.parametrize("kind", ["not-a-count", "empty", "symlink", "directory"])
async def test_an_unreadable_count_adds_0_is_logged_and_removed(tmp_path: Path, kind: str) -> None:
    saved = tmp_path / _FILE
    _plant(saved, kind)
    with capture_logs() as logs:
        assert await _boot(tmp_path) == [0]
    assert [(e["event"], e["log_level"]) for e in logs] == [
        ("admin_jobs.lost_count_unreadable", "warning")
    ]
    assert (saved.is_symlink(), saved.exists()) == (False, kind == "directory")
