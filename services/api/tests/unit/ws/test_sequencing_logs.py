"""E17-T06 (#571): the sequencing layer's log lines (`23-ws-protocol.md` §7.7).

`ws resync` (every `snap` but `initial`) is a `warning` for the two incidents 23 §7.4 names and
`info` for the rest; the incident set is written out below, not read from the module, so widening
or narrowing it fails here. `ws client resync` records what a client said (its reason, and its
`last_seq` only when a log line can carry it) beside the server's own `server_seq`, and
`ws resync rate limited` marks the resync that revokes. Each field set is asserted whole, so a
token, a payload or other client text cannot join a line unnoticed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, cast

import orjson
import pytest
from structlog.testing import capture_logs

from candleviewer.ws.limits import REBUILD_MAX_PER_TOPIC, REBUILD_WINDOW_S
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import (
    CLIENT_RESYNC_REASONS,
    COUNTED_SNAP_REASONS,
    SnapReason,
)
from tests.unit.ws._seq_support import Conn
from tests.unit.ws.test_sequencing import _book_source, _resync

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
