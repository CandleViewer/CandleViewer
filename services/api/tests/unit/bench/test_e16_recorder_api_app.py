"""E16-Q04 (#481): the k6 recorder load target and the script's guards.

The fixture app serves the production status and coverage routers (ASGI, in process: no socket),
and the `recorder` frame it publishes for 20 symbols is measured against the 8 KiB budget here,
deterministically, so a frame that outgrows it fails a unit test before the nightly k6 run.
The k6 script is checked by `k6 inspect` (its init context run, no VU, no request) when a `k6`
binary is on PATH, and by the text lint below either way (BQ-9: inspect when present, else lint).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import httpx
import pytest

from bench.recorder.api_app import SYMBOLS, Backend
from bench.recorder.budgets import FRAME_MAX_BYTES, FRAME_SYMBOLS
from candleviewer.recorder.ws_topic import frame

K6 = Path(__file__).resolve().parents[5] / "tests" / "load" / "k6" / "recorder_api.js"


@pytest.fixture
async def backend(tmp_path: Path) -> Backend:
    be = Backend(tmp_path, sessions=2)
    await be.prepare()
    return be


def _client(be: Backend) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=be.app), base_url="http://bench")


async def test_api_app_serves_status_and_coverage_to_a_bench_session(backend: Backend) -> None:
    auth = {"Authorization": f"Bearer {backend.tokens[0]['access']}"}
    async with _client(backend) as c:
        status = await c.get("/recording/status", headers=auth)
        coverage = await c.get("/market/data-coverage", params={"symbol": "ETHUSDT"}, headers=auth)
        anonymous = await c.get("/recording/status")
        anon_cov = await c.get("/market/data-coverage", params={"symbol": "BTCUSDT"})
    assert status.status_code == 200 and len(status.json()["symbols"]) == FRAME_SYMBOLS
    assert status.json()["role_restricted"] is False
    assert coverage.status_code == 200
    assert anonymous.status_code == 401 and anon_cov.status_code == 401


async def test_api_app_refuses_a_forged_bearer(backend: Backend) -> None:
    async with _client(backend) as c:
        r = await c.get("/recording/status", headers={"Authorization": "Bearer forged"})
    assert r.status_code == 401


async def test_tokens_file_is_owner_only_and_names_20_symbols(
    backend: Backend, tmp_path: Path
) -> None:
    path = tmp_path / "tokens.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    body = json.loads(path.read_text())
    assert body["symbols"] == list(SYMBOLS) and len(set(SYMBOLS)) == FRAME_SYMBOLS
    assert len(body["sessions"]) == 2 and body["origin"].startswith("http://127.0.0.1")


async def test_recorder_frame_for_20_symbols_is_under_8_kib(backend: Backend) -> None:
    snapshot = backend.cache.snapshot()
    assert snapshot is not None
    body = frame(snapshot, frozenset(SYMBOLS), False)
    assert body is not None and len(body["symbols"]) == FRAME_SYMBOLS
    envelope = {"t": "d", "ch": "recorder", "s": 1, "ts": 1_793_000_000_000, "p": body}
    assert len(json.dumps(envelope, separators=(",", ":"))) < FRAME_MAX_BYTES


def _k6_inspect(k6: str, tmp_path: Path, base_url: str) -> subprocess.CompletedProcess[str]:
    """`k6 inspect` of the script: its init context runs (the loopback guard, the tokens file),
    nothing else; no VU and no request. Tokens are placeholders: only their count is read."""
    tokens = tmp_path / "tokens.json"
    tokens.write_text(json.dumps({"symbols": list(SYMBOLS), "sessions": [{}] * 5}))
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "K6_NO_USAGE_REPORT": "true"}
    argv = [k6, "inspect", "-e", f"BASE_URL={base_url}", "-e", f"TOKENS={tokens}", str(K6)]
    return subprocess.run(  # noqa: S603 - fixed argv (the k6 found on PATH), no shell
        argv, capture_output=True, text=True, timeout=60, check=False, env=env, cwd=tmp_path
    )


def _lint_options(text: str) -> None:
    """The lint-only fallback: the budgets and the metrics the thresholds name, as text."""
    assert (
        f"const FRAME_MAX_BYTES = {FRAME_MAX_BYTES};" in text and "const API_P95_MS = 150;" in text
    )
    for key in ("http_req_duration{endpoint:status}", "http_req_duration{endpoint:coverage}",
                "recorder_frame_bytes", "recorder_frames"):  # fmt: skip
        assert key in text


def test_k6_script_inspects_clean_when_k6_is_present_else_lints(tmp_path: Path) -> None:
    """BQ-9: with k6 on PATH, `k6 inspect` parses the script and reports the ticket's thresholds
    and the three scenarios, and its init context refuses a non-loopback target; without k6
    (the PR lane) the lint below is the check."""
    text = K6.read_text(encoding="utf-8")
    _lint_options(text)
    k6 = shutil.which("k6")
    if k6 is None:
        return  # lint only, as ruled: the nightly installs k6 and runs the script itself
    done = _k6_inspect(k6, tmp_path, "http://127.0.0.1:8000")
    assert done.returncode == 0, done.stderr
    options = json.loads(done.stdout)
    assert set(options["scenarios"]) == {"subscribers", "status_poll", "coverage"}
    thresholds = options["thresholds"]
    assert thresholds["http_req_duration{endpoint:status}"] == ["p(95)<150"]
    assert thresholds["recorder_frame_bytes"] == [f"max<{FRAME_MAX_BYTES}"]
    refused = _k6_inspect(k6, tmp_path, "http://10.0.0.1:8000")
    assert refused.returncode != 0 and "refusing non-loopback target" in refused.stdout + (
        refused.stderr
    )


def test_k6_script_refuses_non_loopback_target() -> None:
    text = K6.read_text(encoding="utf-8")
    m = re.search(r"const LOOPBACK = /(.+)/;", text)
    assert m is not None
    loopback = re.compile(m.group(1).replace("\\/", "/"))
    for ok in ("http://127.0.0.1:8000", "http://localhost"):
        assert loopback.match(ok)
    for bad in ("http://10.0.0.1:8000", "https://127.0.0.1", "http://127.0.0.1.evil.example"):
        assert not loopback.match(bad)
    # The guard runs in the init context, before any request, and fails the run.
    guard = text.index("if (!LOOPBACK.test(BASE))")
    assert text.index("fail(`refusing non-loopback target", guard) < text.index("http.get(")


def test_k6_script_thresholds_are_the_ticket_budgets() -> None:
    text = K6.read_text(encoding="utf-8")
    assert "const FRAME_MAX_BYTES = 8192;" in text
    _lint_options(text)
    assert "const SUBSCRIBERS = 5;" in text and "rate: 1, // 1 Hz" in text
