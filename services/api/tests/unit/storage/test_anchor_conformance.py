"""Both tiers choose the same seek anchor from the same snapshots (E26-T02, 24 Sec.13.7).

The cold reader reads them from a partition the production `ColdExporter` wrote. The hot reader
reads them through a PGWire double that answers its anchor query as QuestDB would: the rows of
the asked symbol and depth inside the two-sided bounds, newest first, at most the lookup's row
count. Same rows in, same anchor out, or both refuse a tie wider than one lookup reads.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

import pytest

from candleviewer.domain.sql_names import ts_param
from candleviewer.storage.cold.exporter import ColdExporter
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.recorded_reader import ParquetRecordedReader
from candleviewer.storage.errors import ColdReplayReadError, HotReplayReadError
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.questdb.recorded_reader import ANCHOR_ROWS, QuestDbRecordedReader
from candleviewer.storage.repositories.recorded import RecordedEvent
from tests.unit.storage.cold._replay_rows import H0, HOUR, SYMBOL, MemHotSource

MINUTE = 60_000_000
SNAPSHOTS = StreamKind.ORDERBOOK_SNAPSHOT
AT = H0 + 30 * MINUTE


def _snap(
    ts: int, epoch: int, update_id: int, *, depth: int = 200, bid: str = "65000.0"
) -> dict[str, object]:
    return {
        "ts": ts,
        "symbol": SYMBOL,
        "depth": depth,
        "epoch_id": epoch,
        "update_id": update_id,
        "cross_seq": None,
        "bids": f'[["{bid}","1.5"]]',
        "asks": '[["65000.5","2"]]',
    }


def _ts(row: Mapping[str, object]) -> datetime:
    ts = row["ts"]
    assert isinstance(ts, datetime)
    return ts


class _QuestDbAnswers:
    """`RecordFetcher` answering the anchor query as QuestDB does; `ts` comes back naive UTC."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows: list[Mapping[str, object]] = [
            row | {"ts": ts_param(int(str(row["ts"])))} for row in rows
        ]

    async def fetch_records(self, sql: str, *params: object) -> list[Mapping[str, object]]:
        symbol, depth, lo, hi = params
        assert isinstance(lo, datetime) and isinstance(hi, datetime)
        picked = [
            r
            for r in self._rows
            if r["symbol"] == symbol and r["depth"] == depth and lo <= _ts(r) <= hi
        ]
        picked.sort(key=_ts, reverse=True)
        return picked[:ANCHOR_ROWS]


async def _anchors(
    tmp_path: Path, rows: list[dict[str, object]], *, depth: int = 200
) -> tuple[RecordedEvent | type[Exception] | None, RecordedEvent | type[Exception] | None]:
    """(hot answer, cold answer): the anchor, `None`, or the error class each tier raised."""
    rows = sorted(rows, key=lambda r: int(str(r["ts"])))  # parts are written in time order
    registry = DatasetRegistry(tmp_path / "cold")
    registry.ensure_tree()
    exporter = ColdExporter(registry, MemHotSource({SNAPSHOTS: rows}))
    await exporter.export_partition(SYMBOL, SNAPSHOTS, TimeRange(start_us=H0, end_us=H0 + HOUR))
    readers = (QuestDbRecordedReader(_QuestDbAnswers(rows)), ParquetRecordedReader(registry))
    answers: list[RecordedEvent | type[Exception] | None] = []
    for reader in readers:
        try:
            answers.append(await reader.snapshot_at(SYMBOL, depth, AT, not_before_us=H0))
        except (HotReplayReadError, ColdReplayReadError) as exc:
            answers.append(type(exc))
    return answers[0], answers[1]


@pytest.mark.parametrize(
    ("rows", "want"),
    [
        ([_snap(H0 + m * MINUTE, 0, m) for m in range(20)], (H0 + 19 * MINUTE, (19, 200, 0))),
        ([_snap(H0 + MINUTE, e, u) for e, u in enumerate([3, 9, 5])], (H0 + MINUTE, (9, 200, 1))),
        (
            [_snap(H0 + MINUTE, 1, 7, bid="64999.0"), _snap(H0 + MINUTE, 0, 7)],
            (H0 + MINUTE, (7, 200, 1)),
        ),
        (
            [_snap(H0, 9, 999), *(_snap(H0 + MINUTE, e, 20 + e) for e in range(15))],
            (H0 + MINUTE, (34, 200, 14)),
        ),
        (
            [_snap(H0 + 2 * MINUTE, 0, 99), *(_snap(H0 + MINUTE, e, e) for e in range(15))],
            (H0 + 2 * MINUTE, (99, 200, 0)),
        ),
    ],
    ids=[
        "distinct-instants",
        "tie-by-update-id",
        "tie-by-epoch",
        "fifteen-tied-and-an-older",
        "one-newest-over-fifteen-tied",
    ],
)
async def test_both_tiers_choose_the_same_anchor(
    tmp_path: Path, rows: list[dict[str, object]], want: tuple[int, tuple[int, int, int]]
) -> None:
    hot, cold = await _anchors(tmp_path, rows)

    assert isinstance(hot, RecordedEvent) and hot == cold
    assert (hot.ts_us, hot.tiebreak) == want


async def test_both_tiers_refuse_a_tie_as_wide_as_the_lookup(tmp_path: Path) -> None:
    rows = [_snap(H0 + MINUTE, e, e) for e in range(ANCHOR_ROWS)]

    assert await _anchors(tmp_path, rows) == (HotReplayReadError, ColdReplayReadError)


async def test_both_tiers_find_no_anchor_outside_the_bounds_or_at_another_depth(
    tmp_path: Path,
) -> None:
    rows = [_snap(AT + MINUTE, 0, 1), _snap(H0 + MINUTE, 0, 2, depth=50)]

    assert await _anchors(tmp_path, rows) == (None, None)
