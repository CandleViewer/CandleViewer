from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.ws.binary import BOOK_DELTA, FLAG_COALESCED, Frame, decode_b64
from candleviewer.ws.coalescing import MAX_PENDING_KEYS
from candleviewer.ws.metrics import cv_ws_malformed_updates_total, cv_ws_overflow_total
from candleviewer.ws.pacing import (
    CLASSIFY_INTERVAL_S,
    DEGRADED_THROTTLE_MS,
    PONG_TIMEOUT_S,
    Classifier,
    ConnectionClass,
    Pacer,
    RttProbe,
    classify,
)
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import SnapshotBody
from tests.unit.ws._seq_support import ACC_A, Book, Conn, Source, validate

HEALTHY, LAGGING = ConnectionClass.HEALTHY, ConnectionClass.LAGGING
_RS = "8f3a2c1e-0000-4000-8000-000000000001"  # a replay session id (uuid)
SATURATED, OVERFLOWING = ConnectionClass.SATURATED, ConnectionClass.OVERFLOWING
_COLUMN = {"t_ms": 0, "price_min": "1", "price_step": "1", "bids": [], "asks": [], "complete": True}
_FOOTPRINT = {"symbol": "BTCUSDT", "bar_type": "tick", "param": "1000"}


def _conn() -> tuple[Conn, Pacer]:
    source = Source()
    source.books["BTCUSDT"] = Book("BTCUSDT")
    source.bodies["trades"] = SnapshotBody({"symbol": "BTCUSDT", "trades": []})
    source.bodies["heatmap"] = SnapshotBody(
        {"symbol": "BTCUSDT", "time_bucket_ms": 500, "columns": []}
    )
    source.bodies["footprint"] = SnapshotBody({**_FOOTPRINT, "bars": []})
    conn = Conn(source, ACC_A)
    conn.clock.now = 100.0
    return conn, Pacer(conn.emitter)


def _sub(conn: Conn, ch: str, **opts: Any) -> Subscription:
    _, sub = conn.sub({"ch": ch, "opts": {"encoding": "structured", **opts}})
    conn.take()  # the initial snap
    return sub


def _private(conn: Conn, family: str) -> Subscription:
    _, sub = conn.authz.admit({"ch": family, "opts": {"exchange_account_ids": [str(ACC_A)]}})
    assert sub is not None
    sub.snapshot_pending = False
    return sub


def _bid(price: str, size: str = "1") -> dict[str, Any]:
    return {"symbol": "BTCUSDT", "depth": 50, "bids": [[price, size]], "asks": []}


# -- §8.3 table and hysteresis --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("queue_pct", "rtt_ms", "expected"),
    [
        (0, None, HEALTHY),
        (24.9, 149.9, HEALTHY),
        (25, None, LAGGING),
        (0, 150, LAGGING),
        (59.9, 500, LAGGING),
        (60, 0, SATURATED),
        (0, 500.1, SATURATED),
        (90, 0, SATURATED),
        (90.1, 0, OVERFLOWING),
    ],
)
def test_classify_section_8_3_boundaries(
    queue_pct: float, rtt_ms: float | None, expected: ConnectionClass
) -> None:
    assert classify(queue_pct, rtt_ms) is expected


def test_classifier_worsens_at_once_and_improves_after_two_better_samples() -> None:
    c = Classifier()
    assert c.observe(SATURATED) and c.current is SATURATED
    assert not c.observe(HEALTHY)
    assert not c.observe(SATURATED)  # a repeat of the current class restarts the streak
    assert not c.observe(HEALTHY)
    assert c.observe(LAGGING)  # two better samples: improve to the worse of them
    assert c.current is LAGGING


def test_rtt_probe_one_outstanding_and_its_age_counts() -> None:
    probe = RttProbe(interval_s=2.0)
    first = probe.ping_id(10.0)
    assert first is not None
    assert probe.ping_id(13.0) is None  # still outstanding
    assert probe.rtt_ms(10.6) == pytest.approx(600)
    assert not probe.pong("c-hb-1", 10.7)
    assert probe.pong(first, 10.04)
    assert not probe.pong(first, 10.05)  # answered already: ignored, nothing kept for it
    assert probe.rtt_ms(11.0) == pytest.approx(40)
    assert probe.ping_id(10.9) is None  # not due before half the interval (PROBE_DUE_SHARE)
    second = probe.ping_id(12.0)
    assert second is not None
    assert probe.rtt_ms(12.01) == pytest.approx(40)  # the last sample until the age exceeds it


# -- throttling and coalescing through the real emitter -------------------------------------


def test_pacer_first_update_leaves_at_once_then_the_window_coalesces() -> None:
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50")
    assert pacer.offer(sub, _bid("100"))
    [first] = conn.take()
    for price in ("101", "102", "103"):
        pacer.offer(sub, _bid(price))
    assert conn.take() == []
    assert pacer.next_due() == pytest.approx(100.05)  # book 50 ms default
    assert pacer.tick(100.049) == 0
    assert pacer.tick(100.05) == 1
    [merged] = conn.take()
    assert merged["s"] == first["s"] + 1
    assert merged["p"]["coalesced"] is True
    assert merged["p"]["coalesced_count"] == 3


def test_pacer_500_updates_one_window_one_frame_one_sequence_number() -> None:
    """#412: lossless state, `coalesced_count` 500, exactly one `s`."""
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50")
    pacer.offer(sub, _bid("90"))
    [prime] = conn.take()
    reference = Book("BTCUSDT")
    updates = [_bid(str(100 + i % 7), str(i % 3)) for i in range(500)]
    for update in updates:
        pacer.offer(sub, update)
        reference.apply(update["bids"], update["asks"])
    pacer.tick(100.05)
    [frame] = conn.take()
    assert frame["s"] == prime["s"] + 1
    assert frame["p"]["coalesced_count"] == 500
    client = Book("BTCUSDT")
    client.apply(prime["p"]["bids"], prime["p"]["asks"])
    client.apply(frame["p"]["bids"], frame["p"]["asks"])
    reference.apply([["90", "1"]], [])
    assert {Decimal(p): s for p, s in client.bids.items()} == {
        Decimal(p): s for p, s in reference.bids.items()
    }


def test_pacer_orders_and_executions_bypass_throttle_and_coalescing() -> None:
    """#412: 50 order transitions in 100 ms leave as 50 individual frames."""
    conn, pacer = _conn()
    orders, executions = _private(conn, "orders"), _private(conn, "executions")
    for i in range(50):
        conn.clock.now = 100.0 + i * 0.002
        pacer.offer(orders, {"orders": []})
    pacer.offer(executions, {"executions": []})
    frames = conn.take()
    assert [f["s"] for f in frames[:50]] == list(range(1, 51))
    assert [f["ch"] for f in frames] == ["orders"] * 50 + ["executions"]
    assert pacer.lanes == {}


def test_pacer_200_prints_in_one_window_leave_in_order_as_one_batch() -> None:
    conn, pacer = _conn()
    sub = _sub(conn, "trades.BTCUSDT")
    pacer.offer(sub, {"symbol": "BTCUSDT", "trades": []})
    conn.take()
    prints = [
        {"id": f"t{i}", "ts_ms": 1, "price": "1", "size": "1", "side": "buy"} for i in range(200)
    ]
    for p in prints:
        pacer.offer(sub, {"symbol": "BTCUSDT", "trades": [p]})
    pacer.tick(100.1)
    [frame] = conn.take()
    assert frame["p"]["trades"] == prints


def test_pacer_honours_coalesce_false_only_while_healthy() -> None:
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50", coalesce=False)
    pacer.offer(sub, _bid("100"))
    for price in ("101", "102"):
        pacer.offer(sub, _bid(price))
    pacer.tick(100.05)
    assert [f["p"]["coalesced"] for f in conn.take()] == [False, False, False]
    notice = pacer.classify(30.0, [sub], now=100.05)
    assert notice is not None
    assert notice["applied"]["forced_coalesce"] is True
    for price in ("104", "105"):
        pacer.offer(sub, _bid(price))
    pacer.tick(100.2)
    assert [f["p"]["coalesced_count"] for f in conn.take()] == [2]


def test_pacer_class_multiplies_throttles_and_degrades_heatmap() -> None:
    conn, pacer = _conn()
    book = _sub(conn, "book.BTCUSDT.50")
    heatmap = _sub(conn, "heatmap.BTCUSDT")
    assert (pacer.throttle_ms(book), pacer.throttle_ms(heatmap)) == (50, 500)
    pacer.classify(30.0, [book, heatmap], now=100.0)
    assert (pacer.throttle_ms(book), pacer.throttle_ms(heatmap)) == (100, 1000)
    pacer.classify(70.0, [book, heatmap], now=102.0)
    assert pacer.cls is SATURATED
    assert (pacer.throttle_ms(book), pacer.throttle_ms(heatmap)) == (200, 2000)
    assert DEGRADED_THROTTLE_MS == 1000


def test_pacer_rtt_over_500ms_announces_saturated_with_degraded_topics() -> None:
    """#412: within one 1 s sample, `connection_quality` names the class, multiplier and topics."""
    conn, pacer = _conn()
    heatmap = _sub(conn, "heatmap.BTCUSDT")
    book = _sub(conn, "book.BTCUSDT.50")
    assert pacer.probe.ping_id(100.0) is not None
    notice = pacer.classify(0.0, [book, heatmap], now=100.6)
    assert notice == {
        "kind": "connection_quality",
        "class": "saturated",
        "queue_pct": 0,
        "rtt_ms": 600,
        "applied": {
            "throttle_multiplier": 4,
            "forced_coalesce": True,
            "degraded_topics": ["heatmap.BTCUSDT"],
        },
    }
    validate({"t": "d", "ch": "system", "s": 1, "ts": 1, "e": "j", "p": notice})
    assert pacer.classify(0.0, [book, heatmap], now=102.6) is None  # probe still unanswered


def test_pacer_recovery_is_announced_after_two_healthy_samples() -> None:
    conn, pacer = _conn()
    book = _sub(conn, "book.BTCUSDT.50")
    pacer.classify(70.0, [book], now=100.0)
    assert pacer.classify(5.0, [book], now=102.0) is None
    notice = pacer.classify(5.0, [book], now=104.0)
    assert notice is not None
    assert notice["class"] == "healthy"
    assert notice["applied"] == {
        "throttle_multiplier": 1,
        "forced_coalesce": False,
        "degraded_topics": [],
    }


def test_pacer_queue_overflow_drops_the_topic_for_a_backpressure_snapshot() -> None:
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50")
    flood = {"bids": [[str(i), "1"] for i in range(1, MAX_PENDING_KEYS + 2)], "asks": []}
    drops = _count(cv_ws_overflow_total, reason="drop")
    with capture_logs() as logs:
        assert not pacer.offer(sub, flood)
    assert _count(cv_ws_overflow_total, reason="drop") == drops + 1  # a full queue overflows
    assert logs == []  # a slow consumer's drop is no producer bug: nothing is logged
    assert conn.take() == []  # never a partial state
    assert (sub.snapshot_pending, sub.pending_reason) == (True, "backpressure")
    assert pacer.resnapshot_required == {sub.sub_id: sub}
    assert not pacer.offer(sub, _bid("100"))
    assert pacer.next_due() is None


def test_pacer_drops_updates_of_a_paused_subscription() -> None:
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50")
    sub.effective["paused"] = True
    assert not pacer.offer(sub, _bid("100"))
    assert conn.take() == []


def test_pacer_replay_frame_carries_the_latest_event_time() -> None:
    conn, pacer = _conn()
    _, sub = conn.sub(
        {"ch": "book.BTCUSDT.50", "opts": {"encoding": "structured"}}, replay_session_id=_RS
    )
    conn.take()
    pacer.offer(sub, _bid("100"), ts_ms=1_000)
    pacer.offer(sub, _bid("101"), ts_ms=1_007)
    pacer.offer(sub, _bid("102"), ts_ms=1_009)
    pacer.tick(100.05)
    assert [f["ts"] for f in conn.take()] == [1_000, 1_009]


def test_pacer_forget_drops_lane_and_pending_resnapshot() -> None:
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50")
    pacer.offer(sub, _bid("100"))
    pacer.offer(sub, _bid("101"))
    pacer.drop(sub)
    pacer.forget(sub.sub_id)
    assert pacer.lanes == {}
    assert pacer.resnapshot_required == {}
    assert pacer.tick(101.0) == 0


def test_pacer_pending_bytes_sum_every_lane() -> None:
    conn, pacer = _conn()
    book = _sub(conn, "book.BTCUSDT.50")
    pacer.offer(book, _bid("100"))
    assert pacer.pending_bytes == 0  # the first update left at once
    pacer.offer(book, _bid("101"))
    assert pacer.pending_bytes > 0
    pacer.tick(100.05)
    assert pacer.pending_bytes == 0


def test_pacer_window_with_nothing_new_emits_nothing_and_keeps_its_clock() -> None:
    conn, pacer = _conn()
    heatmap = _sub(conn, "heatmap.BTCUSDT")
    column = {
        "t_ms": 0,
        "price_min": "1",
        "price_step": "1",
        "bids": [],
        "asks": [],
        "complete": True,
    }
    body = {"symbol": "BTCUSDT", "time_bucket_ms": 500, "columns": [column]}
    pacer.offer(heatmap, body)
    assert len(conn.take()) == 1
    pacer.offer(heatmap, body)  # the bucket is complete and already sent
    assert pacer.tick(100.5) == 0
    assert pacer.lanes[heatmap.sub_id].last_emit == 100.0
    assert pacer.next_due() is None


def test_pacer_drop_marks_a_subscription_without_a_lane() -> None:
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50")
    pacer.drop(sub)
    assert pacer.resnapshot_required == {sub.sub_id: sub}
    assert (sub.snapshot_pending, sub.pending_reason) == (True, "backpressure")


def test_pacer_class_change_re_times_a_pending_window() -> None:
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50")
    pacer.offer(sub, _bid("100"))
    conn.take()
    conn.clock.now = 100.01
    pacer.offer(sub, _bid("101"))
    assert pacer.next_due() == pytest.approx(100.05)
    pacer.classify(30.0, [sub], now=100.02)  # lagging: 50 ms becomes 100 ms
    assert pacer.next_due() == pytest.approx(100.1)
    assert pacer.tick(100.05) == 0
    assert pacer.tick(100.1) == 1


def test_pacer_a_ctl_re_times_no_open_window() -> None:
    """A `ctl` that lowers `throttle_ms` leaves an open window's close as it was armed: an update
    into it after the new value would have made it due still waits, and arms nothing (one heap
    entry per window, C-2.18). The next window takes the new value."""
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50", throttle_ms=500)
    pacer.offer(sub, _bid("100"))  # leaves at once
    pacer.offer(sub, _bid("101"))  # a window closing at 100.5
    assert conn.authz.ctl(sub.ch, {"throttle_ms": 50}) == ({"throttle_ms": 50}, False, sub)
    conn.clock.now = 100.1
    pacer.offer(sub, _bid("102"))
    assert (len(conn.take()), len(pacer._dues), pacer.next_due()) == (1, 1, 100.5)
    conn.clock.now = 100.5
    assert pacer.tick() == 1
    pacer.offer(sub, _bid("103"))
    assert pacer.next_due() == pytest.approx(100.55)


def test_pacer_saturated_holds_a_fast_heatmap_to_one_frame_a_second() -> None:
    conn, pacer = _conn()
    heatmap = _sub(conn, "heatmap.BTCUSDT", time_bucket_ms=100)
    assert pacer.throttle_ms(heatmap) == 100
    pacer.classify(70.0, [heatmap], now=100.0)
    assert pacer.throttle_ms(heatmap) == DEGRADED_THROTTLE_MS  # x4 alone would give 400 ms


def test_pacer_snapshot_from_another_path_discards_the_stale_window() -> None:
    """#2501 review: a client resync between two flushes must not let a pre-snapshot delta
    follow the fresh `snap`."""
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50")
    pacer.offer(sub, _bid("100"))
    pacer.offer(sub, _bid("101"))  # pending in the window
    conn.take()
    assert conn.emitter.snapshot(sub, "client_resync")
    [snap] = conn.take()
    assert pacer.tick(100.05) == 0
    assert conn.take() == []
    conn.clock.now = 101.0
    pacer.offer(sub, _bid("102"))
    [delta] = conn.take()
    assert delta["s"] == snap["s"] + 1
    assert delta["p"]["bids"] == [["102", "1"]]


def test_pacer_failing_emit_never_leaves_the_window_due() -> None:
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50")
    pacer.offer(sub, _bid("100"))
    pacer.offer(sub, _bid("101"))

    def broken(frame: dict[str, Any]) -> None:
        raise RuntimeError("socket gone")

    conn.emitter.push = broken
    with pytest.raises(RuntimeError):
        pacer.tick(100.05)
    assert pacer.next_due() is None
    assert pacer.resnapshot_required == {sub.sub_id: sub}  # the lost window recovers by `snap`


def test_each_rtt_probe_id_carries_a_fresh_random_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """§9.1: a counter and a token drawn per probe (`secrets` unless a source is injected), so no
    id follows from an earlier one."""
    tokens = iter(["aa", "bb"])
    probe = RttProbe(token=lambda: next(tokens))
    first = probe.ping_id(0.0)
    assert first == "s-rtt-1-aa" and probe.pong(first, 0.0) and probe.ping_id(1.0) == "s-rtt-2-bb"
    drawn, ids = RttProbe(), list[str]()
    for t in (0.0, 1.0, 2.0):
        ids.append(str(drawn.ping_id(t)))
        assert drawn.pong(ids[-1], t)
    heads, drawn_tokens = zip(*(i.rsplit("-", 1) for i in ids), strict=True)
    assert heads == ("s-rtt-1", "s-rtt-2", "s-rtt-3") and len(set(drawn_tokens)) == 3
    assert {len(t) for t in drawn_tokens} == {12}  # 48 bits, as hex
    monkeypatch.setattr("candleviewer.ws.pacing.secrets.token_hex", lambda n: "ab" * n)
    assert RttProbe().ping_id(0.0) == "s-rtt-1-" + "ab" * 6  # the default draws from `secrets`


def test_an_rtt_sample_is_never_negative() -> None:
    """§15.9 `rtt_ms` minimum 0: a `pong` stamped earlier than its probe's mark (a clock behind
    the probe's) reads 0, and so does an outstanding probe's age."""
    probe = RttProbe()
    first = probe.ping_id(10.0)
    assert first is not None and probe.rtt_ms(9.0) == 0.0
    assert probe.pong(first, 9.5) and probe.sample_ms == 0.0 and probe.rtt_ms(9.6) == 0.0


def test_the_probe_and_the_pacer_default_to_the_classify_interval() -> None:
    assert RttProbe().interval_s == CLASSIFY_INTERVAL_S == 1.0
    assert _conn()[1].probe.interval_s == CLASSIFY_INTERVAL_S


def test_pacer_next_update_after_a_snapshot_drops_the_stale_window() -> None:
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50")
    pacer.offer(sub, _bid("100"))
    pacer.offer(sub, _bid("101"))  # pending in the window
    conn.take()
    assert conn.emitter.snapshot(sub, "reconfigure")
    conn.take()
    conn.clock.now = 101.0
    pacer.offer(sub, _bid("102"))  # the window had closed: leaves at once, without "101"
    [delta] = conn.take()
    assert delta["p"]["bids"] == [["102", "1"]]
    assert delta["p"]["coalesced"] is False


def test_pacer_window_of_a_paused_subscription_frees_its_pending_bytes() -> None:
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50")
    pacer.offer(sub, _bid("100"))
    pacer.offer(sub, _bid("101"))
    assert pacer.pending_bytes > 0
    sub.effective["paused"] = True
    assert not pacer.offer(sub, _bid("102"))
    assert pacer.pending_bytes == 0


def _count(counter: Any, **labels: str) -> float:
    value: float = counter.labels(**labels)._value.get()
    return value


class _GetRaises(dict[str, Any]):
    def get(self, key: str, default: Any = None) -> Any:
        raise RuntimeError("producer bug")


def _refusals(family: str) -> dict[str, float]:
    """The malformed counter of `family` and the overflow counter of each refusal reason."""
    return {
        "malformed": _count(cv_ws_malformed_updates_total, topic=family),
        "drop": _count(cv_ws_overflow_total, reason="drop"),
        "unmergeable": _count(cv_ws_overflow_total, reason="unmergeable"),
    }


@pytest.mark.parametrize(
    "stale", ["", "re-pended", "paused", "re-snapshotted"], ids=lambda s: s or "live"
)
def test_pacer_forced_coalescing_past_the_key_bound(stale: str) -> None:
    """`apply()` folds the frames queued under `coalesce: false` into one merge, which can
    overflow: a live topic is dropped for a snapshot, never lost silently; a dead window (held
    deltas, or a `snap` sent since) is shed, never folded nor counted (§8.4)."""
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50", coalesce=False)
    pacer.offer(sub, _bid("1"))  # leaves at once; the next two wait for the window
    for base in (10_000, 20_000):
        levels = [[str(base + i), "1"] for i in range(MAX_PENDING_KEYS // 2 + 1)]
        assert pacer.offer(sub, {"bids": levels, "asks": []})
    if stale == "re-pended":  # by another sender
        sub.snapshot_pending, sub.pending_reason = True, "client_resync"
    elif stale == "paused":
        sub.effective["paused"] = True
    elif stale:
        assert conn.emitter.snapshot(sub, "client_resync")
    before = _refusals("book")
    assert pacer.classify(30.0, [sub]) is not None  # lagging forces coalescing
    dropped = not stale
    assert (pacer.resnapshot_required == {sub.sub_id: sub}) is dropped
    assert (sub.pending_reason == "backpressure") is dropped
    assert _refusals("book") == {**before, "drop": before["drop"] + dropped}
    assert pacer.pending_bytes == 0
    if stale == "paused":  # the shed window is not lost: the resume `ctl` re-snapshots (§5.4)
        assert conn.authz.ctl(sub.ch, {"paused": False})[1] and sub.snapshot_pending


def test_pacer_malformed_update_is_counted_and_logged_apart_from_overflow() -> None:
    """A producer bug drops the topic like an overflow but counts apart, logging the family,
    topic and error class only; a refusal by `take` is caught at the flush."""
    conn, pacer = _conn()
    heatmap = _sub(conn, "heatmap.BTCUSDT", coalesce=False)
    before = _refusals("heatmap")
    body = {"symbol": "BTCUSDT", "time_bucket_ms": 500, "columns": [_GetRaises(_COLUMN)]}
    with capture_logs() as logs:
        pacer.offer(heatmap, body)
    assert conn.take() == [] and pacer.resnapshot_required == {heatmap.sub_id: heatmap}
    assert _refusals("heatmap") == {**before, "malformed": before["malformed"] + 1}
    event = {"event": "ws update malformed", "family": "heatmap", "ch": heatmap.ch}
    assert logs == [{**event, "error": "RuntimeError", "log_level": "warning"}]  # never its message


def test_pacer_unmergeable_footprint_update_resnapshots_under_its_own_reason() -> None:
    """An update that breaks its merge rule, here one to a footprint bar already confirmed in its
    window (§8.2), re-snapshots the topic: a producer bug counted apart (#3297), neither a slow
    consumer's drop nor a malformed update, and logged as one is (family, topic, class only)."""
    conn, pacer = _conn()
    sub = _sub(conn, "footprint.BTCUSDT.tick.1000")
    cells = [{"price": "1", "bid_volume": "1", "ask_volume": "0"}]
    bar = {"generation": 0, "index": 0, "t_ms": 0, "cells": cells}
    before = _refusals("footprint")
    with capture_logs() as logs:
        assert not pacer.offer(sub, {**_FOOTPRINT, "bars": [{**bar, "confirm": True}, bar]})
    after = {**before, "unmergeable": before["unmergeable"] + 1}
    event = {"event": "ws update unmergeable", "family": "footprint", "ch": sub.ch}
    logged = {**event, "error": "_UnmergeableError", "log_level": "warning"}
    assert (_refusals("footprint"), logs) == (after, [logged])
    assert pacer.resnapshot_required == {sub.sub_id: sub}


def test_pacer_one_missed_pong_does_not_pin_the_connection_saturated() -> None:
    """§9.1: a probe unanswered for 10 s is retired; its age counts once and a fresh probe
    follows, whose answer lets the class recover."""
    conn, pacer = _conn()
    book = _sub(conn, "book.BTCUSDT.50")
    lost = pacer.probe.ping_id(100.0)
    assert pacer.classify(0.0, [book], now=101.0) is not None  # saturated: unanswered for 1 s
    assert pacer.probe.ping_id(100.0 + PONG_TIMEOUT_S - 0.01) is None
    fresh = pacer.probe.ping_id(100.0 + PONG_TIMEOUT_S)
    assert fresh is not None and lost is not None and not pacer.probe.pong(lost, 110.01)
    assert pacer.probe.rtt_ms(110.0) == pytest.approx(PONG_TIMEOUT_S * 1000)
    assert pacer.probe.pong(fresh, 110.04)
    assert pacer.classify(0.0, [book], now=110.5) is None
    notice = pacer.classify(0.0, [book], now=112.5)
    assert notice is not None and notice["class"] == "healthy"


def test_rtt_probe_ignores_a_pong_that_comes_after_the_pong_window() -> None:
    """§9.1: even when nothing retired the probe first, its late `pong` is not a sample."""
    probe = RttProbe()
    late = probe.ping_id(100.0)
    assert late is not None and not probe.pong(late, 100.0 + PONG_TIMEOUT_S + 0.5)
    assert probe.rtt_ms(111.0) == pytest.approx((PONG_TIMEOUT_S + 0.5) * 1000)


@pytest.mark.parametrize("family", ["orders", "executions"])
def test_pacer_drop_refuses_a_never_throttled_family(family: str) -> None:
    """S4: never dropped; the ladder closes the connection instead (§8.4 step 3)."""
    conn, pacer = _conn()
    sub = _private(conn, family)
    with pytest.raises(ValueError, match="never dropped"):
        pacer.drop(sub)
    assert (sub.snapshot_pending, pacer.resnapshot_required) == (False, {})


def test_pacer_tick_apply_and_classify_default_to_the_emitter_clock() -> None:
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50")
    pacer.offer(sub, _bid("100"))
    pacer.offer(sub, _bid("101"))  # due at 100.05
    assert pacer.tick() == 0
    conn.clock.now = 100.3
    pacer.apply([sub])
    assert pacer.next_due() == pytest.approx(100.3)
    assert pacer.tick() == 1
    pacer.probe.ping_id(100.3)
    conn.clock.now = 100.9
    notice = pacer.classify(0.0, [sub])
    assert notice is not None and notice["rtt_ms"] == 600


def test_pacer_reconfigured_heatmap_sends_a_bucket_time_it_sent_before() -> None:
    """A new `time_bucket_ms` reuses `t_ms` values, and the sent-bucket memory is keyed by `t_ms`
    only: every snapshot gives the lane a new queue."""
    conn, pacer = _conn()
    heatmap = _sub(conn, "heatmap.BTCUSDT")
    body = {"symbol": "BTCUSDT", "time_bucket_ms": 500, "columns": [_COLUMN]}
    pacer.offer(heatmap, body)
    assert len(conn.take()) == 1
    assert conn.authz.ctl(heatmap.ch, {"time_bucket_ms": 100})[1]  # `resnapshot: true`
    conn.emitter.flush_pending([heatmap])
    assert [f["meta"]["reason"] for f in conn.take()] == ["reconfigure"]
    conn.clock.now = 101.0
    pacer.offer(heatmap, {**body, "time_bucket_ms": 100})
    assert [f["p"]["columns"] for f in conn.take()] == [[_COLUMN]]


def test_pacer_merged_book_window_reaches_a_binary_subscriber_as_a_coalesced_delta() -> None:
    conn, pacer = _conn()
    sub = _sub(conn, "book.BTCUSDT.50", encoding="binary")
    for price in (100, 101, 102):  # the first leaves at once; the other two merge
        part = Frame(BOOK_DELTA, ((0, price * 10, 1000),), price_scale=1, qty_scale=3)
        pacer.offer(sub, _bid(str(price)), part=part)
    pacer.tick(100.05)
    merged = decode_b64(conn.take()[-1]["p"])
    assert merged.flags & FLAG_COALESCED
    assert merged.records == ((0, 1020, 1000), (0, 1010, 1000))
