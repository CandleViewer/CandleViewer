"""Single home of the E12 read caps, REST and WS (E12 STRIDE SR-E12-01/02/03, #398 scope
addition; SR-E12-07, #399).

`docs/security/threat-models/E12-bars.md` proposes these numbers; an assert test pins them so a
change is a reviewed diff, never a drive-by. Routes import from here, never restate a number.
"""

from __future__ import annotations

from typing import Final

#: `BarLimit` (22-api): rows per page.
MAX_LIMIT: Final = 5_000
DEFAULT_LIMIT: Final = 1_000
#: SR-E12-01: a page whose JSON body would exceed this is `422 response_too_large`, not truncated.
RESPONSE_MAX_BYTES: Final = 2 * 1024 * 1024
#: SR-E12-01: every storage read behind a bars/klines request is bounded by this.
QUERY_TIMEOUT_S: Final = 2.0
#: SR-E12-02: window caps. Time bars: <= 400 d; non-time bars: <= 31 d.
MAX_TIME_WINDOW_US: Final = 400 * 86_400 * 1_000_000
MAX_NON_TIME_WINDOW_US: Final = 31 * 86_400 * 1_000_000
MAX_WINDOW_BARS: Final = 250_000
#: The most bars one WS `bars` snapshot read takes (`BarReader.read_tail`): the topic's `history`
#: maximum. The wire range is 0..1000 (`23-ws-protocol.md` §6.1, §13; the caller skips a 0), and
#: SR-E12-07 caps it at 1000. The window caps above bound a series further, so `history` is only
#: an upper bound: a snapshot holds at most what the window holds, about 800 bars for 12h, 400
#: for 1d, 57 for 1w, the last 31 d of a non-time kind (`21-database-schema.md` §9.5).
MAX_TAIL: Final = 1_000
#: The most WS series tail reads that run at once, process-wide (C-2.18; `bars.series_store`, #2787
#: D2-G1). Every `SeriesStore` on the event loop shares them, and a read that cannot take a slot
#: within `QUERY_TIMEOUT_S` fails like any timed-out read and is read again by a later `ensure`,
#: so the process-wide series cap never turns into one read per series at once (BR-38: snapshot
#: storms against the read path). It is 8, not 16 (ruling D-G2 on #2787 D2-G3): the shared reader
#: connection serialises every query, so a REST read waits behind the first reads in flight. G3
#: measured that REST read at 638 ms behind 16 and 320 ms behind 8 (medians); a first read that
#: cannot start in time retries on a later `ensure`. Revisit the number if the reader gains a
#: second connection or a pool.
MAX_CONCURRENT_TAIL_READS: Final = 8
#: SR-E12-03: param floors/ceilings per non-time bar type.
TICK_PARAM_RANGE: Final = (100, 1_000_000)
RANGE_TICKS_RANGE: Final = (2, 100_000)
#: Renko shares the range bound (a tiny brick emits bricks per trade); reversal cost <= 10 bricks.
RENKO_TICKS_RANGE: Final = RANGE_TICKS_RANGE
MAX_REVERSAL_BRICKS: Final = 10
#: SR on #2125: one trade may complete at most this many bricks; beyond it the builder raises.
MAX_BRICKS_PER_TRADE: Final = 1_000
QTY_PARAM_MAX: Final = 10**12

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_BRICKS_PER_TRADE",
    "MAX_CONCURRENT_TAIL_READS",
    "MAX_LIMIT",
    "MAX_NON_TIME_WINDOW_US",
    "MAX_REVERSAL_BRICKS",
    "MAX_TAIL",
    "MAX_TIME_WINDOW_US",
    "MAX_WINDOW_BARS",
    "QTY_PARAM_MAX",
    "QUERY_TIMEOUT_S",
    "RANGE_TICKS_RANGE",
    "RENKO_TICKS_RANGE",
    "RESPONSE_MAX_BYTES",
    "TICK_PARAM_RANGE",
]
