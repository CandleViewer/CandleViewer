"""E21-T01 (#604): the book topic in the composition root: `create_app` serves `book` from the book
module's publisher and hands it to `WsRuntime`; the deep-book cap and `heatmap_depth_500` reach the
subscription services and the book stream; a `book` upstream reference carries its depth to the
stream's per-(symbol, depth) demand; a window's kind-2 part is a CVWB `book_delta`."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.app import create_app
from candleviewer.book.ws_topic import BookTopic
from candleviewer.orderbook_wiring import BookStream
from candleviewer.ws.binary import BOOK_DELTA, decode, encode
from candleviewer.ws.limits import MAX_DEEP_BOOK_SUBSCRIPTIONS
from candleviewer.ws_wiring import IngestionUpstreamSink, book_delta_part
from tests.unit.ws.test_app_wiring import _settings


def test_create_app_serves_book_from_the_book_topic_with_the_cap_and_the_flag_off() -> None:
    app = create_app(_settings())
    services = app.state.ws_registry.services
    topic = services.snapshots._sources["book"]
    assert isinstance(topic, BookTopic) and topic in app.state.ws_runtime.feeds
    assert services.max_deep_book_subs == MAX_DEEP_BOOK_SUBSCRIPTIONS
    assert services.depth_500 is False


@pytest.mark.parametrize("cap", [1, 3])
def test_the_deep_book_cap_and_the_depth_500_flag_come_from_settings(
    cap: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CV_WS_MAX_DEEP_BOOK_SUBS", str(cap))
    monkeypatch.setenv("CV_HEATMAP_DEPTH_500", "true")
    services = create_app(_settings()).state.ws_registry.services
    assert (services.max_deep_book_subs, services.depth_500) == (cap, True)


class _Stream(BookStream):
    def __init__(self) -> None:  # no ingestion: only the demand calls are seen
        self.calls: list[tuple[Any, ...]] = []

    def acquire_depth(self, consumer: str, symbol: str, depth: int) -> None:
        self.calls.append(("acquire", consumer, symbol, depth))

    def release(self, consumer: str, symbol: str) -> None:
        self.calls.append(("release", consumer, symbol))


async def test_a_book_reference_carries_its_depth_to_the_book_stream() -> None:
    stream = _Stream()
    sink = IngestionUpstreamSink(lambda family: stream if family == "book" else None)
    await sink.open(("BTCUSDT", "book", ("500",)))
    await sink.drop(("BTCUSDT", "book", ("500",)))
    assert stream.calls == [
        ("acquire", "ws:book:500", "BTCUSDT", 500), ("release", "ws:book:500", "BTCUSDT"),
    ]  # fmt: skip


def test_a_window_part_is_a_cvwb_book_delta_at_its_scales() -> None:
    part = book_delta_part(((0, 1000, 5), (1, 1001, 0)), 1, 3)
    back = decode(encode(part))
    assert (back.body_kind, back.price_scale, back.qty_scale) == (BOOK_DELTA, 1, 3)
    assert back.records == ((0, 1000, 5), (1, 1001, 0))
