"""The exchange's capability records (`docs/plan/24-internal-schemas.md` §14.1; G-8, #2877).

Built once, at import, from §14.1's values: one record per environment the port trades, live
and demo, and none for testnet, which carries no trading (§14.3, ruling R6). They describe the
venue (`20-architecture.md` §9 rule 7): live offers WS order entry and demo does not, though v1
sends every order over REST (SR-040a). `order_rate_per_uid_per_s` holds §8.7's defaults; demo
keeps orders 7 days (§8.3 rule 6), live keeps them long (`None`). Consumers read the record,
never the environment (§14.2 rule 3).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from candleviewer.domain.primitives import Environment
from candleviewer.exchange.base.models import ExchangeCapabilities

__all__ = ["CAPABILITIES", "capabilities_for"]

#: §8.7's defaults per endpoint class; no default is given for `batch`, so none is set.
_ORDER_RATES: Final[Mapping[str, int]] = MappingProxyType(
    {
        "order.create": 10,
        "order.amend": 10,
        "order.cancel": 10,
        "order.cancel_all": 1,
        "position.read": 50,
        "account.read": 50,
        "market.read": 50,
    }
)


def _record(environment: Environment, *, demo: bool) -> ExchangeCapabilities:
    return ExchangeCapabilities(
        exchange="bybit",
        environment=environment,
        supports_ws_order_entry=not demo,
        supports_native_oco=False,
        supports_native_iceberg=False,
        supports_native_twap=False,
        supports_native_chase=False,
        supports_native_trailing=True,
        supports_native_conditional=True,
        supports_attached_sl_tp=True,
        supports_batch_orders=True,
        supports_reduce_only=True,
        supports_post_only=True,
        supports_hedge_mode=True,
        supports_dead_mans_switch=False,
        max_batch_size=10,
        max_ws_topics_per_request=10,
        max_orders_per_symbol=500,
        max_conditional_orders_per_symbol=10,
        order_link_id_max_len=36,
        order_rate_per_uid_per_s=dict(_ORDER_RATES),
        ip_rate_per_5s=600,
        book_depths=(1, 50, 200, 500),
        book_cadence_ms={1: 10, 50: 20, 200: 100, 500: 200},
        position_modes=("one_way", "hedge"),
        trigger_sources=("last", "mark", "index"),
        order_retention_days=7 if demo else None,
        has_public_ws=not demo,
    )


#: The records, frozen and built once (`ExchangeCapabilities` is a frozen model).
CAPABILITIES: Final[Mapping[str, ExchangeCapabilities]] = MappingProxyType(
    {"live": _record("live", demo=False), "demo": _record("demo", demo=True)}
)


def capabilities_for(environment: str) -> ExchangeCapabilities:
    """The record of `environment`; testnet, or anything else, is refused (ruling R6)."""
    record = CAPABILITIES.get(environment)
    if record is None:
        raise ValueError("no trading capability record for this environment")
    return record
