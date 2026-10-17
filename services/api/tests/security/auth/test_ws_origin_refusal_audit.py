"""E09-X02 AC-CSRF-11 (#2269): cross-site WebSocket hijacking attempts leave an audit trail.

A cross-site page in a signed-in browser loops `new WebSocket('/ws')`. Through the real
`create_app()` stack (MeshOnly, the SR-042 / SR-183 upgrade check and an audit writer that refuses
unregistered actions as the real one does): every upgrade is refused `4403` before `accept` and
counted, and the refusals are audited as `auth.ws_origin_refused` up to the per-source budget
(C-2.9 vs C-2.18), never with a header value.
"""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.ws.lifecycle import ORIGIN_FORBIDDEN
from candleviewer.ws.metrics import cv_ws_closes_total
from candleviewer.ws.origin_audit import REFUSAL_AUDITS_PER_WINDOW
from tests.security.auth._stack import open_stack

CROSS_SITE = {"origin": "https://evil.example", "sec-fetch-site": "cross-site"}


def _closes() -> float:
    for family in cv_ws_closes_total.collect():
        for s in family.samples:
            if s.name == "cv_ws_closes_total" and s.labels.get("reason") == ORIGIN_FORBIDDEN:
                return float(s.value)
    return 0.0


def test_ac_csrf_11_cross_site_socket_flood_is_refused_counted_and_audited_within_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flood = REFUSAL_AUDITS_PER_WINDOW + 5
    codes: list[int] = []
    with open_stack(monkeypatch) as stack:
        closes = _closes()
        for _ in range(flood):
            with pytest.raises(WebSocketDisconnect) as exc:
                with stack.client.websocket_connect(
                    "/ws", subprotocols=["cv.v1.json"], headers=CROSS_SITE
                ):
                    pass
            codes.append(int(exc.value.code))
        rows = stack.audit.of("auth.ws_origin_refused")
    assert codes == [4403] * flood
    assert _closes() == closes + flood  # every refusal counted, audited or not
    row = {
        "action": "auth.ws_origin_refused",
        "actor_label": "(unknown)",
        "actor_ip": "127.0.0.1",  # the address MeshOnly admitted
        "object_kind": "ws_upgrade",
        "outcome": AuditOutcome.FAILURE,
        "severity": Severity.WARNING,
        "reason": "cross_site",
    }
    assert rows == [row] * REFUSAL_AUDITS_PER_WINDOW  # capped; never a header value
