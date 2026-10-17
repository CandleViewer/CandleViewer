"""Bounded on-disk WAL for durable audit buffering (ticket "Scope /
Deliverables": "writes are asynchronous but survive a Postgres outage via
the bounded on-disk WAL described in `20-architecture.md` Sec.F8, replayed
on recovery in original order so the chain stays monotonic").

Format (PR #1561 N1): a sequence of self-validating frames
`<len>\\n<json>\\n<crc32>\\n` — `len` is the decimal byte length of the
canonical JSON body, `crc32` the 8-hex-digit CRC-32 of those bytes. Each
frame is `fsync`'d before `append()` returns, so a process kill immediately
after a successful `append()` still has the record on disk. A companion
`<file>.committed` cursor file holds the byte offset up to which records
have been durably written to Postgres; `replay()` resumes from that offset.

Torn tails (N1): a crash mid-`write` can leave a partial frame at EOF. On
open, and before every append, the file is truncated back to the last good
frame boundary (logged CRITICAL, counted in `torn_tail_truncations`) so a
new record is never glued onto garbage. The torn frame was never
acknowledged (`append()` had not returned), so nothing accepted is lost.
A complete frame whose `append()` raised is unacknowledged too: the failed
append truncates it at once (best effort), and `replay()` reads only up to
the acknowledged end in any case.
`replay()` stops at, and logs, a bad frame that reaches EOF; a bad frame
with more data after it is real corruption/tampering and raises
`AuditWalCorrupt` — never skipped.

Bounded, never lossy (C-2.9/C-2.18): `append()` raises `AuditWalFull` once
the file would exceed `max_bytes`. `AuditWriter` then compacts the committed
prefix and retries; if still full the writer raises `AuditUnavailable` and
the caller must refuse the audited action.

Idempotency: every record carries a `record_id` (uuid) that is UNIQUE in
`audit_log`, so the one crash window this file cannot close (row committed to
Postgres, cursor not yet advanced) replays as an `ON CONFLICT DO NOTHING`.
"""

from __future__ import annotations

import contextlib
import json
import os
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import structlog

from candleviewer.audit.errors import AuditError


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


_MAX_LEN_DIGITS = 10
_CRC_FIELD = 9  # 8 hex digits + "\n"


class AuditWalFull(AuditError):
    """Raised by `AuditWal.append` when the WAL file has reached `max_bytes`."""


class AuditWalCorrupt(AuditError):
    """A frame *before* the end of the WAL fails validation: data was lost
    or tampered with. Never silently skipped."""

    def __init__(self, offset: int) -> None:
        super().__init__(f"audit WAL corrupt at byte offset {offset}")
        self.offset = offset


def encode_frame(record: dict[str, Any]) -> bytes:
    body = json.dumps(record, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return b"%d\n%s\n%08x\n" % (len(body), body, zlib.crc32(body))


def _header(data: bytes, pos: int) -> tuple[int, int] | None:
    """`(newline_index, declared_len)` of the frame header at `pos`."""
    nl = data.find(b"\n", pos, pos + _MAX_LEN_DIGITS + 1)
    if nl <= pos or not data[pos:nl].isdigit():
        return None
    return nl, int(data[pos:nl])


def _parse_frame(data: bytes, pos: int) -> tuple[int, dict[str, Any]] | None:
    """`(end, record)` for a complete, checksum-valid frame at `pos`, else None."""
    header = _header(data, pos)
    if header is None:
        return None
    nl, length = header
    body_end = nl + 1 + length
    end = body_end + 1 + _CRC_FIELD
    if end > len(data) or data[body_end : body_end + 1] != b"\n" or data[end - 1] != 0x0A:
        return None
    body = data[nl + 1 : body_end]
    if data[body_end + 1 : end - 1] != b"%08x" % zlib.crc32(body):
        return None
    try:
        record = json.loads(body)
    except ValueError:
        return None
    return (end, record) if isinstance(record, dict) else None


def _is_torn_tail(data: bytes, pos: int) -> bool:
    """True if the invalid bytes at `pos` are a truncated final frame: an
    incomplete header, or a declared frame that reaches or passes EOF."""
    if b"\n" not in data[pos : pos + _MAX_LEN_DIGITS + 1]:
        return len(data) - pos <= _MAX_LEN_DIGITS and data[pos:].isdigit()
    header = _header(data, pos)
    if header is None:
        return False
    nl, length = header
    return nl + 1 + length + 1 + _CRC_FIELD >= len(data)


def _scan(data: bytes, start: int) -> tuple[list[tuple[int, dict[str, Any]]], int]:
    """Good frames from `start` and the last good boundary; raises
    `AuditWalCorrupt` on a bad frame that is not a torn tail."""
    out: list[tuple[int, dict[str, Any]]] = []
    pos = start
    while pos < len(data):
        parsed = _parse_frame(data, pos)
        if parsed is None:
            if _is_torn_tail(data, pos):
                break
            raise AuditWalCorrupt(pos)
        pos, record = parsed
        out.append((pos, record))
    return out, pos


class AuditWal:
    """A single append-only WAL file plus its commit cursor.

    Not safe for concurrent writers — `AuditWriter` owns exactly one
    `AuditWal` instance and serialises all appends through `_wal_lock`.
    `replay()` sees the frames present at open plus this instance's own
    appends, so a second instance on the same file never reads newer frames.
    """

    def __init__(self, path: Path, max_bytes: int = 64 * 1024 * 1024) -> None:
        self._path = path
        self._cursor_path = path.with_suffix(path.suffix + ".committed")
        self._max_bytes = max_bytes
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()
        if not self._cursor_path.exists():
            self._cursor_path.write_text("0", encoding="utf-8")
        self.torn_tail_truncations = 0
        _, self._end = _scan(self._path.read_bytes(), 0)
        self._truncate_torn_tail()

    def _truncate_torn_tail(self) -> None:
        size = self._path.stat().st_size
        if size <= self._end:
            return
        self.torn_tail_truncations += 1
        logger().critical(
            "audit WAL %s: truncating %d-byte torn tail at offset %d",
            self._path,
            size - self._end,
            self._end,
        )
        with open(self._path, "r+b") as fh:
            fh.truncate(self._end)
            fh.flush()
            os.fsync(fh.fileno())

    def append(self, record: dict[str, Any]) -> int:
        """Durably append (write + `fsync`) one frame and return the byte
        offset just past it. Raises `AuditWalFull` if this would exceed
        `max_bytes`; any `OSError` propagates (the writer fails closed). The
        bytes it wrote are cut back to the acknowledged end before it raises
        (best effort), so a later open does not read them as acknowledged;
        when that cut fails too, the next append truncates them."""
        encoded = encode_frame(record)
        self._truncate_torn_tail()
        if self._end + len(encoded) > self._max_bytes:
            raise AuditWalFull(f"WAL at {self._path} would exceed max_bytes={self._max_bytes}")
        try:
            with open(self._path, "ab") as fh:
                fh.write(encoded)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            # Cut back once the first handle has closed (a close can flush again), on a fresh
            # handle, never past the acknowledged end. Best effort: the caller sees the original
            # error either way.
            with contextlib.suppress(OSError):
                if self._path.stat().st_size > self._end:
                    with open(self._path, "r+b") as fh:
                        fh.truncate(self._end)
                        fh.flush()
                        os.fsync(fh.fileno())
            raise
        self._end += len(encoded)
        return self._end

    def committed_offset(self) -> int:
        return int(self._cursor_path.read_text(encoding="utf-8").strip() or "0")

    def mark_committed(self, offset: int) -> None:
        """Record that every byte up to `offset` is durably in Postgres.
        `fsync`'d so a crash right after does not replay committed records."""
        tmp = self._cursor_path.with_suffix(".ctmp")
        tmp.write_text(str(offset), encoding="utf-8")
        with open(tmp, "r+", encoding="utf-8") as fh:
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self._cursor_path)

    def replay(self) -> Iterator[tuple[int, dict[str, Any]]]:
        """Yield `(end_offset, record)` for every record after
        `committed_offset()`, in append order. A torn tail is logged and
        skipped; mid-file corruption raises `AuditWalCorrupt`. Only the
        acknowledged part of the file is read: bytes past `_end` belong to an
        append that never returned, and the next append truncates them."""
        raw = self._path.read_bytes()
        frames, good_end = _scan(raw[: self._end], self.committed_offset())
        if good_end < len(raw):
            logger().critical("audit WAL %s: skipping torn tail at offset %d", self._path, good_end)
        yield from frames

    def read_pending(self, max_records: int) -> list[tuple[int, dict[str, Any]]]:
        """Up to `max_records` uncommitted `(end_offset, record)` pairs."""
        out: list[tuple[int, dict[str, Any]]] = []
        for item in self.replay():
            out.append(item)
            if len(out) >= max_records:
                break
        return out

    def compact(self) -> None:
        """Drop every byte already committed so the file does not grow
        forever. The writer task is the sole caller of this and `replay()`."""
        committed = self.committed_offset()
        if committed == 0:
            return
        with open(self._path, "rb") as fh:
            fh.seek(committed)
            remainder = fh.read(max(0, self._end - committed))
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "wb") as fh:
            fh.write(remainder)
            fh.flush()
            os.fsync(fh.fileno())
        # Cursor reset *before* the swap: a crash in between replays the
        # old (committed) prefix, which `record_id` makes a no-op; the other
        # order could skip uncommitted records.
        self.mark_committed(0)
        tmp.replace(self._path)
        self._end = len(remainder)
