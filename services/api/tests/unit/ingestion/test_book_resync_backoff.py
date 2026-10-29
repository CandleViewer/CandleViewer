"""Per-symbol resync backoff (#1898 review r2): a rejected-frame storm cannot hammer snapshots."""

from __future__ import annotations

from decimal import Decimal

from candleviewer.book.models import BookPhase
from candleviewer.bus.bus import Bus
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.ingestion.metrics import ingest_book_resyncs_total
from candleviewer.orderbook_wiring import RESYNC_BACKOFF_CAP_S, RESYNC_STABLE_S, BookStream
from tests._corpus import corpus_path

FRAMES = corpus_path("ws/orderbook_BTCUSDT.jsonl").read_text(encoding="utf-8").splitlines()
BAD_DELTA = (
    '{"topic":"orderbook.200.BTCUSDT","type":"delta","ts":1,"data":{"s":"BTCUSDT","u":3,'
    '"b":[["NaN","1"]],"a":[]}}'
)


def _tick(_s: str) -> Decimal:
    return Decimal("0.1")


class Rig:
    def __init__(self) -> None:
        self.t = 0.0
        self.resubs: list[str] = []

        async def resub(topic: str) -> None:
            self.resubs.append(topic)

        self.stream = BookStream(
            bus=Bus(),
            env="live",
            set_desired=lambda _t: None,
            parse_frame=lambda f: parse_book_frame(f, _tick),
            topic_for=book_topic,
            resubscribe=resub,
            is_listed=lambda s: s == "BTCUSDT",
            touch=lambda _t: None,
            clock=lambda: self.t,
            now_us=lambda: 0,
            rand=lambda: 0.0,  # no jitter: exact doubling
        )
        self.stream.acquire("c", "BTCUSDT")

    async def go_live(self) -> None:
        for f in FRAMES[:3]:
            await self.stream.handle_frame(f)
        assert self.stream.phase("BTCUSDT") is BookPhase.LIVE


def _backoffs() -> float:
    return ingest_book_resyncs_total.labels(
        symbol="BTCUSDT", reason="backoff", depth="200"
    )._value.get()  # type: ignore[attr-defined,no-any-return]


async def test_one_bad_frame_resyncs_immediately() -> None:
    r = Rig()
    await r.go_live()
    n = len(r.resubs)
    await r.stream.handle_frame(BAD_DELTA)
    assert r.stream.phase("BTCUSDT") is BookPhase.SNAPSHOT_PENDING
    assert len(r.resubs) == n + 1
    await r.stream.stop()


async def _cycle(r: Rig) -> None:
    """The venue re-sends a good snapshot, then another bad delta arrives."""
    await r.stream.handle_frame(FRAMES[0])
    await r.stream.handle_frame(BAD_DELTA)


async def test_storm_is_bounded_and_marked_stale() -> None:
    r = Rig()
    await r.go_live()
    before = _backoffs()
    start = len(r.resubs)
    for _ in range(40):  # 40 snapshot/bad-delta cycles inside one second
        r.t += 0.025
        await _cycle(r)
    assert len(r.resubs) - start <= 3  # 250 ms then 500 ms steps -> bounded requests
    assert r.stream.view("BTCUSDT", 50) is None  # stale: no book served
    assert r.stream.phase("BTCUSDT") is not BookPhase.LIVE
    assert _backoffs() > before
    await r.stream.stop()


async def test_backoff_doubles_caps_and_stable_live_resets() -> None:
    r = Rig()
    await r.go_live()
    await r.stream.handle_frame(BAD_DELTA)  # first resync creates the gate
    bo = r.stream._backoff["BTCUSDT"]
    eng = r.stream._books["BTCUSDT"].active
    gaps: list[float] = []
    for _ in range(14):
        r.t = bo.next_ok + 1.0  # always just past the cooldown
        before = len(r.resubs)
        await eng.request_snapshot()
        assert len(r.resubs) == before + 1
        gaps.append(bo.next_ok - r.t)
    assert gaps[:3] == [0.5, 1.0, 2.0] or gaps[:3] == [0.25, 0.5, 1.0]
    assert gaps[1] == 2 * gaps[0] and max(gaps) == RESYNC_BACKOFF_CAP_S  # doubling, capped
    # a good snapshot that then stays LIVE for the stability window resets it
    await r.stream.handle_frame(FRAMES[0])
    assert r.stream.phase("BTCUSDT") is BookPhase.LIVE
    r.t += RESYNC_STABLE_S + 1
    await r.stream.handle_frame(BAD_DELTA)
    assert r.stream.phase("BTCUSDT") is BookPhase.SNAPSHOT_PENDING  # immediate resync again
    assert bo.fails == 1
    await r.stream.stop()


async def test_deferred_snapshot_is_requested_when_cooldown_elapses() -> None:
    r = Rig()
    await r.go_live()
    await r.stream.handle_frame(BAD_DELTA)  # first resync: allowed
    n = len(r.resubs)
    await r.stream._books["BTCUSDT"].active.request_snapshot()
    assert len(r.resubs) == n and "BTCUSDT" in r.stream._deferred
    r.t += 60.0
    assert await r.stream.check_timeouts() == 1
    assert len(r.resubs) == n + 1
    await r.stream.stop()
