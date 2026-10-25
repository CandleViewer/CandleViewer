"""The run's outputs, each scrubbed before a byte is written (#843 A4 brief item 7).

`events.jsonl` (one scrubbed line per event), `summary.json`, `metrics.prom` and the fixture
candidates in the corpus's layout (`fixtures/rest_<call>_<code>_<n>.json`, the reply body;
`fixtures/private_<topic>.jsonl.gz`, the scrubbed frames). Every write goes through `_emit`,
which scrubs, serialises and re-checks first (`Scrubber.dumps`); text the check refuses is never
written and is counted in `refused`. The directory is `0700` and every file `0600`. The fixture
candidates are reviewed before anything reaches `packages/fixtures`, in the findings PR.
"""

from __future__ import annotations

import gzip
import os
import re
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final

from spike.oms_demo_path.scrub import LeakDetected, Scrubber

#: A write: `(path, bytes, append)`; the default makes each file `0600` and follows no symlink.
Writer = Callable[[Path, bytes, bool], None]
#: Frames kept per topic as fixture candidates (C-2.18: a bound, the rest only counted).
FRAMES_PER_TOPIC: Final = 2000
_SAFE_NAME: Final = re.compile(r"[a-z0-9_]+")


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
        self.frames_seen: defaultdict[str, int] = defaultdict(int)
        self.refused = 0
        self.events = 0

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
        """One line of `events.jsonl`: `t` (seconds since the run began), `kind`, the fields."""
        line = {"t": round(self._monotonic() - self._started, 3), "kind": kind}
        line |= {**(fields or {}), **more}
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
        self._emit(path, body, append=False, transient=transient)

    def frame(self, topic: str, frame: str) -> None:
        """A private-stream frame, scrubbed now and kept for `private_<topic>.jsonl.gz`."""
        self.frames_seen[topic] += 1
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
