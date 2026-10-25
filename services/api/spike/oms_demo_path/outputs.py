"""The run's outputs, each scrubbed before a byte is written (#843 A4 brief item 7).

`events.jsonl` (one scrubbed line per event), `summary.json`, `metrics.prom` and the fixture
candidates in the corpus's layout (`fixtures/rest_<call>_<code>_<n>.json`, the reply body;
`fixtures/private_<topic>.jsonl.gz`, the scrubbed frames). Every write goes through `_emit`,
which scrubs, serialises and re-checks first (`Scrubber.dumps`); text the check refuses is never
written and is counted in `refused`. The directory is `0700` and every file `0600`. The fixture
candidates are reviewed before anything reaches `packages/fixtures`, in the findings PR.

Off the receive path (R1C-03): once `start`ed, an event, a frame or a fixture is queued as it
was handed over and a writer task this object owns scrubs and writes it, one item per turn of
the loop, so neither the private socket's `recv` nor a port call pays for a scrub. The queue is
bounded (`QUEUE_BOUND`, C-2.18): an item past it is dropped and counted (`dropped`), never
waited for. Items are written in the order they were handed over, so the scrubber learns each
identifier in the same order as before; `flush` waits for the queue to empty and `stop` ends the
writer, after which every write is synchronous again (the summary and the metrics). An item that
fails, whatever the error, is counted (`write_errors`) and the writer goes on (R2-07), so `flush`
and `stop` never wait forever. Unstarted, every write is synchronous. The intent ledger
(`ledger.py`, `intents.jsonl`) is never queued: its row is scrubbed by the same scrubber, then
written and fsynced before its create is sent.
"""

from __future__ import annotations

import asyncio
import gzip
import os
import re
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final

from candleviewer.observability.context import spawn
from spike.oms_demo_path.scrub import LeakDetected, Scrubber

#: A write: `(path, bytes, append)`; the default makes each file `0600` and follows no symlink.
Writer = Callable[[Path, bytes, bool], None]
#: Frames kept per topic as fixture candidates (C-2.18: a bound, the rest only counted).
FRAMES_PER_TOPIC: Final = 2000
#: Items the writer's queue holds (C-2.18): past it an item is dropped and counted.
QUEUE_BOUND: Final = 10_000
_SAFE_NAME: Final = re.compile(r"[a-z0-9_]+")

type _Work = tuple[Callable[..., object], tuple[object, ...]]


def write_file(path: Path, data: bytes, append: bool) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_APPEND if append else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
    finally:
        os.close(fd)


class RunOutputs:
    """One run's output directory (see the module docstring)."""

    def __init__(
        self,
        directory: Path,
        scrubber: Scrubber,
        *,
        write: Writer = write_file,
        monotonic: Callable[[], float] = time.monotonic,
        queue_bound: int = QUEUE_BOUND,
    ) -> None:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        (directory / "fixtures").mkdir(mode=0o700, exist_ok=True)
        self.directory = directory
        self._scrubber = scrubber
        self._write = write
        self._monotonic = monotonic
        self._started = monotonic()
        self._frames: defaultdict[str, list[str]] = defaultdict(list)
        self._bound = queue_bound
        self._queue: asyncio.Queue[_Work] | None = None
        self._writer: asyncio.Task[None] | None = None
        self.frames_seen: defaultdict[str, int] = defaultdict(int)
        self.refused = 0
        self.events = 0
        self.dropped = 0
        self.write_errors = 0

    # -- the writer, off the receive path ------------------------------------------------------

    def start(self) -> None:
        """Queue every event, frame and fixture for the writer task (in a running loop)."""
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self._bound)
            self._writer = spawn(self._drain(self._queue), name="spike-outputs-writer")

    @property
    def deferred(self) -> bool:
        return self._queue is not None

    def elapsed(self) -> float:
        """Seconds since the run began, to the ms: every line's `t` (the intent ledger's too)."""
        return round(self._monotonic() - self._started, 3)

    def later(self, work: Callable[..., object], *args: object) -> bool:
        """`work(*args)` on the writer task, or now when the writer is not started; `False`
        when the queue is full (the item is dropped and counted)."""
        queue = self._queue
        if queue is None:
            work(*args)
            return True
        try:
            queue.put_nowait((work, args))
        except asyncio.QueueFull:
            self.dropped += 1
            return False
        return True

    async def _drain(self, queue: asyncio.Queue[_Work]) -> None:
        while True:
            work, args = await queue.get()
            try:
                work(*args)
            except Exception:  # a file it cannot write, or any other failure: counted, goes on
                self.write_errors += 1
            finally:
                queue.task_done()
            await asyncio.sleep(0)  # one item per turn: the receive path goes first

    async def flush(self) -> None:
        """Until every queued item is written (or refused)."""
        if self._queue is not None:
            await self._queue.join()

    async def stop(self) -> None:
        """Flush, then end the writer: every write is synchronous again."""
        if self._queue is None:
            return
        await self._queue.join()
        writer, self._writer, self._queue = self._writer, None, None
        if writer is not None:
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)

    # -- the writes ----------------------------------------------------------------------------

    def _emit(self, path: Path, value: object, *, append: bool, transient: Sequence[str]) -> bool:
        try:
            text = self._scrubber.dumps(value, transient)
        except LeakDetected:
            self.refused += 1
            return False
        self._write(path, (text + "\n").encode() if append else text.encode(), append)
        return True

    def event(
        self,
        kind: str,
        fields: Mapping[str, object] | None = None,
        /,
        *,
        transient: Sequence[str] = (),
        **more: object,
    ) -> bool:
        """One line of `events.jsonl`: `t` (seconds since the run began), `kind`, the fields;
        queued once the writer is started (`True` then means queued)."""
        line = {"t": self.elapsed(), "kind": kind}
        line |= {**(fields or {}), **more}
        if self._queue is None:
            return self.write_event(line, tuple(transient))
        return self.later(self.write_event, line, tuple(transient))

    def write_event(self, line: Mapping[str, object], transient: Sequence[str] = ()) -> bool:
        written = self._emit(
            self.directory / "events.jsonl", line, append=True, transient=transient
        )
        self.events += written
        return written

    def rest_fixture(self, name: str, body: object, *, transient: Sequence[str] = ()) -> None:
        """A REST reply body as a corpus file would hold it, scrubbed."""
        if _SAFE_NAME.fullmatch(name) is None:
            raise ValueError("a fixture name is lower-case letters, digits and underscores")
        path = self.directory / "fixtures" / f"rest_{name}.json"
        self.later(self._emit_fixture, path, body, tuple(transient))

    def _emit_fixture(self, path: Path, body: object, transient: Sequence[str]) -> None:
        self._emit(path, body, append=False, transient=transient)

    def frame(self, topic: str, frame: str) -> None:
        """A private-stream frame, counted now; scrubbed and kept for
        `private_<topic>.jsonl.gz` by the writer (`keep_frame`)."""
        self.frames_seen[topic] += 1
        self.later(self.keep_frame, topic, frame)

    def tee(self, topic: str, frame: str) -> None:
        """A frame counted, scrubbed and kept now: the writer's own call (`recorder.py`)."""
        self.frames_seen[topic] += 1
        self.keep_frame(topic, frame)

    def keep_frame(self, topic: str, frame: str) -> None:
        held = len(self._frames.get(topic, ()))
        if _SAFE_NAME.fullmatch(topic) is None or held >= FRAMES_PER_TOPIC:
            return
        scrubbed = self._scrubber.frame(frame)
        if scrubbed is None:
            return
        try:
            self._frames[topic].append(self._scrubber.dumps(scrubbed))
        except LeakDetected:
            self.refused += 1

    def write_summary(self, summary: Mapping[str, object]) -> None:
        self._emit(self.directory / "summary.json", summary, append=False, transient=())

    def write_metrics(self, text: str) -> None:
        """The Prometheus exposition: label values are bounded by construction; still cleaned of
        every registered value and checked."""
        cleaned = str(self._scrubber.scrub(text))
        try:
            self._scrubber.check(cleaned)
        except LeakDetected:
            self.refused += 1
            return
        self._write(self.directory / "metrics.prom", cleaned.encode(), False)

    def close(self) -> None:
        """The frame fixtures, each re-checked as a whole before it is compressed and written."""
        for topic, lines in sorted(self._frames.items()):
            text = "\n".join(lines) + "\n"
            try:
                self._scrubber.check(text)
            except LeakDetected:
                self.refused += 1
                continue
            path = self.directory / "fixtures" / f"private_{topic}.jsonl.gz"
            self._write(path, gzip.compress(text.encode(), mtime=0), False)
        self._frames.clear()
