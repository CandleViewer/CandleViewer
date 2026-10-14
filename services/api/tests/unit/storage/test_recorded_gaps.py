"""`SqlAlchemyRecorderRepository.recording_gaps` (E26-T02): gap rows as `RecordedGap`s."""

from __future__ import annotations

from datetime import UTC, datetime

from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedGap, RecordingGapReader
from tests.unit.storage.test_recorder_repository_unit import _repo

H0 = 1_790_812_800_000_000  # 2026-10-01 00:00 UTC


async def test_gap_rows_become_recorded_gaps_queried_over_the_window() -> None:
    row = {
        "id": 1,
        "stream": "funding",  # the Postgres `stream_kind` spelling
        "gap_start": datetime(2026, 10, 1, 0, 0, 5, tzinfo=UTC),
        "gap_end": datetime(2026, 10, 1, 0, 0, 9, tzinfo=UTC),
        "cause": "ws_disconnect",
        "backfilled": False,
        "backfill_source": None,
    }
    repo, rel = _repo([row])

    got = await repo.recording_gaps("BTCUSDT", TimeRange(start_us=H0, end_us=H0 + 10_000_000))

    assert isinstance(repo, RecordingGapReader)
    assert got == [
        RecordedGap(
            "BTCUSDT", StreamKind.FUNDING_RATES, H0 + 5_000_000, H0 + 9_000_000, "ws_disconnect"
        )
    ]
    assert rel.calls[-1][1] == {
        "symbol": "BTCUSDT",
        "lo": datetime(2026, 10, 1, tzinfo=UTC),
        "hi": datetime(2026, 10, 1, 0, 0, 10, tzinfo=UTC),
    }
