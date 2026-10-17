"""`AuditWal` hands the flusher only acknowledged frames: bytes an append wrote before it raised
are cut back at once, a later open does not read them, and `replay()` never reads past the
acknowledged end even when they are still there."""

from __future__ import annotations

import builtins
import os
from pathlib import Path
from typing import Any

import pytest

from candleviewer.audit import wal as wal_module
from candleviewer.audit.wal import AuditWal, encode_frame


class _FailNextFsync:
    """Stands in for `os` in `wal`; its next `fsync` raises once armed."""

    def __init__(self) -> None:
        self.armed = False

    def fsync(self, fd: int) -> None:
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
