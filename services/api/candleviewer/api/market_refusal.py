"""One place a bars/klines REST refusal is counted and logged (#452 F4a, SR-E12-03).

`note_refused` increments `api_request_rejected_total{route,reason}` and
`bars_endpoint_param_rejected_total{reason}` and writes one structured
WARN, `market_request_refused`, naming the route, the reason, the status and the user-supplied
values the route was refused for. Those values are attacker-controlled, so each one is cut to
`MAX_VALUE_CHARS` and ASCII-escaped (`ascii()`: newlines, control and bidi characters, and every
non-ASCII character become visible escapes), which also stops log-line forgery. An int, such as
a length, is logged as is. Nothing else about the request (session, headers, cookies, cursor
payloads) is ever passed in or logged.
"""

from __future__ import annotations

from typing import Any, Final

import structlog

from candleviewer.bars.metrics import record_param_rejected, record_rejected

#: The longest a user-supplied value is logged; anything past it is dropped, marked by `...`.
MAX_VALUE_CHARS: Final = 32


#: Keys whose value the server itself resolved (never the client): logged as is. `route` and
#: `reason` are fixed by the caller and are not `values` at all.
TRUSTED_KEYS: Final = frozenset({"user_id"})


def escape_value(value: object) -> str:
    """`value` as a bounded, ASCII-only, single-line string, safe to put in a log field."""
    text = str(value)
    cut = text[:MAX_VALUE_CHARS]
    escaped = ascii(cut)
    return escaped + "..." if len(text) > MAX_VALUE_CHARS else escaped


def note_refused(route: str, reason: str, status: int, **values: object) -> None:
    """Count one refusal of `route` (`bars` | `klines`) and log it once."""
    record_param_rejected(reason)  # the original per-reason series, kept for dashboards
    record_rejected(route, reason)
    fields: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        if key in TRUSTED_KEYS:
            fields[key] = str(value)
        else:
            fields[key] = value if isinstance(value, int) else escape_value(value)
    structlog.get_logger(__name__).warning(
        "market_request_refused", route=route, reason=reason, status=status, **fields
    )


__all__ = ["MAX_VALUE_CHARS", "TRUSTED_KEYS", "escape_value", "note_refused"]
