"""The audit export writer (#889 S8, ADR-0039): the file whose bytes `24-internal-schemas.md`
§15.7 defines, for a planned chain span. Nothing routes to it yet: S10 plans, signs and wires it,
and S9 serves the file.

The header line, then one line per entry of the span in id order, read in keyset batches with the
renderings verify hashes (`AuditExportReader`); gzipped as one deterministic stream when
`compressed`, and hashed (SHA-256) as written. The file is created `0600`, `O_EXCL` and
`O_NOFOLLOW`, under a temporary name in `<data dir>/audit-exports/` (`0700`, opened `O_NOFOLLOW`),
synced, then linked to its own name, which it never replaces. Every file step runs on a worker
thread (`thread_future`), one at a time, and any failure, a cancel included, removes what the
export made: nothing is left on disk, unless removing it is what failed.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import struct
import uuid
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from candleviewer.audit.errors import AuditError
from candleviewer.audit.repository import EXPORT_COLUMNS, AuditExportReader
from candleviewer.observability.context import thread_future
from candleviewer.settings import Environment, Settings

FORMAT: Final = "cv.audit.export.v1"
EXPORT_DIR: Final = "audit-exports"
EXPORT_MAX_ROWS: int = Settings.model_fields["audit_export_max_rows"].default
EXPORT_MAX_BYTES: int = Settings.model_fields["audit_export_max_bytes"].default
#: Verify's rows per batch: an export batch is verify's statement and more columns, under the same
#: byte budget. The export's own constant, so that retuning verify leaves the export as it is.
EXPORT_BATCH_SIZE: Final = 10_000
FIRST_BATCH: Final = 256  #: the first batch's rows at most, so no walk starts with a full batch
#: The gzip member header §15.7 fixes (RFC 1952): ID1 ID2, CM 8, FLG 0 (no name, comment or extra
#: field), MTIME 0, XFL 2 (level 9), OS 255. On Python 3.12 `gzip.compress(mtime=0)` writes OS 3
#: and `GzipFile` a name, so the writer frames a raw deflate stream itself.
GZIP_HEADER: Final = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"
_SPAN: Final = ("environment", "first_id", "last_id", "anchor_hash", "head_id", "head_hash")
_DIR_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
#: Never opens what already holds the name, a link included, and never waits on it.
_TMP_FLAGS: Final = (
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
)


class ExportTooLarge(AuditError):
    """The span holds more than `max_rows` entries, or the file would pass `max_bytes`: the job
    fails with `export_too_large`, and nothing is left on disk."""

    code = "export_too_large"

    def __init__(self) -> None:
        super().__init__("the audit export is over its size limit")


class ExportSpanChanged(AuditError):
    """The entries read are not the planned span (its first or last entry, its anchor or its
    count differ), so the header would not describe the file: the job fails (`internal_error`)."""

    code = "internal_error"

    def __init__(self) -> None:
        super().__init__("the audit export span is not the planned one")


class ExportFileFailed(AuditError):
    """A file step's `OSError`, as its errno alone (no cause or context), since its file names can
    hold the export directory's path: the job fails (`internal_error`), and nothing is left on
    disk unless removing it is the step that failed."""

    code = "internal_error"

    def __init__(self, errno: int | None) -> None:
        super().__init__(f"an audit export file step failed (errno {errno})")
        self.errno = errno


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportPlan:
    """What the job planned (§15.7 **Header**), refused (`ValueError`) unless it holds together:
    the window `[from_ts, to_ts)`, aware and starting before it ends (22 `exportAuditLog`), the
    span from `first_id` to `last_id`, `1 <= first_id <= last_id <= head_id`, and its anchor (the
    first entry's `prev_hash`; all three `None` for an empty span), the chain head when the job
    started, and the signing key's id and base64 public key, which the header names and the
    writer never uses. S10 plans it, and its read of the span's first and last ids in the window,
    as of `head_id`, needs the read port's bounds."""

    from_ts: datetime
    to_ts: datetime
    first_id: int | None
    last_id: int | None
    anchor_hash: str | None
    head_id: int
    head_hash: str
    environment: Environment
    key_id: str
    public_key: str
    compressed: bool

    def __post_init__(self) -> None:
        if self.from_ts.utcoffset() is None or self.to_ts.utcoffset() is None:
            raise ValueError("an export window bound must be timezone-aware")
        if self.from_ts >= self.to_ts:
            raise ValueError("an export window must start before it ends")
        span = (self.first_id, self.last_id, self.anchor_hash)
        if None in span and span != (None, None, None):
            raise ValueError("an export span names its first id, last id and anchor, or none")
        first, last = self.first_id, self.last_id
        if first is not None and last is not None and not 1 <= first <= last <= self.head_id:
            raise ValueError("an export span holds 1 <= first_id <= last_id <= head_id")


@dataclass(frozen=True, slots=True)
class ExportFile:
    """The file written, `name` in the export directory: its size and lowercase hex SHA-256 as
    written (the gzip bytes when compressed), and the span it holds."""

    name: str
    size_bytes: int
    sha256: str
    row_count: int
    first_id: int | None
    last_id: int | None


def _utc(ts: datetime) -> str:
    """`YYYY-MM-DDTHH:MM:SS.ffffffZ`, of an aware time: `ExportPlan` refuses a naive one."""
    return ts.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="microseconds") + "Z"


def _line(value: dict[str, Any]) -> bytes:
    """A §15.7 line: compact JSON, members sorted, only `"`, `\\` and U+0000 to U+001F escaped,
    in UTF-8 and ending in `\\n`."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return text.encode() + b"\n"


def _header(plan: ExportPlan, row_count: int) -> bytes:
    head = {"format": FORMAT, "from": _utc(plan.from_ts), "to": _utc(plan.to_ts)}
    keys = {"row_count": row_count, "key_id": plan.key_id, "public_key": plan.public_key}
    return _line(head | keys | {name: getattr(plan, name) for name in _SPAN})


def _entry(row: tuple[Any, ...], start: datetime, end: datetime) -> bytes:
    """An entry's line; `in_window` compares its `event_ts` (the trigger's text) as an instant."""
    entry = dict(zip(EXPORT_COLUMNS, row, strict=True))
    entry["in_window"] = start <= datetime.fromisoformat(entry["event_ts"]) < end
    return _line(entry)


class _Sink:
    """The file side of one export, each method a blocking step for `_off_loop`: the temporary
    file, the gzip member around one raw deflate stream (flushed only at the end), the SHA-256 of
    the bytes as written and the byte cap, checked before each write."""

    def __init__(self, directory: Path, name: str, compressed: bool, max_bytes: int) -> None:
        self.directory, self.name, self._tmp, self._max = directory, name, f".{name}.tmp", max_bytes
        self._deflate = zlib.compressobj(9, zlib.DEFLATED, -15) if compressed else None
        self.sha, self.size, self._crc, self._isize = hashlib.sha256(), 0, 0, 0
        self._dir = self._fd = -1
        self._made = self._linked = False

    def open(self) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._dir = os.open(self.directory, _DIR_FLAGS)  # a link at the directory's name fails
        os.fchmod(self._dir, 0o700)
        self._fd = os.open(self._tmp, _TMP_FLAGS, 0o600, dir_fd=self._dir)
        self._made = True
        os.fchmod(self._fd, 0o600)  # whatever the umask
        if self._deflate is not None:
            self._emit(GZIP_HEADER)

    def write(self, plain: bytes) -> None:
        if self._deflate is not None:
            self._crc, self._isize = zlib.crc32(plain, self._crc), self._isize + len(plain)
            plain = self._deflate.compress(plain)
        self._emit(plain)

    def entries(self, rows: list[tuple[Any, ...]], start: datetime, end: datetime) -> None:
        self.write(b"".join(_entry(row, start, end) for row in rows))

    def finish(self) -> None:
        """The gzip trailer (CRC-32, then the size mod 2^32), fsync, then the link to the file's
        name, which fails if anything holds it, the temporary name's removal and a directory
        fsync."""
        if self._deflate is not None:
            trailer = struct.pack("<II", self._crc, self._isize & 0xFFFFFFFF)
            self._emit(self._deflate.flush() + trailer)
        os.fsync(self._fd)
        os.link(self._tmp, self.name, src_dir_fd=self._dir, dst_dir_fd=self._dir)
        self._linked = True
        os.unlink(self._tmp, dir_fd=self._dir)
        self._made = False
        os.fsync(self._dir)

    def close(self, keep: bool) -> None:
        """Unless the file is kept, remove what this export made, never anything else, each name
        whatever the other's removal does; then close, and raise the first failure."""
        failed: list[OSError] = []
        try:
            for name, made in () if keep else ((self._tmp, self._made), (self.name, self._linked)):
                try:
                    if made:
                        with contextlib.suppress(FileNotFoundError):
                            os.unlink(name, dir_fd=self._dir)
                except OSError as exc:
                    failed.append(exc)
        finally:
            for fd in (self._fd, self._dir):
                if fd >= 0:
                    with contextlib.suppress(OSError):
                        os.close(fd)
        if failed:
            raise failed[0]

    def _emit(self, data: bytes) -> None:
        if self.size + len(data) > self._max:
            raise ExportTooLarge
        self.sha.update(data)
        self.size += len(data)
        view = memoryview(data)
        while view:
            view = view[os.write(self._fd, view) :]


async def _off_loop[T](step: Callable[..., T], *args: Any) -> T:
    """`step(*args)` on a worker thread: a plain `thread_future`, never a Task, which
    `asyncio.run`'s teardown would cancel while the step still writes (#2250, `audit/writer.py`).
    A cancel waits for the step to return, as `ChainHasher.run` waits on its `executor_future`, so
    no step overlaps the next or the cleanup; its error is then retrieved, the cancel raised."""
    job = thread_future(step, *args)
    cancel: asyncio.CancelledError | None = None
    while not job.done():
        try:
            await asyncio.wait([job])  # never cancels the job
        except asyncio.CancelledError as exc:
            cancel = cancel or exc
    if cancel is not None:
        job.exception()  # retrieved, as `backup_artefacts.py` does: the cancel goes on instead
        raise cancel
    try:
        return job.result()
    except OSError as exc:
        failed = exc.errno
    raise ExportFileFailed(failed)  # outside the handler: no cause, no context, so no path


async def _stream(
    reader: AuditExportReader, sink: _Sink, plan: ExportPlan, span: tuple[int, int, int], size: int
) -> None:
    """The span `(first, last, count)` in keyset batches. A batch may stop short on the read
    port's byte budget, so only the last id ends the walk, and the next batch asks for at most
    twice the rows the last one held, as verify's walk does, starting from at most `FIRST_BATCH`.
    What is read must be the plan's: the first entry and its anchor, every id up to the last, and
    the count."""
    first, last, count = span
    after, limit, seen = first - 1, min(size, FIRST_BATCH), 0
    while after < last:
        rows = await reader.fetch_export_batch(after_id=after, to_id=last, limit=limit)
        if not rows or (seen == 0 and (rows[0][0], rows[0][1]) != (first, plan.anchor_hash)):
            raise ExportSpanChanged
        seen += len(rows)
        if seen > count:
            raise ExportSpanChanged
        await _off_loop(sink.entries, rows, plan.from_ts, plan.to_ts)
        after, limit = rows[-1][0], min(size, 2 * len(rows))
    if seen != count:
        raise ExportSpanChanged


async def write_export(
    plan: ExportPlan,
    reader: AuditExportReader,
    *,
    data_dir: Path,
    job_id: uuid.UUID,
    max_rows: int = EXPORT_MAX_ROWS,
    max_bytes: int = EXPORT_MAX_BYTES,
    batch_size: int = EXPORT_BATCH_SIZE,
) -> ExportFile:
    """Write `plan`'s file in `<data_dir>/audit-exports/` as `<job_id>.ndjson`, `.ndjson.gz` when
    compressed. The span is counted first, up to `max_rows` and one more: a larger one raises
    `ExportTooLarge` before anything is written, and the count is the header's `row_count`. The
    write that would take the file past `max_bytes` raises it instead, for a small gzip only at
    `finish`: deflate holds its output back. Any failure removes what the export made."""
    first, last, count = plan.first_id, plan.last_id, 0
    if first is not None and last is not None:
        count = await reader.count_export_span(first_id=first, last_id=last, cap=max_rows + 1)
        if count > max_rows:
            raise ExportTooLarge
    name = f"{job_id}.ndjson.gz" if plan.compressed else f"{job_id}.ndjson"
    sink, kept = _Sink(data_dir / EXPORT_DIR, name, plan.compressed, max_bytes), False
    try:
        await _off_loop(sink.open)
        await _off_loop(sink.write, _header(plan, count))
        if first is not None and last is not None:
            await _stream(reader, sink, plan, (first, last, count), batch_size)
        await _off_loop(sink.finish)
        kept = True
    finally:
        await _off_loop(sink.close, kept)
    return ExportFile(name, sink.size, sink.sha.hexdigest(), count, first, last)
