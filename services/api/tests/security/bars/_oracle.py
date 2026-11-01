"""The E12-X02 response oracle (#452 BQ-8): what every answer of `/market/bars` and
`/market/klines` must satisfy, whatever the query.

- The status is one 22 declares for a refused or served read; a refusal is a `Problem` whose
  `code` is in 22's `x-error-codes` catalogue.
- No body leaks the server: no traceback, no source path, no SQL, no stored table name, and no
  echo of a probe value longer than 32 characters.
- A 200 obeys the caps (SR-E12-01/02): the body is at most 2 MiB, and the requested window is at
  most 400 d (time bars, klines) or 31 d (non-time bars), and for time bars at most 250 000 bars.
  The window is measured as the client asked for it, `from` to `to` (#452 finding F1).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final

import httpx

from candleviewer.bars.limits import (
    MAX_NON_TIME_WINDOW_US,
    MAX_TIME_WINDOW_US,
    MAX_WINDOW_BARS,
    RESPONSE_MAX_BYTES,
)
from candleviewer.bars.spec import TIME_INTERVALS
from tests.contract._generated_contract import SPEC
from tests.contract._market_world import KLINES_NOW_US, NOW

CODES: Final = frozenset(e["code"] for e in SPEC["x-error-codes"])
STATUSES: Final = frozenset({200, 400, 401, 403, 422, 503})
#: Built from parts so the suite's own source holds no SQL statement (Semgrep raw-SQL rule).
_LEAK: Final = re.compile(
    "|".join((r"Traceback", r'File "', r"/candleviewer/", r"\bSEL" + r"ECT\b", r"\bFROM bars_")),
    re.IGNORECASE,
)
ECHO_MAX: Final = 32
_TIME_WIDTH_US: Final = {k: v * 1000 for k, v in TIME_INTERVALS.items()}


def _us(value: object, default: int) -> int:
    if value is None:
        return default
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    parsed = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1_000_000)


def requested_span_us(op: str, query: Mapping[str, object]) -> int:
    """`to - from` as the client asked (`to` defaults to the route's now)."""
    now = NOW if op == "getBars" else KLINES_NOW_US
    return _us(query.get("to"), now) - _us(query["from"], now)


class OracleError(AssertionError):
    """The oracle's refusal of an answer. Each subclass names the rule broken, so a known gap is
    an xfail on exactly that rule (`raises=`), never on any failure."""


class StatusError(OracleError):
    """A status outside `STATUSES` (a 500 included), or a refusal that is no catalogued Problem."""


class LeakError(OracleError):
    """A traceback, source path, SQL or table name, or an echoed probe in the body."""


class SpanCapError(OracleError):
    """A 200 over a cap: the body over 2 MiB, or the requested window over its span or bars."""


def _require(ok: bool, error: type[OracleError], detail: object) -> None:
    if not ok:
        raise error(detail)


def check(op: str, query: Mapping[str, object], resp: httpx.Response) -> None:
    """Check the oracle for one answer of `op` (`getBars` or `getKlines`) to `query`."""
    status, body = resp.status_code, resp.text
    _require(status in STATUSES, StatusError, (status, body[:300]))
    _require(_LEAK.search(body) is None, LeakError, body[:300])
    for name, value in query.items():
        if len(text := str(value)) > ECHO_MAX:
            _require(text not in body, LeakError, f"{name} echoed")
    if status != 200:
        problem = resp.json()
        _require(problem.get("code") in CODES, StatusError, problem)
        _require(problem.get("status") == status, StatusError, problem)
        return
    size = len(body.encode("utf-8"))  # the served bytes (UTF-8 JSON)
    _require(size <= RESPONSE_MAX_BYTES, SpanCapError, ("bytes", size))
    span = requested_span_us(op, query)
    if str(query.get("bar_type", "time")) != "time":
        _require(span <= MAX_NON_TIME_WINDOW_US, SpanCapError, ("non-time span", span))
        return
    _require(span <= MAX_TIME_WINDOW_US, SpanCapError, ("time span", span))
    interval = str(query.get("param" if op == "getBars" else "interval"))
    if interval in _TIME_WIDTH_US and op == "getBars":
        estimate = -(-span // _TIME_WIDTH_US[interval])
        _require(estimate <= MAX_WINDOW_BARS, SpanCapError, ("bars", estimate))
