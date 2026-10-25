# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The round-1 lenses' other findings, each pinned (#843 A4 fold 2): the security lens's R1S-01,
R1S-02, R1S-03, R1S-05 and R1S-06, and the code lens's R1C-03 to R1C-15."""

from __future__ import annotations

import asyncio
import json
import random
import string
import time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import structlog

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.exchange.base.models import (
    Execution,
    Order,
    PlaceOrderRequest,
    PrivateEvent,
)
from spike.oms_demo_path import cycles, modes, report, run
from spike.oms_demo_path.config import DEMO_PRIVATE_WS, RunConfig
from spike.oms_demo_path.harness import Harness
from spike.oms_demo_path.ledger import IntentLedger
from spike.oms_demo_path.measure import ClockOffset, StreamMonitor, Timings, stats
from spike.oms_demo_path.metrics import export
from spike.oms_demo_path.offline import Corpus, CorpusVenue, default_corpus
from spike.oms_demo_path.outputs import RunOutputs
from spike.oms_demo_path.recorder import KEEPALIVE_S, RecordingConnector, RecordingTransport
from spike.oms_demo_path.safety import Refused
from spike.oms_demo_path.scrub import LeakDetected, Scrubber
from spike.oms_demo_path.tests.test_modes import _Rig
from tests._corpus import frames

ACCOUNT = "6c2d0e3f-8041-4b7c-9d5e-3f4a5b6c7d8e"
README = Path(run.__file__).parent / "README.md"


def _venue(**options: Any) -> CorpusVenue:
    return CorpusVenue(Corpus(default_corpus()), **options)


def _cfg(out: Path, **fields: Any) -> RunConfig:
    base: dict[str, Any] = {"mode": "cycles", "out": out, "cycles": 2, "min_hours": 0.0}
    return RunConfig(**(base | {"fill_wait_s": 0.2} | fields))


def _flat(text: str) -> str:
    return " ".join(text.split())


# -- R1S-01: the REST key id and signature never reach an output ------------------------------


async def test_the_rest_key_id_and_signature_never_reach_events(tmp_path: Path) -> None:
    corpus = Corpus(default_corpus())
    scrubber = Scrubber()
    outputs = RunOutputs(tmp_path / "out", scrubber)

    def answer(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=corpus.rest("trading-wallet-balance"))

    recorder = RecordingTransport(
        httpx.MockTransport(answer), scrubber=scrubber, outputs=outputs, timings=Timings()
    )
    named, signed = "Q" * 9 + "w" * 9, "c3" * 32
    headers = {"X-BAPI-API-KEY": named, "X-BAPI-SIGN": signed}
    url = "https://api-demo.bybit.com/v5/account/wallet-balance"
    await recorder.handle_async_request(httpx.Request("GET", url, headers=headers))
    assert scrubber.registered() >= 2  # both, before anything was written
    assert outputs.event("echo", text=f"{named} {signed}") is True
    outputs.close()
    written = (tmp_path / "out" / "events.jsonl").read_text()
    assert named not in written and signed not in written
    assert [json.loads(line)["kind"] for line in written.splitlines()] == ["rest", "echo"]


# -- R1S-02: the UID from the order and position push-id form --------------------------------


@pytest.mark.parametrize(
    ("topic", "uid"), [("order", "592324"), ("position", "100307601"), ("wallet", "592324")]
)
def test_a_push_id_of_the_uuid_form_teaches_the_uid(topic: str, uid: str) -> None:
    scrubber = Scrubber()
    [frame] = frames(f"ws/private-{topic}.jsonl")
    assert json.loads(frame)["id"].startswith(uid)
    scrubber.frame(frame)
    text = scrubber.dumps({"retMsg": f"uid {uid} refused", "note": f"{uid}."})
    assert uid not in text and text.count("<redacted>") == 2


def test_a_push_id_of_no_known_form_teaches_its_leading_digits() -> None:
    scrubber = Scrubber()
    scrubber.scrub({"id": "12345678-not-a-known-form"})
    assert "12345678" not in scrubber.dumps({"retMsg": "uid 12345678"})
    scrubber.scrub({"id": "123456-short"})  # fewer than 7 digits: no UID learnt from it
    assert "123456" in scrubber.dumps({"retMsg": "uid 123456"})


# -- R1S-06: online, the failure's class and code only -----------------------------------------


@pytest.mark.parametrize("offline", [True, False])
def test_mode_failed_keeps_the_traceback_offline_only(
    offline: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    run.configure_logging(Scrubber())
    try:
        raise ExchangeError("the venue echoed an unregistered row", exchange_ret_code=10006)
    except ExchangeError as exc:
        run.mode_failed(exc, offline=offline)
    err = capsys.readouterr().err
    [line] = [json.loads(x) for x in err.splitlines() if "mode_failed" in x]
    assert (line["error"], line["exchange_ret_code"]) == ("ExchangeError", 10006)
    assert ("exception" in line) is offline
    assert ("unregistered row" in err) is offline


def test_mode_failed_names_no_code_for_an_error_of_ours(capsys: pytest.CaptureFixture[str]) -> None:
    run.configure_logging(Scrubber())
    run.mode_failed(RuntimeError("not the venue's"), offline=False)
    [line] = [json.loads(x) for x in capsys.readouterr().err.splitlines()]
    assert line["error"] == "RuntimeError" and line["exchange_ret_code"] is None


# -- R1C-03: the scrub is O(len), and off the receive path ------------------------------------


def _registered(count: int) -> Scrubber:
    """A scrubber holding `count` values of the shapes a long run registers."""
    rng = random.Random(843)  # noqa: S311 - seeded test values, never a secret
    scrubber = Scrubber()
    alnum = string.ascii_letters + string.digits
    while scrubber.registered() < count:
        shape = scrubber.registered() % 4
        if shape == 0:
            scrubber.known("order", str(UUID(int=rng.getrandbits(128), version=4)))
        elif shape == 1:
            scrubber.known("link", f"cvd-0{''.join(rng.choices(alnum, k=21))}-ab12-00en")
        elif shape == 2:
            scrubber.secret("".join(rng.choices("0123456789abcdef", k=64)))
        else:
            scrubber.known(
                "push", f"{rng.randrange(10**8, 10**10)}_BTCUSDT_{rng.randrange(10**12)}"
            )
    return scrubber


def _event() -> dict[str, Any]:
    [frame] = frames("ws/private-execution.jsonl")
    return {"t": 12.5, "kind": "private_frame", "frame": json.loads(frame)}


@pytest.mark.perf  # a time budget (C-13.9): run with `-m perf`, without coverage
def test_one_event_scrubs_in_under_a_millisecond_with_5000_registered_ids() -> None:
    scrubber, event = _registered(5000), _event()
    assert scrubber.registered() == 5000
    spent = []
    for _ in range(20):
        began = time.thread_time_ns()  # this thread's CPU: a loaded host does not inflate it
        scrubber.dumps(event)
        spent.append(time.thread_time_ns() - began)
    assert min(spent) < 1_000_000, f"best of 20: {min(spent) / 1e6:.3f} ms"


async def test_recv_returns_before_the_frame_is_scrubbed_and_the_writer_scrubs_it_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue, scrubber = _venue(), Scrubber()
    outputs = RunOutputs(tmp_path / "out", scrubber)
    outputs.start()
    scrubbed: list[str] = []
    real = scrubber.frame

    def spied(frame: str) -> Any:
        scrubbed.append(frame)
        return real(frame)

    monkeypatch.setattr(scrubber, "frame", spied)
    connector = RecordingConnector(venue.connect, scrubber=scrubber, outputs=outputs)
    sock = await connector(DEMO_PRIVATE_WS)
    await sock.send(json.dumps({"op": "ping"}))
    frame = await sock.recv(1 << 20)
    assert scrubbed == [] and connector.counts["received:op_pong"] == 0  # queued, not scrubbed
    await outputs.flush()
    assert scrubbed == [frame] and connector.counts["received:op_pong"] == 1
    await outputs.stop()
    outputs.close()
    assert (tmp_path / "out" / "fixtures" / "private_op_pong.jsonl.gz").is_file()


async def test_the_writer_scrubs_before_it_writes_and_drops_past_its_bound(tmp_path: Path) -> None:
    writes: list[bytes] = []
    scrubber = Scrubber()
    scrubber.secret(ACCOUNT)
    outputs = RunOutputs(
        tmp_path / "out",
        scrubber,
        write=lambda _path, data, _append: writes.append(data),
        queue_bound=2,
    )
    outputs.start()
    assert [outputs.event("x", note=f"for {ACCOUNT}") for _ in range(3)] == [True, True, False]
    assert writes == [] and outputs.dropped == 1
    await outputs.stop()
    assert len(writes) == 2 and not [w for w in writes if ACCOUNT.encode() in w]
    assert outputs.event("after", n=1) is True and len(writes) == 3  # synchronous again


async def test_an_unstarted_writer_stops_at_once_and_a_transient_value_is_checked(
    tmp_path: Path,
) -> None:
    outputs = RunOutputs(tmp_path / "out", Scrubber())
    await outputs.stop()
    await outputs.flush()
    assert not outputs.deferred
    with pytest.raises(LeakDetected):
        Scrubber().check(f"signed {'d4' * 32}", transient=("d4" * 32,))


async def test_a_write_the_disk_refuses_is_counted_and_the_writer_goes_on(tmp_path: Path) -> None:
    def refusing(_path: Path, _data: bytes, _append: bool) -> None:
        raise OSError("no space")

    outputs = RunOutputs(tmp_path / "out", Scrubber(), write=refusing)
    outputs.start()
    outputs.event("x")
    outputs.event("y")
    await outputs.flush()
    assert outputs.write_errors == 2 and outputs.deferred
    await outputs.stop()
    assert not outputs.deferred


# -- R1C-04: the measured numbers, pinned ----------------------------------------------------


_RANKS = [
    (1, 1, 1, 1),
    (2, 1, 2, 2),
    (20, 10, 19, 20),
    (100, 50, 95, 99),
    (200, 100, 190, 198),
    (400, 200, 380, 396),
]


@pytest.mark.parametrize(("n", "p50", "p95", "p99"), _RANKS)
def test_stats_are_the_nearest_rank(n: int, p50: int, p95: int, p99: int) -> None:
    values = [float(v) for v in range(n, 0, -1)]  # unsorted on purpose
    assert stats(values) == {"n": n, "p50": p50, "p95": p95, "p99": p99, "min": 1.0, "max": n}
    assert stats([]) == {"n": 0}


def test_the_clock_offset_keeps_the_sample_with_the_smallest_round_trip() -> None:
    offset = ClockOffset()
    offset.sample(0.0, 100.0, 1_050)  # rtt 100: 1050 - 50
    assert (offset.value, offset.best_rtt_ms) == (1_000, 100.0)
    offset.sample(300.0, 310.0, 2_305)  # rtt 10 wins: 2305 - 305
    offset.sample(400.0, 500.0, 9_999)  # rtt 100 loses
    assert (offset.value, offset.best_rtt_ms, offset.samples) == (2_000, 10.0, 3)
    offset.reset_best()
    offset.sample(600.0, 700.0, 650)  # a re-measure starts afresh, so drift is followed
    assert offset.value == 0 and offset.read() == 0


async def test_our_overhead_is_the_call_less_the_round_trips_it_made() -> None:
    ticks = iter([0.0, 0.1])
    timings = Timings(monotonic=lambda: next(ticks))
    async with timings.call("create"):
        timings.exchanged("/v5/order/create", 30.0)
        timings.exchanged("/v5/order/create", 20.0, cold=True)
    assert timings.port_ms["create"] == [pytest.approx(100.0)]
    assert timings.overhead_ms["create"] == [pytest.approx(50.0)]
    assert timings.rtt_split_ms["create:warm"] == [30.0]
    assert timings.rtt_split_ms["create:cold"] == [20.0]


def _fill(order_id: str, qty: str, n: int) -> PrivateEvent:
    payload = Execution.model_validate(
        {
            "exec_id": f"exec-{n}",
            "exchange_order_id": order_id,
            "order_link_id": f"ext-{'0' * 31}{n}",
            "account_id": UUID(ACCOUNT),
            "symbol": "BTCUSDT",
            "side": "buy",
            "price": Decimal("60000"),
            "qty": Decimal(qty),
            "fee": Decimal("0.01"),
            "fee_rate": Decimal("0.0002"),
            "fee_currency": "USDT",
            "is_maker": True,
            "exec_type": "trade",
            "closed_pnl": None,
            "ts_exec": 1_000_000,
            "ts_ingest": 1_007_000,
            "seq": n,
        }
    )
    return PrivateEvent(
        kind="execution",
        account_id=AccountId(UUID(ACCOUNT)),
        payload=payload,
        ts_event=1_000_000,
        ts_ingest=1_007_000,
    )


def _order(order_id: str, filled: str) -> PrivateEvent:
    payload = Order.model_validate(
        {
            "order_link_id": f"ext-{'0' * 32}",
            "exchange_order_id": order_id,
            "account_id": UUID(ACCOUNT),
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "limit",
            "qty": Decimal("0.002"),
            "price": Decimal("60000"),
            "state": "partially_filled" if Decimal(filled) < Decimal("0.002") else "filled",
            "filled_qty": Decimal(filled),
            "leaves_qty": Decimal("0.002") - Decimal(filled),
            "avg_fill_price": None,
            "created_at": 1_000_000,
            "terminal_at": None,
            "updated_at": 1_000_000,
        }
    )
    return PrivateEvent(
        kind="order",
        account_id=AccountId(UUID(ACCOUNT)),
        payload=payload,
        ts_event=1_000_000,
        ts_ingest=1_007_000,
    )


def test_the_monitor_counts_reorders_parity_and_corrected_latency() -> None:
    offset = ClockOffset()
    offset.sample(0.0, 0.0, 3)  # the venue 3 ms ahead of the host
    monitor = StreamMonitor(offset)
    monitor.observe(_order("A", "0.001"))  # the order reports the fill first:
    monitor.observe(_fill("A", "0.001", 1))  # a reorder
    monitor.observe(_fill("B", "0.001", 2))  # its order event comes after: in order
    monitor.observe(_order("B", "0.001"))
    monitor.observe(_fill("B", "0.001", 2))  # a duplicate push
    monitor.rest_executions([_fill("C", "0.001", 3).payload])  # type: ignore[list-item]
    assert monitor.ordering_counts() == {
        "venue_reorder_execution_after_its_order_transition": 1,
        "dropped_push_execution_only_via_backfill": 1,
    }
    parity = monitor.parity()
    assert (parity["stream"], parity["rest"], parity["rest_only"], parity["stream_only"]) == (
        2,
        1,
        1,
        2,
    )
    assert parity["duplicates"] == 1
    assert monitor.latency_ms["execution"] == [10.0] * 3  # 1007 ms + 3 - 1000, each push


async def test_a_skewed_venue_clock_is_measured_and_the_latency_corrected(
    tmp_path: Path,
) -> None:
    """The venue 2000 ms ahead: the offset finds it, the private latency stays small once
    corrected, and the backfill windows on the venue's clock miss no fill (R1C-11)."""
    venue = _venue(now_ms=lambda: int(time.time() * 1000) + 2000)
    assert await run.run(_cfg(tmp_path / "out", cycles=3), venue=venue) == 0
    s = dict(run.summary_of(tmp_path / "out"))
    assert abs(s["clock"]["offset_ms"] - 2000) < 100
    assert 0 <= s["private"]["latency_ms"]["execution"]["p50"] < 100
    parity = s["private"]["parity"]
    assert parity["both"] == venue.fills and parity["rest_only"] == parity["stream_only"] == 0


# -- R1C-05: the unfilled path, the log hook and an int id -----------------------------------


async def test_an_unfilled_cycle_cancels_and_closes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue = _venue()
    monkeypatch.setattr(venue, "_match", lambda _order: None)  # nothing ever fills
    assert await run.run(_cfg(tmp_path / "out"), venue=venue) == 0
    s = dict(run.summary_of(tmp_path / "out"))
    assert s["cycles"]["outcomes"] == {"unfilled": 2}
    assert s["cycles"]["actions"] == {"amend": 2, "cancel": 2, "drive": 2, "place": 2}
    assert all(not body["reduceOnly"] for body in venue.creates) and venue.size == 0
    assert s["shutdown"]["flat"] is True


def test_the_process_log_is_scrubbed(capsys: pytest.CaptureFixture[str]) -> None:
    scrubber = Scrubber()
    scrubber.secret(ACCOUNT)
    run.configure_logging(scrubber)
    structlog.get_logger("spike").warning(
        "bybit_private_stream_down", account_id=ACCOUNT, note=f"stream of {ACCOUNT} down"
    )
    err = capsys.readouterr().err
    assert ACCOUNT not in err and "bybit_private_stream_down" in err


def test_an_int_id_under_a_plain_key_is_replaced() -> None:
    scrubber = Scrubber()
    token = scrubber.known("order", "1234567890")
    scrubber.secret("9876543210")
    assert scrubber.scrub({"seq": 1234567890, "n": 9876543210, "qty": 2, "ok": True}) == {
        "seq": token,
        "n": "<redacted>",
        "qty": 2,
        "ok": True,
    }


# -- R1C-06 and R1C-09: cold and warm, openers and closes, failures counted --------------------


async def test_the_seam_tells_cold_from_warm_and_openers_from_closes(tmp_path: Path) -> None:
    corpus = Corpus(default_corpus())
    clock = iter([0.0, 0.01, 1.0, 1.01, 10.0, 10.01])
    timings = Timings()

    def answer(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=corpus.rest("trading-create-reply"))

    scrubber = Scrubber()
    outputs = RunOutputs(tmp_path / "out", scrubber)
    recorder = RecordingTransport(
        httpx.MockTransport(answer),
        scrubber=scrubber,
        outputs=outputs,
        timings=timings,
        monotonic=lambda: next(clock),
    )
    url = "https://api-demo.bybit.com/v5/order/create"
    for closing in (False, True, False):  # cold (first), warm (1 s idle), cold (9 s idle)
        await recorder.handle_async_request(
            httpx.Request("POST", url, json={"reduceOnly": closing, "symbol": "BTCUSDT"})
        )
    split = timings.summary()["rtt_split_ms"]
    assert (split["create:cold"]["n"], split["create:warm"]["n"]) == (2, 1)
    assert (split["create_open"]["n"], split["create_close"]["n"]) == (2, 1)
    assert (split["create_open:cold"]["n"], split["create_close:warm"]["n"]) == (2, 1)
    lines = [json.loads(x) for x in (tmp_path / "out" / "events.jsonl").read_text().splitlines()]
    assert [(e["connection"], e["idle_s"]) for e in lines] == [
        ("cold", None),
        ("warm", 0.99),
        ("cold", 8.99),
    ]
    assert KEEPALIVE_S == httpx.Limits().keepalive_expiry


async def test_a_failed_exchange_is_counted_by_its_class(tmp_path: Path) -> None:
    def failing(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no answer")

    scrubber, timings = Scrubber(), Timings()
    recorder = RecordingTransport(
        httpx.MockTransport(failing),
        scrubber=scrubber,
        outputs=RunOutputs(tmp_path / "out", scrubber),
        timings=timings,
    )
    for _ in range(2):
        with pytest.raises(httpx.ConnectTimeout):
            await recorder.handle_async_request(
                httpx.Request("GET", "https://api-demo.bybit.com/v5/order/realtime")
            )
    rtt = timings.summary()["rtt_ms"]
    assert rtt == {"open_orders": {"n": 0, "failed": 2}}
    text = report.render(_written(tmp_path / "run", {"mode": "cycles", "rtt_ms": rtt}))
    assert "| | n | p50 | p95 | p99 | max | failed |" in text and "| open_orders | 0 |" in text


def _written(run_dir: Path, summary: dict[str, Any]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return run_dir


def test_the_budget_block_and_the_report_carry_the_create_split(tmp_path: Path) -> None:
    timings = Timings()
    timings.rtt_split_ms["create:cold"] = [300.0] * 20
    timings.rtt_split_ms["create:warm"] = [40.0] * 20
    timings.rtt_split_ms["create_open"] = [300.0] * 20
    block = run.budget(timings, offline=False)
    assert block["create_rtt_p95_ms_by_split"] == {
        "create:cold": 300.0,
        "create:warm": 40.0,
        "create_open": 300.0,
        "create_close": None,
    }
    summary = {"mode": "cycles", "offline": False, "budget4": block}
    text = report.render(_written(tmp_path / "run", summary))
    assert (
        "Create RTT p95 by connection and kind (ms): cold 300.0, warm 40.0;"
        " limit openers 300.0, reduce-only closes missing" in text
    )


# -- R1C-08: the offline venue pages its lists ------------------------------------------------


async def test_a_backfill_of_250_executions_reads_every_page(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, _venue())
    rig.venue.list_fills(250)
    await cycles.backfill(rig.harness, rig.harness.now_us() - 3_600_000_000)
    assert len(rig.harness.stream.rest_execs) == 250
    assert rig.venue.paths.count("/v5/execution/list") == 3  # 100, 100, 50
    for _ in range(120):
        rig.venue.rest_foreign_order()
    orders = await rig.port.open_orders(rig.harness.account, "BTCUSDT")
    assert len(orders) == 120 and rig.venue.paths.count("/v5/order/realtime") == 3
    history = await rig.port.order_history(rig.harness.account)
    assert len(history) == 120 and rig.venue.paths.count("/v5/order/history") == 3


# -- R1C-10: the outcome is read again after the cancel ---------------------------------------


async def test_a_fill_seen_only_after_the_cancel_makes_the_cycle_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = cycles.read_order
    reads: list[str] = []

    async def stale_first(h: Harness, link: str) -> Order | None:
        order = await original(h, link)
        reads.append(link)
        if len(reads) == 1 and order is not None:  # a lagging read: no fill yet
            update = {"state": "new", "filled_qty": Decimal(0), "leaves_qty": order.qty}
            return order.model_copy(update=update)
        return order

    monkeypatch.setattr(cycles, "read_order", stale_first)
    cfg = _cfg(tmp_path / "out", cycles=1, side="buy", fill_mode="join")
    assert await run.run(cfg, venue=_venue()) == 0
    s = dict(run.summary_of(tmp_path / "out"))
    assert s["cycles"]["outcomes"] == {"partial": 1}
    assert s["cycles"]["actions"]["close"] == 1


async def test_an_order_seen_filled_only_after_the_cancel_is_a_filled_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = cycles.read_order
    reads: list[str] = []

    async def stale_first(h: Harness, link: str) -> Order | None:
        order = await original(h, link)
        reads.append(link)
        if len(reads) == 1 and order is not None:  # it crossed and filled whole, unseen yet
            update = {"state": "new", "filled_qty": Decimal(0), "leaves_qty": order.qty}
            return order.model_copy(update=update)
        return order

    monkeypatch.setattr(cycles, "read_order", stale_first)
    cfg = _cfg(tmp_path / "out", cycles=1, side="buy", fill_mode="cross")
    assert await run.run(cfg, venue=_venue()) == 0
    s = dict(run.summary_of(tmp_path / "out"))
    assert s["cycles"]["outcomes"] == {"filled": 1} and s["cycles"]["actions"]["close"] == 1


async def test_a_close_left_resting_is_cancelled_and_closed_again_by_the_residual_flatten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue = _venue()
    match = venue._match
    skipped: list[str] = []

    def first_close_rests(order: Any) -> None:
        if order.reduce_only and not skipped:
            skipped.append(order.link)  # the venue leaves the cycle's close resting
            return
        match(order)

    monkeypatch.setattr(venue, "_match", first_close_rests)
    cfg = _cfg(tmp_path / "out", cycles=1, side="buy", fill_mode="cross")
    assert await run.run(cfg, venue=venue) == 0
    s = dict(run.summary_of(tmp_path / "out"))
    assert s["cycles"]["actions"]["residual_flatten"] == 1 and venue.size == 0
    [rested] = [o for o in venue.orders.values() if o.link == skipped[0]]
    assert rested.status == "Cancelled" and s["shutdown"]["flat"] is True


async def test_flatten_mode_refuses_without_a_scope_and_reports_a_net_it_cannot_close(
    tmp_path: Path,
) -> None:
    rig = _Rig(tmp_path, _venue())
    h = rig.harness
    with pytest.raises(Refused, match="needs --run-dir"):
        await modes.run_flatten(h, RunConfig(mode="flatten", out=tmp_path))
    run_dir = _written(tmp_path / "failed", {"run_scope": "not a scope"})
    with pytest.raises(Refused, match="no run scope"):
        await modes.run_flatten(h, RunConfig(mode="flatten", out=tmp_path, run_dir=run_dir))
    theirs = h.links.new()  # a fill of "the failed run", which the venue no longer holds
    rig.venue.list_fills(1)
    rig.venue.executions[-1] |= {"orderLinkId": theirs, "side": "Buy"}
    scope = h.scope.record() | {"window_start_ms": int(time.time() * 1000) - 60_000}
    run_dir = _written(tmp_path / "failed2", {"run_scope": scope})
    sent = PlaceOrderRequest(  # that run's row for it, as its guard wrote it before the send
        account=h.account,
        symbol="BTCUSDT",
        side="buy",
        order_type="limit",
        qty=Decimal("0.002"),
        price=Decimal("60000"),
        order_link_id=theirs,
        stop_loss=Decimal("58000"),
    )
    IntentLedger(run_dir, Scrubber(), elapsed=lambda: 0.0).record(sent)
    report_ = await modes.run_flatten(h, RunConfig(mode="flatten", out=tmp_path, run_dir=run_dir))
    assert report_["flat"] is False and report_["errors"] == ["net_not_held"]
    assert h.shutdown.reason == "error:not_flat"


# -- R1C-15: the metric keeps a negative latency, as the summary does -------------------------


def test_the_metric_keeps_a_negative_private_latency() -> None:
    monitor = StreamMonitor(ClockOffset())
    monitor.latency_ms["order"] = [-3.0, 5.0]
    text = export(Timings(), monitor, {}, None)
    assert 'spike_private_latency_seconds_sum{env="demo",kind="order"} 0.002' in text
    assert 'spike_private_latency_seconds_bucket{env="demo",kind="order",le="0.005"} 2.0' in text


# -- R1S-03, R1S-04, R1S-05, R1C-12: the runbook ----------------------------------------------


def test_the_readme_forbids_a_rotation_during_a_run_and_says_why() -> None:
    flat = _flat(README.read_text(encoding="utf-8"))
    before = flat[flat.index("**Before anything**") : flat.index("1. **The spike checkout**")]
    for words in ("`CV_KEK_PREV_HANDLE`", "key rotation", "revoke", "strands its signing"):
        assert words in before, words


def test_the_readme_words_the_proxy_check_as_httpx_mounts_it() -> None:
    flat = _flat(README.read_text(encoding="utf-8"))
    assert "only when no transport is given" in flat
    assert "`public_rest_client`" in flat and "cannot be bypassed" in flat
    assert "bypass the seam" not in flat


def test_the_readme_and_the_addendum_claim_no_order_action_audit(tmp_path: Path) -> None:
    claim = "one `security.credential_borrowed` row per signed request, not one per order action"
    assert claim in _flat(README.read_text(encoding="utf-8"))
    text = _flat(report.addendum(_written(tmp_path / "run", {"mode": "cycles"})))
    assert claim in text and "must not claim order-action audit coverage" in text


def test_the_runbook_names_the_flatten_and_the_overlay() -> None:
    flat = _flat(README.read_text(encoding="utf-8"))
    runbook = flat[flat.index("## Host runbook") :]
    assert "$SPIKE flatten $IDS --run-dir" in runbook
    assert "the owner's recovery when a run's shutdown flatten failed" in runbook
    assert "infra/compose/docker-compose.demo-host.yml" in runbook
    assert "<3180 overlay>" not in runbook


async def test_the_writer_drains_before_the_soak_reads_its_counts(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, _venue())
    rig.outputs.start()
    h, clock = rig.harness, rig.clock
    task = asyncio.create_task(
        run.MODES["soak"](h, RunConfig(mode="soak", out=tmp_path, hours=0.01))
    )
    await clock.run_until(lambda: h.stream.live, within_s=60, what="the stream comes up")
    await clock.run_until(task.done, within_s=0.01 * 3600 + 600, what="the soak ends")
    result = task.result()
    frames_counted = result["frames"]
    assert isinstance(frames_counted, dict) and frames_counted["received:op_pong"] >= 5
    await rig.outputs.stop()
    assert rig.outputs.frames_seen["op_pong"] == frames_counted["received:op_pong"]


def test_a_fresh_account_id_is_a_uuid() -> None:  # the offline stack's own, as online
    assert UUID(str(uuid4())).version == 4
