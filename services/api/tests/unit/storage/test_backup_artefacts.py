"""E42-T05 BK-6a (#966 Q7, Q8; SR-097): backup artefacts are read only inside the backup root.
Each refusal keeps a readable file where an escape would land, so only the rule under test can
refuse it. The `os` hooks swap, hold or count, in the walk's thread or on the loop; none sleeps."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import gc
import hashlib
import os
import shutil
import threading
import traceback
import weakref
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest

from candleviewer.admin.backups.artefact_port import ArtefactReader
from candleviewer.storage.backup_artefacts import (
    CHUNK_BYTES,
    ArtefactError,
    ArtefactMissing,
    ArtefactUnreadable,
    LocalArtefactStore,
    ResolvedArtefact,
)

#: Deterministic and aperiodic, so no two chunks are alike.
_INSIDE = hashlib.shake_256(b"E42-T05 BK-6").digest(2 * CHUNK_BYTES + CHUNK_BYTES // 2)
_LOCATION = "pg/2026/dump.age"
_WAIT_S = 10
_FILE = "vol/backups/pg/2026/dump.age"
_COMPONENTS = {
    "above-the-root": "vol",
    "root": "vol/backups",
    "directory": "vol/backups/pg",
    "subdirectory": "vol/backups/pg/2026",
    "file": _FILE,
}


def _trees(tmp_path: Path) -> Path:
    """The root `vol/backups` (`top.age`, `pg/2026/dump.age`), mirrored under `elsewhere`."""
    for volume, data in (("vol", _INSIDE), ("elsewhere", b"outside the root")):
        (tmp_path / volume / "backups" / "pg" / "2026").mkdir(parents=True)
        (tmp_path / volume / "backups" / _LOCATION).write_bytes(data)
        (tmp_path / volume / "backups" / "top.age").write_bytes(data)
    return tmp_path / "vol" / "backups"


async def _opened(root: Path) -> ResolvedArtefact:
    return await LocalArtefactStore(str(root)).resolve(f"{root}/{_LOCATION}")


async def _refused(
    store: LocalArtefactStore, location: str, kind: type[ArtefactError] = ArtefactMissing
) -> ArtefactError:
    """Every refusal carries its code only, nothing chained (C-12.6)."""
    with pytest.raises(kind) as refused:
        await store.resolve(location)
    assert (refused.value.code, refused.value.args) == (kind.code, (kind.code,))
    assert refused.value.__cause__ is None and refused.value.__context__ is None
    return refused.value


def _before_open(monkeypatch: pytest.MonkeyPatch, name: str, action: Callable[[], None]) -> None:
    """Runs `action` once, before the first `os.open` of a path through the component `name`."""
    real, pending = os.open, [action]

    def hooked(path: str, flags: int, mode: int = 0o777, **kw: Any) -> int:
        if name in Path(path).parts and pending:
            pending.pop()()
        return real(path, flags, mode, **kw)

    monkeypatch.setattr(os, "open", hooked)


def _swap(tmp_path: Path, component: str, target: str | None = None) -> None:
    """Moves `component` aside; under its name, a symlink to `target` (default: its mirror)."""
    path = tmp_path / component
    path.rename(path.with_name(f"{path.name}.moved"))
    path.symlink_to(tmp_path / (target or component.replace("vol", "elsewhere", 1)))


class _Reads:
    """`os.pread` calls as (thread, size); the read at offset `hold_from` waits for `release`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, hold_from: int | None = None) -> None:
        self.calls: list[tuple[int, int]] = []
        self.entered, self.release, real = threading.Event(), threading.Event(), os.pread

        def spy(fd: int, size: int, offset: int) -> bytes:
            self.calls.append((threading.get_ident(), size))
            if offset == hold_from:
                self.entered.set()
                self.release.wait(_WAIT_S)
            return real(fd, size, offset)

        monkeypatch.setattr(os, "pread", spy)

    async def held(self) -> None:
        assert await asyncio.to_thread(self.entered.wait, _WAIT_S)

    def bounded_and_off_the_loop(self) -> bool:
        threads = {thread for thread, _ in self.calls}
        sizes = {size for _, size in self.calls}
        return sizes == {CHUNK_BYTES} and threading.get_ident() not in threads


class _Closes:
    """`os.close` of `fd`; installed before `resolve`: the finalizer keeps its `os.close`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.fd, self.seen, self.event, real = -1, list[int](), asyncio.Event(), os.close

        def spy(fd: int) -> None:
            real(fd)
            if fd == self.fd:
                self.seen.append(fd)
                self.event.set()

        monkeypatch.setattr(os, "close", spy)


async def _drain(chunks: AsyncIterator[bytes]) -> None:
    async for _ in chunks:
        pass


@pytest.mark.parametrize("below", ["top.age", _LOCATION], ids=["in-the-root", "two-levels-down"])
async def test_reads_a_regular_file_inside_the_root(tmp_path: Path, below: str) -> None:
    root = _trees(tmp_path)
    reader: ArtefactReader = LocalArtefactStore(str(root))

    artefact = await reader.resolve(f"{root}/{below}")

    assert artefact.size == len(_INSIDE)
    assert await artefact.digest() == hashlib.sha256(_INSIDE).hexdigest()
    assert b"".join([chunk async for chunk in artefact.stream()]) == _INSIDE


@pytest.mark.parametrize(
    "below",
    [
        pytest.param("../../elsewhere/backups/pg/2026/dump.age", id="above-the-root"),
        pytest.param("pg/2026/../../../../elsewhere/backups/top.age", id="deeper"),
        pytest.param("pg/../pg/2026/dump.age", id="back-inside"),
    ],
)
async def test_dotdot_location_is_refused(tmp_path: Path, below: str) -> None:
    root = _trees(tmp_path)

    await _refused(LocalArtefactStore(str(root)), f"{root}/{below}")


@pytest.mark.parametrize(
    "location",
    [
        pytest.param("{root}/./pg/2026/dump.age", id="dot"),
        pytest.param("{root}//pg/2026/dump.age", id="empty-component"),
        pytest.param("{root}/pg/2026/dump.age/", id="trailing-slash"),
        pytest.param("{root}/pg/2026/dump.age\x00", id="nul"),
        pytest.param("junk{root}/pg/2026/dump.age", id="relative"),
    ],
)
async def test_a_location_out_of_canonical_form_is_refused_before_any_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    root, opened = _trees(tmp_path), list[object]()
    monkeypatch.setattr(os, "open", lambda *args, **kwargs: opened.append(args))

    await _refused(LocalArtefactStore(str(root)), location.format(root=root))

    assert opened == []


@pytest.mark.parametrize(
    "location",
    [
        pytest.param("{tmp}/elsewhere/backups/top.age", id="mirror"),
        pytest.param("{root}-old/top.age", id="sharing-the-root-prefix"),
    ],
)
async def test_absolute_location_outside_the_root_is_refused(tmp_path: Path, location: str) -> None:
    root = _trees(tmp_path)
    shutil.copytree(tmp_path / "elsewhere" / "backups", f"{root}-old")

    await _refused(LocalArtefactStore(str(root)), location.format(root=root, tmp=tmp_path))


@pytest.mark.parametrize(
    ("component", "target"),
    [
        *(pytest.param(component, None, id=name) for name, component in _COMPONENTS.items()),
        pytest.param(_FILE, "vol/backups/top.age", id="link-inside"),
    ],
)
async def test_a_symlink_in_any_component_is_refused(
    tmp_path: Path, component: str, target: str | None
) -> None:
    """Even a link that stays inside the root is refused: no symlink is followed."""
    root = _trees(tmp_path)
    _swap(tmp_path, component, target)

    await _refused(LocalArtefactStore(str(root)), f"{root}/{_LOCATION}")


@pytest.mark.parametrize("component", list(_COMPONENTS.values()), ids=list(_COMPONENTS))
async def test_a_symlink_swapped_in_after_the_check_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, component: str
) -> None:
    """The swap lands between two steps of the walk, once every component above is open."""
    root = _trees(tmp_path)
    _before_open(monkeypatch, Path(component).name, lambda: _swap(tmp_path, component))

    await _refused(LocalArtefactStore(str(root)), f"{root}/{_LOCATION}")


async def test_a_component_swapped_behind_the_walk_does_not_redirect_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The walk holds each directory's descriptor: `pg`, swapped once open, is off its way."""
    root = _trees(tmp_path)
    _before_open(monkeypatch, "2026", lambda: _swap(tmp_path, "vol/backups/pg"))

    artefact = await _opened(root)

    assert await artefact.digest() == hashlib.sha256(_INSIDE).hexdigest()
    artefact.close()


async def test_the_walk_opens_each_component_from_the_one_before_with_fixed_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each directory from the descriptor of the one before; the file `O_NOCTTY` too (L-2)."""
    root, real, calls = _trees(tmp_path), os.open, list[tuple[str, int, int | None, int]]()

    def spy(path: str, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        fd = real(path, flags, mode, dir_fd=dir_fd)
        calls.append((path, flags, dir_fd, fd))
        return fd

    monkeypatch.setattr(os, "open", spy)
    (await _opened(root)).close()

    directory = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    file = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC
    assert [path for path, *_ in calls] == ["/", *f"{root}/{_LOCATION}".split("/")[1:]]
    assert [flags for _, flags, *_ in calls] == [directory] * (len(calls) - 1) + [file]
    assert [dir_fd for _, _, dir_fd, _ in calls] == [None, *(fd for *_, fd in calls[:-1])]


async def test_a_search_only_directory_on_the_way_is_walked(tmp_path: Path) -> None:
    """`O_PATH`: walking a directory needs search permission only, not read (mode 0o311)."""
    if os.geteuid() == 0:
        pytest.skip("root bypasses directory permissions")
    root = _trees(tmp_path)
    (tmp_path / "vol").chmod(0o311)
    try:
        (await _opened(root)).close()
    finally:
        (tmp_path / "vol").chmod(0o755)


async def test_the_type_check_reads_the_opened_descriptor_not_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory, opened, then replaced under its name by a file a check by path would pass."""
    swapped, real = _trees(tmp_path) / "pg" / "2026", os.open

    def replace_after_open(path: str, flags: int, mode: int = 0o777, **kw: Any) -> int:
        fd = real(path, flags, mode, **kw)
        if path == swapped.name:
            shutil.rmtree(swapped)
            swapped.write_bytes(_INSIDE)
        return fd

    monkeypatch.setattr(os, "open", replace_after_open)

    await _refused(LocalArtefactStore(str(swapped.parent.parent)), str(swapped))


@pytest.mark.parametrize("kind", ["directory", "fifo", "device"])
async def test_directory_fifo_and_device_are_refused(tmp_path: Path, kind: str) -> None:
    root = _trees(tmp_path)
    fifo = root / "pg" / "pipe.age"
    os.mkfifo(fifo)  # no writer: a blocking open would never return
    store, location = {
        "directory": (LocalArtefactStore(str(root)), f"{root}/pg/2026"),
        "fifo": (LocalArtefactStore(str(root)), str(fifo)),
        # The one device every Linux host has: opened read-only, never read, nothing created.
        "device": (LocalArtefactStore("/dev"), "/dev/null"),
    }[kind]

    try:  # bounded, so a blocking open fails red instead of hanging (N5)
        await asyncio.wait_for(_refused(store, location), _WAIT_S)
    finally:  # a writer wakes an open stuck on the FIFO, so no thread outlives the test
        with contextlib.suppress(OSError):
            os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))


@pytest.mark.parametrize("target", ["elsewhere/backups/top.age", "vol/backups/top.age"])
async def test_a_file_with_a_second_link_is_refused(tmp_path: Path, target: str) -> None:
    """L-1: a link to a file outside the root, or a second name inside it (`st_nlink`)."""
    root = _trees(tmp_path)
    os.link(tmp_path / target, root / "pg" / "linked.age")

    await _refused(LocalArtefactStore(str(root)), f"{root}/pg/linked.age")


async def test_a_file_on_another_device_than_the_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L-1: a mount below the root; the device compared is the root's, not the file's parent's."""
    root, real = _trees(tmp_path), os.fstat
    root_inode = os.stat(root).st_ino

    def another_device(fd: int) -> os.stat_result:
        info = real(fd)
        if info.st_ino == root_inode:
            return info
        return os.stat_result((info.st_mode, info.st_ino, info.st_dev + 1, *info[3:]))

    monkeypatch.setattr(os, "fstat", another_device)

    await _refused(LocalArtefactStore(str(root)), f"{root}/{_LOCATION}")


@pytest.mark.parametrize(
    ("root", "below"),
    [
        ("vol/backups", "pg/2026/gone.age"),
        ("vol/backups", "gone/2026/dump.age"),
        ("gone", "x"),
        ("vol/backups", "pg/\ud800.age"),
    ],
    ids=["file", "directory", "root", "a-name-the-os-cannot-encode"],
)
async def test_missing_file_is_artefact_missing(tmp_path: Path, root: str, below: str) -> None:
    """Not even a rendered traceback names the path or an OS error (C-12.6)."""
    _trees(tmp_path)

    refused = await _refused(LocalArtefactStore(f"{tmp_path}/{root}"), f"{tmp_path}/{root}/{below}")

    rendered = "".join(traceback.format_exception(refused))
    assert refused.code == "artefact_missing" and "Errno" not in rendered
    assert "gone" not in rendered and str(tmp_path) not in rendered and "\ud800" not in rendered


@pytest.mark.parametrize("error", [errno.EIO, errno.EMFILE, errno.ENFILE, errno.ENOMEM])
async def test_an_io_or_resource_failure_is_unreadable_not_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: int
) -> None:
    """L-4: the volume or the process failed, so the file may be there: `store_unavailable`."""
    root, real = _trees(tmp_path), os.open

    def failing(path: str, flags: int, mode: int = 0o777, **kw: Any) -> int:
        if path == "dump.age":
            raise OSError(error, os.strerror(error), path)
        return real(path, flags, mode, **kw)

    monkeypatch.setattr(os, "open", failing)

    refused = await _refused(
        LocalArtefactStore(str(root)), f"{root}/{_LOCATION}", ArtefactUnreadable
    )
    assert refused.code == "store_unavailable"


async def test_a_read_failure_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artefact = await _opened(_trees(tmp_path))
    monkeypatch.setattr(os, "pread", lambda *args: os.read(-1, 1))  # a real OSError (EBADF)

    for read in (artefact.digest(), _drain(artefact.stream())):
        with pytest.raises(ArtefactUnreadable) as refused:
            await read
        assert refused.value.__cause__ is None and refused.value.__context__ is None


async def test_digest_matches_hashlib_and_runs_off_the_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artefact = await _opened(_trees(tmp_path))
    reads = _Reads(monkeypatch)

    assert await artefact.digest() == hashlib.sha256(_INSIDE).hexdigest()

    assert len(reads.calls) == 4 and reads.bounded_and_off_the_loop()  # 3 chunks, then the end
    assert CHUNK_BYTES == 1 << 20
    artefact.close()


async def test_short_reads_are_followed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A volume may return fewer bytes than asked: the next read starts where the last one ended."""
    artefact, real = await _opened(_trees(tmp_path)), os.pread
    monkeypatch.setattr(os, "pread", lambda fd, size, offset: real(fd, min(size, 100_000), offset))

    assert await artefact.digest() == hashlib.sha256(_INSIDE).hexdigest()
    assert b"".join([chunk async for chunk in artefact.stream()]) == _INSIDE


async def test_stream_yields_bounded_chunks_and_closes_the_file_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closes = _Closes(monkeypatch)
    artefact = await _opened(_trees(tmp_path))
    closes.fd, reads = artefact._fd, _Reads(monkeypatch)

    chunks = [chunk async for chunk in artefact.stream()]

    assert [len(chunk) for chunk in chunks] == [CHUNK_BYTES, CHUNK_BYTES, CHUNK_BYTES // 2]
    assert len(reads.calls) == 4 and reads.bounded_and_off_the_loop()
    assert closes.seen == [closes.fd]  # the stream closed it at its end
    artefact.close()
    assert closes.seen == [closes.fd]
    with pytest.raises(ValueError, match="none once closed"):
        await artefact.digest()


@pytest.mark.parametrize("read", ["stream", "digest"])
async def test_stream_closes_the_file_when_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, read: str
) -> None:
    """Cancelled in its second read, a stream or a digest closes the artefact, once, after that
    read's thread returns, though the artefact is dropped and collected meanwhile (M-1). The
    digest's thread then ends in `ArtefactMissing`, into a future no one awaits: `_settled`
    retrieves it, so the loop reports nothing when it is collected (N6)."""
    reports = list[str]()
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda _, context: reports.append(context["message"]))
    closes = _Closes(monkeypatch)
    artefact = await _opened(_trees(tmp_path))
    closes.fd, reads = artefact._fd, _Reads(monkeypatch, hold_from=CHUNK_BYTES)
    task = asyncio.create_task(_drain(artefact.stream()) if read == "stream" else artefact.digest())
    await reads.held()
    with pytest.raises(ValueError, match="one read at a time"):
        await artefact.digest()

    task.cancel()
    await asyncio.wait([task])
    alive, cancelled = weakref.ref(artefact), task.cancelled()
    del artefact, task
    gc.collect()
    assert cancelled and alive() is not None and closes.seen == []  # its read holds it, open
    reads.release.set()
    await asyncio.wait_for(closes.event.wait(), _WAIT_S)

    assert closes.seen == [closes.fd] and len(reads.calls) == 2  # the digest read no more
    gc.collect()
    assert alive() is None and reports == []  # collected, and nothing reported for its read


async def test_no_read_starts_once_closed_even_before_the_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F1: after `close()` a read is refused, even between the read in flight's end and its
    release (here, at the start of its done callback)."""
    closes = _Closes(monkeypatch)
    artefact = await _opened(_trees(tmp_path))
    closes.fd, reads = artefact._fd, _Reads(monkeypatch, hold_from=CHUNK_BYTES)
    settled, late = artefact._settled, list[asyncio.Task[str]]()

    def window(reading: asyncio.Future[Any]) -> None:
        loop = asyncio.get_running_loop()
        late.append(asyncio.Task(artefact.digest(), loop=loop, eager_start=True))  # guard runs now
        settled(reading)

    monkeypatch.setattr(artefact, "_settled", window)
    task = asyncio.create_task(artefact.digest())
    await reads.held()
    artefact.close()  # a read is in flight: the release waits for it
    reads.release.set()

    with pytest.raises(ArtefactMissing):  # closed, the digest stopped within one chunk
        await task
    await asyncio.wait_for(closes.event.wait(), _WAIT_S)
    with pytest.raises(ValueError, match="none once closed"):
        await late[0]
    assert closes.seen == [closes.fd]


async def test_a_finished_reads_callback_never_closes_under_a_newer_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F4: a read ends and, before its done callback runs, a second reader (the port forbids it)
    is admitted and `close()` is called, all in one loop iteration. The callback leaves the
    descriptor to the read still in flight, which releases it, once, when its thread returns."""
    closes = _Closes(monkeypatch)
    artefact = await _opened(_trees(tmp_path))
    closes.fd, settled = artefact._fd, artefact._settled
    late = list[tuple[asyncio.Task[str], _Reads]]()

    def window(reading: asyncio.Future[Any]) -> None:
        if not late:
            reads = _Reads(monkeypatch, hold_from=0)  # the second read waits in its thread
            loop = asyncio.get_running_loop()
            late.append((asyncio.Task(artefact.digest(), loop=loop, eager_start=True), reads))
            artefact.close()  # that read is in flight: the release waits for it
        settled(reading)

    monkeypatch.setattr(artefact, "_settled", window)
    assert await artefact.digest() == hashlib.sha256(_INSIDE).hexdigest()
    task, reads = late[0]
    await reads.held()
    assert closes.seen == []  # not under the second read's thread

    reads.release.set()
    with pytest.raises(ArtefactMissing):  # closed, its digest stopped within one chunk
        await task
    await asyncio.wait_for(closes.event.wait(), _WAIT_S)
    assert closes.seen == [closes.fd]


async def test_no_descriptor_outlives_a_refusal_or_a_close(tmp_path: Path) -> None:
    root = _trees(tmp_path)
    store = LocalArtefactStore(str(root))
    (await store.resolve(f"{root}/{_LOCATION}")).close()  # the executor's threads exist now
    before = len(os.listdir("/proc/self/fd"))

    for below in ("pg/2026", "pg/2026/gone.age", "gone/2026/dump.age"):
        await _refused(store, f"{root}/{below}")
    (await store.resolve(f"{root}/{_LOCATION}")).close()

    assert len(os.listdir("/proc/self/fd")) == before


async def test_a_cancelled_resolve_closes_the_file_its_walk_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, closes = _trees(tmp_path), _Closes(monkeypatch)
    entered, release, real = threading.Event(), threading.Event(), os.open

    def held(path: str, flags: int, mode: int = 0o777, **kw: Any) -> int:
        fd = real(path, flags, mode, **kw)
        if path == "dump.age":
            closes.fd = fd
            entered.set()
            release.wait(_WAIT_S)
        return fd

    monkeypatch.setattr(os, "open", held)
    task = asyncio.create_task(_opened(root))
    assert await asyncio.to_thread(entered.wait, _WAIT_S)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    await asyncio.wait_for(closes.event.wait(), _WAIT_S)

    assert closes.seen == [closes.fd]


@pytest.mark.parametrize("root", ["srv/backups", "/", "/srv/../backups", "/srv/backups/"])
def test_the_store_takes_only_a_canonical_absolute_root(root: str) -> None:
    with pytest.raises(ValueError, match="canonical form, not /"):
        LocalArtefactStore(root)
