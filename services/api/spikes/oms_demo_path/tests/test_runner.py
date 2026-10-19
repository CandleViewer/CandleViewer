"""The harness against the in-memory venue (`venue.py`): no network and no real waits.

The venue's REST runs under the harness's own `GuardedTransport`, so every guard rail stays in the
path, and the private stream is the venue's fake socket. Each test drives a public step (`drive`,
`cleanup`, `wrap_up`) and reads what reached the venue and what the run wrote.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.secrets import Secret
from spikes.oms_demo_path.runner import CLEAN, COMPLETED, INTERRUPTED, Config, Harness, drive
from spikes.oms_demo_path.safety import EnvCredentials, SafetyRefusal, new_link

from .venue import SYMBOL, FakeBybit

#: The run's key id: key-shaped, derived at run time (no secret-shaped literal in the source).
KEY_ID = "k" + hashlib.sha256(b"harness key id").hexdigest()[:19]
#: The signing half: the Bybit doc placeholder, as `test_safety.py` uses it.
PLACEHOLDER = "XXXXXXXXXX"
SKIPPED = "skipped: account not flat or run stopped"


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
    assert report["outcome"] == f"{COMPLETED}; cleanup INCOMPLETE: flatten in the demo UI"
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
    assert report["outcome"].endswith("cleanup INCOMPLETE: flatten in the demo UI")
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
