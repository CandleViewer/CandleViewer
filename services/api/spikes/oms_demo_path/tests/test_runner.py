"""The harness against the in-memory venue (`venue.py`): no network and no real waits.

The venue's REST runs under the harness's own `GuardedTransport`, so every guard rail stays in the
path, and the private stream is the venue's fake socket. Each test drives a public step (`drive`,
`cleanup`, `wrap_up`) and reads what reached the venue and what the run wrote.
"""

from __future__ import annotations

import asyncio
import csv
import functools
import hashlib
import json
import signal
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.secrets import Secret
from spikes.oms_demo_path.runner import (
    CLEAN,
    COMPLETED,
    CYCLE_COLUMNS,
    INTERRUPTED,
    ORDER_COLUMNS,
    Config,
    Harness,
    _on_signals,
    drive,
)
from spikes.oms_demo_path.safety import EnvCredentials, SafetyRefusal, new_link
from spikes.oms_demo_path.stats import RestExecution

from .venue import SYMBOL, FakeBybit

#: The run's key id: key-shaped, derived at run time (no secret-shaped literal in the source).
KEY_ID = "k" + hashlib.sha256(b"harness key id").hexdigest()[:19]
#: The signing half: the Bybit doc placeholder, as `test_safety.py` uses it.
PLACEHOLDER = "XXXXXXXXXX"
SKIPPED = "skipped: account not flat or run stopped"
#: What the owner does when a cleanup did not finish, spelt out here and not imported, so a
#: weakened text fails: the run's orders may still rest, and a position may still be open. The
#: run's ids carry no prefix of their own beyond `cvd-` (24 §8.3 puts a random group right after
#: it), so `orders.csv`, next to the summary, is the list of what it sent.
BY_HAND = (
    "in the demo UI cancel the run's open ETHUSDT orders (orderLinkId prefix cvd-; each is listed"
    " in orders.csv of the run's output directory) and flatten the ETHUSDT position"
)
#: The CSV files a run keeps as it goes.
_JOURNALS = ("orders", "cycles", "rest_calls")
#: The first stop reason of a run a key refusal ended: by class and code, never exchange text.
KEY_REFUSED = (
    "stopped early: SafetyRefusal: create refused (retCode 10003: AuthError (AUTH_ERROR)):"
    " stopping the run"
)
#: What the outcome says when the REST execution backfill failed.
AC2_MISSING = (
    "REST execution backfill FAILED: the AC2 number (executions seen only via REST) is missing"
)


async def _no_sleep(_: float) -> None:
    return None


def _config(tmp_path: Path, **changes: Any) -> Config:
    """Four cycles over a moment, every second one a taker, no wait for a passive fill."""
    base: dict[str, Any] = {"mode": "orders", "symbol": SYMBOL, "hours": 1e-6, "orders": 4}
    base |= {"out": tmp_path / "run", "staging": tmp_path / "staging"}
    base |= {"fill_wait_s": 0.0, "taker_every": 2}
    return Config(**(base | changes))


def _harness(venue: FakeBybit, cfg: Config) -> Harness:
    creds = EnvCredentials(Secret(KEY_ID), Secret(PLACEHOLDER))
    return Harness(
        cfg, creds, transport_factory=venue.transport, dial_fn=venue.dial, sleep=_no_sleep
    )


def _left_open(venue: FakeBybit, h: Harness) -> str:
    """One Buy limit of the run resting and a 0.01 long open, as a run that stopped leaves them."""
    link = new_link(h.account_id, "entry")
    h.links.add(link)
    venue.rest_order(link)
    venue.size = Decimal("0.01")
    return link


def _flattens(venue: FakeBybit) -> list[tuple[str, str]]:
    creates = venue.posts("/v5/order/create")
    return [(b["side"], b["qty"]) for b in creates if b.get("reduceOnly") is True]


def _written(tmp_path: Path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in tmp_path.rglob("*") if p.is_file())


def _staged(tmp_path: Path) -> set[str]:
    return {p.name for p in tmp_path.glob("staging/bybit/*/rest/*.json")}


def _cycles(h: Harness) -> list[dict[str, Any]]:
    return [r for r in h.rows if r["cycle"] >= 0]


def _signals(monkeypatch: pytest.MonkeyPatch) -> dict[int, Callable[[], None]]:
    """What `_on_signals` registers on the running loop, kept and not installed: a test then
    sends a stop request by running the callback, as the loop does on the signal."""
    registered: dict[int, Callable[[], None]] = {}

    def add(sig: int, callback: Callable[..., None], *args: Any) -> None:
        registered[sig] = functools.partial(callback, *args)

    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", add)
    return registered


def _stop_once(registered: dict[int, Callable[[], None]], sig: signal.Signals) -> None:
    """A stop request, run by the loop at its next turn."""
    asyncio.get_running_loop().call_soon(registered[sig])


def _hangup(registered: dict[int, Callable[[], None]]) -> None:
    """SIGHUP, as the loop delivers it: the callback runs at once, inside whatever is running."""
    registered[signal.SIGHUP]()


def _stop_twice(
    registered: dict[int, Callable[[], None]],
    first: signal.Signals = signal.SIGINT,
    second: signal.Signals = signal.SIGTERM,
) -> None:
    """A first stop request and a second, run by the loop at its next turn: the cancel lands where
    the run's task is then waiting."""
    _stop_once(registered, first)
    _stop_once(registered, second)


async def _run_with_signals(h: Harness) -> dict[str, Any]:
    """`run()` without its network: the handlers installed from the run's own task, then `drive`."""
    _on_signals(h)
    return await drive(h)


async def _cancel_here() -> None:
    """A stop request that cancels the running task, as the signal handler makes it; it lands at
    the next await, which is this one."""
    task = asyncio.current_task()
    assert task is not None
    task.cancel()
    await asyncio.sleep(0)


def _file(tmp_path: Path, name: str) -> list[dict[str, str]]:
    """The rows of one of the run's CSV files, as a reader of the directory finds them."""
    with (tmp_path / "run" / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


async def test_cleanup_cancels_a_resting_order_by_its_link_then_flattens(tmp_path: Path) -> None:
    """The adapter refuses an order call with no `orderLinkId`, so a cancel by `orderId` never
    left and its error skipped the flatten: the order kept resting and the position open."""
    venue = FakeBybit()
    h = _harness(venue, _config(tmp_path))
    link = _left_open(venue, h)
    await h.cleanup()
    await h.client.aclose()
    cancels = venue.posts("/v5/order/cancel")
    assert [c.get("orderLinkId") for c in cancels] == [link] and "orderId" not in cancels[0]
    assert _flattens(venue) == [("Sell", "0.01")]
    assert (venue.orders[link]["orderStatus"], venue.size) == ("Cancelled", Decimal(0))
    assert (h.notes["cleanup"], h.cleanup_ok) == (CLEAN, True)


@pytest.mark.parametrize("broken", ["refused", "raises"])
async def test_a_failed_cancel_never_skips_the_flatten(tmp_path: Path, broken: str) -> None:
    venue = FakeBybit()
    venue.refuse_cancels = (10001, "params error") if broken == "refused" else None
    venue.cancel_raises = broken == "raises"
    h = _harness(venue, _config(tmp_path))
    _left_open(venue, h)
    await h.cleanup()
    await h.client.aclose()
    assert _flattens(venue) == [("Sell", "0.01")] and venue.size == 0
    assert h.cleanup_ok is False and h.notes["cleanup"].startswith("INCOMPLETE (cancel: ")
    assert h.notes["cleanup"].endswith(f"): {BY_HAND}")


async def test_rehearsal_of_an_orders_run(tmp_path: Path) -> None:
    """The 10002 capture, then four cycles: a passive order amended and cancelled (sent twice:
    the duplicate capture), a taker filled in two parts, a cycle whose order lookup fails after
    the adapter's retries (recorded, its order cancelled, the run goes on), and a taker whose
    fill comes after the stream drops and reconnects. Then the cleanup and the outputs."""
    venue = FakeBybit()
    venue.split_fills, venue.drop_on_taker, venue.fail_lookups = True, 2, {3: 4}
    h = _harness(venue, _config(tmp_path, capture_10002=True))
    report = await drive(h)

    creates = venue.posts("/v5/order/create")
    opening = [b for b in creates if b.get("reduceOnly") is not True]
    assert len(opening) == 5  # four entries, one sent twice
    assert all(b["side"] == "Buy" and Decimal(b["stopLoss"]) < Decimal(b["price"]) for b in opening)
    assert _flattens(venue) == [("Sell", "0.010")]
    for body in venue.posts("/v5/order/amend") + venue.posts("/v5/order/cancel"):
        assert body["orderLinkId"] in h.links and "orderId" not in body

    cycles = [r for r in h.rows if r["cycle"] >= 0]
    assert [r.get("status") for r in cycles] == ["Cancelled", "Filled", None, "Filled"]
    assert (cycles[0]["amend"], cycles[0]["cancel"], cycles[2]["cancel"]) == ("0", "0", "0")
    assert cycles[2]["error"] == "retCode None: TransportError (TRANSPORT_ERROR)"
    assert (report["outcome"], h.notes["cleanup"], venue.size) == (COMPLETED, CLEAN, Decimal(0))
    assert h.notes["duplicate_order_link_id"].startswith("retCode 110072: DuplicateClientIdError")
    assert h.notes["clock_skew_10002"] == "retCode 10002: ClockDriftError (CLOCK_DRIFT)"

    stream = report["stream"]
    assert (stream["connects"], len(stream["drops"]), len(stream["live_ms"])) == (2, 1, 2)
    counts = report["cycles"]
    assert (counts["partial_fill_stream"], counts["partial_fill_rest"], counts["failed"]) == (
        2,
        0,
        1,
    )
    assert report["rest_executions"] == 5
    assert all(p["rest_only"] == {} for p in report["parity"].values())

    assert {
        "order_realtime_0_empty.json",
        "order_realtime_0_New.json",
        "position_list_0_flat.json",
        "position_list_0_open.json",
        "order_create_110072.json",
        "order_realtime_10002.json",
    } <= _staged(tmp_path)
    summary = (tmp_path / "run" / "summary.md").read_text(encoding="utf-8")
    assert "## Budget #4" in summary and "2 by the stream's `order` pushes" in summary
    executions = (tmp_path / "run" / "rest_executions.csv").read_text(encoding="utf-8")
    assert len(executions.splitlines()) == 6
    assert KEY_ID not in _written(tmp_path)


async def test_a_stop_request_reports_an_interrupted_run_and_skips_the_burst(
    tmp_path: Path,
) -> None:
    venue = FakeBybit()
    h = _harness(venue, _config(tmp_path, orders=40, capture_10018=True))
    venue.on_create = lambda n: h.stopping.set() if n == 2 else None
    report = await drive(h)
    assert report["outcome"] == INTERRUPTED and len([r for r in h.rows if r["cycle"] >= 0]) == 2
    assert (h.notes["cleanup"], h.notes["ip_limit_10018"]) == (CLEAN, SKIPPED)
    assert not [s for s in h.recorder.samples if s.op == "burst"]


async def test_the_burst_runs_last_after_a_complete_run_that_left_the_account_flat(
    tmp_path: Path,
) -> None:
    venue = FakeBybit()
    venue.limit_time_reads = 20  # the preflight's five reads, then 15 more before 10018
    h = _harness(venue, _config(tmp_path, orders=2, capture_10018=True, burst_max=50))
    report = await drive(h)
    assert report["outcome"] == COMPLETED
    assert h.notes["ip_limit_10018"] == {"sent": 50, "stopped_by": "HTTP 200"}
    assert len([s for s in h.recorder.samples if s.op == "burst"]) == 50
    assert h.recorder.samples[-1].op == "burst"


async def test_the_burst_is_skipped_when_a_fresh_read_shows_a_position(tmp_path: Path) -> None:
    venue = FakeBybit()
    h = _harness(venue, _config(tmp_path, capture_10018=True))
    h.cleanup_ok, venue.size = True, Decimal("0.01")
    await h.wrap_up(COMPLETED)
    await h.client.aclose()
    assert h.notes["ip_limit_10018"] == SKIPPED
    assert not [s for s in h.recorder.samples if s.op == "burst"]


async def test_a_cleanup_that_cannot_flatten_is_in_the_outcome_and_holds_the_burst(
    tmp_path: Path,
) -> None:
    venue = FakeBybit()
    venue.flatten_fills = False
    h = _harness(venue, _config(tmp_path, orders=2, taker_every=1, capture_10018=True))
    report = await drive(h)
    assert report["outcome"] == f"{COMPLETED}; cleanup INCOMPLETE: {BY_HAND}"
    assert h.notes["cleanup"].startswith("INCOMPLETE (flatten: SafetyRefusal: the position")
    assert (h.cleanup_ok, h.notes["ip_limit_10018"], venue.size) == (
        False,
        SKIPPED,
        Decimal("0.010"),
    )


async def test_three_failed_cycles_in_a_row_stop_the_run_and_cancel_their_orders(
    tmp_path: Path,
) -> None:
    venue = FakeBybit()
    venue.fail_lookups = {1: 4, 2: 4, 3: 4}
    h = _harness(venue, _config(tmp_path, orders=10, taker_every=0))
    report = await drive(h)
    cycles = [r for r in h.rows if r["cycle"] >= 0]
    assert report["outcome"].startswith("stopped early: SafetyRefusal: cycle failed (retCode None")
    assert [(r["error"].split(":")[1], r["cancel"]) for r in cycles] == [
        (" TransportError (TRANSPORT_ERROR)", "0")
    ] * 3
    assert h.notes["cleanup"] == CLEAN and not any(
        o["orderStatus"] == "New" for o in venue.orders.values()
    )


async def test_an_exchange_text_echoing_the_key_id_reaches_no_output_and_no_log(
    tmp_path: Path,
) -> None:
    """A 10004 retMsg echoes the signed string, key id included. From the first create on, every
    position read is refused so: the cycle stops the run (an auth refusal) and the flatten fails.
    The outcome, the notes, every file and every log line name the error by class and code."""
    venue = FakeBybit()
    echo = f'error sign! origin_string[1760630400000{KEY_ID}5000{{"category":"linear"}}]'
    venue.on_create = lambda n: setattr(venue, "refuse_positions", (10004, echo))
    h = _harness(venue, _config(tmp_path, orders=3, taker_every=0))
    with capture_logs() as logs:
        report = await drive(h)
    assert report["outcome"].startswith(
        "stopped early: SafetyRefusal: cycle failed (retCode 10004: AuthError (AUTH_ERROR))"
    )
    assert report["outcome"].endswith(f"cleanup INCOMPLETE: {BY_HAND}")
    assert "origin_string" not in report["outcome"] + json.dumps(h.notes)
    assert KEY_ID not in json.dumps(report) + _written(tmp_path) + repr(logs)


@pytest.mark.parametrize("ips", [[], ["*"], ["203.0.113.0/24"]], ids=["none", "wildcard", "range"])
async def test_a_key_without_a_host_ip_allowlist_is_refused_before_any_order(
    tmp_path: Path, ips: list[str]
) -> None:
    venue = FakeBybit(ips=ips)
    with pytest.raises(SafetyRefusal, match="IP allowlist"):
        await drive(_harness(venue, _config(tmp_path)))
    assert not [call for call in venue.calls if call[0] == "POST"]


async def test_a_soak_reports_no_budget_verdict_without_creates(tmp_path: Path) -> None:
    venue = FakeBybit()
    report = await drive(_harness(venue, _config(tmp_path, mode="soak")))
    summary = (tmp_path / "run" / "summary.md").read_text(encoding="utf-8")
    assert report["outcome"] == COMPLETED and report["budget_4"]["within_allocation"] is None
    assert "Budget #4" not in summary and "within the" not in summary
    assert "order_submit_seconds" not in summary and "partial fill" not in summary


# -- what the owner does by hand when the cleanup did not finish ---------------------------------


async def test_a_failed_open_order_read_says_what_to_cancel_and_what_to_flatten(
    tmp_path: Path,
) -> None:
    """With no read of the open orders nothing can be cancelled by link: the run's orders may still
    rest. The note says to cancel them and to flatten, not to flatten alone."""
    venue = FakeBybit()
    venue.refuse_open_orders = (10001, "params error")
    h = _harness(venue, _config(tmp_path))
    link = _left_open(venue, h)
    with capture_logs() as logs:
        await h.cleanup()
    await h.client.aclose()
    failed = {"event": "cleanup_incomplete", "failed_steps": 1, "by_hand": BY_HAND}
    failed |= {"orders_csv": str(tmp_path / "run" / "orders.csv"), "log_level": "error"}
    assert failed in logs
    assert venue.orders[link]["orderStatus"] == "New"
    assert _flattens(venue) == [("Sell", "0.01")] and venue.size == 0
    assert h.cleanup_ok is False and h.notes["cleanup"].startswith("INCOMPLETE (open orders: ")
    assert h.notes["cleanup"].endswith(f"): {BY_HAND}")


# -- the 10018 burst is for an orders run only ---------------------------------------------------


def test_a_soak_with_the_10018_burst_is_refused_when_the_config_is_built(tmp_path: Path) -> None:
    """The burst bypasses the governor and may hold the IP for ten minutes or more. Only an orders
    run can show the account flat by its own orders, so the burst never runs after a soak."""
    with pytest.raises(SafetyRefusal, match="orders mode only"):
        _config(tmp_path, mode="soak", capture_10018=True)
    assert _config(tmp_path, capture_10018=True).capture_10018
    assert not _config(tmp_path, mode="soak").capture_10018


def test_a_soak_with_the_10002_capture_is_refused_when_the_config_is_built(tmp_path: Path) -> None:
    """Only an orders run reads with a skewed timestamp: a soak would skip the capture without a
    word, and the owner would believe it was taken."""
    with pytest.raises(SafetyRefusal, match="10002 capture runs in orders mode only"):
        _config(tmp_path, mode="soak", capture_10002=True)
    assert _config(tmp_path, capture_10002=True).capture_10002
    assert not _config(tmp_path, mode="soak").capture_10002


# -- a backfill that failed is not a clean run ---------------------------------------------------


async def test_a_failed_backfill_is_marked_in_the_outcome_and_in_both_summaries(
    tmp_path: Path,
) -> None:
    """The REST backfill is the measurement behind the source-of-truth criterion (#843 AC2): the
    executions seen only through REST. With no listing there is no count, and an empty listing
    must not read as zero: the outcome (so the exit code) and both summaries say so."""
    venue = FakeBybit()
    venue.fail_executions = 99
    h = _harness(venue, _config(tmp_path, orders=2, capture_10018=True))
    report = await drive(h)

    error = "retCode None: TransportError (TRANSPORT_ERROR)"
    assert report["outcome"] == f"{COMPLETED}; {AC2_MISSING}"
    assert (report["rest_backfill_error"], report["rest_executions"]) == (error, None)
    for parity in report["parity"].values():
        assert parity["streamed"] > 0 and parity["rest_only"] is None
        assert (parity["rest_only_when"], parity["stream_only"]) == (None, None)
    assert not [s for s in h.recorder.samples if s.op == "burst"]  # not a clean run: no burst

    saved = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert saved["outcome"] == report["outcome"] and saved["rest_backfill_error"] == error
    summary = (tmp_path / "run" / "summary.md").read_text(encoding="utf-8")
    assert AC2_MISSING in summary and f"the REST backfill FAILED ({error})" in summary
    parity_section = summary.split("## Execution parity")[1].split("## Ordering")[0]
    row = next(line for line in parity_section.splitlines() if line.startswith("| execution |"))
    assert row.endswith("| n/a | n/a | n/a | n/a |")


async def test_a_stop_request_during_the_backfill_still_writes_and_marks_the_missing_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first stop request ended the run, and the second lands while the backfill runs (a
    double tap after a long soak): the outputs are still written, with the AC2 number missing."""
    venue = FakeBybit()
    h = _harness(venue, _config(tmp_path, orders=2, capture_10018=True))

    async def cut_backfill() -> dict[str, RestExecution]:
        await _cancel_here()
        return {}  # never reached: the cancel landed

    monkeypatch.setattr(h, "backfill", cut_backfill)
    main = asyncio.create_task(drive(h))
    report = await main
    assert report["outcome"] == f"{INTERRUPTED}; {AC2_MISSING}"
    assert (report["rest_backfill_error"], report["rest_executions"]) == ("CancelledError", None)
    assert h.notes["wrap_up"] == "stopped early: CancelledError"
    assert report["stop_reason"] == "stop request (cancelled)"
    assert (tmp_path / "run" / "summary.json").is_file() and main.cancelling() == 0
    assert not [s for s in h.recorder.samples if s.op == "burst"]


async def test_a_stop_request_during_the_wrap_up_makes_a_completed_run_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cycles are done and the outcome stood at `completed` when the terminal closes (SIGHUP)
    while the backfill reads. The README says a stop request ends the run `interrupted`, exit 1:
    the outcome is settled when the outputs are written, not before the wrap-up begins."""
    venue = FakeBybit()
    registered = _signals(monkeypatch)
    venue.on_get = lambda path: _hangup(registered) if path == "/v5/execution/list" else None
    h = _harness(venue, _config(tmp_path, orders=2, capture_10018=True))

    report = await asyncio.create_task(_run_with_signals(h))
    assert report["outcome"] == INTERRUPTED and h.notes["ip_limit_10018"] == SKIPPED
    assert not [s for s in h.recorder.samples if s.op == "burst"]
    saved = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert (saved["outcome"], saved["stop_reason"]) == (INTERRUPTED, "stop request (SIGHUP)")
    summary = (tmp_path / "run" / "summary.md").read_text(encoding="utf-8")
    assert ": interrupted." in summary


async def test_a_stop_request_during_the_wrap_up_keeps_what_else_was_wrong_with_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a `completed` outcome turns into `interrupted`: a cleanup that did not finish stays
    in the outcome, after the new word."""
    venue = FakeBybit()
    venue.flatten_fills = False
    registered = _signals(monkeypatch)
    venue.on_get = lambda path: _hangup(registered) if path == "/v5/execution/list" else None
    h = _harness(venue, _config(tmp_path, orders=1, taker_every=1))

    report = await asyncio.create_task(_run_with_signals(h))
    assert report["outcome"] == f"{INTERRUPTED}; cleanup INCOMPLETE: {BY_HAND}"


# -- a second Ctrl-C, SIGTERM or SIGHUP: still flatten, still write -----------------------------

_PAIRS = pytest.mark.parametrize(
    ("first", "second"),
    [
        (signal.SIGINT, signal.SIGTERM),
        (signal.SIGTERM, signal.SIGHUP),
        (signal.SIGHUP, signal.SIGINT),
    ],
    ids=["int-term", "term-hup", "hup-int"],
)


@_PAIRS
async def test_a_second_stop_request_still_flattens_and_writes_the_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first: signal.Signals, second: signal.Signals
) -> None:
    """The first stop request (SIGINT, SIGTERM or SIGHUP) ends the run between cycles; the second
    cancels the run's task where it waits, here on a fill. The run still cancels its orders,
    flattens, writes its outputs and reports `interrupted`: nothing escapes `drive`, and the
    cancellation is consumed, so what follows is an ordinary task."""
    venue = FakeBybit()
    registered = _signals(monkeypatch)
    h = _harness(venue, _config(tmp_path, orders=40, capture_10018=True))
    venue.on_create = lambda n: _stop_twice(registered, first, second) if n == 2 else None

    main = asyncio.create_task(_run_with_signals(h))
    with capture_logs() as logs:
        report = await main
    assert set(registered) == {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
    assert report["outcome"] == INTERRUPTED and len(_cycles(h)) == 2
    assert (h.notes["cleanup"], h.cleanup_ok, venue.size) == (CLEAN, True, Decimal(0))
    assert len(_flattens(venue)) == 1 and h.notes["ip_limit_10018"] == SKIPPED
    saved = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert (saved["outcome"], saved["stop_reason"]) == (INTERRUPTED, f"stop request ({first.name})")
    assert main.cancelling() == 0 and {"event": "run_cancelled", "log_level": "warning"} in logs


async def test_a_hangup_is_a_stop_request_and_not_the_end_of_the_run_where_it_stands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing the terminal, the tab, the SSH or the WSL session sends SIGHUP, whose default is to
    kill the process: a resting order and an open position stay, and nothing is written. It is a
    stop request like SIGINT and SIGTERM: the run cancels, flattens, writes and says why."""
    venue = FakeBybit()
    registered = _signals(monkeypatch)
    h = _harness(venue, _config(tmp_path, orders=40, capture_10018=True))
    venue.on_create = lambda n: _stop_once(registered, signal.SIGHUP) if n == 2 else None

    report = await asyncio.create_task(_run_with_signals(h))
    assert signal.SIGHUP in registered
    assert report["outcome"] == INTERRUPTED and len(_cycles(h)) == 2
    assert (h.notes["cleanup"], h.cleanup_ok, venue.size) == (CLEAN, True, Decimal(0))
    assert len(_flattens(venue)) == 1 and h.notes["ip_limit_10018"] == SKIPPED
    saved = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert (saved["outcome"], saved["stop_reason"]) == (INTERRUPTED, "stop request (SIGHUP)")


async def test_a_stop_request_that_cuts_the_cleanup_short_is_followed_by_one_whole_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cancel lands in the cleanup's first step, the read of the open orders: nothing was
    cancelled or flattened, and the account must not be left so. The run cleans up once more,
    whole (it is idempotent), before it writes."""
    venue = FakeBybit()
    h = _harness(venue, _config(tmp_path, orders=1, taker_every=1))  # a taker: a position is open
    reads, own_open = 0, h._own_open

    async def cut_the_first_read() -> list[str]:
        nonlocal reads
        reads += 1
        if reads == 1:
            await _cancel_here()
        return await own_open()

    monkeypatch.setattr(h, "_own_open", cut_the_first_read)
    main = asyncio.create_task(drive(h))
    report = await main
    assert (reads, report["outcome"]) == (2, INTERRUPTED)
    assert (h.notes["cleanup"], h.cleanup_ok, venue.size) == (CLEAN, True, Decimal(0))
    assert len(_flattens(venue)) == 1 and main.cancelling() == 0


async def test_a_stop_request_that_cuts_the_second_cleanup_short_aborts_and_says_what_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every read of the open orders is cut by a stop request: the cleanup, then its repeat. The
    run aborts, nothing more is written, and the account may be left open, so the log says what
    to do by hand; the cancellation itself still ends the task."""
    venue = FakeBybit()
    h = _harness(venue, _config(tmp_path, orders=1, taker_every=1))

    async def cut_every_read() -> list[str]:
        await _cancel_here()
        return []  # never reached: the cancel landed

    monkeypatch.setattr(h, "_own_open", cut_every_read)
    main = asyncio.create_task(drive(h))
    with capture_logs() as logs, pytest.raises(asyncio.CancelledError):
        await main
    aborted = {
        "event": "run_aborted",
        "by_hand": BY_HAND,
        "stop_reason": "stop request (cancelled)",
    }
    aborted |= {"orders_csv": str(tmp_path / "run" / "orders.csv"), "log_level": "error"}
    assert aborted in logs
    assert venue.size > 0 and not (tmp_path / "run" / "summary.json").exists()


async def test_a_stop_request_after_a_cleanup_that_failed_does_not_repeat_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cleanup ran and could not flatten (the venue's IOC finds nothing to hit); the cancel
    then lands in the wait that follows it. Its failure is recorded and stays so: the outcome
    carries it, and a second pass is not run."""
    venue = FakeBybit()
    venue.flatten_fills = False
    h = _harness(venue, _config(tmp_path, orders=1, taker_every=1))

    async def cut_the_trailing_wait(seconds: float) -> None:
        if seconds == 10:  # the wait for the flatten's trailing pushes, after the cleanup
            await _cancel_here()

    monkeypatch.setattr(h, "_sleep", cut_the_trailing_wait)
    main = asyncio.create_task(drive(h))
    report = await main
    assert report["outcome"] == f"{INTERRUPTED}; cleanup INCOMPLETE: {BY_HAND}"
    assert (h.cleanup_ok, len(_flattens(venue)), main.cancelling()) == (False, 1, 0)


async def test_a_second_stop_request_in_a_soak_leaves_the_account_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A soak places no order and may share its symbol with a position of the owner's: no stop
    request makes it cancel or flatten. It still writes its outputs and reports `interrupted`."""
    venue = FakeBybit()
    venue.size = Decimal("0.01")
    registered = _signals(monkeypatch)
    venue.on_get = lambda path: _stop_twice(registered) if path == "/v5/user/query-api" else None
    h = _harness(venue, _config(tmp_path, mode="soak", hours=1))

    report = await asyncio.create_task(_run_with_signals(h))
    assert report["outcome"] == INTERRUPTED and h.cleanup_ok is None
    assert venue.posts("/v5/order/create") == [] and venue.size == Decimal("0.01")
    assert (tmp_path / "run" / "summary.json").is_file()


# -- the first stop reason is kept, whatever stop request comes after it ------------------------


async def test_the_first_stop_reason_survives_a_stop_request_that_cuts_the_cleanup_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key refusal ends the run and its cleanup begins; a stop request then cancels the cleanup
    where it reads the open orders. The cancellation replaces the refusal in flight, so the
    outcome reads `interrupted`: the reason the run stopped must already be recorded, and the
    summaries carry it, by class and code and never by the exchange's text."""
    venue = FakeBybit()
    venue.refuse_creates = lambda n: (10003, "text the exchange wrote")
    h = _harness(venue, _config(tmp_path, orders=10, taker_every=0))
    reads, own_open = 0, h._own_open

    async def cut_the_first_read() -> list[str]:
        nonlocal reads
        reads += 1
        if reads == 1:
            await _cancel_here()
        return await own_open()

    monkeypatch.setattr(h, "_own_open", cut_the_first_read)
    main = asyncio.create_task(drive(h))
    report = await main
    assert (reads, report["outcome"], h.cleanup_ok) == (2, INTERRUPTED, True)
    assert report["stop_reason"] == KEY_REFUSED
    saved = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert (saved["outcome"], saved["stop_reason"]) == (INTERRUPTED, KEY_REFUSED)
    summary = (tmp_path / "run" / "summary.md").read_text(encoding="utf-8")
    assert f"First stop reason: {KEY_REFUSED}." in summary
    assert "text the exchange wrote" not in report["stop_reason"]


async def test_a_failure_that_stopped_the_run_is_named_once_in_the_summary(tmp_path: Path) -> None:
    """With no stop request after it the reason is the outcome: the summary says it once."""
    venue = FakeBybit()
    venue.refuse_creates = lambda n: (10003, "refused")
    h = _harness(venue, _config(tmp_path, orders=10, taker_every=0))
    report = await drive(h)
    assert (report["outcome"], report["stop_reason"]) == (KEY_REFUSED, KEY_REFUSED)
    summary = (tmp_path / "run" / "summary.md").read_text(encoding="utf-8")
    assert "First stop reason" not in summary and summary.count(KEY_REFUSED) == 1


@pytest.mark.parametrize("mode", ["orders", "soak"])
async def test_a_stream_that_refuses_its_auth_is_the_stop_reason_in_either_mode(
    tmp_path: Path, mode: str
) -> None:
    """The refusal comes from the stream's own task, before any cycle runs: it is the reason, named
    by its rule, and `summary.json` carries it."""
    venue = FakeBybit()
    venue.refuse_ws_auth = True
    h = _harness(venue, _config(tmp_path, mode=mode))
    report = await drive(h)
    reason = "stopped early: StreamAuthRefused: the private stream refused auth"
    assert (report["outcome"], report["stop_reason"]) == (reason, reason)
    saved = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert saved["stop_reason"] == reason and venue.posts("/v5/order/create") == []


async def test_a_run_nothing_stopped_has_no_stop_reason(tmp_path: Path) -> None:
    report = await drive(_harness(FakeBybit(), _config(tmp_path, orders=2)))
    assert (report["outcome"], report["stop_reason"]) == (COMPLETED, None)


async def test_only_the_first_stop_reason_is_kept(tmp_path: Path) -> None:
    h = _harness(FakeBybit(), _config(tmp_path))
    h.note_stop("stop request (SIGHUP)")
    h.note_stop(KEY_REFUSED)
    await h.client.aclose()
    assert h.stop_reason == "stop request (SIGHUP)"


# -- the run's record is on disk as it goes, so a killed run still leaves it --------------------


async def test_the_record_of_a_run_is_on_disk_while_the_run_goes_on(tmp_path: Path) -> None:
    """When the venue holds the second create, the process could be killed: the second order is
    already in orders.csv (written before the request goes out), the first cycle's outcome is in
    cycles.csv, and every call answered so far is in rest_calls.csv."""
    venue = FakeBybit()
    h = _harness(venue, _config(tmp_path, orders=3, taker_every=0))
    seen: dict[str, Any] = {}

    def killed_now(n: int) -> None:
        if n == 2:
            seen["in_flight"] = venue.posts("/v5/order/create")[-1]["orderLinkId"]
            seen["answered"] = len(h.recorder.samples)
            seen.update({name: _file(tmp_path, f"{name}.csv") for name in _JOURNALS})

    venue.on_create = killed_now
    await drive(h)

    first, second = (r["order_link_id"] for r in _cycles(h)[:2])
    assert seen["in_flight"] == second
    assert [r["order_link_id"] for r in seen["orders"]] == [first, second]
    assert [r["order_link_id"] for r in seen["cycles"]] == [first]
    assert len(seen["rest_calls"]) == seen["answered"]
    assert {r["order_link_id"] for r in _file(tmp_path, "orders.csv")} == h.links


async def test_an_order_row_names_the_order_the_native_stop_and_the_symbol(tmp_path: Path) -> None:
    venue = FakeBybit()
    h = _harness(venue, _config(tmp_path, orders=2, taker_every=2))
    await drive(h)
    passive, taker = (r for r in _file(tmp_path, "orders.csv") if r["cycle"] != "-1")
    assert (passive["cycle"], passive["kind"], taker["cycle"], taker["kind"]) == (
        "0",
        "passive",
        "1",
        "taker",
    )
    for row in (passive, taker):
        assert (row["symbol"], row["side"]) == (SYMBOL, "Buy")
        assert Decimal(row["stop_loss"]) < Decimal(row["price"]) and Decimal(row["qty"]) > 0
        assert int(row["created_ms"]) > 0 and row["order_link_id"] in h.links


async def test_an_aborted_run_leaves_its_orders_and_calls_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both cleanups are cut by a stop request: the run aborts and writes no summary, yet the order
    it sent, the cycle it ended and every call it made are on disk for the owner."""
    venue = FakeBybit()
    h = _harness(venue, _config(tmp_path, orders=1, taker_every=1))

    async def cut_every_read() -> list[str]:
        await _cancel_here()
        return []  # never reached: the cancel landed

    monkeypatch.setattr(h, "_own_open", cut_every_read)
    main = asyncio.create_task(drive(h))
    with capture_logs(), pytest.raises(asyncio.CancelledError):
        await main
    assert not (tmp_path / "run" / "summary.json").exists()
    link = _cycles(h)[0]["order_link_id"]
    assert [r["order_link_id"] for r in _file(tmp_path, "orders.csv")] == [link]
    assert [r["order_link_id"] for r in _file(tmp_path, "cycles.csv")] == [link]
    calls = _file(tmp_path, "rest_calls.csv")
    assert len(calls) == len(h.recorder.samples)
    assert {"create", "duplicate"} <= {r["op"] for r in calls}


async def test_a_flatten_is_in_orders_csv_before_it_is_sent(tmp_path: Path) -> None:
    venue = FakeBybit()
    h = _harness(venue, _config(tmp_path))
    _left_open(venue, h)
    seen: dict[str, Any] = {}
    venue.on_create = lambda n: seen.update(rows=_file(tmp_path, "orders.csv"))
    await h.cleanup()
    await h.client.aclose()
    flatten = seen["rows"][-1]
    assert (flatten["cycle"], flatten["kind"], flatten["side"], flatten["qty"]) == (
        "-1",
        "flatten:end",
        "Sell",
        "0.01",
    )
    assert flatten["order_link_id"] in h.links and flatten["stop_loss"] == ""


async def test_no_opening_order_is_sent_when_its_record_cannot_be_written(tmp_path: Path) -> None:
    """No row, no order: the record is what the owner has if the run is killed. The run stops, and
    its cleanup still runs."""
    venue = FakeBybit()
    (tmp_path / "run" / "orders.csv").mkdir(parents=True)  # nothing can be appended there
    h = _harness(venue, _config(tmp_path))
    with capture_logs() as logs:
        report = await drive(h)
    opening = [b for b in venue.posts("/v5/order/create") if b.get("reduceOnly") is not True]
    assert opening == []
    assert report["outcome"] == (
        "stopped early: SafetyRefusal: the order record cannot be written: no order is sent"
    )
    assert h.notes["cleanup"] == CLEAN
    failed = [entry for entry in logs if entry["event"] == "journal_unwritable"]
    assert [(e["file"], e["log_level"]) for e in failed] == [("orders.csv", "error")]


async def test_a_flatten_goes_out_even_when_its_record_cannot_be_written(tmp_path: Path) -> None:
    """Closing the position never waits for the record of the order that closes it."""
    venue = FakeBybit()
    (tmp_path / "run" / "orders.csv").mkdir(parents=True)
    h = _harness(venue, _config(tmp_path))
    _left_open(venue, h)
    with capture_logs():
        await h.cleanup()
    await h.client.aclose()
    assert _flattens(venue) == [("Sell", "0.01")] and venue.size == 0
    assert (h.notes["cleanup"], h.cleanup_ok) == (CLEAN, True)


async def test_every_field_of_a_cycle_row_is_a_column_of_cycles_csv(tmp_path: Path) -> None:
    """A field outside the fixed columns would be dropped from the file: the rows of a run that
    uses every field (an error, an amend, a cancel, a flatten) all fit."""
    venue = FakeBybit()
    venue.split_fills, venue.fail_lookups = True, {3: 4}
    h = _harness(venue, _config(tmp_path))
    await drive(h)
    assert set().union(*h.rows) <= set(CYCLE_COLUMNS) and {"error", "amend"} <= set().union(*h.rows)
    assert [r["order_link_id"] for r in _file(tmp_path, "cycles.csv")] == [
        r["order_link_id"] for r in h.rows
    ]
    assert set(_file(tmp_path, "orders.csv")[0]) == set(ORDER_COLUMNS)


async def test_the_retention_probe_looks_up_the_orders_an_earlier_run_listed(
    tmp_path: Path,
) -> None:
    """`orders.csv` is the file the probe reads: `cycle`, `order_link_id` and `created_ms` of each
    order an earlier run sent, its flatten left out."""
    venue = FakeBybit()
    await drive(_harness(venue, _config(tmp_path, orders=3)))
    earlier = tmp_path / "run" / "orders.csv"
    (flatten,) = [r["order_link_id"] for r in _file(tmp_path, "orders.csv") if r["cycle"] == "-1"]
    asked = len(venue.calls)

    probe = _harness(venue, _config(tmp_path / "later", orders=1, retention_probe=earlier))
    await drive(probe)
    found = probe.notes["demo_retention"]
    assert [entry["found"] for entry in found] == [True] * 4
    assert all(0 <= entry["age_days"] < 1 for entry in found)
    looked_up = {p["orderLinkId"] for method, _, p in venue.calls[asked:] if "orderLinkId" in p}
    assert flatten not in looked_up  # a flatten is listed, and no sample of the probe


async def test_the_retention_probe_skips_a_row_the_leak_check_withheld(tmp_path: Path) -> None:
    """A journal row that failed the leak check is one line naming the failed checks, in place of
    the row: it has no order id, and the probe must not stop on it."""
    venue = FakeBybit()
    await drive(_harness(venue, _config(tmp_path, orders=2)))
    earlier = tmp_path / "run" / "orders.csv"
    with earlier.open("a", encoding="utf-8", newline="") as stream:
        stream.write("withheld by the leak check: key-shape\r\n")

    probe = _harness(venue, _config(tmp_path / "later", orders=1, retention_probe=earlier))
    await drive(probe)
    assert [entry["found"] for entry in probe.notes["demo_retention"]] == [True] * 4
    assert "wrap_up" not in probe.notes


# -- the duplicate capture follows the first accepted create ------------------------------------


@pytest.mark.parametrize(
    ("code", "text"),
    [(110007, "insufficient balance"), (110072, "OrderLinkedID is duplicate")],
    ids=["refused", "unresolved"],
)
async def test_a_first_create_that_was_refused_or_is_unresolved_leaves_the_duplicate_to_the_next(
    tmp_path: Path, code: int, text: str
) -> None:
    """The duplicate capture re-sends an order the venue holds, to see its refusal. A refused or
    unresolved first create left nothing to duplicate: sending it again would only retry it, and
    the note would read `accepted`. The capture waits for the next cycle whose create is accepted,
    and only that cycle's order is sent twice."""
    venue = FakeBybit()
    venue.refuse_creates = lambda n: (code, text) if n == 1 else None
    h = _harness(venue, _config(tmp_path, orders=3, taker_every=0))
    report = await drive(h)
    first, second, third = (r["order_link_id"] for r in _cycles(h))
    sent = [b["orderLinkId"] for b in venue.posts("/v5/order/create")]
    assert (sent.count(first), sent.count(second), sent.count(third)) == (1, 2, 1)
    assert h.notes["duplicate_order_link_id"].startswith("retCode 110072: DuplicateClientIdError")
    assert report["outcome"] == COMPLETED


async def test_the_duplicate_is_captured_once_in_a_run(tmp_path: Path) -> None:
    venue = FakeBybit()
    h = _harness(venue, _config(tmp_path, orders=3, taker_every=0))
    await drive(h)
    sent = [b["orderLinkId"] for b in venue.posts("/v5/order/create")]
    assert sorted(sent.count(r["order_link_id"]) for r in _cycles(h)) == [1, 1, 2]
    assert sent[1] == sent[0]  # the first accepted create is the one that is sent twice


async def test_a_run_with_no_accepted_create_says_the_duplicate_was_not_captured(
    tmp_path: Path,
) -> None:
    """The error shape of a duplicate `orderLinkId` is an acceptance criterion: a run that could
    not capture it says so, in the notes and in `summary.md`, and does not leave it silent."""
    venue = FakeBybit()
    venue.refuse_creates = lambda n: (110007, "insufficient balance")
    h = _harness(venue, _config(tmp_path, orders=2, taker_every=0))
    report = await drive(h)
    note = "not captured (no cycle had an accepted create: 2 ran)"
    assert report["outcome"] == COMPLETED and h.notes["duplicate_order_link_id"] == note
    saved = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert saved["notes"]["duplicate_order_link_id"] == note
    summary = (tmp_path / "run" / "summary.md").read_text(encoding="utf-8")
    assert f"duplicate_order_link_id: {note}" in summary


async def test_a_run_that_stops_before_its_first_cycle_says_the_duplicate_was_not_captured(
    tmp_path: Path,
) -> None:
    venue = FakeBybit()
    h = _harness(venue, _config(tmp_path))
    h.stopping.set()
    report = await drive(h)
    assert report["outcome"] == INTERRUPTED
    assert h.notes["duplicate_order_link_id"] == "not captured (no cycle ran)"


async def test_a_stop_request_between_the_create_and_its_duplicate_is_said_in_the_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue = FakeBybit()
    h = _harness(venue, _config(tmp_path, orders=1, taker_every=0))
    post = h._post

    async def cut_the_duplicate(
        op: str, path: str, body: dict[str, Any]
    ) -> tuple[ExchangeError | None, float]:
        if op == "duplicate":
            await _cancel_here()
        return await post(op, path, body)

    monkeypatch.setattr(h, "_post", cut_the_duplicate)
    report = await asyncio.create_task(drive(h))
    assert report["outcome"] == INTERRUPTED
    note = "not captured (the run ended before the duplicate was sent)"
    assert h.notes["duplicate_order_link_id"] == note


async def test_a_soak_has_no_duplicate_capture_to_miss(tmp_path: Path) -> None:
    h = _harness(FakeBybit(), _config(tmp_path, mode="soak"))
    await drive(h)
    assert "duplicate_order_link_id" not in h.notes


# -- the guard rails that stop a run -------------------------------------------------------------

_SYSTEMIC = pytest.mark.parametrize(
    ("code", "error"),
    [
        (10003, "AuthError (AUTH_ERROR)"),
        (10002, "ClockDriftError (CLOCK_DRIFT)"),
        (10006, "RateLimitError (RATE_LIMITED)"),
    ],
    ids=["key", "clock", "rate"],
)


@_SYSTEMIC
async def test_a_key_clock_or_rate_refusal_of_a_create_stops_the_run_at_the_first(
    tmp_path: Path, code: int, error: str
) -> None:
    venue = FakeBybit()
    venue.refuse_creates = lambda n: (code, "refused")
    h = _harness(venue, _config(tmp_path, orders=10, taker_every=0))
    report = await drive(h)
    assert report["outcome"].startswith(
        f"stopped early: SafetyRefusal: create refused (retCode {code}: {error}): stopping the run"
    )
    assert [r["create"] for r in _cycles(h)] == [str(code)]


async def test_three_failed_creates_in_a_row_stop_the_run(tmp_path: Path) -> None:
    venue = FakeBybit()
    venue.refuse_creates = lambda n: (110007, "insufficient balance")
    h = _harness(venue, _config(tmp_path, orders=10, taker_every=0))
    report = await drive(h)
    assert report["outcome"].startswith(
        "stopped early: SafetyRefusal: create refused "
        "(retCode 110007: InsufficientMarginError (INSUFFICIENT_MARGIN)): stopping the run"
    )
    assert [r["create"] for r in _cycles(h)] == ["110007"] * 3


async def test_an_accepted_create_resets_the_count_of_failed_creates(tmp_path: Path) -> None:
    """Two failed creates, one accepted, two failed: never three in a row, so the run goes on."""
    venue = FakeBybit()
    venue.refuse_creates = lambda n: None if n % 3 == 0 else (110007, "insufficient balance")
    h = _harness(venue, _config(tmp_path, orders=6, taker_every=0))
    report = await drive(h)
    assert report["outcome"] == COMPLETED
    assert [r["create"] for r in _cycles(h)] == ["110007", "110007", "0"] * 2


async def test_a_duplicate_id_reply_counts_as_an_accepted_create(tmp_path: Path) -> None:
    """A duplicate-id refusal means the venue holds the order: it resets the count too."""
    venue = FakeBybit()
    plan = {1: (110007, "x"), 2: (110007, "x"), 3: (110072, "OrderLinkedID is duplicate")}
    venue.refuse_creates = lambda n: plan.get(n) or ((110007, "x") if n in (4, 5) else None)
    h = _harness(venue, _config(tmp_path, orders=6, taker_every=0))
    report = await drive(h)
    assert report["outcome"] == COMPLETED
    created = ["110007", "110007", "110072", "110007", "110007", "0"]
    assert [r["create"] for r in _cycles(h)] == created


async def test_failed_cycles_in_a_row_are_counted_from_the_last_good_cycle(tmp_path: Path) -> None:
    """Cycles 1, 2, 4 and 5 end on a failed read after the adapter's retries, 3 and 6 are good:
    four failures, never three in a row, so the run completes."""
    venue = FakeBybit()
    venue.fail_lookups = {1: 4, 2: 4, 4: 4, 5: 4}
    h = _harness(venue, _config(tmp_path, orders=6, taker_every=0))
    report = await drive(h)
    assert report["outcome"] == COMPLETED
    assert ["error" in r for r in _cycles(h)] == [True, True, False, True, True, False]


@_SYSTEMIC
async def test_a_key_clock_or_rate_refusal_ends_the_run_at_the_first_failed_cycle(
    tmp_path: Path, code: int, error: str
) -> None:
    """The first cycle is fine; from its create on every position read is refused, so the second
    cycle's exposure read fails with a refusal no further cycle may retry."""
    venue = FakeBybit()
    venue.on_create = lambda n: setattr(venue, "refuse_positions", (code, "refused"))
    h = _harness(venue, _config(tmp_path, orders=10, taker_every=0))
    report = await drive(h)
    assert report["outcome"].startswith(
        f"stopped early: SafetyRefusal: cycle failed (retCode {code}: {error}): stopping the run"
    )
    assert [r.get("error") for r in _cycles(h)] == [None, f"retCode {code}: {error}"]
