"""Indicator identity: canonical form and `spec_hash` (E13-T02, #426; 24-internal-schemas §7.4).

`spec_hash` is the sha256 of the canonical JSON of
`{"bar_spec_hash", "indicator", "params", "source", "v"}`. The engine's instance key, the cache
key, the metric key and the UI instance all derive from it, so they agree.

Canonical form (`INDICATOR_SPEC_VERSION` 1; changing any rule below moves every hash, so it
bumps the version; `packages/fixtures/golden/indicators/spec_hash_vectors.json` pins it for the
TS mirror):

- keys sorted, separators `,` and `:` with no whitespace, ASCII only (`ensure_ascii`);
- `params` holds every parameter of the indicator. Callers write defaults out explicitly: an
  omitted default is a different identity;
- every number, integer or not, is a JSON string of its plain decimal digits (`"n":"21"`): no
  exponent, no trailing fractional zeros, `-0` as `0`; a float is first taken at its shortest
  round-trip repr. So `ema(21)`, `ema(21.0)` and `ema(Decimal("21.00"))` share one hash. A
  number is 0 or has a decimal exponent from -64 to 64 (a magnitude from 1e-64 to below 1e65),
  with at most 40 significant digits. Booleans stay JSON booleans and enum values stay strings;
- `source` is `BAR_SOURCE`, `"tape"`: where the bars come from (bars built from the recorded
  trades), the only bar source in v1. It is not the price a kernel reads (`Kernel.sources`:
  `close`, `hlc3`), which no identity holds; `v` is the JSON integer `INDICATOR_SPEC_VERSION`.

The number rule mirrors `bars.spec.dec_str`, which this module may not import: M15 `rules`
imports the indicator catalogue and may not reach `bars` (the `rules/ir/canonical.py`
precedent).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from typing import Final

from candleviewer.orderflow.errors import IndicatorParamError
from candleviewer.orderflow.indicators.types import ParamValue

INDICATOR_SPEC_VERSION: Final = 1
#: The bar source every v1 identity hashes: bars built from the recorded trades (24 §7.4).
BAR_SOURCE: Final = "tape"

type CanonicalValue = str | bool

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_TOKEN = re.compile(r"^[a-z0-9_]{1,32}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_MIN_PREC: Final = 28
#: Bounds on a number's decimal exponent and significant digits, so no input can build a huge
#: canonical string (a valid parameter is far inside both; `limits.py` bounds each one).
_MAX_EXPONENT: Final = 64
_MAX_DIGITS: Final = 40


def canonical_number(x: int | float | Decimal) -> str:
    """Plain decimal string of a finite number (see the module docstring)."""
    if isinstance(x, bool):
        raise IndicatorParamError("A number parameter must not be a boolean.")
    if isinstance(x, float):
        if not math.isfinite(x):
            raise IndicatorParamError("A number parameter must be finite.")
        d = Decimal(repr(x))
    elif isinstance(x, int):
        d = Decimal(x)
    else:
        if not x.is_finite():
            raise IndicatorParamError("A number parameter must be finite.")
        d = x
    if d == 0:
        return "0"
    if not -_MAX_EXPONENT <= d.adjusted() <= _MAX_EXPONENT:
        raise IndicatorParamError("A number parameter must be 0 or from 1e-64 to below 1e65.")
    with localcontext() as ctx:
        ctx.prec = max(len(d.as_tuple().digits), _MIN_PREC)  # never round
        normal = d.normalize()
    if len(normal.as_tuple().digits) > _MAX_DIGITS:
        raise IndicatorParamError("A number parameter must have at most 40 significant digits.")
    return format(normal, "f")


def canonical_value(name: str, value: ParamValue) -> CanonicalValue:
    """One parameter value in canonical form; raises `IndicatorParamError` naming `name`."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if not _TOKEN.fullmatch(value):
            raise IndicatorParamError(
                f"{name} must be a lowercase token of letters, digits and '_'."
            )
        return value
    if isinstance(value, int | float | Decimal):
        try:
            return canonical_number(value)
        except IndicatorParamError:
            raise IndicatorParamError(
                f"{name} must be 0 or a finite number from 1e-64 to below 1e65 in magnitude, "
                "with at most 40 significant digits."
            ) from None
    raise IndicatorParamError(f"{name} must be a number, a boolean or a token.")


def canonical_params(params: Mapping[str, ParamValue]) -> dict[str, CanonicalValue]:
    """Every parameter in canonical form, keys sorted."""
    names = list(params)
    for name in names:
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise IndicatorParamError(
                "A parameter name must be a lowercase identifier of at most 32 characters."
            )
    return {name: canonical_value(name, params[name]) for name in sorted(names)}


def _check_identity_fields(indicator: str, bar_spec_hash: str) -> None:
    if not isinstance(indicator, str) or not _NAME.fullmatch(indicator):
        raise IndicatorParamError(
            "The indicator id must be a lowercase identifier of at most 32 characters."
        )
    if not isinstance(bar_spec_hash, str) or not _HASH.fullmatch(bar_spec_hash):
        raise IndicatorParamError("bar_spec_hash must be 64 lowercase hex characters.")


def _canonical_text(
    indicator: str, canonical: Mapping[str, CanonicalValue], bar_spec_hash: str
) -> str:
    """Serialise parameters that are already canonical, after the caller checked the identity
    fields. Never canonicalise them twice: a canonical number is a string such as `"0.5"`,
    which the enum-token rule would then refuse."""
    doc = {
        "bar_spec_hash": bar_spec_hash,
        "indicator": indicator,
        "params": dict(canonical),
        "source": BAR_SOURCE,
        "v": INDICATOR_SPEC_VERSION,
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(indicator: str, params: Mapping[str, ParamValue], *, bar_spec_hash: str) -> str:
    """The exact string `spec_hash` is computed over."""
    _check_identity_fields(indicator, bar_spec_hash)
    return _canonical_text(indicator, canonical_params(params), bar_spec_hash)


def compute_spec_hash(
    indicator: str, params: Mapping[str, ParamValue], *, bar_spec_hash: str
) -> str:
    """sha256 hex of the UTF-8 canonical JSON."""
    return _digest(canonical_json(indicator, params, bar_spec_hash=bar_spec_hash))


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    """One indicator instance over one bar series, canonicalised on construction.

    Every field is canonical after `__post_init__`, so specs built from `21` and `21.0` are
    equal and hash alike.
    """

    indicator: str
    params: tuple[tuple[str, ParamValue], ...]
    bar_spec_hash: str
    spec_hash: str = field(init=False)

    def __post_init__(self) -> None:
        given = dict(self.params)
        if len(given) != len(self.params):
            raise IndicatorParamError("A parameter is given more than once.")
        _check_identity_fields(self.indicator, self.bar_spec_hash)
        canonical = canonical_params(given)
        object.__setattr__(self, "params", tuple(canonical.items()))
        text = _canonical_text(self.indicator, canonical, self.bar_spec_hash)
        object.__setattr__(self, "spec_hash", _digest(text))

    @classmethod
    def of(
        cls, indicator: str, params: Mapping[str, ParamValue], *, bar_spec_hash: str
    ) -> IndicatorSpec:
        """Build a spec from a parameter mapping (defaults already written out)."""
        return cls(indicator, tuple(params.items()), bar_spec_hash)
