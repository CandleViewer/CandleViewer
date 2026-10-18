"""Unit (E42-T05, #966 Q10, SR-BK7-02): `cv_admin_jobs_lost_on_restart_total` counts the jobs a
restart loses. A clean stop saves how many the store holds, finished ones included; the next boot
adds that once; a crash adds nothing; a count that cannot be read adds 0 and is logged, by its
failure only. A file or a link there is removed. Anything else (a FIFO, a socket, a directory) is
refused and left in place, and the read never waits on it (SEC-BK7b-01). A file of more than 16
digits is not a count (SEC-BK7bFU-03), and a FIFO at the save's temporary file never holds the clean
stop (SEC-BK7bFU-01)."""

from __future__ import annotations

import asyncio
import contextlib
import os
import stat
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from candleviewer.api.admin_jobs import LostJobsCount
from candleviewer.api.recorder_admin import AdminJobStore
from candleviewer.app import create_app
from candleviewer.settings import Environment, Settings

_FILE = Path("admin-jobs") / "lost-on-restart"
_BOUND_S = 2.0  # a safety net for a read that waits on a FIFO: refusing one takes microseconds


def _warning(error: str) -> dict[str, str]:
    """The one log record a count that cannot be read leaves: its failure, no path, no content."""
    return {"event": "admin_jobs.lost_count_unreadable", "log_level": "warning", "error": error}


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
    await LostJobsCount(tmp_path, await _store_holding(12), _counter()).save()  # two digits
    saved = tmp_path / _FILE
    assert (saved.read_bytes(), saved.stat().st_mode & 0o777) == (b"12", 0o600)
    assert [entry.name for entry in saved.parent.iterdir()] == [saved.name]  # no temporary left
    assert await _boot(tmp_path) == [12]  # read whole, not its first digit
    assert (saved.exists(), await _boot(tmp_path)) == (False, [0])  # a second restart adds 0


async def test_a_crash_saves_nothing_so_the_next_boot_adds_0(tmp_path: Path) -> None:
    with capture_logs() as logs:
        assert await _boot(tmp_path) == [0]  # no `save` ran: nothing to read, nothing to log
    assert logs == []


def _plant(saved: Path, kind: str) -> None:
    if kind == "not-a-directory":
        saved.parent.write_bytes(b"")  # `admin-jobs` is a file: the open fails (ENOTDIR)
        return
    saved.parent.mkdir(parents=True)
    if kind == "symlink":
        (saved.parent / "elsewhere").write_bytes(b"7")
        saved.symlink_to(saved.parent / "elsewhere")  # never followed
    elif kind == "directory":
        saved.mkdir()  # not a count, and not ours to remove
    elif kind == "socket":
        os.mknod(saved, 0o600 | stat.S_IFSOCK)  # `open` of a socket fails (ENXIO)
    else:
        saved.write_bytes({"not-a-count": b"three", "empty": b"", "too-long": b"1" * 17}[kind])


@pytest.mark.parametrize(
    ("kind", "error", "left"),
    [
        ("not-a-count", "malformed", False),
        ("empty", "malformed", False),
        ("too-long", "malformed", False),  # 17 digits: more than a count has, not its first 16
        ("symlink", "OSError", False),  # ELOOP: the link goes, never its target
        ("directory", "not_regular", True),
        ("socket", "OSError", True),  # the open fails (ENXIO): still not ours to remove
        ("not-a-directory", "NotADirectoryError", False),
    ],
)
async def test_an_unreadable_count_adds_0_and_is_logged_by_its_failure_only(
    tmp_path: Path, kind: str, error: str, left: bool
) -> None:
    saved = tmp_path / _FILE
    _plant(saved, kind)
    with capture_logs() as logs:
        assert await _boot(tmp_path) == [0]
    assert logs == [_warning(error)]  # no path and no content of the file, whatever it held
    assert (saved.is_symlink(), saved.exists(follow_symlinks=False)) == (False, left)


async def test_a_count_of_16_digits_is_read_whole(tmp_path: Path) -> None:
    saved = tmp_path / _FILE
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"9" * 16)  # the longest a count may be; a 17th byte tells a longer file
    assert await _boot(tmp_path) == [9999999999999999]


async def test_a_regular_file_the_open_refuses_is_still_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved, real_open = tmp_path / _FILE, os.open
    _plant(saved, "not-a-count")

    def refuse(path: Any, flags: int, *rest: Any, **kwargs: Any) -> int:
        if Path(path) == saved:
            raise PermissionError("not readable")  # as for a file of another owner, mode 000
        return real_open(path, flags, *rest, **kwargs)

    monkeypatch.setattr(os, "open", refuse)
    with capture_logs() as logs:
        counted = await _boot(tmp_path)
    assert (counted, saved.exists(follow_symlinks=False), logs) == (
        [0],
        False,
        [_warning("PermissionError")],
    )


async def test_a_fifo_at_the_count_path_is_refused_and_never_blocks_the_boot(
    tmp_path: Path,
) -> None:
    saved = tmp_path / _FILE
    saved.parent.mkdir(parents=True)
    os.mkfifo(saved, 0o600)  # no writer: an open that waits for one never returns
    with capture_logs() as logs:
        boot = asyncio.ensure_future(_boot(tmp_path))
        done, _ = await asyncio.wait({boot}, timeout=_BOUND_S)
        with contextlib.suppress(OSError):  # frees a read stuck in `open()`; ENXIO: none is
            os.close(os.open(saved, os.O_WRONLY | os.O_NONBLOCK))
        counted = await boot
    assert bool(done), "the boot waited for a writer on the FIFO"
    assert (counted, logs) == ([0], [_warning("not_regular")])
    assert stat.S_ISFIFO(saved.lstat().st_mode)  # not ours to remove


async def test_a_fifo_at_the_saves_temporary_never_blocks_the_clean_stop(tmp_path: Path) -> None:
    temporary = tmp_path / _FILE.with_name("lost-on-restart.tmp")
    temporary.parent.mkdir(parents=True)
    os.mkfifo(temporary, 0o600)  # no reader: an open for writing that waits for one never returns
    stop = asyncio.ensure_future(LostJobsCount(tmp_path, AdminJobStore(), _counter()).save())
    done, _ = await asyncio.wait({stop}, timeout=_BOUND_S)
    with contextlib.suppress(OSError):  # frees an open stuck for want of a reader; ENXIO: none is
        os.close(os.open(temporary, os.O_RDONLY | os.O_NONBLOCK))
    with contextlib.suppress(OSError):  # what the save raises is not under test, that it returns is
        await stop
    assert bool(done), "the clean stop waited for a reader on the FIFO"
    assert stat.S_ISFIFO(temporary.lstat().st_mode)  # not ours to remove
    assert not (tmp_path / _FILE).exists()  # and nothing was saved


async def test_a_symlink_at_the_saves_temporary_is_refused_never_written_through(
    tmp_path: Path,
) -> None:
    victim, temporary = tmp_path / "victim", tmp_path / _FILE.with_name("lost-on-restart.tmp")
    victim.write_bytes(b"keep")
    temporary.parent.mkdir(parents=True)
    temporary.symlink_to(victim)
    with pytest.raises(OSError):  # ELOOP
        await LostJobsCount(tmp_path, AdminJobStore(), _counter()).save()
    assert victim.read_bytes() == b"keep"


async def test_the_save_replaces_a_stale_temporary_whole(tmp_path: Path) -> None:
    temporary = tmp_path / _FILE.with_name("lost-on-restart.tmp")
    temporary.parent.mkdir(parents=True)
    temporary.write_bytes(b"123456")  # what a save that died before its rename left behind
    await LostJobsCount(tmp_path, await _store_holding(2), _counter()).save()
    assert (tmp_path / _FILE).read_bytes() == b"2"  # not b"223456"


async def test_the_count_is_opened_read_only_never_following_waiting_or_taking_a_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await LostJobsCount(tmp_path, await _store_holding(1), _counter()).save()
    saved, real_open = tmp_path / _FILE, os.open
    opened: list[int] = []

    def spy(path: Any, flags: int, *rest: Any, **kwargs: Any) -> int:
        if Path(path) == saved:
            opened.append(flags)
        return real_open(path, flags, *rest, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    assert await _boot(tmp_path) == [1]
    guards = os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC
    assert [(flags & guards, flags & os.O_ACCMODE) for flags in opened] == [(guards, os.O_RDONLY)]


async def test_a_count_that_cannot_be_removed_is_not_counted_so_it_is_never_counted_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = tmp_path / _FILE
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"5")

    def refuse(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("a read-only volume")

    monkeypatch.setattr(Path, "unlink", refuse)
    with capture_logs() as logs:
        counted = await _boot(tmp_path)  # left in place, it would be counted at every boot
    assert (counted, saved.read_bytes(), logs) == ([0], b"5", [_warning("PermissionError")])


def test_the_app_keeps_the_count_in_the_data_dir_the_wal_anchor_normalises(tmp_path: Path) -> None:
    relative = os.path.relpath(tmp_path / "data" / "parquet")  # relative to here, `..` segments
    settings = Settings(environment=Environment.DEMO, metrics_enabled=False, parquet_root=relative)
    path = create_app(settings).state.admin_jobs_lost._path
    assert path == tmp_path.resolve() / "data" / _FILE
