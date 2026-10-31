"""#410 scenario 1, gateway half: an upstream kill re-snapshots what it touched, and no delta
crosses the gap (G3; §7.1, §7.4; C-13.6 #1, a public WS disconnect, "mid-snapshot" here meaning a
subscription attached during the outage, not a kill during a snapshot; and the gateway's reaction
to #3's desync, whose ingestion half is tests/chaos/ingestion/test_s03_book_sequence_gap.py).

Nothing feeds the hub yet (the book publisher is #604), so the test plays the publisher with
production APIs only and nothing patched (`kill`, `restore`), and encodes the §7.4 table as its
contract. The upstream dying leaves the book unbuildable (`Source.unavailable`) and gapped, which
re-snapshots the symbol's book subscriptions, `upstream_desync`; the upstream coming back is a
resubscribe, which re-snapshots the symbol's public topics, `upstream_reconnect`. A subscription
already waiting for its `snap` keeps its reason, so a book's two triggers make one snap.

Three clients hold a full workspace (the book, the tape, account A's orders filtered to the
symbol), a chart, and a chart of ETHUSDT, a mirror of the recorded book. Through a 10 s outage the
venue keeps moving: each tick's delta reaches `book_step` as a stray that no subscription may take
(a pending one takes no `d`). That is asserted at the publish, which sees what a wait on a socket
cannot (a delta arriving late), and on the frames. On E17-T03's pipeline (#2409: the flag-off row
went).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from candleviewer.ws.pacing import _MULTIPLIER
from candleviewer.ws.sequencing import cv_ws_resync_total, window_delta
from candleviewer.ws.topics import effective_throttle_ms, parse_topic
from tests.chaos.ws._book import replay, structured
from tests.chaos.ws._client import Client, each
from tests.chaos.ws._server import BOOK, DEPTH, ORDERS, SEED, SYM, TRADES, A, Stack, flag_on
from tests.unit.ws._seq_support import ACC_A, Book, validate

pytestmark = pytest.mark.chaos

ETH = "ETHUSDT"
ETH_BOOK = f"book.{ETH}.{DEPTH}"
TRADES_CH, ORDERS_CH = TRADES["ch"], ORDERS["ch"]
#: A blotter filtered to the symbol: a private topic that names it, and is not the upstream's.
BLOTTER: dict[str, Any] = {"ch": ORDERS_CH, "opts": {"exchange_account_ids": [A], "symbols": [SYM]}}
#: Each update must arrive after the previous window closed (tick >= the largest window, 23 §8.6,
#: D12), whatever the connection's class. A class follows RTT samples read on the virtual clock, so
#: a `pong` that spans ticks reads slow: 150 ms is LAGGING (every window doubled), above 500 ms
#: SATURATED (quadrupled), and the tape's 100 ms window becomes 200 or 400 ms. An update held in a
#: window waits for the clock, which a tick that waits for it never moves. Ticks of 125 ms timed
#: out intermittently on that (flag on); 500 ms clears the worst window.
TICK_S = 0.5
WARM_TICKS, AFTER_TICKS, OUTAGE_S = 3, 5, 10.0  # the outage lasts 10 s of virtual time
OUTAGE_TICKS = round(OUTAGE_S / TICK_S)
LATE_TICKS = 2  # s1b: the ticks between a late attach and the recovery
HEARTBEAT_S = 5.0  # the clients' §9.1 pings, on the virtual clock
#: At import, so drift fails here, not as a 5 s timeout: the tick exceeds the slowest window (§8.3):
#: a topic's throttle as `sub_ok` reports it (a book's follows its depth) x the top class's.
THROTTLE_MS = max(effective_throttle_ms(parse_topic(ch), None) for ch in (BOOK, TRADES_CH))
assert THROTTLE_MS * max(_MULTIPLIER.values()) / 1000 < TICK_S and HEARTBEAT_S % TICK_S == 0
PRINTS = 5  # tape prints a tick
FULL, CHART, OTHER = (uuid.UUID(int=n) for n in (0x301, 0x302, 0x303))
Frame = dict[str, Any]


@pytest.fixture
async def world() -> AsyncIterator[Stack]:
    """The gateway on E17-T03's pipeline (#2409: the flag-off row, a `TopicEmitter` per
    connection, went)."""
    async with flag_on() as running:
        yield running


def kill(stack: Stack) -> int:
    """The publisher's part when the upstream dies (module docstring); the snapshots sent."""
    stack.source.unavailable.add(SYM)
    return stack.hub.upstream_desync(SYM)


def restore(stack: Stack) -> int:
    """Its part when the upstream is back and resubscribed; the snapshots sent."""
    stack.source.unavailable.discard(SYM)
    return stack.hub.upstream_reconnect(SYM)


def resyncs() -> dict[str, float]:
    samples = (s for fam in cv_ws_resync_total.collect() for s in fam.samples)
    return {s.labels["reason"]: s.value for s in samples if s.name.endswith("_total")}


def grew(before: dict[str, float]) -> dict[str, float]:
    return {k: v - before.get(k, 0.0) for k, v in resyncs().items() if v != before.get(k)}


def snaps(c: Client, ch: str) -> list[Frame]:
    return [f for f in c.frames if f.get("ch") == ch and f["t"] == "snap"]


def landed(c: Client, ch: str) -> float:
    """The loop time `c`'s last snapshot of `ch` arrived."""
    return c.rx_at[max(i for i, f in enumerate(c.frames) if f.get("ch") == ch and f["t"] == "snap")]


def stream(c: Client, ch: str) -> list[tuple[str, int]]:
    """`ch` on `c` as it arrived: each `snap` and `d` with its `s`."""
    return [(f["t"], f["s"]) for f in c.frames if f.get("ch") == ch and f["t"] in {"snap", "d"}]


def run_of(*deltas: int) -> list[tuple[str, int]]:
    """What a channel shows that took a `snap`, `deltas[0]` deltas, another `snap`, `deltas[1]`
    deltas and so on: `s` runs on from 1, no gap, none twice."""
    kinds = [kind for n in deltas for kind in ("snap", *["d"] * n)]
    return [(kind, s) for s, kind in enumerate(kinds, 1)]


@dataclass
class Venue:
    """The market behind the gateway, and the publisher in front of it. One recorded delta a tick
    moves the BTCUSDT book; ETHUSDT mirrors it (its own symbol, so its own upstream). `last` is
    the `s` each channel has reached, for every client that holds it."""

    stack: Stack
    eth: Book = field(default_factory=lambda: Book(ETH))
    last: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys((BOOK, TRADES_CH, ORDERS_CH, ETH_BOOK), 1)
    )

    def __post_init__(self) -> None:
        self.stack.source.books[ETH] = self.eth
        self.eth.bids, self.eth.asks = dict(self.stack.book.bids), dict(self.stack.book.asks)

    def move(self, *, up: bool) -> None:
        """One tick. With the upstream up, the BTCUSDT book's delta reaches the book subscriptions
        and the tape's prints the trades one. Down, the delta is a stray that no subscription may
        take, and the tape is silent. ETHUSDT moves either way."""
        stack = self.stack
        delivered = stack.book_step()
        if up:
            tape = stack.trades_step(PRINTS)
            assert (delivered, tape) == (2, 1), (delivered, tape)
            self.last[BOOK] += 1
            self.last[TRADES_CH] += 1
        else:
            assert delivered == 0, "a delta crossed the gap"
        b0, a0 = self.eth.top(DEPTH)
        self.eth.bids, self.eth.asks = dict(stack.book.bids), dict(stack.book.asks)
        b1, a1 = self.eth.top(DEPTH)
        body = {"symbol": ETH, "bids": window_delta(b0, b1), "asks": window_delta(a0, a1)}
        assert stack.hub.publish(ETH_BOOK, body) == 1
        self.last[ETH_BOOK] += 1

    def order(self) -> None:
        """An update of account A's orders: a private topic, which the public upstream is not."""
        assert self.stack.private("orders", ACC_A) == 1
        self.last[ORDERS_CH] += 1

    def caught_up(self, c: Client) -> bool:
        """`c` has every frame published to its topics so far."""
        return all(c.seq.get(e["ch"]) == self.last[e["ch"]] for e in c.topics)

    async def run(self, ticks: int, clients: list[Client], *, up: bool) -> None:
        for _ in range(ticks):
            self.move(up=up)
            await each(clients, self.caught_up, "every update delivered, no stray")
            await self.stack.clock.advance(TICK_S)


async def connect(stack: Stack) -> list[Client]:
    """The full workspace, the chart and the other symbol's chart (module docstring): three
    sockets, each with a short §9.1 heartbeat."""
    held = ([structured(BOOK), TRADES, BLOTTER], [structured(BOOK)], [structured(ETH_BOOK)])
    clients = []
    for n, (user, topics) in enumerate(zip((FULL, CHART, OTHER), held, strict=True)):
        c = stack.client(await stack.sessions.mint(str(user)), SEED + n)
        c.heartbeat_s = HEARTBEAT_S
        clients.append(c.start(*topics))
    await each(clients, lambda c: c.synced, "first snapshots")
    return clients


def resnapped(c: Client, ch: str, reason: str, after: int) -> None:
    """`ch` on `c` took its `snap`, `WARM_TICKS` deltas, one re-snapshot of `reason` and `after`
    deltas: the re-snapshot is the frame right after the last delta before the kill, its
    `previous_seq` that delta's `s`, its own `s` the next one."""
    assert stream(c, ch) == run_of(WARM_TICKS, after)
    first, again = snaps(c, ch)
    for frame in (first, again):
        validate(frame)
    assert first["meta"] == {"reason": "initial", "source": "live"}
    assert again["meta"] == {"reason": reason, "source": "live", "previous_seq": WARM_TICKS + 1}
    assert again["s"] == again["meta"]["previous_seq"] + 1


async def delta(stack: Stack, c: Client, s: int) -> None:
    """One recorded delta, taken by `c`'s only subscription, the book's, as its frame `s`."""
    assert stack.book_step() == 1
    await c.until(lambda: c.seq.get(BOOK) == s, f"delta s={s}")
    await stack.clock.advance(TICK_S)


async def test_s1_upstream_kill_resnapshots_every_affected_topic_and_no_delta_crosses_the_gap(
    world: Stack,
) -> None:
    venue = Venue(world)
    full, chart, other = clients = await connect(world)
    await venue.run(WARM_TICKS, clients, up=True)
    before = resyncs()

    # The kill: both book subscriptions of BTCUSDT wait for a `snap`, and none can be built.
    killed = world.clock.now
    assert kill(world) == 0
    await venue.run(OUTAGE_TICKS // 2, clients, up=False)
    venue.order()  # the private topic flows through the outage, in order
    await venue.run(OUTAGE_TICKS - OUTAGE_TICKS // 2, clients, up=False)
    outage = world.clock.now - killed
    assert outage == OUTAGE_S  # exact: the tick is binary-exact
    assert grew(before) == {}  # no snapshot left during the outage

    # The recovery: the book's two subscriptions and the tape's are re-snapshotted, nobody else.
    began = asyncio.get_running_loop().time()
    assert restore(world) == 3
    venue.last[BOOK] += 1  # each re-snapshot takes an `s`
    venue.last[TRADES_CH] += 1
    await each(clients, venue.caught_up, "the re-snapshots")
    ms = 1000 * (
        max(landed(c, ch) for c, ch in [(full, BOOK), (full, TRADES_CH), (chart, BOOK)]) - began
    )
    assert grew(before) == {"upstream_desync": 2, "upstream_reconnect": 1}
    for c in (full, chart):
        resnapped(c, BOOK, "upstream_desync", after=0)  # a pending reason is kept
        assert replay(c.frames, BOOK).matches(world.book, DEPTH)
    resnapped(full, TRADES_CH, "upstream_reconnect", after=0)

    await venue.run(AFTER_TICKS, clients, up=True)
    for c in (full, chart):
        resnapped(c, BOOK, "upstream_desync", after=AFTER_TICKS)
        replica = replay(c.frames, BOOK)
        assert replica.matches(world.book, DEPTH) and replica.gaps == 0
    resnapped(full, TRADES_CH, "upstream_reconnect", after=AFTER_TICKS)
    lost = (WARM_TICKS + 3, BOOK)  # the measure can fail: a replica that lost one delta flags it
    lossy = [f for f in full.frames if (f.get("s"), f.get("ch")) != lost]
    assert replay(lossy, BOOK).gaps == AFTER_TICKS - 1
    assert not replay(lossy, BOOK).matches(world.book, DEPTH)

    # Untouched: the private topic, and the other symbol, which flowed through the outage.
    assert stream(full, ORDERS_CH) == run_of(1) and len(snaps(full, ORDERS_CH)) == 1
    ticks = WARM_TICKS + OUTAGE_TICKS + AFTER_TICKS
    assert stream(other, ETH_BOOK) == run_of(ticks) and len(snaps(other, ETH_BOOK)) == 1
    assert replay(other.frames, ETH_BOOK).matches(venue.eth, DEPTH)
    assert all(c.gaps == [] and c.closes == [] for c in clients) and len(world.gateway) == 3
    flag = "on" if world.backpressure is not None else "off"
    print(
        f"#410 s1 flag {flag}: upstream down {outage:.3f} s virtual ({OUTAGE_TICKS} stray deltas "
        f"refused); the 3 re-snapshots took 0 s of virtual time and landed {ms:.2f} ms (loop "
        f"time) after the recovery"
    )


async def test_s1b_a_subscription_attached_during_the_outage_gets_its_snapshot_only_at_the_recovery(
    world: Stack,
) -> None:
    before = resyncs()
    assert kill(world) == 0  # the upstream is down and the book is being rebuilt
    late = world.client(await world.sessions.mint(str(FULL)), SEED)
    late.heartbeat_s = HEARTBEAT_S
    late.start(structured(BOOK))
    await late.until(lambda: any(f["t"] == "sub_ok" for f in late.frames), "sub_ok")
    (sub_ok,) = (f for f in late.frames if f["t"] == "sub_ok")
    assert [(r["ch"], r["ok"], r["snapshot_pending"]) for r in sub_ok["p"]["results"]] == [
        (BOOK, True, True)
    ]  # every attach is told its snapshot is pending (§7.1): conformance, not the outage's doing
    for _ in range(LATE_TICKS):
        assert world.book_step() == 0, "a delta reached a subscription with no snapshot"
        await world.clock.advance(TICK_S)
    assert snaps(late, BOOK) == []  # the outage holds it: no `snap` before the recovery

    assert restore(world) == 1  # still pending: no snapshot went out while the source was down
    await late.until(lambda: late.synced, "its snapshot at the recovery")
    (snap,) = snaps(late, BOOK)
    validate(snap)
    assert (snap["s"], snap["meta"]) == (1, {"reason": "initial", "source": "live"})  # no resync
    assert stream(late, BOOK) == [("snap", 1)] and grew(before) == {}  # an attach: not counted
    assert replay(late.frames, BOOK).matches(world.book, DEPTH)  # the book as it is now
    await delta(world, late, 2)  # and the stream goes on from it
    await delta(world, late, 3)
    replica = replay(late.frames, BOOK)
    assert replica.matches(world.book, DEPTH) and replica.gaps == 0
    assert late.gaps == [] and late.closes == [] and stream(late, BOOK) == run_of(2)
