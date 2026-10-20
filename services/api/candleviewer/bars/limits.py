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
#: maximum. The wire range is 0..1000 (`23-ws-protocol.md` §6.1, §13), and SR-E12-07 caps it at
#: 1000. The series store's read takes this many whatever a subscriber's `history` (a 0 too). The
#: window caps above bound the read further, so `history` is only an upper bound: the read takes at
#: most what the window holds, about 800 bars for 12h, 400 for 1d, 57 for 1w, the last 31 d of a
#: non-time kind. A series the store keeps also keeps the bars closed since its read, up to this
#: many, so a snapshot of it can hold more than its window holds (`21-database-schema.md` §9.5).
MAX_TAIL: Final = 1_000
#: The most rows of its kind's table a non-time WS tail read looks at (`BarReader.read_tail`,
#: #2787 D2-M4; `23-ws-protocol.md` §6.1). `symbol` has no index, so each statement of the read
#: filters every row of the table from where it starts: the read starts at the later of its
#: window start and the `ts` of the table's `MAX_TAIL_SCAN_ROWS`-th newest row in the window,
#: and a sparse series gets only its bars among those rows. 500 000 is about `MAX_TAIL` bars for
#: each of the 512 series a server builds at most (512 000). Not configurable, and the query
#: builder takes no larger value. Tuning on the target host: a sparse series' cold first read
#: should hold the connection at most 50 ms, this note's own target: half of G3's 100 ms mark for a
#: warm first read (`observability/pgwire_metrics.py`), and the value should not fall far below
#: `MAX_TAIL` times the series the host serves at once. The D2-M4 bench (`D2M4_TAIL_READS=`)
#: prints warm medians at k = 50 000 on tables of the size `D2M2_DENSE_ROWS` sets: a cold read at
#: a candidate value needs the bench's `K` set to it and its first read timed, which it does not
#: do yet. A change is a reviewed diff, and 23 §6.1 carries the value (500 000 as built).
MAX_TAIL_SCAN_ROWS: Final = 500_000
#: The most WS series tail reads that run at once, process-wide (C-2.18; `bars.series_store`, #2787
#: D2-G1). Every `SeriesStore` on the event loop shares them, and a read that cannot take a slot
#: within `QUERY_TIMEOUT_S` fails like any timed-out read and is read again by a later `ensure`,
#: so the process-wide series cap never turns into one read per series at once (BR-38: snapshot
#: storms against the read path). It is 8, not 16 (ruling D-G2 on #2787 D2-G3): on the one
#: connection REST then shared with them, G3 measured a REST read behind 16 first reads at 638 ms
#: and behind 8 at 320 ms (medians). Since D2-G2 the first reads have their own connection
#: (`20-architecture.md` §4.2), where they queue only behind each other: 8 bounds that queue (one
#: runs on QuestDB at a time). A first read that cannot start in time retries on a later `ensure`.
#: Revisit it with `questdb_pgwire_lock_wait_seconds{wire="bars_hydrate"}`.
MAX_CONCURRENT_TAIL_READS: Final = 8
#: How long past the series store's `timeout_s` the heal driver lets a refresh run (#2787 P4b): a
#: read its deadline cut still unwinds through its reader, and `LazyPgWire` gives the cut query's
#: connection up to its `close_timeout_s` (5 s, pinned by a test) to close gracefully; then 1 s of
#: slack. At `QUERY_TIMEOUT_S` a refresh is cut at 8 s, 4 times it.
HEAL_REFRESH_MARGIN_S: Final = 5.0 + 1.0
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
    "HEAL_REFRESH_MARGIN_S",
    "MAX_BRICKS_PER_TRADE",
    "MAX_CONCURRENT_TAIL_READS",
    "MAX_LIMIT",
    "MAX_NON_TIME_WINDOW_US",
    "MAX_REVERSAL_BRICKS",
    "MAX_TAIL",
    "MAX_TAIL_SCAN_ROWS",
    "MAX_TIME_WINDOW_US",
    "MAX_WINDOW_BARS",
    "QTY_PARAM_MAX",
    "QUERY_TIMEOUT_S",
    "RANGE_TICKS_RANGE",
    "RENKO_TICKS_RANGE",
    "RESPONSE_MAX_BYTES",
    "TICK_PARAM_RANGE",
]
