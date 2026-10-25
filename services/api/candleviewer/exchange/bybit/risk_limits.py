"""Bybit v5 risk-limit tiers (`GET /v5/market/risk-limit`, `category=linear`; S-RL, #913).

All wire knowledge for the endpoint lives here (C-2.2): the params, the paging cursor and the
row fields (`id`, `riskLimitValue`, `maintenanceMargin`, `initialMargin`, `maxLeverage`), mapped
to the neutral `RiskLimitTier` (24 §14.4) with `Decimal` values. Public data only: the call goes
through `BybitRestClient.get_public` in the `MARKET_DATA` bucket, so it never draws on the
stop/cancel/SL reserve of the order or position buckets (C-12.7); a venue or transport failure
raises the client's taxonomy error, as for every other public read.

Fail closed per symbol, not per row: the tiers feed the liquidation estimate (a maintenance
margin rate), so one malformed or foreign row rejects the whole answer (`InstrumentParseError`)
rather than leaving a gap in the ladder. `tier_id` is the venue's risk id (`id`), and the tiers
are returned in ascending `risk_limit_value`, which must be strictly increasing. The venue's
`isLowestRisk` flag is a cross-check: at most one row may carry it, and that row must sort first.
`result.category` must be `linear`. `mmDeduction` is not mapped (it is empty on the first tier and
nothing reads it); a consumer that needs it is a contract change (24 §14.4).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any, Final, Protocol

from candleviewer.exchange.base.instruments import (
    InstrumentParseError,
    RiskLimitsFetcher,
)
from candleviewer.exchange.base.models import RiskLimitTier
from candleviewer.exchange.bybit.config import EndpointClass

PATH: Final = "/v5/market/risk-limit"
#: Bounded paging (C-2.18): one symbol's ladder is one page (35 rows recorded for BTCUSDT).
MAX_PAGES: Final = 5
_SYMBOL_RE: Final = re.compile(r"^[A-Z0-9]{2,24}USDT$")


class PublicGetter(Protocol):
    """`BybitRestClient.get_public`'s shape (the governed, credential-less read)."""

    async def get_public(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        endpoint_class: EndpointClass = EndpointClass.MARKET_DATA,
    ) -> dict[str, Any]: ...


def _decimal(row: Mapping[str, Any], key: str) -> Decimal:
    raw = row.get(key)
    if not isinstance(raw, str) or raw == "":
        raise InstrumentParseError(f"risk-limit field {key!r} missing or not a string")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise InstrumentParseError(f"risk-limit field {key!r} is not a decimal") from exc
    if not value.is_finite() or value <= 0:
        raise InstrumentParseError(f"risk-limit field {key!r} must be finite and > 0")
    return value


def _tier(row: object, symbol: str) -> RiskLimitTier:
    if not isinstance(row, Mapping):
        raise InstrumentParseError("risk-limit row is not an object")
    if row.get("symbol") != symbol:
        raise InstrumentParseError("risk-limit row symbol does not match the request")
    tier_id = row.get("id")
    if not isinstance(tier_id, int) or isinstance(tier_id, bool) or tier_id <= 0:
        raise InstrumentParseError("risk-limit row id is not a positive integer")
    mmr, imr = _decimal(row, "maintenanceMargin"), _decimal(row, "initialMargin")
    if mmr > 1 or imr > 1 or mmr > imr:
        raise InstrumentParseError("risk-limit margin rates out of range")
    return RiskLimitTier(
        tier_id=tier_id,
        risk_limit_value=_decimal(row, "riskLimitValue"),
        maintenance_margin_rate=mmr,
        initial_margin_rate=imr,
        max_leverage=_decimal(row, "maxLeverage"),
    )


def parse_risk_limit_page(payload: Mapping[str, Any], *, symbol: str) -> tuple[
    list[RiskLimitTier], str | None
]:  # fmt: skip
    """One page's tiers and its `nextPageCursor` (`None` when it is the last)."""
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise InstrumentParseError("risk-limit: missing result object")
    if result.get("category") != "linear":
        raise InstrumentParseError("risk-limit: result.category is not linear")
    rows = result.get("list")
    if not isinstance(rows, list):
        raise InstrumentParseError("risk-limit: result.list is not a list")
    cursor = result.get("nextPageCursor")
    return [_tier(row, symbol) for row in rows], (
        cursor if isinstance(cursor, str) and cursor else None
    )


def lowest_risk_ids(payload: Mapping[str, Any]) -> list[int]:
    """The ids of a parsed page's rows flagged `isLowestRisk == 1`, one per flagged row (call
    after the parse)."""
    result = payload.get("result")
    rows = result.get("list") if isinstance(result, Mapping) else None
    return [
        row["id"]
        for row in rows or ()
        if isinstance(row, Mapping) and row.get("isLowestRisk") == 1 and "id" in row
    ]


def order_tiers(
    tiers: Sequence[RiskLimitTier], *, lowest_risk_ids: Collection[int] = ()
) -> tuple[RiskLimitTier, ...]:
    """Ascending by `risk_limit_value`; a repeated value or no tier at all is refused, and so is
    a ladder where more than one tier is flagged lowest-risk or the flagged one is not first."""
    ordered = tuple(sorted(tiers, key=lambda t: t.risk_limit_value))
    if not ordered:
        raise InstrumentParseError("risk-limit: no tier for the symbol")
    if len(lowest_risk_ids) > 1 or (lowest_risk_ids and ordered[0].tier_id not in lowest_risk_ids):
        raise InstrumentParseError("risk-limit: isLowestRisk does not mark the first tier alone")
    for low, high in pairwise(ordered):
        if high.risk_limit_value <= low.risk_limit_value:
            raise InstrumentParseError("risk-limit: tier values are not strictly increasing")
    return ordered


async def fetch_risk_limits(client: PublicGetter, symbol: str) -> tuple[RiskLimitTier, ...]:
    """Every tier of `symbol`, following `nextPageCursor` for at most `MAX_PAGES` pages."""
    if not _SYMBOL_RE.fullmatch(symbol):
        raise InstrumentParseError("risk-limit: invalid symbol")
    tiers: list[RiskLimitTier] = []
    flagged: list[int] = []
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        params: dict[str, Any] = {"category": "linear", "symbol": symbol}
        if cursor is not None:
            params["cursor"] = cursor
        payload = await client.get_public(
            PATH, params=params, endpoint_class=EndpointClass.MARKET_DATA
        )
        page, cursor = parse_risk_limit_page(payload, symbol=symbol)
        tiers.extend(page)
        flagged += lowest_risk_ids(payload)
        if cursor is None:
            return order_tiers(tiers, lowest_risk_ids=flagged)
    raise InstrumentParseError(f"risk-limit exceeded {MAX_PAGES} pages; refusing unbounded paging")


def make_risk_limits_fetcher(client: PublicGetter) -> RiskLimitsFetcher:
    """The neutral `RiskLimitsFetcher` port over the governed public client (C-2.2)."""

    async def _fetch(symbol: str) -> Sequence[RiskLimitTier]:
        return await fetch_risk_limits(client, symbol)

    return _fetch


__all__ = [
    "MAX_PAGES",
    "PATH",
    "PublicGetter",
    "fetch_risk_limits",
    "lowest_risk_ids",
    "make_risk_limits_fetcher",
    "order_tiers",
    "parse_risk_limit_page",
]
