"""`bars` topic wire forms (E12-T06 slice C, #399; `23-ws-protocol.md` §3.4 kind 4, §6.1, §14.3).

A builder `Bar` becomes a §14.3 `BarsBatch` item (structured) and a kind-4 record (binary). Both
carry the §8.2 bar key `(generation, index)` and `confirm`, which is false for the forming bar.
The kind-4 scales are `price_scale` for `o`, `h`, `l`, `c` and `qty_scale` for `v`, `turnover`
and `delta`. Unless the subscription set `include_delta`, `delta` is 0 in a record and the
structured order-flow fields are omitted. `cvd` is a series running sum that a single bar does not
hold, so it is never sent from here. Pure: no I/O and no state.

Every scaled field but `turnover` must be exact at its scale: a price or size finer than the scale
is refused with `FrameEncodeError`, never rounded, so the binary and structured twins carry the
same value (§16.4). `turnover` (price x qty) has more places than qty and is rounded half-even.
`covering_scales` gives scales that hold a whole history exactly, including bars recorded before a
tick or qty-step coarsening. A value outside its field's range, a value that is not finite (in
either form), a negative key, a `densify()` filler (never sent on the wire,
`24-internal-schemas.md` §3.1) and an amended forming bar are refused the same way. The checks run
in a private decimal context, so the caller's precision never rounds a value into passing.
Heikin-ashi values are averages, not traded prices: an HA producer must quantise them to the
instrument tick before they reach this module, or the contract must give HA its own rounding rule.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import MAX_EMAX, MAX_PREC, MIN_EMIN, ROUND_HALF_EVEN, Context, Decimal
from typing import Any, Final

from candleviewer.bars.models import Bar
from candleviewer.bars.spec import WireBarType
from candleviewer.ws._generated.cvwb_layout import KINDS
from candleviewer.ws.binary import BARS, Frame, FrameEncodeError, Record

_RANGES: Final = {
    "B": (0, 2**8 - 1),
    "I": (0, 2**32 - 1),
    "Q": (0, 2**64 - 1),
    "q": (-(2**63), 2**63 - 1),
}
_LAYOUT: Final = KINDS[BARS].record
#: Each kind-4 record field with its inclusive range, from the generated layout (`<QQIqqqqQQIqB4x`).
_BOUNDS: Final = tuple(
    zip(_LAYOUT.fields, [_RANGES[c] for c in _LAYOUT.fmt if c in _RANGES], strict=True)
)
#: `ts_offset_ms` is a u32 (§3.4): a frame holds bars opening at most this long after its base.
MAX_TS_SPAN_MS: Final = dict(_BOUNDS)["ts_offset_ms"][1]
#: Bar kinds that open on a clock boundary; every other kind also sends `close_t_ms` (§14.3).
#: `heikin_ashi` is a wire name only (§6.1): no builder produces it yet.
TIME_KINDS: Final[frozenset[WireBarType]] = frozenset({"time", "heikin_ashi"})
_CONFIRM: Final = 0b1
#: Exact arithmetic whatever the caller's context: every field explicit, no rounding below the
#: maximum precision, no traps. Read-only, and only for `scaleb`/`normalize`/`to_integral_value`:
#: never for division or powers, where `MAX_PREC` would allocate.
_EXACT: Final = Context(
    prec=MAX_PREC, rounding=ROUND_HALF_EVEN, Emin=MIN_EMIN, Emax=MAX_EMAX, capitals=1, clamp=0,
    flags=[], traps=[],
)  # fmt: skip
#: A scaled value at or above 10**20 fits no 64-bit field; refused before `int()` would build it.
_MAX_ADJUSTED: Final = 19
#: The structured twin's ceiling: no bar value reaches 10**39, and `format(.., "f")` grows with the
#: exponent.
_MAX_DEC_ADJUSTED: Final = 38


def _key(bar: Bar, generation: int) -> str:
    return f"bars ({generation}, {bar.index})"


def _sendable(bar: Bar, generation: int) -> None:
    if bar.synthetic:
        raise FrameEncodeError(f"{_key(bar, generation)} is a densify() filler: never on the wire")
    if min(generation, bar.index, bar.trade_count, bar.open_time, bar.close_time) < 0:
        fields = (("generation", generation), ("index", bar.index),
                  ("trade_count", bar.trade_count), ("open_time", bar.open_time),
                  ("close_time", bar.close_time))  # fmt: skip
        name, value = next((n, v) for n, v in fields if v < 0)
        raise _refuse(bar, generation, name, value, "is negative")


def _open_ms(bar: Bar) -> int:
    """`t_ms`: the open time floored to the millisecond (builders keep microseconds)."""
    return bar.open_time // 1000


def _refuse(bar: Bar, generation: int, field: str, value: object, why: str) -> FrameEncodeError:
    """The error, formatted only on failure: the per-record path builds no strings."""
    return FrameEncodeError(f"{_key(bar, generation)}: {field} {value} {why}")


def _dec(value: Decimal, bar: Bar, generation: int, field: str) -> str:
    """The `common#/$defs/decimal` form: plain digits, never an exponent and never `-0`."""
    if not value.is_finite():
        raise _refuse(bar, generation, field, value, "is not finite")
    if value and value.adjusted() > _MAX_DEC_ADJUSTED:
        raise _refuse(bar, generation, field, value, "is too large to send")
    return format(value if value else value.copy_abs(), "f")


def _places(value: Decimal) -> int:
    """The decimal places `value` needs: `100.10` needs 1 and `1E+2` needs none."""
    if not value.is_finite():
        return 0  # `_scaled` refuses it
    exponent = value.normalize(_EXACT).as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def _scaled(
    value: Decimal, scale: int, bar: Bar, generation: int, field: str, *, exact: bool = True
) -> int:
    """`value` as an integer of `scale` places: exact, or half-even when `exact` is off."""
    if not value.is_finite():
        raise _refuse(bar, generation, field, value, "is not finite")
    scaled = value.scaleb(scale, _EXACT)
    if not scaled.is_finite() or (scaled and scaled.adjusted() > _MAX_ADJUSTED):
        raise _refuse(bar, generation, field, value, f"overflows every field at scale {scale}")
    whole = scaled.to_integral_value(ROUND_HALF_EVEN, _EXACT)
    if exact and whole != scaled:
        raise _refuse(bar, generation, field, value, f"is not exact at scale {scale}")
    return int(whole)


def covering_scales(bars: Iterable[Bar], *, price_scale: int, qty_scale: int) -> tuple[int, int]:
    """The scales, no coarser than the instrument's, that hold every price and size of `bars`
    exactly. Pass the same pair to `bars_frames` and to the `SnapshotBody`."""
    for bar in bars:
        prices = (bar.open, bar.high, bar.low, bar.close)
        price_scale = max(price_scale, *map(_places, prices))
        qty_scale = max(qty_scale, _places(bar.volume), _places(bar.delta))
    return price_scale, qty_scale


def bar_item(
    bar: Bar,
    *,
    generation: int,
    bar_kind: WireBarType,
    include_delta: bool,
    amended: bool = False,
) -> dict[str, Any]:
    """The §14.3 `bars[]` item for `bar`."""
    _sendable(bar, generation)
    if amended and not bar.closed:
        raise FrameEncodeError(f"{_key(bar, generation)}: only a closed bar is amended (§8.2)")
    item: dict[str, Any] = {
        "generation": generation,
        "index": bar.index,
        "t_ms": _open_ms(bar),
        "o": _dec(bar.open, bar, generation, "open"),
        "h": _dec(bar.high, bar, generation, "high"),
        "l": _dec(bar.low, bar, generation, "low"),
        "c": _dec(bar.close, bar, generation, "close"),
        "v": _dec(bar.volume, bar, generation, "volume"),
        "turnover": _dec(bar.turnover, bar, generation, "turnover"),
        "trades": bar.trade_count,
        "confirm": bar.closed,
    }
    if bar_kind not in TIME_KINDS:
        item["close_t_ms"] = bar.close_time // 1000
    if amended:
        item["amended"] = True
    if include_delta:
        item["delta"] = _dec(bar.delta, bar, generation, "delta")
        item["min_delta"] = _dec(bar.min_delta, bar, generation, "min_delta")
        item["max_delta"] = _dec(bar.max_delta, bar, generation, "max_delta")
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
    _sendable(bar, generation)
    g = generation
    record = (
        generation,
        bar.index,
        _open_ms(bar) - ts_base_ms,
        _scaled(bar.open, price_scale, bar, g, "open"),
        _scaled(bar.high, price_scale, bar, g, "high"),
        _scaled(bar.low, price_scale, bar, g, "low"),
        _scaled(bar.close, price_scale, bar, g, "close"),
        _scaled(bar.volume, qty_scale, bar, g, "volume"),
        _scaled(bar.turnover, qty_scale, bar, g, "turnover", exact=False),
        bar.trade_count,
        _scaled(bar.delta, qty_scale, bar, g, "delta") if include_delta else 0,
        _CONFIRM if bar.closed else 0,
    )
    for (name, (low, high)), value in zip(_BOUNDS, record, strict=True):
        if not low <= value <= high:
            raise _refuse(bar, g, name, value, f"is outside [{low}, {high}]")
    return record


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
    bars exceed. A snapshot sends each frame as its own `partial` chunk; a delta batch can need
    more than one frame too. `split_frame` still splits each frame by size. `SnapshotBody` scales
    must equal these: `render` stamps the body's scales on every part."""
    frames: list[Frame] = []
    run: list[Record] = []
    base = 0
    for bar in bars:
        t_ms = _open_ms(bar)
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
