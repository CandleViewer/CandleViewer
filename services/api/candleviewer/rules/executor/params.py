"""The typed parameters of the two entries a rule hands the OMS (24 §11.6; E35-T11 slice 3b).

`place_order` and `scale_in` read their IR `params` here, strictly (C-12.5): a price, a quantity
or a percent is a `Decimal` parsed from its canonical decimal text, the text the IR's content hash
reads (`canonical.dec_str`; a float an untyped `params` holds is read as its shortest repr, as the
hash reads it), so no binary float ever reaches an order; a parameter the action does not declare
is refused (`extra="forbid"`). A set that does not parse is no request: the handler answers it
`invalid_params`, nothing sent (24 §11.5). The engine never sizes an order (§11.6): these only
carry what the rule asked for to the OMS, whose size step is the last word.

- `place_order`: `side`, `order_type`, `qty_mode` (`explicit` with `qty`, or `profile`, sized by
  the account's profile, a `profile` id naming another of its profiles; 24 §8.1 `OrderIntent`),
  `price` for a limit order and none for a market one, an optional `stop_loss` and at most one
  `take_profits` item, each a 22 `Offset` (`unit`, `value`), and an `algo` of kind `none` or none,
  as the OMS places no emulated algo yet.
- `scale_in`: `qty` or `qty_pct` (a percent of the open position, above 0 and at most 100), not
  both; with neither, the profile sizes it. It adds to the open position, on its side.

E35-T12 reads the exits' the same way (24 §11.6 "The exits' parameters"): `scale_out` names
`qty_pct` or `qty` and a `market` order type; a flatten an optional `symbols`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator

from candleviewer.domain.primitives import Symbol
from candleviewer.rules.ir.canonical import IrValueError, dec_str

#: 22 `Offset`'s units, as the OMS's `StopOffset` takes them; the OMS refuses those it cannot place
#: yet (`stop_unit_unsupported`), never this module.
OffsetUnit = Literal["price", "ticks", "percent", "atr", "r_multiple"]
_STRICT: Final = ConfigDict(frozen=True, extra="forbid")
#: A decimal's text as the IR writes one: ASCII digits with an optional sign, point and exponent,
#: never the grouping underscores or other scripts' digits `Decimal()` would also read.
_DECIMAL_TEXT: Final = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def canonical_decimal(value: object) -> Decimal:
    """`value` as the `Decimal` of its canonical text: an `int` exactly, a `Decimal` and a decimal
    string as written, a float as its shortest repr (the IR hash's reading), each finite and in
    plain form (`dec_str`). A bool, a non-finite or an over-wide number, or a string that is not a
    decimal's ASCII text, is a `ValueError` that names no value."""
    if isinstance(value, bool):
        raise ValueError("a number, not a boolean")
    if isinstance(value, float):
        value = Decimal(float.__repr__(value))
    elif isinstance(value, int):
        value = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if _DECIMAL_TEXT.fullmatch(text) is None:
            raise ValueError("a decimal number")
        value = Decimal(text)
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("a finite decimal number")
    try:
        return Decimal(dec_str(value))
    except IrValueError:
        raise ValueError("a decimal number in range") from None


Positive = Annotated[Decimal, BeforeValidator(canonical_decimal), Field(gt=0)]
Percent = Annotated[Decimal, BeforeValidator(canonical_decimal), Field(gt=0, le=100)]


class Offset(BaseModel):
    """22 `Offset`: a stop or take-profit level (`price`) or a distance from the reference price."""

    model_config = _STRICT
    unit: OffsetUnit
    value: Positive


class NoAlgo(BaseModel):
    """An `algo` of kind `none`, the one the OMS places today (22 `PlaceOrderRequest`)."""

    model_config = _STRICT
    kind: Literal["none"]


class PlaceOrderParams(BaseModel):
    """`place_order`'s parameters (module docstring)."""

    model_config = _STRICT
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"]
    qty_mode: Literal["explicit", "profile"]
    qty: Positive | None = None
    profile: UUID | None = None
    price: Positive | None = None
    stop_loss: Offset | None = None
    take_profits: tuple[Offset, ...] = Field(default=(), max_length=1)
    algo: NoAlgo | None = None

    @model_validator(mode="after")
    def _one_reading(self) -> PlaceOrderParams:
        if (self.qty_mode == "explicit") != (self.qty is not None):
            raise ValueError("an explicit qty_mode names its qty, and only it does")
        if (self.order_type == "limit") != (self.price is not None):
            raise ValueError("a limit order names its price, and only it does")
        return self


class ScaleInParams(BaseModel):
    """`scale_in`'s parameters (module docstring)."""

    model_config = _STRICT
    qty: Positive | None = None
    qty_pct: Percent | None = None

    @model_validator(mode="after")
    def _one_size(self) -> ScaleInParams:
        if self.qty is not None and self.qty_pct is not None:
            raise ValueError("a scale_in names qty or qty_pct, not both")
        return self


EntryParams = PlaceOrderParams | ScaleInParams
_MODELS: Final[Mapping[str, type[PlaceOrderParams] | type[ScaleInParams]]] = {
    "place_order": PlaceOrderParams, "scale_in": ScaleInParams,
}  # fmt: skip


def entry_params(action_type: str, params: Mapping[str, Any]) -> EntryParams | None:
    """`params` of a `place_order` or `scale_in` action, typed; `None` when they do not parse (or
    the type is neither), so the handler answers `invalid_params`. The error names no value."""
    model = _MODELS.get(action_type)
    if model is None:
        return None
    try:
        return model.model_validate(dict(params))
    except ValidationError:
        return None


class ScaleOutParams(BaseModel):
    """`scale_out`'s parameters (E35-T12; 24 §11.6 "The exits' parameters"): `qty_pct` (above 0,
    at most 100) or `qty`, one of the two, and `order_type` `market`, as a reduce-only exit is a
    market order and the table names no price for a limit one."""

    model_config = _STRICT
    order_type: Literal["market"]
    qty: Positive | None = None
    qty_pct: Percent | None = None

    @model_validator(mode="after")
    def _one_size(self) -> ScaleOutParams:
        if (self.qty is None) == (self.qty_pct is None):
            raise ValueError("a scale_out names qty or qty_pct, one of the two")
        return self


class FlattenParams(BaseModel):
    """`flatten_position`'s and `flatten_all_positions`' parameters: an optional `symbols`, each a
    symbol code, which a flatten closes in place of the instance's symbol, or narrows to."""

    model_config = _STRICT
    symbols: tuple[Symbol, ...] | None = Field(default=None, min_length=1, max_length=64)


ReduceParams = ScaleOutParams | FlattenParams
_REDUCE: Final[Mapping[str, type[ScaleOutParams] | type[FlattenParams]]] = {
    "scale_out": ScaleOutParams, "flatten_position": FlattenParams,
    "flatten_all_positions": FlattenParams,
}  # fmt: skip


def reduce_params(action_type: str, params: Mapping[str, Any]) -> ReduceParams | None:
    """`params` of a reduce-only exit, typed as `entry_params` types an entry's: `None` when they
    do not parse (a percent above 100 among them) or the type is none of the three."""
    model = _REDUCE.get(action_type)
    if model is None:
        return None
    try:
        return model.model_validate(dict(params))
    except ValidationError:
        return None
