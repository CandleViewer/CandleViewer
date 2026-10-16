"""Toxiproxy-style TCP proxy between the chaos clients and the gateway (E17-Q02, 127.0.0.1 only).

Faults are injected here, never by patching application code (#410). Each fault is one scripted
step the test applies with `inject()`; nothing is timed on the wall clock. `trace` records every
step and connection, so a scenario can prove its fault really fired.
"""

from __future__ import annotations

import asyncio
import itertools
from enum import StrEnum

HOST = "127.0.0.1"


class Fault(StrEnum):
    HEAL = "heal"  # back to pass-through both ways; release anything held
    PAUSE = "pause"  # the client stops reading: server->client is not read (TCP backs up)
    LATENCY = "latency"  # server->client bytes (and EOF) are held until the next HEAL
    DROP = "drop"  # abort every live connection, both legs (no close frame: 1006)
    REFUSE = "refuse"  # new connections are accepted, then aborted at once, until the next HEAL


class Proxy:
    def __init__(self, upstream_port: int) -> None:
        self.upstream_port = upstream_port
        self.port = 0  # the port clients dial, once started
        self.trace: list[tuple[str, int]] = []
        self.refusing = False
        self.flowing = asyncio.Event()
        self.flowing.set()
        self.held: list[tuple[asyncio.StreamWriter, bytes]] | None = None  # b"" = EOF
        self._links: dict[int, tuple[asyncio.StreamWriter, asyncio.StreamWriter]] = {}
        self._ids = itertools.count(1)
        self._server: asyncio.Server | None = None

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._accept, HOST, 0)
        self.port = int(self._server.sockets[0].getsockname()[1])
        return self.port

    async def stop(self) -> None:
        self.inject(Fault.DROP)
        if self._server is not None:
            self._server.close()

    def inject(self, fault: Fault) -> int:
        """Apply one step now; returns how many live connections it found."""
        live = len(self._links)
        self.trace.append((fault.value, live))
        self.refusing = fault is Fault.REFUSE or (self.refusing and fault is not Fault.HEAL)
        if fault is Fault.DROP:
            for client, upstream in list(self._links.values()):
                client.transport.abort()
                upstream.transport.abort()
        elif fault is Fault.PAUSE:
            self.flowing.clear()
        elif fault is Fault.LATENCY:
            self.held = []
        elif fault is Fault.HEAL:
            for writer, data in self.held or ():
                if data:
                    writer.write(data)
                else:
                    writer.write_eof()
            self.held = None
            self.flowing.set()
        return live

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        n = next(self._ids)
        if self.refusing:
            self.trace.append(("refused", n))
            writer.transport.abort()
            return
        try:
            up_reader, up_writer = await asyncio.open_connection(HOST, self.upstream_port)
        except OSError:  # no server behind the proxy (a restart): reset the client at once
            self.trace.append(("down", n))
            writer.transport.abort()
            return
        self.trace.append(("open", n))
        self._links[n] = (writer, up_writer)
        try:  # each leg ends at its source's EOF and forwards it (half-close), so closes are clean
            await asyncio.gather(self._pipe(reader, up_writer), self._pipe(up_reader, writer, True))
        finally:
            del self._links[n]
            writer.close()
            up_writer.close()

    async def _pipe(
        self, src: asyncio.StreamReader, dst: asyncio.StreamWriter, down: bool = False
    ) -> None:
        try:
            while True:
                if down:
                    await self.flowing.wait()  # PAUSE: stop reading the server's bytes
                data = await src.read(65536)
                if down:
                    await self.flowing.wait()  # a PAUSE that began during the read holds it too
                if down and self.held is not None:
                    self.held.append((dst, data))
                elif data:
                    dst.write(data)
                    await dst.drain()
                elif dst.can_write_eof():
                    dst.write_eof()
                if not data:
                    return
        except OSError:  # a reset on one leg is a reset on the other, as across a real hop
            dst.transport.abort()
