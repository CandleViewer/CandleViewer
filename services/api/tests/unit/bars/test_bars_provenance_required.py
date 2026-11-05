"""BR-05 / SR-E12-11: a `bars_*` row without provenance is withheld as missing, at any time.

`BarWriter` is the one writer of `bars_*` rows and stamps `source` and `row_checksum` on every
row. A row lacking either has no writer that could have produced it, so the reader withholds it
and counts it `reason=missing`, whatever its open time: there is no legacy exception (QuestDB
migration 0004 recreated every bars table before any production data, so the legacy window
is empty in practice).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarReader, _integrity_failure, bars_checksum_mismatch_total
from candleviewer.bars.rows import bar_row

#: The old legacy cut-over (#5634): rows opening before it were once trusted without provenance.
OLD_CUTOVER_US = int(datetime(2026, 10, 7, tzinfo=UTC).timestamp()) * 10**6

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


def _counters() -> tuple[float, ...]:
    m = bars_checksum_mismatch_total
    return tuple(m.labels("bars_time", r)._value.get() for r in ("missing", "mismatch"))


@pytest.mark.parametrize("open_us", [0, 1_700_000_000_000_000, OLD_CUTOVER_US - STEP])
def test_a_row_without_provenance_before_the_old_cutover_is_missing(open_us: int) -> None:
    assert _integrity_failure(_unprovenanced(open_us)) == "missing"


@pytest.mark.parametrize("offset", [0, STEP, 10**12])
def test_a_row_without_provenance_from_the_old_cutover_on_is_missing(offset: int) -> None:
    assert _integrity_failure(_unprovenanced(OLD_CUTOVER_US + offset)) == "missing"


@pytest.mark.parametrize("column", ["source", "row_checksum"])
def test_a_row_missing_either_provenance_column_is_missing(column: str) -> None:
    assert _integrity_failure({**_row(OLD_CUTOVER_US - STEP), column: None}) == "missing"


def test_a_driver_datetime_ts_without_provenance_is_missing() -> None:
    """pgwire hands `ts` back as a `datetime`; the open time plays no part in the rule."""
    for ts in (datetime(2026, 10, 6, 23, 55, tzinfo=UTC), datetime(2026, 10, 7, tzinfo=UTC)):
        assert _integrity_failure({**_unprovenanced(0), "ts": ts}) == "missing"


def test_a_row_without_provenance_and_without_ts_is_missing() -> None:
    row = _unprovenanced(OLD_CUTOVER_US - STEP)
    del row["ts"]
    assert _integrity_failure(row) == "missing"


@pytest.mark.parametrize("open_us", [OLD_CUTOVER_US - STEP, OLD_CUTOVER_US + STEP])
def test_a_stamped_row_verifies_at_any_time(open_us: int) -> None:
    assert _integrity_failure(_row(open_us)) is None


def test_the_metric_reason_set_is_unchanged() -> None:
    """Withholding counts under the existing `missing` reason; no new reason value appears."""
    rows = [
        _unprovenanced(0), _unprovenanced(OLD_CUTOVER_US + STEP), _row(0),
        {**_row(0), "close": 1.0}, {**_row(0), "source": None},
    ]  # fmt: skip
    assert {_integrity_failure(r) for r in rows} == {"missing", "mismatch", None}


async def test_read_bars_emits_only_the_existing_reason_label_values() -> None:
    def _by_reason() -> dict[str, float]:
        return {
            s.labels["reason"]: s.value
            for f in bars_checksum_mismatch_total.collect()
            for s in f.samples
            if s.name.endswith("_total") and s.labels["table"] == "bars_time"
        }

    before = _by_reason()
    rows = [_unprovenanced(0), {**_row(STEP, index=1), "close": 1.0}, _row(2 * STEP, index=2)]
    await BarReader(_Conn(rows), _no_rebuild).read_bars("BTCUSDT", SPEC, 0, 2**55, 10)
    after = _by_reason()
    assert {r for r, v in after.items() if v > before.get(r, 0.0)} == {"missing", "mismatch"}
    assert set(after) <= {"missing", "mismatch"}


async def test_read_bars_withholds_and_counts_every_row_without_provenance() -> None:
    old = _unprovenanced(OLD_CUTOVER_US - STEP)
    good = _row(OLD_CUTOVER_US, index=1)
    new = _unprovenanced(OLD_CUTOVER_US + STEP, index=2)
    before = _counters()
    page = await BarReader(_Conn([old, good, new]), _no_rebuild).read_bars(
        "BTCUSDT", SPEC, 0, 2**55, 10
    )
    assert page.rows == [good]
    assert page.integrity_degraded and page.dropped == 2
    assert _counters() == (before[0] + 2, before[1])
