"""One place a bars/klines REST refusal is counted and logged (#452 F4a, SR-E12-03).

`note_refused` increments `bars_endpoint_param_rejected_total{reason}` and writes one structured
WARN, `market_request_refused`, naming the route, the reason, the status and the user-supplied
values the route was refused for. Those values are attacker-controlled, so each one is cut to
`MAX_VALUE_CHARS` and ASCII-escaped (`ascii()`: newlines, control and bidi characters, and every
non-ASCII character become visible escapes), which also stops log-line forgery. Nothing else
about the request (session, headers, cookies, cursor payloads) is ever passed in or logged.
"""

from __future__ import annotations

from typing import Any, Final

import structlog

from candleviewer.bars.metrics import record_param_rejected

#: The longest a user-supplied value is logged; anything past it is dropped, marked by `...`.
MAX_VALUE_CHARS: Final = 32


def escape_value(value: object) -> str:
    """`value` as a bounded, ASCII-only, single-line string, safe to put in a log field."""
    text = str(value)
    cut = text[:MAX_VALUE_CHARS]
    escaped = ascii(cut)
    return escaped + "..." if len(text) > MAX_VALUE_CHARS else escaped


def note_refused(route: str, reason: str, status: int, **values: object) -> None:
    """Count one refusal of `route` (`bars` | `klines`) and log it once."""
    record_param_rejected(reason)
    fields: dict[str, Any] = {k: escape_value(v) for k, v in values.items() if v is not None}
    structlog.get_logger(__name__).warning(
        "market_request_refused", route=route, reason=reason, status=status, **fields
    )


__all__ = ["MAX_VALUE_CHARS", "escape_value", "note_refused"]
