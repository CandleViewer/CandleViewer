"""E17-T03 (#412), flag on: the writer's turn classifies the connection every
`classify_interval_ms` and announces a class change on `system`; the RTT probe is a server `ping`
on the priority lane whose `pong` `dispatch` routes back (23 §8.3, §9.1, §15.9). Unit tests drive
a pipeline attached to a `Conn` (`_attached`); router tests the real `/ws` router on a fake clock.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from typing import Any
from unittest.mock import Mock

import pytest

from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.outbound import LadderEvent
from candleviewer.ws.pacing import PONG_TIMEOUT_S, Pacer
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.pipeline import ConnectionPipeline
from candleviewer.ws.sequencing import SnapshotBody
from tests.unit.ws._seq_support import Conn, Source, validate
from tests.unit.ws.test_lifecycle_socket import BASE_MS
from tests.unit.ws.test_pacing import _bid
from tests.unit.ws.test_pacing import _conn as _paced
from tests.unit.ws.test_pipeline_invalidation import _connected
from tests.unit.ws.test_pipeline_ladder import _attached, _structured
from tests.unit.ws.test_pipeline_outbound import _BOOK, _ENCODINGS, _d, _queued, _Rig, _Wire

_HEATMAP, _PROFILE = "heatmap.BTCUSDT", "profile.BTCUSDT.volume"
_BODIES = {
    "heatmap": SnapshotBody({"symbol": "BTCUSDT", "time_bucket_ms": 500, "columns": []}),
    "profile": SnapshotBody({"symbol": "BTCUSDT", "kind": "volume", "profiles": []}),
}


def _pacer(pipe: ConnectionPipeline) -> Pacer:
    assert pipe.ladder is not None
    return pipe.ladder.pacer


def _degradable(conn: Conn) -> None:
    """Snapshot bodies for the two families `saturated` degrades (§8.3)."""
    source = conn.emitter.source
    assert isinstance(source, Source)
    source.bodies.update(_BODIES)


def _turn(pipe: ConnectionPipeline, now: float) -> tuple[list[dict[str, Any]], list[str]]:
    """The writer's turn at `now`, then all it queued: the notices (each frame validated against
    §13.1 and §15.9) and the probe ids; anything else queued is let go."""
    pipe.service(now)
    frames = _queued(pipe)
    notices = [f for f in frames if f.get("ch") == "system" and f["p"]["kind"] != "filler"]
    for frame in notices:
        validate(frame)
    return [f["p"] for f in notices], [f["id"] for f in frames if f["t"] == "ping"]


async def _at(rig: _Rig, sock: _Wire, now: float, *feed: dict[str, Any]) -> list[dict[str, Any]]:
    """Set the clock to `now`, feed `feed`, and let the writer take its turn there: every frame it
    sent but the server pings (`sock.pings`). Two fences (a `ping` each): the writer serves `now`
    before it sends the first `pong`, so the second follows all that turn queued, and the client's
    `pong`s (fed, or `sock.answer`'s) are handled at `now`, before the second fence."""
    rig.clock.now = now
    for frame in feed:
        sock.feed(frame)
    frames: list[dict[str, Any]] = []
    for fence in ("f1", "f2"):
        sock.feed({"t": "ping", "id": fence})
        while (frame := (await sock.next())[0])["t"] != "pong" or frame.get("id") != fence:
            frames.append(frame)
    return frames


def _notice(cls: str, rtt_ms: int, multiplier: int, degraded: list[str]) -> dict[str, Any]:
    return {
        "kind": "connection_quality",
        "class": cls,
        "queue_pct": 0,
        "rtt_ms": rtt_ms,
        "applied": {
            "throttle_multiplier": multiplier,
            "forced_coalesce": cls != "healthy",
            "degraded_topics": degraded,
        },
    }


# -- AC5 and the announcements -------------------------------------------------------------------


@_ENCODINGS
@pytest.mark.parametrize("late", [None, 0.6], ids=["unanswered", "answered_600_ms_late"])
async def test_rtt_over_500ms_announces_saturated_at_the_next_classification_naming_degraded_topics(
    late: float | None, encoding: str
) -> None:
    """AC5 as D12 reads it (ruled 17 Oct 08:41Z): "within 2 s" is "at the first classification
    after the probe's age passes 500 ms". Worst phase: the RTT rises just after a classification
    whose probe was answered at once, so the next one still reads that sample and probes, and the
    one after reads the new probe, unanswered or answered 600 ms late, as `saturated`: 1.999 s
    after the rise. The notice names the multiplier and the degraded topics (§8.3, §15.9)."""
    rig, sock = _Rig(BackpressureConfig()), _Wire(encoding)
    rig.source.bodies.update(_BODIES)
    async with _connected(rig, sock):
        for ch in (_HEATMAP, _PROFILE, _BOOK):
            await rig.sub(sock, ch)
        assert await _at(rig, sock, 1.0) == [] and len(sock.pings) == 1  # answered: 0 ms RTT
        risen, sock.answer = 1.001, False  # the RTT rises just after that classification
        assert await _at(rig, sock, 2.0) == [] and len(sock.pings) == 2  # the 0 ms sample
        if late is not None:
            assert await _at(rig, sock, 2.0 + late, {"t": "pong", "id": sock.pings[1]["id"]}) == []
        [notice] = await _at(rig, sock, 3.0)
    assert 3.0 - risen < 2.0 and (notice["t"], notice["ch"]) == ("d", "system")
    validate(notice)
    rtt_ms = 1000 if late is None else 600
    assert notice["p"] == _notice("saturated", rtt_ms, 4, [_HEATMAP, _PROFILE])


def test_classes_announced_both_directions_with_hysteresis() -> None:
    """§8.3: every class change is announced, a worse one at once, a better one only after two
    consecutive better samples, and then to the worse of the two; a turn that changes nothing
    announces nothing. Driven by the RTT (each probe answered after a chosen delay) and, for
    `overflowing`, by the queue depth."""
    pipe, _, conn = _attached(max_frames=100)
    _degradable(conn)
    _structured(conn, _HEATMAP)
    _queued(pipe)
    announced: list[tuple[float, str, int, int, list[str]]] = []
    for now, depth, rtt_s in (
        (1.0, 0, 0.2),  # no sample yet: healthy, as it starts
        (2.0, 0, 0.6),  # 200 ms: lagging, at once
        (3.0, 0, 0.01),  # 600 ms: saturated, at once
        (4.0, 92, 0.01),  # 10 ms, but 92 % queued: overflowing
        (5.0, 0, 0.3),  # one better sample: nothing yet
        (6.0, 0, 0.01),  # 300 ms, the second: to the worse of the two, lagging
        (7.0, 0, 0.01),  # healthy, once
        (8.0, 0, 0.01),  # and twice
    ):
        for _ in range(depth):
            pipe.push(_d("system", kind="filler"))
        notices, (probe,) = _turn(pipe, now)
        pipe.pong(probe, now + rtt_s)
        announced += [
            (now, n["class"], n["queue_pct"], n["rtt_ms"], n["applied"]["degraded_topics"])
            for n in notices
        ]
    assert announced == [
        (2.0, "lagging", 0, 200, []),
        (3.0, "saturated", 0, 600, [_HEATMAP]),
        (4.0, "overflowing", 92, 10, [_HEATMAP]),
        (6.0, "lagging", 0, 300, []),
        (8.0, "healthy", 0, 10, []),
    ]


# -- the RTT probe -------------------------------------------------------------------------------


def test_probe_ping_on_priority_lane_one_outstanding() -> None:
    """§9.1 with the flag on: the probe is a server `ping` queued on the priority lane right after
    the classification, ahead of queued market data; at most one is outstanding; one unanswered
    for 10 s is retired and a fresh one follows. A late turn takes one classification and the
    schedule keeps its grid, so the next tick comes under an interval after that turn's probe and
    still probes (`PROBE_DUE_SHARE`): no tick skips its probe."""
    pipe, _, conn = _attached()
    book = _structured(conn, _BOOK)
    _queued(pipe)
    conn.emitter.delta(book, _bid("90"))  # market data, queued on the normal lane
    pipe.service(1.0)
    first = pipe.queue.pop()
    assert first is not None and first.priority and len(pipe.queue) == 1
    ping = json.loads(first.payload)
    assert ping == {"t": "ping", "id": ping["id"], "ts": BASE_MS, "p": {"server_ms": BASE_MS}}
    assert _turn(pipe, 2.0)[1] == []  # unanswered: still the one outstanding
    pipe.pong(ping["id"], 2.5)
    probes = [ping["id"], *_turn(pipe, 3.0)[1]]
    for now in range(4, 13):
        assert _turn(pipe, float(now))[1] == []
    probes += _turn(pipe, 3.0 + PONG_TIMEOUT_S)[1]  # the second, retired: a third
    pipe.pong(probes[-1], 13.1)
    probes += _turn(pipe, 14.4)[1]  # the turn due at 14.0, 0.4 s late
    pipe.pong(probes[-1], 14.45)
    assert pipe.wait_s(14.4, 10.0) == pytest.approx(0.6)  # the grid: the next is due at 15.0
    probes += _turn(pipe, 15.0)[1]  # 0.6 s after the last probe: still sent
    pipe.pong(probes[-1], 15.0)
    probes += _turn(pipe, 18.5)[1]  # two ticks missed: one classification
    assert pipe.wait_s(18.5, 10.0) == pytest.approx(0.5)  # on the grid: the next is at 19.0
    assert [i.rsplit("-", 1)[0] for i in probes] == [f"s-rtt-{n}" for n in range(1, 7)]


def test_the_configured_classification_interval_paces_the_turn_and_the_probe() -> None:
    """`CV_WS_CLASSIFY_INTERVAL_MS` (`classify_interval_ms`, D10) times both the classification
    and the probe, the first one interval after the `attach` on the gateway's clock: 750 ms here,
    attached at 100 s."""
    pipe, _, _ = _attached(now=100.0, classify_interval_ms=750)
    assert _pacer(pipe).probe.interval_s == 0.75
    assert _turn(pipe, 100.74) == ([], []) and pipe.wait_s(100.74, 1.0) == pytest.approx(0.01)
    (probe,) = _turn(pipe, 100.75)[1]
    pipe.pong(probe, 100.75)
    assert _turn(pipe, 101.49)[1] == [] and len(_turn(pipe, 101.5)[1]) == 1


def test_a_classification_never_lands_on_its_own_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """A float edge: the schedule's sum can round onto `now` (1234567.891 + 1.234), so the next
    classification goes a step on; the wait after the turn is not 0, and no second sample."""
    pipe, _, _ = _attached(classify_interval_ms=1234)
    classify = Mock(wraps=_pacer(pipe).classify)
    monkeypatch.setattr(_pacer(pipe), "classify", classify)
    pipe._classify_at = 1234567.891
    now = pipe._classify_at + 1.234
    pipe.service(now)
    assert pipe.wait_s(now, 10.0) > 0
    pipe.service(now)
    assert classify.call_count == 1


def test_a_predicted_probe_id_is_not_a_sample() -> None:
    """§9.1: each probe id ends in a fresh random token, so a client that has one probe's id
    cannot work out the next: a `pong` for the last id with its counter plus one stores nothing
    while the next probe is outstanding, and only that probe's own id, from its `ping`, counts."""
    pipe, _, _ = _attached()
    probe = _pacer(pipe).probe
    [first] = _turn(pipe, 1.0)[1]
    pipe.pong(first, 1.0)
    [second] = _turn(pipe, 2.0)[1]
    predicted, state = first.replace("-1", "-2", 1), dict(vars(probe))  # its counter plus one
    pipe.pong(predicted, 2.0)
    assert vars(probe) == state  # nothing kept: the second is still outstanding
    pipe.pong(second, 2.25)
    assert probe.sample_ms == pytest.approx(250)


class _Compared(str):
    """A `pong` id that counts the comparisons made with it."""

    seen = 0

    def __eq__(self, other: object) -> bool:
        _Compared.seen += 1
        return str.__eq__(self, other)

    def __ne__(self, other: object) -> bool:
        _Compared.seen += 1
        return str.__ne__(self, other)

    __hash__ = str.__hash__


@_ENCODINGS
async def test_unknown_answered_or_retired_pong_ids_are_ignored(encoding: str) -> None:
    """§9.1 (#2552): only the outstanding probe's `pong` is a sample. Any other id, made up, a
    heartbeat's, already answered or retired, changes nothing and keeps nothing; a client sends
    them at will, past the inbound rate limit (§8.5), and each costs the probe one comparison."""
    rig, sock = _Rig(BackpressureConfig()), _Wire(encoding)
    sock.answer = False
    async with _connected(rig, sock) as conn:
        assert conn.pipeline is not None
        probe = _pacer(conn.pipeline).probe
        await _at(rig, sock, 1.0)
        first = sock.pings[0]["id"]
        state = dict(vars(probe))
        made_up = ["c-1", "s-hb-1", "s-rtt-2", f"{first}0", first.upper(), ""]
        bogus = [{"t": "pong", "id": i} for i in made_up * 6] + [
            {"t": "pong"},
            {"t": "pong", "id": 7},
        ]
        assert await _at(rig, sock, 1.1, *bogus) == []  # 38 in one second: no reply, no strike
        assert vars(probe) == state and probe.sample_ms is None
        assert await _at(rig, sock, 1.2, {"t": "pong", "id": first}) == []
        assert probe.sample_ms == pytest.approx(200)
        state = dict(vars(probe))
        assert await _at(rig, sock, 1.3, {"t": "pong", "id": first}) == []  # answered already
        assert vars(probe) == state
        await _at(rig, sock, 2.0)
        second = sock.pings[1]["id"]
        for second_s in range(3, 13):  # unanswered for 10 s: retired at 12.0, a third follows
            await _at(rig, sock, float(second_s))
        [third] = [p["id"] for p in sock.pings[2:]]
        state = dict(vars(probe))
        assert await _at(rig, sock, 12.5, {"t": "pong", "id": second}) == []  # retired
        assert vars(probe) == state and probe.sample_ms == pytest.approx(PONG_TIMEOUT_S * 1000)
        pipe = conn.pipeline
        for outstanding, now in ((True, 12.6), (False, 12.8)):
            if not outstanding:
                pipe.pong(third, 12.7)
            _Compared.seen = 0
            pipe.pong(_Compared("c-1"), now)
            assert _Compared.seen == (1 if outstanding else 0)


@pytest.mark.parametrize("depth", [math.nan, math.inf, -math.inf], ids=["nan", "inf", "-inf"])
def test_non_finite_queue_pct_is_guarded(depth: float, monkeypatch: pytest.MonkeyPatch) -> None:
    """#2552: a queue depth that is not finite reads as a full queue: `overflowing`, announced with
    `queue_pct` 100 (valid under §15.9). Never healthy, and never the NaN that `round` would raise
    on in the writer's turn; `Pacer.classify` holds it for any caller, with an RTT of its own."""
    pipe, _, _ = _attached()
    monkeypatch.setattr(pipe.queue, "pct", lambda pending_bytes=0: depth)
    notices, probes = _turn(pipe, 1.0)
    assert [(n["class"], n["queue_pct"]) for n in notices] == [("overflowing", 100)]
    assert len(probes) == 1
    _, pacer = _paced()
    pacer.probe.ping_id(100.0)
    notice = pacer.classify(depth, [], now=100.6)  # the probe's age alone reads saturated
    assert notice is not None and (notice["class"], notice["queue_pct"]) == ("overflowing", 100)


def test_the_depth_counts_the_windows_pending_state() -> None:
    """§8.3's depth is the §8.4 budget's: queued frames and the windows' pending state, read
    before the turn closes them. With the queue empty and an open window holding over a quarter
    of the budget, the connection is `lagging`."""
    pipe, _, conn = _attached(max_bytes=400)
    book = _structured(conn, _BOOK)
    _queued(pipe)
    for i in range(12):  # the first leaves at once; the window holds the rest
        pipe.delta(book, _bid(str(90 + i)))
    _queued(pipe)
    pending = _pacer(pipe).pending_bytes
    notices, _ = _turn(pipe, 1.0)
    assert [(n["class"], n["queue_pct"]) for n in notices] == [("lagging", round(pending / 4))]


# -- what a class change does --------------------------------------------------------------------


def test_classification_reschedules_the_next_window() -> None:
    """#2552, "re-read `next_due` after `classify`": `apply` re-times the open windows, both ways.
    A class that worsens before a window closes moves its close later, and the writer's wait is
    read after it; one that improves can make a window due at once, and it leaves in the same
    turn: the classification runs before the turn closes the due windows."""
    pipe, _, conn = _attached(max_frames=8)
    book = _structured(conn, _BOOK)

    def updates(*at: tuple[float, str]) -> None:
        """The first update leaves at once; the next opens a window."""
        for now, price in at:
            conn.clock.now = now
            pipe.delta(book, _bid(price))
        _queued(pipe)

    updates((0.98, "90"), (0.99, "91"))  # the window closes at 1.03, at 50 ms
    assert pipe.wait_s(0.99, 1.0) == pytest.approx(0.01)  # the classification, at 1.0, first
    for _ in range(2):  # 25 % of the budget queued: lagging at the 1.0 classification
        pipe.push(_d("system", kind="filler"))
    notices, (probe,) = _turn(pipe, 1.0)
    pipe.pong(probe, 1.0)
    assert [n["class"] for n in notices] == ["lagging"]
    assert pipe.wait_s(1.0, 1.0) == pytest.approx(0.08)  # at 100 ms it closes at 1.08
    pipe.service(1.05)
    assert len(pipe.queue) == 0  # its old close passed: it waits on
    pipe.service(1.08)
    [window] = _queued(pipe)
    assert window["p"]["bids"] == [["91", "1"]]
    notices, (probe,) = _turn(pipe, 2.0)
    pipe.pong(probe, 2.0)
    assert notices == []  # healthy once: still lagging
    updates((2.95, "92"), (2.96, "93"))  # the window closes at 3.05, at 100 ms
    pipe.service(3.0)  # healthy twice: at 50 ms it closes at 3.0, so it goes in this turn
    frames = _queued(pipe)
    assert [f["p"]["class"] for f in frames if f.get("ch") == "system"] == ["healthy"]
    assert [f["p"]["bids"] for f in frames if f.get("ch") == _BOOK] == [[["93", "1"]]]


async def test_a_window_re_armed_sooner_closes_on_time_while_the_writer_idles() -> None:
    """§8.1, §8.3 through the router, the writer's tick 30 s: a class that improves at a
    classification re-arms an open window to close sooner (`apply`, which `Pacer.on_arm` sees
    too), and the writer, idle after that turn, sends the window at its new close, before its
    old one, with nothing else on the wire to wake it."""
    rig, sock = _Rig(BackpressureConfig(), tick_s=30.0), _Wire()
    async with _connected(rig, sock):
        await rig.sub(sock)
        sock.answer = False
        assert await _at(rig, sock, 1.0) == []
        sock.answer = True
        assert await _at(rig, sock, 1.2, {"t": "pong", "id": sock.pings[0]["id"]}) == []
        [lagging] = await _at(rig, sock, 2.0)  # 200 ms
        assert await _at(rig, sock, 3.0) == []  # healthy, once
        for at, price in ((3.97, "101"), (3.98, "102")):  # a window, closing at 4.07 (100 ms)
            rig.clock.now = at
            rig.sequencing.publish(_BOOK, _bid(price))
        [first] = await sock.next()
        rig.clock.now = 4.0  # healthy twice: the window closes at 4.02 (50 ms)
        [healthy] = await sock.next()
        rig.clock.now = 4.03  # past its new close, before its old one
        [window] = await sock.next()
    assert (lagging["p"]["class"], healthy["p"]["class"]) == ("lagging", "healthy")
    assert (window["s"], window["p"]["bids"]) == (first["s"] + 1, [["102", "1"]])


async def test_coalesce_false_honoured_only_while_healthy() -> None:
    """§5.1 `coalesce`, §8.3: a subscription's `coalesce: false` holds while the connection is
    healthy, each update in a window its own frame; under pressure the server merges them and its
    notice says so (`applied.forced_coalesce`), until the class recovers and says so again."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    async with _connected(rig, sock):
        sub_ok, _ = await rig.sub(sock, coalesce=False)
        assert sub_ok["p"]["results"][0]["effective"]["coalesce"] is False

        async def window(at: float) -> list[tuple[bool, int]]:
            """Three updates at `at`: the first leaves at once, the others when the window
            closes, which the turn 250 ms on is past in every class."""
            rig.clock.now = at
            for price in ("101", "102", "103"):
                rig.sequencing.publish(_BOOK, _bid(price))
            frames = await _at(rig, sock, at + 0.25)
            return [(f["p"]["coalesced"], f["p"].get("coalesced_count", 1)) for f in frames]

        assert await window(0.2) == [(False, 1)] * 3
        assert await _at(rig, sock, 1.0) == []  # healthy; its probe is answered at once
        sock.answer = False
        assert await _at(rig, sock, 2.0) == []
        [saturated] = await _at(rig, sock, 3.0)
        assert await window(3.1) == [(False, 1), (True, 2)]
        sock.answer = True
        assert await _at(rig, sock, 3.4, {"t": "pong", "id": sock.pings[1]["id"]}) == []
        for now in (4.0, 5.0):  # 2 400 ms, then one healthy sample: no change yet
            assert await _at(rig, sock, now) == []
        [healthy] = await _at(rig, sock, 6.0)
        assert await window(6.1) == [(False, 1)] * 3
    forced = [(n["p"]["class"], n["p"]["applied"]["forced_coalesce"]) for n in (saturated, healthy)]
    assert forced == [("saturated", True), ("healthy", False)]


async def test_a_class_change_checks_the_budget_though_nothing_is_queued_with_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ladder's caller duty (§8.4): `apply` may fold a window into a larger estimate, so a
    class change runs the budget check, and acts on it, though nothing is queued with it: a
    principal with no role gets no notice (§15.9), and no probe goes while one is outstanding.
    A step 3 `close` that check returns closes the connection `slow_consumer`."""
    pipe, asked, _ = _attached()
    ladder = pipe.ladder
    assert ladder is not None
    monkeypatch.setattr(pipe, "_notify", lambda body: None)  # §15.9 leaves it out
    checks: list[float] = []
    check = ladder.check

    def spy(subs: Iterable[Subscription]) -> list[LadderEvent]:
        checks.append(pipe._now)
        return check(subs) if pipe._now < 2.0 else [LadderEvent("close", (), "budget")]

    monkeypatch.setattr(ladder, "check", spy)
    pipe.service(1.0)  # healthy, as it starts: its probe's push is checked
    pipe.service(2.0)  # 1 s unanswered: saturated, with nothing queued; the check says close
    assert (checks, asked, len(pipe.queue)) == ([1.0, 2.0], ["slow_consumer"], 0)


async def test_a_notice_over_the_budget_closes_and_nothing_follows_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§8.4 step 3 for the classification's own frames: a `system` notice is never dropped, so one
    that takes the queue over its budget closes the connection `slow_consumer`; no probe and no
    window follows the close (WS-D01)."""
    pipe, asked, _ = _attached(max_frames=4)
    for _ in range(4):  # the budget, exactly
        pipe.push(_d("system", kind="filler"))
    ticks: list[float] = []
    monkeypatch.setattr(_pacer(pipe), "tick", ticks.append)
    pipe.service(1.0)  # 100 % queued: overflowing, and its notice is one frame too many
    assert (asked, ticks, len(pipe.queue)) == (["slow_consumer"], [], 0)
    assert _pacer(pipe).probe.rtt_ms(1.5) is None  # no probe outstanding: none was taken
