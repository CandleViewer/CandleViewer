"""#2484 gap 2 (E17-S01 security notes): the WS access token never reaches a log line, a frame,
an audit record or a metric. Three sockets drive every token path:
- three failed auths (the 3rd closes and is audited)
- an auth, an in-place re-auth, then the token's expiry
- an auth, then a session revocation

Every sink is captured and scanned for a marker that only the tokens carry: structlog events,
stdlib logging, stdout/stderr, every raw frame received, the audit records, and the `cv_ws_*`
exposition `/metrics` serves."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Final

import pytest
from prometheus_client import CollectorRegistry, generate_latest
from starlette.websockets import WebSocketDisconnect
from structlog.testing import capture_logs

from candleviewer.ws.metrics import export_ws_metrics
from tests.unit.ws.test_lifecycle_socket import JSON, SESSION, TOKEN_TTL_S, _advance, _World

_MARK: Final = "c4f9e2a1b7d3"
#: Fake test tokens carrying the marker; `good-` passes the world's fake authenticator.
_GOOD: Final = f"good-{_MARK}-1"
_GOOD2: Final = f"good-{_MARK}-2"
_BAD: Final = f"bad-{_MARK}"
_TIMEOUT_S: Final = 5.0


class _Wire:
    """Sends frames and records every raw frame text received, until the socket closes."""

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.closes: list[int] = []

    def recv(self, ws: Any) -> dict[str, Any] | None:
        """The next frame, or None once the socket closed (its code is recorded)."""
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            text = pool.submit(ws.receive_text).result(timeout=_TIMEOUT_S)
        except WebSocketDisconnect as exc:
            self.closes.append(int(exc.code))
            return None
        except FutureTimeout:
            pytest.fail(f"no WS frame within {_TIMEOUT_S}s")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        self.texts.append(text)
        frame: dict[str, Any] = json.loads(text)
        return frame

    def send(self, ws: Any, frame: dict[str, Any]) -> dict[str, Any] | None:
        ws.send_json(frame)
        return self.recv(ws)

    def until_closed(self, ws: Any) -> list[dict[str, Any]]:
        frames = []
        while (frame := self.recv(ws)) is not None:
            frames.append(frame)
        return frames


def _auth(token: str, fid: str) -> dict[str, Any]:
    return {"t": "auth", "id": fid, "p": {"access_token": token}}


def test_ws_access_token_never_reaches_a_log_frame_audit_record_or_metric(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    registry = CollectorRegistry()
    export_ws_metrics(registry, env="test")
    rejected = {"env": "test", "reason": "rejected"}
    rejected_before = registry.get_sample_value("cv_ws_auth_failures_total", rejected) or 0.0
    wire = _Wire()
    w = _World()
    with capture_logs() as events, w.client:
        with w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
            wire.send(ws, {"t": "hello", "id": "h"})
            for i in range(2):
                err = wire.send(ws, _auth(_BAD, f"a{i}"))
                assert err is not None and err["p"]["code"] == "auth_failed"
            ws.send_json(_auth(_BAD, "a2"))
            assert [f["t"] for f in wire.until_closed(ws)] == ["bye"]

        with w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
            wire.send(ws, {"t": "hello", "id": "h"})
            assert (wire.send(ws, _auth(_GOOD, "a1")) or {})["t"] == "auth_ok"
            assert (wire.send(ws, _auth(_GOOD2, "a2")) or {})["t"] == "auth_ok"  # in place
            _advance(ws, w, TOKEN_TTL_S - 10)
            w.clock.now = TOKEN_TTL_S + 1.0
            bye = wire.until_closed(ws)[-1]
            assert (bye["t"], bye["p"]["reason"]) == ("bye", "token_expired")

        with w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
            wire.send(ws, {"t": "hello", "id": "h"})
            assert (wire.send(ws, _auth(_GOOD, "a1")) or {})["t"] == "auth_ok"
            assert w.client.portal.call(w.revocation.revoke, SESSION) == 1  # type: ignore[union-attr]  # set in ctx
            assert wire.until_closed(ws)[-1]["t"] == "bye"

    exposition = generate_latest(registry).decode()
    out, err_out = capsys.readouterr()
    sinks = {
        "structlog": repr(events),
        "logging": caplog.text,
        "stdout/stderr": out + err_out,
        "frames": "\n".join(wire.texts),
        "audit": repr(w.audit.records),
        "metrics": exposition,
    }
    leaked = [name for name, text in sinks.items() if _MARK in text]
    assert leaked == [], f"the access token reached: {leaked}"
    # Not vacuous: every token path ran and each sink saw it.
    assert len(wire.closes) == 3 and len(wire.texts) >= 9
    assert any(e.get("event") == "ws authenticated" and e.get("reauth") for e in events)
    failed = [e["attempt"] for e in events if e.get("event") == "ws auth failed"]
    assert failed == [1, 2, 3]  # the 1st socket's failed auths logged lines, and the scan saw them
    # The 3rd failed `auth`, plus one `ws.connection.closed` row per authenticated close (#2486);
    # every row reached the audit sink scanned above, so none of them carries the token either.
    actions = [r["action"] for r in w.audit.records]
    assert actions.count("auth.login_failed") == 1
    assert set(actions) == {"auth.login_failed", "ws.connection.closed"}
    # One row per authenticated close: the 2nd and 3rd sockets. The 1st never authenticated, so its
    # close writes none (its 3rd failed `auth` is the `auth.login_failed` row above).
    assert actions.count("ws.connection.closed") == 2
    assert registry.get_sample_value("cv_ws_auth_failures_total", rejected) == rejected_before + 3
