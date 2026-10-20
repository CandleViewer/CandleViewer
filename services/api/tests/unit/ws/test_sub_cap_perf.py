"""#415 (E17-X02): the subscription caps are checked in constant time (C-13.9).

One `sub` of 50 entries, each refused at the 40-symbol cap, timed fastest-of-N with GC disabled:
it costs the same whether the 40 symbols are held by 40 subscriptions or by 199, and stays inside
a fixed bound, far above its cost. Deselected by default (`-m perf`).
"""

from __future__ import annotations

import asyncio
import gc
import time
import uuid
from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.ws.permissions import ConnectionAuthz, SubscriptionServices, handle_sub
from candleviewer.ws.upstream import UpstreamRefs

pytestmark = pytest.mark.perf

#: The whole frame (50 refused entries and the reply), in ns: far above its cost on a runner.
BOUND_NS = 2_000_000
#: Held by 199 subscriptions, the frame may cost at most this many times as much as held by 40.
CONSTANT = 1.5
SYMBOLS = [f"S{i:02d}USDT" for i in range(90)]
#: The 40 symbols held by 40 subscriptions, and by 199 (four `book` depths on each, and `trades`).
FEW = [f"trades.{s}" for s in SYMBOLS[:40]]
MANY = [f"book.{s}.{d}" for d in (1, 50, 200, 500) for s in SYMBOLS[:40]] + FEW[:39]
OVER = {"t": "sub", "id": "over", "p": {"topics": [f"trades.{s}" for s in SYMBOLS[40:]]}}


async def _send(frame: dict[str, Any]) -> None:
    """The reply goes nowhere: only the server side is timed."""


async def _at_the_cap(held: list[str]) -> ConnectionAuthz:
    perms = frozenset({Permission.MARKETDATA_READ})
    principal = PrincipalSnapshot(uuid.UUID(int=0x415), frozenset({"viewer"}), perms)
    authz = ConnectionAuthz(principal, SubscriptionServices(upstream=UpstreamRefs()))
    replies: list[dict[str, Any]] = []

    async def keep(frame: dict[str, Any]) -> None:
        replies.append(frame)

    for i in range(0, len(held), 50):
        await handle_sub(authz, {"t": "sub", "p": {"topics": held[i : i + 50]}}, keep)
    assert all(r["ok"] for reply in replies for r in reply["p"]["results"])
    return authz


async def _best_ns(authz: ConnectionAuthz, rounds: int = 15, inner: int = 10) -> float:
    gc.collect()
    gc.disable()
    try:
        best = float("inf")
        for _ in range(rounds):
            t0 = time.perf_counter_ns()
            for _ in range(inner):
                await handle_sub(authz, OVER, _send)
            best = min(best, (time.perf_counter_ns() - t0) / inner)
    finally:
        gc.enable()
    return best


async def measure() -> tuple[float, float]:
    """(ns, ns): the refused frame with the 40 symbols held by 40 subscriptions, then by 199."""
    few, many = await _at_the_cap(FEW), await _at_the_cap(MANY)
    assert (len(few.by_id), len(many.by_id)) == (40, 199)
    return await _best_ns(few), await _best_ns(many)


def test_a_refused_50_entry_sub_at_the_40_symbol_cap_costs_constant_time() -> None:
    few, many = asyncio.run(measure())
    assert 0 < few < BOUND_NS
    assert many < CONSTANT * few  # the subscriptions held do not count
