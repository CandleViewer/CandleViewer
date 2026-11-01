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


def check(op: str, query: Mapping[str, object], resp: httpx.Response) -> None:
    """Assert the oracle for one answer of `op` (`getBars` or `getKlines`) to `query`."""
    status, body = resp.status_code, resp.text
    assert status in STATUSES, (status, body[:300])
    assert _LEAK.search(body) is None, body[:300]
    for name, value in query.items():
        if len(text := str(value)) > ECHO_MAX:
            assert text not in body, f"{name} echoed"
    if status != 200:
        problem = resp.json()
        assert problem["code"] in CODES, problem
        assert problem["status"] == status, problem
        return
    assert len(body.encode("utf-8")) <= RESPONSE_MAX_BYTES  # the served bytes (UTF-8 JSON)
    span = requested_span_us(op, query)
    kind = str(query.get("bar_type", "time"))
    if kind != "time":
        assert span <= MAX_NON_TIME_WINDOW_US, ("non-time span", span)
        return
    assert span <= MAX_TIME_WINDOW_US, ("time span", span)
    interval = str(query.get("param" if op == "getBars" else "interval"))
    if interval in _TIME_WIDTH_US and op == "getBars":
        assert -(-span // _TIME_WIDTH_US[interval]) <= MAX_WINDOW_BARS, ("bars", span)
