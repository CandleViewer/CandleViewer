"""#2223: `BookEngine.anchor_snapshot`, the book the recorder writes as a periodic seek anchor.

The anchor is stamped with the last applied event's exchange time and sequence, never the time
of the snapshot the book was built from: a seek re-applies the deltas recorded after it, and the
`(ts, symbol, depth)` DEDUP key must not land on an older anchor (24-internal-schemas.md §13.7).
"""

from __future__ import annotations

from candleviewer.book.resync import BookEngine

from ._builders import delta, lvl, snap


async def _nothing() -> None:
    """A resubscribe that does nothing."""


async def _drop(_obj: object) -> None:
    """A publish that drops."""


def engine() -> BookEngine:
    return BookEngine(
        symbol="BTCUSDT", depth=200, publish=_drop, resubscribe=_nothing, now_us=lambda: 999_999
    )  # fmt: skip


async def test_anchor_snapshot_is_none_until_live() -> None:
    e = engine()
    assert e.anchor_snapshot() is None
    await e.start()
    assert e.anchor_snapshot() is None


async def test_anchor_snapshot_carries_the_last_applied_delta_stamp_and_the_full_book() -> None:
    e = engine()
    await e.start()
    await e.on_event(snap(10, [lvl(99, 1)], [lvl(101, 1)]))
    await e.on_event(delta(11, 10, [lvl(98, 2)]))
    await e.on_event(delta(12, 11, [], [lvl(102, 3)]))

    a = e.anchor_snapshot()

    assert a is not None
    assert (a.ts_event, a.ts_ingest, a.ts_match, a.cross_seq, a.update_id) == (12, 12, 12, 12, 12)
    assert [x.price_ticks for x in a.bids] == [99, 98] and [x.price_ticks for x in a.asks] == [
        101,
        102,
    ]


async def test_anchor_snapshot_right_after_live_is_stamped_as_its_snapshot() -> None:
    e = engine()
    await e.start()
    await e.on_event(snap(10, [lvl(99, 1)], [lvl(101, 1)]))

    a = e.anchor_snapshot()

    assert a is not None and (a.ts_event, a.update_id, a.cross_seq) == (10, 10, 10)


async def test_anchor_snapshot_after_buffered_deltas_carries_the_last_buffered_stamp() -> None:
    """Deltas buffered while the snapshot was pending are applied by `go_live`, not by a frame:
    the stamp is still the exchange's (never the engine's wall clock)."""
    e = engine()
    await e.start()
    await e.on_event(delta(11, 10, [lvl(98, 2)]))
    await e.on_event(delta(12, 11, [lvl(97, 2)]))
    await e.on_event(snap(10, [lvl(99, 1)], [lvl(101, 1)]))

    a = e.anchor_snapshot()

    assert a is not None and (a.ts_event, a.update_id) == (12, 12)


async def test_anchor_snapshot_is_none_after_a_desync() -> None:
    e = engine()
    await e.start()
    await e.on_event(snap(10, [lvl(99, 1)], [lvl(101, 1)]))
    await e.on_event(delta(13, 12, [lvl(98, 1)]))  # sequence break

    assert e.anchor_snapshot() is None
