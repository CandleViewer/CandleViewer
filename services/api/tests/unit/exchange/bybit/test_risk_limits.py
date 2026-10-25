"""S-RL (#913): the risk-limit parser's refusals and its bounded paging (no network)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from candleviewer.exchange.base.instruments import InstrumentParseError
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.risk_limits import (
    MAX_PAGES,
    fetch_risk_limits,
    make_risk_limits_fetcher,
    order_tiers,
    parse_risk_limit_page,
)
from tests._corpus import rest

SYMBOL = "BTCUSDT"


def _row(**over: Any) -> dict[str, Any]:
    base = next(iter(rest("rest/risk_limit_BTCUSDT.json")["result"]["list"]))
    return {**base, **over}


def _page(rows: list[Any], cursor: str = "") -> dict[str, Any]:
    return {
        "retCode": 0,
        "result": {"category": "linear", "list": rows, "nextPageCursor": cursor},
    }


class _Pages:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = list(pages)
        self.cursors: list[Any] = []

    async def get_public(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        endpoint_class: EndpointClass = EndpointClass.MARKET_DATA,
    ) -> dict[str, Any]:
        self.cursors.append((params or {}).get("cursor"))
        return self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]


@pytest.mark.parametrize(
    "row",
    [
        "not an object",
        _row(symbol="ETHUSDT"),
        _row(id="1"),
        _row(id=True),
        _row(id=0),
        _row(maintenanceMargin=""),
        _row(maintenanceMargin=0.0033),
        _row(initialMargin="abc"),
        _row(riskLimitValue="NaN"),
        _row(maxLeverage="-1"),
        _row(maintenanceMargin="0.5", initialMargin="0.1"),
        _row(initialMargin="1.5"),
    ],
)
def test_parse_risk_limit_page_malformed_row_rejects_the_whole_answer(row: Any) -> None:
    with pytest.raises(InstrumentParseError):
        parse_risk_limit_page(_page([row]), symbol=SYMBOL)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"result": []},
        {"result": {"category": "linear", "list": {}}},
        {"result": {"category": "inverse", "list": []}},
        {"result": {"list": []}},
    ],
    ids=["none", "list", "dict", "inverse", "no-category"],
)
def test_parse_risk_limit_page_bad_envelope_raises(payload: dict[str, Any]) -> None:
    with pytest.raises(InstrumentParseError):
        parse_risk_limit_page(payload, symbol=SYMBOL)


def test_order_tiers_refuses_an_empty_or_repeated_ladder() -> None:
    tier, _ = parse_risk_limit_page(_page([_row()]), symbol=SYMBOL)
    with pytest.raises(InstrumentParseError, match="no tier"):
        order_tiers([])
    with pytest.raises(InstrumentParseError, match="strictly"):
        order_tiers([tier[0], tier[0]])


@pytest.mark.parametrize(
    "rows",
    [
        [_row(), _row(id=2, riskLimitValue="600000", isLowestRisk=1)],  # two flagged
        [_row(isLowestRisk=0), _row(id=2, riskLimitValue="600000", isLowestRisk=1)],  # not first
    ],
    ids=["two-flagged", "flag-not-first"],
)
async def test_fetch_risk_limits_refuses_a_misplaced_lowest_risk_flag(
    rows: list[dict[str, Any]],
) -> None:
    with pytest.raises(InstrumentParseError, match="isLowestRisk"):
        await fetch_risk_limits(_Pages([_page(rows)]), SYMBOL)


async def test_fetch_risk_limits_accepts_a_ladder_with_no_flag() -> None:
    unflagged = _Pages([_page([_row(isLowestRisk=0)])])  # nothing to cross-check
    assert [t.tier_id for t in await fetch_risk_limits(unflagged, SYMBOL)] == [1]


async def test_fetch_risk_limits_follows_the_cursor_then_orders_the_tiers() -> None:
    client = _Pages(  # the one `isLowestRisk` row is on the second page and sorts first
        [_page([_row(id=2, riskLimitValue="600000", isLowestRisk=0)], "c1"), _page([_row()])]
    )
    tiers = await fetch_risk_limits(client, SYMBOL)
    assert [t.tier_id for t in tiers] == [1, 2] and client.cursors == [None, "c1"]


async def test_fetch_risk_limits_refuses_unbounded_paging_and_a_bad_symbol() -> None:
    client = _Pages([_page([_row()], "again")])
    with pytest.raises(InstrumentParseError, match="pages"):
        await fetch_risk_limits(client, SYMBOL)
    assert len(client.cursors) == MAX_PAGES
    with pytest.raises(InstrumentParseError, match="symbol"):
        await fetch_risk_limits(client, "btc/usdt")


async def test_risk_limits_fetcher_wraps_the_client() -> None:
    fetch = make_risk_limits_fetcher(_Pages([_page([_row()])]))
    assert [t.tier_id for t in await fetch(SYMBOL)] == [1]
