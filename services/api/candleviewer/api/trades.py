"""`GET /market/trades` (`docs/plan/22-api-openapi.yaml` `getTrades`, E08-S04, E22-T02).

Serves the in-memory hot tape kept by `TradeStream` (last 1 000 prints per
symbol), newest-first, with the full contract surface: `from`/`to`, `side`,
`min_size`, opaque keyset `cursor` paging, clustering (`cluster_window_ms`/
`cluster_tolerance_ticks`) and derived `tick_direction`. The page is built through
the big-trade tape (`orderflow/bigtrade_tape.py`), the code `trades.{symbol}` uses
(23 §6.1): `min_size` is a raw floor before the engine's clusterer, `is_big_trade`
the engine's flag, and `meta` carries the threshold (`TradesPageMeta`). Bounds are
checked before the tape is read (E22 threat model): `to - from` at most 6 h, 15 min
past a 2 000 ms cluster window (SR-E22-01, 400 `invalid_time_range`); `limit` at most
500 (SR-E22-02); `min_size` at least the instrument's `MIN_SIZE_FLOOR` (SR-E22-03,
400 `invalid_min_size`). A request for a listed symbol also (re)acquires its
public-trade stream demand with a grace period, so the tape fills lazily with no
other consumer. RBAC (C-12.4) mirrors `api/ticker.py`: fail-closed 501/401/403.
Deeper history is E16.

The route has no rate limit of its own, and a page runs both tapes over up to 1 000 prints on
the event loop, so pages are memoised (`PageCache`): per symbol, option set and side, keyed on
the hot tape's head print `(ts_event, trade_id)` (plus the tick size and the threshold config),
in an LRU of at most `PAGE_CACHE_MAX` entries. A repeated read of an unchanged tape is a lookup;
any new print moves the head and misses.
"""

from __future__ import annotations

import base64
import binascii
import inspect
import json
from collections import OrderedDict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal, Protocol

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from candleviewer.api.ticker import _iso, _Principal, _problem, _Resolver
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.orderflow import limits as L
from candleviewer.orderflow.bigtrade_metrics import bigtrade_range_rejected_total
from candleviewer.orderflow.bigtrade_models import BigTradeConfig, Mode
from candleviewer.orderflow.bigtrade_tape import Options, TapeItem, tape_page

_REQUIRED_PERMISSION = "marketdata:read"
_ENDPOINT = "trades"


class TradeReader(Protocol):
    def recent(self, symbol: str) -> list[TradeEvent]: ...
    def is_listed(self, symbol: str) -> bool: ...
    def acquire(self, consumer: str, symbol: str) -> None: ...
    def release(self, consumer: str, symbol: str) -> None: ...
    def tick_size(self, symbol: str) -> Decimal | None: ...


DEMAND_CONSUMER = "rest-tape"
#: Memoised pages per router (module docstring): 64 keys of at most 1 000 items each.
PAGE_CACHE_MAX: Final = 64

#: `(symbol, options, side, tick size, config, head print)`; the head is None on an empty tape.
PageKey = tuple[str, Options, str | None, Decimal, BigTradeConfig, tuple[int, str] | None]
Page = tuple[tuple[TapeItem, ...], Decimal, Mode]


class PageCache:
    """A bounded LRU of `tape_page` results (module docstring); the event loop's only."""

    def __init__(self, maxsize: int = PAGE_CACHE_MAX) -> None:
        self._max = maxsize
        self._pages: OrderedDict[PageKey, Page] = OrderedDict()

    def __len__(self) -> int:
        return len(self._pages)

    def get(self, key: PageKey) -> Page | None:
        page = self._pages.get(key)
        if page is not None:
            self._pages.move_to_end(key)
        return page

    def put(self, key: PageKey, page: Page) -> None:
        self._pages[key] = page
        self._pages.move_to_end(key)
        while len(self._pages) > self._max:
            self._pages.popitem(last=False)


def _head(events: Sequence[TradeEvent]) -> tuple[int, str] | None:
    return (events[-1].ts_event, events[-1].trade_id) if events else None


def serialize_trade(item: TapeItem) -> dict[str, object]:
    """The 22 `PublicTrade` of a tape row: its first print, the members' total size."""
    ev = item.first.event
    out: dict[str, object] = {
        "id": ev.trade_id,
        "ts": _iso(ev.ts_event),
        "price": format(ev.price, "f"),
        "size": format(item.size, "f"),
        "side": ev.side,
        "is_block_trade": ev.is_block_trade,
        "is_liquidation": False,  # the public tape names no liquidation-origin print
        "is_big_trade": item.big,
        "cluster_size": item.cluster_size,
    }
    if item.first.tick_direction is not None:
        out["tick_direction"] = item.first.tick_direction
    return out


def _coded(status: int, code: str, detail: str) -> JSONResponse:
    bigtrade_range_rejected_total.labels(_ENDPOINT).inc()
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"https://candleviewer.local/errors/{code}",
            "title": "Bad request",
            "status": status,
            "detail": detail,
            "code": code,
        },
    )


def _encode_cursor(e: TradeEvent) -> str:
    raw = json.dumps({"ts": e.ts_event, "id": e.trade_id}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[int, str]:
    try:
        obj = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        return int(obj["ts"]), str(obj["id"])
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise ValueError("invalid cursor") from exc


def _parse_ts(value: str | None) -> int | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must carry a UTC offset")
    return int(dt.astimezone(UTC).timestamp() * 1_000_000)


def make_trades_router(
    reader_provider: Callable[[], TradeReader | None],
    *,
    principal_resolver: _Resolver | None = None,
    min_size_floor: Callable[[str], Decimal | None] = lambda _symbol: None,
    config: Callable[[str], BigTradeConfig] = lambda _symbol: BigTradeConfig(),
    pages: PageCache | None = None,
) -> APIRouter:
    """`min_size_floor` is the instrument's `MIN_SIZE_FLOOR` (SR-E22-03; `None` while the catalogue
    does not list it, which refuses any `min_size`); `config` the symbol's threshold config;
    `pages` the memo of built pages (a new one per router when None)."""
    router = APIRouter(tags=["market-data"])
    cache = PageCache() if pages is None else pages

    @router.get("/market/trades")
    async def get_trades(
        request: Request,
        symbol: str,
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = None,
        cursor: str | None = Query(default=None, max_length=512),
        limit: int = Query(default=100, ge=1, le=L.TRADES_MAX_LIMIT),
        side: Literal["buy", "sell"] | None = None,
        min_size: str | None = None,
        cluster_window_ms: int = Query(default=0, ge=0, le=L.CLUSTER_WINDOW_MS_MAX_REST),
        cluster_tolerance_ticks: int = Query(default=0, ge=0, le=L.CLUSTER_TOLERANCE_TICKS_MAX),
    ) -> JSONResponse:
        if principal_resolver is None:
            return _problem(501, "Not implemented", "no principal resolver wired")
        resolved: Any = principal_resolver.resolve(request)
        principal: _Principal | None = await resolved if inspect.isawaitable(resolved) else resolved
        if principal is None:
            return _problem(401, "Unauthorized", "no verified session for this request")
        if not principal.has(_REQUIRED_PERMISSION):
            return _problem(403, "Forbidden", f"requires {_REQUIRED_PERMISSION}")
        if not (4 <= len(symbol) <= 20 and symbol.isascii() and symbol.isalnum()):
            return _problem(400, "Bad request", "invalid symbol")
        try:
            start, end = _parse_ts(from_), _parse_ts(to)
            floor = None if min_size is None else Decimal(min_size)
            after = None if cursor is None else _decode_cursor(cursor)
        except (ValueError, InvalidOperation):
            return _problem(400, "Bad request", "invalid from/to/min_size/cursor")
        span = _window_refusal(start, end, cluster_window_ms)
        if span is not None:  # SR-E22-01, before anything is read
            return _coded(400, "invalid_time_range", span)
        symbol = symbol.upper()
        reader = reader_provider()
        if reader is None:
            return _problem(503, "Service unavailable", "trade stream not running")
        if not reader.is_listed(symbol):
            return _problem(404, "Not found", f"unknown instrument {symbol}")
        if floor is not None:  # SR-E22-03
            bound = min_size_floor(symbol)
            if bound is None or not floor.is_finite() or floor < bound:
                shown = "unknown" if bound is None else format(bound, "f")
                return _coded(400, "invalid_min_size", f"min_size is below the floor ({shown})")
        tick = reader.tick_size(symbol)
        if tick is None:
            return _problem(503, "Service unavailable", "instrument tick size unknown")
        # Demand is refreshed per request; the grace period expires it when idle.
        reader.acquire(DEMAND_CONSUMER, symbol)
        reader.release(DEMAND_CONSUMER, symbol)
        options = Options(floor, cluster_window_ms, cluster_tolerance_ticks)
        events, cfg = reader.recent(symbol), config(symbol)
        key: PageKey = (symbol, options, side, tick, cfg, _head(events))
        built = cache.get(key)
        if built is None:
            found, threshold, mode = tape_page(events, symbol, tick, cfg, options, side=side)
            built = (tuple(found), threshold, mode)
            cache.put(key, built)
        items, threshold, mode = built
        rows = [
            i
            for i in reversed(items)
            if (start is None or i.key[0] >= start)
            and (end is None or i.key[0] < end)
            and (after is None or i.key < after)
        ]
        page = rows[:limit]
        has_more = len(rows) > limit
        meta = {
            "next_cursor": _encode_cursor(page[-1].first.event) if has_more else None,
            "has_more": has_more,
            "count": len(page),
            "big_trade_threshold": format(threshold, "f"),
            "big_trade_mode": mode,
        }
        items_out = [serialize_trade(i) for i in page]
        return JSONResponse(status_code=200, content={"items": items_out, "meta": meta})

    return router


def _window_refusal(start: int | None, end: int | None, cluster_window_ms: int) -> str | None:
    """SR-E22-01: `to - from` at most 6 h, or 15 min when `cluster_window_ms` is over 2000 ms."""
    if start is None or end is None:
        return None  # the hot tape bounds an open-ended read
    if end < start:
        return "to is before from"
    wide = cluster_window_ms > L.CLUSTER_WINDOW_MS_MAX_WS
    cap_ms = L.TRADES_MAX_WINDOW_CLUSTERED_MS if wide else L.TRADES_MAX_WINDOW_MS
    if end - start > cap_ms * 1000:
        return f"to - from exceeds {cap_ms // 60_000} min"
    return None


__all__ = [
    "PAGE_CACHE_MAX",
    "Page",
    "PageCache",
    "PageKey",
    "TradeReader",
    "make_trades_router",
    "serialize_trade",
]
