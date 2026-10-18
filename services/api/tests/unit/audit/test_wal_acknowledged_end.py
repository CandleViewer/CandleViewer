"""`AuditWal` hands the flusher only acknowledged frames: bytes an append wrote before it raised
are cut back at once (a cut that fails is logged), a later open does not read them, and
`replay()` never reads past the acknowledged end even when they are still there. A frame inside
the acknowledged part that fails validation fails closed."""

from __future__ import annotations

import builtins
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.audit import wal as wal_module
from candleviewer.audit.wal import AuditWal, AuditWalCorrupt, encode_frame


class _FailNextFsync:
    """Stands in for `os` in `wal`; its next `fsync` raises once armed. `sizes` holds the size of
    the file behind every `fsync` call (the failing one included), in call order."""

    def __init__(self) -> None:
        self.armed = False
        self.sizes: list[int] = []

    def fsync(self, fd: int) -> None:
        self.sizes.append(os.fstat(fd).st_size)
        if self.armed:
            self.armed = False
            raise OSError(5, "Input/output error")
        os.fsync(fd)

    def __getattr__(self, name: str) -> object:
        return getattr(os, name)


@pytest.fixture
def failing_fsync(monkeypatch: pytest.MonkeyPatch) -> _FailNextFsync:
    proxy = _FailNextFsync()
    monkeypatch.setattr(wal_module, "os", proxy)
    return proxy


class _TruncateRefused:
    """A real handle whose `truncate` raises `error`; everything else is the real handle."""

    def __init__(self, handle: Any, error: OSError) -> None:
        self._handle = handle
        self._error = error

    def __enter__(self) -> _TruncateRefused:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._handle.close()

    def truncate(self, _size: int) -> int:
        raise self._error

    def __getattr__(self, name: str) -> Any:
        return getattr(self._handle, name)


def _patch_open(
    monkeypatch: pytest.MonkeyPatch,
    *,
    refuse: dict[str, OSError] | None = None,
    truncate_refused: OSError | None = None,
) -> list[str]:
    """Replace `open` in `wal` and return the modes it is called with, in order. A mode in
    `refuse` raises its error instead of opening; with `truncate_refused` the `r+b` handle's
    `truncate` raises that error."""
    modes: list[str] = []
    refused = refuse or {}

    def _open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        modes.append(mode)
        if mode in refused:
            raise refused[mode]
        handle = builtins.open(file, mode, *args, **kwargs)
        if mode == "r+b" and truncate_refused is not None:
            return _TruncateRefused(handle, truncate_refused)
        return handle

    monkeypatch.setattr(wal_module, "open", _open, raising=False)
    return modes


def _ids(wal: AuditWal) -> list[str]:
    return [r["record_id"] for _, r in wal.replay()]


def test_wal_failed_append_is_cut_back_before_a_later_open(
    tmp_path: Path, failing_fsync: _FailNextFsync
) -> None:
    path = tmp_path / "w.wal"
    wal = AuditWal(path)
    wal.append({"record_id": "a"})
    failing_fsync.armed = True
    with pytest.raises(OSError):
        wal.append({"record_id": "b"})
    assert path.read_bytes() == encode_frame({"record_id": "a"})
    assert [r["record_id"] for _, r in wal.read_pending(10)] == ["a"]
    assert _ids(AuditWal(path)) == ["a"]


def test_wal_failed_cut_back_keeps_the_original_error_and_the_next_append_truncates(
    tmp_path: Path, failing_fsync: _FailNextFsync, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "w.wal"
    wal = AuditWal(path)
    wal.append({"record_id": "a"})
    denied = {"once": True}

    def _open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if mode == "r+b" and denied["once"]:
            denied["once"] = False
            raise PermissionError(13, "Permission denied")
        return builtins.open(file, mode, *args, **kwargs)

    monkeypatch.setattr(wal_module, "open", _open, raising=False)
    failing_fsync.armed = True
    with pytest.raises(OSError) as raised:
        wal.append({"record_id": "b"})
    assert raised.value.errno == 5  # the append's own error, not the cut-back's
    assert _ids(wal) == ["a"]
    wal.append({"record_id": "c"})
    assert wal.torn_tail_truncations == 1
    assert _ids(wal) == ["a", "c"]


def test_wal_replay_never_reads_past_the_acknowledged_end(tmp_path: Path) -> None:
    path = tmp_path / "w.wal"
    wal = AuditWal(path)
    wal.append({"record_id": "a"})
    with open(path, "ab") as fh:  # a complete frame whose append raised and was not cut back
        fh.write(encode_frame({"record_id": "b"}))
    batch = wal.read_pending(10)
    assert [r["record_id"] for _, r in batch] == ["a"]
    wal.append({"record_id": "c"})
    wal.mark_committed(batch[-1][0])
    wal.compact()
    assert _ids(wal) == ["c"]


@pytest.mark.parametrize("refused_step", ["open", "truncate"])
def test_wal_failed_cut_back_is_logged_critical_once_with_the_error_type_only(
    tmp_path: Path,
    failing_fsync: _FailNextFsync,
    monkeypatch: pytest.MonkeyPatch,
    refused_step: str,
) -> None:
    path = tmp_path / "w.wal"
    wal = AuditWal(path)
    wal.append({"record_id": "a"})
    denied = PermissionError(13, "Permission denied")
    if refused_step == "open":
        _patch_open(monkeypatch, refuse={"r+b": denied})
    else:
        _patch_open(monkeypatch, truncate_refused=denied)
    failing_fsync.armed = True
    with capture_logs() as logs, pytest.raises(OSError) as raised:
        wal.append({"record_id": "b"})
    assert raised.value.errno == 5  # the append's own error, not the cut-back's
    assert logs == [
        {
            "event": "audit.wal.cut_back_failed",
            "log_level": "critical",
            "error": "PermissionError",
            "path": str(path),
        }
    ]


def test_wal_cut_back_that_succeeds_is_not_logged(
    tmp_path: Path, failing_fsync: _FailNextFsync
) -> None:
    wal = AuditWal(tmp_path / "w.wal")
    wal.append({"record_id": "a"})
    failing_fsync.armed = True
    with capture_logs() as logs, pytest.raises(OSError):
        wal.append({"record_id": "b"})
    assert logs == []


def test_wal_cut_back_is_synced_to_disk_after_the_cut(
    tmp_path: Path, failing_fsync: _FailNextFsync
) -> None:
    wal = AuditWal(tmp_path / "w.wal")
    acknowledged = wal.append({"record_id": "a"})
    failing_fsync.sizes.clear()
    failing_fsync.armed = True
    with pytest.raises(OSError):
        wal.append({"record_id": "b"})
    written = acknowledged + len(encode_frame({"record_id": "b"}))
    assert failing_fsync.sizes == [written, acknowledged]  # the failed sync, then the cut's own


def test_wal_append_that_cannot_open_skips_the_cut_back(
    tmp_path: Path, failing_fsync: _FailNextFsync, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "w.wal"
    wal = AuditWal(path)
    wal.append({"record_id": "a"})
    synced = len(failing_fsync.sizes)
    modes = _patch_open(monkeypatch, refuse={"ab": PermissionError(13, "Permission denied")})
    with pytest.raises(PermissionError):
        wal.append({"record_id": "b"})
    assert modes == ["ab"]  # nothing was written, so no `r+b` handle is opened to cut back
    assert len(failing_fsync.sizes) == synced
    assert path.read_bytes() == encode_frame({"record_id": "a"})


@pytest.mark.parametrize(
    "mangle",
    [
        pytest.param(
            lambda d: d[:-2] + bytes([d[-2] ^ 0x01]) + d[-1:], id="checksum-digit-flipped"
        ),
        pytest.param(lambda d: d[:-3], id="file-shorter-than-the-acknowledged-end"),
    ],
)
def test_wal_replay_raises_on_an_invalid_frame_inside_the_acknowledged_end(
    tmp_path: Path, mangle: Callable[[bytes], bytes]
) -> None:
    path = tmp_path / "w.wal"
    wal = AuditWal(path)
    first_end = wal.append({"record_id": "a"})
    wal.append({"record_id": "b"})  # acknowledged, so complete when it was appended
    path.write_bytes(mangle(path.read_bytes()))
    with pytest.raises(AuditWalCorrupt) as raised:
        list(wal.replay())
    assert raised.value.offset == first_end


@pytest.mark.parametrize(
    "tail",
    [
        pytest.param(encode_frame({"record_id": "b"})[:-4], id="partial-frame"),
        pytest.param(
            encode_frame({"record_id": "b"}).replace(b'"b"', b'"x"'), id="bad-checksum-frame"
        ),
        pytest.param(b"\x00\xffnot a frame", id="garbage"),
    ],
)
def test_wal_replay_still_skips_an_unacknowledged_tail_and_the_next_append_cuts_it(
    tmp_path: Path, tail: bytes
) -> None:
    path = tmp_path / "w.wal"
    wal = AuditWal(path)
    wal.append({"record_id": "a"})
    with open(path, "ab") as fh:  # what an append that never returned left behind
        fh.write(tail)
    with capture_logs() as logs:
        assert _ids(wal) == ["a"]
    assert len(logs) == 1
    assert "torn tail" in logs[0]["event"]
    wal.append({"record_id": "c"})
    assert wal.torn_tail_truncations == 1
    assert _ids(wal) == ["a", "c"]
