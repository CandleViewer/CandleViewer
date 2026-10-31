"""E17-T03 (#412): `create_app` and the outbound budget.

The composition root always hands `make_ws_router` a `BackpressureConfig` built from the budget
settings (#2409 removed `CV_WS_BACKPRESSURE_ENABLED`), and `welcome.features.coalescing` is `true`
through the real handshake (`23-ws-protocol.md` §4.2). A sibling of `test_app_wiring.py`.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from candleviewer import app as app_module
from candleviewer.app import create_app
from candleviewer.settings import Environment, Settings
from candleviewer.ws import gateway
from candleviewer.ws.backpressure_config import BackpressureConfig

JSON = ["cv.v1.json"]
ORIGIN = "http://testserver"  # §2.5: in CV_ALLOWED_ORIGINS and sent on every upgrade


def _settings(**overrides: Any) -> Settings:
    return Settings(environment=Environment.DEMO, allowed_origins=ORIGIN, **overrides)


def _spy_on_the_router(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record the keyword arguments `create_app` gives `make_ws_router`, then build it for real."""
    seen: list[dict[str, Any]] = []
    real = gateway.make_ws_router

    def spy(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(app_module, "make_ws_router", spy)
    return seen


@pytest.mark.parametrize(
    ("budget", "expected"),
    [
        ({}, BackpressureConfig()),
        (
            {"ws_queue_bytes": 5_000_000, "ws_queue_frames": 300, "ws_classify_interval_ms": 750},
            BackpressureConfig(max_bytes=5_000_000, max_frames=300, classify_interval_ms=750),
        ),
    ],
    ids=["contract_budget", "settings_budget"],
)
def test_create_app_passes_the_budget_settings(
    monkeypatch: pytest.MonkeyPatch, budget: dict[str, int], expected: BackpressureConfig
) -> None:
    seen = _spy_on_the_router(monkeypatch)

    create_app(_settings(**budget))

    (kwargs,) = seen
    assert kwargs["backpressure"] == expected


def test_welcome_advertises_coalescing() -> None:
    """The pipeline always coalesces (§8.2), so `coalescing` is `true` beside `replay` and
    `binary_payloads`."""
    app = create_app(_settings())

    with TestClient(app, client=("127.0.0.1", 50000), headers={"origin": ORIGIN}) as client:
        with client.websocket_connect("/ws", subprotocols=JSON) as ws:
            ws.send_json({"t": "hello", "id": "h", "p": {"clock_ms": 1}})
            welcome = ws.receive_json()

    assert welcome["t"] == "welcome"
    assert welcome["p"]["features"] == {
        "replay": True,
        "binary_payloads": True,
        "coalescing": True,
    }
