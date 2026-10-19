"""Indicator kernel framework (E13-T02, #426; ADR-0034; 24-internal-schemas §7.4).

A kernel is one scalar float64 fold over a bar series. `update(bar)` takes the next closed bar
and returns one value per declared output; `run(bars)` and `kernels.compute()` are the same fold
over a window, so there is one implementation, not two. The state is plain numbers, so
`snapshot()` / `restore()` resume a series bit-identically after a restart or a replay seek.

Parity contract (ADR-0034 rule 3). The TS worker mirror follows it operation for operation:

- IEEE-754 binary64 only. The operations are `+ - * / sqrt min max floor` and comparisons, each
  correctly rounded or exact; `abs(x)` is `max(x, -x)`, which is exact. No `pow`, `exp` or
  `log`, and no reassociated (prefix-sum, pairwise) or one-pass-variance forms.
- Each expression is evaluated left to right exactly as its kernel's docstring writes it.
  Integers (`n`, `n - 1`) convert to binary64 exactly.
- A value is `None` until it is defined, never 0 and never NaN; `nullable_when` says when.
  ADX is the one exception (`AdxKernel`): with no range its DIs and DX read 0, not `None`.
- A zero produced by a branch is `+0.0` (never `max(-0.0, 0.0)`), so the sign of zero agrees.
- Every kernel carries a `build_version`. Changing an operation or its order bumps it,
  regenerates `packages/fixtures/golden/indicators/` and re-pins the kernel's output digest
  beside its `build_version` in `tests/unit/orderflow/indicators/test_golden_vectors.py`. The
  pin fails on any changed output, so the bump is a reviewed diff (IR-20).

Shared recurrences:

- Wilder smoothing (`WilderAverage`; ATR, RSI, ADX): seed `acc / n`, where `acc` sums the
  first `n` inputs left to right from `0.0`; then `v = (v * (n - 1) + x) / n`.
- EMA (`ExponentialAverage`): the same seed, `alpha = 2 / (n + 1)`, then
  `v = (x - v) * alpha + v`.

State blob: orjson JSON `{v, indicator, build_version, params, source, context, state}` with
`v = STATE_VERSION`; `params` are canonical (`identity`), `source` is the price the kernel
reads (`sources`), `context` the `KernelContext`. `restore()` refuses a blob whose header
differs from the kernel in any field (`IndicatorStateError`) and replaces the state only once
the whole blob has parsed.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import ClassVar, Final

import orjson

from candleviewer.orderflow.errors import IndicatorParamError, IndicatorStateError
from candleviewer.orderflow.indicators.identity import CanonicalValue, canonical_params
from candleviewer.orderflow.indicators.types import (
    BarInput,
    KernelContext,
    Outputs,
    ParamValue,
)

STATE_VERSION: Final = 1
DAY_US: Final = 86_400_000_000
MINUTE_US: Final = 60_000_000

type State = dict[str, object]


def int_param(params: Mapping[str, ParamValue], name: str, *, minimum: int = 1) -> int:
    """A whole-number parameter: an `int`, or an integral float or Decimal (`21.0` is 21)."""
    value = params.get(name)
    rule = f"{name} must be a whole number of at least {minimum}."
    if isinstance(value, float) and value.is_integer():
        n = int(value)
    elif isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value():
        n = int(value)
    elif isinstance(value, int) and not isinstance(value, bool):
        n = value
    else:
        raise IndicatorParamError(rule)
    if n < minimum:
        raise IndicatorParamError(rule)
    return n


def number_param(params: Mapping[str, ParamValue], name: str, *, minimum: float = 0.0) -> float:
    """A finite real parameter, read as binary64 (`float(Decimal)` is correctly rounded)."""
    value = params.get(name)
    rule = f"{name} must be a finite number of at least {minimum:g}."
    if isinstance(value, Decimal) and value.is_finite():
        number = float(value)
    elif isinstance(value, int | float) and not isinstance(value, bool):
        number = float(value)
    else:
        raise IndicatorParamError(rule)
    if not math.isfinite(number) or number < minimum:
        raise IndicatorParamError(rule)
    return number


def choice_param(params: Mapping[str, ParamValue], name: str, choices: tuple[str, ...]) -> str:
    """An enum parameter."""
    value = params.get(name)
    if not isinstance(value, str) or value not in choices:
        raise IndicatorParamError(f"{name} must be one of: {', '.join(choices)}.")
    return value


def session_start(t: int, anchor_us: int) -> int:
    """Start (µs) of the 24 h period holding `t` when periods start at `anchor_us` past 00:00
    UTC: `floor((t - anchor_us) / DAY_US) * DAY_US + anchor_us`, in exact integer arithmetic."""
    return (t - anchor_us) // DAY_US * DAY_US + anchor_us


def as_float(raw: object) -> float:
    """A state number; orjson writes floats with a fraction or exponent, ints as integers."""
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise TypeError("expected a number")
    return float(raw)


def as_optional_float(raw: object) -> float | None:
    return None if raw is None else as_float(raw)


def as_count(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise TypeError("expected a count")
    return raw


def as_float_list(raw: object) -> list[float]:
    if not isinstance(raw, list):
        raise TypeError("expected a list")
    return [as_float(x) for x in raw]


def as_state(raw: object) -> State:
    if not isinstance(raw, dict):
        raise TypeError("expected an object")
    return raw


class _SeededAverage(ABC):
    """Shared seed: the mean of the first `n` inputs, summed left to right from `0.0`."""

    __slots__ = ("_acc", "_k", "_n", "value")

    def __init__(self, n: int) -> None:
        self._n = n
        self._k = 0
        self._acc = 0.0
        self.value: float | None = None

    def update(self, x: float) -> float | None:
        if self.value is None:
            self._acc = self._acc + x
            self._k += 1
            if self._k == self._n:
                self.value = self._acc / self._n
            return self.value
        self.value = self._step(self.value, x)
        return self.value

    @abstractmethod
    def _step(self, v: float, x: float) -> float: ...

    def dump(self) -> list[object]:
        return [self._k, self._acc, self.value]

    def load(self, raw: object) -> None:
        """Replace the state with `raw` (a fresh instance's job: parse, then assign)."""
        if not isinstance(raw, list) or len(raw) != 3:
            raise TypeError("expected [k, acc, value]")
        k, acc, value = as_count(raw[0]), as_float(raw[1]), as_optional_float(raw[2])
        if k > self._n or (value is None) != (k < self._n):
            raise ValueError("inconsistent average state")
        self._k, self._acc, self.value = k, acc, value


class WilderAverage(_SeededAverage):
    """Wilder smoothing: `v = (v * (n - 1) + x) / n` after the seed."""

    __slots__ = ()

    def _step(self, v: float, x: float) -> float:
        return (v * (self._n - 1) + x) / self._n


class ExponentialAverage(_SeededAverage):
    """EMA: `v = (x - v) * alpha + v` after the seed, with `alpha = 2 / (n + 1)`."""

    __slots__ = ("_alpha",)

    def __init__(self, n: int) -> None:
        super().__init__(n)
        self._alpha = 2 / (n + 1)

    def _step(self, v: float, x: float) -> float:
        return (x - v) * self._alpha + v


class Kernel(ABC):
    """Base of every server kernel. Subclasses declare their identity as class attributes."""

    indicator: ClassVar[str]
    outputs: ClassVar[tuple[str, ...]]
    build_version: ClassVar[int]
    param_names: ClassVar[tuple[str, ...]]
    #: The price the kernel reads (`close`, `hlc3`), or `None` for fixed bar fields; `sources[0]`
    #: is the default. A check on the caller, never part of the identity: `spec_hash` hashes the
    #: bar source `tape` (`identity.BAR_SOURCE`, 24 §7.4).
    sources: ClassVar[tuple[str | None, ...]]
    nullable_when: ClassVar[str]

    def __init__(
        self,
        params: Mapping[str, ParamValue],
        *,
        source: str | None,
        context: KernelContext | None = None,
    ) -> None:
        if any(k not in self.param_names for k in params):  # never echo the key (IR-24)
            raise IndicatorParamError(f"{self.indicator} was given an undeclared parameter.")
        missing = [k for k in self.param_names if k not in params]
        if missing:
            raise IndicatorParamError(f"{self.indicator} needs the parameter {missing[0]}.")
        if source not in self.sources:
            raise IndicatorParamError(f"{self.indicator} does not accept that source.")
        self._canonical: dict[str, CanonicalValue] = canonical_params(params)
        self._source = source
        self._context = context if context is not None else KernelContext()

    @classmethod
    @abstractmethod
    def warmup_bars(cls, params: Mapping[str, ParamValue]) -> int:
        """Bars needed before the first output (`outputs[0]`) can be defined: its first value is
        at index `warmup_bars - 1` at the earliest. Each output is `None` exactly when
        `nullable_when` says."""

    @abstractmethod
    def update(self, bar: BarInput) -> Outputs:
        """Fold in the next closed bar; returns one value per entry of `outputs`."""

    @abstractmethod
    def _dump(self) -> State:
        """The kernel state as JSON-ready numbers."""

    @abstractmethod
    def _load(self, state: State) -> None:
        """Parse `state` completely, then replace the kernel state; raise on any defect."""

    def run(self, bars: Iterable[BarInput]) -> list[Outputs]:
        """The same fold over a window."""
        return [self.update(bar) for bar in bars]

    def _header(self) -> State:
        return {
            "v": STATE_VERSION,
            "indicator": self.indicator,
            "build_version": self.build_version,
            "params": dict(self._canonical),
            "source": self._source,
            "context": {"session_anchor_utc_min": self._context.session_anchor_utc_min},
        }

    def snapshot(self) -> bytes:
        return orjson.dumps({**self._header(), "state": self._dump()})

    def restore(self, blob: bytes) -> None:
        try:
            doc = orjson.loads(blob)
        except orjson.JSONDecodeError as exc:
            raise IndicatorStateError("The state blob is not valid JSON.") from exc
        if not isinstance(doc, dict):
            raise IndicatorStateError("The state blob is not a JSON object.")
        for key, want in self._header().items():
            got = orjson.dumps(doc.get(key), option=orjson.OPT_SORT_KEYS)
            if got != orjson.dumps(want, option=orjson.OPT_SORT_KEYS):
                raise IndicatorStateError(f"The state blob's {key} does not match this kernel.")
        try:
            self._load(as_state(doc.get("state")))
        except (TypeError, ValueError, KeyError, IndexError) as exc:
            raise IndicatorStateError(f"The {self.indicator} state is malformed.") from exc
