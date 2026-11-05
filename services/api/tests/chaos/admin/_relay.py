"""The admin chaos relay (E42-Q03, #1216): an asyncio TCP relay on 127.0.0.1 in front of Postgres.

[BQ-4] Faults are injected in process, never by `tc netem` or a proxy container (the E27-Q03
ruling, `qa/plans/e27/chaos.md`): this relay generalises the loopback relays of
`tests/integration/oms/test_place_order_route_pg.py` and `test_order_entry_gate_measured_pg.py`.
One relay aims at one subsystem: a store built on `through(dsn)` reaches Postgres only through it,
so a second relay leaves the other stores healthy.

Modes, each set by one call and logged in `trace`:
- `heal()`: pass-through. Links that lived through a `blackhole` or a `cut` are reset first, so a
  pool reconnects cleanly rather than reading a half-sent reply;
- `delay(ms)`: every chunk, both ways, is held `ms` before it is forwarded ("Postgres slow");
- `blackhole()`: links are kept and new ones accepted, but nothing is forwarded (an unreachable
  host whose packets vanish: the reader's own budget ends the wait);
- `cut()`: the port refuses connections and every live link is reset (Postgres down).

`ensure_up()` is the asserted recovery of every scenario (as `chaos/storage/_stack.py` after
GH-3087): it fails unless a Postgres SSLRequest sent through the relay is answered by the upstream
(one `S` or `N` byte). A relay only ever forwards to a loopback upstream. Every wait here is
bounded but the blackhole's, which `heal()` and `close()` end.
"""

from __future__ import annotations

import asyncio
import contextlib
from enum import StrEnum
from types import TracebackType
from typing import Self

from sqlalchemy.engine import make_url

from candleviewer.observability import spawn

HOST = "127.0.0.1"
CONNECT_TIMEOUT_S = 5.0
CHUNK = 65536
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
SSL_REQUEST = bytes.fromhex("0000000804d2162f")  # the 8-byte Postgres SSLRequest; answered S or N


class Mode(StrEnum):
    OPEN = "open"
    DELAY = "delay"
    BLACKHOLE = "blackhole"
    CUT = "cut"


def upstream_of(dsn: str) -> tuple[str, int]:
    """The (host, port) a SQLAlchemy DSN dials; 5432 when it names none."""
    url = make_url(dsn)
    if url.host is None:
        raise ValueError("the DSN names no host")
    return url.host, url.port or 5432


class Relay:
    """One relay, `async with Relay(upstream) as relay:`; `through(dsn)` is `dsn` aimed at it."""

    def __init__(self, upstream: tuple[str, int]) -> None:
        if upstream[0] not in LOOPBACK:
            raise ValueError("the relay forwards to a loopback upstream only")
        self.upstream = upstream
        self.port = 0
        self.mode = Mode.OPEN
        self.delay_s = 0.0
        self.trace: list[str] = []
        self._flowing = asyncio.Event()
        self._flowing.set()
        self._server: asyncio.Server | None = None
        self._links: set[asyncio.StreamWriter] = set()
        self._faulted: set[asyncio.StreamWriter] = set()  # links that lived through a fault
        self._tasks: set[asyncio.Task[None]] = set()

    async def __aenter__(self) -> Self:
        await self._listen()
        return self

    async def __aexit__(
        self, kind: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.close()

    def through(self, dsn: str) -> str:
        """`dsn` with its host and port replaced by the relay's."""
        if not self.port:
            raise RuntimeError("the relay is not listening yet")
        return make_url(dsn).set(host=HOST, port=self.port).render_as_string(hide_password=False)

    async def _listen(self) -> None:
        self._server = await asyncio.start_server(self._accept, HOST, self.port)
        self.port = int(self._server.sockets[0].getsockname()[1])

    def delay(self, ms: float) -> None:
        self._set(Mode.DELAY)
        self.delay_s = ms / 1000
        self._flowing.set()  # a delay set over a blackhole must not stay held

    def blackhole(self) -> None:
        self._set(Mode.BLACKHOLE)
        self._flowing.clear()
        self._faulted |= self._links

    def cut(self) -> None:
        self._set(Mode.CUT)
        self._flowing.set()
        if self._server is not None:
            self._server.close()  # the port refuses from now on
            self._server = None
        self._reset(set(self._links))

    async def heal(self) -> None:
        self._reset(self._faulted)
        self._set(Mode.OPEN)
        self._flowing.set()
        if self._server is None:
            await self._listen()  # the same port again: a pool keeps its DSN

    async def ensure_up(self) -> None:
        """Fails unless the relay is in pass-through and the upstream answers an SSLRequest sent
        through it: the asserted end of every scenario."""
        assert self.mode is Mode.OPEN, f"the relay was left in {self.mode.value}"
        async with asyncio.timeout(CONNECT_TIMEOUT_S):
            reader, writer = await asyncio.open_connection(HOST, self.port)
            try:
                writer.write(SSL_REQUEST)
                await writer.drain()
                answer = await reader.readexactly(1)
            finally:
                writer.close()
        assert answer in {b"S", b"N"}, "the upstream did not answer the SSLRequest"
        with contextlib.suppress(OSError):
            await writer.wait_closed()

    async def close(self) -> None:
        self._set(Mode.CUT)
        server, self._server = self._server, None
        if server is not None:
            server.close()
        self._reset(set(self._links))
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if server is not None:
            async with asyncio.timeout(CONNECT_TIMEOUT_S):
                await server.wait_closed()

    def _set(self, mode: Mode) -> None:
        self.mode, self.delay_s = mode, 0.0
        self.trace.append(mode.value)

    def _reset(self, links: set[asyncio.StreamWriter]) -> None:
        for writer in links:
            writer.transport.abort()
        self._faulted -= links

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT_S):
                up_reader, up_writer = await asyncio.open_connection(*self.upstream)
        except (OSError, TimeoutError):
            writer.transport.abort()
            return
        pair = {writer, up_writer}
        if self.mode is Mode.CUT:  # cut while this link was being opened: reset, never relay
            self._reset(pair)
            return
        self._links |= pair
        if self.mode is Mode.BLACKHOLE:
            self._faulted |= pair
        pipes = [
            spawn(self._pipe(reader, up_writer), name="chaos-relay-up"),
            spawn(self._pipe(up_reader, writer), name="chaos-relay-down"),
        ]
        self._tasks.update(pipes)
        try:
            await asyncio.gather(*pipes)
        finally:
            self._tasks.difference_update(pipes)
            self._links -= pair
            self._faulted -= pair

    async def _pipe(self, src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        try:
            while chunk := await src.read(CHUNK):
                await self._flowing.wait()  # a blackhole holds the chunk until heal or close
                if self.delay_s:
                    await asyncio.sleep(self.delay_s)
                dst.write(chunk)
                await dst.drain()
        except OSError:
            pass  # a reset link: the other pipe sees it too
        finally:
            if self.mode is Mode.OPEN:
                dst.close()  # an orderly end: pass the EOF on
            else:
                dst.transport.abort()
