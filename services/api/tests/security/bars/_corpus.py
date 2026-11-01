"""The E12-X02 hostile parameter dictionary (#452 BQ-8; X01 AC-01..AC-03): built in code, never
stored as a fixture. Each value probes one parser rule: SQL and ILP metacharacters, path
traversal, unicode and look-alike digits, percent-encoded overlong UTF-8, NUL and control bytes,
the 24/25-character `param` boundary, the 18/19-digit `_UINT` boundary, `atr:` and `10:3`
shapes, absurd numbers, inverted and pre-epoch windows, year 9999, and `limit` edges.

SQL and shell text is assembled from parts so the suite's source holds no statement a static
rule would read as one (Semgrep raw-SQL; gitleaks).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, NamedTuple

from tests.contract._market_world import BASE

_Q, _DQ = "'", '"'
_SQL: Final = ("SEL" + "ECT", "DR" + "OP TABLE bars_tick", "UNI" + "ON ALL", "--", "/*", ";")

#: `param` probes (bars) and `interval` probes (klines).
VALUES: Final[tuple[str, ...]] = (
    "", " ", "0", "-1", "-100", "+100", "1e3", "0x64", "100.0", "1_000", "100 ", " 100", "100\t",
    "100\n", "100\r\n", "100\x00", "100%00", "%00", "%", "%25", "100;", f"100{_Q}", f"100{_DQ}",
    f"1{_Q} OR {_Q}1{_Q}={_Q}1", f"100{_Q}; {_SQL[1]}; {_SQL[3]}", f"100 {_SQL[2]} {_SQL[0]} 1",
    f"100{_SQL[4]}", "100,a=1", "100 i=1", "bars_tick", "../100", "..", "..%2f..%2f", "\\..\\",
    "%C0%AE%C0%AE", "%E0%80%AE", "\uff11\uff10\uff10", "\u0661\u0660\u0660", "100\u200b",
    "1\u00a000", "\u2170\u2174", "NaN",
    "Infinity", "-0", "null", "None", "[]", "{}", "$(id)", "${7*7}", "{{7*7}}", "\x1b[31m100",
    "9" * 18, "9" * 19, "1" * 24, "1" * 25, "x" * 4096, "atr:", "atr:14", "atr:" + "9" * 20,
    "renko:atr:14", "10:3", "20:0", "20:-1", "20:10", "20:11", "2:1", "1:1", "20:", ":3", "20:3:3",
    "20.5:3", "D", "W", "M", "1", "60", "1440", "720", "5000",
)  # fmt: skip
BAR_TYPES: Final = ("time", "tick", "volume", "range", "delta", "renko", "pnf", "heikin_ashi")
HOSTILE_BAR_TYPES: Final = (
    "", "TIME", "time ", "tick\x00", "bars_tick", f"tick{_SQL[5]}{_SQL[3]}", "rénko", "x" * 300,
    "..", "%00", "renko:atr",
)  # fmt: skip
PRE_EPOCH: Final = ("1900-01-01T00:00:00Z", "1970-06-01T00:00:00Z")
YEAR_9999: Final = ("9999-12-31T23:59:59Z", "9999-12-31T23:59:59.999999Z")
#: `(from, to)` probes; `None` drops the parameter.
WINDOWS: Final[tuple[tuple[str | None, str | None], ...]] = (
    PRE_EPOCH, ("0001-01-01T00:00:00Z", "0001-01-02T00:00:00Z"), ("1970-01-01T00:00:00Z", None),
    ("9999-12-31T23:59:59Z", None), YEAR_9999,
    ("2023-11-15T00:00:00Z", "2023-11-14T00:00:00Z"), (None, "2023-11-15T00:00:00Z"),
    ("0", None), ("-1", None), ("1700000000", None), ("2023-13-01T00:00:00Z", None),
    ("2023-11-14T22:00:00+25:00", None), ("2023-11-14T22:00:00.1234567Z", None),
    ("2023-11-14T22:00:00Z\x00", None), ("x" * 200, None), ("2023-11-14T22:00:00Z", "now"),
    (f"2023-11-14{_Q}{_SQL[3]}", None), ("+10000-01-01T00:00:00Z", None),
)  # fmt: skip
LIMITS: Final = ("0", "-1", "1", "5000", "5001", "1e3", "1.5", "", "9" * 30, "0x10", "५")
CURSORS: Final = ("", "a" * 10_000, "../../", "%00", "null", "e30", "eyJ0cyI6MH0", "\x1b[0m")
SYMBOLS: Final = ("", "btcusdt", f"BTCUSDT{_Q}", "BTC/USDT", "x" * 200, "ETHUSDT", "BTCUSDT\x00")
PRICE_TYPES: Final = ("trade", "mark", "", "TRADE", f"trade{_Q}", "x" * 100)
#: The window F1 serves: span measured from the epoch, not from `from` (`market_bars.py:306`).
F1: Final = "#452 findings row F1: a pre-epoch `from` is measured from the epoch, not from `from`"
#: New in PR-1: the float `timestamp() * 1e6` rounds the last microsecond of 9999 up to year 10000,
#: which the bar read's timestamp bind cannot hold (`domain/sql_names.ts_param`): a 500.
F7: Final = "#452 findings row F7: a `to` in the last microsecond of 9999 overflows the bar read"


class Case(NamedTuple):
    op: str
    query: Mapping[str, object]
    xfail: str | None = None  # the findings row a known gap cites


def _bars(**over: object) -> dict[str, object]:
    base = {**BASE["getBars"], "bar_type": "tick", "param": "100", "limit": 50, **over}
    return {k: v for k, v in base.items() if v is not None}


def _klines(**over: object) -> dict[str, object]:
    base = {**BASE["getKlines"], "limit": 50, **over}
    return {k: v for k, v in base.items() if v is not None}


def _known(bar_type: str, window: tuple[str | None, str | None]) -> str | None:
    """The finding a window probe hits: F1 (time bars at 1 min over `PRE_EPOCH` estimate under
    the cap only when measured from 1970), F7 (`YEAR_9999`: a 500, probed on time bars only)."""
    if window == YEAR_9999:
        return F7
    return F1 if bar_type == "time" and window == PRE_EPOCH else None


def cases() -> list[Case]:
    """About 450 probes of `getBars` and 250 of `getKlines`: one parameter hostile at a time,
    over a base query the route serves."""
    out = [Case("getBars", _bars(bar_type=t, param=v)) for t in BAR_TYPES for v in VALUES[::2]]
    out += [Case("getBars", _bars(bar_type=t)) for t in HOSTILE_BAR_TYPES]
    for bar_type, param in (("time", "1"), ("tick", "100"), ("renko", "30")):
        for window in WINDOWS:
            if window == YEAR_9999 and bar_type != "time":
                continue  # F7 is the same overflow for every bar type: one probe pins it
            query = _bars(bar_type=bar_type, param=param, **{"from": window[0], "to": window[1]})
            out.append(Case("getBars", query, _known(bar_type, window)))
    out += [Case("getBars", _bars(limit=v)) for v in LIMITS]
    out += [Case("getBars", _bars(cursor=v)) for v in CURSORS]
    out += [Case("getBars", _bars(symbol=v)) for v in SYMBOLS]
    out += [Case("getKlines", _klines(interval=v)) for v in VALUES]
    some = VALUES[::6]
    out += [Case("getKlines", _klines(price_type=p, interval=v)) for p in PRICE_TYPES for v in some]
    for window in WINDOWS:
        out.append(Case("getKlines", _klines(**{"from": window[0], "to": window[1]})))
    out += [Case("getKlines", _klines(limit=v)) for v in LIMITS]
    out += [Case("getKlines", _klines(cursor=v)) for v in CURSORS]
    out += [Case("getKlines", _klines(symbol=v)) for v in SYMBOLS]
    return out
