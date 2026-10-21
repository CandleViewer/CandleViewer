"""E17-T08: `B14BookSupervisor` feeds `machines.book:{symbol}.state` (23 §6.4), an unscoped kind:
the entry is the symbol's whatever the tier's key, it follows the health edges, and a detach
removes it (the stop is a task, so it lands once the loop turns)."""

from __future__ import annotations

from candleviewer.ingestion.book_supervisor import B14BookSupervisor
from candleviewer.ws.topics import EntityScope
from tests.unit.ingestion._fakes import settle
from tests.unit.ws._feed_support import Feed

CH, KEY = "machines.book:BTCUSDT.state", "live:BTCUSDT:50"


async def test_a_book_publishes_its_symbols_entry_and_a_detach_removes_it() -> None:
    feed = Feed()
    supervisor = B14BookSupervisor(feed=feed.port)
    sink = await supervisor.attach(KEY, "BTCUSDT")
    served = feed.served(CH)
    assert served is not None and served["state"] == "init"
    assert feed.registry.scope(CH) == EntityScope()  # no accounts, no user: an unscoped kind
    await sink("SUBSCRIBE")
    await sink("SNAPSHOT")
    await settle(64)
    served = feed.served(CH)
    assert served is not None and (served["state"], served["tags"]) == ("live", ["consumable"])
    assert served["context_summary"] == {"symbol": "BTCUSDT", "resync_count": 0}
    assert feed.scope_missing() == 0  # an unscoped kind has no scope to miss
    supervisor.detach(KEY)
    await settle(64)
    assert feed.served(CH) is None


async def test_a_newer_chart_of_the_symbol_keeps_the_entry_when_the_older_one_stops() -> None:
    """A re-attach of the symbol (a new engine) publishes first; the old chart's spawned stop then
    finds the newer owner's entry and leaves it: one live machine of the entity."""
    feed = Feed()
    supervisor = B14BookSupervisor(feed=feed.port)
    await supervisor.attach(KEY, "BTCUSDT")
    await supervisor.attach("live:BTCUSDT:200", "BTCUSDT")
    supervisor.detach(KEY)  # the older chart stops, in a task
    await settle(64)
    assert feed.served(CH) is not None and len(feed.registry) == 1  # the newer chart's, still
