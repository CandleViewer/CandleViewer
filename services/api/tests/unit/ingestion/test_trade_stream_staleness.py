"""#2487: `TradeStream.is_stale`, the freshness of a symbol's tape that the WS `bars` and
`indicators` snapshots read (`ws_wiring.series_stale`). It ages the moment the watchdog is touched
(a frame for a demanded symbol) against the watchdog's own `trade` limit: no new SLO. It fails
closed: a demanded symbol whose tape has delivered no frame yet is stale. Recorded corpus, fake
clock, no network (C-13.5, C-13.7)."""

from __future__ import annotations

from candleviewer.bus.bus import Bus
from candleviewer.exchange.bybit.trades import parse_trade_frame
from candleviewer.ingestion.planner import DEFAULT_GRACE_S
from candleviewer.ingestion.trade_stream import TRADE_STALE_AFTER_S, TradeStream
from candleviewer.ingestion.watchdog import STALENESS_S
from tests._corpus import frames

SYM = "BTCUSDT"
TRADES = frames("ws/publicTrade_BTCUSDT.jsonl")  # BTCUSDT prints


class _Rig:
    def __init__(self) -> None:
        self.t = 100.0
        self.touched: list[str] = []
        self.stream = TradeStream(
            bus=Bus(), env="live", set_desired=lambda _t: None, parse_frame=parse_trade_frame,
            topic_for=lambda s: f"t.{s}", is_listed=lambda _s: True, touch=self.touched.append,
            clock=lambda: self.t, now_us=lambda: 0,
        )  # fmt: skip


def test_trade_stale_limit_is_the_watchdogs_trade_limit() -> None:
    assert TRADE_STALE_AFTER_S == STALENESS_S["trade"]


def test_is_stale_without_demand_is_true() -> None:
    assert _Rig().stream.is_stale(SYM) is True


async def test_is_stale_until_the_first_frame_then_ages_from_each_frame_the_watchdog_sees() -> None:
    rig = _Rig()
    rig.stream.acquire("ws", SYM)
    assert rig.stream.is_stale(SYM) is True  # demanded, no frame yet: nothing is fresh
    rig.t += TRADE_STALE_AFTER_S - 0.001
    assert rig.stream.is_stale(SYM) is True  # no grace window with no upstream
    await rig.stream.handle_frame(TRADES[0])
    assert rig.touched == [f"t.{SYM}"]  # the same moment the watchdog is touched
    rig.t += TRADE_STALE_AFTER_S - 0.001
    assert rig.stream.is_stale(SYM) is False
    rig.t += 0.001
    assert rig.stream.is_stale(SYM) is True  # at the limit, as the watchdog's `>=`
    await rig.stream.handle_frame(TRADES[1])
    assert rig.stream.is_stale(SYM) is False  # the tape resumed


async def test_a_frame_for_an_undemanded_symbol_does_not_make_it_fresh() -> None:
    rig = _Rig()
    await rig.stream.handle_frame(TRADES[0])
    assert rig.stream.is_stale(SYM) is True and rig.touched == []


async def test_a_symbol_that_left_demand_is_forgotten_and_a_new_demand_waits_for_a_frame() -> None:
    rig = _Rig()
    rig.stream.acquire("ws", SYM)
    await rig.stream.handle_frame(TRADES[0])
    rig.stream.release("ws", SYM)
    rig.t += DEFAULT_GRACE_S
    rig.stream.sync()  # the grace ran out: the symbol left demand, its last frame forgotten
    assert rig.stream.is_stale(SYM) is True
    rig.stream.acquire("ws", SYM)
    assert rig.stream.is_stale(SYM) is True  # a new demand is fresh only from its first frame
    await rig.stream.handle_frame(TRADES[1])
    assert rig.stream.is_stale(SYM) is False


async def test_a_reacquire_in_grace_keeps_the_last_frames_age() -> None:
    """Demand that never lapsed keeps its last frame: a tape silent past the limit stays stale."""
    rig = _Rig()
    rig.stream.acquire("ws", SYM)
    await rig.stream.handle_frame(TRADES[0])
    rig.stream.release("ws", SYM)
    rig.t += TRADE_STALE_AFTER_S
    rig.stream.acquire("ws", SYM)
    assert rig.stream.is_stale(SYM) is True
