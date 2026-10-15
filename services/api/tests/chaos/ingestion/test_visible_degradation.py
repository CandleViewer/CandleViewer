"""Cross-scenario AC "Degradation is visible, not silent" (E08-Q03).

For every fault that cannot fully auto-recover inside its window, the end
state must carry a staleness/desync signal on the affected topic AND the
health endpoint must report degraded. Wrong-and-silent is a P0 failure.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig

pytestmark = pytest.mark.chaos


async def _refused_forever(rig: Rig, feed: Feeder) -> None:
    rig.ex.inject(Fault(FaultKind.REFUSE, count=10_000))
    rig.ex.inject(Fault(FaultKind.RESET))
    await feed.run(20.0)


async def _stalled_forever(rig: Rig, feed: Feeder) -> None:
    rig.ex.inject(Fault(FaultKind.REFUSE, count=10_000))
    rig.ex.inject(Fault(FaultKind.STALL))
    await feed.run(20.0)


UNRECOVERABLE: dict[str, Callable[[Rig, Feeder], Awaitable[None]]] = {
    "exchange-refuses": _refused_forever,
    "stall-then-refuse": _stalled_forever,
}


async def _run(rig: Rig, name: str) -> None:
    feed = Feeder(rig.ex)
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    await feed.run(3.0)
    rig.observe()
    await UNRECOVERABLE[name](rig, feed)


@pytest.mark.parametrize("name", sorted(UNRECOVERABLE))
async def test_unrecovered_fault_leaves_a_topic_signal(rig: Rig, name: str) -> None:
    await _run(rig, name)
    seen = rig.observe()
    book = [f.state for f in seen.feed if f.topic == "orderbook.200.BTCUSDT"]
    no_signal = f"{name}: no degraded/stale signal on orderbook.200.BTCUSDT (feed states: {book})"
    assert book and book[-1] in ("degraded", "stale"), no_signal
    assert rig.ws.state() != "open", f"{name}: socket still open after an unrecovered fault"
    assert rig.books.view("BTCUSDT", 200) is None or rig.book_phase() is not None


@pytest.mark.parametrize("name", sorted(UNRECOVERABLE))
async def test_unrecovered_fault_reports_degraded_health(rig: Rig, name: str) -> None:
    await _run(rig, name)
    health = rig.health_report()
    assert health == "degraded", f"{name}: health reports {health!r}, expected 'degraded'"
