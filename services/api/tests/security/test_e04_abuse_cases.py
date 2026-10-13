"""E04-X02 abuse-case execution (in-process, fake backends, no network).

Case ids follow docs/security/reviews/E04-X02-observability-security-review.md section 2.
"""

from __future__ import annotations

import io
import json
import logging
import re
import uuid
from collections.abc import Iterator
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import structlog
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from candleviewer.api.telemetry import make_telemetry_router
from candleviewer.app import create_app
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.observability import logging as logging_mod
from candleviewer.observability.correlation import sanitize_correlation_id
from candleviewer.observability.logging import configure_logging
from candleviewer.observability.metrics import Metrics, MetricsError
from candleviewer.observability.metrics_server import MetricsBindError, parse_private_bind
from candleviewer.observability.support_bundle import BundleError, BundleSources, build_bundle
from candleviewer.observability.telemetry import (
    FrontendTelemetry,
    SessionRateLimiter,
    TelemetrySink,
)
from tests.csrf_helpers import arm_csrf, wire_fake_sessions

# Secret-shaped values are assembled at runtime so no literal sits in the repo.
FAKE_KEY = "AKIA" + "Zq9Xw3Lm" + "Pv7Rt2Yb" + "Nc4Hd"
FAKE_JWT = ".".join(
    ["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiJhYmNkZWYxMjM0NTYifQ", "c2lnbmF0dXJlMTIzNDU2Nzg5"]
)
FAKE_SECRET_KV = "api_secret=" + "Zq9" + "x" * 20 + "AbCd"
SECRET_SHAPES = (FAKE_KEY, FAKE_JWT, "Zq9" + "x" * 20 + "AbCd")


class _Resolver:
    def __init__(self) -> None:
        self.by_token: dict[str, PrincipalSnapshot] = {}

    def resolve(self, request: Request) -> PrincipalSnapshot | None:
        auth = request.headers.get("authorization", "")
        return self.by_token.get(auth.removeprefix("Bearer "))


@pytest.fixture
def world() -> TestClient:
    res = _Resolver()
    res.by_token["mgr"] = PrincipalSnapshot(
        user_id=uuid.uuid4(),
        roles=frozenset({"manager"}),
        permissions=frozenset({Permission.AUDIT_READ}),
    )
    app = create_app(principal_resolver=res)
    wire_fake_sessions(app, "mgr")
    return arm_csrf(TestClient(app, client=("127.0.0.1", 50000)), app.state.csrf_codec)


@pytest.fixture
def stdout_logs() -> Iterator[io.StringIO]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        configure_logging(env="ci", level="debug", fmt="json")
        yield buf
        if logging_mod._listener is not None:
            logging_mod._listener.stop()
            logging_mod._listener = None
    logging.getLogger().handlers = []
    structlog.reset_defaults()


def _flush(buf: io.StringIO) -> str:
    assert logging_mod._listener is not None
    logging_mod._listener.stop()
    logging_mod._listener = None
    return buf.getvalue()


# ---- Case 1: RBAC on admin diagnostics ------------------------------------------------

_WIN = {"from": "2026-10-01T00:00:00Z", "to": "2026-10-01T01:00:00Z"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/admin/health", None),
        ("post", "/admin/support-bundle", _WIN),
        ("put", "/admin/log-level", {"subsystem": "ws", "level": "debug", "ttl_seconds": 60}),
    ],
)
def test_case1_unauthenticated_and_manager_denied(
    world: TestClient, method: str, path: str, body: Any
) -> None:
    kw: dict[str, Any] = {"json": body} if body is not None else {}
    anon = getattr(world, method)(path, **kw)
    # 501 = fail-closed, never 2xx; an unsafe call with no session is refused by SR-041 first
    assert anon.status_code in ((401, 501) if method == "get" else (403,)), anon.text
    mgr = getattr(world, method)(path, headers={"Authorization": "Bearer mgr"}, **kw)
    assert mgr.status_code in (403, 501), mgr.text
    assert "postgres" not in mgr.text and "parquet" not in mgr.text


# ---- Case 2: /metrics exposure --------------------------------------------------------


def test_case2_metrics_bind_refuses_public_interfaces() -> None:
    for bad in ("0.0.0.0:9100", "8.8.8.8:9100", "[::]:9100", "example.com:9100"):
        with pytest.raises(MetricsBindError):
            parse_private_bind(bad)
    assert parse_private_bind("127.0.0.1:9100") == ("127.0.0.1", 9100)


def test_case2_metrics_body_has_no_secret_or_id_material(world: TestClient) -> None:
    world.get("/health/live", headers={"X-Correlation-Id": FAKE_KEY})
    text = world.get("/metrics").text
    for shape in SECRET_SHAPES:
        assert shape not in text
    assert not re.search(r'(order_?id|api_?key|session|email)="', text, re.I)


# ---- Case 3: log injection ------------------------------------------------------------


@pytest.mark.parametrize(
    "evil",
    [
        'abc\r\n{"level":"critical","event":"forged"}',
        "\x1b[31mRED\x1b[0m",
        "x" * 500,
        "00000000-0000-4000-8000-000000000000\r\nX-Injected: 1",
    ],
)
def test_case3_correlation_id_cannot_forge_or_inject(evil: str) -> None:
    out = sanitize_correlation_id(evil)
    uuid.UUID(out)
    assert "\n" not in out and "\r" not in out and "\x1b" not in out


def test_case3_http_header_injection_no_forged_log_line(
    world: TestClient, stdout_logs: io.StringIO
) -> None:
    r = world.get("/health/live", headers={"X-Correlation-Id": "abc\x1b[31m" + "y" * 80})
    uuid.UUID(r.headers["x-correlation-id"])
    for line in _flush(stdout_logs).splitlines():
        if line.strip():
            json.loads(line)  # every line is one intact JSON object


def test_case3_crlf_ansi_in_logged_field_stay_on_one_json_line(stdout_logs: io.StringIO) -> None:
    payload = 'BTCUSDT\r\n{"level":"critical","event":"forged"}\x1b[31m'
    structlog.get_logger("abuse").info("symbol_seen", symbol=payload)
    lines = [ln for ln in _flush(stdout_logs).splitlines() if ln.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "symbol_seen" and rec["level"] == "info"
    assert "\r" not in lines[0] and "\x1b" not in lines[0]


# ---- Case 3b: secret-shaped strings never reach logs / metrics -----------------------


def test_case3b_secrets_in_body_header_query_never_logged_or_metered(
    world: TestClient, stdout_logs: io.StringIO
) -> None:
    world.post(
        f"/telemetry/frontend?token={FAKE_JWT}&k={FAKE_KEY}",
        headers={
            "Authorization": f"Bearer {FAKE_JWT}",
            "X-Api-Key": FAKE_KEY,
            "Cookie": f"sid={FAKE_KEY}",
        },
        content=json.dumps({"screen": FAKE_KEY, "note": FAKE_SECRET_KV}),
    )
    log = structlog.get_logger("abuse")
    log.warning("echo", detail=f"user sent {FAKE_SECRET_KV}", api_key=FAKE_KEY)
    logging.getLogger("third_party").error("boom %s", FAKE_JWT)
    out = _flush(stdout_logs)
    metrics = world.get("/metrics").text
    for shape in SECRET_SHAPES:
        assert shape not in out
        assert shape not in metrics


# ---- Case 4: support bundle / system_events ------------------------------------------

T1 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
T0 = T1 - timedelta(hours=1)
_CHANNELS: dict[str, Any] = {
    "logs": lambda a, b: [FAKE_SECRET_KV],
    "metrics": lambda: "x 1 " + FAKE_SECRET_KV + "\n",
    "health": lambda: {"detail": FAKE_SECRET_KV},
    "system_events": lambda a, b: [{"msg": FAKE_SECRET_KV}],
    "alerts": lambda: [{"annotation": FAKE_SECRET_KV}],
}


def _sources(**over: Any) -> BundleSources:
    base: dict[str, Any] = {
        "logs": lambda a, b: ["l1"],
        "metrics": lambda: "up 1\n",
        "health": lambda: {"overall": "healthy"},
        "system_events": lambda a, b: [{"kind": "x"}],
        "alerts": lambda: [],
        "build_info": lambda: {"version": "1"},
        "config": lambda: {"CV_ENV": "demo"},
    }
    base.update(over)
    return BundleSources(**base)


@pytest.mark.parametrize("channel", sorted(_CHANNELS))
def test_case4_secret_in_any_bundle_channel_fails_generation(tmp_path: Path, channel: str) -> None:
    src = _sources(**{channel: _CHANNELS[channel]})
    with pytest.raises(BundleError) as ei:
        build_bundle(src, tmp_path, T0, T1, free_bytes=lambda p: 10**12)
    assert ei.value.code == "BUNDLE_SECRET_DETECTED"
    assert not list(tmp_path.glob("*.zip"))


# ---- Case 5: cardinality bomb ---------------------------------------------------------


def test_case5_disallowed_label_names_rejected_and_series_capped() -> None:
    m = Metrics("demo")
    for bad in ("api_key", "session_id", "email", "token"):
        with pytest.raises(MetricsError):
            m.counter(f"abuse_{bad}_total", "x", labels=(bad,))
    c = m.counter("abuse_bomb_total", "x", labels=("screen",), max_series=10)
    for i in range(5000):
        c.labels(f"R-{i:03d}").inc()
    assert c.series_count <= 10 and c.breached
    assert m.total_series() < 100


def test_case5_telemetry_screen_label_is_pattern_bound() -> None:
    base: dict[str, Any] = {
        "engine_version": "0.1.0",
        "fe_frame_time_ms": {"counts": [0] * 9},
        "fe_ws_decode_ms": {"counts": [0] * 9},
        "fe_dropped_frames_total": 0,
    }
    for screen in ("BTCUSDT", "R-1000", FAKE_KEY, "R-100\n", "../x"):
        with pytest.raises(ValidationError):
            FrontendTelemetry.model_validate({"screen": screen, **base})


# ---- Case 6: telemetry exposure + body bounds ----------------------------------------


class _Sess:
    def __init__(self, key: str | None) -> None:
        self.key = key

    async def resolve_session_key(self, request: Request) -> str | None:
        return self.key


def _tele(key: str | None) -> tuple[TestClient, Metrics]:
    m = Metrics("demo")
    app = FastAPI()
    app.include_router(
        make_telemetry_router(TelemetrySink(m), SessionRateLimiter(lambda: 0.0), _Sess(key))
    )
    return TestClient(app), m


def test_case6_unauthenticated_telemetry_is_401() -> None:
    client, _ = _tele(None)
    assert client.post("/telemetry/frontend", content=b"{}").status_code == 401


def test_case6_real_app_telemetry_not_open_without_principal(world: TestClient) -> None:
    r = world.post("/telemetry/frontend", content=b"{}")  # no principal, no session
    assert r.status_code == 403 and r.json()["code"] == "csrf_token_invalid"


def test_case6_oversized_body_rejected_bounded_and_counted() -> None:
    client, m = _tele("s1")
    big = json.dumps({"screen": "R-100", "pad": "x" * 200_000})
    r = client.post("/telemetry/frontend", content=big)
    assert r.status_code in (400, 413, 422) and len(r.content) < 1024
    from prometheus_client import generate_latest

    text = generate_latest(m.registry).decode()
    assert 'telemetry_rejected_total{env="demo",reason="too_large"} 1.0' in text
