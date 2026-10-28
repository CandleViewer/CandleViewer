"""The bench feeder out of the backend's process (#571): `fixture_app --feeder proc`.

In process (`--feeder inproc`, the default) the feeder parses the corpus, keeps 40 server books
and validates every print on the gateway's own event loop, so a saturated run cannot say how much
of the loop was the harness. Here the same `Feeder`, from the same seed, runs in a child process
and writes what each slot produced to the backend as one JSON line; `RemoteFeeder`, on the
backend's loop, publishes it into the real `SequencingHub` and `Bus` as the in-process sink does.

- **Child.** `python -m bench.ws.feed_proc --plan JSON [--cpus SPEC]` (started by `RemoteFeeder`).
  Every topic counts as live, so it always computes the depth windows. Lines: a hello (the
  streams, and per symbol its opening window, xu, scales and tick), then `t0`, then a line per
  slot (`b` a book step's window deltas with their CVWB records, `t` a trades batch's prints with
  `price_ticks`, notional and scaled ints) and, when a stream skipped slots, `s` (missed by kind).
  Writes are blocking: a full pipe stalls the child's schedule, and slots that end up over
  `MAX_LATE_S` late are skipped and counted, as in process. Stdin is its lifeline: EOF on it, or
  EPIPE on stdout, ends it (exit 0). `--cpus` pins it with `sched_setaffinity`.
- **Pipe.** `PIPE_BYTES` (16 KiB, about 0.15 s of profile B's lines), not the kernel's 64 KiB,
  so a backend loop that stops reading stalls the child within that, and the shortfall shows in
  `cv_bench_feed_published_total`, which counts lines the receiver has published, not lines
  written.
- **Receiver.** `RemoteFeeder` has the surface `fixture_app` uses of `Feeder` (`feeds`,
  `scales`, `tick_size`, `stats`, `run`). Each symbol's mirror holds the depth window only (what
  `BookSource` reads), the 200-print ring, `xu` and `trades_gen`. A print's `ts_ms` is the wall
  clock when the receiver publishes it (budget #3's reference), its `TradeEvent` is built by the
  in-process builder (`feeder.trade_event`, validated), and the bus publish is awaited, so a slow
  bars lane stops the reading and backs the child up. The receiver yields after every line, as
  the in-process feeder yields after every slot (#4833).
- **Counters.** `stats()` is the in-process formula over the child's streams and `t0`
  (CLOCK_MONOTONIC is one clock for both processes), plus `missed` and the child's CPU seconds.

Differences from in process, by design: during a warm-up in which a book topic has no subscriber,
the child still skips deltas that move no window level (in process a dead topic takes one delta
per slot), so the corpus position differs from then on (the seed still fixes it); and a book
re-snapshot sorts the 50-level window, not the full book.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl
import json
import os
import sys
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import orjson

from bench.ws.feeder import (
    BOOK_PRICE_SCALE,
    BOOK_QTY_SCALE,
    TRADES_SNAPSHOT,
    Book,
    BookMove,
    Feeder,
    Tier,
    _Feed,
    _places,
    print_fields,
    scale_int,
    schedule_stats,
    trade_event,
)
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import Topic
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.ws.binary import BOOK_DELTA, TRADES, Frame
from candleviewer.ws.sequencing import SequencingHub

API: Final = Path(__file__).resolve().parents[2]
#: The pipe between the child and the backend (module docstring, "Pipe").
PIPE_BYTES: Final = 16 << 10
READ_BYTES: Final = 64 << 10
HELLO_TIMEOUT_S: Final = 180.0  # the child imports and loads the corpus first
STOP_TIMEOUT_S: Final = 10.0
STATS_EVERY_S: Final = 1.0
F_SETPIPE_SZ: Final = getattr(fcntl, "F_SETPIPE_SZ", 1031)
_ENV: Final = "demo"


class FeederGone(RuntimeError):
    """The child closed its end: it exited, or failed (its stderr is the backend's)."""


def _line(msg: list[Any]) -> bytes:
    return orjson.dumps(msg) + b"\n"


def cpu_set(spec: str) -> set[int]:
    """`0-3,6` as the set of cpus."""
    out: set[int] = set()
    for part in spec.split(","):
        a, sep, b = part.partition("-")
        out |= set(range(int(a), int(b) + 1)) if sep else {int(a)}
    return out


def plan_of(
    symbols: Sequence[str], tiers: Sequence[Tier], *, seed: int, depths: Sequence[int]
) -> dict[str, Any]:
    """What the child needs to build the backend's `Feeder`: the `--plan` JSON."""
    rates = [[t.book_per_s, t.batches_per_s, t.prints_per_batch] for t in tiers]
    return {"symbols": list(symbols), "tiers": rates, "seed": seed, "depths": list(depths)}


class LineSink:
    """The child's sink: one line per slot to `out`."""

    def __init__(self, out: Callable[[bytes], None]) -> None:
        self._out = out

    def book(self, feed: _Feed, moves: Sequence[BookMove]) -> None:
        self._out(_line(["b", feed.name, feed.xu, [[d, b, a, r] for d, b, a, r in moves]]))

    async def trades(
        self,
        feed: _Feed,
        prints: Sequence[tuple[TradePrint, str]],
        items: list[dict[str, str | int]],
        now_ms: int,
        live: bool,
    ) -> None:
        ps, qs = feed.price_scale, feed.qty_scale
        rows = []
        for p, tid in prints:
            ticks, notional = print_fields(p, feed.tick)
            price, qty = scale_int(p.price, ps), scale_int(p.qty, qs)
            rows.append([tid, str(p.price), str(p.qty), p.side, ticks, str(notional), price, qty])
        self._out(_line(["t", feed.name, rows]))


def child_feeder(plan: dict[str, Any], out: Callable[[bytes], None]) -> Feeder:
    """The backend's `Feeder` for `plan`, every topic live, writing lines to `out`."""
    tiers = [Tier(*t) for t in plan["tiers"]]
    return Feeder(
        None, None, plan["symbols"], tiers, seed=int(plan["seed"]),
        depths=tuple(plan["depths"]), live=lambda ch: True, sink=LineSink(out),
    )  # fmt: skip


def hello(f: Feeder, depth: int) -> bytes:
    """The first line: the streams and, per symbol, what the receiver's mirror starts from."""
    feeds = {}
    for name, feed in f.feeds.items():
        bids, asks = feed.book.top(depth)
        feeds[name] = {
            "xu": feed.xu,
            "bids": [[p, s] for p, s in bids.items()],
            "asks": [[p, s] for p, s in asks.items()],
            "scales": [feed.price_scale, feed.qty_scale],
            "tick": str(feed.tick),
        }
    streams = [[s.feed.name, s.kind, s.interval, s.start] for s in f.streams]
    return _line(["h", {"depth": depth, "streams": streams, "feeds": feeds}])


def _write_all(data: bytes) -> None:
    view = memoryview(data)
    while view:  # a blocking pipe: a full one stalls the child, by design
        view = view[os.write(1, view) :]


async def _report_missed(f: Feeder, out: Callable[[bytes], None]) -> None:
    said: dict[str, int] = {}
    while True:
        await asyncio.sleep(STATS_EVERY_S)
        missed = {"book": 0, "trades": 0}
        for s in f.streams:
            missed[s.kind] += s.missed
        if missed != said:
            out(_line(["s", missed]))
            said = missed


async def child(plan: dict[str, Any], steps: int | None = None) -> None:
    """The child's whole life: hello, then the schedule until stdin ends or stdout breaks.
    `steps` replays the first `steps` slots of the plan with no clock and returns (a test's)."""
    f = child_feeder(plan, _write_all)
    _write_all(hello(f, max(plan["depths"])))
    if steps is not None:
        for _, i in f.schedule(steps):
            await f.step(f.streams[i])
        return
    loop, eof = asyncio.get_running_loop(), asyncio.Event()

    def on_stdin() -> None:
        try:
            data = os.read(0, 4096)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            eof.set()

    os.set_blocking(0, False)
    loop.add_reader(0, on_stdin)
    t0 = time.monotonic()
    _write_all(_line(["0", t0]))
    tasks = [
        asyncio.ensure_future(f.run(t0)),
        asyncio.ensure_future(_report_missed(f, _write_all)),
        asyncio.ensure_future(eof.wait()),
    ]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        loop.remove_reader(0)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    for t in done:
        if not t.cancelled() and (exc := t.exception()) is not None:
            raise exc


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--plan", required=True, help="JSON: symbols, tiers, seed, depths")
    ap.add_argument("--cpus", default="", help="the cpus the child runs on (sched_setaffinity)")
    ap.add_argument("--steps", type=int, help="replay this many slots with no clock, then exit")
    args = ap.parse_args(argv)
    if args.cpus:
        os.sched_setaffinity(0, cpu_set(args.cpus))
    from bench.ws.fixture_app import egress_guard  # here: fixture_app imports this module

    sys.stdout = sys.stderr  # fd 1 is the lines' alone: nothing else may print to it
    try:
        with egress_guard():  # it opens no socket; defence in depth, as the backend's
            asyncio.run(child(json.loads(args.plan), args.steps))
    except BrokenPipeError:  # the backend closed its end: nothing left to feed
        return 0
    return 0


# -- the receiver, on the backend's loop ----------------------------------------------------------


class MirrorFeed:
    """What the snapshot sources and the bars read of one symbol, kept from the child's lines:
    the `SnapshotFeed` of `feeder`, with the depth window as its book."""

    def __init__(self, name: str, spec: dict[str, Any]) -> None:
        self.name = name
        self.book = Book()
        self.book.apply_rows(spec["bids"], spec["asks"])
        self.xu: int = spec["xu"]
        self.price_scale, self.qty_scale = (int(x) for x in spec["scales"])
        self.tick = Decimal(spec["tick"])
        self.ring: deque[dict[str, str | int]] = deque(maxlen=TRADES_SNAPSHOT)
        self.trades_gen = 0
        self.seq = 0


@dataclass(slots=True)
class _Slot:
    """A child's stream, as the receiver counts what it published of it."""

    kind: str
    interval: float
    start: float
    published: int = 0


def _wake(ready: asyncio.Future[None]) -> None:
    if not ready.done():  # a level-triggered reader may fire again before the waiter runs
        ready.set_result(None)


class RemoteFeeder:
    """The out-of-process feeder's end in the backend (module docstring, "Receiver")."""

    def __init__(
        self,
        hub: SequencingHub,
        bus: Bus,
        symbols: Sequence[str],
        tiers: Sequence[Tier],
        *,
        seed: int,
        depths: Sequence[int] = (50,),
        cpus: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
    ) -> None:
        self._hub, self._bus = hub, bus
        self._plan = plan_of(symbols, tiers, seed=seed, depths=depths)
        self._cpus, self._clock, self._wall_ms = cpus, clock, wall_ms
        self._depth = max(depths)
        self.feeds: dict[str, MirrorFeed] = {}
        self.streams: list[_Slot] = []
        self._slots: dict[tuple[str, str], _Slot] = {}
        self.t0: float | None = None
        self.missed = {"book": 0, "trades": 0}
        self.proc: asyncio.subprocess.Process | None = None
        self._fd = -1
        self._carry = b""
        self._cpu_s = 0.0

    def scales(self, symbol: str) -> tuple[int, int] | None:
        feed = self.feeds.get(symbol)
        return None if feed is None else (max(1, _places(feed.tick)), feed.qty_scale)

    def tick_size(self, symbol: str) -> Decimal | None:
        feed = self.feeds.get(symbol)
        return None if feed is None else feed.tick

    def stats(self) -> dict[str, tuple[int, int]]:
        if self.t0 is None:
            return {"book": (0, 0), "trades": (0, 0)}
        return schedule_stats(self.streams, self._clock() - self.t0)

    def cpu_seconds(self) -> float:
        """The child's CPU seconds (user and system), the last reading once it has gone."""
        if self.proc is not None and self.proc.returncode is None:
            with contextlib.suppress(OSError, IndexError, ValueError):
                stat = Path(f"/proc/{self.proc.pid}/stat").read_text(encoding="utf-8")
                fields = stat.rsplit(")", 1)[1].split()
                self._cpu_s = (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
        return self._cpu_s

    async def start(self) -> None:
        """Start the child and read its hello: `feeds`, `scales` and `tick_size` answer after."""
        r, w = os.pipe()
        try:
            fcntl.fcntl(w, F_SETPIPE_SZ, PIPE_BYTES)
            argv = [sys.executable, "-m", "bench.ws.feed_proc", "--plan", json.dumps(self._plan)]
            argv += ["--cpus", self._cpus] if self._cpus else []
            self.proc = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.PIPE, stdout=w, cwd=API
            )
        except BaseException:
            os.close(r)
            raise
        finally:
            os.close(w)
        os.set_blocking(r, False)
        self._fd = r
        try:
            async with asyncio.timeout(HELLO_TIMEOUT_S):
                while not self.feeds:
                    for msg in await self._lines():
                        await self.handle(msg)
        except BaseException:
            await self.close()
            raise

    async def _lines(self) -> list[Any]:
        """The complete lines of the next read, decoded (waits until the pipe is readable)."""
        loop = asyncio.get_running_loop()
        while True:
            try:
                data = os.read(self._fd, READ_BYTES)
            except BlockingIOError:
                ready: asyncio.Future[None] = loop.create_future()
                loop.add_reader(self._fd, _wake, ready)
                try:
                    await ready
                finally:
                    loop.remove_reader(self._fd)
                continue
            if not data:
                raise FeederGone("the feeder process closed its pipe")
            *lines, self._carry = (self._carry + data).split(b"\n")
            return [orjson.loads(x) for x in lines]

    async def run(self) -> None:
        while True:
            for msg in await self._lines():
                await self.handle(msg)
                await asyncio.sleep(0)  # a turn per slot, as in process (#4833)

    async def handle(self, msg: list[Any]) -> None:
        """One line of the child."""
        kind = msg[0]
        if kind == "b":
            self._book(msg[1], int(msg[2]), msg[3])
        elif kind == "t":
            await self._trades(msg[1], msg[2])
        elif kind == "0":
            self.t0 = float(msg[1])
        elif kind == "s":
            self.missed = {k: int(v) for k, v in msg[1].items()}
        elif kind == "h":
            self._hello(msg[1])
        else:
            raise ValueError(f"unknown feeder line {kind!r}")

    def _hello(self, h: dict[str, Any]) -> None:
        self.streams = [_Slot(kind, float(iv), float(st)) for _, kind, iv, st in h["streams"]]
        self._slots = {
            (n, k): s for (n, k, _, _), s in zip(h["streams"], self.streams, strict=True)
        }
        self.feeds.update({name: MirrorFeed(name, spec) for name, spec in h["feeds"].items()})

    def _book(self, name: str, xu: int, moves: list[list[Any]]) -> None:
        feed = self.feeds[name]
        for d, bids, asks, _ in moves:
            if d == self._depth:  # a smaller window is the top of this one
                feed.book.apply_rows(bids, asks)
        feed.xu = xu
        for d, bids, asks, recs in moves:
            ch = f"book.{name}.{d}"
            if self._hub.subscriptions(ch):
                records = tuple((int(a), int(b), int(c)) for a, b, c in recs)
                part = Frame(
                    BOOK_DELTA, records, price_scale=BOOK_PRICE_SCALE, qty_scale=BOOK_QTY_SCALE
                )
                body = {"symbol": name, "xu": xu, "xseq": xu, "bids": bids, "asks": asks}
                self._hub.publish(ch, body, part=part)
        self._slots[(name, "book")].published += 1

    async def _trades(self, name: str, rows: list[list[Any]]) -> None:
        feed, now_ms = self.feeds[name], self._wall_ms()
        items: list[dict[str, str | int]] = []
        events = []
        for k, (tid, price, qty, side, ticks, notional, _, _) in enumerate(rows):
            items.append({"id": tid, "ts_ms": now_ms, "price": price, "size": qty, "side": side})
            feed.seq += 1
            fields = (Decimal(price), Decimal(qty), side, int(ticks), Decimal(notional))
            events.append(trade_event(name, feed.seq, tid, fields, now_ms * 1000 + k))
        feed.ring.extend(items)
        feed.trades_gen += 1
        ch = f"trades.{name}"
        if self._hub.subscriptions(ch):
            records = tuple((0, int(r[6]), int(r[7]), 0 if r[3] == "buy" else 1, 0) for r in rows)
            ps, qs = feed.price_scale, feed.qty_scale
            part = Frame(TRADES, records, price_scale=ps, qty_scale=qs, ts_base_ms=now_ms)
            self._hub.publish(ch, {"symbol": name, "trades": items}, part=part)
        topic = Topic(env=_ENV, domain="md", symbol=name, detail="trade")
        for ev in events:  # NEVER_DROP: a slow bars lane stops the reading, the child backs up
            await self._bus.publish(topic, ev)
        self._slots[(name, "trades")].published += 1

    async def close(self) -> None:
        """End the child and reap it: our end of its stdout closes (EPIPE on its next write), its
        stdin ends (EOF), and a child still there after `STOP_TIMEOUT_S` is killed."""
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1
        proc = self.proc
        if proc is None:
            return
        self.cpu_seconds()  # the last reading, while /proc still has it
        if proc.stdin is not None:
            proc.stdin.close()
        try:
            async with asyncio.timeout(STOP_TIMEOUT_S):
                await proc.wait()
        except TimeoutError:
            proc.kill()
            await proc.wait()


if __name__ == "__main__":
    sys.exit(main())
