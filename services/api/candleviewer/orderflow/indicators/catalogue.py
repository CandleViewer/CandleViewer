"""The v1 indicator catalogue: one definition per indicator (E13-T02, #426; ADR-0034 and the
assignment table of `docs/plan/spikes/e13-o4.md` §5; 24-internal-schemas §7.1; 22-api-openapi
`IndicatorDescriptor`).

`GET /api/v1/indicators` serves whatever `IndicatorCatalogue` it is given, in its order, so
registering a definition changes the response with no frontend release. The rule vocabulary
(M15) derives its kernel-backed metric rows from `SERVER_DEFINITIONS`, so the indicator list
and the rule vocabulary cannot drift.

- `compute` is derived, never requested (IR-41): `server` exactly when the definition carries
  its backend kernel. ADR-0034 assigns that set by rule eligibility: `sma`, `ema`, `rsi`, `atr`,
  `adx`, `vwap`, `cvd`, `volume` and `zigzag`. The other 19 v1 indicators are `client_worker`
  and have no Python kernel (#426): E13-S02..S07 build theirs in the chart worker.
- A server definition takes its outputs, `nullable_when` and warmup from its kernel and must
  declare the kernel's parameters, so the descriptor cannot disagree with what is computed.
- Every parameter has a type, a title and a default; a numeric one also a minimum and a maximum
  from `limits.py`, and a step (`multipleOf`) when it is fractional (SR-E13-01).
  `params_schema()` is the closed JSON Schema subset a client renders (SR-E13-09): `type`,
  `title`, `default`, `minimum`, `maximum`, `multipleOf` and `enum`, with
  `additionalProperties: false` and no `required`: an absent parameter takes its default
  (23 §6.1).
- `validate_params()` is the server's check of a parameter object: a value outside its bounds
  or off its step is refused, never clamped. The error names a JSON pointer into the public
  `params_schema` and the bound, never the rejected value or an undeclared key (IR-24). The
  step is decimal: it is checked in `Decimal` on the value's shortest repr, so `0.3` is a
  multiple of `0.1` although `0.3 / 0.1` is not 3 in binary64. A stock JSON Schema validator
  divides in binary64 and refuses such legal values (jsonschema does, and so does Ajv without
  `multipleOfPrecision`), so a client checks `multipleOf` in decimal (24 §7.4) and the server
  checks parameters only with `validate_params`.
- `warmup_bars` is the number of closed bars `outputs[0]` needs, as the kernels count it: its
  first value is on bar `warmup_bars` (index `warmup_bars - 1`) at the earliest (24 §7.4).
- `unit` is the unit of every output that does not name its own (`OutputSpec.unit`): `vwap`'s
  `band_sigma` is a z-score and `supertrend`'s `direction` (+1 up, -1 down) a ratio.
  `GET /indicators` serves `unit` only when every output shares it, as 22's
  `IndicatorDescriptor.unit` ("every output's unit") reads, so it omits it for those two; the
  rule vocabulary takes a kernel-bound metric's unit from the output it reads. `rsi` is `pct`
  and `adx` `ratio`, the units the rule vocabulary has given them since E35-T03 (a unit change
  would change which rules validate); the client_worker 0..100 oscillators follow `adx`.
- Defaults chosen here: `sma` 20 (the Bollinger middle line's period and the spike's control
  kernel) and `ema` 21 (US-IND-001's example and a 21 §10.5 built-in preset); the rest of the
  moving-average family 20. `zigzag` defaults to depth 5 with no deviation, which is exactly
  24 §7.2's `swing_high`/`swing_low` (a pivot with 5 bars either side), so the rule metrics keep
  their meaning. Other defaults are the common charting ones; E13-S02..S07 may revise theirs.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Final, Literal

from candleviewer.orderflow.errors import DuplicateIndicatorError, InvalidParamsError
from candleviewer.orderflow.indicators.kernel import Kernel, int_param
from candleviewer.orderflow.indicators.kernels import (
    AdxKernel,
    AtrKernel,
    CvdKernel,
    DeltaKernel,
    EmaKernel,
    RsiKernel,
    SmaKernel,
    VolumeKernel,
    VwapKernel,
    ZigzagKernel,
)
from candleviewer.orderflow.indicators.limits import (
    DEVIATION_PCT_MAX,
    DEVIATION_PCT_MIN,
    DEVIATION_PCT_STEP,
    MULTIPLIER_MAX,
    MULTIPLIER_MIN,
    MULTIPLIER_STEP,
    PERIOD_MAX,
    PERIOD_MIN,
    PSAR_ACCELERATION_MAX,
    PSAR_ACCELERATION_MIN,
    PSAR_ACCELERATION_STEP,
)
from candleviewer.orderflow.indicators.types import ParamValue

Category = Literal["trend", "momentum", "volatility", "volume", "orderflow"]
Pane = Literal["price", "sub", "both"]
Compute = Literal["client_worker", "server"]
#: 24-internal-schemas §7.1 `unit`.
Unit = Literal[
    "price", "qty", "notional", "ratio", "pct", "bps", "count", "ms", "zscore", "enum", "bool"
]
ParamType = Literal["integer", "number", "string"]

type Param = int | Decimal | str
"""A validated parameter value: `int` for an integer, an exact `Decimal` for a fractional
number, `str` for an enum."""

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
type Warmup = Callable[[Mapping[str, ParamValue]], int]

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _json_number(x: int | Decimal) -> int | float:
    """A bound or default as a JSON number: integral values as integers."""
    if isinstance(x, int):
        return x
    return int(x) if x == x.to_integral_value() else float(x)


@dataclass(frozen=True, slots=True)
class ParamSpec:
    """One parameter of a definition: its `params_schema` property and its validation rule."""

    name: str
    title: str
    type: ParamType
    default: Param
    minimum: int | Decimal | None = None
    maximum: int | Decimal | None = None
    multiple_of: Decimal | None = None
    enum: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _NAME.fullmatch(self.name):
            raise ValueError(f"parameter name {self.name!r} is not a lowercase identifier")
        if self.type == "string":
            if not self.enum or self.default not in self.enum or self.minimum is not None:
                raise ValueError(f"{self.name}: a string parameter is an enum holding its default")
            return
        if self.enum or self.minimum is None or self.maximum is None:
            raise ValueError(f"{self.name}: a numeric parameter needs a minimum and a maximum")
        if (self.type == "integer") != (self.multiple_of is None):
            raise ValueError(f"{self.name}: a step is required exactly when it is fractional")
        try:
            checked = _checked(self, self.default)
        except InvalidParamsError as exc:
            raise ValueError(f"{self.name}: the default is invalid: {exc}") from None
        if type(checked) is not type(self.default) or checked != self.default:
            raise ValueError(f"{self.name}: the default must already be canonical")

    def schema(self) -> dict[str, JsonValue]:
        """This parameter's `params_schema` property, in the closed subset (SR-E13-09)."""
        out: dict[str, JsonValue] = {"type": self.type, "title": self.title}
        if self.enum:
            out["enum"] = list(self.enum)
        if self.minimum is not None and self.maximum is not None:
            out["minimum"] = _json_number(self.minimum)
            out["maximum"] = _json_number(self.maximum)
        if self.multiple_of is not None:
            out["multipleOf"] = _json_number(self.multiple_of)
        out["default"] = self.json_default()
        return out

    def json_default(self) -> JsonValue:
        return self.default if isinstance(self.default, str) else _json_number(self.default)


@dataclass(frozen=True, slots=True)
class OutputSpec:
    """One output series: `id` in the order the kernel emits it, `name` the screen-reader
    label (22 `IndicatorOutput`), and `unit` when it differs from its indicator's."""

    id: str
    name: str
    unit: Unit | None = None

    def __post_init__(self) -> None:
        if not _NAME.fullmatch(self.id) or not self.name:
            raise ValueError(f"output {self.id!r} needs a lowercase id and a name")


@dataclass(frozen=True, slots=True)
class IndicatorDef:
    """One v1 indicator: the 24 §7.1 descriptor fields plus `category`, `pane`, `outputs` and,
    for the server set only, its `kernel`. Every v1 indicator reads closed bars once per bar
    close, deterministically, so `value_type`, `scope`, `inputs`, `cadence`, `deterministic`
    and `confidence` take one value each today; no v1 output is a heuristic."""

    id: str
    title: str
    category: Category
    pane: Pane
    unit: Unit
    outputs: tuple[OutputSpec, ...]
    params: tuple[ParamSpec, ...]
    nullable_when: str
    warmup: Warmup
    kernel: type[Kernel] | None = None
    value_type: Literal["number"] = "number"
    scope: Literal["symbol"] = "symbol"
    inputs: tuple[Literal["bars"], ...] = ("bars",)
    cadence: Literal["on_bar_close"] = "on_bar_close"
    deterministic: bool = True
    confidence: Literal["exact", "estimated"] = "exact"

    def __post_init__(self) -> None:
        if not _NAME.fullmatch(self.id) or not self.title or not self.nullable_when:
            raise ValueError(f"indicator {self.id!r} needs a lowercase id, a title and prose")
        if not self.outputs or len({o.id for o in self.outputs}) != len(self.outputs):
            raise ValueError(f"{self.id}: outputs must be non-empty and unique")
        if len({p.name for p in self.params}) != len(self.params):
            raise ValueError(f"{self.id}: a parameter is declared twice")
        kernel = self.kernel
        if kernel is not None and (
            kernel.indicator != self.id
            or kernel.outputs != tuple(o.id for o in self.outputs)
            or kernel.param_names != tuple(p.name for p in self.params)
            or kernel.nullable_when != self.nullable_when
        ):
            raise ValueError(f"{self.id}: the definition disagrees with its kernel")
        if self.warmup_bars() < 1:
            raise ValueError(f"{self.id}: a value needs at least one bar")

    @property
    def compute(self) -> Compute:
        """Where the indicator is computed, from the definition alone (ADR-0034, IR-41)."""
        return "server" if self.kernel is not None else "client_worker"

    @property
    def estimated(self) -> bool:
        return self.confidence == "estimated"

    def defaults(self) -> dict[str, Param]:
        return {p.name: p.default for p in self.params}

    def json_defaults(self) -> dict[str, JsonValue]:
        return {p.name: p.json_default() for p in self.params}

    def output_unit(self, output: str) -> Unit:
        """The unit of one output: its own, or the indicator's."""
        spec = next((o for o in self.outputs if o.id == output), None)
        if spec is None:
            raise KeyError(output)
        return self.unit if spec.unit is None else spec.unit

    def shared_unit(self) -> Unit | None:
        """The unit every output is in, or `None` when the outputs differ."""
        units = {self.output_unit(o.id) for o in self.outputs}
        return self.unit if units == {self.unit} else None

    def warmup_bars(self, params: Mapping[str, ParamValue] | None = None) -> int:
        """Closed bars before `outputs[0]` has a value, at `params` (complete) or the defaults."""
        return self.warmup(self.defaults() if params is None else params)

    def params_schema(self) -> dict[str, JsonValue]:
        """The JSON Schema the settings form renders from (closed subset, SR-E13-09)."""
        properties: dict[str, JsonValue] = {p.name: p.schema() for p in self.params}
        return {"type": "object", "additionalProperties": False, "properties": properties}


class IndicatorCatalogue:
    """An ordered registry of indicator definitions, keyed by id."""

    def __init__(self, definitions: Iterable[IndicatorDef] = ()) -> None:
        self._by_id: dict[str, IndicatorDef] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: IndicatorDef) -> None:
        if definition.id in self._by_id:
            raise DuplicateIndicatorError(f"The indicator {definition.id} is already registered.")
        self._by_id[definition.id] = definition

    def get(self, indicator: str) -> IndicatorDef | None:
        return self._by_id.get(indicator)

    def __iter__(self) -> Iterator[IndicatorDef]:
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)


def _as_decimal(value: object) -> Decimal | None:
    """A finite JSON number as an exact `Decimal` (a float at its shortest repr); else `None`.
    A boolean is not a number here, although Python counts it as an `int`."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value)) if math.isfinite(value) else None
    if isinstance(value, Decimal) and value.is_finite():
        return value
    return None


def _checked(spec: ParamSpec, value: object) -> Param:
    pointer, name = f"/{spec.name}", spec.name
    if spec.type == "string":
        if isinstance(value, str) and value in spec.enum:
            return value
        raise InvalidParamsError(pointer, "enum", f"{name} must be one of: {', '.join(spec.enum)}.")
    number = _as_decimal(value)
    if spec.type == "integer" and (number is None or number != number.to_integral_value()):
        raise InvalidParamsError(pointer, "type", f"{name} must be a whole number.")
    if number is None:
        raise InvalidParamsError(pointer, "type", f"{name} must be a number.")
    low, high = spec.minimum, spec.maximum
    if low is not None and high is not None and not low <= number <= high:
        rule = "minimum" if number < low else "maximum"
        raise InvalidParamsError(pointer, rule, f"{name} must be between {low} and {high}.")
    if spec.type == "integer":
        return int(number)
    step = spec.multiple_of
    if step is not None and number % step != 0:
        raise InvalidParamsError(pointer, "multipleOf", f"{name} must be a multiple of {step}.")
    return number


def validate_params(definition: IndicatorDef, params: object) -> dict[str, Param]:
    """The complete parameter object of `definition` from a caller's `params`: every declared
    parameter, an absent one at its default, each in its canonical type. Raises
    `InvalidParamsError` on the first defect, in declaration order; nothing is clamped."""
    if not isinstance(params, Mapping):
        raise InvalidParamsError("", "type", "params must be an object.")
    declared = [p.name for p in definition.params]
    if any(not isinstance(key, str) or key not in declared for key in params):
        known = ", ".join(declared)
        detail = f"takes only these parameters: {known}" if known else "takes no parameters"
        raise InvalidParamsError("", "additionalProperties", f"{definition.id} {detail}.")
    return {
        p.name: _checked(p, params[p.name]) if p.name in params else p.default
        for p in definition.params
    }


# --- parameters ----------------------------------------------------------------------------


def _period(default: int, name: str = "n", title: str = "Period") -> ParamSpec:
    return ParamSpec(name, title, "integer", default, PERIOD_MIN, PERIOD_MAX)


def _multiplier(default: str, title: str, name: str = "mult") -> ParamSpec:
    return ParamSpec(
        name, title, "number", Decimal(default), MULTIPLIER_MIN, MULTIPLIER_MAX, MULTIPLIER_STEP
    )


def _acceleration(name: str, title: str, default: str) -> ParamSpec:
    return ParamSpec(
        name,
        title,
        "number",
        Decimal(default),
        PSAR_ACCELERATION_MIN,
        PSAR_ACCELERATION_MAX,
        PSAR_ACCELERATION_STEP,
    )


def _anchor(*choices: str) -> ParamSpec:
    return ParamSpec("anchor", "Reset anchor", "string", choices[0], enum=choices)


# --- warmup of the client_worker indicators (the server ones ask their kernel) --------------


def _linear(*names: str, scale: int = 1, offset: int = 0) -> Warmup:
    """`scale` times the sum of the named periods, plus `offset`, bars."""

    def warmup(params: Mapping[str, ParamValue]) -> int:
        return scale * sum(int_param(params, name) for name in names) + offset

    return warmup


def _longest(*names: str) -> Warmup:
    """The longest of several periods."""

    def warmup(params: Mapping[str, ParamValue]) -> int:
        return max(int_param(params, name) for name in names)

    return warmup


def _fixed(bars: int) -> Warmup:
    def warmup(params: Mapping[str, ParamValue]) -> int:
        return bars

    return warmup


def _outputs(*pairs: tuple[str, str]) -> tuple[OutputSpec, ...]:
    return tuple(OutputSpec(output, name) for output, name in pairs)


def _server(
    kernel: type[Kernel],
    title: str,
    category: Category,
    pane: Pane,
    unit: Unit,
    names: Mapping[str, str],
    params: tuple[ParamSpec, ...] = (),
    units: Mapping[str, Unit] | None = None,
) -> IndicatorDef:
    """A server definition: outputs, `nullable_when` and warmup come from its kernel; `names`
    gives each output its label and `units` an output in a unit other than `unit`."""
    own = units or {}
    return IndicatorDef(
        kernel.indicator,
        title,
        category,
        pane,
        unit,
        tuple(OutputSpec(o, names[o], own.get(o)) for o in kernel.outputs),
        params,
        kernel.nullable_when,
        kernel.warmup_bars,
        kernel,
    )


# --- the 28 v1 indicators, in ADR-0034's table order ----------------------------------------

_BANDS = (("upper", "Upper band"), ("middle", "Middle line"), ("lower", "Lower band"))

SMA = _server(
    SmaKernel, "Simple moving average", "trend", "price", "price", {"sma": "SMA"}, (_period(20),)
)
EMA = _server(
    EmaKernel, "Exponential moving average", "trend", "price", "price", {"ema": "EMA"},
    (_period(21),),
)  # fmt: skip
WMA = IndicatorDef(
    "wma", "Weighted moving average", "trend", "price", "price", _outputs(("wma", "WMA")),
    (_period(20),),
    "None until n bars exist; then the mean of the last n closes weighted 1 to n, newest "
    "heaviest.",
    _linear("n"),
)  # fmt: skip
VWMA = IndicatorDef(
    "vwma", "Volume-weighted moving average", "trend", "price", "price",
    _outputs(("vwma", "VWMA")),
    (_period(20),),
    "None until n bars exist, and while the last n bars hold no volume; then the mean of the "
    "last n closes weighted by volume.",
    _linear("n"),
)  # fmt: skip
SMMA = IndicatorDef(
    "smma", "Smoothed moving average", "trend", "price", "price", _outputs(("smma", "SMMA")),
    (_period(20),),
    "None until n bars exist: the first value is the mean of the first n closes, then Wilder "
    "smoothing.",
    _linear("n"),
)  # fmt: skip
DEMA = IndicatorDef(
    "dema", "Double exponential moving average", "trend", "price", "price",
    _outputs(("dema", "DEMA")),
    (_period(20),),
    "None until 2n-1 bars exist: the EMA of the EMA needs n values of the first EMA.",
    _linear("n", scale=2, offset=-1),
)  # fmt: skip
TEMA = IndicatorDef(
    "tema", "Triple exponential moving average", "trend", "price", "price",
    _outputs(("tema", "TEMA")),
    (_period(20),),
    "None until 3n-2 bars exist: three chained EMAs, each needing n values of the one before.",
    _linear("n", scale=3, offset=-2),
)  # fmt: skip
VWAP = _server(
    VwapKernel, "Volume-weighted average price", "volume", "price", "price",
    {
        "vwap": "VWAP",
        "sigma": "Standard deviation",
        "upper_1": "Upper band, 1 sigma",
        "lower_1": "Lower band, 1 sigma",
        "upper_2": "Upper band, 2 sigma",
        "lower_2": "Lower band, 2 sigma",
        "upper_3": "Upper band, 3 sigma",
        "lower_3": "Lower band, 3 sigma",
        "band_sigma": "Distance of the close from VWAP, in standard deviations",
    },
    (_anchor("session"),),
    {"band_sigma": "zscore"},
)  # fmt: skip
BOLLINGER = IndicatorDef(
    "bollinger", "Bollinger Bands", "volatility", "price", "price", _outputs(*_BANDS),
    (_period(20), _multiplier("2", "Standard deviations")),
    "None until n bars exist; then the SMA of the last n closes, plus and minus mult "
    "population standard deviations of them.",
    _linear("n"),
)  # fmt: skip
KELTNER = IndicatorDef(
    "keltner", "Keltner Channels", "volatility", "price", "price", _outputs(*_BANDS),
    (_period(20, title="EMA period"), _multiplier("2", "ATR multiplier"),
     _period(10, "atr_n", "ATR period")),
    "None until the longer of n and atr_n bars exist: the EMA of the close needs n bars and "
    "Wilder's ATR atr_n; the bands are the EMA plus and minus mult ATRs.",
    _longest("n", "atr_n"),
)  # fmt: skip
DONCHIAN = IndicatorDef(
    "donchian", "Donchian Channels", "volatility", "price", "price", _outputs(*_BANDS),
    (_period(20),),
    "None until n bars exist; then the highest high and the lowest low of the last n bars and "
    "their midpoint.",
    _linear("n"),
)  # fmt: skip
ATR = _server(
    AtrKernel, "Average true range", "volatility", "sub", "price", {"atr": "ATR"}, (_period(14),)
)
ADX = _server(
    AdxKernel, "Average directional index", "volatility", "sub", "ratio",
    {"adx": "ADX", "plus_di": "Plus DI", "minus_di": "Minus DI"},
    (_period(14),),
)  # fmt: skip
RSI = _server(
    RsiKernel, "Relative strength index", "momentum", "sub", "pct", {"rsi": "RSI"}, (_period(14),)
)
MACD = IndicatorDef(
    "macd", "MACD", "momentum", "sub", "price",
    _outputs(("macd", "MACD line"), ("signal", "Signal line"), ("histogram", "Histogram")),
    (_period(12, "fast", "Fast period"), _period(26, "slow", "Slow period"),
     _period(9, "signal", "Signal period")),
    "The MACD line is None until the longer of fast and slow bars exist (both EMAs seeded); "
    "the signal line and the histogram until signal-1 more bars seed the signal EMA.",
    _longest("fast", "slow"),
)  # fmt: skip
STOCHASTIC = IndicatorDef(
    "stochastic", "Stochastic", "momentum", "sub", "ratio",
    _outputs(("k", "%K"), ("d", "%D")),
    (_period(14, title="%K period"), _period(1, "smooth_k", "%K smoothing"),
     _period(3, "smooth_d", "%D period")),
    "%K is None until n+smooth_k-1 bars exist, and while the n-bar high equals the n-bar low; "
    "%D until smooth_d-1 more values of %K exist.",
    _linear("n", "smooth_k", offset=-1),
)  # fmt: skip
CCI = IndicatorDef(
    "cci", "Commodity channel index", "momentum", "sub", "ratio", _outputs(("cci", "CCI")),
    (_period(20),),
    "None until n bars exist, and while the mean deviation of the last n typical prices is 0.",
    _linear("n"),
)  # fmt: skip
WILLIAMS_R = IndicatorDef(
    "williams_r", "Williams %R", "momentum", "sub", "ratio",
    _outputs(("williams_r", "Williams %R")),
    (_period(14),),
    "None until n bars exist, and while the n-bar high equals the n-bar low.",
    _linear("n"),
)  # fmt: skip
SUPERTREND = IndicatorDef(
    "supertrend", "Supertrend", "trend", "price", "price",
    (OutputSpec("supertrend", "Supertrend"),
     OutputSpec("direction", "Direction, +1 up or -1 down", "ratio")),
    (_period(10, title="ATR period"), _multiplier("3", "ATR multiplier")),
    "None until n bars exist: the bands are the median price plus and minus mult times "
    "Wilder's ATR over n bars.",
    _linear("n"),
)  # fmt: skip
ZIGZAG = _server(
    ZigzagKernel, "Zig Zag", "trend", "price", "price",
    {"swing_high": "Swing high", "swing_low": "Swing low"},
    (
        ParamSpec("depth", "Depth", "integer", 5, PERIOD_MIN, PERIOD_MAX),
        ParamSpec("deviation_pct", "Deviation (%)", "number", Decimal("0"), DEVIATION_PCT_MIN,
                  DEVIATION_PCT_MAX, DEVIATION_PCT_STEP),
    ),
)  # fmt: skip
ICHIMOKU = IndicatorDef(
    "ichimoku", "Ichimoku Cloud", "trend", "price", "price",
    _outputs(("tenkan", "Conversion line"), ("kijun", "Base line"),
             ("senkou_a", "Leading span A"), ("senkou_b", "Leading span B"),
             ("chikou", "Lagging span")),
    (_period(9, "tenkan", "Conversion line period"), _period(26, "kijun", "Base line period"),
     _period(52, "senkou_b", "Leading span B period"),
     _period(26, "displacement", "Displacement")),
    "Each line is None until its period's bars exist: tenkan bars for the conversion line, "
    "kijun for the base line, both for leading span A and senkou_b for leading span B. The "
    "leading spans plot displacement bars ahead, the lagging span (the close) displacement "
    "bars back.",
    _linear("tenkan"),
)  # fmt: skip
PSAR = IndicatorDef(
    "psar", "Parabolic SAR", "trend", "price", "price", _outputs(("psar", "Parabolic SAR")),
    (_acceleration("step", "Acceleration step", "0.02"),
     _acceleration("max_step", "Maximum acceleration", "0.2")),
    "None on the first bar: the second bar sets the first trend and its extreme point.",
    _fixed(2),
)  # fmt: skip
VOLUME = _server(VolumeKernel, "Volume", "volume", "both", "qty", {"volume": "Volume"})
VOLUME_MA = IndicatorDef(
    "volume_ma", "Volume moving average", "volume", "both", "qty",
    _outputs(("volume_ma", "Volume MA")),
    (_period(20),),
    "None until n bars exist; then the mean volume of the last n bars.",
    _linear("n"),
)  # fmt: skip
OBV = IndicatorDef(
    "obv", "On-balance volume", "volume", "sub", "qty", _outputs(("obv", "OBV")), (),
    "None only before the first bar; then the running sum of each bar's volume, added on an "
    "up close and subtracted on a down close.",
    _fixed(1),
)  # fmt: skip
CMF = IndicatorDef(
    "cmf", "Chaikin money flow", "volume", "sub", "ratio", _outputs(("cmf", "CMF")),
    (_period(20),),
    "None until n bars exist, and while the last n bars hold no volume.",
    _linear("n"),
)  # fmt: skip
MFI = IndicatorDef(
    "mfi", "Money flow index", "volume", "sub", "ratio", _outputs(("mfi", "MFI")),
    (_period(14),),
    "None until n+1 bars exist (n changes of the typical price), and while the money flow of "
    "the last n changes is 0.",
    _linear("n", offset=1),
)  # fmt: skip
CVD = _server(
    CvdKernel, "Cumulative volume delta", "orderflow", "sub", "qty", {"cvd": "CVD"},
    (_anchor("session", "utc_day"),),
)  # fmt: skip

V1_INDICATORS: Final[tuple[IndicatorDef, ...]] = (
    SMA, EMA, WMA, VWMA, SMMA, DEMA, TEMA, VWAP, BOLLINGER, KELTNER, DONCHIAN, ATR, ADX, RSI,
    MACD, STOCHASTIC, CCI, WILLIAMS_R, SUPERTREND, ZIGZAG, ICHIMOKU, PSAR, VOLUME, VOLUME_MA,
    OBV, CMF, MFI, CVD,
)  # fmt: skip

#: The bar's aggressor delta, which `cvd` sums: a rule metric with a server kernel, but not a v1
#: chart indicator (`docs/plan/spikes/e13-o4.md` §5.1), so no catalogue lists it and
#: `GET /indicators` never serves it (IR-25).
DELTA: Final = _server(DeltaKernel, "Delta", "orderflow", "sub", "qty", {"delta": "Delta"})

#: Every definition with a server kernel, by id: the rule vocabulary binds metrics to these only
#: (ADR-0034 rule 2: rule eligibility is what makes an indicator `server`).
SERVER_DEFINITIONS: Final[Mapping[str, IndicatorDef]] = MappingProxyType(
    {d.id: d for d in (*V1_INDICATORS, DELTA) if d.kernel is not None}
)


def default_catalogue() -> IndicatorCatalogue:
    """A fresh catalogue of the 28 v1 indicators, in ADR-0034's table order."""
    return IndicatorCatalogue(V1_INDICATORS)
