"""E21-X02 (#652; 23 §16.2): the deep `book.*` weight's rows, measured on the recorded capture.

A deep book weighs ⌈rows x publishes a second ÷ the point⌉, rows being the mean count of levels
one depth-200 publish changes (`ws/limits.py` `DEEP_BOOK_ROWS_PER_PUBLISH`). This replays the
recorded BTCUSDT depth-200 capture (`packages/fixtures/bybit/2026-10-05/ws/orderbook_BTCUSDT.jsonl`,
documented-shape under exception #1778 A: a `u` hole at frame 2700 and a reset at 4000) through the
book engine and its depth-200 publisher (`book/ws_topic.py`) on a fake clock at the capture's own
times, counts the levels of every `d` it publishes, and pins the constant as their mean taken up to
a whole row: the band is (constant - 1, constant]. Nothing is synthesised; depth 500 is the
extrapolation the constant's note names (no depth-500 capture exists)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from candleviewer.book.models import BookPhase
from candleviewer.book.resync import BookEngine
from candleviewer.book.snapshot_source import BookSnapshotSource
from candleviewer.book.ws_topic import WINDOW_S, BookTopic
from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.models import BookLevel
from candleviewer.ws.limits import (
    DEEP_BOOK_MEASURED_DEPTH,
    DEEP_BOOK_PUBLISHES_PER_S,
    DEEP_BOOK_ROWS_PER_PUBLISH,
)
from tests._corpus import frames
from tests.unit.book._builders import delta, snap

RECORDED = "ws/orderbook_BTCUSDT.jsonl"
TICK = Decimal("0.1")


@dataclass(frozen=True)
class _T:
    symbol: str | None
    depth: int | None


@dataclass
class _Sub:
    ch: str = f"book.BTCUSDT.{DEEP_BOOK_MEASURED_DEPTH}"
    topic: _T = _T("BTCUSDT", DEEP_BOOK_MEASURED_DEPTH)
    replay_session_id: str | None = None
    snapshot_pending: bool = True
    ended: bool = False


@dataclass
class _Hub:
    """The hub's calls the publisher makes; each `d`'s level count is kept."""

    sub: _Sub
    levels: list[int] = field(default_factory=list)

    def subscriptions(self, ch: str) -> Sequence[_Sub]:
        return [self.sub] if ch == self.sub.ch else []

    def publish(self, ch: str, body: Mapping[str, Any] | None = None, **_: Any) -> int:
        assert body is not None
        self.levels.append(len(body["bids"]) + len(body["asks"]))
        return 1

    def upstream_desync(self, symbol: str) -> int:
        self.sub.snapshot_pending = True  # a desync re-snaps the subscription
        return 0

    def flush_pending(self, match: Any = None) -> int:
        return 0


def _level(price: str, qty: str) -> BookLevel:
    return BookLevel(price=Decimal(price), qty=Decimal(qty), price_ticks=int(Decimal(price) / TICK))


def _body(
    structured: Mapping[str, Any],
    records: tuple[tuple[int, int, int], ...],
    trailer: tuple[int, int],
    *,
    price_scale: int,
    qty_scale: int,
    stale: bool,
) -> Mapping[str, Any]:
    return structured


async def _publishes() -> list[int]:
    """The level count of every depth-200 `d` the recorded capture makes the publisher send."""
    out: list[object] = []
    now = [0.0]

    async def publish(ev: object) -> None:
        out.append(ev)

    async def resubscribe() -> None:
        return None

    eng = BookEngine(
        symbol="BTCUSDT", depth=DEEP_BOOK_MEASURED_DEPTH, publish=publish,
        resubscribe=resubscribe, now_us=lambda: 0, incidents=True,
    )  # fmt: skip
    await eng.start()
    hub = _Hub(_Sub())
    source: BookSnapshotSource[Mapping[str, Any]] = BookSnapshotSource(
        {"BTCUSDT": eng}.get, lambda _s: (TICK, Decimal("0.001")), _body
    )
    topic = BookTopic(
        source, hub.subscriptions, hub.publish, hub.upstream_desync, hub.flush_pending,
        lambda r, ps, qs: r, bus=Bus(), env="live", clock=lambda: now[0],
    )  # fmt: skip
    records = [json.loads(f) for f in frames(RECORDED)]
    start, prev = records[0]["ts"], None
    for record in records:
        now[0] = (record["ts"] - start) / 1000  # the capture's own times, on the fake clock
        data = record["data"]
        bids = [_level(p, q) for p, q in data["b"]]
        asks = [_level(p, q) for p, q in data["a"]]
        if record["type"] == "snapshot":
            ev: object = snap(data["u"], bids, asks)
        else:
            ev = delta(data["u"], data["u"] - 1 if prev is None else prev, bids, asks)
        prev = data["u"]
        seen = len(out)
        await eng.on_event(ev)  # type: ignore[arg-type]
        for item in out[seen:]:
            topic.offer(item)
        if hub.sub.snapshot_pending and eng.phase is BookPhase.LIVE:
            hub.sub.snapshot_pending = topic.build(hub.sub) is None  # the subscription's `snap`
        topic.tick()
        now[0] += WINDOW_S[DEEP_BOOK_MEASURED_DEPTH]  # its 100 ms window closes: what is held goes
        topic.tick()
    return hub.levels


async def test_deep_book_rows_are_the_recorded_mean_changed_levels_per_publish() -> None:
    levels = await _publishes()
    mean = Decimal(sum(levels)) / len(levels)
    assert len(levels) > 3_000  # both live stretches of the capture, around its hole and reset
    assert round(mean, 2) == Decimal("4.50")  # 17 936 levels over 3 989 publishes
    assert DEEP_BOOK_ROWS_PER_PUBLISH - 1 < mean <= DEEP_BOOK_ROWS_PER_PUBLISH
    assert (
        DEEP_BOOK_PUBLISHES_PER_S * WINDOW_S[200] == DEEP_BOOK_PUBLISHES_PER_S * WINDOW_S[500] == 1
    )
