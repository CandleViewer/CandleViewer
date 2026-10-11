"""Bybit v5 public linear WS specifics for the ingestion skeleton (E08-T04).

Owns every Bybit-native piece the venue-neutral `ingestion.ConnectionManager`
needs (C-2.2): the public stream host per environment, the topic-head to
stream-kind mapping, and a size-capped socket factory. Public market data is
unauthenticated — no credentials are read or sent here (C-2.11: demo has no
public feed of its own, so `demo` uses the mainnet public stream).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection

#: `docs/plan/24-internal-schemas.md` §14.3 public WS hosts, verbatim.
PUBLIC_WS_URLS: dict[str, str] = {
    "live": "wss://stream.bybit.com/v5/public/linear",
    "demo": "wss://stream.bybit.com/v5/public/linear",
    "testnet": "wss://stream-testnet.bybit.com/v5/public/linear",
}

_TOPIC_KIND: dict[str, str] = {"orderbook": "book", "publicTrade": "trade", "tickers": "ticker"}


def topic_kind(topic: str) -> str:
    """Map a Bybit topic (`orderbook.50.BTCUSDT`) to a neutral stream kind."""
    head = topic.split(".", 1)[0]
    return _TOPIC_KIND.get(head, head)


#: Topic prefix -> Postgres `stream_kind` names (E16-T04 recorder gap attribution).
_TOPIC_STREAMS: dict[str, tuple[str, ...]] = {
    "publicTrade": ("trades",),
    "orderbook": ("orderbook_delta", "orderbook_snapshot"),
    "tickers": ("tickers",),
    "allLiquidation": ("liquidations",),
    "liquidation": ("liquidations",),
}
#: Streams a socket-wide (`*`) health event affects.
_ALL_STREAMS: tuple[str, ...] = (
    "trades", "orderbook_delta", "orderbook_snapshot", "tickers", "liquidations"
)  # fmt: skip


def stream_for_topic(topic: str) -> tuple[str | None, tuple[str, ...]]:
    """`exchange.base.ports.StreamForTopic`: `publicTrade.BTCUSDT` -> ("BTCUSDT", ("trades",));
    `*` -> (None, all recorded streams); unknown prefix -> (symbol, ())."""
    if topic == "*" or "." not in topic:
        return None, _ALL_STREAMS
    head, _, rest = topic.partition(".")
    return rest.rsplit(".", 1)[-1], _TOPIC_STREAMS.get(head, ())


_TOPIC_RE = re.compile(r'"topic"\s*:\s*"([A-Za-z0-9._]{1,64})"')


def frame_route(frame: str) -> tuple[str, str, str] | None:
    """#1916: cheap `(topic, kind, symbol)` routing key for one raw frame
    without a full JSON parse (the stream parsers still validate it fully).
    None for control frames (acks, pongs) or anything unrecognised."""
    m = _TOPIC_RE.search(frame, 0, 256)
    if m is None:
        return None
    topic = m.group(1)
    kind = topic_kind(topic)
    if kind not in ("book", "trade", "ticker"):
        return None
    return topic, kind, topic.rsplit(".", 1)[-1]


class PublicSocket(Protocol):
    async def send(self, frame: str) -> None: ...
    async def recv(self, max_bytes: int) -> str: ...
    async def close(self) -> None: ...


class _WsSocket:
    """Adapter over a `websockets` client connection; frames above
    `max_size` are refused by the library before buffering (E08-X01)."""

    def __init__(self, conn: ClientConnection) -> None:
        self._conn = conn

    async def send(self, frame: str) -> None:
        await self._conn.send(frame)

    async def recv(self, max_bytes: int) -> str:
        text = str(await self._conn.recv(decode=True))
        if len(text) > max_bytes:
            raise ValueError("ws frame exceeds max_bytes")
        return text

    async def close(self) -> None:
        await self._conn.close()


def public_socket_factory(
    env: str, *, max_frame_bytes: int, open_timeout_s: float = 10.0
) -> Callable[[], Awaitable[PublicSocket]]:
    """Return a zero-arg coroutine factory dialing the public stream for `env`."""
    url = PUBLIC_WS_URLS[env]

    async def connect() -> PublicSocket:
        from websockets.asyncio.client import connect as ws_connect

        conn = await ws_connect(
            url, max_size=max_frame_bytes, open_timeout=open_timeout_s, ping_interval=None
        )
        return _WsSocket(conn)

    return connect
