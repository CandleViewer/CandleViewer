"""E21-X02 (#652; 23 §8.4 "Degradation record", §16.2 "Degradation log lines"; the threat model's
G-10, its server half): a class change and a §8.4 step 1 drop each write one structured line,
naming the connection, the acting user, the families, from and to and the wall time, and each kind
logs at most once per connection per `OVERFLOW_LOG_WINDOW_S`, the next counting the ones held back.
A pipeline attached to a `Conn` (`_attached`), on its fake clock; the RTT probe drives the class:
answered at once it reads healthy, left unanswered for a second it reads `saturated` (§8.3)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from structlog.testing import capture_logs

from candleviewer.ws import pipeline
from candleviewer.ws.pipeline import ConnectionPipeline
from tests.unit.ws._seq_support import USER, Conn
from tests.unit.ws.test_close_logs import _overflow_twice
from tests.unit.ws.test_lifecycle_socket import BASE_MS
from tests.unit.ws.test_pipeline_ladder import _attached, _structured
from tests.unit.ws.test_pipeline_outbound import _BOOK, _queued
from tests.unit.ws.test_pipeline_quality import _HEATMAP, _degradable, _turn

_CHANGED = "ws connection class changed"
_DROP = "ws overflow drop"
VIEWER = uuid.UUID(int=0x652)


def _lines(logs: Iterable[Mapping[str, Any]], event: str) -> list[Mapping[str, Any]]:
    return [e for e in logs if e["event"] == event]


def _tick(pipe: ConnectionPipeline, conn: Conn, now: float, *, answer: bool) -> list[str]:
    """The writer's turn at `now` on both clocks; with `answer`, every probe it sent is answered
    at once (an RTT of 0). The probe ids it sent."""
    conn.clock.now = now
    _, pings = _turn(pipe, now)
    if answer:
        for probe in pings:
            pipe.pong(probe, now)
    return pings


def _classified(viewer: uuid.UUID | None = None) -> tuple[ConnectionPipeline, Conn]:
    """A pipeline holding a heatmap (a family `saturated` degrades) and a book, healthy at 1 s."""
    pipe, _, conn = _attached()
    conn.authz.viewer_user_id = viewer
    _degradable(conn)
    for ch in (_HEATMAP, _BOOK):
        _structured(conn, ch)
    _queued(pipe)
    _tick(pipe, conn, 1.0, answer=True)
    return pipe, conn


def _saturate(pipe: ConnectionPipeline, conn: Conn, at: float) -> None:
    """A probe sent at `at` and left unanswered: `saturated` one classification later."""
    (probe,) = _tick(pipe, conn, at, answer=False)
    _tick(pipe, conn, at + 1, answer=False)
    pipe.pong(probe, at + 1)


def test_ac_hm_06_a_class_change_and_a_drop_each_write_one_capped_record() -> None:
    pipe, conn = _classified()
    with capture_logs() as logs:
        _saturate(pipe, conn, 2.0)  # the change: healthy to saturated at 3 s
        for now in (4.0, 5.0, 6.0):  # answered at once: healthy again at 6 s, inside the window
            _tick(pipe, conn, now, answer=True)
        assert len(_lines(logs, _CHANGED)) == 1  # the second change is held back
        for now in (7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0):
            _tick(pipe, conn, now, answer=True)
        _saturate(pipe, conn, 14.0)  # the third change, at 15 s: past the window, counts one
    first, second = _lines(logs, _CHANGED)
    assert first == {
        "event": _CHANGED,
        "log_level": "warning",
        "connection_id": "ws_test",
        "actor_user_id": str(USER),
        "class_from": "healthy",
        "class_to": "saturated",
        "families": ["heatmap"],  # the book is throttled, not degraded (§8.3)
        "at_ms": BASE_MS,
        "suppressed": 0,
    }
    assert (second["class_from"], second["class_to"], second["suppressed"]) == (
        "healthy",
        "saturated",
        1,
    )
    # the drop: a book over a four-frame budget, as `test_close_logs` drives it
    pipe, _, conn = _attached(max_frames=4, classify_interval_ms=600_000)
    book = _structured(conn, _BOOK)
    _queued(pipe)
    with capture_logs() as logs:
        _overflow_twice(pipe, conn, book)
        conn.clock.now += pipeline.OVERFLOW_LOG_WINDOW_S / 2  # inside the window: held back
        _overflow_twice(pipe, conn, book)
    (drop,) = _lines(logs, _DROP)
    assert (drop["connection_id"], drop["actor_user_id"]) == ("ws_test", str(USER))
    assert (drop["families"], drop["at_ms"], drop["topics"]) == (["book"], BASE_MS, [_BOOK])


def test_a_degradation_record_names_the_viewer_under_view_as() -> None:
    """§9.6: the viewer acts on a socket that views as another user, so the record names the
    viewer, never the target whose principal the socket holds."""
    pipe, conn = _classified(viewer=VIEWER)
    with capture_logs() as logs:
        _saturate(pipe, conn, 2.0)
    (changed,) = _lines(logs, _CHANGED)
    assert changed["actor_user_id"] == str(VIEWER) != str(conn.authz.principal.user_id)
