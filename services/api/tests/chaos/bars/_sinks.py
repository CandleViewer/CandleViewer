"""Capture sink for the bars chaos suite: every emission, in order, as a `BarSink` (E12-Q06)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from candleviewer.bars.emit import BarEmission
from candleviewer.bars.models import Bar


@dataclass(frozen=True, slots=True)
class Seen:
    """One emitted update: its kind, the amended flag and the bar as emitted."""

    kind: str
    amended: bool
    bar: Bar
    generation: int = 0


class CaptureSink:
    """What a client of the emit path would have received, per spec hash."""

    name = "chaos-capture"

    def __init__(self) -> None:
        self.updates: dict[str, list[Seen]] = {}
        self.emissions = 0

    async def emit(self, emission: BarEmission) -> None:
        self.emissions += 1
        seq = self.updates.setdefault(emission.spec.spec_hash, [])
        seq.extend(Seen(u.kind, u.amended, u.bar, emission.generation) for u in emission.updates)

    def final_bars(self, spec_hash: str) -> list[Bar]:
        """Latest emission per bar index, in index order (an amend overwrites, like the upsert)."""
        latest: dict[int, Bar] = {}
        for seen in self.updates.get(spec_hash, []):
            latest[seen.bar.index] = seen.bar
        return [latest[i] for i in sorted(latest)]

    def amended(self, spec_hash: str) -> list[Seen]:
        return [s for s in self.updates.get(spec_hash, []) if s.amended]


class FlakyRowSink:
    """The store seam of scenario 5: a `RowSink` over an in-memory table with outage windows.

    Rows are keyed like the tables' DEDUP key (`symbol`, `bar_param`, `generation`, `index`), so a
    replayed batch overwrites itself. A write inside an outage window (virtual seconds, `now()`)
    raises `ConnectionError`, which `BarWriter` classifies as transient."""

    def __init__(
        self, now: Callable[[], float], outages: Sequence[tuple[float, float]] = ()
    ) -> None:
        self._now = now
        self.outages = list(outages)
        self.rows: dict[tuple[str, str, str, int, int], dict[str, object]] = {}
        self.accepted_rows = 0  # rows the store acknowledged, rewrites included
        self.rejected_batches = 0

    def down(self) -> bool:
        t = self._now()
        return any(start <= t < end for start, end in self.outages)

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        if self.down():
            self.rejected_batches += 1
            raise ConnectionError("store unavailable")
        for row in rows:
            key = (table, str(row["symbol"]), str(row["bar_param"]), int(str(row["generation"])),
                   int(str(row["index"])))  # fmt: skip
            self.rows[key] = row
        self.accepted_rows += len(rows)

    def stored(self, table: str) -> list[dict[str, object]]:
        keyed = [(k[4], r) for k, r in self.rows.items() if k[0] == table]
        return [r for _, r in sorted(keyed, key=lambda kr: kr[0])]
