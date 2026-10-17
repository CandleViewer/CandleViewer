"""Free-text hygiene for request fields: refuse text that Postgres cannot store.

Request fields that are stored or audited refuse U+0000 and lone surrogates, which Postgres
`text`/`jsonb` refuse, through each endpoint's existing validation error. Dependency-free, so
every module may import it (see the package docstring).
"""

from __future__ import annotations

#: The validation message: it never echoes the input.
UNSTORABLE_TEXT = "must not contain U+0000 or an unpaired surrogate"


def refuse_unstorable_text(value: str) -> str:
    """Field validator: `value` unchanged, or `ValueError` if it holds U+0000 or a lone
    surrogate. A value that is not a `str` is returned unchanged."""
    if not isinstance(value, str):
        return value
    if "\x00" in value:
        raise ValueError(UNSTORABLE_TEXT)
    if not value.isascii():
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError(UNSTORABLE_TEXT) from None
    return value
