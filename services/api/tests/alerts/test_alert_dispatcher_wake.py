"""E40-T04 PR-B (review round 1): a firing that commits while the dispatcher is polling is polled
at once, not at the next `interval_s`. `PR-B`'s `WakingFiringStore` promises its in-app row is
visible within 250 ms; that holds only if a `notify()` during a poll survives the poll."""

from __future__ import annotations

import asyncio
from typing import Any

from _dispatch_env import Clock, MemStore

from candleviewer.alerts.dispatcher import AlertDispatcher, default_adapters


async def test_a_firing_that_commits_during_a_poll_is_polled_again_at_once() -> None:
    clock = Clock()
    store = MemStore(clock)
    delivered = asyncio.Event()
    claims = 0
    real_claim = store.claim

    async def claim(**kw: Any) -> list[Any]:
        nonlocal claims
        claims += 1
        jobs = await real_claim(**kw)
        if claims == 1:  # the poll has looked: a firing commits and wakes the loop mid-poll
            store.fire(["in_app"])
            d.notify()
        return jobs

    async def on_change(_ids: Any) -> None:
        delivered.set()

    store.claim = claim  # type: ignore[method-assign]  # fault injection
    d = AlertDispatcher(
        store, default_adapters(None), worker="w", now=clock, rng=lambda: 1.0,
        on_change=on_change, interval_s=3600,
    )  # fmt: skip
    d.start()
    try:
        await asyncio.wait_for(delivered.wait(), timeout=5)  # an hour's wait would never end
    finally:
        await d.stop()
    assert store.rows[1].status == "sent" and claims == 2  # the second poll took it, no third
