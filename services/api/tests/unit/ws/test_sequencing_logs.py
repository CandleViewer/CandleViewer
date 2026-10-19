"""E17-T06 (#571): the sequencing layer's log lines (`23-ws-protocol.md` §7.7).

`ws resync` (every `snap` but `initial`) is a `warning` for the two incidents 23 §7.4 names and
`info` for the rest; the incident set is written out below, not read from the module, so widening
or narrowing it fails here. `ws client resync` records what a client said (its reason, and its
`last_seq` only when a log line can carry it) beside the server's own `server_seq`, and names the
stream both numbers belong to: `ch`, and `rs` when it is a replay session's, as the server spells
it (#3371). So do `ws resync` and `ws resync rate limited` (#3690), the latter for a refused
`resync`, `ctl` or `sub`; it also marks the resync that revokes. Each field set is asserted
whole, so a token, a payload or other client text cannot join a line unnoticed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from typing import Any, cast
from unittest.mock import AsyncMock

import orjson
import pytest
from structlog.testing import capture_logs

from candleviewer.ws.lifecycle import REFUSAL_LOG_LIMIT
from candleviewer.ws.limits import (
    REBUILD_MAX_PER_CONNECTION,
    REBUILD_MAX_PER_TOPIC,
    REBUILD_WINDOW_S,
)
from candleviewer.ws.permissions import Subscription, handle_ctl, handle_sub
from candleviewer.ws.sequencing import (
    CLIENT_RESYNC_REASONS,
    COUNTED_SNAP_REASONS,
    SnapReason,
)
from tests.unit.ws._seq_support import Conn
from tests.unit.ws.test_sequencing import RS, _book_source, _resync

_CH = "book.BTCUSDT.50"
_CONN = "ws_test"  # `Conn`'s connection id
_INCIDENTS = frozenset({"upstream_desync", "backpressure"})  # 23 §7.4, not `INCIDENT_REASONS`


def _attached() -> tuple[Conn, Subscription]:
    conn = Conn(_book_source())
    _, sub = conn.sub(_CH)  # the `initial` snapshot takes sequence number 1
    conn.take()
    return conn, sub


def _lines(logs: Iterable[Mapping[str, Any]], event: str) -> list[Mapping[str, Any]]:
    return [e for e in logs if e["event"] == event]


def _twinned() -> tuple[Conn, Subscription]:
    """`_CH` held live and in replay session `RS` by one connection: two streams, two sequences.
    The live stream's numbers go on to 3 (two deltas) while its replay twin's stays at 1."""
    conn = Conn(_book_source())
    _, live = conn.sub(_CH)
    _, twin = conn.sub(_CH, replay_session_id=RS)
    for i in range(2):
        delta = {"symbol": "BTCUSDT", "bids": [[f"{i}.5", "1"]], "asks": []}
        assert conn.emitter.delta(live, delta)
    conn.take()
    return conn, twin


def _resync_in(conn: Conn, rs: str, **p: Any) -> None:
    """A `resync` of `_CH` naming the replay session `rs`, spelled as the client wrote it."""
    frame = {"t": "resync", "id": "c-91", "ch": _CH, "rs": rs, "p": {"reason": "manual", **p}}
    conn.emitter.client_resync(conn.authz, frame)


_RS2 = "bb000000-0000-4000-8000-000000000002"  # a second replay session of `_CH`
_MIXED = "Bb000000-0000-4000-8000-000000000002"  # `_RS2` in mixed case


def _streams() -> tuple[Conn, dict[str | None, Subscription]]:
    """`_CH` held live and in the replay sessions `RS` and `_RS2`: three streams, three sequences.
    The `initial` snapshot took 1 of each; two deltas on the live one and one on `_RS2` took more,
    so they stand at 3, 1 and 2."""
    conn = Conn(_book_source())
    conn.authz.connection_id = _CONN  # the gateway gives the authz and the emitter one id
    held = {rs: conn.sub(_CH, replay_session_id=rs)[1] for rs in (None, RS, _RS2)}
    for rs, deltas in ((None, 2), (_RS2, 1)):
        for i in range(deltas):
            delta = {"symbol": "BTCUSDT", "bids": [[f"{i}.5", "1"]], "asks": []}
            assert conn.emitter.delta(held[rs], delta)
    conn.take()
    return conn, held


@pytest.mark.parametrize("reason", COUNTED_SNAP_REASONS)
def test_ws_resync_is_a_warning_for_an_incident_reason_and_info_for_the_rest(reason: str) -> None:
    conn, sub = _attached()
    with capture_logs() as logs:
        assert conn.emitter.snapshot(sub, cast("SnapReason", reason))
    assert logs == [
        {
            "event": "ws resync",
            "log_level": "warning" if reason in _INCIDENTS else "info",
            "connection_id": _CONN,
            "ch": _CH,
            "reason": reason,
            "previous_seq": 1,
        }
    ]


def test_the_initial_snapshot_is_an_attach_and_logs_nothing() -> None:
    with capture_logs() as logs:
        _attached()
    assert logs == []


@pytest.mark.parametrize("reason", COUNTED_SNAP_REASONS)
def test_ws_resync_of_a_replay_stream_names_its_session_and_logs_its_own_number(
    reason: str,
) -> None:
    conn, streams = _streams()
    with capture_logs() as logs:
        for sub in streams.values():
            assert conn.emitter.snapshot(sub, cast("SnapReason", reason))
    line = {
        "event": "ws resync",
        "log_level": "warning" if reason in _INCIDENTS else "info",
        "connection_id": _CONN,
        "ch": _CH,
        "reason": reason,
    }
    assert logs == [  # the live line keeps no `rs` key beside its twins' lines
        line | {"previous_seq": 3},
        line | {"rs": RS, "previous_seq": 1},
        line | {"rs": _RS2, "previous_seq": 2},
    ]


@pytest.mark.parametrize("spelled", [_RS2.upper(), _MIXED], ids=["upper-case", "mixed-case"])
def test_the_snapshot_answering_a_resync_in_another_letter_case_logs_the_canonical_rs(
    spelled: str,
) -> None:
    conn, _ = _streams()
    with capture_logs() as logs:
        _resync_in(conn, spelled, last_seq=7)  # the client says 7; the stream's number is 2
    (answer,) = _lines(logs, "ws resync")
    assert answer == {
        "event": "ws resync",
        "log_level": "info",
        "connection_id": _CONN,
        "ch": _CH,
        "rs": _RS2,
        "reason": "client_resync",
        "previous_seq": 2,
    }
    assert spelled not in repr(logs)


@pytest.mark.parametrize("client_reason", sorted(CLIENT_RESYNC_REASONS))
def test_client_resync_logs_the_stated_reason_and_both_sequence_numbers(client_reason: str) -> None:
    conn, _ = _attached()
    with capture_logs() as logs:
        _resync(conn, _CH, reason=client_reason, last_seq=7)
    assert _lines(logs, "ws client resync") == [
        {
            "event": "ws client resync",
            "log_level": "warning" if client_reason == "sequence_gap" else "info",
            "connection_id": _CONN,
            "ch": _CH,
            "client_reason": client_reason,
            "client_last_seq": 7,
            "server_seq": 1,
        }
    ]
    (answer,) = _lines(logs, "ws resync")  # the `snap` that answers it logs the server's own reason
    assert (answer["log_level"], answer["reason"], answer["previous_seq"]) == (
        "info",
        "client_resync",
        1,
    )


def test_client_resync_after_deltas_logs_the_servers_current_sequence_number() -> None:
    conn, sub = _attached()
    for i in range(3):  # the `initial` snapshot took 1; three deltas take 2, 3 and 4
        assert conn.emitter.delta(sub, {"symbol": "BTCUSDT", "bids": [[f"{i}.5", "1"]], "asks": []})
    conn.take()
    with capture_logs() as logs:
        _resync(conn, _CH, last_seq=2)  # the client says it saw up to 2, the server had sent 4
    (line,) = _lines(logs, "ws client resync")
    assert (line["client_last_seq"], line["server_seq"]) == (2, 4)  # not the one snapshot built
    (answer,) = _lines(logs, "ws resync")
    assert answer["previous_seq"] == line["server_seq"]  # the two lines name the same number


@pytest.mark.parametrize("client_reason", sorted(CLIENT_RESYNC_REASONS))
def test_a_replay_streams_resync_logs_its_rs_and_its_own_server_seq(client_reason: str) -> None:
    conn, _ = _twinned()
    with capture_logs() as logs:
        _resync_in(conn, RS, reason=client_reason, last_seq=1)
    assert _lines(logs, "ws client resync") == [
        {
            "event": "ws client resync",
            "log_level": "warning" if client_reason == "sequence_gap" else "info",
            "connection_id": _CONN,
            "ch": _CH,
            "rs": RS,
            "client_reason": client_reason,
            "client_last_seq": 1,
            "server_seq": 1,  # the replay twin's own number, not the live stream's 3
        }
    ]


@pytest.mark.parametrize("live_rs", [{}, {"rs": None}], ids=["no-rs", "rs-null"])
def test_the_lines_of_a_live_stream_and_its_replay_twin_differ_only_by_rs_and_the_numbers(
    live_rs: dict[str, None],
) -> None:
    conn, _ = _twinned()
    p = {"reason": "manual", "last_seq": 3}
    live_frame = {"t": "resync", "id": "c-90", "ch": _CH, **live_rs, "p": p}
    with capture_logs() as logs:
        conn.emitter.client_resync(conn.authz, live_frame)
        _resync_in(conn, RS, reason="manual", last_seq=1)
    live_line, twin_line = _lines(logs, "ws client resync")
    assert (live_line["server_seq"], twin_line["server_seq"]) == (3, 1)
    assert "rs" not in live_line  # no key at all, not a null one
    assert twin_line["rs"] == RS
    assert set(twin_line) == set(live_line) | {"rs"}
    unlike = {"rs", "server_seq", "client_last_seq"}
    assert {k: v for k, v in twin_line.items() if k not in unlike} == {
        k: v for k, v in live_line.items() if k not in unlike
    }


@pytest.mark.parametrize(
    "spelled",
    [RS.upper(), "Bb000000-0000-4000-8000-000000000001"],
    ids=["upper-case", "mixed-case"],
)
def test_a_resync_naming_its_session_in_another_letter_case_logs_the_canonical_rs(
    spelled: str,
) -> None:
    conn, twin = _twinned()
    assert spelled != RS and spelled.lower() == RS == twin.replay_session_id
    with capture_logs() as logs:
        _resync_in(conn, spelled)
    (line,) = _lines(logs, "ws client resync")
    assert line["rs"] == RS  # the server's own form, however the client spelled it
    assert spelled not in repr(logs)
    assert [f["rs"] for f in conn.take() if f["t"] == "snap"] == [RS]  # and it named the twin


@pytest.mark.parametrize(
    ("last_seq", "logged"),
    [
        (0, True),
        (1, True),
        (2**53 - 1, True),
        (-1, False),
        (2**53, False),
        (10**30, False),
        (None, False),
    ],
)
def test_client_last_seq_is_logged_only_as_an_int_from_zero_below_two_to_the_53rd(
    last_seq: int | None, logged: bool
) -> None:
    conn, _ = _attached()
    with capture_logs() as logs:
        _resync(conn, _CH, last_seq=last_seq)
    (line,) = _lines(logs, "ws client resync")
    assert ("client_last_seq" in line) is logged
    if logged:
        assert line["client_last_seq"] == last_seq
    orjson.dumps(line, default=str)  # the log renderer: it raises on an int above 64 bits
    assert [f["t"] for f in conn.take()] == ["snap"]  # and the resync is answered all the same


@pytest.mark.parametrize("client_reason", ["sequence_gap", "manual"])
def test_the_sixth_resync_in_a_minute_logs_the_rate_limit_warning_and_no_snapshot(
    client_reason: str,
) -> None:
    conn, sub = _attached()
    with capture_logs() as logs:
        for i in range(REBUILD_MAX_PER_TOPIC):
            conn.clock.now = float(i)
            _resync(conn, _CH, reason=client_reason)
        assert _lines(logs, "ws resync rate limited") == []  # five are within the limit
        conn.clock.now = 59.0
        _resync(conn, _CH, reason=client_reason)
    assert len(_lines(logs, "ws client resync")) == REBUILD_MAX_PER_TOPIC + 1  # the refused too
    assert len(_lines(logs, "ws resync")) == REBUILD_MAX_PER_TOPIC  # no `snap` answered it
    assert _lines(logs, "ws resync rate limited") == [
        {
            "event": "ws resync rate limited",
            "log_level": "warning",
            "connection_id": _CONN,
            "ch": _CH,
            "client_reason": client_reason,  # the stated one, whichever it is
            "path": "resync",
            "scope": "topic",
            "limit": REBUILD_MAX_PER_TOPIC,
            "window_s": REBUILD_WINDOW_S,
        }
    ]
    assert conn.authz.find(sub.ch) is None  # the subscription was revoked, as before


_NEW = ("trades.BTCUSDT", "trades.ETHUSDT")  # topics that no stream of the connection holds
_NOBODY = "cc000000-0000-4000-8000-000000000003"  # a canonical session no stream has
_LIMITED = {  # the fields every `ws resync rate limited` line of a spent connection has
    "event": "ws resync rate limited",
    "log_level": "warning",
    "connection_id": _CONN,
    "ch": _CH,
    "scope": "connection",
    "limit": REBUILD_MAX_PER_CONNECTION,
    "window_s": REBUILD_WINDOW_S,
}
_SAYS: dict[str, dict[str, Any]] = {  # and what the line of each path adds
    "resync": {"path": "resync", "client_reason": "manual"},
    "ctl": {"path": "ctl"},
    "sub": {"path": "sub", "ch": _NEW[0], "count": len(_NEW)},  # the first refused topic's `ch`
}


def _spent(conn: Conn) -> None:
    """The connection's whole rebuild budget drawn: what it asks for now is refused at its limit."""
    for i in range(REBUILD_MAX_PER_CONNECTION):
        assert conn.authz.rebuilds.take((f"x.S{i:03d}", None), "ctl") is None


def _ask(conn: Conn, path: str, rs: str | None) -> str:
    """One `resync`, `ctl` (a resume: the only kind that draws) or `sub` (of two new topics) naming
    the replay session `rs` as the client wrote it (None: the live stream), sent as the gateway
    would; the code of the `err` that answers it."""
    named = {} if rs is None else {"rs": rs}
    if path == "resync":
        frame = {"t": "resync", "id": "c-93", "ch": _CH, **named, "p": {"reason": "manual"}}
        conn.emitter.client_resync(conn.authz, frame)
    elif path == "ctl":
        for paused in (True, False):
            frame = {"t": "ctl", "id": "c-94", "ch": _CH, **named, "p": {"paused": paused}}
            conn.push(handle_ctl(conn.authz, frame, 1))
    else:
        body = {"topics": list(_NEW)} | ({} if rs is None else {"replay_session_id": rs})
        send = AsyncMock(side_effect=conn.push)
        asyncio.run(handle_sub(conn.authz, {"t": "sub", "p": body}, send, now_ms=1))
    reply = conn.take()[-1]
    return str(reply["p"]["results"][0]["error"]["code"] if path == "sub" else reply["p"]["code"])


@pytest.mark.parametrize("path", ["resync", "ctl", "sub"])
@pytest.mark.parametrize(
    ("written", "rs"),
    [(None, None), (RS, RS), (_RS2, _RS2), (_RS2.upper(), _RS2), (_MIXED, _RS2)],
    ids=["live", "replay", "second-session", "upper-case", "mixed-case"],
)
def test_the_rate_limited_line_of_each_path_names_its_stream_as_the_server_spells_it(
    path: str, written: str | None, rs: str | None
) -> None:
    conn, _ = _streams()  # a live stream and two replay ones of `_CH`; the request names one
    _spent(conn)
    with capture_logs() as logs:
        assert _ask(conn, path, written) == "resync_rate_limited"
    assert _lines(logs, "ws resync rate limited") == [
        _LIMITED | _SAYS[path] | ({} if rs is None else {"rs": rs})
    ]
    assert written in (None, rs) or written not in repr(logs)  # the client's text is no field


@pytest.mark.parametrize("rs", [None, RS], ids=["live", "replay"])
def test_the_capped_line_names_the_stream_of_the_refusal_that_reached_the_cap(
    rs: str | None,
) -> None:
    conn, _ = _streams()
    _spent(conn)
    with capture_logs() as logs:
        for _ in range(REFUSAL_LOG_LIMIT + 2):  # the lines, the capped one, one only counted
            _ask(conn, "resync", rs)
    lines = _lines(logs, "ws resync rate limited")
    assert [line.get("capped") for line in lines] == [None] * REFUSAL_LOG_LIMIT + [True]
    assert lines[-1] == _LIMITED | _SAYS["resync"] | {"capped": True} | (
        {} if rs is None else {"rs": rs}
    )


@pytest.mark.parametrize(
    ("path", "rs", "code"),
    [
        ("resync", "x" * 4000, "invalid_options"),
        ("ctl", "x" * 4000, "invalid_options"),
        ("sub", "x" * 4000, "invalid_options"),
        ("resync", _NOBODY, "not_subscribed"),
        ("ctl", _NOBODY, "not_subscribed"),
    ],
    ids=["resync-malformed", "ctl-malformed", "sub-malformed", "resync-unknown", "ctl-unknown"],
)
def test_a_request_naming_no_stream_logs_nothing_and_gets_its_err(
    path: str, rs: str, code: str
) -> None:
    conn, _ = _streams()
    _spent(conn)  # a request that named a stream of the connection would be refused and logged
    with capture_logs() as logs:
        assert _ask(conn, path, rs) == code
    assert logs == []


@pytest.mark.parametrize(
    ("ch", "p"),
    [
        pytest.param(_CH, {"reason": "bogus"}, id="unknown-reason"),
        pytest.param(_CH, {"reason": "manual", "last_seq": "x"}, id="last-seq-not-an-int"),
        pytest.param(_CH, {"reason": "manual", "last_seq": True}, id="last-seq-a-bool"),
        pytest.param(_CH, "not-a-body", id="body-not-an-object"),
        pytest.param("trades.ETHUSDT", {"reason": "manual"}, id="not-subscribed"),
        pytest.param(None, {"reason": "manual"}, id="no-ch"),
        pytest.param("Bad Topic", {"reason": "manual"}, id="not-a-topic-name"),
    ],
)
def test_a_resync_the_server_refuses_logs_nothing(ch: Any, p: Any) -> None:
    conn, _ = _attached()
    with capture_logs() as logs:
        conn.emitter.client_resync(conn.authz, {"t": "resync", "id": "c-1", "ch": ch, "p": p})
    assert logs == []  # client text reaches a line only through a resync of a subscribed topic
    assert [f["t"] for f in conn.take()] == ["err"]


def test_other_content_of_a_resync_frame_is_never_logged() -> None:
    conn, _ = _attached()
    extra = {"access_token": "zz-secret-token", "note": "n" * 4000}
    with capture_logs() as logs:
        _resync(conn, _CH, last_seq=5, **extra)
    assert "zz-secret-token" not in repr(logs) and "nnnn" not in repr(logs)
