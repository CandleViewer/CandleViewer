"""Volume and order-flow kernels: `vwap`, `cvd`, `volume`, `delta` (E13-T02, #426; 24 §7.4)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Final

from candleviewer.orderflow.indicators.kernel import (
    MINUTE_US,
    Kernel,
    State,
    as_float,
    choice_param,
    session_start,
)
from candleviewer.orderflow.indicators.types import BarInput, KernelContext, Outputs, ParamValue

_NO_VWAP: Outputs = (None,) * 9
_BAND_MULTIPLES = (1.0, 2.0, 3.0)
#: `band_sigma` is undefined while `sigma <= abs(vwap) * SIGMA_FLOOR`: sigma is then rounding
#: noise (bars sharing one typical price that rounds apart), and dividing by it would publish a
#: z-score of 1e13. The literal is exactly 2**-40: far above that noise, far below any real
#: dispersion.
SIGMA_FLOOR: Final = 9.094947017729282e-13


def _optional_int(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise TypeError("expected an integer or null")
    return raw


class VwapKernel(Kernel):
    """Session VWAP of the typical price, with sigma bands from West's weighted variance.

    The session restarts when `session_start(t, anchor)` changes (anchor: the bar spec's session
    anchor): `w_sum = mean = s = 0.0`. A bar with volume `w > 0.0` updates, with
    `x = (high + low + close) / 3.0`:
    `w_sum = w_sum + w`; `d = x - mean`; `mean = mean + (w / w_sum) * d`;
    `s = s + w * d * (x - mean)`, then `s = 0.0` if `s < 0.0`. A zero-volume bar (a `densify()`
    filler too) changes nothing. While `w_sum > 0.0`: `vwap = mean`, `sigma = sqrt(s / w_sum)`,
    `upper_k = vwap + k * sigma` and `lower_k = vwap - k * sigma` for `k` in `1.0, 2.0, 3.0`,
    and `band_sigma = (close - vwap) / sigma` when `sigma > abs(vwap) * SIGMA_FLOOR`.

    VWAP is West's running `mean`, never the quotient of two running sums (the two differ in
    the last bits). `s` is a sum of non-negative terms, but when one bar's volume dwarfs the
    session's (a ratio of about 1e16 or more) and the price moves more than twofold, `mean` can
    round past `x` and the term comes out negative; the clamp keeps `s` a valid variance
    numerator, so sigma stays defined and a snapshot always restores.
    """

    indicator = "vwap"
    outputs = (
        "vwap",
        "sigma",
        "upper_1",
        "lower_1",
        "upper_2",
        "lower_2",
        "upper_3",
        "lower_3",
        "band_sigma",
    )
    build_version = 1
    param_names = ("anchor",)
    sources = ("hlc3",)
    nullable_when = (
        "None until a bar with volume closes in the current session; each session, starting at "
        "the bar spec's session anchor, begins without a value. band_sigma is also None while "
        "sigma is 0 to within rounding (at most |vwap| * 2^-40)."
    )

    def __init__(
        self,
        params: Mapping[str, ParamValue],
        *,
        source: str | None,
        context: KernelContext | None = None,
    ) -> None:
        super().__init__(params, source=source, context=context)
        self._anchor_us = self.anchor_us(params, self._context)
        self._session: int | None = None
        self._w_sum = self._mean = self._s = 0.0

    @classmethod
    def anchor_us(cls, params: Mapping[str, ParamValue], context: KernelContext) -> int:
        choice_param(params, "anchor", ("session",))
        return context.session_anchor_utc_min * MINUTE_US

    @classmethod
    def warmup_bars(cls, params: Mapping[str, ParamValue]) -> int:
        return 1

    def update(self, bar: BarInput) -> Outputs:
        session = session_start(bar.t, self._anchor_us)
        if session != self._session:
            self._session = session
            self._w_sum = self._mean = self._s = 0.0
        w = bar.volume
        if w > 0.0:
            x = (bar.high + bar.low + bar.close) / 3.0
            self._w_sum = self._w_sum + w
            d = x - self._mean
            self._mean = self._mean + (w / self._w_sum) * d
            s = self._s + w * d * (x - self._mean)
            self._s = 0.0 if s < 0.0 else s
        if not self._w_sum > 0.0:
            return _NO_VWAP
        vwap = self._mean
        sigma = math.sqrt(self._s / self._w_sum)
        bands: list[float | None] = []
        for k in _BAND_MULTIPLES:
            bands += [vwap + k * sigma, vwap - k * sigma]
        band_sigma = (bar.close - vwap) / sigma if sigma > abs(vwap) * SIGMA_FLOOR else None
        return (vwap, sigma, *bands, band_sigma)

    def _dump(self) -> State:
        return {
            "session": self._session,
            "w_sum": self._w_sum,
            "mean": self._mean,
            "s": self._s,
        }

    def _load(self, state: State) -> None:
        session = _optional_int(state["session"])
        w_sum, mean, s = as_float(state["w_sum"]), as_float(state["mean"]), as_float(state["s"])
        if w_sum < 0.0 or s < 0.0:
            raise ValueError("weights and the squared-deviation sum are never negative")
        self._session, self._w_sum, self._mean, self._s = session, w_sum, mean, s


class CvdKernel(Kernel):
    """Cumulative volume delta: `cvd = cvd + delta`, restarting from `0.0` when the anchor period
    changes (`session`: the bar spec's session anchor; `utc_day`: 00:00 UTC)."""

    indicator = "cvd"
    outputs = ("cvd",)
    build_version = 1
    param_names = ("anchor",)
    sources = (None,)
    nullable_when = (
        "None only before the first bar; the sum restarts from 0 at each anchor (the session "
        "start, or 00:00 UTC for utc_day)."
    )

    def __init__(
        self,
        params: Mapping[str, ParamValue],
        *,
        source: str | None,
        context: KernelContext | None = None,
    ) -> None:
        super().__init__(params, source=source, context=context)
        self._anchor_us = self.anchor_us(params, self._context)
        self._period: int | None = None
        self._cvd = 0.0

    @classmethod
    def anchor_us(cls, params: Mapping[str, ParamValue], context: KernelContext) -> int:
        anchor = choice_param(params, "anchor", ("session", "utc_day"))
        minutes = context.session_anchor_utc_min if anchor == "session" else 0
        return minutes * MINUTE_US

    @classmethod
    def warmup_bars(cls, params: Mapping[str, ParamValue]) -> int:
        return 1

    def update(self, bar: BarInput) -> Outputs:
        period = session_start(bar.t, self._anchor_us)
        if period != self._period:
            self._period = period
            self._cvd = 0.0
        self._cvd = self._cvd + bar.delta
        return (self._cvd,)

    def _dump(self) -> State:
        return {"period": self._period, "cvd": self._cvd}

    def _load(self, state: State) -> None:
        period, cvd = _optional_int(state["period"]), as_float(state["cvd"])
        self._period, self._cvd = period, cvd


class _PassThrough(Kernel):
    """A stateless kernel publishing one bar field as is."""

    build_version = 1
    param_names = ()
    sources = (None,)

    @classmethod
    def warmup_bars(cls, params: Mapping[str, ParamValue]) -> int:
        return 1

    def _dump(self) -> State:
        return {}

    def _load(self, state: State) -> None:
        if state:
            raise ValueError("a pass-through kernel has no state")


class VolumeKernel(_PassThrough):
    """The bar's volume (the `bar_volume` metric of the `volume` indicator)."""

    indicator = "volume"
    outputs = ("volume",)
    nullable_when = "None only before the first bar; each value is that bar's volume."

    def update(self, bar: BarInput) -> Outputs:
        return (bar.volume,)


class DeltaKernel(_PassThrough):
    """The bar's aggressor delta, `buy_volume - sell_volume` (the `delta` metric)."""

    indicator = "delta"
    outputs = ("delta",)
    nullable_when = "None only before the first bar; each value is that bar's delta."

    def update(self, bar: BarInput) -> Outputs:
        return (bar.delta,)
