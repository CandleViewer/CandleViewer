"""`bars` topic wire forms (E12-T06 slice C, #399; `23-ws-protocol.md` §3.4 kind 4, §6.1, §14.3).

A builder `Bar` becomes a §14.3 `BarsBatch` item (structured) and a kind-4 record (binary). Both
carry the §8.2 bar key `(generation, index)` and `confirm`, which is false for the forming bar.
The kind-4 scales are `price_scale` for `o`, `h`, `l`, `c` and `qty_scale` for `v`, `turnover`
and `delta`. Unless the subscription set `include_delta`, `delta` is 0 in a record and the
structured order-flow fields are omitted. `cvd` is a series running sum that a single bar does not
hold, so it is never sent from here. Pure: no I/O and no state.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Final

from candleviewer.bars.models import Bar
from candleviewer.ws.binary import BARS, Frame

#: `ts_offset_ms` is a u32 (§3.4): a frame holds bars opening at most this long after its base.
MAX_TS_SPAN_MS: Final = 2**32 - 1
#: Bar kinds that open on a clock boundary; every other kind also sends `close_t_ms` (§14.3).
TIME_KINDS: Final = frozenset({"time", "heikin_ashi"})
_CONFIRM: Final = 0b1

Record = tuple[int, ...]


def _dec(value: Decimal) -> str:
    """The `common#/$defs/decimal` form: plain digits, never an exponent."""
    return format(value, "f")


def _scaled(value: Decimal, scale: int) -> int:
    """`value` as an integer of `scale` places, half-even: turnover has more places than qty."""
    return int(value.scaleb(scale).to_integral_value(rounding=ROUND_HALF_EVEN))


def bar_item(
    bar: Bar, *, generation: int, bar_kind: str, include_delta: bool, amended: bool = False
) -> dict[str, Any]:
    """The §14.3 `bars[]` item for `bar`."""
    item: dict[str, Any] = {
        "generation": generation,
        "index": bar.index,
        "t_ms": bar.open_time // 1000,
        "o": _dec(bar.open),
        "h": _dec(bar.high),
        "l": _dec(bar.low),
        "c": _dec(bar.close),
        "v": _dec(bar.volume),
        "turnover": _dec(bar.turnover),
        "trades": bar.trade_count,
        "confirm": bar.closed,
    }
    if bar_kind not in TIME_KINDS:
        item["close_t_ms"] = bar.close_time // 1000
    if amended:
        item["amended"] = True
    if include_delta:
        item["delta"] = _dec(bar.delta)
        item["min_delta"] = _dec(bar.min_delta)
        item["max_delta"] = _dec(bar.max_delta)
    return item


def bar_record(
    bar: Bar,
    *,
    generation: int,
    include_delta: bool,
    price_scale: int,
    qty_scale: int,
    ts_base_ms: int,
) -> Record:
    """The kind-4 record for `bar`, in the layout's field order (`cvwb_layout.KINDS[4]`)."""
    return (
        generation,
        bar.index,
        bar.open_time // 1000 - ts_base_ms,
        _scaled(bar.open, price_scale),
        _scaled(bar.high, price_scale),
        _scaled(bar.low, price_scale),
        _scaled(bar.close, price_scale),
        _scaled(bar.volume, qty_scale),
        _scaled(bar.turnover, qty_scale),
        bar.trade_count,
        _scaled(bar.delta, qty_scale) if include_delta else 0,
        _CONFIRM if bar.closed else 0,
    )


def bars_frames(
    bars: Sequence[Bar],
    *,
    generation: int,
    include_delta: bool,
    price_scale: int,
    qty_scale: int,
) -> tuple[Frame, ...]:
    """Kind-4 frames for `bars` (one generation, in index order): a new frame starts whenever a
    bar's open time does not fit the u32 offset after the current frame's base, which 1 000 daily
    bars exceed. `split_frame` still splits each frame by size."""
    frames: list[Frame] = []
    run: list[Record] = []
    base = 0
    for bar in bars:
        t_ms = bar.open_time // 1000
        if run and not 0 <= t_ms - base <= MAX_TS_SPAN_MS:
            frames.append(_frame(run, base, price_scale, qty_scale))
            run = []
        if not run:
            base = t_ms
        run.append(
            bar_record(
                bar,
                generation=generation,
                include_delta=include_delta,
                price_scale=price_scale,
                qty_scale=qty_scale,
                ts_base_ms=base,
            )
        )
    if run:
        frames.append(_frame(run, base, price_scale, qty_scale))
    return tuple(frames)


def _frame(run: list[Record], base: int, price_scale: int, qty_scale: int) -> Frame:
    return Frame(BARS, tuple(run), price_scale=price_scale, qty_scale=qty_scale, ts_base_ms=base)
