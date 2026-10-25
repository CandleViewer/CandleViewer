# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""`shapes`, `soak`, `retention` and `report` offline, and the recording seams
(#843 A4 brief items 3 to 7)."""

from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import RateLimitError
from candleviewer.exchange.base.models import AccountRef
from candleviewer.exchange.base.reconnect import ConnectionBudget, ReconnectPolicy
from candleviewer.exchange.bybit.private_stream import PrivateStreams
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.trading import BybitTradingPort
from spike.oms_demo_path import modes, report, run
from spike.oms_demo_path.config import RunConfig
from spike.oms_demo_path.harness import Harness, PublicReads
from spike.oms_demo_path.measure import ClockOffset, Timings
from spike.oms_demo_path.offline import Corpus, CorpusVenue, default_corpus
from spike.oms_demo_path.outputs import RunOutputs
from spike.oms_demo_path.recorder import RecordingConnector, RecordingTransport
from spike.oms_demo_path.safety import GuardedPort, Refused, Shutdown
from spike.oms_demo_path.scrub import Scrubber
from tests._signing import CREDENTIAL_ID, fake_capability
from tests.chaos.ingestion._clock import VirtualClock

SIGNER = "fixture-signer-id"


def _venue(**options: Any) -> CorpusVenue:
    return CorpusVenue(Corpus(default_corpus()), **options)


def _account() -> AccountRef:
    return AccountRef(
        account_id=AccountId(uuid4()), uid="spike", environment="demo", key_ref=str(CREDENTIAL_ID)
    )


class _Rig:
    """The real port and private stream over the corpus venue, signed by the M2 double, on a
    virtual clock: what `run.open_harness` composes, minus M2 and audit."""

    def __init__(self, tmp: Path, venue: CorpusVenue) -> None:
        self.clock = VirtualClock()
        self.venue = venue
        self.scrubber = Scrubber()
        self.outputs = RunOutputs(tmp / "out", self.scrubber)
        timings = Timings()
        self.recorder = RecordingTransport(
            httpx.MockTransport(venue.handle),
            scrubber=self.scrubber,
            outputs=self.outputs,
            timings=timings,
        )
        self.connector = RecordingConnector(
            venue.connect, scrubber=self.scrubber, outputs=self.outputs, monotonic=self.clock
        )
        self.offset = ClockOffset()
        streams = PrivateStreams(
            environment="demo",
            credentials=fake_capability(SIGNER),
            connect=self.connector,
            budget=ConnectionBudget(self.clock),
            policy=ReconnectPolicy(rng=random.Random(7)),  # noqa: S311 - seeded test jitter
            sleep=self.clock.sleep,
            monotonic=self.clock,
            wall_ms=lambda: int(time.time() * 1000),
            now_us=lambda: int(time.time() * 1_000_000),
        )
        # The governor waits for tokens on the virtual clock too, so nothing here waits in real
        # time while virtual time runs ahead (C-13.7).
        governor = TokenBucketGovernor(clock=self.clock, sleep=self.clock.sleep)
        port = BybitTradingPort(
            environment="demo",
            credentials=fake_capability(SIGNER),
            governor=governor,
            transport=self.recorder,
            clock_offset_ms=self.offset.read,
            private_streams=streams,
            sleep=self.clock.sleep,
            monotonic=self.clock,
        )
        self.port = port

        def skewed(offset_ms: int) -> BybitTradingPort:
            return BybitTradingPort(
                environment="demo",
                credentials=fake_capability(SIGNER),
                governor=governor,
                transport=self.recorder,
                clock_offset_ms=lambda: offset_ms,
                sleep=self.clock.sleep,
                monotonic=self.clock,
            )

        self.harness = Harness(
            port=GuardedPort(port, timings),
            account=_account(),
            public=PublicReads(venue.get_public, lambda: int(time.time() * 1_000_000)),
            outputs=self.outputs,
            scrubber=self.scrubber,
            shutdown=Shutdown(sleep=self.clock.sleep),
            offset=self.offset,
            recorder=self.recorder,
            connector=self.connector,
            skewed_port=skewed,
            sleep=self.clock.sleep,
            monotonic=self.clock,
        )


async def test_soak_counts_reconnects_heartbeats_gaps_and_auth_refusals(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, _venue())
    h, clock = rig.harness, rig.clock
    task = asyncio.create_task(modes.run_soak(h, RunConfig(mode="soak", out=tmp_path, hours=0.5)))
    await clock.run_until(lambda: h.stream.live, within_s=60, what="the stream comes up")
    await clock.advance(700)
    rig.venue.refuse_auth = 1
    rig.venue.sockets[-1].drop()
    await clock.run_until(task.done, within_s=0.5 * 3600 + 600, what="the soak ends")
    result = task.result()
    assert result["dials"] == 3 and result["reconnects"] == 2
    frames = result["frames"]
    assert isinstance(frames, dict)
    assert frames["auth:granted"] == 2 and frames["auth:refused"] == 1
    assert frames["received:op_pong"] > 300
    statuses = h.stream.statuses
    assert statuses["down:socket_closed"] == 1 and statuses["resyncing:reconnected"] == 1
    assert len(h.stream.gaps_s) == 1 and h.stream.gaps_s[0] > 0
    assert result["meets_ticket"] is False and rig.offset.samples >= 10
    assert rig.venue.creates == []  # a soak places nothing


async def test_shapes_capture_the_duplicate_and_the_clock_drift_replies(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, _venue())
    shapes = await modes.run_shapes(rig.harness, RunConfig(mode="shapes", out=tmp_path))
    duplicate, drift = shapes["duplicate"], shapes["10002"]
    assert isinstance(duplicate, dict) and isinstance(drift, dict)
    corpus = Corpus(default_corpus())
    assert duplicate["raised"] == "DuplicateClientIdError" and duplicate["code"] == 110072
    assert duplicate["reply"] == corpus.rest("trading-error-110072")
    assert duplicate["attempts"] == 1 and duplicate["first_ok"] is True
    assert drift["raised"] == "ClockDriftError" and drift["code"] == 10002
    assert drift["attempts"] == 2
    expected = corpus.rest("error_10002")
    assert {k: v for k, v in drift["reply"].items() if k != "time"} == {
        k: v for k, v in expected.items() if k != "time"
    }
    assert shapes["10018"] is None
    first = rig.venue.creates[0]
    assert first["timeInForce"] == "PostOnly" and "stopLoss" in first
    assert all(o.status == "Cancelled" for o in rig.venue.orders.values())


async def test_shapes_needs_the_adapters_port_factory(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, _venue())
    rig.harness.skewed_port = None
    with pytest.raises(Refused, match="factory"):
        await modes.run_shapes(rig.harness, RunConfig(mode="shapes", out=tmp_path))


async def test_a_10018_is_recorded_whole_when_one_occurs(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, _venue(rate_limit_once=True))
    with pytest.raises(RateLimitError):
        await rig.port.wallet(rig.harness.account)
    assert rig.recorder.codes == {10018: 1}
    shape = rig.recorder.shapes[10018]
    assert isinstance(shape, dict) and shape["retMsg"] == "too many visits"


async def test_retention_counts_history_by_state_and_age(tmp_path: Path) -> None:
    venue = _venue()
    venue.seed_history(3, age_days=9)
    venue.seed_history(2, age_days=0.5, status="Filled")
    rig = _Rig(tmp_path, venue)
    since = int(time.time() * 1000) - 10 * 86_400_000
    result = await modes.run_retention(
        rig.harness, RunConfig(mode="retention", out=tmp_path, since_ms=since)
    )
    assert result["rows"] == 5 and result["older_than_7d"] == 3 and result["older_than_1d"] == 3
    assert result["by_state"] == {"cancelled": 3, "filled": 2}


async def test_retention_offline_defaults_to_nine_days_back(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, _venue())
    result = await modes.run_retention(rig.harness, RunConfig(mode="retention", out=tmp_path))
    assert result["rows"] == 0 and isinstance(result["since_ms"], int)


async def test_offline_shapes_through_the_whole_run(tmp_path: Path) -> None:
    venue = _venue()
    assert await run.run(RunConfig(mode="shapes", out=tmp_path / "out"), venue=venue) == 0
    summary = dict(run.summary_of(tmp_path / "out"))
    assert summary["shapes"]["duplicate"]["raised"] == "DuplicateClientIdError"
    assert summary["error_codes"] == {"10002": 2, "110072": 1}
    assert summary["shutdown"]["flat"] is True
    text = report.render(tmp_path / "out")
    assert "### Reply shape 10002" in text and "### Reply shape 110072" in text


async def test_report_renders_the_run_tables(tmp_path: Path) -> None:
    cfg = RunConfig(mode="cycles", out=tmp_path / "out", cycles=2, min_hours=0.0, fill_wait_s=0.2)
    assert await run.run(cfg, venue=_venue()) == 0
    text = report.render(tmp_path / "out")
    for title in (
        "Venue RTT at the seam",
        "Our overhead, port minus RTT",
        "Budget #4 (create)",
        "Execution parity",
        "Ordering (23 S5)",
        "Cycle outcomes",
        "Private stream latency",
    ):
        assert f"### {title}" in text
    assert "offline corpus venue" in text


# -- the recording seams ----------------------------------------------------------------------


async def test_the_recording_transport_refuses_a_host_off_the_demo_allow_list(
    tmp_path: Path,
) -> None:
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200)

    scrubber = Scrubber()
    recorder = RecordingTransport(
        httpx.MockTransport(answer),
        scrubber=scrubber,
        outputs=RunOutputs(tmp_path / "out", scrubber),
        timings=Timings(),
    )
    for url in (
        "https://api.bybit.com/v5/order/create",
        "http://api-demo.bybit.com/v5/order/create",
    ):
        with pytest.raises(Refused, match="allow-list"):
            await recorder.handle_async_request(httpx.Request("POST", url))
    assert sent == []


async def test_the_recording_connector_refuses_a_stream_off_the_demo_allow_list(
    tmp_path: Path,
) -> None:
    venue = _venue()
    scrubber = Scrubber()
    connector = RecordingConnector(
        venue.connect, scrubber=scrubber, outputs=RunOutputs(tmp_path / "out", scrubber)
    )
    with pytest.raises(Refused, match="allow-list"):
        await connector("wss://stream.bybit.com/v5/private")
    assert venue.sockets == [] and connector.dials == 0


async def test_an_auth_frame_is_never_recorded_and_its_values_are_learnt(tmp_path: Path) -> None:
    venue = _venue()
    scrubber = Scrubber()
    outputs = RunOutputs(tmp_path / "out", scrubber)
    connector = RecordingConnector(venue.connect, scrubber=scrubber, outputs=outputs)
    sock = await connector("wss://stream-demo.bybit.com/v5/private")
    key, signature = "K" * 18, "ab" * 32
    await sock.send(json.dumps({"op": "auth", "args": [key, 1_790_000_000_000, signature]}))
    await sock.recv(1 << 20)
    await sock.send(json.dumps({"op": "ping"}))
    await sock.recv(1 << 20)
    venue.sockets[-1].inbox.put_nowait("{not json")
    await sock.recv(1 << 20)
    await sock.close()
    outputs.event("echo", text=f"the venue said {key} and {signature}")
    outputs.close()
    written = (tmp_path / "out" / "events.jsonl").read_text()
    assert key not in written and signature not in written
    assert connector.counts["auth:granted"] == 1 and connector.counts["received:op_pong"] == 1
    assert connector.counts["received:unreadable"] == 1
    assert not list((tmp_path / "out" / "fixtures").glob("*auth*"))


async def test_public_reads_refuse_other_paths_and_answers_with_no_row() -> None:
    async def empty(path: str, *, params: Any = None) -> dict[str, Any]:
        return {"retCode": 0, "result": {"list": []}}

    reads = PublicReads(empty, lambda: 0)
    with pytest.raises(Refused, match="public reads"):
        await reads._read("/v5/market/tickers")
    with pytest.raises(Refused, match="no recent trade"):
        await reads.reference()
    with pytest.raises(Refused, match="single BTCUSDT"):
        await reads.instrument()
    assert reads.reads == 2


async def test_the_seam_records_a_transport_failure_and_caps_a_reply(tmp_path: Path) -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v5/order/realtime":
            raise httpx.ConnectError("refused")
        return httpx.Response(200, content=b"x" * (5 * 1024 * 1024))

    scrubber = Scrubber()
    outputs = RunOutputs(tmp_path / "out", scrubber)
    recorder = RecordingTransport(
        httpx.MockTransport(failing), scrubber=scrubber, outputs=outputs, timings=Timings()
    )
    with pytest.raises(httpx.ConnectError):
        await recorder.handle_async_request(
            httpx.Request("GET", "https://api-demo.bybit.com/v5/order/realtime")
        )
    with pytest.raises(httpx.ReadError):
        await recorder.handle_async_request(
            httpx.Request("GET", "https://api-demo.bybit.com/v5/position/list")
        )
    lines = [json.loads(x) for x in (tmp_path / "out" / "events.jsonl").read_text().splitlines()]
    assert [(e["call"], e["failure"]) for e in lines] == [
        ("open_orders", "ConnectError"),
        ("positions", "ReadError"),
    ]
