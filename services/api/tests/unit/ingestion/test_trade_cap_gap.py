"""B10 / F6-2 (#3876, decision on #35): a public-trade frame refused over the cap leaves a gap.

The cap (`MAX_PRINTS_PER_BATCH`, the E08-X02 control) still refuses such a frame whole, counted and
logged, and now also opens a gap at the last published print, as a print rejected after publish does
(`test_rejected_trade_after_publish_marks_gap`): the next accepted batch publishes one `gap` event.
Oversized frames repeat the print entries of a recorded capture (C-13.5); no shape is invented.
"""

from __future__ import annotations

import json
from typing import Any

from structlog.testing import capture_logs

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy
from candleviewer.exchange.base.trade_print import MAX_PRINTS_PER_BATCH
from candleviewer.exchange.bybit.trades import parse_trade_frame, trade_topic
from candleviewer.ingestion import metrics
from candleviewer.ingestion.trade_stream import GapEvent, TradeStream
from tests._corpus import corpus_path, frames

RECORDED = frames("ws/recorded_publicTrade_BTCUSDT.jsonl")  # live capture, up to 12 prints/frame
#: Every public-trade capture in the corpus (C-13.5).
PUBLIC_TRADE = sorted(f"ws/{p.name}" for p in corpus_path("ws").glob("*publicTrade_*.jsonl"))
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def _oversized(frame: str) -> str:
    """`frame` with its recorded print entries repeated to one past the cap."""
    msg = json.loads(frame)
    rows = msg["data"]
    msg["data"] = [rows[i % len(rows)] for i in range(MAX_PRINTS_PER_BATCH + 1)]
    return json.dumps(msg, separators=(",", ":"))


def _ts(frame: str) -> list[int]:
    return [p.ts_event_us for p in parse_trade_frame(frame) or ()]


def _rejections() -> tuple[float, float]:
    labelled = metrics.ingest_rejected_total.labels(stream="trade", reason="malformed")
    return float(metrics.trade_prints_rejected_total._value.get()), float(labelled._value.get())


def _drained(sub: Any) -> list[Any]:
    return [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]


class _Tape:
    """One `TradeStream` demanding every corpus symbol, its tape and gap topics drained."""

    def __init__(self) -> None:
        self.bus = Bus()
        self.prints = self.bus.subscribe(
            "t", "live.md.*.trade", QueuePolicy.NEVER_DROP, maxsize=10_000
        )
        self.gaps = self.bus.subscribe("g", "live.md.*.gap", QueuePolicy.NEVER_DROP)
        self.stream = TradeStream(
            bus=self.bus,
            env="live",
            set_desired=lambda _t: None,
            parse_frame=parse_trade_frame,
            topic_for=trade_topic,
            is_listed=lambda s: s in SYMBOLS,
            touch=lambda _t: None,
            clock=lambda: 0.0,
            now_us=lambda: 1_792_391_740_000_000,
        )
        for symbol in SYMBOLS:
            self.stream.acquire("tape", symbol)

    async def feed(self, *frames_in: str) -> None:
        for frame in frames_in:
            await self.stream.handle_frame(frame)
            await self.stream.wait_backfills()


async def test_a_frame_over_the_cap_is_still_counted_and_logged_and_now_marks_one_gap() -> None:
    tape = _Tape()
    await tape.feed(RECORDED[0])
    before = _rejections()
    with capture_logs() as logs:
        await tape.feed(_oversized(RECORDED[1]))

    assert _rejections() == (before[0] + 1, before[1] + 1)
    assert logs == [
        {
            "event": "trade frame rejected",
            "stream": "trade",
            "reason": "malformed",
            "error": "FrameRejectedError",  # was `ValueError`: the refusal now carries its symbol
            "suppressed": 0,
            "log_level": "warning",
        }
    ]
    assert tape.stream.open_gaps() == {"BTCUSDT": (max(_ts(RECORDED[0])), "rejected_frame")}
    assert _drained(tape.gaps) == []  # the window's own close publishes the marker

    await tape.feed(RECORDED[2])
    (gap,) = _drained(tape.gaps)
    assert (gap.symbol, gap.reason, gap.recovered) == ("BTCUSDT", "rejected_frame", False)
    assert (gap.start_us, gap.end_us) == (max(_ts(RECORDED[0])), min(_ts(RECORDED[2])))


async def test_the_refused_frames_gap_is_built_as_for_a_print_rejected_after_publish() -> None:
    """Same window, same event: only `event_id` differs (one UUID7 each)."""
    rejected = json.loads(RECORDED[1])
    rejected["data"][0]["p"] = "1e308"  # one implausible print: refused after publish (E08-X02)
    gaps: list[GapEvent] = []
    for refused in (json.dumps(rejected), _oversized(RECORDED[1])):
        tape = _Tape()
        await tape.feed(RECORDED[0], refused, RECORDED[2])
        gaps += _drained(tape.gaps)

    after_publish, over_cap = gaps
    assert after_publish.model_dump(exclude={"event_id"}) == over_cap.model_dump(
        exclude={"event_id"}
    )
    assert after_publish.event_id != over_cap.event_id


async def test_a_flood_of_frames_over_the_cap_leaves_one_gap_per_window() -> None:
    """Refusals while a window is open fold into it: one marker, one backfill, per window."""
    tape = _Tape()
    await tape.feed(RECORDED[0])
    before = _rejections()
    backfills = metrics.trade_backfill_rows_total.labels(result="unavailable")  # no fetcher
    tried = float(backfills._value.get())
    await tape.feed(*(_oversized(f) for f in RECORDED[1:4]))
    await tape.feed(RECORDED[4])

    assert _rejections() == (before[0] + 3, before[1] + 3)
    assert float(backfills._value.get()) == tried + 1
    (gap,) = _drained(tape.gaps)
    assert (gap.start_us, gap.end_us) == (max(_ts(RECORDED[0])), min(_ts(RECORDED[4])))


async def test_a_frame_over_the_cap_before_any_published_print_marks_no_gap() -> None:
    """As after publish: a gap opens at the last published print, so before the first there is
    no tape to resync (the first accepted batch starts it)."""
    tape = _Tape()
    await tape.feed(_oversized(RECORDED[0]), RECORDED[1])

    assert tape.stream.open_gaps() == {} and _drained(tape.gaps) == []
    assert len(_drained(tape.prints)) == len(_ts(RECORDED[1]))


async def test_the_recorded_public_trade_frames_replay_with_no_refusal_and_no_gap() -> None:
    corpus = [frame for rel in PUBLIC_TRADE for frame in frames(rel)]
    ids = {(p.symbol, p.trade_id) for frame in corpus for p in parse_trade_frame(frame) or ()}
    tape = _Tape()
    before = _rejections()
    await tape.feed(*corpus)

    assert max(len(_ts(frame)) for frame in corpus) <= MAX_PRINTS_PER_BATCH
    assert _rejections() == before
    assert _drained(tape.gaps) == [] and tape.stream.open_gaps() == {}
    assert {(e.symbol, e.trade_id) for e in _drained(tape.prints)} == ids
