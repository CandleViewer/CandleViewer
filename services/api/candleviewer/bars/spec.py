"""`spec_hash` canonicalisation and the `BarSpec ⇄ (bar_type, param)` wire mapping (E12-T01).

Canonical form (SPEC_HASH_VERSION 1 — changing it moves every hash; golden vectors in
`packages/fixtures/golden/bars/spec_hash_vectors.json` pin it): every `BarSpec` field,
defaults **explicitly included**, keys sorted, no whitespace, Decimals as plain normalised
strings (`50.00` -> `"50"`, never exponent form), ints/bools as JSON literals. Mirrors the
`rules/ir/canonical.py` precedent (that module is not importable from M8, C-3.1).

Wire convention: `22-api-openapi.yaml` `/market/bars` and `23-ws-protocol.md` §6.1. `param`
is untrusted input that becomes a topic segment, cache key and QuestDB SYMBOL value: it is
length-bounded (24), dot-free and parsed with a strict per-`bar_type` whitelist.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, localcontext
from typing import Any, Final, Literal

import structlog

from candleviewer.bars.errors import BarParamOutOfRange, BarSpecError
from candleviewer.bars.limits import QTY_PARAM_MAX, RANGE_TICKS_RANGE, TICK_PARAM_RANGE
from candleviewer.bars.models import BarSpec, check_renko_bounds
from candleviewer.observability.metrics import Counter

SPEC_HASH_VERSION: Final = 1
PARAM_MAX_LEN: Final = 24

WireBarType = Literal["time", "tick", "volume", "range", "delta", "renko", "pnf", "heikin_ashi"]
WIRE_BAR_TYPES: Final[frozenset[str]] = frozenset(
    {"time", "tick", "volume", "range", "delta", "renko", "pnf", "heikin_ashi"}
)

#: `KlineInterval` codes (OpenAPI) -> interval_ms. `M` is calendar-variable: not a fixed
#: `interval_ms`, so it is rejected for locally built time bars.
_MIN = 60_000
TIME_INTERVALS: Final[dict[str, int]] = {
    **{
        code: int(code) * _MIN
        for code in ("1", "3", "5", "15", "30", "60", "120", "240", "360", "720")
    },
    "D": 1440 * _MIN,
    "W": 7 * 1440 * _MIN,
}
_INTERVAL_CODES: Final[dict[int, str]] = {v: k for k, v in TIME_INTERVALS.items()}

_UINT = re.compile(r"^[1-9][0-9]{0,17}$")
#: ADR-0033: `atr` is reserved (R2); strict whitelist, bounded period 2..100 and optional mult.
_ATR = re.compile(r"^atr:(?:[2-9]|[1-9][0-9]|100)(?::[1-9][0-9]{0,3})?$")
#: ADR-0033 Decision 1: the exact 422 detail, naming the reason and the supported alternative.
RENKO_ATR_DEFERRED: Final = "ATR bricks are not available yet. Enter a brick size in ticks."

bar_specs_registered_total = Counter(
    "bar_specs_registered_total", "Distinct bar specs registered (spec_hash -> BarSpec)."
)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def dec_str(d: Decimal) -> str:
    """Plain notation, no exponent, no trailing fractional zeros, `-0` -> `0`."""
    if d == 0:
        return "0"
    with localcontext() as ctx:
        ctx.prec = max(len(d.as_tuple().digits), 28)  # never round
        return format(d.normalize(), "f")


def canonical_json(spec: BarSpec) -> str:
    """The exact byte string `spec_hash` is computed over."""
    doc: dict[str, object] = {}
    for name in BarSpec.model_fields:
        v = getattr(spec, name)
        doc[name] = dec_str(v) if isinstance(v, Decimal) else v
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_spec_hash(spec: BarSpec) -> str:
    """sha256 hex over UTF-8 canonical JSON. Prefer the memoised `BarSpec.spec_hash`."""
    return hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest()


def _uint(bar_type: str, param: str) -> int:
    if not _UINT.match(param):
        raise BarSpecError(
            f"The param '{param}' is not valid for bar_type '{bar_type}'; "
            "it must be a positive whole number."
        )
    return int(param)


def from_wire(bar_type: str, param: str) -> BarSpec:
    """Parse an untrusted wire pair into a `BarSpec`; raises `BarSpecError` (-> 422)."""
    if bar_type not in WIRE_BAR_TYPES:
        raise BarSpecError(f"The bar_type '{bar_type[:32]}' is not a supported bar type.")
    if len(param) > PARAM_MAX_LEN:
        raise BarSpecError(f"The param must be at most {PARAM_MAX_LEN} characters long.")
    if "." in param:
        raise BarSpecError(
            "The param must not contain a dot; use a colon to separate compound values."
        )
    if bar_type == "pnf":
        raise BarSpecError("Point-and-figure bars (bar_type 'pnf') are not available.")
    if bar_type == "heikin_ashi":
        raise BarSpecError(
            "Heikin-Ashi is a chart transform over time bars; request bar_type 'time' instead."
        )
    if bar_type == "time":
        if param not in TIME_INTERVALS:
            raise BarSpecError(
                f"The param '{param}' is not a supported time interval for bar_type 'time'."
            )
        return BarSpec(kind="time", interval_ms=TIME_INTERVALS[param])
    if bar_type == "renko" and _ATR.match(param):
        raise BarSpecError(RENKO_ATR_DEFERRED)
    n = _uint(bar_type, param)
    if bar_type == "tick":
        return BarSpec(kind="tick", tick_count=n)
    if bar_type == "volume":
        return BarSpec(kind="volume", volume_threshold=Decimal(n))
    if bar_type == "delta":
        return BarSpec(kind="delta", delta_threshold=Decimal(n))
    if bar_type == "range":
        return BarSpec(kind="range", range_ticks=n)
    check_renko_bounds(n, 2)  # ordinary invalid-param 422 before any registry/series work
    return BarSpec(kind="renko", range_ticks=n)


_DEFAULT_OPTIONS: Final[dict[str, object]] = {
    "price_source": "last",
    "session_anchor_utc_min": 0,
    "align_to_epoch": True,
    "renko_wick": False,
    "reversal_bricks": 2,
}


def is_wire_representable(spec: BarSpec) -> bool:
    try:
        to_wire(spec)
    except BarSpecError:
        return False
    return True


#: SR-E12-03: each non-time kind's `param` floor and ceiling (`bars/limits.py`); time bars take
#: only catalogue intervals. REST `/market/bars` and the WS `bars.*`/`footprint.*` subscribe path
#: both refuse outside these, never clamp.
_PARAM_BOUNDS: Final[dict[str, tuple[int, int]]] = {
    "tick": TICK_PARAM_RANGE,
    "range": RANGE_TICKS_RANGE,
    "renko": RANGE_TICKS_RANGE,
    "volume": (1, QTY_PARAM_MAX),
    "delta": (1, QTY_PARAM_MAX),
}


def check_param_bounds(spec: BarSpec, bar_type: str) -> None:
    """Raise `BarParamOutOfRange`, naming the bound, when `spec`'s param is outside SR-E12-03's
    floor and ceiling for its kind (a one-print tick bar is a builder-amplification vector,
    BR-29). `bar_type` is the wire name, for the message."""
    bounds = _PARAM_BOUNDS.get(spec.kind)
    if bounds is not None and not bounds[0] <= int(spec.param_value) <= bounds[1]:
        raise BarParamOutOfRange(
            f"param for bar_type {bar_type} must be between {bounds[0]} and {bounds[1]}."
        )


def to_wire(spec: BarSpec) -> tuple[WireBarType, str]:
    """Render a spec as its human-readable wire pair; 1:1 with `spec_hash`.

    The current wire grammar carries one scalar, so specs with non-default shared options,
    non-catalogue intervals or fractional thresholds are not representable and raise.
    """
    for opt, default in _DEFAULT_OPTIONS.items():
        if getattr(spec, opt) != default:
            raise BarSpecError(
                f"The option {opt} has no wire encoding; only its default is supported."
            )
    value = spec.param_value  # never None: guaranteed by BarSpec._exactly_one
    if spec.kind == "time":
        code = _INTERVAL_CODES.get(int(value))
        if code is None:
            raise BarSpecError(f"The interval_ms {value} has no wire interval code.")
        return "time", code
    if spec.kind in ("tick", "range", "renko"):
        return spec.kind, str(value)
    thr = Decimal(value)
    if thr != thr.to_integral_value():
        field = "volume_threshold" if spec.kind == "volume" else "delta_threshold"
        raise BarSpecError(f"The {field} must be a whole number to be sent on the wire.")
    s = dec_str(thr)
    if len(s) > PARAM_MAX_LEN:
        raise BarSpecError(f"The param must be at most {PARAM_MAX_LEN} characters long.")
    return spec.kind, s


class SpecRegistry:
    """Process-local `spec_hash -> BarSpec` map so operators can resolve a QuestDB
    `bar_param` / WS topic back to a readable spec."""

    def __init__(self) -> None:
        self._specs: dict[str, BarSpec] = {}

    def register(self, spec: BarSpec) -> str:
        h = spec.spec_hash
        if h not in self._specs:
            self._specs[h] = spec
            bar_specs_registered_total.inc()
            _log().info("bar_spec_registered", spec_hash=h, spec=canonical_json(spec))
        return h

    def resolve(self, spec_hash: str) -> BarSpec | None:
        return self._specs.get(spec_hash)
