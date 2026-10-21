"""The closed style vocabulary of an indicator preset (E13-T03, #427; SR-E13-08, IR-09, IR-14).

`style` maps a style key to a design-token name, both from closed sets: the keys, and for each
key the token names E13-D04 publishes. A key or a value outside them is refused (422 rule
`style_not_allowed`), never dropped, so no colour, CSS, URL or free text is stored or handed to a
renderer, and no `__proto__` or `constructor` key reaches a client object (IR-14).

E13-D04 has not published its list, so the vocabulary is empty and only `{}` validates (ruling
Q1; 22 `IndicatorPresetStyle`). Data-driven: when the list ships, `STYLE_VOCABULARY` (with its
pin test) and 22's schema gain the keys, additively, and nothing else changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

#: style key -> the design-token names it may take. Empty until E13-D04 publishes the list.
STYLE_VOCABULARY: Final[Mapping[str, frozenset[str]]] = MappingProxyType({})


def style_defect(style: Mapping[str, object]) -> str | None:
    """Why `style` is outside the vocabulary, in words that quote no submitted key or value;
    None when every key is known and takes one of its tokens."""
    for key, value in style.items():
        allowed = STYLE_VOCABULARY.get(key)
        if allowed is None:
            if not STYLE_VOCABULARY:
                return "style takes no keys until the indicator style tokens are published."
            return "style has a key outside the indicator style vocabulary."
        if not isinstance(value, str) or value not in allowed:
            return f"style.{key} must be one of its design tokens."
    return None


__all__ = ["STYLE_VOCABULARY", "style_defect"]
