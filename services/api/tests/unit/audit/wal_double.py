"""A recording file double for `candleviewer.audit.wal` (E50-T63): it counts what each WAL call
reads, writes and `fsync`s, so a budget is proven by structure, never by a wall-clock assertion
(the `test_page_structure_budget.py` precedent, C-2.17)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from candleviewer.audit import wal as wal_module


@dataclass
class Recorded:
    """Bytes per `read()` and per `write()`, by file name, and the `fsync` calls."""

    reads: list[tuple[str, int]] = field(default_factory=list)
    writes: list[tuple[str, int]] = field(default_factory=list)
    fsyncs: int = 0

    def clear(self) -> None:
        self.reads.clear()
        self.writes.clear()
        self.fsyncs = 0

    def read_sizes(self, name: str) -> list[int]:
        return [n for file, n in self.reads if file == name]

    def write_sizes(self, name: str) -> list[int]:
        return [n for file, n in self.writes if file == name]


class _File:
    def __init__(self, inner: Any, name: str, recorded: Recorded) -> None:
        self._inner, self._name, self._recorded = inner, name, recorded

    def __enter__(self) -> _File:
        return self

    def __exit__(self, *exc: object) -> None:
        self._inner.close()

    def read(self, size: int = -1) -> Any:
        data = self._inner.read(size)
        self._recorded.reads.append((self._name, len(data)))
        return data

    def write(self, data: Any) -> int:
        self._recorded.writes.append((self._name, len(data)))
        written: int = self._inner.write(data)
        return written

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._inner, attr)


def record_wal_io(monkeypatch: pytest.MonkeyPatch) -> Recorded:
    """Route `open()` and `os.fsync()` inside `audit/wal.py` through the recorder."""
    recorded = Recorded()
    real_open, real_fsync = open, os.fsync

    def recording_open(path: Any, *args: Any, **kwargs: Any) -> _File:
        return _File(real_open(path, *args, **kwargs), Path(path).name, recorded)

    def recording_fsync(fd: int) -> None:
        recorded.fsyncs += 1
        real_fsync(fd)

    monkeypatch.setattr(wal_module, "open", recording_open, raising=False)
    monkeypatch.setattr(wal_module.os, "fsync", recording_fsync)
    return recorded
