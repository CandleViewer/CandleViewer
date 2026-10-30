"""#571 (E17-T06) Logs Part B: the close lines and the overflow drop line (the orchestrator's
ruling of 2026-10-28 on the proposed severity table).

`ws close` logs at its audit row's severity, with step 3's `trigger`; `ws close deadline passed`
says `flush_abandoned`; `ws connection ended` is one line per ended connection; `ws overflow drop`
is one capped `warning` per connection per 10 s. No line carries a token.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from typing import Any, cast

import pytest
from structlog.testing import capture_logs

from candleviewer.ws import pipeline
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import WARNING_CLOSES, _Connection
from candleviewer.ws.outbound import LadderEvent
from candleviewer.ws.sequencing import SnapshotBody
from tests.unit.ws.test_bars_share import _BARS, _bars
from tests.unit.ws.test_bars_share import _rig as _share_rig
from tests.unit.ws.test_outbound import _sub
from tests.unit.ws.test_pipeline_ladder import _attached, _bid, _structured
from tests.unit.ws.test_pipeline_outbound import _BOOK, _DEADLINE_S, _queued, _Rig, _Wire

_JSON = "cv.v1.json"
_INFO_CLOSES = ("heartbeat_timeout", "bad_client", "token_expired", "shutdown")
#: A marker only the access token carries (as `test_ws_token_never_leaks`): no line may carry it.
_MARK = "d7e3b9a5c1f8"
_ACCESS = f"fake-access-{_MARK}"
_TRADES = "trades.BTCUSDT"


def _lines(logs: Iterable[Mapping[str, Any]], event: str) -> list[Mapping[str, Any]]:
    return [e for e in logs if e["event"] == event]


def _bare(backpressure: BackpressureConfig | None = None) -> _Connection:
    kw: dict[str, Any] = {"encoding": _JSON, "clock": float, "wall_ms": int, "auth_timeout_s": 1}
    return _Connection(cast(Any, _Wire()), **kw, backpressure=backpressure)


def test_the_flag_off_deadline_line_says_the_flush_was_abandoned() -> None:
    # The bare connection keeps the flag-off flush timer until #2409's removal PR, which deletes
    # this test with the branch it covers (`_flush_deadline_passed`, `pipeline is None`).
    conn = _bare()
    conn.end_writer = lambda: True  # the writer still ran at its deadline
    with capture_logs() as logs:
        conn._flush_deadline_passed()
    (line,) = _lines(logs, "ws close deadline passed")
    assert (line["log_level"], line["flush_abandoned"]) == ("warning", True)
    assert line["connection_id"] == conn.connection_id and "trigger" not in line


# -- row 1: `ws close` ---------------------------------------------------------------------------


@pytest.mark.parametrize("reason", sorted(WARNING_CLOSES) + list(_INFO_CLOSES))
async def test_ws_close_is_logged_at_its_audit_rows_severity(reason: str) -> None:
    """`warning` for `WARNING_CLOSES`, `info` otherwise; no `trigger` outside step 3 (a plain
    `slow_consumer` close, an eviction or a flush deadline, names none). The fields stay."""
    conn = _bare(BackpressureConfig())
    with capture_logs() as logs:
        conn.close_with(reason)
    (line,) = _lines(logs, "ws close")
    assert line["log_level"] == ("warning" if reason in WARNING_CLOSES else "info")
    assert "trigger" not in line
    assert {"connection_id", "reason", "code", "dropped", "user_id", "session_id"} <= set(line)


async def test_a_step_3_budget_close_names_its_trigger() -> None:
    rig, sock = _Rig(BackpressureConfig(max_frames=8)), _Wire()
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handler, conn = await rig.open(sock)
            for i in range(9):
                rig.hub.broadcast_system({"kind": "tick", "n": i})  # in one turn: one over
            await handler
    (line,) = _lines(logs, "ws close")
    assert (line["log_level"], line["reason"], line["trigger"]) == (
        "warning",
        "slow_consumer",
        "budget",
    )
    assert line["connection_id"] == conn.connection_id


async def test_a_step_3_redrop_close_names_its_trigger() -> None:
    """A `backpressure` snapshot larger than the budget, dropped three times before it is sent."""
    rig, sock = _Rig(BackpressureConfig(max_bytes=8192)), _Wire()
    rig.source.bodies["trades"] = SnapshotBody({"symbol": "BTCUSDT", "trades": []})
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handler, _ = await rig.open(sock)
            await rig.sub(sock, _TRADES)
            big = {"symbol": "BTCUSDT", "trades": [], "pad": "x" * 9000}
            rig.source.bodies["trades"] = SnapshotBody(big)
            rig.source.gen += 1
            rig.sequencing.publish(_TRADES, big)
            await handler
    (line,) = _lines(logs, "ws close")
    assert (line["log_level"], line["trigger"]) == ("warning", "redrop")


# -- row 2: `ws close deadline passed` -----------------------------------------------------------


async def test_the_flag_on_deadline_line_says_the_flush_was_abandoned_and_its_trigger() -> None:
    """A step 3 close whose flush also expires: the deadline line names step 3's trigger too."""
    rig, sock = _Rig(BackpressureConfig(max_frames=8, close_flush_s=0.01)), _Wire()
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handler, _ = await rig.open(sock)
            sock.hold()
            rig.hub.broadcast_system({"kind": "tick"})
            await sock.parked.wait()
            for i in range(9):
                rig.hub.broadcast_system({"kind": "tick", "n": i})
            await handler
    (line,) = _lines(logs, "ws close deadline passed")
    assert (line["log_level"], line["flush_abandoned"], line["trigger"]) == (
        "warning",
        True,
        "budget",
    )


# -- row 3: `ws connection ended` ----------------------------------------------------------------


async def test_a_server_close_ends_with_one_line_its_duration_and_class() -> None:
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handler, conn = await rig.open(sock)
            rig.clock.now += 2.5
            conn.close_with("heartbeat_timeout")
            await handler
    (close,) = _lines(logs, "ws close")
    (line,) = _lines(logs, "ws connection ended")
    assert line == {
        "event": "ws connection ended",
        "log_level": "info",
        "connection_id": conn.connection_id,
        "initiator": "server",
        "close_code": close["code"],
        "reason": "heartbeat_timeout",
        "duration_ms": 2500,
        "authenticated": True,
        "connection_class": "healthy",
    }


@pytest.mark.parametrize("authenticate", [True, False], ids=["authenticated", "unauthenticated"])
async def test_a_client_disconnect_ends_with_one_line_and_a_class_once_attached(
    authenticate: bool,
) -> None:
    """The class is the pipeline's last: none before the first `auth_ok` attaches it."""
    rig, sock = _Rig(), _Wire()
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            if authenticate:
                handler, conn = await rig.open(sock)
            else:
                handler = asyncio.create_task(rig.endpoint(sock))
                sock.feed({"t": "hello", "id": "h"})
                await sock.next()
                (conn,) = rig.hub._live
            rig.clock.now += 0.25
            sock.inbound.put_nowait({"type": "websocket.disconnect", "code": 1001})
            await handler
    (line,) = _lines(logs, "ws connection ended")
    assert line == {
        "event": "ws connection ended",
        "log_level": "info",
        "connection_id": conn.connection_id,
        "initiator": "client",
        "close_code": 1001,
        "reason": "client_closed",
        "duration_ms": 250,
        "authenticated": authenticate,
    } | ({"connection_class": "healthy"} if authenticate else {})


async def test_an_unauthenticated_server_close_ends_with_one_line() -> None:
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handler = asyncio.create_task(rig.endpoint(sock))
            sock.feed({"t": "hello", "id": "h"})
            await sock.next()
            (conn,) = rig.hub._live
            conn.close_with("auth_timeout")
            await handler
    (line,) = _lines(logs, "ws connection ended")
    assert (line["initiator"], line["reason"], line["authenticated"]) == (
        "server",
        "auth_timeout",
        False,
    )
    assert line["log_level"] == "info" and "connection_class" not in line  # never attached


async def test_a_fault_ends_with_one_warning_line() -> None:
    """`internal_error` alone raises the line to `warning`: the server's 1011."""
    rig, sock = _Rig(BackpressureConfig()), _Wire()
    rig.expires_at = rig.expires_at.replace(tzinfo=None)  # an authenticator contract fault
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handler = asyncio.create_task(rig.endpoint(sock))
            sock.feed({"t": "hello", "id": "h"})
            await sock.next()
            sock.feed({"t": "auth", "id": "a", "p": {"access_token": _ACCESS}})
            await handler
    (line,) = _lines(logs, "ws connection ended")
    assert (line["log_level"], line["reason"], line["close_code"], line["initiator"]) == (
        "warning",
        "internal_error",
        1011,
        "server",
    )
    assert _MARK not in repr(logs)


async def test_no_close_line_carries_the_token() -> None:
    rig, sock = _Rig(BackpressureConfig(max_frames=8)), _Wire()
    with capture_logs() as logs:
        async with asyncio.timeout(_DEADLINE_S):
            handler = asyncio.create_task(rig.endpoint(sock))
            sock.feed({"t": "hello", "id": "h"})
            await sock.next()
            sock.feed({"t": "auth", "id": "a", "p": {"access_token": _ACCESS}})
            assert [f["t"] for f in await sock.next()] == ["auth_ok"]
            for i in range(9):
                rig.hub.broadcast_system({"kind": "tick", "n": i})
            await handler
    assert _lines(logs, "ws close") and _lines(logs, "ws connection ended")
    assert _MARK not in repr(logs)
    assert all("connection_id" in e for e in logs if e["event"].startswith("ws "))


# -- row 4: `ws overflow drop` -------------------------------------------------------------------


def _overflow_twice(pipe: Any, conn: Any, book: Any) -> None:
    """Five book deltas against four frames: step 1 drops the book; the writer's turn queues its
    `backpressure` snapshot, which is then sent."""
    for i in range(5):
        conn.emitter.delta(book, _bid(i))
    pipe.service(conn.clock.now)
    _queued(pipe)


async def test_a_step_1_drop_logs_one_capped_warning_per_connection_per_10_s() -> None:
    pipe, _, conn = _attached(max_frames=4, classify_interval_ms=600_000)
    book = _structured(conn, _BOOK)
    _queued(pipe)
    with capture_logs() as logs:
        _overflow_twice(pipe, conn, book)
        (first,) = _lines(logs, "ws overflow drop")
        conn.clock.now += pipeline.OVERFLOW_LOG_WINDOW_S / 2
        _overflow_twice(pipe, conn, book)  # within the window: held back
        assert len(_lines(logs, "ws overflow drop")) == 1
        conn.clock.now += pipeline.OVERFLOW_LOG_WINDOW_S / 2  # the window ends: the next counts
        _overflow_twice(pipe, conn, book)
    first, second = _lines(logs, "ws overflow drop")
    assert first == {
        "event": "ws overflow drop",
        "log_level": "warning",
        "connection_id": "ws_test",
        "topics": [_BOOK],
        "shed": 1,
        "queue_pct_before": 125.0,
        "queue_pct_after": 0.0,
        "trigger": "budget",
        "suppressed": 0,
    }
    assert second["suppressed"] == 1


def test_a_drop_event_ranks_its_topics_largest_first_and_keeps_its_name_order() -> None:
    """Over the share alone every `bars` topic goes: the event's topics stay sorted by name (the
    ladder's contract), its `ranked` order is by queued bytes, and `pct_before` is the depth the
    check found."""
    conn, _, queue, ladder, subs, _ = _share_rig(max_bytes=60_000)  # a share of 20 frames
    five = _sub(conn, queue, "bars.BTCUSDT.time.5")
    conn.emitter.delta(subs[0], _bars(1))
    for i in range(21):
        conn.emitter.delta(five, _bars(i))
    depth = queue.pct()
    (event,) = ladder.check([*subs, five])
    assert event == LadderEvent("drop", (_BARS, five.ch), "share")
    assert (event.ranked, event.pct_before) == ((five.ch, _BARS), depth)


def test_the_drop_line_names_at_most_five_topics_largest_first_and_the_share_trigger() -> None:
    pipe, _, _ = _attached()
    ranked = tuple(f"book.SYM{i}USDT.50" for i in range(7))
    event = LadderEvent("drop", tuple(sorted(ranked)), "share", ranked=ranked, pct_before=60.0)
    with capture_logs() as logs:
        pipe._apply([event])
    (line,) = _lines(logs, "ws overflow drop")
    assert (line["topics"], line["shed"], line["trigger"]) == (list(ranked[:5]), 7, "share")
    assert (line["queue_pct_before"], line["log_level"]) == (60.0, "warning")
