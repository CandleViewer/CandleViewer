"""The harness against the in-memory venue (`venue.py`): no network and no real waits.

The venue's REST runs under the harness's own `GuardedTransport`, so every guard rail stays in the
path, and the private stream is the venue's fake socket. Each test drives a public step (`drive`,
`cleanup`, `wrap_up`) and reads what reached the venue and what the run wrote.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import signal
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.secrets import Secret
from spikes.oms_demo_path.runner import (
    CLEAN,
    COMPLETED,
    INTERRUPTED,
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
#: weakened text fails: the run's orders may still rest, and a position may still be open.
BY_HAND = (
    "in the demo UI cancel the run's open ETHUSDT orders (orderLinkId prefix cvd-)"
    " and flatten the ETHUSDT position"
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

    def add(sig: int, callback: Callable[[], None]) -> None:
        registered[sig] = callback

    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", add)
    return registered


def _stop_twice(registered: dict[int, Callable[[], None]]) -> None:
    """A first stop request (SIGINT) and a second (SIGTERM), run by the loop at its next turn: the
    cancel lands where the run's task is then waiting."""
    loop = asyncio.get_running_loop()
    loop.call_soon(registered[signal.SIGINT])
    loop.call_soon(registered[signal.SIGTERM])


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
    assert failed | {"log_level": "error"} in logs
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
    assert report["outcome"] == f"{COMPLETED}; {AC2_MISSING}"
    assert (report["rest_backfill_error"], report["rest_executions"]) == ("CancelledError", None)
    assert h.notes["wrap_up"] == "stopped early: CancelledError"
    assert (tmp_path / "run" / "summary.json").is_file() and main.cancelling() == 0
    assert not [s for s in h.recorder.samples if s.op == "burst"]


# -- a second Ctrl-C or SIGTERM: still flatten, still write -------------------------------------


async def test_a_second_stop_request_still_flattens_and_writes_the_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first stop request (SIGINT) ends the run between cycles; the second (SIGTERM) cancels
    the run's task where it waits, here on a fill. The run still cancels its orders, flattens,
    writes its outputs and reports `interrupted`: nothing escapes `drive`, and the cancellation
    is consumed, so what follows is an ordinary task."""
    venue = FakeBybit()
    registered = _signals(monkeypatch)
    h = _harness(venue, _config(tmp_path, orders=40, capture_10018=True))
    venue.on_create = lambda n: _stop_twice(registered) if n == 2 else None

    main = asyncio.create_task(_run_with_signals(h))
    with capture_logs() as logs:
        report = await main
    assert set(registered) == {signal.SIGINT, signal.SIGTERM}
    assert report["outcome"] == INTERRUPTED and len(_cycles(h)) == 2
    assert (h.notes["cleanup"], h.cleanup_ok, venue.size) == (CLEAN, True, Decimal(0))
    assert len(_flattens(venue)) == 1 and h.notes["ip_limit_10018"] == SKIPPED
    saved = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert saved["outcome"] == INTERRUPTED
    assert main.cancelling() == 0 and {"event": "run_cancelled", "log_level": "warning"} in logs


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
    assert {"event": "run_aborted", "by_hand": BY_HAND, "log_level": "error"} in logs
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


# -- the duplicate capture follows an accepted first create only ---------------------------------


async def test_a_rejected_first_create_is_not_sent_again_as_the_duplicate_capture(
    tmp_path: Path,
) -> None:
    """The duplicate capture re-sends an order the venue holds, to see its refusal. A rejected
    first create left nothing to duplicate: sending it again would only retry it, and the note
    would read `accepted`."""
    venue = FakeBybit()
    venue.refuse_creates = lambda n: (110007, "insufficient balance") if n == 1 else None
    h = _harness(venue, _config(tmp_path, orders=2, taker_every=0))
    report = await drive(h)
    first = _cycles(h)[0]["order_link_id"]
    assert [b["orderLinkId"] for b in venue.posts("/v5/order/create")].count(first) == 1
    assert "duplicate_order_link_id" not in h.notes
    assert [r["create"] for r in _cycles(h)] == ["110007", "0"] and report["outcome"] == COMPLETED


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
