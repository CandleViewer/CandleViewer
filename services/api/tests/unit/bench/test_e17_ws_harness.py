"""E17-Q03 (#568): the harness itself, offline and on loopback: the profile table against the caps
the gateway enforces, the feeder (rates, determinism, a client that stays consistent), the CVWB
port and the profile helper against their Python twins, the egress guard, the bench send delay,
and the real fixture backend with a tiny protocol client. No k6 here (the smokes need it).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl
import itertools
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Callable, MutableMapping
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import orjson
import pytest
import structlog
import websockets
from structlog.testing import capture_logs

from bench.ws import budgets, feed_proc, fixture_app, profiles, runner, w5
from bench.ws import feeder as feed
from bench.ws.feeder import Feeder, Tier, scale_int, tier_plan
from candleviewer.bars.leases import CAP_PER_USER
from candleviewer.bus.bus import Bus
from candleviewer.observability.logging import reset_logging
from candleviewer.ws import limits
from candleviewer.ws.binary import TRADES, Frame, decode_b64
from candleviewer.ws.gateway import WS_PATH
from candleviewer.ws.sequencing import CLIENT_RESYNC_REASONS, SequencingHub
from tests import _ci_network_guard as ci_guard

LOAD = Path(__file__).resolve().parents[5] / "tests" / "load" / "ws"
VECTORS = (
    Path(__file__).resolve().parents[5]
    / "packages"
    / "fixtures"
    / "golden"
    / "cvwb"
    / "vectors.json"
)
TABLE = profiles.load()
RUN_PROFILES = ("A", "B", "C", "smoke", "W5", "selfcheck")
NOW_MS = 1_789_000_000_000


def families(table: dict[str, Any], name: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for fam, ch in profiles.topics(table, profiles.resolve(table, name)):
        out.setdefault(fam, []).append(ch)
    return out


@pytest.mark.parametrize("name", RUN_PROFILES)
def test_every_profile_stays_inside_the_caps_the_gateway_enforces(name: str) -> None:
    prof = profiles.resolve(TABLE, name)
    topics = profiles.topics(TABLE, prof)
    fams = families(TABLE, name)
    series = {(ch.split(".")[1], "time.1") for ch in fams.get("bars", [])}
    series |= {
        (ch.split(".")[1], "time.5") for ch in fams.get("footprint", [])
    }  # both lease a series
    assert len(series) <= CAP_PER_USER  # 8 distinct bar series per user
    assert len(topics) <= limits.MAX_SUBSCRIPTIONS
    assert prof["symbols"] <= limits.MAX_SYMBOLS_PER_CONNECTION
    assert len(fams.get("bars", [])) <= limits.MAX_BARS_SUBSCRIPTIONS
    assert len(topics) <= limits.REBUILD_MAX_PER_CONNECTION
    assert len(topics) * prof["connections"] <= limits.REBUILD_MAX_PER_USER
    assert 1 <= prof["connections"] <= 8 and prof["users"] >= 1
    assert prof["symbols"] <= TABLE["feeds"][prof["feed"]]["symbols"]


def test_the_profiles_have_the_shapes_the_ticket_names() -> None:
    sub = {n: len(profiles.topics(TABLE, profiles.resolve(TABLE, n))) for n in "ABC"}
    assert sub == {"A": 28, "B": 128, "C": 16}  # A: 7 bars + 1 footprint + 10 + 10; C: 4 panes x RW
    assert (TABLE["profiles"]["A"]["users"], TABLE["profiles"]["A"]["connections"]) == (5, 1)
    assert (TABLE["profiles"]["B"]["users"], TABLE["profiles"]["B"]["connections"]) == (1, 8)
    assert families(TABLE, "B")["heatmap"] == [f"heatmap.{s}" for s in TABLE["symbols"][:40]]
    assert families(TABLE, "C")["footprint"][0].startswith("footprint.BTCUSDT")
    ref = [
        ch
        for ch in profiles.topics(TABLE, profiles.resolve(TABLE, "A"))
        if ch[1].split(".")[1] == "BTCUSDT"
    ]
    assert {f for f, _ in ref} == {
        "bars",
        "footprint",
        "book",
        "trades",
    }  # the 23 16.3 reference workspace
    assert (
        profiles.resolve(TABLE, "W5")["probe"] is False
        and profiles.resolve(TABLE, "smoke")["users"] == 5
    )


def test_the_feed_tiers_total_what_the_design_states() -> None:
    def totals(feed_name: str) -> tuple[int, int]:
        f = TABLE["feeds"][feed_name]
        tiers = tier_plan(f["symbols"], f["hot"], f["warm"], TABLE["tiers"])
        return sum(t.book_per_s for t in tiers), sum(
            t.batches_per_s * t.prints_per_batch for t in tiers
        )

    assert totals("ten") == (84, 87) and totals("forty") == (368, 384)
    depth = TABLE["topics"]["book"]["ch"].rsplit(".", 1)[1]
    assert all(f["book_depths"] == [int(depth)] for f in TABLE["feeds"].values())


# -- the feeder --------------------------------------------------------------------------------


class Recorder:
    """Stands in for the hub: one subscriber on every topic, every publish recorded."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], Frame | None]] = []

    def subscriptions(self, ch: str) -> list[object]:
        return [object()]

    def publish(self, ch: str, body: dict[str, Any], *, part: Frame | None = None) -> int:
        self.calls.append((ch, json.loads(json.dumps(body)), part))
        return 1


def make_feeder(seed: int, rec: Recorder, n: int = 4) -> Feeder:
    symbols = TABLE["symbols"][:n]
    tiers = tier_plan(n, 1, 1, TABLE["tiers"])
    return Feeder(
        cast(SequencingHub, rec), Bus(), symbols, tiers, seed=seed, wall_ms=lambda: NOW_MS
    )


async def drive(f: Feeder, steps: int) -> None:
    for _, i in f.schedule(steps):
        await f.step(f.streams[i])


class SpyBus:
    """Stands in for the bus: every event the bars lanes would get (its random id aside)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, topic: object, ev: Any) -> None:
        self.events.append((str(topic), ev.model_dump(exclude={"event_id"})))


def proc_plan(seed: int, n: int = 4) -> dict[str, Any]:
    tiers = tier_plan(n, 1, 1, TABLE["tiers"])
    return feed_proc.plan_of(TABLE["symbols"][:n], tiers, seed=seed, depths=(50,))


async def child_lines(seed: int, steps: int, n: int = 4) -> tuple[Feeder, list[bytes]]:
    """The child's feeder and the lines it writes for the hello and its first `steps` slots."""
    out: list[bytes] = []
    child = feed_proc.child_feeder(proc_plan(seed, n), out.append)
    out.append(feed_proc.hello(child, 50))
    await drive(child, steps)
    return child, out


def remote(
    rec: Recorder, bus: SpyBus | None = None, seed: int = 7, n: int = 4, **kw: Any
) -> feed_proc.RemoteFeeder:
    """The receiver of `seed`'s child, publishing into `rec` (every topic subscribed)."""
    return feed_proc.RemoteFeeder(
        cast(SequencingHub, rec), cast(Bus, bus or SpyBus()), TABLE["symbols"][:n],
        tier_plan(n, 1, 1, TABLE["tiers"]), seed=seed, wall_ms=lambda: NOW_MS, **kw,
    )  # fmt: skip


async def relay(lines: list[bytes], rf: feed_proc.RemoteFeeder) -> None:
    for line in b"".join(lines).splitlines():
        await rf.handle(orjson.loads(line))


@pytest.mark.parametrize("mode", ["inproc", "proc"])
async def test_the_feeder_is_deterministic_per_seed(mode: str) -> None:
    """Either mode: the seed fixes what reaches the hub (out of process, through the lines)."""

    async def calls(seed: int) -> list[Any]:
        rec = Recorder()
        if mode == "inproc":
            await drive(make_feeder(seed, rec), 300)
        else:
            await relay((await child_lines(seed, 300))[1], remote(rec, seed=seed))
        return rec.calls

    a, b, c = await calls(7), await calls(7), await calls(8)
    assert a == b and a
    assert a != c  # another seed: other offsets, other phases


async def test_with_every_topic_subscribed_both_modes_publish_the_same_frames_and_bus_events() -> (
    None
):
    """#571: the receiver publishes what the in-process feeder publishes, frame for frame and
    `TradeEvent` for `TradeEvent` (built and validated by the same builder), when every topic has
    a subscriber (the child always assumes one; the steady state of profile B)."""
    rec_in, bus_in, rec_out, bus_out = Recorder(), SpyBus(), Recorder(), SpyBus()
    symbols, tiers = TABLE["symbols"][:4], tier_plan(4, 1, 1, TABLE["tiers"])
    f = Feeder(
        cast(SequencingHub, rec_in), cast(Bus, bus_in), symbols, tiers, seed=7,
        wall_ms=lambda: NOW_MS,
    )  # fmt: skip
    await drive(f, 1500)
    await relay((await child_lines(7, 1500))[1], remote(rec_out, bus_out))
    assert rec_in.calls == rec_out.calls and len(rec_in.calls) == 1500
    assert bus_in.events == bus_out.events and len(bus_in.events) > 1000


async def test_a_client_applying_the_remote_feeders_window_deltas_stays_equal_to_its_book() -> None:
    """The twin of the in-process property: from the hello's window, the published deltas
    rebuild the receiver's mirror, which is the child's server book's top 50."""
    rec = Recorder()
    child, lines = await child_lines(7, 2000)
    rf = remote(rec)
    await relay(lines[:1], rf)  # the hello: the window a first snapshot shows
    bids, asks = rf.feeds["BTCUSDT"].book.top(50)
    held = {"bid": dict(bids), "ask": dict(asks)}
    await relay(lines[1:], rf)
    deltas = [body for ch, body, _ in rec.calls if ch == "book.BTCUSDT.50"]
    assert len(deltas) > 100
    for body in deltas:
        for side, rows in (("bid", body["bids"]), ("ask", body["asks"])):
            for price, size in rows:
                if Decimal(size) == 0:
                    held[side].pop(price, None)
                else:
                    held[side][price] = size
    mirror = rf.feeds["BTCUSDT"]
    assert (held["bid"], held["ask"]) == mirror.book.top(50) == child.feeds["BTCUSDT"].book.top(50)
    assert len(mirror.book.bids) == len(mirror.book.asks) == 50  # the window, never the full book
    assert mirror.xu == child.feeds["BTCUSDT"].xu


async def test_the_receiver_counts_what_it_published_stamps_prints_and_yields_after_each_line() -> (
    None
):
    """Out of the pipe: `published` is what reached the hub, per stream as the child scheduled it,
    `scheduled` the in-process formula over the child's `t0`; a print's `ts_ms` is the receiver's
    wall clock; and no two lines are handled in one loop turn (#4833's yield, kept)."""
    child, lines = await child_lines(7, 200)
    data = b"".join(lines) + orjson.dumps(["0", 100.0]) + b"\n"
    assert len(data) < 60_000  # the default pipe holds it all: the writer never blocks here
    turns, at_line = 0, []

    class Counting(feed_proc.RemoteFeeder):
        async def handle(self, msg: list[Any]) -> None:
            at_line.append(turns)
            await super().handle(msg)

    rf = Counting(
        cast(SequencingHub, Recorder()), cast(Bus, SpyBus()), TABLE["symbols"][:4],
        tier_plan(4, 1, 1, TABLE["tiers"]), seed=7, wall_ms=lambda: NOW_MS, clock=lambda: 101.0,
    )  # fmt: skip
    r, w = os.pipe()
    os.write(w, data)
    os.close(w)
    os.set_blocking(r, False)
    rf._fd = r

    async def tick() -> None:
        nonlocal turns
        while True:
            turns += 1
            await asyncio.sleep(0)

    ticker = asyncio.create_task(tick())
    try:
        with pytest.raises(feed_proc.FeederGone):  # the writer's end closed: the pipe's EOF
            async with asyncio.timeout(30):  # a hang guard, never a latency bound
                await rf.run()
    finally:
        ticker.cancel()
        await asyncio.gather(ticker, return_exceptions=True)
        os.close(r)
    rf._fd = -1
    assert max(len(list(g)) for _, g in itertools.groupby(at_line)) == 1
    assert rf.stats() == feed.schedule_stats(child.streams, 1.0)
    assert sum(pub for _, pub in rf.stats().values()) == 200
    assert {int(t["ts_ms"]) for f in rf.feeds.values() for t in f.ring} == {NOW_MS}
    assert rf.scales("BTCUSDT") == child.scales("BTCUSDT")
    assert rf.tick_size("ETHUSDT") == child.tick_size("ETHUSDT")


async def test_the_child_process_writes_the_lines_the_child_feeder_writes() -> None:
    """`python -m bench.ws.feed_proc --steps N`: the real entry point, no clock, byte for byte."""
    plan = proc_plan(7, 2)
    argv = [sys.executable, "-m", "bench.ws.feed_proc", "--plan", json.dumps(plan)]
    done = await asyncio.to_thread(
        subprocess.run, [*argv, "--steps", "300"], cwd=feed_proc.API, capture_output=True,
        timeout=300, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr.decode()
    assert done.stdout == b"".join((await child_lines(7, 300, 2))[1])


async def spawn_child(seed: int = 7) -> tuple[asyncio.subprocess.Process, bytes]:
    """The real child, started the way `RemoteFeeder.start` does, and its hello line."""
    argv = [sys.executable, "-m", "bench.ws.feed_proc", "--plan", json.dumps(proc_plan(seed, 2))]
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        cwd=feed_proc.API, limit=1 << 24,
    )  # fmt: skip
    assert proc.stdout is not None
    async with asyncio.timeout(180):
        return proc, await proc.stdout.readline()


async def test_the_child_schedules_nothing_before_go_and_starts_its_clock_at_it() -> None:
    proc, line = await spawn_child()
    try:
        assert proc.stdout is not None and proc.stdin is not None
        assert orjson.loads(line)[0] == "h"
        with pytest.raises(TimeoutError):  # a bounded wait: no `0`, no slot, before the go
            async with asyncio.timeout(2.0):
                await proc.stdout.readline()
        assert proc.returncode is None
        before = time.monotonic()
        proc.stdin.write(b"go\n")
        await proc.stdin.drain()
        async with asyncio.timeout(60):
            first = orjson.loads(await proc.stdout.readline())
        assert first[0] == "0" and float(first[1]) >= before  # t0 is taken at the go
    finally:
        if proc.stdin is not None:
            proc.stdin.close()
        async with asyncio.timeout(60):
            code = await proc.wait()
    assert code == 0


async def test_the_child_exits_on_eof_before_the_go() -> None:
    proc, line = await spawn_child()
    assert orjson.loads(line)[0] == "h" and proc.stdin is not None
    proc.stdin.close()
    async with asyncio.timeout(60):
        assert await proc.wait() == 0
    assert proc.stdout is not None
    assert await proc.stdout.read() == b""  # it never wrote a `0` or a slot


@pytest.mark.parametrize("end", ["stdin", "stdout"])
async def test_the_child_exits_when_the_backend_closes_its_end(end: str) -> None:
    """No orphan: EOF on its stdin (the backend's lifeline) ends it while its lines are still
    read, and so does EPIPE when the backend stops reading and closes its end."""
    rf = remote(Recorder(), n=2)
    await rf.start()
    assert rf.proc is not None and rf.feeds.keys() == {"BTCUSDT", "ETHUSDT"}
    # bounded: a backend that stops reading stalls the child within PIPE_BYTES, not 64 KiB
    assert fcntl.fcntl(rf._fd, getattr(fcntl, "F_GETPIPE_SZ", 1032)) == feed_proc.PIPE_BYTES
    reader: asyncio.Task[None] | None = None
    try:
        if end == "stdin":
            reader = asyncio.create_task(rf.run())  # drained: only the EOF can end it
            assert rf.proc.stdin is not None
            rf.proc.stdin.close()
        else:  # stdin stays open: only the broken pipe can end it
            await rf.go()  # the schedule runs, so its next write finds the pipe closed
            os.close(rf._fd)
            rf._fd = -1
        async with asyncio.timeout(60):  # a hang guard
            code = await rf.proc.wait()
        assert code == 0
        if reader is not None:
            with pytest.raises(feed_proc.FeederGone):
                await reader
    finally:
        if reader is not None and not reader.done():
            reader.cancel()
        await rf.close()


async def test_a_client_applying_the_published_window_deltas_stays_equal_to_the_server_book() -> (
    None
):
    rec = Recorder()
    f = make_feeder(7, rec)
    book = f.feeds["BTCUSDT"].book
    bids, asks = book.top(50)
    held = {"bid": dict(bids), "ask": dict(asks)}
    await drive(f, 2000)
    deltas = [body for ch, body, _ in rec.calls if ch == "book.BTCUSDT.50"]
    assert len(deltas) > 100
    for body in deltas:
        for side, rows in (("bid", body["bids"]), ("ask", body["asks"])):
            for price, size in rows:
                if Decimal(size) == 0:
                    held[side].pop(price, None)
                else:
                    held[side][price] = size
    assert (held["bid"], held["ask"]) == book.top(50)
    assert all(len(held[s]) == 50 for s in held)  # a window stays exactly `depth` levels (7.3)


async def test_book_parts_decode_to_the_structured_body_and_trade_ids_never_repeat() -> None:
    rec = Recorder()
    f = make_feeder(3, rec, 3)
    await drive(f, 2500)
    for ch, body, part in rec.calls:
        assert part is not None
        if ch.startswith("book."):
            n = len(body["bids"]) + len(body["asks"])
            assert (
                part.body_kind == 2
                and len(part.records) == n
                and (part.price_scale, part.qty_scale) == (1, 3)
            )
    ids = [t["id"] for ch, body, _ in rec.calls if ch == "trades.BTCUSDT" for t in body["trades"]]
    assert len(ids) > 540 and len(ids) == len(set(ids))  # more than one pass over the recorded tape
    assert {i.rsplit(".", 1)[1] for i in ids} >= {"0", "1"}


async def test_a_feeder_that_fell_behind_gives_the_loop_a_turn_between_the_slots_it_replays() -> (
    None
):
    """#4833 (#571): a feeder up to `MAX_LATE_S` behind replays every slot it missed. Its steps
    never suspend (the book's publish is synchronous, the bus's queue is not full), so without a
    yield the whole backlog ran in one loop turn, beside the gateway it feeds. Each slot it
    replays now gives the loop a turn: no two steps at one loop-turn count."""
    turns, enough = 0, asyncio.Event()
    at_step: list[int] = []  # the loop-turn count at each step
    began = 1000.0
    reads = iter([began])  # `run` reads its start once, then finds itself 0.9 s behind

    def clock() -> float:
        return next(reads, began + 0.9)

    class Counting(Feeder):
        async def step(self, stream: Any) -> None:
            at_step.append(turns)
            if len(at_step) >= 40:
                enough.set()
            await super().step(stream)

    symbols = TABLE["symbols"][:4]
    f = Counting(
        cast(SequencingHub, Recorder()), Bus(), symbols, tier_plan(4, 1, 1, TABLE["tiers"]),
        seed=7, wall_ms=lambda: NOW_MS, clock=clock,
    )  # fmt: skip

    async def tick() -> None:
        nonlocal turns
        while True:  # a turn counts as it is taken
            turns += 1
            await asyncio.sleep(0)

    ticker, run = asyncio.create_task(tick()), asyncio.create_task(f.run())
    async with asyncio.timeout(10):  # a hang guard, never a latency bound
        await enough.wait()
    run.cancel()
    ticker.cancel()
    await asyncio.wait({run, ticker})
    runs = [len(list(steps)) for _, steps in itertools.groupby(at_step)]
    assert max(runs) == 1, runs


def test_the_schedule_is_drift_free_and_the_rate_is_the_tiers() -> None:
    f = make_feeder(7, Recorder(), 2)
    plan = f.schedule(2000)
    due = [t for t, i in plan if i == 0]  # the hot symbol's book stream: 50 a second
    assert all(b - a == pytest.approx(1 / 50) for a, b in itertools.pairwise(due))
    assert Tier(**TABLE["tiers"]["hot"]).book_per_s == 50


def test_scale_int_never_rounds() -> None:
    assert (
        scale_int("63120.60", 2) == 6312060
        and scale_int("0", 3) == 0
        and scale_int(Decimal("-1.5"), 1) == -15
    )
    with pytest.raises(ValueError, match="decimal places"):
        scale_int("1.25", 1)
    assert feed.BOOK_PRICE_SCALE == 1  # the recorded book is on one decimal place


# -- the CVWB port and the profile helper, against their Python twins (node) ---------------------


def node(*args: str) -> subprocess.CompletedProcess[str]:
    path = shutil.which("node")
    if path is None:
        pytest.skip("node is not on PATH: the k6 client's pure modules are checked with it")
    return subprocess.run(  # noqa: S603
        [path, "--no-warnings", *args], capture_output=True, text=True, timeout=120
    )


def test_the_cvwb_port_decodes_every_golden_vector_as_the_production_decoder_does() -> None:
    done = node(str(LOAD / "lib" / "cvwb.check.mjs"))
    assert done.returncode == 0, done.stderr
    assert "9 golden vectors" in done.stdout


def test_the_cvwb_check_fails_on_a_vector_that_disagrees(tmp_path: Path) -> None:
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
    vectors[4]["records"][0][3] = str(int(vectors[4]["records"][0][3]) + 1)  # a bars open price
    mutated = tmp_path / "vectors.json"
    mutated.write_text(json.dumps(vectors), encoding="utf-8")
    done = node(str(LOAD / "lib" / "cvwb.check.mjs"), str(mutated))
    assert done.returncode == 1 and "bars_v2: records[0][3]" in done.stderr


def test_the_js_profile_helper_resolves_and_lists_topics_as_the_python_twin_does() -> None:
    script = f"""
    import {{ readFileSync }} from 'node:fs';
    import {{ resolve, topicsFor }} from '{LOAD}/lib/profile.js';
    const table = JSON.parse(readFileSync('{profiles.PROFILES}', 'utf8'));
    const out = {{}};
    for (const name of {json.dumps(RUN_PROFILES)}) {{
      const p = resolve(table, name);
      out[name] = {{ p, topics: topicsFor(table, p).map((t) => [t.fam, t.ch]) }};
    }}
    console.log(JSON.stringify(out));
    """
    done = node("--input-type=module", "-e", script)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    for name in RUN_PROFILES:
        assert got[name]["p"] == profiles.resolve(TABLE, name)
        assert got[name]["topics"] == [
            list(t) for t in profiles.topics(TABLE, profiles.resolve(TABLE, name))
        ]


#: (welcome clock_skew_ms, hello rtt ms, corrected, |raw|, |corrected|): NTP's one-way estimate
SKEW_VECTORS = [
    (13, 20, 3, 13, 3),  # one host: the raw skew is the hello's transit, so it passes the guard
    (33, 30, 18, 33, 18),  # a real offset on top of the transit: still beyond the guard
    (-8, 4, -10, 8, 10),  # corrected before the absolute value: 10, not |-8| - 2 = 6
    (2, 20, -8, 2, 8),  # the correction crosses zero: the corrected reading is the larger one
    (7, 0, 7, 7, 7),  # a round trip inside one millisecond: nothing to take off
]


def test_the_js_skew_correction_takes_half_the_round_trip_off_the_raw_skew() -> None:
    script = f"""
    import {{ correctSkew }} from '{LOAD}/lib/skew.js';
    const vectors = {json.dumps([[raw, rtt] for raw, rtt, *_ in SKEW_VECTORS])};
    const sent = {NOW_MS};
    console.log(JSON.stringify(vectors.map(([raw, rtt]) => correctSkew(raw, sent, sent + rtt))));
    """
    done = node("--input-type=module", "-e", script)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [
        {"raw": raw, "rtt": rtt, "corrected": c, "absRaw": a_raw, "absCorrected": a_c}
        for raw, rtt, c, a_raw, a_c in SKEW_VECTORS
    ]


def test_the_js_skew_correction_returns_nothing_for_a_welcome_without_a_skew_or_a_time() -> None:
    script = f"""
    import {{ correctSkew }} from '{LOAD}/lib/skew.js';
    const none = [correctSkew(undefined, 1, 2), correctSkew(5, null, 2), correctSkew(5, 1, NaN)];
    console.log(JSON.stringify(none));
    """
    done = node("--input-type=module", "-e", script)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [None, None, None]


#: What node loads for every `k6/*` import, so that the k6 client's modules run outside k6: a
#: metric keeps its name and what each `add()` gave it; the rest are inert.
K6_STUB = (
    "export class Trend { constructor(name) { this.name = name; this.added = []; } "
    "add(v) { this.added.push(v); } } export class Counter extends Trend {} "
    "export class WebSocket {} export default {};"
)


def k6_node(body: str) -> subprocess.CompletedProcess[str]:
    """`body`, an ES module that imports the k6 client's modules, run by node over `K6_STUB`."""
    hook = (
        "export async function resolve(s, c, next) { return s.startsWith('k6/') ? { url: "
        f"'data:text/javascript,' + encodeURIComponent({json.dumps(K6_STUB)}), "
        "shortCircuit: true } : next(s, c); }"
    )
    script = "import { register } from 'node:module';\n"
    script += f"register('data:text/javascript,' + encodeURIComponent({json.dumps(hook)}));\n"
    return node("--input-type=module", "-e", script + body)


def test_the_js_summary_keeps_each_vus_hello_paired_and_out_of_the_pooled_trends() -> None:
    """k6 pools a metric's samples over every VU, which loses which round trip went with which
    skew, so each VU keeps its one hello in two trends of its own; the summary turns them into
    `hellos`, the pairs the guard reads: one for each VU whose two trends hold one sample each."""
    script = f"""
    const {{ helloTrends, summarize }} = await import('{LOAD}/lib/measure.js');
    const own = helloTrends(3);
    const trend = (v, count) => ({{ type: 'trend', values: {{ 'p(50)': v, max: v, count }} }});
    const metrics = {{ cv_hello_rtt_ms: trend(44, 3) }};
    for (const [vu, raw, rtt, n] of [[3, 7, 9, 2], [2, 40, 44, 1], [1, -2, 3, 1]]) {{
      metrics[own[vu - 1].raw.name] = trend(raw, n);
      metrics[own[vu - 1].rtt.name] = trend(rtt, n);
    }}
    console.log(JSON.stringify(summarize({{ metrics }}, {{}})));
    """
    done = k6_node(script)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert list(out["trends"]) == ["cv_hello_rtt_ms"]  # the pooled trend stays, the pairs move
    assert out["hellos"] == [{"vu": 1, "raw": -2, "rtt": 3}, {"vu": 2, "raw": 40, "rtt": 44}]


def test_the_js_welcome_keeps_the_vus_hello_pair_with_its_signed_raw_skew() -> None:
    """The line that keeps the pair, run: a server clock 5 ms behind stays -5 ms, never folded
    into one 5 ms ahead, and the hello's round trip goes beside it."""
    script = f"""
    const {{ helloTrends }} = await import('{LOAD}/lib/measure.js');
    const {{ Connection }} = await import('{LOAD}/lib/client.js');
    Date.now = () => {NOW_MS};
    const hello = helloTrends(1)[0];
    const c = new Connection({{ id: 1, topics: [], tokens: {{}}, hello }});
    c.ws = {{ readyState: 0 }};
    c.helloSentMs = {NOW_MS - 7};
    const p = {{ clock_skew_ms: -5, encoding: 'json', heartbeat: {{ interval_ms: 30000 }} }};
    c.welcome({{ p }});
    c.clearTimers();
    console.log(JSON.stringify([hello.raw.added, hello.rtt.added]));
    """
    done = k6_node(script)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [[-5], [7]]


# -- the egress guard and the send delay ----------------------------------------------


def test_the_egress_guard_refuses_a_lookup_and_a_connect_that_is_not_loopback() -> None:
    with fixture_app.egress_guard():
        with pytest.raises(RuntimeError, match="not loopback"):
            socket.getaddrinfo("exchange.example", 443)
        with socket.socket() as s, pytest.raises(RuntimeError, match="not loopback"):
            s.connect(("192.0.2.7", 443))
        socket.getaddrinfo("127.0.0.1", 80)  # loopback still resolves
    with pytest.raises(RuntimeError, match="not loopback"):
        fixture_app.assert_loopback("api.example")


async def test_the_send_delay_waits_before_a_websocket_send_and_touches_nothing_else() -> None:
    events: list[str] = []

    async def sleep(delay: float) -> None:
        events.append(f"sleep {delay}")

    async def app(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "websocket.send", "text": "x"})
        await send({"type": "websocket.close"})

    async def receive() -> MutableMapping[str, Any]:
        return {}

    async def out(message: MutableMapping[str, Any]) -> None:
        events.append(message["type"])

    await fixture_app.SendDelay(app, 0.05, sleep)({"type": "websocket"}, receive, out)
    assert events == ["sleep 0.05", "websocket.send", "websocket.close"]  # only the send waits
    events.clear()
    await fixture_app.SendDelay(app, 0.5, sleep)({"type": "http"}, receive, out)
    assert events == ["websocket.send", "websocket.close"]  # not a websocket scope: no wait at all


# -- the real fixture backend, with a tiny protocol client ---------------------------


async def recv(ws: Any, wait_s: float = 10.0) -> dict[str, Any]:
    async with asyncio.timeout(wait_s):
        frame: dict[str, Any] = json.loads(await ws.recv())
    return frame


def apply(state: dict[str, dict[int, int]], frame: Frame, *, reset: bool) -> None:
    if reset:
        state["bid"].clear()
        state["ask"].clear()
    for side, price, size in frame.records:
        book = state["ask" if side else "bid"]
        if size == 0:
            book.pop(price, None)
        else:
            book[price] = size


@pytest.mark.parametrize(("flag", "feeder"), [(True, "inproc"), (False, "inproc"), (True, "proc")])
async def test_the_backend_serves_the_real_gateway_and_a_client_ends_consistent(
    flag: bool, feeder: str, tmp_path: Path
) -> None:
    """`feeder="proc"` (#571): the same, fed by the child through the receiver; the child is
    reaped when the backend exits."""
    cfg = fixture_app.BackendConfig(
        symbols=("BTCUSDT", "ETHUSDT"), hot=1, warm=1, users=1, connections=1, flag=flag,
        feeder=feeder,
    )  # fmt: skip
    async with fixture_app.Backend(cfg, TABLE, tmp_path) as be:
        assert (tmp_path / "tokens.json").stat().st_mode & 0o777 == 0o600
        url = f"ws://127.0.0.1:{be.port}/ws"
        with pytest.raises(
            websockets.exceptions.InvalidStatus
        ):  # 2.5: only the allow-listed origin
            async with websockets.connect(
                url, subprotocols=cast(Any, ["cv.v1.json"]), origin=cast(Any, "http://evil.test")
            ):
                pass
        async with websockets.connect(
            url, subprotocols=cast(Any, ["cv.v1.json"]), origin=cast(Any, TABLE["origin"])
        ) as ws:
            assert ws.subprotocol == "cv.v1.json"
            assert [e.name for e in ws.protocol.extensions] == ["permessage-deflate"]
            await ws.send(
                json.dumps(
                    {
                        "t": "hello",
                        "id": "c-1",
                        "p": {"client": "t", "client_version": "1", "protocol": "cv.v1"},
                    }
                )
            )
            welcome = await recv(ws)
            assert (
                welcome["p"]["features"]["coalescing"] is flag
                and welcome["p"]["encoding"] == "json"
            )
            await ws.send(
                json.dumps(
                    {"t": "auth", "id": "c-2", "p": {"access_token": be.tokens["u0"][0]["access"]}}
                )
            )
            assert (await recv(ws))["t"] == "auth_ok"
            chans = [
                "book.BTCUSDT.50",
                "trades.BTCUSDT",
                "bars.BTCUSDT.time.1",
                "footprint.BTCUSDT.time.5",
            ]
            await ws.send(
                json.dumps({"t": "sub", "id": "c-3", "p": {"topics": [{"ch": c} for c in chans]}})
            )
            state: dict[str, dict[int, int]] = {"bid": {}, "ask": {}}
            seen: dict[str, int] = {}
            want: dict[str, dict[int, int]] | None = None
            async with asyncio.timeout(30):  # a bound on a failure, never the pass condition
                while want is None or state != want:  # the book is final once the feeder stops
                    m = await recv(ws)
                    if m["t"] == "sub_ok":
                        assert all(r["ok"] for r in m["p"]["results"])
                    if m["t"] == "ping":
                        pong = {"t": "pong", "id": m["id"], "p": {"client_ms": 1}}
                        await ws.send(json.dumps(pong))
                    if m["t"] not in ("snap", "d"):
                        continue
                    key = f"{m['t']}:{m['ch'].split('.')[0]}"
                    seen[key] = seen.get(key, 0) + 1
                    assert m["e"] == "b64"  # the hot topics are binary on cv.v1.json (3.2)
                    part = decode_b64(m["p"])
                    if m["ch"].startswith("book."):
                        apply(state, part, reset=m["t"] == "snap")
                    enough = all(seen.get(k, 0) >= n for k, n in (("d:book", 12), ("d:trades", 3)))
                    if want is None and enough and seen.get("d:bars", 0) >= 1:
                        be._tasks[1].cancel()  # the feeder stops; what is in flight still arrives
                        await asyncio.gather(be._tasks[1], return_exceptions=True)
                        top = be.feeder.feeds["BTCUSDT"].book.top(50)
                        want = {
                            side: {scale_int(p, 1): scale_int(s, 3) for p, s in levels.items()}
                            for side, levels in zip(("bid", "ask"), top, strict=True)
                        }
            assert {"snap:book", "snap:trades", "snap:bars", "d:book", "d:trades", "d:bars"} <= set(
                seen
            )
            assert "snap:footprint" not in seen  # pending: no producer (#2197)
            assert state == want  # the frames the gateway sent rebuild the server's top 50, exactly
        scrape = await asyncio.to_thread(runner.get, be.port, "/metrics")
        assert (
            "cv_ws_fanout_seconds_bucket" in scrape
            and 'cv_bench_feed_scheduled_total{kind="book"}' in scrape
        )
        assert "event_loop_lag_seconds" in scrape and "process_resident_memory_bytes" in scrape
        assert ("cv_bench_feeder_cpu_seconds_total" in scrape) is (feeder == "proc")
    if feeder == "proc":
        proc = cast(feed_proc.RemoteFeeder, be.feeder).proc
        assert proc is not None and proc.returncode is not None  # ended and reaped
        with pytest.raises(ProcessLookupError):
            os.kill(proc.pid, 0)


async def test_the_refresh_double_rotates_a_session_and_the_socket_re_auths_in_place(
    tmp_path: Path,
) -> None:
    cfg = fixture_app.BackendConfig(
        symbols=("BTCUSDT",), hot=1, warm=0, users=1, connections=1, flag=False
    )
    async with fixture_app.Backend(cfg, TABLE, tmp_path) as be:
        first = be.tokens["u0"][0]
        url = f"ws://127.0.0.1:{be.port}/ws"
        async with websockets.connect(
            url, subprotocols=cast(Any, ["cv.v1.json"]), origin=cast(Any, TABLE["origin"])
        ) as ws:
            await ws.send(
                json.dumps(
                    {
                        "t": "hello",
                        "id": "c-1",
                        "p": {"client": "t", "client_version": "1", "protocol": "cv.v1"},
                    }
                )
            )
            await recv(ws)
            await ws.send(
                json.dumps({"t": "auth", "id": "c-2", "p": {"access_token": first["access"]}})
            )
            await recv(ws)
            body = json.dumps({"refresh_token": first["refresh"]})
            rotated = await asyncio.to_thread(post, be.port, "/auth/refresh", body)
            assert (
                rotated["access_token"] != first["access"]
                and rotated["refresh_token"] != first["refresh"]
            )
            await ws.send(
                json.dumps(
                    {"t": "auth", "id": "c-3", "p": {"access_token": rotated["access_token"]}}
                )
            )
            while (m := await recv(ws))["t"] != "auth_ok":
                assert m["t"] in ("ping",)
            assert m["id"] == "c-3"


def post(port: int, path: str, body: str) -> dict[str, str]:
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    conn.request("POST", path, body, {"Content-Type": "application/json"})
    out: dict[str, str] = json.loads(conn.getresponse().read())
    conn.close()
    return out


# -- the runner's pure parts, on saved artefacts ---------------------------------------------------

HEALTHY_FANOUT = {0.01: 2900, 0.02: 3150, 0.03: 3200}
TIMED_OUT_SCRAPE = {"timeout_s": 15.0, "attempted": 12, "timed_out_ms": [15003], "missing": []}


def make_run(
    out: Path, *, bandwidth: float = 9.0, fanout: dict[float, int] | None = None, **over: Any
) -> Path:
    """The artefacts of a run (`runner.execute` writes these), healthy unless overridden."""
    out.mkdir(parents=True)
    facts: dict[str, Any] = {
        "harness": "e17-q03/1",
        "profile": "A",
        "resolved": profiles.resolve(TABLE, "A") | {"name": "A"},
        "flag": "on",
        "steady_s": 3600.0,
        "warmup_s": 300.0,
        "profile_duration_s": 3600.0,
        "profile_warmup_s": 300.0,
        "k6_exit": 0,
        "k6_version": "v2.3.0",
        "staging": True,
        "cpus": ["0-7", "8-15"],
        "cgroup": "4cpu-8g",
        "loop": "asyncio",
        "k6_cpu_frac": 0.3,
        "rss_bytes": 200 << 20,
        "mem_max_bytes": 8 << 30,
        "oom_events": 0,
        "commit": "a" * 40,
        "cpu_model": "cpu-x",
        "kernel": "6",
        "machine_profile": "m+4cpu-8g",
        "variance": {"nr_throttled": 0, "other_cores": 0.1},
        "finished": "2026-10-20T00:00:00Z",
    }
    facts |= over
    t = {
        k: {"count": 100, "p50": v / 2, "p95": v, "p99": v, "max": v}
        for k, v in {
            "cv_tick_decode_ms_trades": 95.0,
            "cv_release_decode_ms_trades": 2.0,
            "cv_rw_kib_s": bandwidth,
            "cv_resnap_kib": 9.0,
            "cv_resnap_ms": 6.0,
            "cv_client_lag_ms": 1.0,
            "cv_clock_skew_ms": 1.0,
        }.items()
    }
    lines = [
        f'cv_ws_fanout_seconds_bucket{{env="demo",le="{le:g}"}} {n}'
        for le, n in (fanout or HEALTHY_FANOUT).items()
    ]
    total = max((fanout or HEALTHY_FANOUT).values())
    lines += [
        f'cv_ws_fanout_seconds_bucket{{env="demo",le="+Inf"}} {total}',
        f'cv_ws_fanout_seconds_count{{env="demo"}} {total}',
    ]
    lines += [
        'cv_bench_feed_scheduled_total{kind="book"} 100',
        'cv_bench_feed_published_total{kind="book"} 100',
        "process_cpu_seconds_total 600",
    ]
    (out / "run.json").write_text(json.dumps(facts), encoding="utf-8")
    (out / "summary.json").write_text(
        json.dumps({"schema": 1, "trends": t, "counters": {"cv_connections_up": 6}}),
        encoding="utf-8",
    )
    (out / "scrape0.txt").write_text("cv_ws_connections_in_use 6\n", encoding="utf-8")
    (out / "scrape1.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def test_finish_writes_the_report_and_exits_by_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "none")
    ok = make_run(tmp_path / "ok")
    assert runner.finish(ok, 0.10) == 0
    report = (ok / "report.md").read_text(encoding="utf-8")
    assert "# E17-Q03 WS load report: A, flag on: PASS" in report and "Not staged" not in report
    assert (
        "Approximations" in report
        and "Not measurable here" in report
        and "bars_symbols" not in report
    )
    assert "asyncio loop" in report and "uvloop" in report  # the approximation a baseline carries
    assert (
        json.loads((ok / "result.json").read_text(encoding="utf-8"))["result"]["status"] == "PASS"
    )
    assert runner.finish(make_run(tmp_path / "bw", bandwidth=1126.4), 0.10) == 1
    assert "| FAIL |" in (tmp_path / "bw" / "report.md").read_text(encoding="utf-8")
    assert runner.finish(make_run(tmp_path / "k6", k6_exit=107, bandwidth=1126.4), 0.10) == 2
    banner = (tmp_path / "k6" / "report.md").read_text(encoding="utf-8")
    assert "k6_exit: 107" in banner and "; missed: s16_3.bandwidth.reference_workspace):" in banner


def test_a_scrape_timeout_reads_fail_and_lists_the_guard_that_also_tripped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "none")
    # k6 exit 107 trips a guard
    run = make_run(tmp_path / "run", k6_exit=107, scrapes=TIMED_OUT_SCRAPE)
    assert runner.finish(run, 0.10) == 1
    console, report = capsys.readouterr().out, (run / "report.md").read_text(encoding="utf-8")
    assert "FAIL, failed: scrape.metrics_timeout" in console and "also invalid: k6_exit" in console
    assert report.splitlines()[0].endswith(": FAIL") and "- k6_exit: 107" in report
    result = json.loads((run / "result.json").read_text(encoding="utf-8"))["result"]
    assert (result["status"], result["invalid"]) == ("FAIL", ["k6_exit: 107"])


def test_the_report_heads_the_guards_a_scrape_line_outranks_as_also_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "none")
    run = make_run(tmp_path / "run", k6_exit=107, scrapes=TIMED_OUT_SCRAPE)
    runner.finish(run, 0.10)
    head = "Also invalid (a validity guard tripped; scrape.metrics_timeout decides FAIL):"
    assert f"{head}\n- k6_exit: 107" in (run / "report.md").read_text(encoding="utf-8")


def hello_skew_run(out: Path, **over: Any) -> Path:
    """A healthy run whose summary carries the hello-skew trends the k6 client writes now: on one
    host the server's skew (13 ms at most) is the hello's transit (20 ms p50, 33 ms at most)."""
    make_run(out, **over)
    path = out / "summary.json"
    summ = json.loads(path.read_text(encoding="utf-8"))
    summ["trends"] |= {
        "cv_clock_skew_ms": {"count": 6, "p50": 9.0, "p95": 12.0, "p99": 13.0, "max": 13.0},
        "cv_clock_skew_corrected_ms": {"count": 6, "p50": 1.0, "p95": 2.0, "p99": 3.0, "max": 3.0},
        "cv_hello_rtt_ms": {"count": 6, "p50": 20.0, "p95": 30.0, "p99": 33.0, "max": 33.0},
    }
    path.write_text(json.dumps(summ), encoding="utf-8")
    return out


def test_the_report_shows_the_raw_and_corrected_skew_the_hello_rtt_and_same_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "none")
    run = hello_skew_run(tmp_path / "run", same_host=True)
    assert runner.finish(run, 0.10) == 0  # 13 ms raw is over the 5 ms guard, 3 ms corrected is not
    assert (
        "- Clock skew at the hello (same_host true, skew_estimator max_over_hellos): corrected max "
        "3.0 ms against 5 ms (max over 6 hellos of |raw - RTT/2|; raw max 13.0 ms; hello RTT p50 "
        "20.0 ms / max 33.0 ms)\n- WARNING: the summary has no per-hello pairs; the skew was "
        "measured with max_over_hellos (the fallback)\n"
    ) in (run / "report.md").read_text(encoding="utf-8")


def test_a_run_with_paired_hellos_reports_its_minimum_rtt_hello_and_names_the_estimator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "none")
    run = hello_skew_run(tmp_path / "run", same_host=True)
    summ = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    pairs = [(13.0, 33.0), (9.0, 17.0), (10.0, 20.0), (11.0, 22.0), (10.0, 21.0), (12.0, 24.0)]
    summ["hellos"] = [{"vu": i, "raw": r, "rtt": t} for i, (r, t) in enumerate(pairs, 1)]
    (run / "summary.json").write_text(json.dumps(summ), encoding="utf-8")
    assert runner.finish(run, 0.10) == 0
    report = (run / "report.md").read_text(encoding="utf-8")
    assert (  # the pairs pick the hello; the pooled trend gives the round trips' p50 and max
        "- Clock skew at the hello (same_host true, skew_estimator min_rtt_hello): corrected 0.5 "
        "ms against 5 ms (the minimum-RTT hello of 6: raw 9.0 ms, RTT 17.0 ms; hello RTT p50 20.0 "
        "ms / max 33.0 ms)"
    ) in report
    skew = json.loads((run / "result.json").read_text(encoding="utf-8"))["result"]["clock_skew"]
    assert skew["skew_estimator"] == "min_rtt_hello" and skew["hello_rtt"] == 17.0
    assert skew["warning"] is None and "WARNING" not in report  # read as meant: nothing to say


def test_result_json_keeps_the_skew_the_rtt_and_same_host_in_the_run_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "none")
    run = hello_skew_run(tmp_path / "run", same_host=True)
    runner.finish(run, 0.10)
    body = json.loads((run / "result.json").read_text(encoding="utf-8"))
    assert body["facts"]["same_host"] is True
    assert body["result"]["clock_skew"] == {
        "skew_ms": 3.0,
        "skew_estimator": "max_over_hellos",  # its summary has no pairs: written before them
        "raw": 13.0,
        "rtt_p50": 20.0,
        "rtt_max": 33.0,
        "hellos": 6,
        "rtt_corrected": True,
        "send_delay_ms": 0.0,
        "hello_raw": None,
        "hello_rtt": None,
        "warning": (
            "the summary has no per-hello pairs; the skew was measured with max_over_hellos "
            "(the fallback)"
        ),
        "judged": True,
    }


def test_a_run_saved_before_the_correction_is_reported_as_raw_with_no_host_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "none")
    run = make_run(tmp_path / "old")  # only the raw skew in its summary, no same_host in run.json
    assert runner.finish(run, 0.10) == 0
    assert (
        "- Clock skew at the hello (same_host not recorded, skew_estimator raw_max): raw max 1.0 "
        "ms against 5 ms (max over 100 hellos of |raw|; not RTT-corrected: the summary has no "
        "cv_clock_skew_corrected_ms)\n- WARNING: the summary has no cv_clock_skew_corrected_ms; "
        "the skew was measured with raw_max (the fallback)\n"
    ) in (run / "report.md").read_text(encoding="utf-8")


def test_a_run_whose_welcomes_were_never_timed_reports_no_skew(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "none")
    run = make_run(tmp_path / "run")
    path = run / "summary.json"
    summ = json.loads(path.read_text(encoding="utf-8"))
    del summ["trends"]["cv_clock_skew_ms"]  # no welcome was timed
    path.write_text(json.dumps(summ), encoding="utf-8")
    assert runner.finish(run, 0.10) == 0
    assert "Clock skew" not in (run / "report.md").read_text(encoding="utf-8")
    body = json.loads((run / "result.json").read_text(encoding="utf-8"))
    assert body["result"]["clock_skew"] is None


def baseline_15_percent_better(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Three runs, and a recorded baseline each of them is 15 % worse than."""
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "base")
    runs = [make_run(tmp_path / f"run{i}") for i in range(3)]
    now = runner.judge(runs[0])[0].verdict.metrics
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "A.json").write_text(
        json.dumps(
            {
                "harness_version": "e17-q03/1",
                "machine_profile": "m+4cpu-8g",
                "gate": "gated",
                "loop": "asyncio",
                "run_profile": "full",
                "metrics": {k: {**m, "p95": m["p95"] / 1.15} for k, m in now.items()},
            }
        ),
        encoding="utf-8",
    )
    return runs


@pytest.mark.parametrize(("tolerance", "code"), [(0.05, 1), (0.10, 1), (0.20, 0)])
def test_the_gate_fails_on_the_median_of_three_runs_at_the_tolerance(
    tolerance: float,
    code: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dirs = [str(d) for d in baseline_15_percent_better(tmp_path, monkeypatch)]
    assert runner.cmd_gate(argparse.Namespace(dirs=dirs, tolerance=tolerance)) == code
    assert ("::error::A: fanout_ms" in capsys.readouterr().out) is (code == 1)


def test_one_run_only_warns_about_a_regression_because_c_13_9_gates_the_median_of_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = baseline_15_percent_better(tmp_path, monkeypatch)
    assert runner.finish(runs[0], runner.TOLERANCE) == 0
    out = capsys.readouterr().out
    assert "::warning::A: fanout_ms" in out and "C-13.9 gates the median of 3" in out
    assert "::error::" not in out
    assert (runner.TOLERANCE, runner.MIN_GATE_RUNS) == (0.05, 3)  # the default gate


def test_record_writes_a_warn_only_baseline_of_a_passing_run_and_never_under_ci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "base")
    monkeypatch.delenv("CI", raising=False)
    ok = make_run(tmp_path / "ok", flag="off")
    assert runner.cmd_record(argparse.Namespace(dir=str(ok))) == 0
    base = json.loads((tmp_path / "base" / "A-flag-off.json").read_text(encoding="utf-8"))
    assert (base["harness_version"], base["gate"], base["flag"]) == (
        "e17-q03/1",
        "warn-only",
        "off",
    )
    assert base["machine_profile"] == "m+4cpu-8g" and "fanout_ms" in base["metrics"]
    assert (base["loop"], base["k6_version"], base["cgroup"]) == ("asyncio", "v2.3.0", "4cpu-8g")
    assert base["commit"] == "a" * 40 and base["cpu_model"] == "cpu-x"
    assert (
        runner.cmd_record(argparse.Namespace(dir=str(make_run(tmp_path / "bad", k6_exit=107)))) == 1
    )
    monkeypatch.setenv("CI", "true")
    with pytest.raises(RuntimeError, match="never rewritten by CI"):
        runner.cmd_record(argparse.Namespace(dir=str(ok)))


def test_median_of_three_runs_is_what_the_five_percent_gate_compares(tmp_path: Path) -> None:
    slow = {0.01: 100, 0.02: 400, 0.03: 3200}
    outs = [
        make_run(tmp_path / "a"),
        make_run(tmp_path / "b", fanout=slow),
        make_run(tmp_path / "c"),
    ]
    res, facts = runner.merge([runner.judge(o) for o in outs])
    one = runner.judge(outs[0])[0].verdict.metrics["fanout_ms"]["p95"]
    assert res.verdict.metrics["fanout_ms"]["p95"] == pytest.approx(one)  # two of three are healthy
    assert facts["profile"] == "A"


def test_repro_fails_on_a_headline_that_moved_unless_a_variance_source_is_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = (
        make_run(tmp_path / "a"),
        make_run(tmp_path / "b", bandwidth=12.0),
    )  # +33 % on the bandwidth
    args = argparse.Namespace(dir_a=str(a), dir_b=str(b), variance_source=None)
    assert runner.cmd_repro(args) == 1 and "s16_3" not in capsys.readouterr().out
    assert (
        runner.cmd_repro(
            argparse.Namespace(dir_a=str(a), dir_b=str(b), variance_source=["noisy neighbour"])
        )
        == 0
    )
    c = make_run(tmp_path / "c", bandwidth=12.0, variance={"nr_throttled": 4, "other_cores": 0.1})
    assert (
        runner.cmd_repro(argparse.Namespace(dir_a=str(a), dir_b=str(c), variance_source=None)) == 0
    )
    assert "cpu throttling" in capsys.readouterr().out
    same = make_run(tmp_path / "d")
    assert (
        runner.cmd_repro(argparse.Namespace(dir_a=str(a), dir_b=str(same), variance_source=None))
        == 0
    )


def test_the_runner_takes_only_the_pinned_k6_from_k6_bin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(version: str) -> str:
        path = tmp_path / f"k6-{version}"
        path.write_text(
            f"#!/bin/sh\necho 'k6 {version} (commit/abc, go1.26.8, linux/amd64)'\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        return str(path)

    monkeypatch.delenv("K6_BIN", raising=False)
    with pytest.raises(SystemExit, match="K6_BIN"):
        runner.k6_binary()  # never looked up on PATH
    monkeypatch.setenv("K6_BIN", fake("v1.9.0"))
    with pytest.raises(SystemExit, match=r"pinned to k6 v2\.3\.0"):
        runner.k6_binary()
    pinned = fake("v2.3.0")
    monkeypatch.setenv("K6_BIN", pinned)
    assert runner.k6_binary() == pinned
    monkeypatch.setenv("K6_BIN", pinned + "/")  # the checks normalise the slash away
    assert runner.k6_binary() == pinned  # and the path they checked is the one run and returned


def is_file_of_python_313(self: Path, **_: object) -> bool:
    """`Path.is_file()` from Python 3.13: `os.path.isfile`, False for every OSError. Up to 3.12 it
    raised for EACCES and ENAMETOOLONG. The refusals must be the same under either."""
    return os.path.isfile(self)


@pytest.mark.parametrize(
    ("kind", "why"),
    [
        ("bare name", "not an absolute path"),  # a PATH lookup, or the working directory's
        ("relative path", "not an absolute path"),  # a real, executable file, but a relative one
        ("directory", "not a regular file"),  # absolute and searchable, but not a file
        ("missing file", "not a regular file"),  # stat fails with ENOENT
        ("through a file", "not a regular file"),  # stat fails with ENOTDIR
        ("not executable", "not executable"),  # a regular file whose mode has no x bit
        pytest.param(  # stat fails with EACCES, not ENOENT
            "unsearchable parent",
            "cannot be checked",
            marks=pytest.mark.skipif(os.geteuid() == 0, reason="root searches any directory"),
        ),
        ("over-long path", "cannot be checked"),  # stat fails with ENAMETOOLONG
        ("symlink loop", "cannot be checked"),  # stat fails with ELOOP: any other OSError
    ],
)
def test_a_k6_bin_that_is_not_an_absolute_executable_file_is_refused_before_anything_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, why: str
) -> None:
    script = "#!/bin/sh\necho 'k6 v2.3.0 (commit/abc, go1.26.8, linux/amd64)'\n"
    locked = tmp_path / "locked"
    locked.mkdir()
    files = {tmp_path / "k6": 0o755, tmp_path / "plain": 0o644, locked / "k6": 0o755}
    for path, mode in files.items():
        path.write_text(script, encoding="utf-8")
        path.chmod(mode)
    (tmp_path / "loop").symlink_to(tmp_path / "loop")
    value = {
        "bare name": "k6",
        "relative path": "./k6",
        "directory": str(tmp_path),
        "missing file": str(tmp_path / "gone"),
        "through a file": str(tmp_path / "plain" / "k6"),
        "not executable": str(tmp_path / "plain"),
        "unsearchable parent": str(locked / "k6"),
        "over-long path": "/" + "k" * 5000,
        "symlink loop": str(tmp_path / "loop"),
    }[kind]
    started: list[object] = []

    def spy(*args: object, **kwargs: object) -> None:
        started.append(args)
        raise AssertionError(f"a process was started for K6_BIN={value!r}: {args!r}")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("K6_BIN", value)
    monkeypatch.setattr(subprocess, "run", spy)  # the one runner.k6_binary calls
    if kind == "unsearchable parent":
        locked.chmod(0o600)  # no x bit: the k6 inside cannot be reached
    try:
        for is_file in (Path.is_file, is_file_of_python_313):  # the interpreter's, and 3.13's
            monkeypatch.setattr(Path, "is_file", is_file)
            with pytest.raises(SystemExit, match=why):
                runner.k6_binary()
    finally:
        locked.chmod(0o700)  # so that tmp_path can be removed
    assert started == []  # no process was started for a path that failed the check


@pytest.mark.parametrize(
    "raised",
    [
        PermissionError(13, "Permission denied"),
        OSError(8, "Exec format error"),
        subprocess.CalledProcessError(1, "k6 version"),
        subprocess.TimeoutExpired("k6 version", 30),
    ],
    ids=["permission denied", "exec format error", "non-zero exit", "timeout"],
)
def test_a_k6_bin_that_cannot_be_run_is_refused_never_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raised: Exception
) -> None:
    k6 = tmp_path / "k6"  # an absolute, executable, regular file: the filesystem checks pass
    k6.write_text("#!/bin/sh\n", encoding="utf-8")
    k6.chmod(0o755)

    def fail(*_: object, **__: object) -> None:
        raise raised

    monkeypatch.setenv("K6_BIN", str(k6))
    monkeypatch.setattr(subprocess, "run", fail)  # the one runner.k6_binary calls
    with pytest.raises(SystemExit, match="cannot be run") as refused:
        runner.k6_binary()
    assert str(k6) in str(refused.value)


def test_a_run_plan_applies_the_overrides_to_the_resolved_profile() -> None:
    ns = argparse.Namespace(
        flag="off",
        staging=True,
        seed=9,
        duration_s=90.0,
        warmup_s=15.0,
        rtt_delay_ms=700.0,
        reauth_after_s=None,
        probe_every_s=None,
        send_delay_ms=None,
        gate_on="including",
        backend_cpus=None,
        k6_cpus="2-3",
        trace_sp=False,
    )
    p = runner.plan(TABLE, ns, "smoke", Path("out"), families=["book"])
    assert (p.profile, p.flag, p.staging, p.seed, p.duration_s) == ("smoke", False, True, 9, 90.0)
    assert (p.backend_cpus, p.k6_cpus) == ("0-7", "2-3")  # --staging's default, one overridden
    assert (
        p.prof["rtt_delay_ms"] == 700.0
        and p.prof["warmup_s"] == 15.0
        and p.prof["families"] == ["book"]
    )
    assert p.prof["gate_on"] == "including" and p.prof["reauth_after_s"] == 45  # the smoke's own
    assert runner.baseline_name({"profile": "A", "flag": "off"}) == "A-flag-off"
    assert runner._cpus("0-7") == 8 and runner._cpus("0,2-3") == 3
    assert (p.feeder, p.feeder_cpus) == ("inproc", None)  # a namespace without it: as before


def test_a_proc_feeder_runs_off_the_backends_cpus_on_k6s_unless_given_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def plan(**over: Any) -> runner.Plan:
        return runner.plan(TABLE, args(**over), "smoke", tmp_path)

    p = plan(feeder="proc", staging=True)
    assert (p.feeder, p.backend_cpus, p.feeder_cpus) == ("proc", "0-7", "8-15")
    assert plan(feeder="proc", k6_cpus="4-7", feeder_cpus="3").feeder_cpus == "3"
    assert plan(feeder="proc").feeder_cpus is None  # no cpusets at all: the runner's own set
    assert plan(k6_cpus="4-7").feeder_cpus is None  # in process there is no child to pin
    assert plan(feeder="proc", backend_cpus="0-3", k6_cpus="4-7").feeder_cpus == "4-7"
    assert plan(feeder="proc", backend_cpus="0-3", feeder_cpus="5").feeder_cpus == "5"
    assert plan(backend_cpus="0-3").feeder_cpus is None  # in process nothing is refused
    with pytest.raises(ValueError, match="feeder 'x'"):
        plan(feeder="x")
    seen: list[list[str]] = []

    def popen(argv: list[str], **_: Any) -> None:
        seen.append(argv)
        raise RuntimeError("stop here")

    monkeypatch.setattr(runner, "subprocess", SimpleNamespace(Popen=popen, PIPE=-1))
    for p in (plan(), plan(feeder="proc", k6_cpus="4-7")):
        with pytest.raises(RuntimeError, match="stop here"):
            runner.start_backend(p)
    assert seen[0][-2:] == ["--feeder", "inproc"]
    assert seen[1][-4:] == ["--feeder", "proc", "--feeder-cpus", "4-7"]
    cfg = fixture_app.BackendConfig.for_profile(TABLE, "B", flag=True, seed=1, feeder="proc")
    assert (cfg.feeder, cfg.feeder_cpus) == ("proc", None)


def test_a_proc_feeder_with_a_pinned_backend_and_no_cpus_of_its_own_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The child would inherit the backend's own cpus while the report said `any`: exit 2."""
    with pytest.raises(SystemExit) as refused:
        runner.plan(TABLE, args(feeder="proc", backend_cpus="0-3"), "smoke", tmp_path)
    assert refused.value.code == 2
    out = capsys.readouterr().out
    assert "--feeder-cpus" in out and "0-3" in out and out.startswith("::error::")


def test_an_unpinned_proc_feeder_is_reported_as_inheriting_not_as_any(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = "process_cpu_seconds_total 1\ncv_bench_feeder_cpu_seconds_total 0\n"
    t1 = "process_cpu_seconds_total 31\ncv_bench_feeder_cpu_seconds_total 15.5\n"
    out = execute_virtually(tmp_path / "p", monkeypatch, [t0, t1], 30.0, feeder="proc")
    res, facts = runner.judge(out)
    report = runner.render(res, facts, runner.compare(res, facts, 0.05))
    assert "on cpus 0:" in report
    facts = facts | {"feeder_cpus": None}
    report = runner.render(res, facts, runner.compare(res, facts, 0.05))
    assert "cpus any:" not in report and "inherited, not pinned" in report


def test_a_plan_keeps_the_profiles_own_length_apart_from_the_overridden_one(tmp_path: Path) -> None:
    """The producer half of the run label: `plan` takes the nominal window and warm-up from the
    table before any override, so `run_profile` has something to measure a shortened run against."""
    for name, over, nominal in (
        ("A", {"duration_s": 120.0, "warmup_s": 20.0}, (3600.0, 300.0)),
        ("smoke", {"duration_s": 75.0, "warmup_s": 12.0}, (120.0, 20.0)),
    ):
        p = runner.plan(TABLE, args(**over), name, tmp_path)
        assert (p.duration_s, p.prof["warmup_s"]) == (over["duration_s"], over["warmup_s"])
        assert (p.nominal_duration_s, p.nominal_warmup_s) == nominal


def test_execute_writes_the_profiles_own_length_the_loop_and_the_host_to_run_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half: a run cut to 120 s says so in run.json. A stand-in backend that serves
    nothing and a k6 that exits at once: `execute` still writes the run's facts and stops what it
    started."""
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    backend = subprocess.Popen(sleeper, stdout=subprocess.PIPE, text=True)  # noqa: S603 - ours
    monkeypatch.setattr(runner, "start_backend", lambda p: (backend, 1, backend.pid))
    k6 = tmp_path / "k6"
    k6.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    k6.chmod(0o755)
    p = runner.plan(TABLE, args(duration_s=120.0, warmup_s=20.0), "A", tmp_path / "out")
    facts = json.loads((runner.execute(p, str(k6)) / "run.json").read_text(encoding="utf-8"))
    assert (facts["steady_s"], facts["warmup_s"]) == (120.0, 20.0)
    assert (facts["profile_duration_s"], facts["profile_warmup_s"]) == (3600.0, 300.0)
    assert runner.run_profile(facts) == "smoke"
    assert facts["loop"] == "asyncio"
    assert (facts["feeder"], facts["feeder_cpus"], facts["feeder_cpu_cores"]) == (
        "inproc", None, None,
    )  # fmt: skip
    assert facts["same_host"] is True  # the runner starts both; k6 refuses a remote target
    assert backend.poll() is not None  # stopped, not left running


# -- a /metrics scrape that times out is recorded, and the run goes on ----------------------------


def get_that(*answers: object) -> Callable[[int, str], str]:
    """A stand-in for `runner.get`: each call gives the next answer, or raises an exception."""
    queue = iter(answers)

    def get(port: int, path: str) -> str:
        answer = next(queue)
        if isinstance(answer, BaseException):
            raise answer
        return str(answer)

    return get


def test_a_periodic_scrape_that_times_out_is_a_sample_and_the_next_scrape_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter([10.0, 25.002, 30.0])  # the first request began, it timed out, the next began
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    answers = get_that(TimeoutError(), "process_resident_memory_bytes 5\n")
    monkeypatch.setattr(runner, "get", answers)
    tally = budgets.ScrapeTally(15.0)
    assert runner.scrape_sample(1, tally) == {"scrape_timeout_ms": 15002}
    assert runner.scrape_sample(1, tally)["rss"] == 5.0
    assert (tally.attempted, tally.timed_out_ms, tally.missing) == (2, [15002], [])


@pytest.mark.parametrize(
    ("retry", "text", "waited", "missing", "retried"),
    [("ok\n", "ok\n", [15000], [], ["t0"]), (TimeoutError(), None, [30002], ["t0"], [])],
    ids=["retry answers", "retry times out"],
)
def test_a_boundary_scrape_that_times_out_is_tried_once_more_and_still_counted(
    monkeypatch: pytest.MonkeyPatch, retry: object, text: str | None, waited: list[float],
    missing: list[str], retried: list[str],
) -> None:  # fmt: skip
    slept: list[float] = []
    ticks = iter([10.0, 25.0, 30.0, 45.002])  # a request: when it began, when it timed out
    clock = SimpleNamespace(monotonic=lambda: next(ticks), sleep=slept.append)
    monkeypatch.setattr(runner, "time", clock)
    monkeypatch.setattr(runner, "get", get_that(TimeoutError(), retry))
    tally = budgets.ScrapeTally(15.0)
    assert runner.scrape(1, tally, "t0") == text
    assert (tally.timed_out_ms, tally.missing, tally.retried) == (waited, missing, retried)
    assert (tally.attempted, slept) == (1, [runner.BOUNDARY_RETRY_S])


def test_a_scrape_request_waits_15_s_on_its_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, float] = {}

    def conn(host: str, port: int, timeout: float) -> None:
        seen["timeout"] = timeout
        raise TimeoutError  # the request goes nowhere

    monkeypatch.setattr("http.client.HTTPConnection", conn)
    with pytest.raises(TimeoutError):
        runner.get(4242, "/metrics")
    assert seen == {"timeout": 15.0}


def test_a_refused_connection_is_not_a_timeout_and_still_ends_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: 0.0))
    monkeypatch.setattr(runner, "get", get_that(ConnectionRefusedError()))
    with pytest.raises(ConnectionRefusedError):
        runner.scrape(1, budgets.ScrapeTally(15.0))


def fake_proc(poll: Callable[[], int | None]) -> SimpleNamespace:
    """A process stand-in for `execute`: `poll()` says when it has exited."""
    return SimpleNamespace(
        pid=os.getpid(), returncode=0, stdout=None, stderr=None, poll=poll,
        wait=lambda timeout=None: 0, terminate=lambda: None, kill=lambda: None,
    )  # fmt: skip


def execute_virtually(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answers: list[object], duration_s: float,
    k6_cores: float = 0.0, **plan_over: Any,
) -> Path:  # fmt: skip
    """`runner.execute` in virtual time, no sleeps, k6 and the backend stood in: each `/metrics`
    request takes the next of `answers` (an exception takes the 15 s it waits); k6 is gone once
    they are used up. It burns `k6_cores` of its one-core cpuset, on the virtual clock."""
    clock = [1_000.0]
    queue = iter(answers)
    asked: list[str] = []

    def advance(seconds: float) -> None:
        clock[0] += seconds
        assert clock[0] < 5_000.0, "the run never ended"  # a regression fails, it does not hang

    def get(port: int, path: str) -> str:
        asked.append(path)
        answer = next(queue)
        if isinstance(answer, BaseException):
            advance(runner.SCRAPE_TIMEOUT_S)
            raise answer
        return str(answer)

    k6 = fake_proc(lambda: None if len(asked) < len(answers) else 0)
    virtual = SimpleNamespace(time=lambda: clock[0], monotonic=lambda: clock[0], sleep=advance)
    popen = SimpleNamespace(Popen=lambda *a, **kw: k6, TimeoutExpired=subprocess.TimeoutExpired)
    monkeypatch.setattr(runner, "time", virtual)
    monkeypatch.setattr(runner, "subprocess", popen)
    monkeypatch.setattr(runner, "start_backend", lambda p: (fake_proc(lambda: 0), 1, os.getpid()))
    busy = itertools.count(0, 1000)  # the machine's busy seconds: 0 at t0, 1000 at t1
    for name, stand_in in (
        ("get", get), ("_commit", lambda: "c" * 40), ("_cgroup_count", lambda *a: 0),
        ("_busy_s", lambda text: float(next(busy))), ("BASELINES", tmp_path / "none"),
        ("_proc_cpu_s", lambda pid: k6_cores * (clock[0] - 1_000.0)),
    ):  # fmt: skip
        monkeypatch.setattr(runner, name, stand_in)
    a = args(duration_s=duration_s, warmup_s=0.0, k6_cpus="0", **plan_over)
    return runner.execute(runner.plan(TABLE, a, "A", tmp_path / "out"), "k6")


def test_a_proc_run_reports_the_feeders_cpu_apart_and_leaves_it_out_of_the_co_tenant_figure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#571: out of process the backend's `process_*` is the gateway's alone, and the child's CPU
    is read from its own counter, reported apart and not counted as a co-tenant's."""
    t0 = "process_cpu_seconds_total 0\ncv_bench_feeder_cpu_seconds_total 0\n"
    t1 = "process_cpu_seconds_total 31\ncv_bench_feeder_cpu_seconds_total 15.5\n"
    runs = {
        mode: json.loads(
            (execute_virtually(tmp_path / mode, monkeypatch, [t0, t1], 30.0, feeder=mode)
             / "run.json").read_text(encoding="utf-8")
        )
        for mode in ("inproc", "proc")
    }  # fmt: skip
    inproc, proc = runs["inproc"], runs["proc"]
    assert (proc["feeder"], proc["feeder_cpus"]) == ("proc", "0")  # k6's cpuset, not the backend's
    span = proc["steady_actual_s"]
    assert (
        proc["feeder_cpu_cores"] == pytest.approx(15.5 / span)
        and inproc["feeder_cpu_cores"] is None
    )
    other = inproc["variance"]["other_cores"] - proc["variance"]["other_cores"]
    assert other == pytest.approx(15.5 / span)  # in process the counter is not there to subtract
    res, facts = runner.judge(tmp_path / "proc" / "out")
    report = runner.render(res, facts, runner.compare(res, facts, 0.05))
    assert f"Feeder out of process (`--feeder proc`) on cpus 0: {15.5 / span:.2f} core(s)" in report
    res, facts = runner.judge(tmp_path / "inproc" / "out")
    assert "Feeder out of process" not in runner.render(
        res, facts, runner.compare(res, facts, 0.05)
    )


@pytest.mark.parametrize("boundary", ["t0", "t1"])
def test_a_lost_boundary_leaves_a_run_json_with_its_tally_and_no_co_tenant_figure_or_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    never, ok = TimeoutError("timed out"), "process_cpu_seconds_total 600\n"
    answers = [never, never, ok] if boundary == "t0" else [ok, never, never]
    out = execute_virtually(tmp_path, monkeypatch, answers, duration_s=30.0)
    facts = json.loads((out / "run.json").read_text(encoding="utf-8"))
    tally = {"timeout_s": 15.0, "attempted": 2, "timed_out_ms": [30000], "retried": []}
    assert facts["scrapes"] == tally | {"missing": [boundary]}
    assert facts["variance"]["other_cores"] is None  # left out, not 0.0
    assert facts["steady_actual_s"] is None  # no delta to span


@pytest.mark.parametrize("boundary", ["t0", "t1"])
def test_a_lost_boundary_reads_fail_and_the_report_says_what_it_left_unjudged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "none")
    run = make_run(tmp_path / "run", scrapes=TIMED_OUT_SCRAPE | {"missing": [boundary]})
    assert runner.finish(run, 0.10) == 1
    report = (run / "report.md").read_text(encoding="utf-8")
    assert "backend did not answer /metrics within 15 s, 1 of 12 scrapes" in report
    assert f"- budget6.cv_ws_fanout_seconds.p95: not judged ({boundary} scrape timed out)" in report
    result = json.loads((run / "result.json").read_text(encoding="utf-8"))["result"]
    assert (result["status"], result["invalid"]) == ("FAIL", [])


def periodic_timeout_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Four scrapes (t0, 60 s, 120 s, t1): the 120 s one timed out."""
    ok = "cv_ws_connections_in_use 6\n"
    answers = [ok, ok + "process_resident_memory_bytes 5000000\n", TimeoutError("timed out"), ok]
    return execute_virtually(tmp_path, monkeypatch, answers, duration_s=130.0)


def test_a_periodic_scrape_that_times_out_is_tallied_and_leaves_a_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = periodic_timeout_run(tmp_path, monkeypatch)
    tally = json.loads((out / "run.json").read_text(encoding="utf-8"))["scrapes"]
    assert (tally["attempted"], tally["timed_out_ms"], tally["missing"]) == (4, [15000], [])
    lines = (out / "series.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x).get("scrape_timeout_ms") for x in lines] == [None, 15000]


def test_a_run_with_a_periodic_timeout_reads_its_rss_from_the_scrape_that_answered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = periodic_timeout_run(tmp_path, monkeypatch)
    facts = json.loads((out / "run.json").read_text(encoding="utf-8"))
    first = json.loads((out / "series.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert (facts["rss_bytes"], first["rss"]) == (5_000_000, 5_000_000)


def test_a_retried_t0_is_read_at_the_instant_it_answered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retry answers 20 s late while k6 burns 0.82 cores: its share is not diluted by the wait,
    and run.json keeps the 11 s that t0 to t1 really spans in the 30 s window."""
    ok = "process_cpu_seconds_total 100\n"
    answers = [TimeoutError("timed out"), ok, ok]
    out = execute_virtually(tmp_path, monkeypatch, answers, duration_s=30.0, k6_cores=0.82)
    facts = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert facts["k6_cpu_frac"] == pytest.approx(0.82)
    assert (facts["steady_actual_s"], facts["scrapes"]["retried"]) == (pytest.approx(11.0), ["t0"])


def test_a_retried_t1_is_read_at_the_instant_it_answered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retry answers 20 s after the request, so t0 to t1 spans 51 s, not the 31 s up to it."""
    ok = "process_cpu_seconds_total 100\n"
    answers = [ok, TimeoutError("timed out"), ok]
    out = execute_virtually(tmp_path, monkeypatch, answers, duration_s=30.0)
    facts = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert (facts["steady_actual_s"], facts["scrapes"]["retried"]) == (pytest.approx(51.0), ["t1"])


def test_a_phase_keeps_its_own_length_unless_the_cli_gives_one(tmp_path: Path) -> None:
    phase = {"rtt_delay_ms": 700, "duration_s": 600, "warmup_s": 60, "families": ["book"]}
    own = runner.plan(TABLE, args(), "W5", tmp_path, **phase)
    assert (own.duration_s, own.prof["warmup_s"], own.prof["rtt_delay_ms"]) == (600.0, 60, 700)
    dry = runner.plan(TABLE, args(duration_s=30.0, warmup_s=10.0), "W5", tmp_path, **phase)
    assert (dry.duration_s, dry.prof["warmup_s"], dry.prof["rtt_delay_ms"]) == (30.0, 10.0, 700)
    assert (dry.nominal_duration_s, dry.nominal_warmup_s) == (
        600.0,
        60.0,
    )  # the phase's, not the dry run's


def w5_phase(p: runner.Plan) -> Path:
    """What `execute` leaves for one W5 phase: a run whose bytes and waits follow its class."""
    cls = w5.intended_class(int(p.prof["rtt_delay_ms"]))
    mult = {"healthy": 1, "lagging": 2, "saturated": 4}[cls]
    steady, warmup = p.duration_s, float(p.prof["warmup_s"])
    out = make_run(p.out, resolved=p.prof, steady_s=steady, warmup_s=warmup)
    summ = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    summ["counters"][f"cv_class_{cls}"] = 5
    for fam, nbytes in (("book", 100_000), ("trades", 60_000), ("bars", 40_000)):
        if fam in p.prof["families"]:
            summ["counters"][f"cv_frames_{fam}"] = 100
            summ["counters"][f"cv_bytes_{fam}"] = nbytes if fam == "trades" else nbytes // mult
    for name, ms in (("cv_tick_decode_ms_trades", 100), ("cv_hold_ms_book", 50)):
        summ["trends"][name] = {"count": 100, "p50": ms, "p95": ms * mult, "p99": ms * mult}
    summ["trends"]["cv_hold_ms_bars"] = {"count": 100, "p50": 250, "p95": 250 * mult, "p99": 250}
    (out / "summary.json").write_text(json.dumps(summ), encoding="utf-8")
    return out


def test_w5_gives_every_phase_the_cli_window_and_refuses_a_pong_delay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`runner w5 --duration-s 30 --warmup-s 10` is a dry run of the whole plan: every phase takes
    that window and warm-up (it used to ignore them), and the answer and w5.json still come out.
    A phase's class is its pong delay, so `--rtt-delay-ms` would make the plan measure nothing:
    it is refused."""
    ran: list[tuple[str, float, float]] = []

    def execute(p: runner.Plan, k6: str) -> Path:
        ran.append((p.out.name, p.duration_s, float(p.prof["warmup_s"])))
        return w5_phase(p)

    monkeypatch.setattr(runner, "execute", execute)
    monkeypatch.setattr(runner, "k6_binary", lambda: "k6")
    with pytest.raises(SystemExit, match="every phase sets its own pong delay"):
        runner.cmd_w5(args(out_dir=tmp_path, rtt_delay_ms=700.0))
    assert ran == []  # refused before anything ran
    code = runner.cmd_w5(args(out_dir=tmp_path / "dry", duration_s=30.0, warmup_s=10.0))
    names = [ph["name"] for ph in TABLE["w5"]["phases"]]
    assert [r[0] for r in ran] == names and {(r[1], r[2]) for r in ran} == {(30.0, 10.0)}
    answer = json.loads((tmp_path / "dry" / "w5.json").read_text(encoding="utf-8"))
    assert answer["recommendation"] == "per_family" and answer["skipped"] == []
    assert code == 0 and "W5: per_family" in capsys.readouterr().out


def saved_w5(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A whole W5 directory as a dry run of `runner w5` leaves it (`execute` stands in)."""
    monkeypatch.setattr(runner, "execute", lambda p, k6: w5_phase(p))
    monkeypatch.setattr(runner, "k6_binary", lambda: "k6")
    runner.cmd_w5(args(out_dir=root, duration_s=30.0, warmup_s=10.0))
    return root


def test_w5_judge_rereads_a_saved_directory_to_the_answer_w5_wrote_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def tree() -> dict[Path, bytes]:
        return {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    saved_w5(tmp_path, monkeypatch)
    saved = tree()
    capsys.readouterr()
    assert runner.cmd_w5_judge(argparse.Namespace(dir=str(tmp_path))) == 0
    assert capsys.readouterr().out == saved[tmp_path / "w5.json"].decode() and tree() == saved


@pytest.mark.parametrize("kind", ["symlink", "fifo", "oversized"])
def test_w5_judge_refuses_a_symlink_a_fifo_or_an_oversized_file_before_it_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    saved = saved_w5(tmp_path, monkeypatch)
    capsys.readouterr()
    bad = saved / "mixed-healthy" / "extra"
    if kind == "symlink":
        bad.symlink_to(saved / "w5.json")
    elif kind == "fifo":
        os.mkfifo(bad)  # neither a directory nor a regular file: a read would wait for a writer
    else:
        with bad.open("wb") as f:
            f.truncate((64 << 20) + 1)  # sparse: nothing is written
    with pytest.raises(SystemExit) as refused:
        runner.cmd_w5_judge(argparse.Namespace(dir=str(saved)))
    assert str(refused.value) == f"{bad}: a symlink or over 64 MiB: not read"
    assert capsys.readouterr().out == ""  # the clean phases around it were not judged either


def test_w5_judge_reads_a_file_of_exactly_64_mib(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with (saved_w5(tmp_path, monkeypatch) / "mixed-healthy" / "extra").open("wb") as f:
        f.truncate(64 << 20)  # sparse: the limit itself is read, one byte more is not
    capsys.readouterr()
    assert runner.cmd_w5_judge(argparse.Namespace(dir=str(tmp_path))) == 0


def test_w5_judge_refuses_a_symlinked_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    link = tmp_path / "link"
    link.symlink_to(saved_w5(tmp_path / "saved", monkeypatch), target_is_directory=True)
    with pytest.raises(SystemExit) as refused:
        runner.cmd_w5_judge(argparse.Namespace(dir=str(link)))
    assert str(refused.value) == f"{link}: a symlink or over 64 MiB: not read"


def test_w5_judge_of_a_missing_dir_gives_no_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert runner.cmd_w5_judge(argparse.Namespace(dir=str(tmp_path / "absent"))) == 1
    assert json.loads(capsys.readouterr().out)["recommendation"] == "no_data"


def test_w5_judge_names_a_mixed_phase_its_directory_lacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.rmtree(saved_w5(tmp_path, monkeypatch) / "mixed-lagging")
    capsys.readouterr()
    assert runner.cmd_w5_judge(argparse.Namespace(dir=str(tmp_path))) == 1
    answer = json.loads(capsys.readouterr().out)
    assert answer["skipped"] == ["mixed-lagging"]
    assert any("mixed-lagging is not in the plan" in n for n in answer["notes"])


LOST_T1, LATE_T0 = {"missing": ["t1"]}, {"timed_out_ms": [15000, 15000], "retried": ["t0"]}
OUT, KEPT = "a boundary scrape timed out, left out", "scrapes timed out"
ONE_TIMEOUT = {"timed_out_ms": [15000]}


@pytest.mark.parametrize(
    ("phase", "late", "skipped", "note", "code"),
    [
        ("mixed-lagging", LOST_T1, ["mixed-lagging"], f"phase mixed-lagging: {OUT}", 1),
        ("idle", LOST_T1, [], f"phase idle: {OUT}", 1),
        ("book-healthy", LATE_T0, [], f"phase book-healthy: 2 of 7 {KEPT} (t0 retried), kept", 0),
        ("idle", ONE_TIMEOUT, [], f"phase idle: 1 of 7 {KEPT}, kept", 0),
        ("mixed-lagging", ONE_TIMEOUT, [], f"phase mixed-lagging: 1 of 7 {KEPT}, kept", 0),
    ],
)
def test_a_w5_phase_that_had_a_scrape_time_out_is_left_out_if_a_boundary_was_lost_else_kept(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    phase: str,
    late: dict[str, Any],
    skipped: list[str],
    note: str,
    code: int,
) -> None:
    def execute(p: runner.Plan, k6: str) -> Path:
        out = w5_phase(p)
        if p.out.name == phase:
            facts = json.loads((out / "run.json").read_text(encoding="utf-8"))
            tally = {"timeout_s": 15.0, "attempted": 7, "timed_out_ms": [], "missing": []} | late
            (out / "run.json").write_text(json.dumps(facts | {"scrapes": tally}), encoding="utf-8")
        return out

    monkeypatch.setattr(runner, "execute", execute)
    monkeypatch.setattr(runner, "k6_binary", lambda: "k6")
    assert runner.cmd_w5(args(out_dir=tmp_path, duration_s=30.0, warmup_s=10.0)) == code
    answer = json.loads((tmp_path / "w5.json").read_text(encoding="utf-8"))
    assert answer["skipped"] == skipped and note in answer["notes"]
    assert f"  {note}" in capsys.readouterr().out
    assert not any("not in the plan" in n for n in answer["notes"])  # noted once
    again = runner.cmd_w5_judge(argparse.Namespace(dir=str(tmp_path)))  # the saved directory
    rejudged = json.loads(capsys.readouterr().out)
    assert (again, rejudged["skipped"]) == (code, skipped)
    assert (note in rejudged["notes"]) is (code == 1)  # a kept note is not repeated


def feeder_skips(out: Path) -> None:  # the 15 s gap made the feeder skip 5 of its 100 slots
    text = (out / "scrape1.txt").read_text(encoding="utf-8")
    skipped = text.replace('published_total{kind="book"} 100', 'published_total{kind="book"} 95')
    (out / "scrape1.txt").write_text(skipped, encoding="utf-8")


def server_closes(out: Path) -> None:  # and the server closed two of k6's sockets
    summ = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    summ["counters"]["cv_unplanned_closes"] = 2
    (out / "summary.json").write_text(json.dumps(summ), encoding="utf-8")


@pytest.mark.parametrize("guard", [feeder_skips, server_closes])
def test_a_w5_mixed_phase_with_a_scrape_timeout_and_a_guard_is_left_out_and_noted_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    guard: Callable[[Path], None],
) -> None:
    def execute(p: runner.Plan, k6: str) -> Path:
        out = w5_phase(p)
        if p.out.name == "mixed-saturated":
            facts = json.loads((out / "run.json").read_text(encoding="utf-8"))
            tally = facts | {"scrapes": TIMED_OUT_SCRAPE}
            (out / "run.json").write_text(json.dumps(tally), encoding="utf-8")
            guard(out)
        return out

    monkeypatch.setattr(runner, "execute", execute)
    monkeypatch.setattr(runner, "k6_binary", lambda: "k6")
    assert runner.cmd_w5(args(out_dir=tmp_path, duration_s=30.0, warmup_s=10.0)) == 1
    answer = json.loads((tmp_path / "w5.json").read_text(encoding="utf-8"))
    assert (answer["skipped"], answer["recommendation"]) == (["mixed-saturated"], "no_data")
    said = [n for n in answer["notes"] if "mixed-saturated" in n]
    assert said == ["phase mixed-saturated is INVALID and is left out"]  # not "kept" as well
    assert capsys.readouterr().out.count("mixed-saturated") == 1
    assert runner.cmd_w5_judge(argparse.Namespace(dir=str(tmp_path))) == 1
    assert json.loads(capsys.readouterr().out) == answer  # the saved directory says the same


def test_w5_divides_a_phases_cpu_by_the_seconds_its_deltas_span_when_it_recorded_them() -> None:
    d = budgets.parse_scrape("process_cpu_seconds_total 30")
    idle = w5.Phase("idle", (), 0, {}, d, 100.0, "PASS")  # 0.3 cores over its 100 s
    book = w5.Phase("book-healthy", ("book",), 0, {}, d, 100.0, "PASS", delta_s=50.0)
    cpu = w5.analyze([idle, book])["cpu_s_per_s"]
    assert cpu == {"idle": pytest.approx(0.3), "book/healthy": pytest.approx(0.3)}  # 0.6 - 0.3


def test_a_baseline_taken_on_another_event_loop_is_not_compared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixture runs on the stdlib loop and production's uvicorn picks uvloop: loop-sensitive
    numbers (fan-out, loop lag, CPU) of one are not a baseline for the other."""
    runs = baseline_15_percent_better(tmp_path, monkeypatch)
    res, facts = runner.judge(runs[0])
    assert runner.compare(res, facts, 0.05, 3).failures  # the same loop: the 15 % regression gates
    path = tmp_path / "base" / "A.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(data | {"loop": "uvloop"}))
    g = runner.compare(res, facts, 0.05, 3)
    assert not g.gated and g.failures == [] and "uvloop" in g.reason and "asyncio" in g.reason
    del data["loop"]  # a baseline that records no loop is not taken to be this loop's
    path.write_text(json.dumps(data))
    g = runner.compare(res, facts, 0.05, 3)
    assert not g.gated and g.failures == [] and "not recorded" in g.reason
    g = runner.compare(res, {k: v for k, v in facts.items() if k != "loop"}, 0.05, 3)
    assert not g.gated and g.failures == [] and "not recorded" in g.reason  # nor is either side


def without_loop(out: Path) -> Path:
    """`out`'s run as an artefact from before the loop was recorded."""
    facts = json.loads((out / "run.json").read_text(encoding="utf-8"))
    del facts["loop"]
    (out / "run.json").write_text(json.dumps(facts), encoding="utf-8")
    return out


def test_a_baseline_of_the_other_feeder_mode_is_not_compared_and_one_records_its_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#571: in process the feeder's CPU and loop time are in the backend's numbers, out of it they
    are not, so a baseline gates runs of its own mode only; one from before the mode was recorded
    is `inproc`, the only mode there was."""
    runs = baseline_15_percent_better(tmp_path, monkeypatch)
    res, facts = runner.judge(runs[0])
    assert "feeder" not in facts and runner.compare(res, facts, 0.05, 3).failures  # both legacy
    g = runner.compare(res, facts | {"feeder": "proc"}, 0.05, 3)
    assert not g.gated and g.failures == [] and g.reason == "no baseline recorded"  # no `A-proc`
    base = tmp_path / "base"
    legacy = (base / "A.json").read_text(encoding="utf-8")
    (base / "A-proc.json").write_text(legacy, encoding="utf-8")  # a misfiled one: mode inproc
    g = runner.compare(res, facts | {"feeder": "proc"}, 0.05, 3)
    assert not g.gated and "baseline feeder inproc, this run's proc" in g.reason
    (base / "A-proc.json").write_text(
        json.dumps(json.loads(legacy) | {"feeder": "proc"}), encoding="utf-8"
    )
    assert runner.compare(res, facts | {"feeder": "inproc"}, 0.05, 3).failures  # A.json, as before
    assert runner.compare(res, facts | {"feeder": "proc"}, 0.05, 3).failures  # its own mode gates
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "rec")
    written = runner.record_baseline(res, facts | {"feeder": "proc"})
    assert json.loads(written.read_text(encoding="utf-8"))["feeder"] == "proc"


def test_a_proc_baseline_has_its_own_file_and_leaves_the_inproc_one_where_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert runner.baseline_name({"profile": "A", "flag": "on"}) == "A"
    assert runner.baseline_name({"profile": "A", "flag": "on", "feeder": "inproc"}) == "A"
    assert runner.baseline_name({"profile": "A", "flag": "off", "feeder": "inproc"}) == "A-flag-off"
    assert runner.baseline_name({"profile": "A", "flag": "on", "feeder": "proc"}) == "A-proc"
    off = {"profile": "A", "flag": "off", "feeder": "proc"}
    assert runner.baseline_name(off) == "A-flag-off-proc"
    runs = baseline_15_percent_better(tmp_path, monkeypatch)
    res, facts = runner.judge(runs[0])
    monkeypatch.delenv("CI", raising=False)
    base = tmp_path / "coexist"
    monkeypatch.setattr(runner, "BASELINES", base)
    first = runner.record_baseline(res, facts)
    second = runner.record_baseline(res, facts | {"feeder": "proc"})
    assert (first.name, second.name) == ("A.json", "A-proc.json")
    assert json.loads(first.read_text(encoding="utf-8"))["feeder"] == "inproc"
    assert json.loads(second.read_text(encoding="utf-8"))["feeder"] == "proc"


def test_runs_that_record_no_loop_are_not_compared_with_ones_that_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "none")
    dirs = [make_run(tmp_path / f"run{i}") for i in range(3)]
    without_loop(dirs[1])
    assert runner.cmd_gate(argparse.Namespace(dirs=[str(d) for d in dirs], tolerance=0.05)) == 2
    assert "differ in loop: asyncio, not recorded" in capsys.readouterr().out
    for d in (dirs[0], dirs[2]):  # nor with each other: three runs without one share no loop
        without_loop(d)
    assert runner.cmd_gate(argparse.Namespace(dirs=[str(d) for d in dirs], tolerance=0.05)) == 2
    assert "run0 does not record its event loop" in capsys.readouterr().out


def test_a_run_that_records_no_loop_is_refused_as_a_baseline_never_a_key_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "base")
    monkeypatch.delenv("CI", raising=False)
    old = without_loop(make_run(tmp_path / "old"))  # full length and PASS: only the loop is missing
    assert runner.main(["record", str(old)]) == 1  # the command's refusal, not a traceback
    assert runner.finish(old, runner.TOLERANCE, record=True) == 0  # judged, and not recorded
    out = capsys.readouterr().out
    assert out.count("not recorded: the run does not record its event loop") == 2
    assert not (tmp_path / "base").exists()


def test_a_w5_dispatch_with_no_answer_says_so_and_exits_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "k6_binary", lambda: "k6")
    monkeypatch.setattr(  # every phase ends INVALID (k6 exited 107): no mixed phase can be read
        runner, "execute", lambda p, k6: make_run(p.out, resolved=p.prof, k6_exit=107)
    )
    code = runner.cmd_w5(args(out_dir=tmp_path / "w5"))
    out = capsys.readouterr().out
    assert code == 1 and "W5: no usable answer" in out and "every rule met" not in out
    assert "phase mixed-healthy is INVALID" in out  # the notes still say why


# -- review round 1: the run label, the gate's inputs, the path, the guard, the logs ---------------


def args(**over: Any) -> argparse.Namespace:
    """The parsed CLI arguments `runner.plan` reads, as `runner.main` builds them."""
    names = ("duration_s", "warmup_s", "rtt_delay_ms", "reauth_after_s", "probe_every_s")
    base: dict[str, Any] = dict.fromkeys((*names, "send_delay_ms", "gate_on", "ws_path"))
    base |= {"flag": "on", "staging": False, "seed": 7, "trace_sp": False}
    base |= {"backend_cpus": None, "k6_cpus": None, "feeder": "inproc", "feeder_cpus": None}
    return argparse.Namespace(**(base | over))


#: `resolved` as `execute` writes it for `--duration-s 120 --warmup-s 20`: the overridden values.
SHORT = profiles.resolve(TABLE, "A") | {"name": "A", "duration_s": 120.0, "warmup_s": 20.0}


def short_run(tmp_path: Path) -> Path:
    return make_run(tmp_path / "short", steady_s=120.0, warmup_s=20.0, resolved=SHORT)


def test_a_shortened_run_is_smoke_and_the_gate_never_holds_it_to_the_full_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    full = baseline_15_percent_better(tmp_path, monkeypatch)  # every full run is 15 % worse
    res, facts = runner.judge(short_run(tmp_path))
    assert runner.run_profile(facts) == "smoke"
    assert runner.run_profile(runner.judge(full[0])[1]) == "full"
    assert runner.run_profile(facts | {"steady_s": 3600.0}) == "smoke"  # a short warm-up counts too
    assert runner.run_profile({"steady_s": 3600.0, "warmup_s": 300.0}) == "smoke"  # length unknown
    g = runner.compare(res, facts, 0.05, 3)
    assert not g.gated and g.failures == [] and "'full'" in g.reason


def test_a_shortened_run_is_never_recorded_as_the_full_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "base")
    monkeypatch.delenv("CI", raising=False)
    short = short_run(tmp_path)
    assert runner.cmd_record(argparse.Namespace(dir=str(short))) == 1
    assert runner.finish(short, runner.TOLERANCE, record=True) == 0  # judged, and not recorded
    assert capsys.readouterr().out.count("not recorded: the run is shortened") == 2
    assert not (tmp_path / "base").exists()
    assert runner.cmd_record(argparse.Namespace(dir=str(make_run(tmp_path / "full")))) == 0
    legacy = make_run(tmp_path / "legacy", flag="off")  # from before the length was recorded
    facts = json.loads((legacy / "run.json").read_text(encoding="utf-8"))
    del facts["profile_duration_s"], facts["profile_warmup_s"]
    (legacy / "run.json").write_text(json.dumps(facts), encoding="utf-8")
    capsys.readouterr()
    assert runner.cmd_record(argparse.Namespace(dir=str(legacy))) == 1  # no KeyError, no baseline
    assert "does not record how long its profile is" in capsys.readouterr().out
    assert not (tmp_path / "base" / "A-flag-off.json").exists()


@pytest.mark.parametrize(
    ("over", "code", "needle"),
    [
        ([{}, {"k6_exit": 107}, {}], 2, "run1 is INVALID"),
        ([{}, {"k6_exit": 107, "bandwidth": 1126.4}, {}], 2, "(k6_exit: 107; missed: s16_3.band"),
        (
            [{}, {"k6_exit": 107, "scrapes": TIMED_OUT_SCRAPE}, {}],
            2,
            "is FAIL (k6_exit: 107; missed: scrape",
        ),
        ([{}, {"flag": "off"}, {}], 2, "differ in flag"),
        ([{}, {"loop": "uvloop"}, {}], 2, "differ in loop: asyncio, uvloop"),
        # #571: one proc run among legacy ones (no `feeder`: inproc, the only mode there was)
        ([{}, {"feeder": "proc"}, {}], 2, "differ in feeder: inproc, proc"),
        ([{"feeder": "inproc"}, {}, {"feeder": "proc"}], 2, "differ in feeder: inproc, proc"),
        ([{}, {}, {"steady_s": 600.0}], 2, "differ in steady_s"),
        ([{}, {}], 2, "the gate needs 3"),
        ([{}, {"bandwidth": 1126.4}, {}], 1, "run1 missed a budget: s16_3.bandwidth"),
    ],
)
def test_the_gate_names_why_it_refuses_runs_it_cannot_compare_or_that_missed(
    over: list[dict[str, Any]],
    code: int,
    needle: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "none")
    dirs = [str(make_run(tmp_path / f"run{i}", **o)) for i, o in enumerate(over)]
    assert runner.cmd_gate(argparse.Namespace(dirs=dirs, tolerance=0.05)) == code
    assert needle in capsys.readouterr().out


def test_repro_names_the_headlines_it_could_not_compare_when_a_run_lost_a_boundary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lost_t1 = TIMED_OUT_SCRAPE | {"missing": ["t1"]}
    a, b = make_run(tmp_path / "a"), make_run(tmp_path / "b", scrapes=lost_t1)
    assert runner.cmd_repro(argparse.Namespace(dir_a=str(a), dir_b=str(b), variance_source=[])) == 0
    out = capsys.readouterr().out
    assert "not compared (no reading in one run): fanout_ms, backend_cpu_s_per_s" in out
    assert "reproducibility OK: every compared headline within 15%" in out


def test_repro_does_not_list_a_headline_both_runs_lack_by_design_as_not_compared(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    c = profiles.resolve(TABLE, "C") | {"name": "C"}  # no probe: no re-snapshot in either run
    a, b = (make_run(tmp_path / x, resolved=c, profile="C") for x in "ab")
    assert runner.cmd_repro(argparse.Namespace(dir_a=str(a), dir_b=str(b), variance_source=[])) == 0
    assert capsys.readouterr().out == "reproducibility OK: every headline within 15%\n"


def test_repro_refuses_an_invalid_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a, b = make_run(tmp_path / "a"), make_run(tmp_path / "b", k6_exit=107)
    assert runner.cmd_repro(argparse.Namespace(dir_a=str(a), dir_b=str(b), variance_source=[])) == 2
    assert "refused" in capsys.readouterr().out


def test_co_tenant_load_is_the_machine_busy_outside_the_run_not_the_load_average(
    tmp_path: Path,
) -> None:
    hz = os.sysconf("SC_CLK_TCK")
    stat = "cpu  100 5 50 800 20 4 6 1 99 0\ncpu0  1 1 1 1 1 1 1 1 1 1\n"
    assert runner._busy_s(stat) == pytest.approx((100 + 5 + 50 + 4 + 6 + 1) / hz)  # no idle, iowait
    assert runner._other_cores(30.0, 10.0, [1.5, 0.5]) == pytest.approx(1.0)  # 3 busy, 2 are ours
    assert runner._other_cores(10.0, 10.0, [1.5, 0.5]) == 0.0
    quiet, noisy = (
        make_run(tmp_path / "q"),
        make_run(tmp_path / "n", variance={"nr_throttled": 0, "other_cores": 2.5}),
    )
    facts = [runner.judge(d)[1] for d in (quiet, noisy)]
    assert runner.variance_sources(facts[0], facts[0]) == []
    assert any("co-tenant" in x for x in runner.variance_sources(facts[0], facts[1]))


def test_a_run_that_could_not_read_the_co_tenant_load_names_no_co_tenant(tmp_path: Path) -> None:
    unread = {"nr_throttled": 0, "other_cores": None}  # a lost boundary: nothing to subtract from
    facts = runner.judge(make_run(tmp_path / "run", variance=unread))[1]
    assert runner.variance_sources(facts, facts) == []


def test_k6_runs_with_no_usage_report_and_no_extension_resolution() -> None:
    env = runner._env()  # the name the pinned v2.3.0 binary reads: with it unset k6 may fetch code
    assert (env["K6_NO_USAGE_REPORT"], env["K6_AUTO_EXTENSION_RESOLUTION"]) == ("true", "false")


def test_a_run_directory_is_cleared_of_what_an_earlier_run_left(tmp_path: Path) -> None:
    runner._fresh(tmp_path)  # the first run takes an empty directory and marks it its own
    assert [x.name for x in tmp_path.iterdir()] == [runner.MARKER]
    for name in (*runner.STALE, "tokens.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "bars").mkdir()  # the bar builders restore this at start
    (tmp_path / "bars" / "BTCUSDT.state").write_text("{}", encoding="utf-8")
    runner._fresh(tmp_path)
    left = sorted(x.name for x in tmp_path.iterdir())
    assert left == sorted(["tokens.json", runner.MARKER])  # the backend writes its own tokens


def test_a_cleared_link_goes_and_what_it_points_at_stays(tmp_path: Path) -> None:
    out, elsewhere = tmp_path / "run", tmp_path / "elsewhere"
    runner._fresh(out)
    elsewhere.mkdir()
    (elsewhere / "BTCUSDT.state").write_text("{}", encoding="utf-8")
    (out / "bars").symlink_to(elsewhere, target_is_directory=True)
    runner._fresh(out)  # a `bars` link left in place would hand its target to the next backend
    assert not os.path.lexists(out / "bars") and (elsewhere / "BTCUSDT.state").exists()


@pytest.mark.parametrize("name", [*runner.STALE, "bars"])
def test_the_clear_removes_a_bars_directory_and_no_other_directory(
    tmp_path: Path, name: str
) -> None:
    """`bars/` is the one directory a run's backend writes. A directory named like one of the
    seven run files is not the harness's: the clear fails on it, as unlinking a directory does,
    and what it holds stays."""
    runner._fresh(tmp_path)  # an empty directory, taken and marked
    held = tmp_path / name
    held.mkdir()
    (held / "kept.txt").write_text("kept\n", encoding="utf-8")
    if name == "bars":
        runner._fresh(tmp_path)
        assert not held.exists()
    else:
        with pytest.raises(OSError):
            runner._fresh(tmp_path)
        assert (held / "kept.txt").read_text(encoding="utf-8") == "kept\n"


@pytest.mark.parametrize("name", [*runner.STALE, "bars", "notes.txt"])
def test_a_directory_the_harness_did_not_make_is_never_cleared(tmp_path: Path, name: str) -> None:
    """`--out-dir candleviewer` would otherwise delete a source tree's `bars/`, and an operator's
    folder its `report.md`: a directory without an earlier run's marker that holds anything, one
    entry is enough, is refused, says why, deletes nothing and is not marked."""
    foreign = tmp_path / "candleviewer"
    foreign.mkdir()
    entry = foreign / name
    if name == "bars":
        entry.mkdir()
        (entry / "series.py").write_text("SERIES = 1\n", encoding="utf-8")
    else:
        entry.write_text("not ours\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="not made by this harness") as refused:
        runner._fresh(foreign)
    assert name in str(refused.value) and "nothing was deleted" in str(refused.value)
    assert [x.name for x in foreign.iterdir()] == [name]  # as it was, and no marker
    if name == "bars":  # what it held is as it was
        assert (entry / "series.py").read_text(encoding="utf-8") == "SERIES = 1\n"
    (foreign / runner.MARKER).write_text("e17-q03/1\n", encoding="utf-8")  # the operator's say-so
    runner._fresh(foreign)
    assert entry.exists() is (name == "notes.txt")  # then only the harness's own names go


@pytest.mark.parametrize("name", ["report.md", runner.MARKER])
def test_a_symlink_makes_a_directory_foreign_and_is_left_as_it_is(
    tmp_path: Path, name: str
) -> None:
    """Neither the check nor the clear follows a link: a dangling one named like an artefact is
    held, not missing, and a link named like the marker is not the marker a run wrote."""
    target, foreign = tmp_path / "operator.txt", tmp_path / "foreign"
    if name == runner.MARKER:
        target.write_text("kept\n", encoding="utf-8")  # a run would write its marker into it
    foreign.mkdir()
    (foreign / name).symlink_to(target)
    with pytest.raises(SystemExit, match="not made by this harness"):
        runner._fresh(foreign)
    assert (foreign / name).is_symlink() and [x.name for x in foreign.iterdir()] == [name]
    if name == runner.MARKER:
        assert target.read_text(encoding="utf-8") == "kept\n"  # never written through the link


def test_a_backend_that_never_gets_ready_is_stopped_before_the_runner_gives_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pidfile, fake = tmp_path / "pid", tmp_path / "python"
    fake.write_text(f"#!/bin/sh\necho $$ > {pidfile}\nexec sleep 60\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(fake))
    monkeypatch.setattr(runner, "START_TIMEOUT_S", 2.0)  # long enough for the shell to start
    with pytest.raises(SystemExit, match="did not become ready"):
        runner.start_backend(runner.plan(TABLE, args(), "smoke", tmp_path / "out"))
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text(encoding="utf-8")), 0)  # the one pid we started: gone


def test_the_ws_path_defaults_to_the_gateways_and_one_option_moves_it_everywhere(
    tmp_path: Path,
) -> None:
    assert profiles.GATEWAY_PATH == WS_PATH == TABLE["defaults"]["ws_path"] == "/ws"
    plans = [
        runner.plan(TABLE, args(**o), "smoke", tmp_path) for o in ({}, {"ws_path": "/api/v1/ws"})
    ]
    assert [runner.k6_env(p, 7, 1.0, 2.0)["WS_PATH"] for p in plans] == ["/ws", "/api/v1/ws"]
    paths = [p.prof["ws_path"] for p in plans]
    cfgs = [
        fixture_app.BackendConfig.for_profile(TABLE, "A", flag=True, seed=1, ws_path=x)
        for x in paths
    ]
    assert [c.ws_path for c in cfgs] == ["/ws", "/api/v1/ws"]
    with pytest.raises(ValueError, match="expected /ws"):
        runner.plan(TABLE, args(ws_path="/x"), "smoke", tmp_path)


@contextlib.asynccontextmanager
async def session(be: fixture_app.Backend, path: str = "/ws") -> AsyncIterator[Any]:
    """A client of the backend at `path`, through hello and auth."""
    url = f"ws://127.0.0.1:{be.port}{path}"
    proto, origin = cast(Any, ["cv.v1.json"]), cast(Any, TABLE["origin"])
    async with websockets.connect(url, subprotocols=proto, origin=origin) as ws:
        hello = {"client": "t", "client_version": "1", "protocol": "cv.v1"}
        await ws.send(json.dumps({"t": "hello", "id": "c-1", "p": hello}))
        assert (await recv(ws))["t"] == "welcome"
        token = {"access_token": be.tokens["u0"][0]["access"]}
        await ws.send(json.dumps({"t": "auth", "id": "c-2", "p": token}))
        assert (await recv(ws))["t"] == "auth_ok"
        yield ws


@pytest.mark.parametrize("ws_path", ["/ws", "/api/v1/ws", "/bench/ws"])
async def test_the_fixture_serves_both_gateway_paths_as_the_app_does(
    ws_path: str, tmp_path: Path
) -> None:
    """#3916: `create_app` serves the gateway at `/ws` and `/api/v1/ws` (`include_ws_router`), and
    so does the fixture, whichever path k6 is given; another prefix is served as well."""
    cfg = fixture_app.BackendConfig(
        symbols=("BTCUSDT",), hot=1, warm=0, users=1, connections=1, flag=False, ws_path=ws_path
    )
    async with fixture_app.Backend(cfg, TABLE, tmp_path) as be:
        for path in dict.fromkeys(("/ws", "/api/v1/ws", ws_path)):
            async with session(be, path):
                pass
        with pytest.raises(websockets.exceptions.InvalidStatus):
            async with session(be, "/other/ws"):
                pass


async def test_a_window_holds_an_update_that_the_envelope_stamp_cannot_see(tmp_path: Path) -> None:
    """The premise of W5's instrument, through the real gateway: an update published into a window
    is stamped by `ts` when the window RELEASES it, a window after its source, while the CVWB header
    keeps the source. Decode minus `ts` cannot price the wait; decode minus the source does."""
    cfg = fixture_app.BackendConfig(
        symbols=("BTCUSDT",), hot=1, warm=0, users=1, connections=1, flag=True
    )
    async with fixture_app.Backend(cfg, TABLE, tmp_path) as be:
        be._tasks[1].cancel()  # no feeder: the two updates below are all there is
        await asyncio.gather(be._tasks[1], return_exceptions=True)
        async with session(be) as ws:
            sub = {"topics": [{"ch": "trades.BTCUSDT"}]}
            await ws.send(json.dumps({"t": "sub", "id": "c-3", "p": sub}))
            window_ms = 0.0
            while (m := await recv(ws))["t"] != "snap":
                if m["t"] == "sub_ok":
                    window_ms = m["p"]["results"][0]["effective"]["throttle_ms"]
            source = time.time_ns() // 1_000_000
            for i in range(2):  # no await between: the second falls in the window the first opened
                part = Frame(TRADES, ((0, 631200, 1000, 0, 0),), 0, 1, 3, source)
                item = {"id": f"x{i}", "ts_ms": source, "price": "63120.0", "size": "1.000"}
                body = {"symbol": "BTCUSDT", "trades": [item | {"side": "buy"}]}
                be.hub.publish("trades.BTCUSDT", body, part=part)
            frames: list[dict[str, Any]] = []
            while len(frames) < 2:
                m = await recv(ws)
                if m["t"] == "ping":
                    await ws.send(json.dumps({"t": "pong", "id": m["id"], "p": {"client_ms": 1}}))
                frames += [m] if m["t"] == "d" else []
    held = frames[1]
    assert window_ms == 100.0 and decode_b64(held["p"]).ts_base_ms == source
    assert held["ts"] - source >= 0.9 * window_ms  # released a window after its source


def test_the_js_ws_url_helper_takes_the_paths_the_python_twin_takes() -> None:
    cases = ["/ws", "/api/v1/ws", "/x", "//ws", "/a/../ws", "/ws?x=1", "/ws/", "ws", ""]
    cases += ["/.h/ws", "/a b/ws", "/a/./ws", "/ws/ws"]
    script = f"""
    import {{ wsUrl }} from '{LOAD}/lib/profile.js';
    const out = {{}};
    for (const c of {json.dumps(cases)}) {{
      try {{ out[c] = wsUrl(7, c); }} catch {{ out[c] = null; }}
    }}
    console.log(JSON.stringify(out));
    """
    done = node("--input-type=module", "-e", script)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    for case in cases:
        try:
            want: str | None = f"ws://127.0.0.1:7{profiles.ws_path(case)}"
        except ValueError:
            want = None
        assert got[case] == want, case
    assert "ws://127.0.0.1:7/api/v1/ws" in got.values() and None in got.values()


def test_the_k6_client_sends_only_resync_reasons_the_protocol_names() -> None:
    source = (LOAD / "lib" / "client.js").read_text(encoding="utf-8")
    sent = set(re.findall(r'voidStream\([^)]*?,\s*"([a-z_]+)"\)', source))
    assert sent == {"sequence_gap", "decode_error"} and sent <= CLIENT_RESYNC_REASONS


def test_the_egress_guard_covers_every_lookup_and_connect_the_ci_guard_wraps() -> None:
    assert set(fixture_app._LOOKUPS) == set(ci_guard._LOOKUPS)
    assert set(fixture_app._CONNECTS) == set(ci_guard._CONNECTS)
    before = {n: getattr(socket, n) for n in fixture_app._LOOKUPS}
    lookups = {
        "getaddrinfo": ("exchange.example", 443),
        "gethostbyname": ("exchange.example",),
        "gethostbyname_ex": ("exchange.example",),
        "gethostbyaddr": ("192.0.2.7",),
        "getnameinfo": (("192.0.2.7", 443), 0),
    }
    with fixture_app.egress_guard():
        for call, call_args in lookups.items():
            with pytest.raises(RuntimeError, match="not loopback"):
                getattr(socket, call)(*call_args)
        with socket.socket() as s:
            for name in fixture_app._CONNECTS:
                with pytest.raises(RuntimeError, match="not loopback"):
                    getattr(s, name)(("192.0.2.7", 443))
        assert socket.gethostbyname("127.0.0.1") == "127.0.0.1"  # loopback goes through
        socket.getaddrinfo(None, 80)  # a passive lookup names no host
    assert all(getattr(socket, n) is before[n] for n in before)  # and the guard leaves no trace


def test_the_backend_runs_on_the_stdlib_loop_and_logs_through_the_redacting_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, str] = {}
    shape = "aaaaaaaaaa.bbbbbbbbbb.cccccccccc"  # a JWT's shape: the filter redacts it by shape

    async def serve(_: argparse.Namespace) -> None:  # the process setup is under test
        seen["loop"] = type(asyncio.get_running_loop()).__module__
        structlog.get_logger("bench").warning("probe", note="kept", blob=shape)
        logging.getLogger("bench.std").warning("probe %s kept2", shape)

    monkeypatch.setattr(fixture_app, "serve", serve)
    monkeypatch.setenv("CV_LOG_LEVEL", "warning")
    try:
        assert fixture_app.main(["--profile", "A", "--out", str(tmp_path)]) == 0
    finally:
        reset_logging()  # also drains the listener thread, so the lines are out before the read
    out, err = capfd.readouterr()
    assert not seen["loop"].startswith("uvloop")  # uvloop resolves names where no guard sees them
    assert out == ""  # stdout is the ready line's alone
    assert "kept" in err and "kept2" in err and "[redacted:jwt-shape]" in err
    assert shape not in err  # redacted, as every project logger is (C-12.6)


async def test_a_feeder_task_that_ends_with_an_error_is_logged_as_it_ends() -> None:
    """#4852 (a Fable carry): a feed that dies mid-run, such as a receiver whose child closed its
    pipe, is named in the log when it dies, not only by the `feeder_behind` guard at the end. A
    cancelled feeder (the shutdown) logs nothing."""

    async def gone() -> None:
        raise RuntimeError("the feeder process closed its pipe")

    async def idle() -> None:
        await asyncio.Event().wait()

    failed = asyncio.create_task(gone(), name="bench-ws-feeder")
    await asyncio.wait({failed})
    cancelled = asyncio.create_task(idle(), name="bench-ws-feeder")
    cancelled.cancel()
    await asyncio.wait({cancelled})
    with capture_logs() as logs:
        fixture_app.feeder_ended(failed)
        fixture_app.feeder_ended(cancelled)
    assert [(e["event"], e["log_level"], e["error"]) for e in logs] == [
        ("bench_feeder_ended", "error", "RuntimeError")
    ]
