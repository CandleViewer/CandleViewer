"""Golden-file tests for the storage query shapes named in
`docs/qa/plans/E07-storage.md` section 6 (E07-Q01 DoD: "Golden fixtures
committed with rationale").

Golden files live under `packages/fixtures/golden/storage/` and are
regenerable only via a written PR rationale (`03-testing-strategy.md`
section 4.2) — this suite has no `--update-golden` flag itself; it simply
proves the checked-in golden files are trustworthy by replaying their
`input_rows` through `FakeMarketDataRepository` and comparing against
`expected_rows` exact-string (never float) for prices/sizes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from candleviewer.storage.models import TimeRange
from candleviewer.storage.repositories.rows import BarRow, TradeRow
from candleviewer.storage.testing import FakeMarketDataRepository

_REPO_ROOT = Path(__file__).resolve().parents[5]
_GOLDEN_DIR = _REPO_ROOT / "packages" / "fixtures" / "golden" / "storage"


def _load(case: str) -> dict[str, Any]:
    path = _GOLDEN_DIR / f"{case}.golden.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


async def test_trades_range_golden_file_round_trips() -> None:
    golden = _load("trades_range")
    query: dict[str, Any] = golden["query"]
    time_range: dict[str, Any] = query["range"]
    repo = FakeMarketDataRepository()
    await repo.write_trades([TradeRow(**row) for row in golden["input_rows"]])
    result = await repo.read_trades(
        query["symbol"],
        TimeRange(start_us=time_range["start_us"], end_us=time_range["end_us"]),
    )
    expected = [TradeRow(**row) for row in golden["expected_rows"]]
    assert result == expected


async def test_bars_range_golden_file_round_trips() -> None:
    golden = _load("bars_range")
    query: dict[str, Any] = golden["query"]
    time_range: dict[str, Any] = query["range"]
    repo = FakeMarketDataRepository()
    repo.seed_bars([BarRow(**row) for row in golden["input_rows"]])  # no bars writer: BR-05
    result = await repo.read_bars(
        query["symbol"],
        query["family"],
        query["param"],
        TimeRange(start_us=time_range["start_us"], end_us=time_range["end_us"]),
    )
    expected = [BarRow(**row) for row in golden["expected_rows"]]
    assert result == expected
