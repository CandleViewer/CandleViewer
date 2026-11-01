"""Seeded recorder load mix (E16-Q04): trade bursts, depth churn and liquidation cascades.

Realistic rather than uniform (ticket technical notes): every message is built from a template the
E08 normalisers parsed out of the recorded corpus (`fixture_app.CORPUS`, capture 2026-10-05), so a
trade carries a captured price, size, side and 36-character id shape, and a book delta a captured
level set (about 5 levels; depth 200). Only the timestamps, ids and sequence numbers are re-issued,
so the writer's dedup keys stay distinct and each symbol's `prev_update_id` chain never jumps.
A liquidation has no capture of its own: a cascade re-uses trade templates as the liquidated
orders, priced and sized as captured prints (the writer reads only `LiquidationLike`).

The mix runs in phases of `PHASE_MSGS` messages, each drawn from `PHASES` with a seeded RNG:
`steady` (mostly depth churn), `burst` (mostly trades) and `cascade` (liquidations with the trades
they set off). The produced counters (`produced_msgs`, `produced_rows` per QuestDB table) are the
oracle's side of the reconciliation: rows are counted as the writer will map them (one per trade or
liquidation, one per book level), independently of the writer.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from typing import Final, Literal

from bench.ingestion.fixture_app import CORPUS
from candleviewer.exchange.base.models import BookDelta, BookLevel

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.orderbook import parse_book_frame

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.trades import parse_trade_frame

Kind = Literal["trades", "orderbook_deltas", "liquidations"]
#: Per phase: weights of (trade, depth delta, liquidation).
PHASES: Final[dict[str, tuple[float, float, float]]] = {
    "steady": (0.25, 0.75, 0.0),
    "burst": (0.80, 0.20, 0.0),
    "cascade": (0.40, 0.20, 0.40),
}
PHASE_ODDS: Final = (("steady", 0.80), ("burst", 0.15), ("cascade", 0.05))
PHASE_MSGS: Final = 500
DEPTH: Final = 200
#: Captures with trades of their own; any other symbol takes the first one's.
TRADE_CAPTURES: Final = {
    "BTCUSDT": "ws/clean_publicTrade_BTCUSDT.jsonl",
    "ETHUSDT": "ws/clean_publicTrade_ETHUSDT.jsonl",
    "SOLUSDT": "ws/clean_publicTrade_SOLUSDT.jsonl",
}
BOOK_CAPTURE: Final = "ws/orderbook_BTCUSDT.jsonl"
BOOK_TICK: Final = Decimal("0.1")


@dataclass(frozen=True, slots=True)
class TradeTemplate:
    price: Decimal
    qty: Decimal
    side: str


@dataclass(frozen=True, slots=True)
class Trade:  # `writer.TradeLike`
    symbol: str
    ts_event: int
    trade_id: str
    price: Decimal
    qty: Decimal
    notional: Decimal
    side: str
    is_block_trade: bool
    seq: int


@dataclass(frozen=True, slots=True)
class Delta:  # `writer.BookDeltaLike`
    symbol: str
    ts_event: int
    depth: int
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    update_id: int
    prev_update_id: int
    cross_seq: int
    ts_match: int


@dataclass(frozen=True, slots=True)
class Liquidation:  # `writer.LiquidationLike`
    symbol: str
    ts_event: int
    price: Decimal
    qty: Decimal
    liquidated_side: str
    notional: Decimal
    batch_index: int


Event = Trade | Delta | Liquidation


def _normalised(w: tuple[float, float, float]) -> tuple[float, float, float]:
    total = sum(w)
    if total <= 0 or min(w) < 0:
        raise ValueError(f"phase weights {w}: non-negative, not all zero")
    return (w[0] / total, w[1] / total, w[2] / total)


def mean_delta_levels() -> float:
    books = book_templates()
    return sum(len(b) + len(a) for b, a in books) / len(books)


def reference_phase(rows_per_day: Mapping[str, int]) -> tuple[dict[str, float], float]:
    """The soak's one-phase mix at the 21 §11.1 reference rates (E16-K01's rows/day): per-symbol
    messages a second of trades and of book deltas (rows / mean captured levels per delta), and
    their sum. At that rate GB/day is comparable with the E16-K01 figure."""
    trades = rows_per_day["trades"] / 86_400
    deltas = rows_per_day["orderbook_deltas"] / 86_400 / mean_delta_levels()
    return {"trades": trades, "orderbook_deltas": deltas}, trades + deltas


@cache
def trade_templates(symbol: str) -> tuple[TradeTemplate, ...]:
    rel = TRADE_CAPTURES.get(symbol, TRADE_CAPTURES["BTCUSDT"])
    out = []
    for line in (CORPUS / rel).read_text(encoding="utf-8").splitlines():
        for p in parse_trade_frame(line) or ():
            out.append(TradeTemplate(p.price, p.qty, p.side))
    if not out:
        raise ValueError(f"no trade template in {rel}")
    return tuple(out)


@cache
def book_templates() -> tuple[tuple[tuple[BookLevel, ...], tuple[BookLevel, ...]], ...]:
    out = []
    for line in (CORPUS / BOOK_CAPTURE).read_text(encoding="utf-8").splitlines():
        ev = parse_book_frame(line, lambda _s: BOOK_TICK)
        if isinstance(ev, BookDelta) and (ev.bids or ev.asks):
            out.append((tuple(ev.bids), tuple(ev.asks)))
    if not out:
        raise ValueError(f"no delta template in {BOOK_CAPTURE}")
    return tuple(out)


class Mix:
    """`next(ts_us)` gives the next `(kind, event)`; symbols take turns, seeded throughout."""

    def __init__(
        self,
        symbols: Sequence[str],
        *,
        seed: int = 7,
        depth: int = DEPTH,
        phases: Mapping[str, tuple[float, float, float]] = PHASES,
        odds: Sequence[tuple[str, float]] = PHASE_ODDS,
    ) -> None:
        if not symbols:
            raise ValueError("at least one symbol")
        if {name for name, _ in odds} - set(phases) or abs(sum(o for _, o in odds) - 1) > 1e-9:
            raise ValueError("phase odds must name known phases and sum to 1")
        self.symbols = tuple(symbols)
        self._phases = {k: _normalised(w) for k, w in phases.items()}
        self._odds = tuple(odds)
        self._rng = random.Random(seed)  # noqa: S311 - seeded, reproducible mix; not crypto
        self._depth = depth
        self._trades = {s: trade_templates(s) for s in self.symbols}
        self._books = book_templates()
        self._update_id = dict.fromkeys(self.symbols, 0)
        self._batch = dict.fromkeys(self.symbols, 0)
        self._i = 0
        self.phase = "steady"
        self.produced_msgs = 0
        self.produced_rows: dict[str, int] = {}
        #: The same rows per symbol: the reconciliation's per-symbol breakdown (#5333).
        self.produced_by_symbol: dict[str, int] = {}
        self.phases_seen: dict[str, int] = {}

    def _pick_phase(self) -> None:
        roll, acc = self._rng.random(), 0.0
        for name, odds in self._odds:
            acc += odds
            if roll < acc:
                self.phase = name
                break
        self.phases_seen[self.phase] = self.phases_seen.get(self.phase, 0) + 1

    def _count(self, kind: Kind, symbol: str, rows: int) -> None:
        self.produced_msgs += 1
        self.produced_rows[kind] = self.produced_rows.get(kind, 0) + rows
        self.produced_by_symbol[symbol] = self.produced_by_symbol.get(symbol, 0) + rows

    def next(self, ts_us: int) -> tuple[Kind, Event]:
        if self._i % PHASE_MSGS == 0:
            self._pick_phase()
        symbol = self.symbols[self._i % len(self.symbols)]
        self._i += 1
        w_trade, w_delta, _ = self._phases[self.phase]
        roll = self._rng.random()
        if roll < w_trade:
            return "trades", self._trade(symbol, ts_us)
        if roll < w_trade + w_delta:
            return "orderbook_deltas", self._delta(symbol, ts_us)
        return "liquidations", self._liquidation(symbol, ts_us)

    def _trade(self, symbol: str, ts_us: int) -> Trade:
        t = self._rng.choice(self._trades[symbol])
        self._count("trades", symbol, 1)
        return Trade(
            symbol=symbol, ts_event=ts_us, trade_id=str(uuid.UUID(int=self._rng.getrandbits(128))),
            price=t.price, qty=t.qty, notional=t.price * t.qty, side=t.side,
            is_block_trade=False, seq=self._i,
        )  # fmt: skip

    def _delta(self, symbol: str, ts_us: int) -> Delta:
        bids, asks = self._rng.choice(self._books)
        prev = self._update_id[symbol]
        uid = self._update_id[symbol] = prev + 1
        self._count("orderbook_deltas", symbol, len(bids) + len(asks))
        return Delta(
            symbol=symbol, ts_event=ts_us, depth=self._depth, bids=bids, asks=asks,
            update_id=uid, prev_update_id=prev, cross_seq=uid, ts_match=ts_us,
        )  # fmt: skip

    def _liquidation(self, symbol: str, ts_us: int) -> Liquidation:
        t = self._rng.choice(self._trades[symbol])
        self._batch[symbol] += 1
        self._count("liquidations", symbol, 1)
        return Liquidation(
            symbol=symbol, ts_event=ts_us, price=t.price, qty=t.qty,
            liquidated_side="long" if t.side == "sell" else "short",
            notional=t.price * t.qty, batch_index=self._batch[symbol],
        )  # fmt: skip
