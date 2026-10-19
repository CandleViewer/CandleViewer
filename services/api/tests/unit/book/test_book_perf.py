"""Per-delta cost of the book hot path (E08-S05, 2 ms p95 budget, C-13.9).

* `test_book_engine_per_delta_work_is_constant_in_stream_length` (unit,
  deterministic): fake clock + operation counting. The work per delta is
  bounded by the delta's own level count and the tier bound, never by how
  many deltas came before (no rescans, no interpreter, one publish).
* `test_book_engine_apply_p95_under_2ms` (`perf`): wall-clock p95 over 10k
  deltas from a fixed-seed synthetic book.
"""

from __future__ import annotations

import random
import time

import pytest

from candleviewer.book import state as book_state
from candleviewer.book.resync import BookEngine
from candleviewer.exchange.base.models import BookDelta, BookLevel

from ._builders import delta, lvl, snap

N_DELTAS = 10_000
DEPTH = 200
P95_BUDGET_S = 0.002


def _stream(seed: int, n: int) -> tuple[list[object], list[BookDelta]]:
    """Fixed-seed synthetic book: 200 levels per side around 100_000 ticks,
    then `n` uncrossed deltas of 1-6 upserts/deletes."""
    rng = random.Random(seed)  # noqa: S311 - deterministic test data, not crypto
    mid = 100_000
    bids = [lvl(mid - 1 - i, rng.randint(1, 50)) for i in range(DEPTH)]
    asks = [lvl(mid + 1 + i, rng.randint(1, 50)) for i in range(DEPTH)]
    out: list[BookDelta] = []
    for k in range(n):
        u = 11 + k
        b = [
            lvl(mid - 1 - rng.randrange(DEPTH), rng.randint(0, 50))
            for _ in range(rng.randint(0, 3))
        ]
        a = [
            lvl(mid + 1 + rng.randrange(DEPTH), rng.randint(0, 50))
            for _ in range(rng.randint(0, 3))
        ]
        out.append(delta(u, u - 1, b, a, depth=DEPTH))
    return [snap(10, bids, asks, depth=DEPTH)], out


class _Counts:
    def __init__(self) -> None:
        self.publish = 0
        self.resub = 0
        self.edges = 0

    async def pub(self, _ev: object) -> None:
        self.publish += 1

    async def resubscribe(self) -> None:
        self.resub += 1

    async def sink(self, _event: str) -> None:
        self.edges += 1


async def _live_engine(c: _Counts, first: object) -> BookEngine:
    clock = iter(range(10**9))
    e = BookEngine(
        symbol="BTCUSDT", depth=DEPTH, publish=c.pub, resubscribe=c.resubscribe,
        now_us=lambda: next(clock),
    )  # fmt: skip
    e.health_sink = c.sink
    await e.start()
    await e.on_event(first)  # type: ignore[arg-type]
    return e


async def test_book_engine_per_delta_work_is_constant_in_stream_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ops = {"n": 0}
    real_up, real_del = book_state._Side.upsert, book_state._Side.delete

    def up(self: book_state._Side, lv: object) -> None:
        ops["n"] += 1
        real_up(self, lv)  # type: ignore[arg-type]

    def dl(self: book_state._Side, lv: BookLevel) -> None:
        ops["n"] += 1
        real_del(self, lv)

    monkeypatch.setattr(book_state._Side, "upsert", up)
    monkeypatch.setattr(book_state._Side, "delete", dl)

    c = _Counts()
    snaps, deltas = _stream(seed=1714, n=2_000)
    e = await _live_engine(c, snaps[0])
    base_pub, base_edges, base_resub = c.publish, c.edges, c.resub
    for d in deltas:
        before = ops["n"]
        await e.on_event(d)
        # one side op per level in *this* delta, independent of history
        assert ops["n"] - before == len(d.bids) + len(d.asks)
        assert e.book is not None and len(e.book._bids) <= 2 * DEPTH
    assert c.publish - base_pub == len(deltas)  # exactly one publish per delta
    assert c.edges == base_edges and c.resub == base_resub  # no supervisor/resync work
    assert e.last_u == deltas[-1].update_id


@pytest.mark.perf
async def test_book_engine_apply_p95_under_2ms() -> None:
    c = _Counts()
    snaps, deltas = _stream(seed=1714, n=N_DELTAS)
    e = await _live_engine(c, snaps[0])
    lat: list[float] = []
    for d in deltas:
        t0 = time.perf_counter()
        await e.on_event(d)
        lat.append(time.perf_counter() - t0)
    lat.sort()
    p95 = lat[int(0.95 * len(lat)) - 1]
    print(f"[perf][E08-S05] book delta p95 over {len(lat)}: {p95 * 1e6:.1f} us (budget 2000 us)")
    assert len(lat) >= 10_000
    assert e.last_u == deltas[-1].update_id
    assert p95 < P95_BUDGET_S
