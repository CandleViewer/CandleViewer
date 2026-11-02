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

from candleviewer.exchange.bybit.capabilities import capabilities_for
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.trading import CANCEL_ALL_FILTER, ENDPOINTS
from candleviewer.oms.order_link_resolution import HistoryRetentionPolicy
from tests.unit.exchange.bybit._trading import DAY_US, NOW_US


def test_there_is_a_live_and_a_demo_record_and_no_other() -> None:
    """The port and the service's factory rely on the refusal: testnet trades nothing (R6)."""
    assert [capabilities_for(env).environment for env in ("live", "demo")] == ["live", "demo"]
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


#: 24 §14.1's values, field by field, written out here (the OMS reads the record, never the
#: environment, 24 §14.2 rule 3): `order_rate_per_uid_per_s` holds §8.7's defaults.
SECTION_14_1: dict[str, Any] = {
    "exchange": "bybit",
    "supports_native_oco": False,
    "supports_native_iceberg": False,
    "supports_native_twap": False,
    "supports_native_chase": False,
    "supports_native_trailing": True,
    "supports_native_conditional": True,
    "supports_attached_sl_tp": True,
    "supports_batch_orders": True,
    "supports_reduce_only": True,
    "supports_reduce_only_tpsl": False,
    "supports_post_only": True,
    "supports_hedge_mode": True,
    "supports_dead_mans_switch": False,
    "max_batch_size": 10,
    "max_ws_topics_per_request": 10,
    "max_orders_per_symbol": 500,
    "max_conditional_orders_per_symbol": 10,
    "order_link_id_max_len": 36,
    "order_rate_per_uid_per_s": {
        "order.create": 10,
        "order.amend": 10,
        "order.cancel": 10,
        "order.cancel_all": 1,
        "position.read": 50,
        "account.read": 50,
        "market.read": 50,
    },
    "ip_rate_per_5s": 600,
    "book_depths": (1, 50, 200, 500),
    "book_cadence_ms": {1: 10, 50: 20, 200: 100, 500: 200},
    "position_modes": ("one_way", "hedge"),
    "trigger_sources": ("last", "mark", "index"),
    "trailing_stop_unit": "price_distance",
}
VENUES: dict[str, dict[str, Any]] = {
    "live": {
        "environment": "live",
        "supports_ws_order_entry": True,
        "order_retention_days": None,
        "has_public_ws": True,
    },
    "demo": {
        "environment": "demo",
        "supports_ws_order_entry": False,
        "order_retention_days": 7,
        "has_public_ws": False,
    },
}


@pytest.mark.parametrize("environment", sorted(VENUES))
def test_each_record_is_section_14_1_field_for_field(environment: str) -> None:
    assert capabilities_for(environment).model_dump() == SECTION_14_1 | VENUES[environment]


@pytest.mark.parametrize("environment", sorted(VENUES))
def test_neither_record_sets_a_take_profit_or_a_stop_loss_on_a_reduce_only_create(
    environment: str,
) -> None:
    """The venue's create-order rule, `reduceOnly` row: "When reduceOnly is true, take profit/stop
    loss cannot be set" (`bybit-exchange/docs@19518b90fb36e1527eaf99ff692076487a977921`,
    `docs/v5/order/create-order.mdx`). The OMS asks this field, never a constant of its own."""
    record = capabilities_for(environment)
    assert (record.supports_reduce_only, record.supports_reduce_only_tpsl) == (True, False)


def test_the_records_are_frozen() -> None:
    record: Any = capabilities_for("demo")  # untyped on purpose: the write below must fail
    with pytest.raises(ValidationError):
        record.supports_ws_order_entry = True


def test_a_write_to_one_callers_tables_reaches_no_other_caller() -> None:
    """The model is frozen but its rate and cadence tables are dicts: each caller gets its own
    copy, so one consumer's write never changes the record another consumer reads."""
    first = capabilities_for("demo")
    first.order_rate_per_uid_per_s["order.create"] = 1
    first.book_cadence_ms[1] = 999
    again = capabilities_for("demo")
    assert again.order_rate_per_uid_per_s["order.create"] == 10
    assert again.book_cadence_ms[1] == 10
    assert again.model_dump() == SECTION_14_1 | VENUES["demo"]


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
    exits = {n: (ENDPOINTS[n].endpoint_class, ENDPOINTS[n].lane) for n in ("cancel_all",
             "set_trading_stop")}  # fmt: skip
    assert exits == {
        "cancel_all": (EndpointClass.ORDER, "critical"),
        "set_trading_stop": (EndpointClass.POSITION, "critical"),
    }
    #: a cancel's lane is its request's, `critical` unless a rule's own cancel names `entry`
    #: (24 Sec.14.2 rule 12, Sec.8.4 item 3): `CancelOrderRequest`'s default keeps AC-31
    by_request = {
        n: ENDPOINTS[n] for n in ("place_order", "place_batch", "amend_order", "cancel_order")
    }
    assert all(
        e.endpoint_class is EndpointClass.ORDER and e.lane is None for e in by_request.values()
    )
    assert ENDPOINTS["set_leverage"].lane == "entry"
    assert CANCEL_ALL_FILTER == "Order"
