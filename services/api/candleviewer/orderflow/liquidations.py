"""Liquidations read side and ingest meter (E24-T03, #667): clustering, coverage, paging.

Module boundary (C-3.1): orderflow may not import `storage` or `ingestion`, so the store is a local
structural Protocol the composition root injects.

- **Clustering** (`Clusterer`, also the WS topic's): exact, per side. A cluster opens on a print
  and gathers every later print of its side before `first.ts + window`; `size` and `notional`
  are sums, `ts` and `price` the first print's, `cluster_size` the count. Window 0: one item per
  print. Nothing is estimated (22 `/market/liquidations`).
- **Coverage** (STRIDE T, US-DERIV-006): `first_available_ts` is the first stored print of the
  symbol; a window that ends at or before it (or a symbol with nothing stored) is `no_coverage`,
  and the store is not read: an empty page there means "not recorded", never "none happened".
- **Bounds** (`deriv_limits`, G1) are checked before any store read.
- **Paging.** Items are ordered by their first print's dedup-key order (a total order). A page
  reads each side from its own cut, at most `SCAN_PRINTS` prints a side. The cursor carries the
  last item's key and, per side, a cut: the full key (`Cut`) of that side's first unreturned
  print, inclusive. One side's clusters are contiguous runs of its prints in key order, so a scan
  restarted there rebuilds every later cluster exactly, however many prints share one `ts`.
  A side cut short by the cap keeps only the clusters no unread print can join, and the page stops
  below the first item it could not keep. A single cluster of more prints than the cap is split
  after the last print read.
- **Cursor trust.** A cursor is client input: its numbers are bounded (finite, `0..MAX_PRICE` /
  `MAX_QTY`, at most 32 characters, a bounded exponent) before any arithmetic, it is bound to the
  request (symbol, side, window, floor, `from`, `to`), and a next cursor is built only from keys
  the store returned, never from the one the client sent.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Protocol

from candleviewer.domain.liquidations import ClosingSide, Cut, LiqPrint, closing_side
from candleviewer.exchange.base.frame_guard import MAX_FUTURE_SKEW_MS, MAX_PRICE, MAX_QTY
from candleviewer.exchange.base.models import LiquidationEvent
from candleviewer.orderflow.deriv_limits import (
    CLUSTER_WINDOW_MS_MAX_REST,
    CURSOR_MAX_LEN,
    CURSOR_TTL_S,
    MAX_WINDOW_DAYS_LIQ,
    DerivInvalidRequest,
    DerivSymbolUnlisted,
    check_limit,
    check_window,
)
from candleviewer.orderflow.deriv_metrics import (
    deriv_liquidation_burst_rate,
    deriv_liquidation_ingest_lag_seconds,
    deriv_liquidation_notional_total,
    deriv_liquidation_prints_total,
    deriv_liquidation_socket_reconnects_total,
)
from candleviewer.orderflow.funding_metrics import deriv_upstream_schema_rejected_total

#: Prints one page reads at most (the hot tier's row cap is 5 001).
SCAN_PRINTS: Final = 5000
_SIDES: Final[tuple[ClosingSide, ClosingSide]] = ("buy", "sell")
_BAD_CURSOR: Final = "pagination cursor is malformed or expired"
_ZERO: Final = Decimal(0)
_SKEW_US: Final = MAX_FUTURE_SKEW_MS * 1000
#: A cursor number: at most this many characters and fractional digits.
_CURSOR_NUM_CHARS: Final = 32
type Key = tuple[int, str, Decimal, Decimal, int]


class LiquidationStore(Protocol):
    async def write_prints(self, rows: Sequence[LiqPrint]) -> None: ...

    async def read_prints(
        self, symbol: str, rng: Any, side: str | None, limit: int, from_key: Cut | None = None
    ) -> Sequence[LiqPrint]:
        """`symbol`'s prints in `rng`, dedup-key order, those at or above `from_key` only."""
        ...

    async def first_ts(self, symbol: str) -> int | None: ...


ListedLookup = Callable[[str], bool | None]


def print_of(event: LiquidationEvent) -> LiqPrint:
    """The table row of one print; its side from `liquidated_side` (24 §17.4 L6)."""
    return LiqPrint(
        ts_us=event.ts_event,
        symbol=event.symbol,
        side=closing_side(event.liquidated_side),
        price=event.price,
        size=event.qty,
        notional=event.notional,
        batch_index=event.batch_index,
        recv_ts_us=event.ts_ingest,
    )


@dataclass(slots=True)
class LiqItem:
    """One print or one cluster of one side."""

    first: LiqPrint
    end_us: int
    size: Decimal
    notional: Decimal
    count: int = 1

    @classmethod
    def open(cls, p: LiqPrint, window_us: int) -> LiqItem:
        return cls(p, p.ts_us + max(window_us, 1), p.size, p.notional)

    def key(self) -> Key:
        return self.first.key()

    def wire(self) -> dict[str, Any]:
        """The 23 §14.9 item (`ts_ms`); REST renames `ts` at its edge."""
        return {
            "symbol": self.first.symbol,
            "ts_ms": self.first.ts_us // 1000,
            "side": self.first.side,
            "price": format(self.first.price, "f"),
            "size": format(self.size, "f"),
            "notional_usd": format(self.notional, "f"),
            "cluster_size": self.count,
        }


class Clusterer:
    """Exact per-side clustering over prints in time order (module docstring)."""

    def __init__(self, window_ms: int) -> None:
        self.window_us = window_ms * 1000
        self.open: dict[str, LiqItem] = {}

    def add(self, p: LiqPrint, now_us: int | None = None) -> LiqItem | None:
        """Take one print; the item it closed (window 0: its own), or None. With `now_us` (the
        live topic), a cluster ends by `now + skew + window` at the latest (`skew` the ingest
        window's future tolerance, so an accepted print is never cut short): a print stamped
        further ahead cannot hold its side open past that."""
        if self.window_us == 0:
            return LiqItem.open(p, 0)
        held = self.open.get(p.side)
        if held is not None and p.ts_us < held.end_us:
            held.size += p.size
            held.notional += p.notional
            held.count += 1
            return None
        item = self.open[p.side] = LiqItem.open(p, self.window_us)
        if now_us is not None:
            item.end_us = min(item.end_us, now_us + _SKEW_US + self.window_us)
        return held

    def expire(self, now_us: int) -> list[LiqItem]:
        """Close the clusters whose window ended at or before `now_us`."""
        done = [item for item in self.open.values() if item.end_us <= now_us]
        for item in done:
            del self.open[item.first.side]
        return done


@dataclass(frozen=True, slots=True)
class Coverage:
    first_available_us: int | None
    covered_from_us: int | None
    covered_to_us: int | None
    no_coverage: bool


@dataclass(frozen=True, slots=True)
class LiquidationPage:
    symbol: str
    items: tuple[LiqItem, ...]
    next_cursor: str | None
    has_more: bool
    coverage: Coverage


@dataclass(frozen=True, slots=True)
class _Window:
    start_us: int
    end_us: int


@dataclass(slots=True)
class _Cursor:
    after: Key | None
    cuts: dict[str, Cut] = field(default_factory=dict)


def _cut_of(p: LiqPrint) -> Cut:
    return (p.ts_us, p.price, p.size, p.batch_index)


def encode_cursor(binding: str, cur: _Cursor, *, now_s: float) -> str:
    """Only ever called with keys the store returned (module docstring, cursor trust)."""
    after = None
    if cur.after is not None:
        ts, side, price, size, bi = cur.after
        after = [ts, side, format(price, "f"), format(size, "f"), bi]
    cuts = {s: [t, format(p, "f"), format(z, "f"), b] for s, (t, p, z, b) in cur.cuts.items()}
    raw = {"k": binding, "a": after, "c": cuts, "i": int(now_s)}
    text = json.dumps(raw, separators=(",", ":"))
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _int(v: object) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < 2**63:
        raise ValueError("not an int")
    return v


def _num(v: object, cap: Decimal) -> Decimal:
    """A cursor's price or size, bounded before any arithmetic: a string of at most 32
    characters, finite, `0..cap`, at most 32 fractional digits (so `format(.., "f")` is short)."""
    if not isinstance(v, str) or len(v) > _CURSOR_NUM_CHARS:
        raise ValueError("cursor number")
    d = Decimal(v)
    if not d.is_finite() or d.adjusted() > cap.adjusted() or not _ZERO <= d <= cap:
        raise ValueError("cursor number out of range")
    exponent = d.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -_CURSOR_NUM_CHARS:
        raise ValueError("cursor number precision")
    return d


def _cut(v: object) -> Cut:
    if not isinstance(v, list) or len(v) != 4:
        raise ValueError("cut")
    ts, price, size, bi = v
    return (_int(ts), _num(price, MAX_PRICE), _num(size, MAX_QTY), _int(bi))


def decode_cursor(cursor: str, *, binding: str, now_s: float) -> _Cursor:
    """Malformed, foreign, oversized, out-of-range or expired cursors raise `invalid_cursor`
    (400)."""
    bad = DerivInvalidRequest("invalid_cursor", _BAD_CURSOR)
    if not cursor or len(cursor) > CURSOR_MAX_LEN:
        raise bad
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        issued, after, cuts = _int(data["i"]), data["a"], data["c"]
        if data["k"] != binding or now_s - issued > CURSOR_TTL_S or issued > now_s + 60:
            raise ValueError("foreign or expired")
        key = None
        if after is not None:
            ts, side, price, size, bi = after
            if side not in _SIDES:
                raise ValueError("side")
            key = (_int(ts), str(side), _num(price, MAX_PRICE), _num(size, MAX_QTY), _int(bi))
        if not isinstance(cuts, dict) or set(cuts) - set(_SIDES):
            raise ValueError("cuts")
        return _Cursor(key, {str(s): _cut(c) for s, c in cuts.items()})
    except (ValueError, KeyError, TypeError, InvalidOperation, binascii.Error) as exc:
        raise bad from exc


def _passes(item: LiqItem, min_notional: Decimal | None) -> bool:
    return min_notional is None or item.notional >= min_notional


def cluster_scan(prints: Iterable[LiqPrint], window_ms: int, cuts: dict[str, int]) -> list[LiqItem]:
    """Every item of `prints` (dedup-key order), side `s` read from `cuts[s]` on, in key order;
    the clusters still open at the end come last, unclosed (the caller decides finality)."""
    clusterer, items = Clusterer(window_ms), []
    for p in prints:
        if p.ts_us < cuts.get(p.side, 0):
            continue
        closed = clusterer.add(p)
        if closed is not None:
            items.append(closed)
    items.extend(clusterer.open.values())
    return sorted(items, key=LiqItem.key)


class LiquidationService:
    def __init__(
        self,
        *,
        store: LiquidationStore,
        listed: ListedLookup,
        clock_s: Callable[[], float] = time.time,
        scan_prints: int = SCAN_PRINTS,
    ) -> None:
        self._store, self._listed, self._clock_s = store, listed, clock_s
        self._scan = scan_prints

    async def write(self, events: Sequence[LiquidationEvent]) -> None:
        """The ingestion stream's write-behind: one row per print, the dedup key absorbs a replay.
        `StorageTierUnavailable` until the hot tier is up: the stream retries, dropping nothing."""
        await self._store.write_prints([print_of(e) for e in events])

    async def page(
        self,
        symbol: str,
        *,
        start_us: int | None,
        end_us: int | None,
        limit: int,
        cursor: str | None,
        side: str | None,
        min_notional: Decimal | None,
        cluster_window_ms: int,
    ) -> LiquidationPage:
        now_s = self._clock_s()
        now_us = int(now_s * 1_000_000)
        if cursor is not None and (not cursor or len(cursor) > CURSOR_MAX_LEN):
            raise DerivInvalidRequest("invalid_cursor", _BAD_CURSOR)
        if not 0 <= cluster_window_ms <= CLUSTER_WINDOW_MS_MAX_REST:
            raise DerivInvalidRequest(
                "validation_failed", f"cluster_window_ms must be 0..{CLUSTER_WINDOW_MS_MAX_REST}"
            )
        if side is not None and side not in _SIDES:
            raise DerivInvalidRequest("validation_failed", "side must be buy or sell")
        if min_notional is not None and not (min_notional.is_finite() and min_notional >= 0):
            raise DerivInvalidRequest("validation_failed", "min_notional_usd must be >= 0")
        check_limit(limit)
        start, end = check_window(start_us, end_us, now_us=now_us, max_days=MAX_WINDOW_DAYS_LIQ)
        if self._listed(symbol) is False:
            raise DerivSymbolUnlisted(symbol)
        # Bound to every option and to the window as the client sent it (an omitted `to` is
        # "now" on each page, so paging a live window still works).
        binding = f"{symbol}:{side}:{cluster_window_ms}:{min_notional}:{start_us}:{end_us}"
        cur = _Cursor(None)
        if cursor is not None:
            cur = decode_cursor(cursor, binding=binding, now_s=now_s)
        first = await self._store.first_ts(symbol)
        if first is None or end <= first:
            return LiquidationPage(symbol, (), None, False, Coverage(first, None, None, True))
        coverage = Coverage(first, max(start, first), min(end, now_us), False)
        merged: list[LiqItem] = []
        horizon: Key | None = None
        rest: dict[str, Cut] = {}
        for s in (side,) if side is not None else _SIDES:
            scan = await self._scan_side(symbol, s, _Window(start, end), cur.cuts.get(s),
                                         cluster_window_ms)  # fmt: skip
            merged += scan.items
            rest[s] = scan.resume if scan.resume is not None else (end, _ZERO, _ZERO, 0)
            if scan.horizon is not None and (horizon is None or scan.horizon < horizon):
                horizon = scan.horizon
        merged = sorted((i for i in merged if cur.after is None or i.key() > cur.after),
                        key=LiqItem.key)  # fmt: skip
        avail = [i for i in merged if horizon is None or i.key() < horizon]
        eligible = [i for i in avail if _passes(i, min_notional)]
        page = eligible[:limit]
        if len(eligible) <= limit and horizon is None:
            return LiquidationPage(symbol, tuple(page), None, False, coverage)
        # The next cursor holds only keys read from the store this page (never `cur.after`).
        after = page[-1].key() if page else (avail[-1].key() if avail else None)
        left = [i for i in merged if after is None or i.key() > after]
        cuts = {s: next((_cut_of(i.first) for i in left if i.first.side == s), r)
                for s, r in rest.items()}  # fmt: skip
        more = horizon is not None or any(_passes(i, min_notional) for i in left)
        nxt = encode_cursor(binding, _Cursor(after, cuts), now_s=now_s) if more else None
        return LiquidationPage(symbol, tuple(page), nxt, more, coverage)

    async def _scan_side(
        self, symbol: str, side: str, window: _Window, cut: Cut | None, window_ms: int
    ) -> _SideScan:
        """One side's prints from its cut. Cut short by the cap after the print `last`, it keeps
        the clusters no unread print (key above `last`, so `ts >= last.ts`) can join, and names
        where the side resumes (its first unkept cluster's first print) and the key below which
        every item of the side is known (`horizon`). When every item read is final (window 0),
        or one cluster holds every row read (more prints than the cap in one window: split), it
        resumes just after `last`, never re-reading a row."""
        rows = list(await self._store.read_prints(symbol, window, side, self._scan, cut))
        items = cluster_scan(rows, window_ms, {})
        if len(rows) < self._scan:
            return _SideScan(items, None, None)
        last = rows[-1]
        kept = [i for i in items if window_ms == 0 or i.end_us <= last.ts_us]
        if kept and len(kept) < len(items):
            dropped = items[len(kept)]
            return _SideScan(kept, _cut_of(dropped.first), dropped.key())
        # The least key above `last` (batch_index is an int, the key's last column).
        nxt = (last.ts_us, last.price, last.size, last.batch_index + 1)
        return _SideScan(items, nxt, (last.ts_us, last.side, *nxt[1:]))


@dataclass(frozen=True, slots=True)
class _SideScan:
    items: list[LiqItem]
    resume: Cut | None  # where the side's next scan starts (inclusive); None: read to the end
    horizon: Key | None  # every item of the side with a smaller key is in `items`


class LiquidationMeter:
    """`LiquidationObserver` for the ingestion stream: the ticket's `deriv_liquidation_*` series.
    The burst rate is the print count of the current exchange-time second."""

    def __init__(self) -> None:
        self._second = -1
        self._count = 0

    def prints(self, events: Sequence[LiquidationEvent], now_us: int) -> None:
        for e in events:
            deriv_liquidation_prints_total.labels(e.liquidated_side).inc()
            deriv_liquidation_notional_total.labels(e.liquidated_side).inc(float(e.notional))
            second = e.ts_event // 1_000_000
            if second != self._second:
                self._second, self._count = second, 0
            self._count += 1
        deriv_liquidation_burst_rate.set(self._count)
        newest = max(e.ts_event for e in events)
        deriv_liquidation_ingest_lag_seconds.set(max(0.0, (now_us - newest) / 1e6))

    def reconnect(self) -> None:
        deriv_liquidation_socket_reconnects_total.inc()

    def rejected(self) -> None:
        deriv_upstream_schema_rejected_total.labels("liquidations", "schema").inc()


__all__ = [
    "SCAN_PRINTS",
    "Clusterer",
    "Coverage",
    "LiqItem",
    "LiquidationMeter",
    "LiquidationPage",
    "LiquidationService",
    "LiquidationStore",
    "cluster_scan",
    "decode_cursor",
    "encode_cursor",
    "print_of",
]
