"""Bybit `instruments-info` (`category=linear`) parsing (C-2.2: all Bybit
vocabulary — `tickSize`, `qtyStep`, `lotSizeFilter`, ... — lives only here).

`candleviewer.ingestion.instruments` consumes the neutral `Instrument` model
this module returns; it never sees a raw Bybit field name.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol

from pydantic import ValidationError

from candleviewer.domain.events import Instrument
from candleviewer.exchange.base.instruments import (
    InstrumentParseError,
    InstrumentsFetcher,
    InstrumentsFetchResult,
    RejectedInstrument,
)

__all__ = [
    "InstrumentParseError",
    "make_instruments_info_fetcher",
    "parse_instrument",
    "parse_instruments",
]

_STATUS_MAP: dict[str, Literal["pre_launch", "trading", "delivering", "closed"]] = {
    "PreLaunch": "pre_launch",
    "Trading": "trading",
    "Delivering": "delivering",
    "Closed": "closed",
}


def _decimal(raw: Mapping[str, Any], key: str, *, require_positive: bool = False) -> Decimal:
    value = raw.get(key)
    if value is None or value == "":
        raise InstrumentParseError(f"missing required field {key!r}")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise InstrumentParseError(f"field {key!r} is not a valid decimal: {value!r}") from exc
    if not parsed.is_finite():
        raise InstrumentParseError(f"field {key!r} is not finite: {value!r}")
    if require_positive and parsed <= 0:
        raise InstrumentParseError(f"field {key!r} must be > 0: {value!r}")
    return parsed


def _int(raw: Mapping[str, Any], key: str, value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:  # #5040: `int(inf)` overflows
        raise InstrumentParseError(f"field {key!r} is not an integer: {value!r}") from exc


def _optional_decimal(raw: Mapping[str, Any], key: str, default: Decimal) -> Decimal:
    value = raw.get(key)
    if value is None or value == "":
        return default
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise InstrumentParseError(f"field {key!r} is not a valid decimal: {value!r}") from exc
    if not parsed.is_finite():
        raise InstrumentParseError(f"field {key!r} is not finite: {value!r}")
    return parsed


def _filter(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """A nested filter object; absent is empty, anything but an object is malformed (#1896)."""
    value = raw.get(key)
    if value is None or value == "":
        return {}
    if not isinstance(value, Mapping):
        raise InstrumentParseError(f"field {key!r} is not an object: {value!r}")
    return value


def _str(raw: Mapping[str, Any], key: str, default: str) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str):
        raise InstrumentParseError(f"field {key!r} is not a string: {value!r}")
    return value


def parse_instrument(raw: Mapping[str, Any], *, fetched_at_us: int) -> Instrument:
    """Normalise one Bybit `instruments-info` (`category=linear`) list item
    into the neutral `Instrument` model. Raises `InstrumentParseError` on any
    missing/malformed required field rather than silently defaulting
    precision-critical values (native-SL/order-validation depends on these
    being exact — C-2.2 adapter rule, ticket "Technical notes").
    """
    try:
        symbol = raw["symbol"]
        status_raw = raw["status"]
        launch_time_ms = int(raw["launchTime"])
    except KeyError as exc:
        raise InstrumentParseError(f"missing required field {exc.args[0]!r}") from exc
    except (TypeError, ValueError, OverflowError) as exc:
        raise InstrumentParseError(
            f"launchTime is not an integer: {raw.get('launchTime')!r}"
        ) from exc

    if not isinstance(symbol, str) or not symbol:
        raise InstrumentParseError(f"symbol is not a non-empty string: {symbol!r}")
    # A list or object here is unhashable: check the type before the lookup (#1896).
    status = _STATUS_MAP.get(status_raw) if isinstance(status_raw, str) else None
    if status is None:
        raise InstrumentParseError(f"unknown instrument status: {status_raw!r}")

    # No default (#1933): a wrong interval corrupts the countdown and annualisation, so a row
    # without one is rejected like any other missing precision field.
    funding_cfg = raw.get("fundingInterval")
    if funding_cfg is None or funding_cfg == "":
        raise InstrumentParseError("missing required field 'fundingInterval'")

    try:
        return _build(raw, symbol, status, launch_time_ms, fetched_at_us)
    except ValidationError as exc:  # a value the domain model refuses is a malformed row (#1896)
        fields = ", ".join(sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]}))
        raise InstrumentParseError(f"invalid instrument field(s): {fields}") from exc


def _build(
    raw: Mapping[str, Any],
    symbol: str,
    status: Literal["pre_launch", "trading", "delivering", "closed"],
    launch_time_ms: int,
    fetched_at_us: int,
) -> Instrument:
    price_filter = _filter(raw, "priceFilter")
    lot_size_filter = _filter(raw, "lotSizeFilter")
    leverage_filter = _filter(raw, "leverageFilter")
    return Instrument(
        exchange="bybit",
        category="linear",
        symbol=symbol,
        base_coin=_str(raw, "baseCoin", ""),
        quote_coin=_str(raw, "quoteCoin", "USDT"),
        settle_coin=_str(raw, "settleCoin", "USDT"),
        status=status,
        contract_type="linear_perpetual",
        launch_time=launch_time_ms * 1000,
        tick_size=_decimal(price_filter, "tickSize", require_positive=True),
        price_scale=_int(raw, "priceScale", raw.get("priceScale", 2)),
        min_price=_optional_decimal(price_filter, "minPrice", Decimal(0)),
        max_price=_optional_decimal(price_filter, "maxPrice", Decimal(0)),
        qty_step=_decimal(lot_size_filter, "qtyStep", require_positive=True),
        min_order_qty=_decimal(lot_size_filter, "minOrderQty", require_positive=True),
        max_order_qty=_decimal(lot_size_filter, "maxOrderQty"),
        max_mkt_order_qty=_optional_decimal(
            lot_size_filter, "maxMktOrderQty", _decimal(lot_size_filter, "maxOrderQty")
        ),
        min_notional=_optional_decimal(lot_size_filter, "minNotionalValue", Decimal(0)),
        max_leverage=_decimal(leverage_filter, "maxLeverage"),
        min_leverage=_optional_decimal(leverage_filter, "minLeverage", Decimal(1)),
        leverage_step=_optional_decimal(leverage_filter, "leverageStep", Decimal("0.01")),
        funding_interval_min=_int(raw, "fundingInterval", raw["fundingInterval"]),
        upper_funding_rate=(
            _decimal(raw, "upperFundingRate")
            if raw.get("upperFundingRate") is not None
            else Decimal(0)
        ),
        lower_funding_rate=(
            _decimal(raw, "lowerFundingRate")
            if raw.get("lowerFundingRate") is not None
            else Decimal(0)
        ),
        copy_trading=bool(raw.get("copyTrading", False) not in (False, "None", "none")),
        metadata_version=1,
        fetched_at=fetched_at_us,
    )


class _PublicGetter(Protocol):
    async def get_public(
        self, path: str, *, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]: ...


_INSTRUMENTS_INFO_PATH = "/v5/market/instruments-info"
_INSTRUMENTS_PAGE_LIMIT = 1000
#: Hard bound on pages per refresh (bounded work, C-2.18): the linear
#: catalogue is ~500 symbols, i.e. one page; 20 pages leaves ample headroom.
_INSTRUMENTS_MAX_PAGES = 20


def parse_instruments(
    raw_items: Sequence[Mapping[str, Any]], *, fetched_at_us: int
) -> InstrumentsFetchResult:
    """Parse every list item; malformed rows are collected as rejections
    (never raised) so one bad row cannot fail the whole catalogue."""
    parsed: list[Instrument] = []
    rejected: list[RejectedInstrument] = []
    for raw in raw_items:
        if not isinstance(raw, Mapping):
            rejected.append(RejectedInstrument(symbol=None, reason="row is not an object"))
            continue
        try:
            parsed.append(parse_instrument(raw, fetched_at_us=fetched_at_us))
        except InstrumentParseError as exc:
            symbol = raw.get("symbol")
            rejected.append(
                RejectedInstrument(
                    symbol=symbol if isinstance(symbol, str) else None, reason=str(exc)
                )
            )
    return InstrumentsFetchResult(instruments=tuple(parsed), rejected=tuple(rejected))


async def _fetch_raw_pages(client: _PublicGetter) -> list[Mapping[str, Any]]:
    items: list[Mapping[str, Any]] = []
    cursor: str | None = None
    for _ in range(_INSTRUMENTS_MAX_PAGES):
        params: dict[str, Any] = {"category": "linear", "limit": _INSTRUMENTS_PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        response = await client.get_public(_INSTRUMENTS_INFO_PATH, params=params)
        result = response.get("result") or {}
        page = result.get("list") or []
        if not isinstance(page, list):
            raise InstrumentParseError("instruments-info result.list is not a list")
        items.extend(p for p in page if isinstance(p, Mapping))
        cursor = result.get("nextPageCursor") or None
        if not cursor:
            return items
    raise InstrumentParseError(
        f"instruments-info exceeded {_INSTRUMENTS_MAX_PAGES} pages; refusing unbounded paging"
    )


def make_instruments_info_fetcher(client: _PublicGetter) -> InstrumentsFetcher:
    """Adapt `BybitRestClient.get_public` (E08-T02) into the neutral
    `exchange.base.instruments.InstrumentsFetcher` port: fetch every
    `category=linear` page (following `nextPageCursor`) and parse it here, so
    the endpoint path, paging fields and raw payload never leave the adapter
    (C-2.2)."""

    async def _fetch(now_us: Callable[[], int]) -> InstrumentsFetchResult:
        raw_items = await _fetch_raw_pages(client)
        return parse_instruments(raw_items, fetched_at_us=now_us())

    return _fetch
