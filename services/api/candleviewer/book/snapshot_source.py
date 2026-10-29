"""`book.{symbol}.{depth}` snapshots for the WS gateway (#2196; `23-ws-protocol.md` §6.1, §7).

The book module's `ws/sequencing.py::SnapshotSource`: adapters live in their owning module and the
gateway only wires them (#1778 Q2). `book` may not import `ws` (CONSTITUTION §3), so the Protocol
is met structurally: `sub` is typed by the fields read here and the gateway's body constructor is
injected (`ws_wiring.book_snapshot_body`). Every call reads the engine's plain published state
(`phase`, `resync_count`, `last_u`, its book), never an interpreter (C-2.20, INV-B14-b).

- `build`: only a `live` book is served (B14 tags only `live` consumable), so it is
  `None` for a replay subscription (the live book is no replay state), an unknown symbol or
  instrument, and while the book is building, rebuilding or desynced (C-2.5). Otherwise the best
  `min(topic depth, engine tier)` levels per side. `stale` is the injected `stale(symbol)`
  (#2487): the wiring binds `BookStream.is_stale`, the freshness the REST book reads, so both
  surfaces derive it once from the last applied frame against the watchdog's book limit.
  Scales are the instrument's tick and qty step, raised where a level needs more places, so
  both forms carry every level exactly (§3.4). A book whose
  scales or values do not fit §14.1 and the kind-1 fields is not served either: one malformed
  level never reaches the encoder.
- `generation`: a counter that moves whenever the engine, its resync count, its update id or its
  phase changes, or `stale` flips (a stalled book applies no frame, so only the flag tells the
  render cache its verdict is out of date): monotonic, and never one value for two states (`u`
  is per tier, and a venue reset restarts it).
- `continuity`: always False. The engine keeps no delta history and the book publisher (#604)
  starts at the attach point, so no `snapshot: false` attach can be proven (§7.6): every one is
  `snapshot_forced` (§7.7).

One entry per engine, dropped with it (weak keys).
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable, Mapping
from decimal import MAX_EMAX, MAX_PREC, MIN_EMIN, Context, Decimal
from typing import Any, Final, Protocol
from weakref import WeakKeyDictionary

from candleviewer.book.models import BookPhase
from candleviewer.book.resync import BookEngine
from candleviewer.exchange.base.models import BookLevel

#: A CVWB kind-1 record `(side, price, size)`, side 0 bid and 1 ask (§3.4).
Record = tuple[int, int, int]
#: §14.1 caps `price_scale` and `qty_scale` at 18 (the CVWB header holds each in a u8).
_MAX_SCALE: Final = 18
#: Kind-1 field ranges (§3.4): `price` is an i64; `size` and the trailer's `xu`, `xseq` are u64.
_I64: Final = range(-(2**63), 2**63)
_U64: Final = range(2**64)
#: Scaling a level to an integer never rounds, whatever the caller's decimal context.
_EXACT: Final = Context(prec=MAX_PREC, Emax=MAX_EMAX, Emin=MIN_EMIN)
#: What one engine's generation names: its resync count, update id `u`, phase and `stale`.
_State = tuple[int, int, BookPhase, bool]


class _Topic(Protocol):
    @property
    def symbol(self) -> str | None: ...

    @property
    def depth(self) -> int | None: ...


class BookSub(Protocol):
    """The fields of a WS `Subscription` read here."""

    @property
    def topic(self) -> _Topic: ...

    @property
    def replay_session_id(self) -> str | None: ...


class BodyFactory[B](Protocol):
    """The gateway's snapshot body from the §14.1 payload and its kind-1 records and trailer."""

    def __call__(
        self,
        structured: Mapping[str, Any],
        records: tuple[Record, ...],
        trailer: tuple[int, int],
        *,
        price_scale: int,
        qty_scale: int,
        stale: bool,
    ) -> B: ...


class BookSnapshotSource[B]:
    """`SnapshotSource` of the `book` family over the live engines (see the module docstring)."""

    def __init__(
        self,
        engines: Callable[[str], BookEngine | None],
        steps: Callable[[str], tuple[Decimal, Decimal] | None],
        body: BodyFactory[B],
        *,
        stale: Callable[[str], bool] | None = None,
    ) -> None:
        """`engines`: a symbol's active engine. `steps`: its instrument's tick and qty step.
        `stale`: whether a symbol's book is behind its freshness SLO (none: never stale)."""
        self._engines, self._steps, self._body = engines, steps, body
        self._stale = stale
        self._seen: WeakKeyDictionary[BookEngine, tuple[_State, int]] = WeakKeyDictionary()
        self._generations = itertools.count(1)

    def build(self, sub: BookSub) -> B | None:
        eng = self._engine(sub)
        steps = None if eng is None else self._steps(eng.symbol)
        if eng is None or steps is None or eng.phase is not BookPhase.LIVE:
            return None
        book, xseq = eng.book, eng.snapshot_cross_seq
        if book is None or xseq is None:
            return None
        depth = min(sub.topic.depth or eng.depth, eng.depth)
        bids, asks = book.top(depth)
        scales = book_scales(steps, bids, asks)
        if scales is None:
            return None
        return self.render(eng, depth, bids, asks, eng.last_u, scales)

    def steps(self, symbol: str) -> tuple[Decimal, Decimal] | None:
        """The symbol's instrument tick and qty step, `None` while unknown."""
        return self._steps(symbol)

    def render(
        self,
        eng: BookEngine,
        depth: int,
        bids: tuple[BookLevel, ...],
        asks: tuple[BookLevel, ...],
        xu: int,
        scales: tuple[int, int],
    ) -> B | None:
        """The §14.1 body of these levels at `scales` (E21-T01: the book publisher renders the
        window it holds through it); `None` when a value does not fit its kind-1 field."""
        xseq = eng.snapshot_cross_seq
        if xseq is None:
            return None
        ps, qs = scales
        records = _records(0, bids, ps, qs) + _records(1, asks, ps, qs)
        trailer = (xu, xseq)
        if not _fits(records, trailer):
            return None
        structured = {"symbol": eng.symbol, "depth": depth, "xu": xu, "xseq": xseq,
                      "bids": _rows(bids), "asks": _rows(asks)}  # fmt: skip
        return self._body(
            structured, records, trailer, price_scale=ps, qty_scale=qs, stale=self.is_stale(eng)
        )

    def generation(self, sub: BookSub) -> int:
        eng = self._engine(sub)
        if eng is None:
            return 0
        state = (eng.resync_count, eng.last_u, eng.phase, self.is_stale(eng))
        seen = self._seen.get(eng)
        if seen is None or seen[0] != state:
            seen = self._seen[eng] = (state, next(self._generations))
        return seen[1]

    def continuity(self, sub: BookSub, from_ts_ms: int | None) -> bool:
        """Never proven, so every `snapshot: false` attach is forced (see the module docstring)."""
        return False

    def is_stale(self, eng: BookEngine) -> bool:
        """Whether `eng`'s book is behind its freshness SLO (#2487)."""
        return self._stale is not None and self._stale(eng.symbol)

    def engine(self, symbol: str) -> BookEngine | None:
        """The symbol's active engine."""
        return self._engines(symbol)

    def _engine(self, sub: BookSub) -> BookEngine | None:
        symbol = sub.topic.symbol
        if sub.replay_session_id is not None or symbol is None:
            return None
        return self._engines(symbol)


def book_scales(
    steps: tuple[Decimal, Decimal], bids: tuple[BookLevel, ...], asks: tuple[BookLevel, ...]
) -> tuple[int, int] | None:
    """The `(price_scale, qty_scale)` that carry the steps and every level exactly (§3.4), `None`
    past §14.1's 18: checked before any value is scaled by 10**scale."""
    ps = _places(steps[0], (lv.price for lv in (*bids, *asks)))
    qs = _places(steps[1], (lv.qty for lv in (*bids, *asks)))
    return None if ps > _MAX_SCALE or qs > _MAX_SCALE else (ps, qs)


def scaled_records(
    side: int, levels: Iterable[tuple[Decimal, Decimal]], scales: tuple[int, int]
) -> tuple[Record, ...] | None:
    """Kind-1/2 records of `(price, size)` pairs at `scales`, `None` when one is not exact there or
    does not fit its field (a delta's level then needs a resnapshot at wider scales)."""
    ps, qs = scales
    out: list[Record] = []
    for price, size in levels:
        p, q = price.scaleb(ps, _EXACT), size.scaleb(qs, _EXACT)
        if p != p.to_integral_value() or q != q.to_integral_value():
            return None
        rec = (side, int(p), int(q))
        if rec[1] not in _I64 or rec[2] not in _U64:
            return None
        out.append(rec)
    return tuple(out)


def _places(step: Decimal, values: Iterable[Decimal]) -> int:
    """Decimal places that hold `step` and every value exactly."""
    exponents = (v.as_tuple().exponent for v in (step, *values))
    return max(-e if isinstance(e, int) and e < 0 else 0 for e in exponents)


def _rows(levels: tuple[BookLevel, ...]) -> list[list[str]]:
    return [[format(lv.price, "f"), format(lv.qty, "f")] for lv in levels]


def _records(side: int, levels: tuple[BookLevel, ...], ps: int, qs: int) -> tuple[Record, ...]:
    return tuple(
        (side, int(lv.price.scaleb(ps, _EXACT)), int(lv.qty.scaleb(qs, _EXACT))) for lv in levels
    )


def _fits(records: tuple[Record, ...], trailer: tuple[int, int]) -> bool:
    """Every record and trailer value fits its kind-1 field (§3.4)."""
    return all(p in _I64 and q in _U64 for _, p, q in records) and all(x in _U64 for x in trailer)
