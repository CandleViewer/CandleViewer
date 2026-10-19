"""Trend kernels: `zigzag`, the confirmed swing pivots (E13-T02; plan §3.3, D11)."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping

from candleviewer.orderflow.indicators.kernel import (
    Kernel,
    State,
    as_count,
    as_float,
    as_float_list,
    as_optional_float,
    int_param,
    number_param,
)
from candleviewer.orderflow.indicators.types import BarInput, KernelContext, Outputs, ParamValue


class _Extremum:
    """Maximum (or minimum) of the values pushed at the last `size` indices: a monotonic deque
    of `[index, value]`, O(1) amortised per push. Selections are exact, so the result does not
    depend on the algorithm."""

    __slots__ = ("_highest", "_items", "_size")

    def __init__(self, size: int, *, highest: bool) -> None:
        self._size = size
        self._highest = highest
        self._items: deque[tuple[int, float]] = deque()

    def push(self, index: int, x: float) -> None:
        items = self._items
        while items and (items[-1][1] <= x if self._highest else items[-1][1] >= x):
            items.pop()
        items.append((index, x))
        while items[0][0] <= index - self._size:
            items.popleft()

    def value(self) -> float:
        return self._items[0][1]

    def dump(self) -> list[list[float]]:
        return [[i, x] for i, x in self._items]

    def load(self, raw: object, next_index: int) -> None:
        if not isinstance(raw, list) or len(raw) > self._size:
            raise TypeError("expected at most `size` entries")
        items: deque[tuple[int, float]] = deque()
        for entry in raw:
            if not isinstance(entry, list) or len(entry) != 2:
                raise TypeError("expected [index, value]")
            index, x = as_count(entry[0]), as_float(entry[1])
            if index >= next_index or (items and index <= items[-1][0]):
                raise ValueError("deque indices must increase and precede the next bar")
            items.append((index, x))
        self._items = items


class ZigzagKernel(Kernel):
    """Confirmed swing highs and lows: Zig Zag without its provisional leg.

    Bar `c` is a pivot high when its high is strictly above each of the `depth` highs before it
    and at or above each of the `depth` highs after it (a flat top keeps its first bar); a pivot
    low mirrors this with lows. A pivot is confirmed at bar `c + depth`, so a published swing
    never repaints. It is accepted when no swing of the other kind exists yet, or when
    `abs(p - other) * 100.0 >= deviation_pct * other`, `other` being the last accepted swing of
    the other kind; on one bar the high is tested before the low. The outputs carry the last
    accepted `swing_high` and `swing_low`. With `deviation_pct = 0` every pivot is accepted,
    which is the "n bars either side" swing of 24-internal-schemas §7.2.
    """

    indicator = "zigzag"
    outputs = ("swing_high", "swing_low")
    build_version = 1
    param_names = ("depth", "deviation_pct")
    sources = (None,)
    nullable_when = (
        "swing_high (swing_low) is None until a pivot high (low) is confirmed: that needs at "
        "least 2*depth+1 bars and a bar whose high is above the depth highs before it and not "
        "below the depth highs after it (lows: below, and not above), moving at least "
        "deviation_pct percent away from the last swing of the other kind."
    )

    def __init__(
        self,
        params: Mapping[str, ParamValue],
        *,
        source: str | None,
        context: KernelContext | None = None,
    ) -> None:
        super().__init__(params, source=source, context=context)
        self._depth = int_param(params, "depth")
        self._deviation = number_param(params, "deviation_pct")
        self._reset()

    def _reset(self) -> None:
        d = self._depth
        self._j = 0
        self._highs: deque[float] = deque(maxlen=d + 2)  # bars j-d-1 .. j
        self._lows: deque[float] = deque(maxlen=d + 2)
        self._before_max = _Extremum(d, highest=True)  # bars c-d .. c-1
        self._before_min = _Extremum(d, highest=False)
        self._after_max = _Extremum(d, highest=True)  # bars c+1 .. c+d
        self._after_min = _Extremum(d, highest=False)
        self._swing_high: float | None = None
        self._swing_low: float | None = None

    @classmethod
    def warmup_bars(cls, params: Mapping[str, ParamValue]) -> int:
        return 2 * int_param(params, "depth") + 1

    def _clears(self, p: float, other: float | None) -> bool:
        return other is None or abs(p - other) * 100.0 >= self._deviation * other

    def update(self, bar: BarInput) -> Outputs:
        d, j = self._depth, self._j
        self._highs.append(bar.high)
        self._lows.append(bar.low)
        self._after_max.push(j, bar.high)
        self._after_min.push(j, bar.low)
        if j > d:  # bar j-d-1 moves into the window before the centre c = j-d
            self._before_max.push(j - d - 1, self._highs[0])
            self._before_min.push(j - d - 1, self._lows[0])
        if j >= 2 * d:
            high, low = self._highs[1], self._lows[1]
            if (
                high > self._before_max.value()
                and high >= self._after_max.value()
                and self._clears(high, self._swing_low)
            ):
                self._swing_high = high
            if (
                low < self._before_min.value()
                and low <= self._after_min.value()
                and self._clears(low, self._swing_high)
            ):
                self._swing_low = low
        self._j = j + 1
        return (self._swing_high, self._swing_low)

    def _dump(self) -> State:
        return {
            "j": self._j,
            "highs": list(self._highs),
            "lows": list(self._lows),
            "extrema": [
                e.dump()
                for e in (self._before_max, self._before_min, self._after_max, self._after_min)
            ],
            "swings": [self._swing_high, self._swing_low],
        }

    def _load(self, state: State) -> None:
        j = as_count(state["j"])
        highs, lows = as_float_list(state["highs"]), as_float_list(state["lows"])
        if not len(highs) == len(lows) == min(j, self._depth + 2):
            raise ValueError("the bar ring does not match the bar count")
        extrema, swings = state["extrema"], state["swings"]
        if not isinstance(extrema, list) or len(extrema) != 4:
            raise TypeError("expected four extrema")
        if not isinstance(swings, list) or len(swings) != 2:
            raise TypeError("expected [swing_high, swing_low]")
        loaded = [_Extremum(self._depth, highest=h) for h in (True, False, True, False)]
        for extremum, raw in zip(loaded, extrema, strict=True):
            extremum.load(raw, j)
        swing_high, swing_low = as_optional_float(swings[0]), as_optional_float(swings[1])
        self._reset()
        self._j = j
        self._highs.extend(highs)
        self._lows.extend(lows)
        self._before_max, self._before_min, self._after_max, self._after_min = loaded
        self._swing_high, self._swing_low = swing_high, swing_low
