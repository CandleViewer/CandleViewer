"""E17-T06 (#571, slice D3): the series that wait on #412's flag-on pipeline, aggregated per
process (ruling D6; `20-architecture.md` section 12.1). With `CV_WS_BACKPRESSURE_ENABLED` on:

- a throttle window of n >= 2 source updates that leaves as one frame adds n - 1 to
  `cv_ws_conflated_total{topic}` under its family, and observes n in `cv_ws_coalesced_updates`;
- a connection counts under its 23 section 8.3 class in `cv_ws_connection_class{state}` from its
  first `auth_ok` (`attach`) to its teardown (`release`), moved on each class change, and never
  again once released;
- each RTT probe sample, answered or retired, is one `cv_ws_rtt_seconds` observation;
- each classification observes the depth it read in `cv_ws_queue_bytes` and `cv_ws_queue_frames`:
  depth and class are read when the connection's writer runs, so a parked writer takes no sample.

With the flag off none of them moves. Each read is one collect of the default registry (a scrape's
view) that names the series rather than importing them, so on the source before this slice every
test fails on an assertion, none on an import.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from prometheus_client import REGISTRY
from prometheus_client.metrics_core import Metric

from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.coalescing import MERGED_FAMILIES
from candleviewer.ws.metrics import CV_WS_NAMES
from candleviewer.ws.pacing import PONG_TIMEOUT_S, ConnectionClass, RttProbe
from tests.unit.ws.test_pacing import _COLUMN, _bid
from tests.unit.ws.test_pacing import _conn as _paced
from tests.unit.ws.test_pacing import _sub as _subscribed
from tests.unit.ws.test_pipeline_invalidation import _connected
from tests.unit.ws.test_pipeline_ladder import _attached, _structured
from tests.unit.ws.test_pipeline_outbound import (
    _BOOK,
    _ENCODINGS,
    _d,
    _overflow,
    _pipe,
    _Rig,
    _Wire,
)
from tests.unit.ws.test_pipeline_pacing import _TRADES, _pacer, _print
from tests.unit.ws.test_pipeline_quality import _HEATMAP, _at, _turn

CONFLATED, COALESCED = "cv_ws_conflated_total", "cv_ws_coalesced_updates"
CLASS, RTT = "cv_ws_connection_class", "cv_ws_rtt_seconds"
QUEUE_BYTES, QUEUE_FRAMES = "cv_ws_queue_bytes", "cv_ws_queue_frames"
NAMES = (CONFLATED, COALESCED, CLASS, RTT, QUEUE_BYTES, QUEUE_FRAMES)
HISTOGRAMS = (COALESCED, RTT, QUEUE_BYTES, QUEUE_FRAMES)
#: The two labelled series, each with its label and closed value set; the histograms have none.
CLOSED = {
    CONFLATED: ("topic", MERGED_FAMILIES),
    CLASS: ("state", frozenset(c.value for c in ConnectionClass)),
}
_API_ROOT = Path(__file__).resolve().parents[3]
_ARCH = Path(__file__).resolve().parents[5] / "docs" / "plan" / "20-architecture.md"

#: One sample: its name and its one label's value ("" for none). Buckets are read apart.
Sample = tuple[str, str]


def _families() -> list[Metric]:
    """The six families, as one scrape collects them."""
    names = {name.removesuffix("_total") for name in NAMES}
    return [family for family in REGISTRY.collect() if family.name in names]


def _read() -> dict[Sample, float]:
    """Every sample of the six series but the buckets and `_created`, in one collect."""
    return {
        (s.name, next(iter(s.labels.values()), "")): s.value
        for family in _families()
        for s in family.samples
        if not s.name.endswith(("_bucket", "_created"))
    }


def _moved(before: dict[Sample, float]) -> dict[Sample, float]:
    """What moved since `before`, sample by sample."""
    return {k: v - before.get(k, 0.0) for k, v in _read().items() if v != before.get(k, 0.0)}


def _of(name: str, before: dict[Sample, float]) -> dict[str, float]:
    """What moved in one labelled series since `before`, by label value."""
    return {label: v for (sample, label), v in _moved(before).items() if sample == name}


def _buckets(name: str) -> dict[str, float]:
    """One histogram's cumulative bucket counts, by `le`."""
    return {
        s.labels["le"]: s.value
        for family in _families()
        if family.name == name
        for s in family.samples
        if s.name == f"{name}_bucket"
    }


# -- registered at import, bounded ----------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_each_series_is_live_exported_and_served_once_as_catalogued(name: str) -> None:
    """Served once, as the catalogue declares it (kind, HELP, labels, buckets) and re-exported on
    the app registry (`CV_WS_NAMES`); `max_series` is its closed label set's size, or 1."""
    spec = next((s for s in CATALOGUE if s.name == name), None)
    assert spec is not None, name
    assert (spec.status, spec.owner_epic, spec.exported) == ("live", "E17", True)
    assert name in CV_WS_NAMES
    [family] = [f for f in _families() if f.name == name.removesuffix("_total")]
    assert (family.type, family.documentation) == (spec.kind, spec.help)
    assert {k for s in family.samples for k in s.labels} - {"le"} == set(spec.labels)
    closed = CLOSED.get(name)
    assert spec.max_series == (1 if closed is None else len(closed[1]))
    if spec.kind == "histogram":
        assert spec.buckets is not None
        edges = sorted(float(le) for le in _buckets(name))
        assert edges == [*map(float, spec.buckets), math.inf]


_PROBE = """
import json
import sys

sys.modules["candleviewer.ws.gateway"] = None  # export_ws_metrics alone must serve them
from candleviewer.observability.metrics import CollectorRegistry
from candleviewer.ws.metrics import export_ws_metrics

scraped = CollectorRegistry()
export_ws_metrics(scraped, env="demo")
names = {%s}
print(json.dumps(sorted(
    [s.name, next((v for k, v in s.labels.items() if k != "env"), ""), s.value]
    for f in scraped.collect() if f.name in names for s in f.samples
    if not s.name.endswith(("_bucket", "_created"))
)))
"""


def test_a_new_process_serves_each_closed_label_value_at_zero_and_no_other() -> None:
    """Bound at import: the first scrape of a new process (`export_ws_metrics` alone; the gateway
    is never imported) already holds every family with a merge rule under `topic` and every class
    under `state` at 0, and the four histograms at 0, so `increase()` sees the first event after a
    restart. No other label value is a series: no symbol, user, channel or connection. The
    planned `ws_conflated_total` was promoted to `cv_ws_conflated_total`, not kept beside it."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(_API_ROOT)
    names = ", ".join(repr(name.removesuffix("_total")) for name in NAMES)
    done = subprocess.run(  # noqa: S603 -- fixed argv: this interpreter and a literal probe
        [sys.executable, "-c", _PROBE % names],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=_API_ROOT,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    expected = sorted(
        [(CONFLATED, family, 0.0) for family in MERGED_FAMILIES]
        + [(CLASS, cls.value, 0.0) for cls in ConnectionClass]
        + [(f"{name}_{part}", "", 0.0) for name in HISTOGRAMS for part in ("count", "sum")]
    )
    assert [tuple(row) for row in json.loads(done.stdout)] == expected
    assert "ws_conflated_total" not in {s.name for s in CATALOGUE}


# -- a merged window, as it leaves (`Pacer._flush`) -----------------------------------------------


def _column(t_ms: int) -> dict[str, Any]:
    return {"symbol": "BTCUSDT", "time_bucket_ms": 500, "columns": [{**_COLUMN, "t_ms": t_ms}]}


@pytest.mark.parametrize(
    ("ch", "updates", "n"),
    [
        (_BOOK, [_bid(price) for price in ("100", "101", "102", "103")], 3),
        (_HEATMAP, [_column(t_ms) for t_ms in (0, 500, 1000)], 2),
    ],
    ids=["book", "heatmap"],
)
def test_a_merged_window_counts_n_less_one_under_its_family_and_observes_n(
    ch: str, updates: list[dict[str, Any]], n: int
) -> None:
    """The first update after a quiet window leaves at once, alone: nothing to count. The rest
    merge and leave as one frame when the window closes, which a book frame discloses as
    `coalesced_count` n and a heatmap frame cannot (its payload has no such field, 23 section
    8.2): n - 1 under the window's own family, and one observation of n, in each bucket from the
    first edge at or above n."""
    conn, pacer = _paced()
    sub = _subscribed(conn, ch)
    before, buckets = _read(), _buckets(COALESCED)
    for update in updates:
        pacer.offer(sub, update)
    pacer.tick(101.0)
    [_, window] = conn.take()
    assert window["p"].get("coalesced_count") == (n if ch == _BOOK else None)
    assert _moved(before) == pytest.approx(
        {
            (CONFLATED, ch.split(".", 1)[0]): n - 1,
            (f"{COALESCED}_count", ""): 1,
            (f"{COALESCED}_sum", ""): n,
        }
    )
    after = _buckets(COALESCED)
    assert {le for le in after if after[le] != buckets[le]} == {
        le for le in buckets if float(le) >= n
    }


@pytest.mark.parametrize("case", ["lone", "appended", "whole_frames", "suppressed"])
def test_a_window_that_merges_nothing_or_never_leaves_counts_nothing(case: str) -> None:
    """A lone update (count 1); trades, appended and never merged (a window of them is one frame of
    count 1); a book a healthy client asked not to coalesce (`coalesce: false`: whole frames); and a
    merged window the emitter suppresses, its subscription paused before it closed: the client got
    no frame, so nothing was conflated into one."""
    conn, pacer = _paced()
    opts = {"coalesce": False} if case == "whole_frames" else {}
    sub = _subscribed(conn, _TRADES if case == "appended" else _BOOK, **opts)
    updates = [
        {"symbol": "BTCUSDT", "trades": [_print(i)]} if case == "appended" else _bid(f"10{i}")
        for i in range(1 if case == "lone" else 3)
    ]
    before = _read()
    assert (CONFLATED, "book") in before  # served: an empty move below is not vacuous
    for update in updates:
        pacer.offer(sub, update)
    if case == "suppressed":
        sub.effective["paused"] = True
    pacer.tick(101.0)
    expected = {"lone": [1], "appended": [1, 1], "whole_frames": [1, 1, 1], "suppressed": [1]}
    assert [f["p"].get("coalesced_count", 1) for f in conn.take()] == expected[case]
    assert _moved(before) == {}


# -- the class gauge, from `attach` to `release` (`ConnectionPipeline`) ---------------------------


def test_a_connection_counts_under_its_class_from_attach_to_release() -> None:
    """A socket that never authenticates is never counted (no `attach`). From `attach` it counts
    as `healthy`; a 200 ms RTT moves it to `lagging` at once and two 10 ms samples back to
    `healthy` (the section 8.3 hysteresis); `release` takes it out once, however often it runs."""
    before = _read()
    unattached, _ = _pipe()
    unattached.release()
    assert (CLASS, "healthy") in before and _of(CLASS, before) == {}
    pipe, _, _ = _attached()
    assert _of(CLASS, before) == {"healthy": 1}
    _, [probe] = _turn(pipe, 1.0)  # no sample yet: healthy
    pipe.pong(probe, 1.2)
    _, [probe] = _turn(pipe, 2.0)  # 200 ms: lagging, at once
    assert _of(CLASS, before) == {"lagging": 1}
    for now in (3.0, 4.0):  # two 10 ms samples: healthy after the second
        pipe.pong(probe, now - 0.99)
        _, [probe] = _turn(pipe, now)
        assert _of(CLASS, before) == ({"lagging": 1} if now == 3.0 else {"healthy": 1})
    pipe.release()
    pipe.release()
    assert _of(CLASS, before) == {}


def test_a_released_pipeline_is_not_counted_or_sampled_again() -> None:
    """`release` is final, so nothing after it moves a series (the gateway ends the reader and
    joins the writer first: this is the class's own invariant, not the teardown order's). A writer
    turn classifies nothing: the connection does not come back into `cv_ws_connection_class`, no
    depth is observed, and the probe still out is not retired into `cv_ws_rtt_seconds`, although
    the turn is past the next classification (2.0) and past that probe's 10 s (11.0). A late
    `pong` is no sample either. The schedule is parked, as before `attach`, so an idle writer
    waits its tick and not 0; and were it armed again, the guard in `_classify` still holds."""
    before = _read()
    pipe, _, _ = _attached()
    _, [probe] = _turn(pipe, 1.0)  # healthy, and the first probe is out
    pipe.release()
    released = _read()
    assert _of(CLASS, before) == {}
    assert {(f"{RTT}_count", ""), (f"{QUEUE_BYTES}_count", "")} <= released.keys()  # served
    pipe.service(12.0)
    assert (_moved(released), _of(CLASS, before)) == ({}, {})  # nothing moved; the count is out
    pipe.pong(probe, 12.0)  # 11 s on, it would retire the probe into the RTT
    assert _moved(released) == {}
    assert pipe.wait_s(12.0, 1.0) == 1.0  # parked: nothing is due, the writer waits its tick
    pipe._classify_at = 2.0  # armed again: the guard is the second line
    pipe.service(12.0)
    assert _moved(released) == {}


def test_release_takes_the_connection_out_of_the_class_count_first_and_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The count leaves before any other teardown step: one that raises (here the queue's
    `clear`) cannot strand it, and a second `release` takes nothing out again."""

    def refuse(*, normal_only: bool = False) -> int:
        raise RuntimeError("teardown")

    before = _read()
    pipe, _, _ = _attached()
    assert _of(CLASS, before) == {"healthy": 1}
    monkeypatch.setattr(pipe.queue, "clear", refuse)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="teardown"):
            pipe.release()
        assert _of(CLASS, before) == {}


# -- the depth each classification reads ----------------------------------------------------------


def test_each_classification_observes_the_depth_it_reads_once() -> None:
    """The depth section 8.3 classifies on: queued bytes plus the windows' pending state, and the
    frames queued on both lanes. Observed once per classification of the connection, never per
    frame: 40 frames queued and a writer turn before the classification is due add nothing."""
    pipe, _, conn = _attached()
    book = _structured(conn, _BOOK)  # its snapshot is queued
    conn.clock.now = 0.6
    pipe.delta(book, _bid("101"))  # leaves at once
    conn.clock.now = 0.61
    pipe.delta(book, _bid("102"))  # waits in the window, to 0.65
    before = _read()
    for _ in range(40):
        pipe.push(_d("system", kind="filler"))
    pipe.service(0.62)  # the first classification is due at 1.0
    assert (QUEUE_BYTES + "_count", "") in before and _moved(before) == {}
    pending = _pacer(pipe).pending_bytes
    depth = (pipe.queue.bytes + pending, len(pipe.queue))
    assert pending > 0 and depth[1] > 40
    pipe.service(1.0)
    pipe.service(1.5)  # the next is due at 2.0
    assert _moved(before) == pytest.approx(
        {
            (f"{QUEUE_BYTES}_count", ""): 1,
            (f"{QUEUE_BYTES}_sum", ""): depth[0],
            (f"{QUEUE_FRAMES}_count", ""): 1,
            (f"{QUEUE_FRAMES}_sum", ""): depth[1],
        }
    )


async def test_a_parked_writer_takes_no_sample_and_a_stuck_socket_shows_in_overflow() -> None:
    """Depth and class are read when the connection's writer runs (`service`). A writer parked in
    a send (a peer that stopped reading) gets no turn while its queue grows, so nothing is sampled
    and the connection keeps the class of its last turn, until the budget closes it. That shows in
    `cv_ws_overflow_total{reason="close_budget"}` (and, through the gateway, in
    `cv_ws_closes_total{reason="slow_consumer"}`)."""
    before, closed = _read(), _overflow("close_budget")
    pipe, asked, _ = _attached(max_frames=4)
    for _ in range(5):
        pipe.push(_d("system", kind="filler"))
    assert (asked, _overflow("close_budget")) == (["slow_consumer"], closed + 1)
    assert _moved(before) == {(CLASS, "healthy"): 1}  # counted at `attach`, never re-read


@pytest.mark.parametrize("name", [CLASS, QUEUE_BYTES, QUEUE_FRAMES])
def test_the_series_read_at_a_writer_turn_say_so_in_their_help_and_their_row(name: str) -> None:
    """The HELP an operator reads, and the 20 section 12.1 row, say that depth and class are read
    when the connection's writer runs, that a parked writer takes no sample, and where a stuck
    socket shows instead."""
    spec = next((s for s in CATALOGUE if s.name == name), None)
    assert spec is not None, name
    rows = [
        line
        for line in _ARCH.read_text(encoding="utf-8").splitlines()
        if line.startswith("| Gateway |") and f"`{name}" in line
    ]
    assert len(rows) == 1
    for text in (spec.help, rows[0]):
        assert "a writer parked in a send takes no sample" in text
        assert "cv_ws_overflow_total" in text and "cv_ws_closes_total" in text


# -- each RTT sample (`RttProbe`) -----------------------------------------------------------------


def test_each_probe_sample_is_one_rtt_observation_in_seconds() -> None:
    """An answered probe is its RTT; one retired unanswered after 10 s is its age, as the class
    reads it, above the top edge. A `pong` for any other id (a heartbeat's, an answered or a
    retired probe's) adds nothing, and a sample on a clock that ran back is 0, never negative."""
    probe = RttProbe(1.0, token=lambda: "t")
    before, buckets = _read(), _buckets(RTT)
    first = probe.ping_id(1.0)
    assert first is not None and probe.pong(first, 1.25)
    assert not probe.pong(first, 1.3) and not probe.pong("c-hb", 1.3)
    second = probe.ping_id(2.0)
    assert second is not None and probe.rtt_ms(2.0 + PONG_TIMEOUT_S + 0.5) == 10_500
    assert not probe.pong(second, 13.0)
    third = probe.ping_id(20.0)
    assert third is not None and probe.pong(third, 19.0)
    assert _moved(before) == pytest.approx({(f"{RTT}_count", ""): 3, (f"{RTT}_sum", ""): 10.75})
    after = _buckets(RTT)
    assert (after["10.0"] - buckets["10.0"], after["+Inf"] - buckets["+Inf"]) == (2, 3)


# -- the real router, flag on and off -------------------------------------------------------------


@_ENCODINGS
@pytest.mark.parametrize("flag", [False, True], ids=["flag_off", "flag_on"])
async def test_a_session_moves_the_series_only_with_the_flag_on(flag: bool, encoding: str) -> None:
    """The real `/ws` router on a fake clock: `auth_ok`, a book `sub`, three deltas published at
    once with a producer's own `coalesced_count` 7, the writer's turn at 1.0 (the window closes;
    the first classification sends the probe), its `pong` at 1.25, the teardown. Flag on: the
    connection counts as `healthy` while open, not after; the pacer carries no producer count, so
    the window is the second and third update, 1 conflated; an RTT of 0.25 s; one depth sample of
    each kind. Flag off: the frames say 7 and nothing moves. No label value is ever added."""
    rig, sock = _Rig(BackpressureConfig() if flag else None), _Wire(encoding)
    sock.answer = False  # the probe's `pong` is fed below, 250 ms late
    before = _read()
    assert (CONFLATED, "book") in before  # served: an empty move below is not vacuous
    async with _connected(rig, sock):
        assert _of(CLASS, before) == ({"healthy": 1} if flag else {})
        await rig.sub(sock)
        for price in ("101", "102", "103"):
            rig.sequencing.publish(_BOOK, _bid(price), coalesced_count=7)
        frames = await _at(rig, sock, 1.0)
        assert [f["p"].get("coalesced_count", 1) for f in frames] == ([1, 2] if flag else [7] * 3)
        assert len(sock.pings) == flag
        if flag:
            await _at(rig, sock, 1.25, {"t": "pong", "id": sock.pings[0]["id"]})
    moved = _moved(before)
    depth = moved.pop((f"{QUEUE_BYTES}_sum", ""), 0.0), moved.pop((f"{QUEUE_FRAMES}_sum", ""), 0.0)
    expected = {
        (CONFLATED, "book"): 1,
        (f"{COALESCED}_count", ""): 1,
        (f"{COALESCED}_sum", ""): 2,
        (f"{RTT}_count", ""): 1,
        (f"{RTT}_sum", ""): 0.25,
        (f"{QUEUE_BYTES}_count", ""): 1,
        (f"{QUEUE_FRAMES}_count", ""): 1,
    }
    assert moved == pytest.approx(expected if flag else {})
    assert (depth[0] > 0) is flag
    for name, (label, values) in CLOSED.items():
        assert {s.labels[label] for f in _families() for s in f.samples if s.name == name} == values
