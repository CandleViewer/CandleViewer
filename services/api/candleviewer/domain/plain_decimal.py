"""A decimal in plain notation, no wider than ``MAX_PLAIN_WIDTH`` characters.

The rule IR hashes every number as its plain decimal string, and writes a number param as the same
string. Both go through ``plain_decimal``, which refuses a number whose form would be wider than the
bound. The width is worked out from the number's leading exponent and digit count, before the form
is built. Dependency-free, like the rest of this package.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

#: The most characters (sign, digits and decimal point) a number's plain form may take.
MAX_PLAIN_WIDTH: Final = 64
_TOO_WIDE: Final = f"a number's plain form is wider than {MAX_PLAIN_WIDTH} characters"


class PlainWidthError(ValueError):
    """A number whose plain form would be wider than ``MAX_PLAIN_WIDTH`` characters."""


def plain_decimal(d: Decimal) -> str:
    """``d`` with no exponent, no trailing fractional zeros, no ``+``, ``-0`` as ``0``, rounded as
    ``Decimal.normalize`` rounds it (to the context's precision).

    Raises ``PlainWidthError`` if the form would be wider than ``MAX_PLAIN_WIDTH`` characters. That
    covers every number outside the context's exponent range. ``normalize`` raises what the context
    traps: ``decimal.InvalidOperation`` for a signalling NaN.
    """
    if d == 0:
        return "0"
    # Rounding only ever raises the leading exponent, by one at most. So a number whose leading
    # digit lies this far out is too wide whatever it rounds to, and is refused unnormalised.
    if not -MAX_PLAIN_WIDTH < d.adjusted() < MAX_PLAIN_WIDTH:
        raise PlainWidthError(_TOO_WIDE)
    normal = d.normalize()
    sign, digits, _ = normal.as_tuple()
    count, lead = len(digits), normal.adjusted()
    if lead >= 0:  # lead + 1 integer digits, then a point and the rest if any digits remain
        width = sign + max(lead + 1, count) + (count > lead + 1)
    else:  # "0.", then -lead - 1 zeros, then the digits
        width = sign + 1 + count - lead
    if width > MAX_PLAIN_WIDTH:
        raise PlainWidthError(_TOO_WIDE)
    return format(normal, "f")
