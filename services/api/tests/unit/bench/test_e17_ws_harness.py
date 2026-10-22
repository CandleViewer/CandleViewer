"""E17-Q03 (#568): the harness itself, offline and on loopback: the profile table against the caps
the gateway enforces, the feeder (rates, determinism, a client that stays consistent), the CVWB
port and the profile helper against their Python twins, the egress guard, the bench send delay,
and the real fixture backend with a tiny protocol client. No k6 here (the smokes need it).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
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

import pytest
import structlog
import websockets

from bench.ws import budgets, fixture_app, profiles, runner, w5
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


async def test_the_feeder_is_deterministic_per_seed() -> None:
    a, b, c = Recorder(), Recorder(), Recorder()
    for rec, seed in ((a, 7), (b, 7), (c, 8)):
        await drive(make_feeder(seed, rec), 300)
    assert a.calls == b.calls and a.calls
    assert a.calls != c.calls  # another seed: other offsets, other phases


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


@pytest.mark.parametrize("flag", [True, False])
async def test_the_backend_serves_the_real_gateway_and_a_client_ends_consistent(
    flag: bool, tmp_path: Path
) -> None:
    cfg = fixture_app.BackendConfig(
        symbols=("BTCUSDT", "ETHUSDT"), hot=1, warm=1, users=1, connections=1, flag=flag
    )
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
STALL = {"timeout_s": 15.0, "attempted": 12, "timed_out_ms": [15003], "missing": []}


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
    run = make_run(tmp_path / "run", k6_exit=107, scrapes=STALL)  # k6 exit 107 trips a guard
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
    run = make_run(tmp_path / "run", k6_exit=107, scrapes=STALL)
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
        "- Clock skew at the hello (same_host true): corrected max 3.0 ms against 5 ms "
        "(max over 6 hellos of |raw - RTT/2|; raw max 13.0 ms; hello RTT p50 20.0 ms / max 33.0 ms)"
    ) in (run / "report.md").read_text(encoding="utf-8")


def test_result_json_keeps_the_skew_the_rtt_and_same_host_in_the_run_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "none")
    run = hello_skew_run(tmp_path / "run", same_host=True)
    runner.finish(run, 0.10)
    body = json.loads((run / "result.json").read_text(encoding="utf-8"))
    assert body["facts"]["same_host"] is True
    assert body["result"]["clock_skew"] == {
        "max_ms": 3.0,
        "raw": 13.0,
        "rtt_p50": 20.0,
        "rtt_max": 33.0,
        "hellos": 6,
        "rtt_corrected": True,
        "send_delay_ms": 0.0,
        "judged": True,
    }


def test_a_run_saved_before_the_correction_is_reported_as_raw_with_no_host_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "none")
    run = make_run(tmp_path / "old")  # only the raw skew in its summary, no same_host in run.json
    assert runner.finish(run, 0.10) == 0
    assert (
        "- Clock skew at the hello (same_host not recorded): raw max 1.0 ms against 5 ms "
        "(max over 100 hellos of |raw|; not RTT-corrected: the summary has no "
        "cv_clock_skew_corrected_ms)"
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
    monkeypatch.setenv("K6_BIN", fake("v2.3.0"))
    assert runner.k6_binary().endswith("k6-v2.3.0")


@pytest.mark.parametrize(
    ("kind", "why"),
    [
        ("bare name", "not an absolute path"),  # a PATH lookup, or the working directory's
        ("relative path", "not an absolute path"),  # a real, executable file, but a relative one
        ("directory", "not a regular file"),  # absolute and searchable, but not a file
        ("missing file", "not a regular file"),
        ("not executable", "not executable"),  # a regular file whose mode has no x bit
    ],
)
def test_a_k6_bin_that_is_not_an_absolute_executable_file_is_refused_before_anything_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, why: str
) -> None:
    script = "#!/bin/sh\necho 'k6 v2.3.0 (commit/abc, go1.26.8, linux/amd64)'\n"
    real = tmp_path / "k6"
    real.write_text(script, encoding="utf-8")
    real.chmod(0o755)
    plain = tmp_path / "plain"
    plain.write_text(script, encoding="utf-8")
    plain.chmod(0o644)
    value = {
        "bare name": "k6",
        "relative path": "./k6",
        "directory": str(tmp_path),
        "missing file": str(tmp_path / "gone"),
        "not executable": str(plain),
    }[kind]
    started: list[object] = []

    def spy(*args: object, **kwargs: object) -> None:
        started.append(args)
        raise AssertionError(f"a process was started for K6_BIN={value!r}: {args!r}")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("K6_BIN", value)
    monkeypatch.setattr(subprocess, "run", spy)  # the one runner.k6_binary calls
    with pytest.raises(SystemExit, match=why):
        runner.k6_binary()
    assert started == []  # no process was started for a path that failed the check


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
    k6_cores: float = 0.0,
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
    a = args(duration_s=duration_s, warmup_s=0.0, k6_cpus="0")
    return runner.execute(runner.plan(TABLE, a, "A", tmp_path / "out"), "k6")


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
    run = make_run(tmp_path / "run", scrapes=STALL | {"missing": [boundary]})
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


LOST_T1, LATE_T0 = {"missing": ["t1"]}, {"timed_out_ms": [15000, 15000], "retried": ["t0"]}
OUT, KEPT = "a boundary scrape timed out, left out", "scrapes timed out"
STALLED = {"timed_out_ms": [15000]}


@pytest.mark.parametrize(
    ("phase", "late", "skipped", "note", "code"),
    [
        ("mixed-lagging", LOST_T1, ["mixed-lagging"], f"phase mixed-lagging: {OUT}", 1),
        ("idle", LOST_T1, [], f"phase idle: {OUT}", 1),
        ("book-healthy", LATE_T0, [], f"phase book-healthy: 2 of 7 {KEPT} (t0 retried), kept", 0),
        ("idle", STALLED, [], f"phase idle: 1 of 7 {KEPT}, kept", 0),
        ("mixed-lagging", STALLED, [], f"phase mixed-lagging: 1 of 7 {KEPT}, kept", 0),
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


def feeder_skips(out: Path) -> None:  # the stall made the feeder skip 5 of its 100 slots
    text = (out / "scrape1.txt").read_text(encoding="utf-8")
    skipped = text.replace('published_total{kind="book"} 100', 'published_total{kind="book"} 95')
    (out / "scrape1.txt").write_text(skipped, encoding="utf-8")


def server_closes(out: Path) -> None:  # and the server closed two of k6's sockets
    summ = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    summ["counters"]["cv_unplanned_closes"] = 2
    (out / "summary.json").write_text(json.dumps(summ), encoding="utf-8")


@pytest.mark.parametrize("guard", [feeder_skips, server_closes])
def test_a_w5_mixed_phase_that_stalled_and_tripped_a_guard_is_left_out_and_noted_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    guard: Callable[[Path], None],
) -> None:
    def execute(p: runner.Plan, k6: str) -> Path:
        out = w5_phase(p)
        if p.out.name == "mixed-saturated":
            facts = json.loads((out / "run.json").read_text(encoding="utf-8"))
            (out / "run.json").write_text(json.dumps(facts | {"scrapes": STALL}), encoding="utf-8")
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


def test_runs_that_record_no_loop_are_not_compared_with_ones_that_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "BASELINES", tmp_path / "none")
    dirs = [make_run(tmp_path / f"run{i}") for i in range(3)]
    facts = json.loads((dirs[1] / "run.json").read_text(encoding="utf-8"))
    del facts["loop"]  # an artefact from before the loop was recorded
    (dirs[1] / "run.json").write_text(json.dumps(facts), encoding="utf-8")
    assert runner.cmd_gate(argparse.Namespace(dirs=[str(d) for d in dirs], tolerance=0.05)) == 2
    assert "differ in loop: asyncio, not recorded" in capsys.readouterr().out


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
    base |= {"backend_cpus": None, "k6_cpus": None}
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
        ([{}, {"k6_exit": 107, "scrapes": STALL}, {}], 2, "is FAIL (k6_exit: 107; missed: scrape"),
        ([{}, {"flag": "off"}, {}], 2, "differ in flag"),
        ([{}, {"loop": "uvloop"}, {}], 2, "differ in loop: asyncio, uvloop"),
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
    a, b = make_run(tmp_path / "a"), make_run(tmp_path / "b", scrapes=STALL | {"missing": ["t1"]})
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


def test_a_directory_the_harness_did_not_make_is_never_cleared(tmp_path: Path) -> None:
    """`--out-dir candleviewer` would otherwise delete a source tree's `bars/`: without the marker
    of an earlier run the runner refuses, says why and deletes nothing."""
    foreign = tmp_path / "candleviewer"
    (foreign / "bars").mkdir(parents=True)
    (foreign / "bars" / "series.py").write_text("SERIES = 1\n", encoding="utf-8")
    (foreign / "report.md").write_text("a report that is not ours\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="not made by this harness") as refused:
        runner._fresh(foreign)
    assert "bars" in str(refused.value) and "nothing was deleted" in str(refused.value)
    assert (foreign / "bars" / "series.py").read_text(encoding="utf-8") == "SERIES = 1\n"
    assert (foreign / "report.md").exists()
    assert not (foreign / runner.MARKER).exists()  # and it did not take the directory either
    (foreign / runner.MARKER).write_text("e17-q03/1\n", encoding="utf-8")  # the operator's say-so
    runner._fresh(foreign)
    assert not (foreign / "bars").exists() and not (foreign / "report.md").exists()


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


async def test_the_gateway_is_served_at_the_configured_path_and_nowhere_else(
    tmp_path: Path,
) -> None:
    cfg = fixture_app.BackendConfig(
        symbols=("BTCUSDT",), hot=1, warm=0, users=1, connections=1, flag=False,
        ws_path="/api/v1/ws",
    )  # fmt: skip
    async with fixture_app.Backend(cfg, TABLE, tmp_path) as be:
        async with session(be, "/api/v1/ws"):
            pass
        with pytest.raises(websockets.exceptions.InvalidStatus):
            async with session(be, "/ws"):
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
