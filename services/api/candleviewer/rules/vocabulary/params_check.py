"""The closed JSON Schema subset an action's `params_schema` is written in, and its check (#5963).

A rule's action parameters are checked against their published bounds at save, as an indicator's
are against its descriptor (`orderflow.indicators.catalogue.validate_params`, the pattern this
follows): `validate_rule` runs `param_defects` on each action, so validate, compile, a save and
arming answer alike. The subset is closed: a catalogue schema writes only `KEYWORDS` and
`ANNOTATIONS`, a `type` of `TYPES` and a boolean `additionalProperties`, and a unit test fails
anything else, so no bound is published that this does not read.

- A number is an `int`, a finite `float` or a finite `Decimal`, never a `bool`, compared exactly
  (a float at its shortest repr); an integer is a number without a fraction. Decimal text counts
  as its number (the #5963 ruling: the IR carries decimal text, and the rule handlers read it):
  ASCII digits with an optional sign, point and exponent, nothing around them, inside the range a
  rule can hold (`plain_decimal`, as the content hash reads a number). Other text, `NaN`, an
  infinity and a number past that range are no number.
- `maxLength` counts a text's characters (code points).
- A property holding `null` is absent, as the validator's `required` check has always read it.
- A defect names its parameter and the bound it breaks, from the schema alone: never the value,
  nor a key the schema does not declare.
"""

from __future__ import annotations

import decimal
import math
import operator
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from candleviewer.domain.plain_decimal import PlainWidthError, plain_decimal

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
#: Each numeric bound: the relation a value must hold to it, in words and as a test.
_BOUNDS: Final = (
    ("exclusiveMinimum", "greater than", operator.gt),
    ("minimum", "at least", operator.ge),
    ("exclusiveMaximum", "less than", operator.lt),
    ("maximum", "at most", operator.le),
)
#: Decimal text: ASCII digits with an optional sign, point and exponent. Linear to match.
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


def _number(value: object) -> Decimal | None:
    """A finite number as an exact `Decimal`, decimal text as its number, else `None` (module
    docstring; a `bool` is no number here)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value)) if math.isfinite(value) else None
    if isinstance(value, Decimal) and value.is_finite():
        return value
    if isinstance(value, str) and _DECIMAL_TEXT.fullmatch(value):
        try:  # an exponent past the decimal module's range raises; past a rule's, plain_decimal
            number = Decimal(value)
            plain_decimal(number)  # the range a rule can hold, as the content hash reads it
        except (PlainWidthError, decimal.DecimalException):
            return None
        return number
    return None


def _is(kind: str, value: object) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "object":
        return isinstance(value, Mapping)
    if kind == "array":
        return isinstance(value, list | tuple)
    number = _number(value)
    if kind == "integer":
        return number is not None and number == number.to_integral_value()
    return kind == "number" and number is not None  # a type outside the subset holds nothing


def _same(value: object, member: object) -> bool:
    return value == member and isinstance(value, bool) == isinstance(member, bool)


def _check(schema: Mapping[str, Any], value: Any, path: str, param: str) -> Iterator[ParamDefect]:
    """`value`'s defects against `schema`; `path` is where it is (`qty`, `stop_loss.value`, or
    `symbols[]` for an item) and `param` the parameter it is in."""
    where = f"each item of '{path[:-2]}'" if path.endswith("[]") else f"'{path or 'params'}'"
    kind = schema.get("type")
    if kind is not None and not _is(kind, value):
        yield ParamDefect(param, "type", f"{where} must be {TYPES.get(kind, kind)}")
        return
    if "enum" in schema and not any(_same(value, m) for m in schema["enum"]):
        choices = ", ".join(str(m) for m in schema["enum"])
        yield ParamDefect(param, "enum", f"{where} must be one of {choices}")
    # A number, or decimal text where the schema asks for a number: the bounds read its number.
    number = _number(value) if not isinstance(value, str) or kind in _NUMERIC else None
    for keyword, words, holds in _BOUNDS:
        bound = _number(schema.get(keyword))
        if number is not None and bound is not None and not holds(number, bound):
            yield ParamDefect(param, keyword, f"{where} must be {words} {schema[keyword]}")
    longest = schema.get("maxLength")
    if isinstance(value, str) and isinstance(longest, int) and len(value) > longest:
        yield ParamDefect(param, "maxLength", f"{where} must be at most {longest} characters")
    if isinstance(value, Mapping):
        yield from _object(schema, value, path, param)
    elif isinstance(value, list | tuple) and "items" in schema:
        for item in value:  # the first item that breaks the bound speaks for the list
            found = list(_check(schema["items"], item, f"{path}[]", param))
            if found:
                yield from found
                return


def _object(
    schema: Mapping[str, Any], value: Mapping[str, Any], path: str, param: str
) -> Iterator[ParamDefect]:
    where = f"'{path or 'params'}'"
    for name in schema.get("required", ()):
        if value.get(name) is None:
            text = f"{where} is missing '{name}'"
            yield ParamDefect(param or name, "required", text, missing=not path)
    properties: Mapping[str, Any] = schema.get("properties", {})
    for name, sub in properties.items():
        if value.get(name) is not None:
            yield from _check(sub, value[name], f"{path}.{name}" if path else name, param or name)
    if schema.get("additionalProperties", True) is False and any(
        k not in properties for k in value
    ):
        yield ParamDefect(
            param, "additionalProperties", f"{where} takes only {', '.join(properties)}"
        )


def param_defects(schema: Mapping[str, Any], params: Mapping[str, Any]) -> list[ParamDefect]:
    """Every defect of an action's `params` against its `params_schema`: the required parameters
    first, then each declared one in the schema's order, then a key it does not declare."""
    return list(_check(schema, params, "", ""))


__all__ = ["ANNOTATIONS", "KEYWORDS", "TYPES", "ParamDefect", "param_defects"]
