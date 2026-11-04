"""The body reader of the five alert writes that take one (E40-X01, #5696; 22 "Alert write bounds
and refusal records"), in this order: at most `MAX_ALERT_BODY_BYTES` before the body is buffered
whole (`rule_body.read_capped`: a declared length over it refused unread, a stream one chunk past
it), else 413 `payload_too_large`; strict UTF-8 without a byte order mark (RFC 8259 section
8.1); nested at most `MAX_ALERT_JSON_DEPTH` deep, scanned before anything decodes the text, else
422 `json_too_deep`; decoded; at most `MAX_ALERT_VALUES` values (each object, array and scalar,
not the keys, as `check_bounds` counts them) before it is validated, else 422 `too_many_values`.
Text that is not UTF-8 JSON (a byte order mark included) raises `ValueError`, the route's own
422. No refusal here writes an audit record: each is counted through `on_refused(reason)`, a
`REFUSAL_REASONS` value, before it is raised.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Final

from fastapi import Request

from candleviewer.alerts.compiler import MAX_DEPTH
from candleviewer.api.alerts_http import Problem
from candleviewer.api.rule_body import _TOO_LARGE, read_capped
from candleviewer.ws.limits import json_depth_exceeds

#: The body ceiling of the five alert writes (22: 64 KiB). A typical alert holds about 20 values
#: in under 500 bytes, and one at the value bound fits with room for its strings. With the value
#: bound it keeps the widest admissible alert's save under the loop budget (C-2.17).
MAX_ALERT_BODY_BYTES: Final = 64 * 1024
#: The deepest body the alert compiler takes: a variable's arithmetic chain down to its walker's
#: `MAX_DEPTH`, ending in a metric with `params`. The body is level 1, `condition_ir` 2,
#: `variables` 3 and the variable's operand (walker depth 1) 4; each arithmetic step adds two
#: (`operands` and the operand), so walker depth `MAX_DEPTH` sits at `2 * MAX_DEPTH + 2` and its
#: `params` one deeper. A condition's own nesting tops out two levels shallower.
MAX_ALERT_JSON_DEPTH: Final = 2 * MAX_DEPTH + 3
#: The values one alert body may hold (22: 2,048).
MAX_ALERT_VALUES: Final = 2048
_INVALID: Final = "Invalid body"
#: `cv_alert_write_refused_total{reason}`: the closed label set (the write rate's included).
REFUSAL_REASONS: Final = ("body_too_large", "json_too_deep", "too_many_values", "rate_limited")
#: Counts one refusal by its `REFUSAL_REASONS` value.
OnRefused = Callable[[str], None]


def values_over(doc: object, limit: int) -> bool:
    """True when `doc` holds more than `limit` values (each object, array and scalar, the document
    included; keys are not values). Every value stacked and every child of the one at hand is
    still to be counted, so a container is refused by its length before its children are
    stacked, as `rules.compiler.common.check_bounds` refuses one: the stack never outgrows the
    bound."""
    stack, count = [doc], 0
    while stack:
        cur = stack.pop()
        count += 1
        wide = len(cur) if isinstance(cur, (dict, list)) else 0
        if count + len(stack) + wide > limit:
            return True
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return False


def _invalid(rule: str, message: str, on_refused: OnRefused) -> Problem:
    on_refused(rule)
    return Problem(422, "validation_failed", _INVALID, message,
                   errors=[{"field": "", "rule": rule, "message": message}])  # fmt: skip


async def read_alert_body(request: Request, on_refused: OnRefused) -> object:
    """The decoded body of an alert write, read in the module docstring's order."""
    raw = await read_capped(request, MAX_ALERT_BODY_BYTES)
    if raw is None:
        on_refused("body_too_large")
        raise Problem(413, "payload_too_large", _TOO_LARGE,
                      f"The request body exceeds {MAX_ALERT_BODY_BYTES} bytes.")  # fmt: skip
    text = raw.decode("utf-8")  # `UnicodeDecodeError` is a `ValueError`: the route's 422
    if json_depth_exceeds(text, MAX_ALERT_JSON_DEPTH):
        msg = f"JSON nesting is deeper than {MAX_ALERT_JSON_DEPTH} levels."
        raise _invalid("json_too_deep", msg, on_refused)
    body = json.loads(text)
    if values_over(body, MAX_ALERT_VALUES):
        msg = f"The body holds more than {MAX_ALERT_VALUES} values."
        raise _invalid("too_many_values", msg, on_refused)
    return body


__all__ = [
    "MAX_ALERT_BODY_BYTES",
    "MAX_ALERT_JSON_DEPTH",
    "MAX_ALERT_VALUES",
    "REFUSAL_REASONS",
    "OnRefused",
    "read_alert_body",
    "values_over",
]
