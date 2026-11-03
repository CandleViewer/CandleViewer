"""BR-05 / SR-E12-11: a `bars_*` row without provenance is trusted only before the cutover.

`source` and `row_checksum` were added by QuestDB migration 0003, together with the bar writer
that stamps both on every row it writes. A row carrying neither is therefore trusted as legacy
only when it opens before `PROVENANCE_CUTOVER_US`; from the cutover on, such a row has no
writer that could have produced it, so it is withheld and counted like a missing checksum.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarReader, _integrity_failure, bars_checksum_mismatch_total
from candleviewer.bars.rows import PROVENANCE_CUTOVER_US, bar_row

SPEC = BarSpec(kind="time", interval_ms=300_000)
STEP = 300_000_000  # one 5-minute bar, µs


def _row(open_us: int, index: int = 0) -> dict[str, object]:
    bar = Bar.model_validate(
        dict(
            spec_hash=SPEC.spec_hash, symbol="BTCUSDT", index=index, open_time=open_us,
            close_time=open_us + STEP - 1, open=Decimal("100.1"), high=Decimal("101"),
            low=Decimal("99.5"), close=Decimal("100.5"), volume=Decimal("10"),
            buy_volume=Decimal("6"), sell_volume=Decimal("4"), delta=Decimal("2"),
            min_delta=Decimal("-1"), max_delta=Decimal("3"), trade_count=7,
            turnover=Decimal("1001"), vwap=Decimal("100.3"), closed=True, partial=False,
            gap_before=False,
        )
    )  # fmt: skip
    return bar_row(bar, SPEC, generation=0)


def _unprovenanced(open_us: int, index: int = 0) -> dict[str, object]:
    """A row as a writer that stamps no provenance would leave it."""
    return {**_row(open_us, index), "source": None, "row_checksum": None}


class _Conn:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        return self.rows


async def _no_rebuild(sym: str, h: str, lo: int, hi: int) -> None:
    return None


def _missing() -> float:
    value: float = bars_checksum_mismatch_total.labels("bars_time", "missing")._value.get()
    return value


def test_the_cutover_is_the_day_migration_0003_landed() -> None:
    """2026-10-07T00:00:00Z: the day QuestDB migration 0003 and the stamping writer merged."""
    assert PROVENANCE_CUTOVER_US == int(datetime(2026, 10, 7, tzinfo=UTC).timestamp()) * 10**6


def test_a_row_without_provenance_before_the_cutover_is_trusted_as_legacy() -> None:
    assert _integrity_failure(_unprovenanced(PROVENANCE_CUTOVER_US - STEP)) is None


@pytest.mark.parametrize("offset", [0, STEP, 10**12])
def test_a_row_without_provenance_from_the_cutover_on_is_missing(offset: int) -> None:
    assert _integrity_failure(_unprovenanced(PROVENANCE_CUTOVER_US + offset)) == "missing"


def test_the_cutover_applies_to_a_driver_datetime_ts() -> None:
    """pgwire hands `ts` back as a `datetime`; the rule reads it the same way."""
    before = datetime(2026, 10, 6, 23, 55, tzinfo=UTC)
    after = datetime(2026, 10, 7, 0, 0, tzinfo=UTC)
    assert _integrity_failure({**_unprovenanced(0), "ts": before}) is None
    assert _integrity_failure({**_unprovenanced(0), "ts": after}) == "missing"


def test_a_row_without_provenance_and_without_ts_is_missing() -> None:
    row = _unprovenanced(PROVENANCE_CUTOVER_US - STEP)
    del row["ts"]
    assert _integrity_failure(row) == "missing"


def test_a_stamped_row_after_the_cutover_still_verifies() -> None:
    assert _integrity_failure(_row(PROVENANCE_CUTOVER_US + STEP)) is None


async def test_read_bars_withholds_and_counts_a_post_cutover_row_without_provenance() -> None:
    legacy = _unprovenanced(PROVENANCE_CUTOVER_US - STEP)
    good = _row(PROVENANCE_CUTOVER_US, index=1)
    forged = _unprovenanced(PROVENANCE_CUTOVER_US + STEP, index=2)
    before = _missing()
    page = await BarReader(_Conn([legacy, good, forged]), _no_rebuild).read_bars(
        "BTCUSDT", SPEC, 0, 2**55, 10
    )
    assert page.rows == [legacy, good]
    assert page.integrity_degraded and page.dropped == 1
    assert _missing() == before + 1
