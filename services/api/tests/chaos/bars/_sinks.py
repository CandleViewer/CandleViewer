"""Capture sink for the bars chaos suite: every emission, in order, as a `BarSink` (E12-Q06)."""

from __future__ import annotations

from dataclasses import dataclass

from candleviewer.bars.emit import BarEmission
from candleviewer.bars.models import Bar


@dataclass(frozen=True, slots=True)
class Seen:
    """One emitted update: its kind, the amended flag and the bar as emitted."""

    kind: str
    amended: bool
    bar: Bar


class CaptureSink:
    """What a client of the emit path would have received, per spec hash."""

    name = "chaos-capture"

    def __init__(self) -> None:
        self.updates: dict[str, list[Seen]] = {}
        self.emissions = 0

    async def emit(self, emission: BarEmission) -> None:
        self.emissions += 1
        seq = self.updates.setdefault(emission.spec.spec_hash, [])
        seq.extend(Seen(u.kind, u.amended, u.bar) for u in emission.updates)

    def final_bars(self, spec_hash: str) -> list[Bar]:
        """Latest emission per bar index, in index order (an amend overwrites, like the upsert)."""
        latest: dict[int, Bar] = {}
        for seen in self.updates.get(spec_hash, []):
            latest[seen.bar.index] = seen.bar
        return [latest[i] for i in sorted(latest)]

    def amended(self, spec_hash: str) -> list[Seen]:
        return [s for s in self.updates.get(spec_hash, []) if s.amended]
