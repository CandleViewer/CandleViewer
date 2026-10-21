"""Shared recorded-exchange fixture corpus + replay harness (E08-T05, 24-internal-schemas §14.2).

Every E08 test reads exchange payloads from `packages/fixtures/<exchange>/<capture-date>/`
through this module, so all tickets assert against the same inputs (C-13.5, no
network). `replay()` drives the production parser entry points the socket path
uses (`parse_trade_frame`, `parse_ticker_frame`, `parse_book_frame` — the same
functions `TradeStream`/`TickerStream`/`BookStream.handle_frame` call), never a
parallel decoder. Timing is deterministic: inter-frame gaps come from the
envelope `ts`, scaled by `speed`, and are slept on an injected (fake) clock.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Awaitable, Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.orderbook import parse_book_frame

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.ticker import parse_ticker_frame

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.trades import parse_trade_frame

CAPTURE_DATE = "2026-10-05"
# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
CORPUS_ROOT = Path(__file__).resolve().parents[3] / "packages" / "fixtures" / "bybit"
#: Tick sizes for the corpus symbols (mirrors `rest/instruments_before.json`).
TICKS: dict[str, Decimal] = {
    "BTCUSDT": Decimal("0.1"),
    "ETHUSDT": Decimal("0.01"),
    "SOLUSDT": Decimal("0.010"),
}


def corpus_path(rel: str, *, capture_date: str = CAPTURE_DATE) -> Path:
    """Absolute path of a corpus file; an old test may pin an older `capture_date`."""
    return CORPUS_ROOT / capture_date / rel


def manifest(*, capture_date: str = CAPTURE_DATE) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(corpus_path("manifest.json", capture_date=capture_date)
                                      .read_text(encoding="utf-8"))  # fmt: skip
    return data


def frames(rel: str, *, capture_date: str = CAPTURE_DATE) -> list[str]:
    """Raw WS frames of a `.jsonl` corpus file, exactly as received."""
    text = corpus_path(rel, capture_date=capture_date).read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.strip()]


def rest(rel: str, *, capture_date: str = CAPTURE_DATE) -> Any:
    """Decoded body of a REST corpus response."""
    return json.loads(corpus_path(rel, capture_date=capture_date).read_text(encoding="utf-8"))


def http_status(rel: str, *, capture_date: str = CAPTURE_DATE) -> int:
    """The recorded HTTP status of a REST corpus file; a docs-transcribed file states none."""
    for entry in manifest(capture_date=capture_date)["fixtures"]:
        if entry["path"] == rel:
            if entry["http_status"] is None:
                raise ValueError(f"{rel} states no HTTP status: its source shows none")
            return int(entry["http_status"])
    raise KeyError(rel)


def _tick(symbol: str) -> Decimal | None:
    return TICKS.get(symbol)


def normalize(frame: str) -> list[object]:
    """Run one raw frame through the production parser owning its topic (the same
    parser the socket pump reaches; the others would return `None` for it)."""
    # nosemgrep: cv-bybit-vocabulary-leak,cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31  # noqa: E501 - semgrep marker format is fixed
    if '"topic":"publicTrade.' in frame:
        return list(parse_trade_frame(frame) or ())
    if '"topic":"tickers.' in frame:
        ticker = parse_ticker_frame(frame)
        return [] if ticker is None else [ticker]
    book = parse_book_frame(frame, _tick)
    if book is not None:
        return [book]
    # Non-compact JSON (no fast-path match): fall back to every parser.
    ticker = parse_ticker_frame(frame)
    return [ticker] if ticker is not None else list(parse_trade_frame(frame) or ())


def encode(event: object) -> bytes:
    """Canonical bytes of a domain event. `event_id` is excluded: it is a per-ingest
    UUID minted by design, not derived from the frame (24-internal-schemas §1)."""
    if isinstance(event, BaseModel):
        body = event.model_dump(mode="json", exclude={"event_id"})
    elif dataclasses.is_dataclass(event) and not isinstance(event, type):
        body = dataclasses.asdict(event)
    else:
        raise TypeError(f"not a domain event: {type(event).__name__}")
    body["__type__"] = type(event).__name__
    return json.dumps(body, default=str, sort_keys=True, separators=(",", ":")).encode()


def _envelope_ts(frame: str) -> int | None:
    try:
        ts = json.loads(frame).get("ts")
    except (ValueError, AttributeError):
        return None
    return ts if isinstance(ts, int) else None


class FakeClock:
    """Virtual clock: `sleep` advances time instantly (no wall-clock wait, C-13.7)."""

    def __init__(self) -> None:
        self.now_s = 0.0
        self.sleeps: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now_s += seconds


async def replay(
    raw_frames: list[str],
    *,
    sink: Callable[[str], Awaitable[None]] | None = None,
    speed: float = 0.0,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> list[object]:
    """Replay frames in order; return the normalized domain-event sequence.

    `sink` (e.g. `TradeStream.handle_frame`) receives every raw frame, so stream
    consumers are exercised exactly as the socket pump would. `speed` scales the
    recorded inter-frame gap (`1.0` = real time, `10.0` = 10x, `0` = no pacing);
    pacing sleeps on `sleep` (pass `FakeClock().sleep` in tests).
    """
    if speed < 0:
        raise ValueError("speed must be >= 0")
    if speed > 0 and sleep is None:
        raise ValueError("a paced replay needs an injected sleep (use FakeClock)")
    events: list[object] = []
    prev: int | None = None
    for frame in raw_frames:
        ts = _envelope_ts(frame) if speed > 0 else None
        if speed > 0 and sleep is not None and prev is not None and ts is not None:
            gap_ms = ts - prev
            if gap_ms > 0:
                await sleep(gap_ms / 1000.0 / speed)
        if ts is not None:
            prev = ts
        if sink is not None:
            await sink(frame)
        events.extend(normalize(frame))
    return events


def event_stream_bytes(events: list[object]) -> bytes:
    return b"\n".join(encode(e) for e in events)


def iter_corpus_files(*, capture_date: str = CAPTURE_DATE) -> Iterator[Path]:
    for entry in manifest(capture_date=capture_date)["fixtures"]:
        yield corpus_path(entry["path"], capture_date=capture_date)
