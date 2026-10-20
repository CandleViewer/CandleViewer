"""What the WS option tests share (E13-T02, #426): a value for each option a family requires, which
a test that judges other options fills in (`test_ws_parser_fuzz.py`, `test_option_value_types.py`).
"""

from __future__ import annotations

from typing import Any, Final

from candleviewer.ws.topics import TopicFamily

#: A value each option a family requires takes: `indicators`' `instances` (23 §6.1).
REQUIRED_FILL: Final[dict[str, Any]] = {"instances": [{"indicator": "rsi"}]}


def required_fill(family: TopicFamily, *, omit: str | None = None) -> dict[str, Any]:
    """`REQUIRED_FILL`'s value for each option `family` requires, `omit` aside. A registry change
    that makes an option required with no value here fails naming it, not with a bare KeyError."""
    unknown = sorted(set(family.required) - set(REQUIRED_FILL))
    assert not unknown, (
        f"`{family.family}` now requires {unknown}: give each a valid value in REQUIRED_FILL "
        f"({__name__})"
    )
    return {name: REQUIRED_FILL[name] for name in sorted(family.required) if name != omit}
