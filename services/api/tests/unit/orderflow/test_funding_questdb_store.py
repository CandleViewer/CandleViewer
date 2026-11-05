from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from candleviewer.domain.funding import PredictedFunding, PredictedFundingRefused, settle
from candleviewer.domain.sql_names import ts_param
from candleviewer.storage.models import TimeRange
from candleviewer.storage.questdb.funding_store import QuestDbFundingStore
from candleviewer.storage.questdb.ilp_writer import serialize_ilp_line
from candleviewer.storage.questdb.reader import build_funding_coverage, build_read_funding
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS, FUNDING_RATES_SCHEMA


class _Writer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, object]], str]] = []

    async def write_rows(self, table: str, rows: list[dict[str, object]], key: str) -> None:
        self.calls.append((table, rows, key))


class _Reader:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.sql: list[tuple[str, tuple[object, ...]]] = []

    async def run(self, builder: object) -> list[dict[str, object]]:
        self.sql.append((builder.sql, builder.params))  # type: ignore[attr-defined]
        return self.rows


async def test_write_settled_emits_precomputed_annualised_row() -> None:
    writer = _Writer()
    store = QuestDbFundingStore(writer, _Reader([]))  # type: ignore[arg-type]
    await store.write_settled([settle("BTCUSDT", 5, Decimal("0.0001"), 240)])
    await store.write_settled([])
    table, rows, key = writer.calls[0]
    assert (table, key, len(writer.calls)) == ("funding_rates", "ts", 1)
    assert rows[0]["interval_min"] == 240 and rows[0]["source"] == "history"
    assert rows[0]["annualised_pct"] == pytest.approx(0.0001 * (525600 / 240) * 100)


async def test_write_settled_refuses_predicted_without_touching_writer() -> None:
    writer = _Writer()
    store = QuestDbFundingStore(writer, _Reader([]))  # type: ignore[arg-type]
    with pytest.raises(PredictedFundingRefused):
        await store.write_settled([PredictedFunding(1, "BTCUSDT", Decimal(1))])  # type: ignore[list-item]
    assert not writer.calls


async def test_read_settled_binds_all_params_and_maps_rows() -> None:
    reader = _Reader(
        [
            {
                "ts": 9,
                "symbol": "BTCUSDT",
                "funding_rate": 0.0001,
                "annualised_pct": 21.9,
                "interval_min": 240,
                "source": "history",
            }
        ]
    )
    store = QuestDbFundingStore(_Writer(), reader)  # type: ignore[arg-type]
    out = await store.read_settled("BTCUSDT", TimeRange(start_us=1, end_us=2), 7)
    assert out[0].interval_min == 240 and out[0].funding_rate == Decimal("0.0001")
    sql, params = reader.sql[0]
    assert (
        sql.endswith("LIMIT 7")
        and "$4" not in sql
        and params == ("BTCUSDT", ts_param(1), ts_param(2))
    )
    with pytest.raises(ValueError):
        await store.read_settled("BTC;DROP", TimeRange(start_us=1, end_us=2), 7)


def test_schema_registered_with_dedup_ddl_and_symbol_tags() -> None:
    assert ALL_SCHEMAS["funding_rates"] is FUNDING_RATES_SCHEMA
    line = serialize_ilp_line(
        FUNDING_RATES_SCHEMA,
        {"symbol": "BTCUSDT", "source": "history", "funding_rate": 0.0001, "interval_min": 240},
        5,
    )
    assert line.startswith("funding_rates,symbol=BTCUSDT,source=history ")
    assert build_read_funding("BTCUSDT", TimeRange(start_us=1, end_us=2), 3).params == (
        "BTCUSDT",
        ts_param(1),
        ts_param(2),
    )


# -- E24-S03 (#778): the coverage read behind `getFundingHistory`'s `meta.coverage` ------------


def test_build_funding_coverage_is_one_bound_symbol_with_aliased_min_and_max() -> None:
    q = build_funding_coverage("BTCUSDT")
    assert q.sql == "SELECT min(ts) lo, max(ts) hi FROM funding_rates WHERE symbol = $1"
    assert q.params == ("BTCUSDT",)


async def test_coverage_converts_the_lo_and_hi_aliases_to_microseconds() -> None:
    first = datetime(2023, 11, 14, 0, 0, tzinfo=UTC)  # the recorded settlements' first and last
    last = datetime(2023, 11, 15, 0, 0, tzinfo=UTC)
    reader = _Reader([{"lo": first, "hi": last}])
    got = await QuestDbFundingStore(_Writer(), reader).coverage("BTCUSDT")  # type: ignore[arg-type]
    assert got == (1_699_920_000_000_000, 1_700_006_400_000_000)
    assert reader.sql == [(build_funding_coverage("BTCUSDT").sql, ("BTCUSDT",))]


@pytest.mark.parametrize(
    "rows",
    [[], [{"lo": None, "hi": None}], [{"lo": None, "hi": 5}], [{"lo": 5, "hi": None}]],
    ids=["no-row", "null-row", "null-lo", "null-hi"],
)
async def test_coverage_is_none_when_nothing_is_stored(rows: list[dict[str, object]]) -> None:
    store = QuestDbFundingStore(_Writer(), _Reader(rows))  # type: ignore[arg-type]
    assert await store.coverage("BTCUSDT") is None


async def test_coverage_refuses_a_non_identifier_symbol_before_querying() -> None:
    reader = _Reader([])
    with pytest.raises(ValueError):
        await QuestDbFundingStore(_Writer(), reader).coverage("BTC;DROP")  # type: ignore[arg-type]
    assert reader.sql == []
