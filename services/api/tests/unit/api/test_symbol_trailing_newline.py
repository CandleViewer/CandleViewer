"""#3555: a symbol that ends in a newline is not a symbol. Python's `$` also matches before a final
newline, so `.match` took `"BTCUSDT\\n"`; the three inbox projections below now read it whole."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.alerts.ws_topic import delivery_item
from candleviewer.api import alert_deliveries, notifications

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_BAD = ["BTCUSDT\n", "BTCUSDT\r\n", "\nBTCUSDT", "BTC\nUSDT"]


def _notification(symbol: str) -> dict[str, Any]:
    row = SimpleNamespace(
        src=1, src_id=1, nkind="order", event="filled", severity=None, title="", body="",
        ts=_TS, read_at=None, symbol=symbol, code=None, account_id=None, source_uuid=None,
    )  # fmt: skip
    return notifications.dump(row)  # type: ignore[arg-type]  # a duck-typed row


def _delivery(symbol: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=1, alert_id="a", user_id=None, channel="in_app", status="sent", title="t", body="b",
        context={"symbol": symbol}, error_message=None, queued_at=_TS, acked_at=None,
        severity=None,
    )  # fmt: skip


_SITES = {
    "notifications": lambda s: _notification(s)["symbol"],
    "alert_deliveries": lambda s: alert_deliveries.dump(_delivery(s))["symbol"],  # type: ignore[arg-type]  # duck-typed
    "alerts_ws_topic": lambda s: delivery_item(_delivery(s))["symbol"],  # type: ignore[arg-type]  # duck-typed
}


@pytest.mark.parametrize("site", _SITES)
def test_symbol_projection_accepts_a_plain_symbol(site: str) -> None:
    assert _SITES[site]("BTCUSDT") == "BTCUSDT"


@pytest.mark.parametrize("site", _SITES)
@pytest.mark.parametrize("bad", _BAD)
def test_symbol_projection_refuses_a_newline(site: str, bad: str) -> None:
    assert _SITES[site](bad) is None
