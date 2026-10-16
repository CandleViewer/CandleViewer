"""Six-character strings that `str.isdigit()` accepts but that are not ASCII digits (#2605).

Each one passed the old `verify_code` guard (`isdigit()` and `len == 6`) and then made
`hmac.compare_digest(str, str)` raise `TypeError`, which it does for any non-ASCII text. They are
written as code points, so this file stays ASCII and no editor or linter has to tell them apart
from the Latin digits.
"""

from __future__ import annotations

import pytest


def _six_digits_from(zero: int) -> str:
    """`123456` written with the decimal digits of a script whose zero is code point *zero*."""
    return "".join(chr(zero + digit) for digit in (1, 2, 3, 4, 5, 6))


ARABIC_INDIC_CODE = _six_digits_from(0x0660)

#: Superscript one to six (U+00B9, U+00B2, U+00B3, U+2074..U+2076) and circled one to six
#: (U+2460..U+2465): `isdigit()` but not `isdecimal()`, so `int()` refuses them as well.
_SUPERSCRIPT = "".join(chr(cp) for cp in (0x00B9, 0x00B2, 0x00B3, 0x2074, 0x2075, 0x2076))
_CIRCLED = "".join(chr(0x2460 + offset) for offset in range(6))

NON_ASCII_DIGIT_CODES = [
    pytest.param(ARABIC_INDIC_CODE, id="arabic-indic"),
    pytest.param(_six_digits_from(0x06F0), id="extended-arabic-indic"),
    pytest.param(_six_digits_from(0x0966), id="devanagari"),
    pytest.param(_six_digits_from(0xFF10), id="fullwidth"),
    pytest.param(_SUPERSCRIPT, id="superscript"),
    pytest.param(_CIRCLED, id="circled"),
    pytest.param("12345" + chr(0x0666), id="five-ascii-and-one-arabic-indic"),
]
