"""Bounded on-disk spill WAL for the StreamWriter (E16-T03, ADR-0015 decision 8).

Layout per stream lane (`<CV_RECORDER_WAL_DIR>/<stream>/`, dirs 0700, files 0600 where the
platform supports it):

- `spill.wal` + `spill.meta` — new spills. The writer appends one **batch** per call (one
  write + one fsync per batch, never per event). `*.meta` holds `{symbol: [min_ts, max_ts]}`
  so a corrupt tail can still be attributed to the symbols it held.
- `replay.wal` + `replay.meta` — `spill.wal` rotated for replay.
- `runs/` — an external sort of `replay.wal`: it is read in bounded chunks (`chunk_rows`
  frames), and each chunk is sorted by `exch_ts` and written as `NNNNNN.run`. Then `READY`
  is written and `replay.wal` is deleted. Replay is a `heapq.merge` (k-way) over buffered run
  readers, so memory is O(runs + one batch), never the whole WAL. `CHECKPOINT` stores how many
  merged records QuestDB has already committed, so a retried replay resumes from there.
- `corrupt/` — the rest of a file after the first frame that fails CRC, or a torn frame. These
  bytes stay counted in the budget, so quarantine cannot grow the disk past the cap.

Frame: `>I length` + `>I crc32(payload)` + orjson
`{"t": stream, "s": symbol, "e": exch_ts, "q": seq, "u": sub, "r": row}`.

The budget (`CV_RECORDER_WAL_MAX_BYTES`) is shared by every lane and counts spill, replay,
runs and corrupt bytes. A frame that does not fit is refused, and the caller turns it into a
`backpressure_drop` gap. While `runs/` is being built, the disk can briefly hold up to twice
the replayed file's size (documented bound: 2x the cap).

All methods are synchronous and are only ever called through `asyncio.to_thread`.
"""

from __future__ import annotations

import contextlib
import heapq
import os
import shutil
import struct
import zlib
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import orjson

_HEADER = struct.Struct(">II")
#: Hard ceiling on one frame (a 500-level snapshot is ~40 KiB); larger = corrupt length.
_MAX_FRAME = 8 * 1024 * 1024
_COPY_CHUNK = 1 << 20
SPILL_NAME = "spill.wal"
REPLAY_NAME = "replay.wal"
RUNS_DIR = "runs"
CORRUPT_DIR = "corrupt"
_READY = "READY"
_CHECKPOINT = "CHECKPOINT"
_MANIFEST = "MANIFEST"
_DAMAGED = "DAMAGED"
_META = "META"
_BINARY = getattr(os, "O_BINARY", 0)


@dataclass(frozen=True, slots=True)
class WalRecord:
    """One recorded row. `(symbol, stream, exch_ts, seq, sub)` is its identity; `sub` is the
    row's index inside one exchange message (a book delta carries many levels)."""

    stream: str
    symbol: str
    exch_ts: int
    seq: int
    sub: int
    row: dict[str, object]

    @property
    def key(self) -> tuple[str, str, int, int, int]:
        return (self.symbol, self.stream, self.exch_ts, self.seq, self.sub)


def encode_frame(rec: WalRecord) -> bytes:
    payload = orjson.dumps(
        {
            "t": rec.stream,
            "s": rec.symbol,
            "e": rec.exch_ts,
            "q": rec.seq,
            "u": rec.sub,
            "r": rec.row,
        }
    )
    return _HEADER.pack(len(payload), zlib.crc32(payload)) + payload


def _decode_payload(payload: bytes) -> WalRecord:
    raw = orjson.loads(payload)
    return WalRecord(
        stream=str(raw["t"]),
        symbol=str(raw["s"]),
        exch_ts=int(raw["e"]),
        seq=int(raw["q"]),
        sub=int(raw["u"]),
        row=dict(raw["r"]),
    )


def read_frames(fh: BinaryIO) -> Iterator[tuple[WalRecord, int]]:
    """Yield `(record, end_offset)` frame by frame from a buffered file. Stops silently at the
    first torn or corrupt frame; the caller compares the last end offset to the file size."""
    offset = fh.tell()
    while True:
        header = fh.read(_HEADER.size)
        if len(header) < _HEADER.size:
            return
        length, crc = _HEADER.unpack(header)
        if length > _MAX_FRAME:
            return
        payload = fh.read(length)
        if len(payload) < length or zlib.crc32(payload) != crc:
            return
        try:
            rec = _decode_payload(payload)
        except (orjson.JSONDecodeError, KeyError, TypeError, ValueError):
            return
        offset += _HEADER.size + length
        yield rec, offset


class WalBudget:
    """Byte budget shared by every lane's WAL files (spill, replay, runs, corrupt)."""

    def __init__(self, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be >= 1")
        self.max_bytes = max_bytes
        self.used = 0


@dataclass(slots=True)
class ReplayPrep:
    """Outcome of `begin_replay`."""

    pending: bool
    corrupt_bytes: int = 0
    #: symbol -> (start, end) exch_ts window lost to the quarantined tail.
    corrupt_windows: dict[str, tuple[int, int]] = field(default_factory=dict)


def _open_append(path: Path) -> int:
    # nosemgrep: cv-recorder-fs-write-unvalidated-path reason=wal-own-dir owner=@CandleViewer/security review=2027-03-25  # noqa: E501 - semgrep marker format is fixed
    return os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _BINARY, 0o600)


def _write_atomic(path: Path, data: bytes, fsync: Callable[[int], None]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    # nosemgrep: cv-recorder-fs-write-unvalidated-path reason=wal-own-dir owner=@CandleViewer/security review=2027-03-25  # noqa: E501 - semgrep marker format is fixed
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _BINARY, 0o600)
    try:
        os.write(fd, data)
        fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _tree_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*.wal") if p.is_file()) + sum(
        p.stat().st_size for p in path.rglob("*.run") if p.is_file()
    )


class SpillWal:
    """The WAL of one stream lane. Not concurrency-safe: the lane serialises access.

    The constructor does no I/O; `open()` (via `to_thread`) creates the directory and
    recovers the budget share of files a previous process left."""

    def __init__(
        self,
        directory: Path,
        budget: WalBudget,
        *,
        chunk_rows: int = 50_000,
        fsync: Callable[[int], None] = os.fsync,
    ) -> None:
        if chunk_rows < 1:
            raise ValueError("chunk_rows must be >= 1")
        self._dir = directory
        self._budget = budget
        self._chunk_rows = chunk_rows
        self._fsync = fsync
        self._spill_windows: dict[str, list[int]] = {}
        #: Frames merged by the last `iter_replay` (see `replay_complete`).
        self.consumed = 0
        #: Non-fatal anomalies for the writer to log (the WAL module does no logging).
        self.warnings: list[str] = []

    # -- paths ---------------------------------------------------------------------------------

    @property
    def spill_path(self) -> Path:
        return self._dir / SPILL_NAME

    @property
    def replay_path(self) -> Path:
        return self._dir / REPLAY_NAME

    @property
    def runs_dir(self) -> Path:
        return self._dir / RUNS_DIR

    @property
    def corrupt_dir(self) -> Path:
        return self._dir / CORRUPT_DIR

    def _meta(self, wal: Path) -> Path:
        return wal.with_suffix(".meta")

    # -- lifecycle -----------------------------------------------------------------------------

    def open(self) -> None:
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(self._dir, 0o700)
        if (self.runs_dir / _READY).exists():
            recovered = _tree_bytes(self.runs_dir)
        else:
            # nosemgrep: cv-recorder-destructive-outside-retention reason=own-runs-dir owner=@CandleViewer/security review=2027-03-25  # noqa: E501 - semgrep marker format is fixed
            shutil.rmtree(self.runs_dir, ignore_errors=True)  # torn run build: rebuilt
            recovered = 0
        recovered += _tree_bytes(self.spill_path) + _tree_bytes(self.replay_path)
        recovered += _tree_bytes(self.corrupt_dir)
        self._budget.used += recovered
        self._spill_windows = self._load_meta(self.spill_path)

    def has_data(self) -> bool:
        if (self.runs_dir / _READY).exists():
            return True
        return any(p.exists() and p.stat().st_size > 0 for p in (self.spill_path, self.replay_path))

    # -- spill (one write + one fsync per batch) -----------------------------------------------

    def append(self, records: list[WalRecord]) -> int:
        """Append the longest prefix of `records` that fits the budget, with a single write
        and a single fsync. Returns how many records were written."""
        chunks: list[bytes] = []
        size = 0
        for rec in records:
            frame = encode_frame(rec)
            if self._budget.used + size + len(frame) > self._budget.max_bytes:
                break
            chunks.append(frame)
            size += len(frame)
        if not chunks:
            return 0
        fd = _open_append(self.spill_path)
        try:
            os.write(fd, b"".join(chunks))
            self._fsync(fd)
        finally:
            os.close(fd)
        self._budget.used += size
        for rec in records[: len(chunks)]:
            w = self._spill_windows.setdefault(rec.symbol, [rec.exch_ts, rec.exch_ts])
            w[0], w[1] = min(w[0], rec.exch_ts), max(w[1], rec.exch_ts)
        # Advisory (not fsync'd): attributes a corrupt tail to the symbols it held.
        self._meta(self.spill_path).write_bytes(orjson.dumps(self._spill_windows))
        return len(chunks)

    def _load_meta(self, wal: Path) -> dict[str, list[int]]:
        try:
            raw = orjson.loads(self._meta(wal).read_bytes())
        except (OSError, orjson.JSONDecodeError):
            return {}
        return {str(k): [int(v[0]), int(v[1])] for k, v in dict(raw).items()}

    # -- replay: rotate -> external sort into runs -> k-way merge with checkpoint ---------------

    def begin_replay(self) -> ReplayPrep:
        """Make `runs/` ready for the next replay. Rotates `spill.wal` only if no replay is
        pending, so frames spilled during a replay wait for the next round. On `OSError` the
        partial `runs/` is removed and `replay.wal` stays as it was; the error propagates."""
        if (self.runs_dir / _READY).exists():
            return ReplayPrep(pending=True)
        if not self.replay_path.exists():
            if not self.spill_path.exists():
                return ReplayPrep(pending=False)
            os.replace(self.spill_path, self.replay_path)
            if self._meta(self.spill_path).exists():
                os.replace(self._meta(self.spill_path), self._meta(self.replay_path))
            self._spill_windows = {}
        try:
            return self._build_runs()
        except OSError:
            self._discard_runs()
            raise

    def _discard_runs(self) -> None:
        self._budget.used -= _tree_bytes(self.runs_dir)
        # nosemgrep: cv-recorder-destructive-outside-retention reason=own-runs-dir owner=@CandleViewer/security review=2027-03-25  # noqa: E501 - semgrep marker format is fixed
        shutil.rmtree(self.runs_dir, ignore_errors=True)

    def _build_runs(self) -> ReplayPrep:
        # nosemgrep: cv-recorder-destructive-outside-retention reason=own-runs-dir owner=@CandleViewer/security review=2027-03-25  # noqa: E501 - semgrep marker format is fixed
        shutil.rmtree(self.runs_dir, ignore_errors=True)
        self.runs_dir.mkdir(mode=0o700)
        size = self.replay_path.stat().st_size
        last_good = 0
        last_ts: dict[str, int] = {}
        n_runs = 0
        manifest: dict[str, dict[str, object]] = {}
        with self.replay_path.open("rb", buffering=_COPY_CHUNK) as fh:
            frames = read_frames(fh)
            while True:
                chunk: list[WalRecord] = []
                for rec, end in frames:
                    chunk.append(rec)
                    last_good = end
                    last_ts[rec.symbol] = max(last_ts.get(rec.symbol, rec.exch_ts), rec.exch_ts)
                    if len(chunk) >= self._chunk_rows:
                        break
                if not chunk:
                    break
                chunk.sort(key=lambda r: r.exch_ts)
                run = self.runs_dir / f"{n_runs:06d}.run"
                data = b"".join(encode_frame(r) for r in chunk)
                _write_atomic(run, data, self._fsync)
                self._budget.used += len(data)
                windows: dict[str, list[int]] = {}
                for r in chunk:
                    w = windows.setdefault(r.symbol, [r.exch_ts, r.exch_ts])
                    w[0], w[1] = min(w[0], r.exch_ts), max(w[1], r.exch_ts)
                manifest[run.name] = {
                    "frames": len(chunk),
                    "bytes": len(data),
                    "crc": zlib.crc32(data),
                    "windows": windows,
                }
                n_runs += 1
        prep = ReplayPrep(pending=n_runs > 0)
        corrupt = size - last_good
        if corrupt:
            self._quarantine(last_good, corrupt)
            prep.corrupt_bytes = corrupt
            for symbol, (lo, hi) in self._load_meta(self.replay_path).items():
                start = last_ts.get(symbol, lo)
                if symbol not in last_ts or hi > start:
                    prep.corrupt_windows[symbol] = (start, max(hi, start + 1))
        _write_atomic(self.runs_dir / _MANIFEST, orjson.dumps(manifest), self._fsync)
        self.commit(0)
        _write_atomic(self.runs_dir / _READY, b"", self._fsync)
        # The good bytes now live in runs/; the corrupt bytes stay counted in corrupt/.
        self._budget.used -= last_good
        self.replay_path.unlink()
        self._meta(self.replay_path).unlink(missing_ok=True)
        if not prep.pending:
            self.finish_replay()
        return prep

    def _quarantine(self, offset: int, length: int) -> None:
        self.corrupt_dir.mkdir(mode=0o700, exist_ok=True)
        name = self.corrupt_dir / f"{len(list(self.corrupt_dir.iterdir())):06d}.wal"
        # nosemgrep: cv-recorder-fs-write-unvalidated-path reason=wal-own-dir owner=@CandleViewer/security review=2027-03-25  # noqa: E501 - semgrep marker format is fixed
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _BINARY, 0o600)
        try:
            with self.replay_path.open("rb") as src:
                src.seek(offset)
                while block := src.read(_COPY_CHUNK):
                    os.write(fd, block)
            self._fsync(fd)
        finally:
            os.close(fd)

    def _manifest(self) -> dict[str, dict[str, object]]:
        try:
            raw = orjson.loads((self.runs_dir / _MANIFEST).read_bytes())
        except (OSError, orjson.JSONDecodeError):
            return {}
        return {str(k): dict(v) for k, v in dict(raw).items()}

    def total(self) -> int:
        """Frames in the (verified) runs: the range a valid checkpoint lives in."""
        return sum(int(str(m["frames"])) for m in self._manifest().values())

    def checkpoint(self) -> int:
        """The committed merge index, or 0 when it is unreadable, bound to another run set,
        negative or past the end. Restarting is safe (DEDUP UPSERT KEYS) and logged."""
        total = self.total()
        try:
            raw = orjson.loads((self.runs_dir / _CHECKPOINT).read_bytes())
            ck, bound = int(raw["ck"]), int(raw["total"])
        except (OSError, orjson.JSONDecodeError, KeyError, TypeError, ValueError):
            ck, bound = -1, -1
        if bound != total or not 0 <= ck <= total:
            if not (ck == 0 and bound == total):
                self.warnings.append(
                    f"replay checkpoint invalid (ck={ck}, bound={bound}, total={total}); "
                    "restarting at 0"
                )
            return 0
        return ck

    def commit(self, merged_index: int) -> None:
        """Durably record that merged records `[0, merged_index)` reached QuestDB. The value is
        bound to the run set's total, so a stale checkpoint can never skip records."""
        payload = orjson.dumps({"ck": merged_index, "total": self.total()})
        _write_atomic(self.runs_dir / _CHECKPOINT, payload, self._fsync)

    def _damaged(self) -> dict[str, list[int]]:
        try:
            raw = orjson.loads((self.runs_dir / _DAMAGED).read_bytes())
        except (OSError, orjson.JSONDecodeError):
            return {}
        return {str(k): [int(v[0]), int(v[1])] for k, v in dict(raw).items()}

    def verify_runs(self) -> ReplayPrep:
        """Check every run against the manifest (size + CRC). A run that is missing, truncated
        or altered is moved whole to `corrupt/` (still counted in the budget) and reported with
        its symbols' windows. The checkpoint is then reset (the merge order changed).

        Crash safety: the damaged windows are durably written to `runs/DAMAGED` *before* any
        file moves, and are reported from that marker on every call until
        `ack_damaged()`. A crash between the quarantine and the gap being taken therefore
        still raises the gap on restart."""
        manifest = self._manifest()
        damaged = self._damaged()
        bad: list[tuple[str, int]] = []
        listed = {p.name for p in self.runs_dir.glob("*.run")}
        for name in sorted(set(manifest) | listed):
            path = self.runs_dir / name
            meta = manifest.get(name)
            ok = meta is not None and path.exists()
            if ok and meta is not None:
                data = path.read_bytes()
                ok = len(data) == int(str(meta["bytes"])) and zlib.crc32(data) == int(
                    str(meta["crc"])
                )
            if ok:
                continue
            bad.append((name, path.stat().st_size if path.exists() else 0))
            raw_windows = meta.get("windows") if meta is not None else None
            windows = raw_windows if isinstance(raw_windows, dict) else {}
            for symbol, (lo, hi) in windows.items():
                lo, hi = int(lo), int(hi)
                old = damaged.get(str(symbol))
                if old is not None:
                    lo, hi = min(lo, old[0]), max(hi, old[1])
                damaged[str(symbol)] = [lo, max(hi, lo + 1)]
        prep = ReplayPrep(pending=True)
        if bad:
            _write_atomic(self.runs_dir / _DAMAGED, orjson.dumps(damaged), self._fsync)
            for name, size in bad:
                path = self.runs_dir / name
                if path.exists():
                    self.corrupt_dir.mkdir(mode=0o700, exist_ok=True)
                    n = len(list(self.corrupt_dir.iterdir()))
                    os.replace(path, self.corrupt_dir / f"{n:06d}.run.wal")  # stays budgeted
                prep.corrupt_bytes += size
                manifest.pop(name, None)
            _write_atomic(self.runs_dir / _MANIFEST, orjson.dumps(manifest), self._fsync)
            self.commit(0)
        prep.corrupt_windows = {k: (v[0], v[1]) for k, v in damaged.items()}
        return prep

    def ack_damaged(self) -> None:
        """The writer has taken the damaged windows as gaps: clear the marker."""
        (self.runs_dir / _DAMAGED).unlink(missing_ok=True)

    def iter_replay(self) -> Generator[tuple[int, WalRecord]]:
        """K-way merge of the runs in `exch_ts` order (stable), from the checkpoint onwards.
        Yields `(merged_index, record)`; within one `exch_ts`, duplicate keys yield once.
        `consumed` counts merged frames, so `replay_complete()` can prove every frame of every
        run was read (a run that stops early never lets `runs/` be deleted)."""
        runs = sorted(self.runs_dir.glob("*.run"))
        start = self.checkpoint()
        self.consumed = 0
        with contextlib.ExitStack() as stack:
            streams = [
                (rec for rec, _ in read_frames(stack.enter_context(p.open("rb", buffering=65536))))
                for p in runs
            ]
            ts: int | None = None
            seen: set[tuple[str, str, int, int, int]] = set()
            for i, rec in enumerate(heapq.merge(*streams, key=lambda r: r.exch_ts)):
                self.consumed = i + 1
                if rec.exch_ts != ts:
                    ts, seen = rec.exch_ts, set()
                if rec.key in seen:
                    continue
                seen.add(rec.key)
                if i >= start:
                    yield i, rec

    def replay_complete(self) -> bool:
        """True iff the last `iter_replay` read exactly the manifest's frame total."""
        return self.consumed == self.total()

    def finish_replay(self) -> None:
        """Every run reached QuestDB: delete `runs/` and release its budget."""
        self._discard_runs()
