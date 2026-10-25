"""S-RL-a (#913): the recorded `GET /v5/market/risk-limit` replies keep the envelope the adapter
(S-RL-b) parses: a linear, single-page answer of strictly increasing tiers with one lowest-risk
row. Recorded fixtures only, no network (C-13.5).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests._corpus import rest

#: The recorded replies, one per symbol (named in full for the feed-rot meta-check).
FIXTURES = {"BTCUSDT": "rest/risk_limit_BTCUSDT.json", "ETHUSDT": "rest/risk_limit_ETHUSDT.json"}
ROW_KEYS = {
    "id",
    "symbol",
    "riskLimitValue",
    "maintenanceMargin",
    "initialMargin",
    "isLowestRisk",
    "maxLeverage",
    "mmDeduction",
}


@pytest.mark.parametrize("symbol", sorted(FIXTURES))
def test_recorded_risk_limit_reply_keeps_the_parsed_envelope(symbol: str) -> None:
    reply = rest(FIXTURES[symbol])
    assert reply["retCode"] == 0
    result = reply["result"]
    assert result["category"] == "linear"
    assert result.get("nextPageCursor", "") == ""
    rows = result["list"]
    assert len(rows) == 35
    assert all(set(row) == ROW_KEYS and row["symbol"] == symbol for row in rows)
    values = [Decimal(row["riskLimitValue"]) for row in rows]
    assert values == sorted(values) and len(set(values)) == len(values)
    assert [row["isLowestRisk"] for row in rows].count(1) == 1
    assert rows[0]["isLowestRisk"] == 1
