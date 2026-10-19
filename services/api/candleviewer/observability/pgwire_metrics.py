"""The QuestDB PG-wire series of `LazyPgWire` (#2787 D2-G2), defined in `observability` so both
`storage` (the wire) and `bars.metrics` (which re-exports them onto the scraped registry) may import
them, as `kline_boundary_metrics`. Every wire has a name from the closed `WireName` set, so `wire`
takes at most 6 values, and 18 series with `reason`."""

from __future__ import annotations

from typing import Final, Literal, get_args

from candleviewer.observability.metrics import Counter, Histogram

#: Each `LazyPgWire` of the process: the bars sink's (the bars writer's probes, REST bars and the
#: klines tape tier), the WS series store's first reads (D2-G2), the disk budget's, the replay
#: read path's (E26-T02, `replay_wiring`), retention's and the roll-off's.
WireName = Literal["bars", "bars_hydrate", "budget", "replay", "retention", "rolloff"]
#: Why a connection was discarded after its query raised: the caller was cancelled during the
#: query (`cancelled`: its own deadline, as the store's or REST's 2 s, or a cancelled subscribe),
#: the wire's `query_timeout_s` fired (`query_timeout`), or anything else (`error`).
DiscardReason = Literal["error", "query_timeout", "cancelled"]
WIRE_NAMES: Final[tuple[WireName, ...]] = get_args(WireName)
DISCARD_REASONS: Final[tuple[DiscardReason, ...]] = get_args(DiscardReason)
#: No wait, up to the 2 s of a REST read or a first read and past them, to the 15 s a waiter with
#: no deadline of its own may wait (a 10 s query, then a 5 s close). 0.1 s is G3's mark for one
#: warm first read's hold of the connection.
LOCK_WAIT_BUCKETS: Final = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 15.0)

questdb_pgwire_discards_total = Counter(
    "questdb_pgwire_discards_total",
    "QuestDB PG-wire connections discarded after their query raised, by wire (reason: error,"
    " query_timeout, cancelled = the caller was cancelled during the query).",
    labelnames=("wire", "reason"),
)
questdb_pgwire_abandoned_total = Counter(
    "questdb_pgwire_abandoned_total",
    "QuestDB PG-wire queries cancelled before they started, waiting for the wire's lock or its"
    " connect, by wire.",
    labelnames=("wire",),
)
questdb_pgwire_lock_wait_seconds = Histogram(
    "questdb_pgwire_lock_wait_seconds",
    "Wait for a QuestDB PG-wire connection's lock before a query, by wire (observed when granted).",
    labelnames=("wire",),
    buckets=LOCK_WAIT_BUCKETS,
)
