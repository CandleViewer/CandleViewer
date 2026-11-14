"""The closed JSON Schema subset an action's `params_schema` is written in, and its check (#5963).

A rule's action parameters are checked against their published bounds at save, as an indicator's
are against its descriptor (`orderflow.indicators.catalogue.validate_params`, the pattern this
follows): `validate_rule` runs `param_defects` on each action, so validate, compile, a save and
arming answer alike. The subset is closed: a catalogue schema writes only `KEYWORDS` and
`ANNOTATIONS`, a `type` of `TYPES` and a boolean `additionalProperties`, and a unit test fails
anything else, so no bound is published that this does not read.

- A number is one the content hash can hold, read exactly: finite and inside `plain_decimal`'s
  range, as the content hash reads a number. It is an `int`, a `float` (at its shortest repr) or
  a `Decimal`, never a `bool`; or decimal text, read as its number, as #5876 reads a rule
  constant's text and as 22's `Decimal` carries a number (convention C6): ASCII digits with an
  optional sign, point and exponent, nothing around them, at most `MAX_NUMBER_TEXT` characters.
  `NaN`, an infinity, a number past that range in either spelling, and any other text are no
  number. An integer is a number without a fraction. Validate and compile hash a document before
  they validate it (#4185), so there a number no rule can hold is the content hash's refusal; a
  save validates first, so there it is this check's.
- `maxLength` counts a text's characters (code points).
- A property holding `null` is absent, as the validator's `required` check has always read it.
- A defect's text is `_TEXT`'s, from the schema alone: it names the parameter and the bound it
  breaks, never the value, nor a key the schema does not declare.
"""

from __future__ import annotations

import decimal
import operator
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from candleviewer.domain.plain_decimal import MAX_PLAIN_WIDTH, PlainWidthError, plain_decimal

#: The validation keywords the subset reads.
KEYWORDS: Final = frozenset(
    {
        "type", "enum", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
        "maxLength", "required", "properties", "additionalProperties", "items",
    }
)  # fmt: skip
#: Keywords that describe a value and bound nothing.
ANNOTATIONS: Final = frozenset({"default", "title", "description"})
#: Each `type` the subset reads, as a defect names it.
TYPES: Final = {
    "string": "text", "number": "a number", "integer": "a whole number",
    "boolean": "true or false", "object": "an object", "array": "a list",
}  # fmt: skip
#: Each defect's text, by the keyword it breaks: `{at}` is where (`'qty'`, `each item of
#: 'symbols'`) and `{bound}` what the schema writes there. Nothing else is ever filled in.
_TEXT: Final = {
    "type": "{at} must be {bound}",
    "enum": "{at} must be one of {bound}",
    "exclusiveMinimum": "{at} must be greater than {bound}",
    "minimum": "{at} must be at least {bound}",
    "exclusiveMaximum": "{at} must be less than {bound}",
    "maximum": "{at} must be at most {bound}",
    "maxLength": "{at} must be at most {bound} characters",
    "required": "{at} is missing '{bound}'",
    "additionalProperties": "{at} takes only {bound}",
}
#: Each numeric bound and the relation a number must hold to it.
_BOUNDS: Final = (
    ("exclusiveMinimum", operator.gt),
    ("minimum", operator.ge),
    ("exclusiveMaximum", operator.lt),
    ("maximum", operator.le),
)
#: The longest decimal text read as a number, the bound #5876 reads a constant's text to: twice
#: the widest plain form a rule holds. Longer text is no number, before the pattern reads it.
MAX_NUMBER_TEXT: Final = 2 * MAX_PLAIN_WIDTH
#: Decimal text: ASCII digits with an optional sign, point and exponent.
_DECIMAL_TEXT: Final = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
#: The types whose values the numeric bounds read, decimal text included.
_NUMERIC: Final = frozenset({"number", "integer"})


@dataclass(frozen=True, slots=True)
class ParamDefect:
    """One way an action's `params` break its schema: `param` is the parameter it is in (`""` for
    the params object itself), `keyword` the keyword it breaks and `text` what the schema asks
    (`'qty' must be greater than 0`); `missing` marks a required parameter that is absent."""

    param: str
    keyword: str
    text: str
    missing: bool = False


def _defect(
    param: str, keyword: str, path: str, bound: object, missing: bool = False
) -> ParamDefect:
    """The defect of `keyword` at `path`, its text `_TEXT[keyword]`, built only once a value
    breaks it; `bound` is what the schema writes for it."""
    at = f"each item of '{path[:-2]}'" if path.endswith("[]") else f"'{path or 'params'}'"
    return ParamDefect(param, keyword, _TEXT[keyword].format(at=at, bound=bound), missing)


def _number(value: object) -> Decimal | None:
    """`value` as an exact `Decimal` when it is a number the content hash can hold, decimal text
    included, else `None` (module docstring)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        number = Decimal(repr(value))
    elif isinstance(value, Decimal):
        number = value
    elif (
        isinstance(value, str)
        and len(value) <= MAX_NUMBER_TEXT
        and _DECIMAL_TEXT.fullmatch(value) is not None
    ):
        try:  # an exponent past the decimal module's own range raises
            number = Decimal(value)
        except decimal.DecimalException:
            return None
    else:
        return None
    if not number.is_finite():  # NaN and the infinities: no hash holds them
        return None
    try:
        plain_decimal(number)  # the range a rule can hold, as the content hash reads a number
    except (PlainWidthError, decimal.DecimalException):
        return None
    return number


def _is(kind: str, value: object, number: Decimal | None) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "object":
        return isinstance(value, Mapping)
    if kind == "array":
        return isinstance(value, list | tuple)
    if kind == "integer":
        return number is not None and number == number.to_integral_value()
    return kind == "number" and number is not None  # a type outside the subset holds nothing


def _same(value: object, member: object) -> bool:
    return value == member and isinstance(value, bool) == isinstance(member, bool)


def _check(
    schema: Mapping[str, Any], value: object, path: str, param: str
) -> Iterator[ParamDefect]:
    """`value`'s defects against `schema`; `path` is where it is (`qty`, `stop_loss.value`, or
    `symbols[]` for an item) and `param` the parameter it is in."""
    kind = schema.get("type")
    # A number, or decimal text where the schema asks for a number: the type and bounds read it.
    number = _number(value) if kind in _NUMERIC or not isinstance(value, str) else None
    if kind is not None and not _is(kind, value, number):
        yield _defect(param, "type", path, TYPES.get(kind, kind))
        return
    if "enum" in schema and not any(_same(value, m) for m in schema["enum"]):
        yield _defect(param, "enum", path, ", ".join(str(m) for m in schema["enum"]))
    for keyword, holds in _BOUNDS:
        bound = _number(schema.get(keyword))
        if number is not None and bound is not None and not holds(number, bound):
            yield _defect(param, keyword, path, schema[keyword])
    longest = schema.get("maxLength")
    if isinstance(value, str) and isinstance(longest, int) and len(value) > longest:
        yield _defect(param, "maxLength", path, longest)
    if isinstance(value, Mapping):
        yield from _object(schema, value, path, param)
    elif isinstance(value, list | tuple) and "items" in schema:
        for item in value:  # the first item that breaks the bound speaks for the list
            found = list(_check(schema["items"], item, f"{path}[]", param))
            if found:
                yield from found
                return


def _object(
    schema: Mapping[str, Any], value: Mapping[str, object], path: str, param: str
) -> Iterator[ParamDefect]:
    for name in schema.get("required", ()):
        if value.get(name) is None:
            yield _defect(param or name, "required", path, name, missing=not path)
    properties: Mapping[str, Any] = schema.get("properties", {})
    for name, sub in properties.items():
        if value.get(name) is not None:
            yield from _check(sub, value[name], f"{path}.{name}" if path else name, param or name)
    if schema.get("additionalProperties", True) is False and any(
        k not in properties for k in value
    ):
        yield _defect(param, "additionalProperties", path, ", ".join(properties))


def param_defects(schema: Mapping[str, object], params: Mapping[str, object]) -> list[ParamDefect]:
    """Every defect of an action's `params` against its `params_schema`: the required parameters
    first, then each declared one in the schema's order, then a key it does not declare."""
    return list(_check(schema, params, "", ""))


__all__ = ["ANNOTATIONS", "KEYWORDS", "MAX_NUMBER_TEXT", "TYPES", "ParamDefect", "param_defects"]
