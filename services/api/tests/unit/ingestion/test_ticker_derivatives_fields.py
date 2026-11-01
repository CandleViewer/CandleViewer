"""The derivatives fields of the `ticker.{symbol}` item (E24-T04, 23 §14.8): open interest, its
value, funding rate, next funding time, mark and index price, and `stale`.

Recorded BTCUSDT ticker frames only (C-13.5). An absent source is left out of the item, never
`null` and never zero (§14.8); a decimal goes out as plain text, so `0.1` stays `0.1`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from candleviewer.exchange.base.models import TickerEvent
from candleviewer.ingestion.ticker_stream import ticker_event
from candleviewer.ingestion.ticker_topic import STALE_S, ticker_item
from tests import _tickers as t
from tests.contract.ws._harness import check_schema
from tests.unit.ingestion.test_ticker_topic import FIELDS, SCHEMA, Rig, Sub, _event

#: Wire member -> the recorded field it carries.
DERIVATIVES = {
    "open_interest": "openInterest",
    "open_interest_value": "openInterestValue",
    "funding_rate": "fundingRate",
    "mark_price": "markPrice",
    "index_price": "indexPrice",
}


def _without(*names: str) -> TickerEvent:
    fields = {k: v for k, v in FIELDS.items() if k not in names}
    return ticker_event("BTCUSDT", fields, ts_event_us=1_790_000_000_000_000, ts_ingest_us=0)


def _frame(rig: Rig, event: TickerEvent) -> dict[str, Any]:
    rig.reader.push(event)
    body = rig.topic().build(Sub("ticker.BTCUSDT"))
    assert body is not None
    check_schema(SCHEMA, body, "ticker frame")
    return body


def test_ticker_item_with_every_source_carries_the_recorded_text_and_validates() -> None:
    body = _frame(Rig(), _event(Rig().clock))
    (item,) = body["tickers"]
    for member, recorded in DERIVATIVES.items():
        assert item[member] == t.DATA[recorded]
    assert item["next_funding_time_ms"] == int(t.DATA["nextFundingTime"])
    assert item["stale"] is False


@pytest.mark.parametrize("member", sorted(DERIVATIVES))
def test_ticker_item_without_a_derivatives_source_omits_it_not_null_not_zero(member: str) -> None:
    rig = Rig()
    body = _frame(rig, _without(member))
    (item,) = body["tickers"]
    assert member not in item
    assert None not in item.values() and Decimal(0) not in (
        Decimal(v) for k, v in item.items() if k in DERIVATIVES and k != member
    )


def test_ticker_item_without_next_funding_time_omits_it() -> None:
    (item,) = _frame(Rig(), _without("next_funding_time"))["tickers"]
    assert "next_funding_time_ms" not in item


def test_ticker_item_stale_keeps_the_last_derivatives_values_and_validates() -> None:
    rig = Rig()
    rig.reader.push(_event(rig.clock))
    topic = rig.topic()
    fresh = topic.build(Sub("ticker.BTCUSDT"))
    rig.clock.t += STALE_S + 0.001
    stale = topic.build(Sub("ticker.BTCUSDT"))
    assert fresh is not None and stale is not None
    check_schema(SCHEMA, stale, "stale ticker frame")
    (a,), (b,) = fresh["tickers"], stale["tickers"]
    assert b["stale"] is True and a["stale"] is False
    assert {k: v for k, v in b.items() if k != "stale"} == {
        k: v for k, v in a.items() if k != "stale"
    }


@pytest.mark.parametrize(
    ("value", "text"),
    [("0.1", "0.1"), ("0.0000771", "0.0000771"), ("1E-7", "0.0000001"), ("57911.602", "57911.602")],
)
def test_ticker_item_decimal_round_trips_as_plain_text(value: str, text: str) -> None:
    fields = dict(FIELDS) | {"funding_rate": Decimal(value), "open_interest": Decimal(value)}
    event = ticker_event("BTCUSDT", fields, ts_event_us=1_790_000_000_000_000, ts_ingest_us=0)
    item = ticker_item(event, stale=False)
    assert item["funding_rate"] == item["open_interest"] == text
    assert Decimal(item["funding_rate"]) == Decimal(value)
