"""SEC-REM-03 (#3009, ADR-0037 decision 9): `lane.lock` is taken through descriptors, first the
audit directory's, then `lane/`'s, so a symlink swapped in after an open is never followed. The
relative, `..`, other-error and holder cases are the façade's and the release command's tests."""

from __future__ import annotations

import fcntl
import gc
import os
import stat
from pathlib import Path

import pytest

from candleviewer.admin.lane_release import release
from candleviewer.audit import lane_journal as lj
from candleviewer.audit.lane import LaneBootRefused, lock_lane
from candleviewer.audit.lane_lock import LaneUnanchored, take_lane_lock


@pytest.fixture
def audit(tmp_path: Path) -> Path:
    (path := tmp_path.resolve() / "audit").mkdir()
    return path


def wal(audit: Path) -> str:
    return str(audit / "audit.wal")


def fds() -> int:
    """This process's open descriptors (Linux CI), as `test_lane_journal_appends` counts them."""
    return len(os.listdir("/proc/self/fd"))


def after_open(mp: pytest.MonkeyPatch, swap: Path, moved: Path, to: Path) -> None:
    """Once the helper opened the audit directory, `swap` moves to `moved`, a link to `to` there."""
    real = lj._open

    def opening(path: Path | str, flags: int, dir_fd: int | None = None) -> int:
        fd = real(path, flags, dir_fd)
        if Path(path).name == "audit":
            swap.rename(moved)
            swap.symlink_to(to)
        return fd

    mp.setattr(lj, "_open", opening)


def test_take_without_create_refuses_a_missing_lane_and_makes_nothing(audit: Path) -> None:
    """The release command's call: a missing `lane/` is an error, and nothing is made."""
    with pytest.raises(FileNotFoundError):
        take_lane_lock(wal(audit), create=False)

    assert os.listdir(audit) == []


def test_release_refuses_a_missing_lane_and_makes_nothing(audit: Path) -> None:
    """Only cv-api makes `lane/`: the release command fails on a missing one (exit 4 in `main`)."""
    with pytest.raises(FileNotFoundError):
        release(wal(audit), lj.LaneKeys(bytes(32)), (1, 0), ("owner", "INC-1", "why"))

    assert os.listdir(audit) == []


def test_take_makes_lane_0700_and_the_lock_0600(audit: Path) -> None:
    os.close(take_lane_lock(wal(audit), create=True))
    lane = audit / "lane"

    assert [stat.S_IMODE(p.stat().st_mode) for p in (lane, lane / "lane.lock")] == [0o700, 0o600]


def test_take_fsyncs_the_audit_directory_once_when_it_makes_lane(
    audit: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new `lane/` is durable in the audit directory before the lock is taken in it; when
    `lane/` is there already, nothing is fsynced."""
    synced, fsync = list[int](), os.fsync

    def syncing(fd: int) -> None:
        synced.append(os.fstat(fd).st_ino)
        fsync(fd)

    monkeypatch.setattr(os, "fsync", syncing)
    for _ in range(2):
        os.close(take_lane_lock(wal(audit), create=True))

    assert synced == [audit.stat().st_ino]


def test_the_lock_descriptor_is_close_on_exec(audit: Path) -> None:
    """No child process inherits the lock."""
    fd = take_lane_lock(wal(audit), create=True)
    try:
        flags = fcntl.fcntl(fd, fcntl.F_GETFD)
    finally:
        os.close(fd)

    assert flags & fcntl.FD_CLOEXEC


def test_the_lock_is_opened_non_blocking(audit: Path) -> None:
    """cv-api takes the lock on the event loop: a FIFO planted in its place opens at once."""
    fd = take_lane_lock(wal(audit), create=True)
    try:
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    finally:
        os.close(fd)

    assert flags & os.O_NONBLOCK


@pytest.mark.parametrize(
    ("case", "raised"),
    [
        ("create", None),
        ("fifo", None),
        ("held", BlockingIOError),
        ("lock_is_symlink", LaneUnanchored),
        ("lane_is_file", LaneUnanchored),
        ("lane_is_symlink", LaneUnanchored),
        ("no_audit_dir", FileNotFoundError),
    ],
)
def test_take_closes_every_descriptor_it_opens(
    tmp_path: Path, audit: Path, case: str, raised: type[Exception] | None
) -> None:
    """On every path the directories' descriptors are closed, and the lock's when `flock` fails:
    only the descriptor returned stays open, for its caller to close. A FIFO keeps a writer here,
    so the open could not block even without `O_NONBLOCK` (the test above pins that flag)."""
    lane, path = audit / "lane", wal(audit)
    holder: int | None = None
    got: type[Exception] | None = None
    (target := tmp_path / "elsewhere").mkdir()
    if case == "fifo":
        lane.mkdir(mode=0o700)
        os.mkfifo(lane / "lane.lock", 0o600)
        holder = os.open(lane / "lane.lock", os.O_RDWR | os.O_NONBLOCK)
    elif case == "held":
        holder = take_lane_lock(path, create=True)
    elif case == "lock_is_symlink":
        lane.mkdir(mode=0o700)
        (lane / "lane.lock").symlink_to(target / "lock")
    elif case == "lane_is_file":
        lane.write_bytes(b"")
    elif case == "lane_is_symlink":
        lane.symlink_to(target)
    elif case == "no_audit_dir":
        path = wal(tmp_path.resolve() / "absent")
    gc.collect()  # nothing left for a collection to close while the count is taken
    before = fds()
    try:
        os.close(take_lane_lock(path, create=True))
    except (LaneUnanchored, OSError) as exc:
        got = type(exc)
    after = fds()
    if holder is not None:
        os.close(holder)

    assert after == before and got is raised


@pytest.mark.parametrize(
    ("name", "kind", "said"),
    [
        ("audit", "link", "the audit directory "),
        ("audit/lane", "file", "lane/ "),
        ("audit/lane/lane.lock", "link", "lane.lock "),
    ],
)
def test_a_symlink_or_a_file_where_a_directory_should_be_is_one_refusal(
    tmp_path: Path, name: str, kind: str, said: str
) -> None:
    """`ENOTDIR` (`O_DIRECTORY | O_NOFOLLOW` on a link, or a file) and `ELOOP` (the lock a link):
    one refusal, which refuses cv-api's boot and names the component, never its path; nothing is
    made through a link. A linked `lane/` is the façade's `lane-dir` case and the release
    command's `symlinked_lane`."""
    (target := tmp_path / "elsewhere").mkdir()
    (path := tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    if kind == "file":
        path.write_bytes(b"")
    else:
        path.symlink_to(target)
    messages = list[str]()
    for create in (True, False):
        with pytest.raises(LaneUnanchored) as refused:
            take_lane_lock(wal(tmp_path.resolve() / "audit"), create=create)
        messages.append(str(refused.value))
    with pytest.raises(LaneBootRefused):
        lock_lane(wal(tmp_path.resolve() / "audit"))

    assert os.listdir(target) == []
    assert all(m.startswith(said) and str(tmp_path) not in m for m in messages)


def test_the_lock_is_taken_through_the_directory_the_helper_opened(
    tmp_path: Path, audit: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The audit directory swapped for a link once opened: `lane/` and `lane.lock` land in the
    one opened, and nothing is made through the link."""
    moved, target = tmp_path / "moved", tmp_path / "elsewhere"
    target.mkdir()
    after_open(monkeypatch, audit, moved, target)
    lock_lane(wal(audit)).close()

    assert os.listdir(moved / "lane") == ["lane.lock"] and os.listdir(target) == []


def test_a_swap_of_lane_after_the_audit_dir_open_is_not_followed(
    tmp_path: Path, audit: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`lane/` swapped for a link between the two opens: boot is refused and nothing is made
    outside the audit directory (the release command's case: `swapped_lane`)."""
    (lane := audit / "lane").mkdir()
    target = tmp_path / "elsewhere"
    after_open(monkeypatch, lane, target, target)
    with pytest.raises(LaneBootRefused):
        lock_lane(wal(audit))

    assert os.listdir(target) == [] and os.listdir(audit) == ["lane"]
