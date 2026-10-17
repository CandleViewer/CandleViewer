"""E04-Q01: API-level black-box regression pack for health and telemetry endpoints.

Drives only the public HTTP surface (no module internals beyond router wiring).
Cases: E04-TC-H01..H04 and H06 (health matrix), E04-TC-T01..T05 (telemetry rejections). H05, the
admin health RBAC cells, is `test_rbac_cell` in `tests/contract/test_admin_ops_routes_contract.py`.
See qa/plans/e04-observability-test-plan.md.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.health_report import make_health_report_router
from candleviewer.api.telemetry import make_telemetry_router
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.telemetry import SessionRateLimiter, TelemetrySink

CANARY = "CANARY-SECRET-e04q01-do-not-ship"  # obviously fake, greppable


def _health(checks: dict[str, Any]) -> TestClient:
    app = FastAPI()
    app.include_router(make_health_report_router(ready_checks=checks, ready_timeout_s=0.1))
    return TestClient(app)


async def _up() -> bool:
    return True


def _down_factory(name: str) -> Any:
    async def down() -> bool:
        raise ConnectionError(f"{name} unreachable {CANARY}")

    return down


def test_h01_each_dependency_down_in_turn_flips_ready_naming_only_it() -> None:
    names = ["postgres", "questdb", "bybit_rest"]
    for stopped in names:
        checks = {n: (_down_factory(n) if n == stopped else _up) for n in names}
        c = _health(checks)
        r = c.get("/health/ready")
        assert r.status_code == 503
        detail = r.json()["detail"]
        assert stopped in detail
        assert all(n not in detail for n in names if n != stopped)
        assert CANARY not in r.text  # exception text never leaks
        assert c.get("/health/live").status_code == 200  # liveness independent of deps


def test_h02_all_up_ready_200() -> None:
    r = _health({"postgres": _up}).get("/health/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready"


def test_h03_slow_probe_is_bounded_and_does_not_block_liveness() -> None:
    async def slow() -> bool:
        await asyncio.sleep(30)
        return True

    c = _health({"postgres": slow})
    t0 = time.monotonic()
    r = c.get("/health/ready")
    assert r.status_code == 503
    assert time.monotonic() - t0 < 2.0
    t1 = time.monotonic()
    assert c.get("/health/live").status_code == 200
    assert time.monotonic() - t1 < 0.5


def test_h04_live_body_is_static_and_leaks_nothing() -> None:
    r = _health({"postgres": _down_factory("postgres")}).get("/health/live")
    assert r.json() == {"status": "ok"}
    assert CANARY not in r.text


def test_h06_ready_503_carries_retry_after_and_leaks_nothing() -> None:
    r = _health({"postgres": _down_factory("postgres")}).get("/health/ready")
    assert r.headers["retry-after"] == "5"
    assert CANARY not in r.text


PATH = "/telemetry/frontend"


def _payload(**over: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "screen": "R-100",
        "engine_version": "0.1.0",
        "fe_frame_time_ms": {"counts": [1, 0, 0, 0, 0, 0, 0, 0, 0]},
        "fe_ws_decode_ms": {"counts": [1, 0, 0, 0, 0, 0, 0, 0, 0]},
        "fe_dropped_frames_total": 0,
        "fe_gpu_memory_mb": 1.0,
    }
    p.update(over)
    return p


def _telemetry(key: str | None = "s1") -> tuple[TestClient, Metrics]:
    class R:
        async def resolve_session_key(self, request: Request) -> str | None:
            return key

    m = Metrics("demo")
    app = FastAPI()
    app.include_router(
        make_telemetry_router(TelemetrySink(m), SessionRateLimiter(lambda: 0.0), R())
    )
    return TestClient(app), m


def _rejected(m: Metrics, reason: str) -> float:
    v = m.registry.get_sample_value("telemetry_rejected_total", {"env": "demo", "reason": reason})
    return 0.0 if v is None else v


def test_t01_unauthenticated_rejected_401_and_counted() -> None:
    c, m = _telemetry(key=None)
    assert c.post(PATH, json=_payload()).status_code == 401
    assert _rejected(m, "unauthenticated") == 1


def test_t02_oversize_rejected_400_and_counted() -> None:
    c, m = _telemetry()
    body = b'{"screen":"' + b"x" * 5000 + b'"}'
    r = c.post(PATH, content=body, headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert _rejected(m, "too_large") == 1


def test_t03_unknown_field_and_wrong_type_rejected_400() -> None:
    c, m = _telemetry()
    assert c.post(PATH, json=_payload(extra_field=1)).status_code == 400
    assert c.post(PATH, json=_payload(fe_dropped_frames_total="many")).status_code == 400
    assert _rejected(m, "invalid") == 2


def test_t04_label_cardinality_attack_rejected_not_minted() -> None:
    c, m = _telemetry()
    r = c.post(PATH, json=_payload(screen=f"user-{CANARY}"))
    assert r.status_code == 400
    assert CANARY not in r.text
    assert (
        m.registry.get_sample_value(
            "fe_frame_time_ms_count", {"env": "demo", "screen": f"user-{CANARY}"}
        )
        is None
    )


def test_t05_burst_beyond_limit_is_429_with_retry_after() -> None:
    c, m = _telemetry()
    codes = [c.post(PATH, json=_payload()) for _ in range(20)]
    assert 429 in [r.status_code for r in codes]
    limited = next(r for r in codes if r.status_code == 429)
    assert "retry-after" in limited.headers
    assert _rejected(m, "rate_limited") >= 1


# --- E04-TC-G01 (AC5): canary secrets through the four logging paths at DEBUG ---


def test_g01_canaries_never_reach_output_via_four_logging_paths() -> None:
    import io
    import logging
    from contextlib import redirect_stdout

    import structlog

    from candleviewer.observability import logging as logging_mod
    from candleviewer.observability.logging import configure_logging
    from candleviewer.observability.secret_type import Secret

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            configure_logging(env="dev", level="debug", fmt="json")
            # 1. app path (structlog), sensitive key name and Secret wrapper
            structlog.get_logger("app").debug(
                "login", password=f"{CANARY}-app", wrapped=Secret(f"{CANARY}-wrapped")
            )
            # 2. stdlib path, no structlog contact
            logging.getLogger("stdlib.e04").debug(
                "hdr %s", {"authorization": f"{CANARY}-stdlib", "x-bapi-sign": CANARY + "-sig"}
            )
            # 3. third-party-style logger with extra fields
            logging.getLogger("urllib3.connectionpool").debug(
                "req", extra={"api_secret": f"{CANARY}-3p"}
            )
            # 4. traceback path
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                structlog.get_logger("app").error("failed", exc_info=True, secret=f"{CANARY}-tb")
            listener = logging_mod._listener
            assert listener is not None
            listener.stop()
            logging_mod._listener = None
    finally:
        logging.getLogger().handlers = []
        structlog.reset_defaults()
    out = buf.getvalue()
    assert out.strip(), "expected log output to be captured"
    assert "CANARY-SECRET" not in out, "canary leaked into logs (p0)"
