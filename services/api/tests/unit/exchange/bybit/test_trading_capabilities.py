"""The capability records and the closed endpoint table (G-8, #2877; 24 §14.1, rulings R6, R10;
C-2.8).

Two records, live and demo, built once from §14.1 and frozen; none for testnet. They describe the
venue: live offers WS order entry, demo does not, and v1 builds no trade socket (SR-040a). Demo
keeps orders 7 days, so the OMS's history rule expires an id after 6 (§8.3 rule 6). The port's
endpoints are a closed table with nothing under `/v5/asset/` and no `/v5/user/` call at all.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.exchange.bybit.capabilities import CAPABILITIES, capabilities_for
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.trading import CANCEL_ALL_FILTER, ENDPOINTS
from candleviewer.oms.order_link_resolution import HistoryRetentionPolicy
from tests.unit.exchange.bybit._trading import DAY_US, NOW_US


def test_there_is_a_live_and_a_demo_record_and_no_other() -> None:
    assert set(CAPABILITIES) == {"live", "demo"}
    for environment in ("testnet", "mainnet", ""):
        with pytest.raises(ValueError, match="no trading capability record"):
            capabilities_for(environment)


@pytest.mark.parametrize(
    ("environment", "ws", "retention", "public_ws"),
    [("live", True, None, True), ("demo", False, 7, False)],
)
def test_each_record_states_its_venue(
    environment: str, ws: bool, retention: int | None, public_ws: bool
) -> None:
    record = capabilities_for(environment)
    assert record.environment == environment and record.exchange == "bybit"
    assert (record.supports_ws_order_entry, record.order_retention_days) == (ws, retention)
    assert record.has_public_ws is public_ws
    assert (record.supports_dead_mans_switch, record.max_batch_size) == (False, 10)
    assert (record.order_link_id_max_len, record.ip_rate_per_5s) == (36, 600)
    assert record.order_rate_per_uid_per_s["order.cancel_all"] == 1
    assert record.order_rate_per_uid_per_s["order.create"] == 10
    assert record.trailing_stop_unit == "price_distance"


def test_the_records_are_frozen() -> None:
    record: Any = CAPABILITIES["demo"]  # untyped on purpose: the writes below must fail
    table: Any = CAPABILITIES
    with pytest.raises(ValidationError):
        record.supports_ws_order_entry = True
    with pytest.raises(TypeError):
        table["testnet"] = record


def test_demo_history_expires_an_id_after_six_days_and_live_never() -> None:
    demo = HistoryRetentionPolicy.from_capabilities(capabilities_for("demo"))
    live = HistoryRetentionPolicy.from_capabilities(capabilities_for("live"))
    created = NOW_US - 6 * DAY_US
    assert demo.unresolvable_by_history(created_at=created, now=NOW_US) is False
    assert demo.unresolvable_by_history(created_at=created - 1, now=NOW_US) is True
    assert live.unresolvable_by_history(created_at=created - 365 * DAY_US, now=NOW_US) is False


# -- the closed endpoint table (C-2.8, 24 §14.2 rule 12) ----------------------------------------


def test_the_endpoint_table_is_closed() -> None:
    assert {name: (e.method, e.path) for name, e in ENDPOINTS.items()} == {
        "place_order": ("POST", "/v5/order/create"),
        "place_batch": ("POST", "/v5/order/create-batch"),
        "amend_order": ("POST", "/v5/order/amend"),
        "cancel_order": ("POST", "/v5/order/cancel"),
        "cancel_all": ("POST", "/v5/order/cancel-all"),
        "set_trading_stop": ("POST", "/v5/position/trading-stop"),
        "set_leverage": ("POST", "/v5/position/set-leverage"),
        "open_orders": ("GET", "/v5/order/realtime"),
        "order_history": ("GET", "/v5/order/history"),
        "positions": ("GET", "/v5/position/list"),
        "executions": ("GET", "/v5/execution/list"),
        "closed_pnl": ("GET", "/v5/position/closed-pnl"),
        "wallet": ("GET", "/v5/account/wallet-balance"),
        "fee_rate": ("GET", "/v5/account/fee-rate"),
        "account_info": ("GET", "/v5/account/info"),
    }


def test_no_endpoint_moves_money_or_touches_a_key() -> None:
    """C-2.8: no withdrawal or transfer, and no key-permission change, through the port."""
    paths = [e.path for e in ENDPOINTS.values()]
    assert not [p for p in paths if p.startswith(("/v5/asset/", "/v5/user/"))]
    assert not [p for p in paths if any(w in p for w in ("withdraw", "transfer", "api"))]


def test_endpoint_classes_and_lanes_follow_rule_12() -> None:
    by_class = {(e.endpoint_class, e.lane) for e in ENDPOINTS.values() if e.method == "GET"}
    assert by_class == {(EndpointClass.ACCOUNT, "poll")}
    exits = {n: (ENDPOINTS[n].endpoint_class, ENDPOINTS[n].lane) for n in ("cancel_order",
             "cancel_all", "set_trading_stop")}  # fmt: skip
    assert exits == {
        "cancel_order": (EndpointClass.ORDER, "critical"),
        "cancel_all": (EndpointClass.ORDER, "critical"),
        "set_trading_stop": (EndpointClass.POSITION, "critical"),
    }
    by_request = {n: ENDPOINTS[n] for n in ("place_order", "place_batch", "amend_order")}
    assert all(
        e.endpoint_class is EndpointClass.ORDER and e.lane is None for e in by_request.values()
    )
    assert ENDPOINTS["set_leverage"].lane == "entry"
    assert CANCEL_ALL_FILTER == "Order"
