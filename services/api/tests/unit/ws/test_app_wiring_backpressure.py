"""E17-T03 (#412): `create_app` and the backpressure flag (`CV_WS_BACKPRESSURE_ENABLED`).

The composition root hands `make_ws_router` a `BackpressureConfig`, built from the budget settings,
only while the flag is on; off (the default) it passes none and the gateway keeps today's path.
`welcome.features.coalescing` mirrors the flag through the real handshake (`23-ws-protocol.md`
§4.2). A sibling of `test_app_wiring.py`, which other open PRs edit at its tail (C-4.15).
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
    "budget",
    [{}, {"ws_queue_bytes": 5_000_000, "ws_queue_frames": 300}],
    ids=["defaults", "budget_set"],
)
def test_create_app_passes_no_backpressure_config_while_the_flag_is_off(
    monkeypatch: pytest.MonkeyPatch, budget: dict[str, int]
) -> None:
    """Off is the default, and the budget settings alone change nothing: only the flag selects
    the pipeline."""
    seen = _spy_on_the_router(monkeypatch)

    create_app(_settings(**budget))

    (kwargs,) = seen
    assert kwargs.get("backpressure") is None


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
def test_create_app_passes_the_budget_settings_while_the_flag_is_on(
    monkeypatch: pytest.MonkeyPatch, budget: dict[str, int], expected: BackpressureConfig
) -> None:
    seen = _spy_on_the_router(monkeypatch)

    create_app(_settings(ws_backpressure_enabled=True, **budget))

    (kwargs,) = seen
    assert kwargs["backpressure"] == expected


@pytest.mark.parametrize("flag", [False, True], ids=["off", "on"])
def test_welcome_coalescing_feature_mirrors_the_flag(flag: bool) -> None:
    """Off it honestly reads `false` (nothing coalesces); `replay` and `binary_payloads` are not
    the flag's to change."""
    app = create_app(_settings(ws_backpressure_enabled=flag))

    with TestClient(app, client=("127.0.0.1", 50000), headers={"origin": ORIGIN}) as client:
        with client.websocket_connect("/ws", subprotocols=JSON) as ws:
            ws.send_json({"t": "hello", "id": "h", "p": {"clock_ms": 1}})
            welcome = ws.receive_json()

    assert welcome["t"] == "welcome"
    assert welcome["p"]["features"] == {
        "replay": True,
        "binary_payloads": True,
        "coalescing": flag,
    }
