"""E14-T01 (C4): the real `create_app()` records the drawings metrics (batch size, conflicts)."""

from __future__ import annotations

import _drawings_api_env as fakes
import pytest
from _drawings_api_env import BATCH, SID, TRENDLINE, wire
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

import candleviewer.app as appmod
from tests.csrf_helpers import arm_csrf
from tests.unit.auth.auth_fakes import FullUsers

MISSING = "00000000-0000-4000-8000-0000000000ff"


def _scrape(app: object) -> dict[str, float]:
    text = generate_latest(app.state.app_context.metrics).decode()  # type: ignore[attr-defined]
    out: dict[str, float] = {}
    for line in text.splitlines():
        if line.startswith("cv_drawings_") and not line.startswith("#"):
            name, _, value = line.rpartition(" ")
            out[name] = float(value)
    return out


def test_batch_through_the_full_app_increments_both_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(appmod, "build_identity_provider", lambda _s: fakes.Identity())
    app = appmod.create_app()
    app.state.app_context.auth._sessions = fakes.Sessions()
    app.state.app_context.auth._repository = FullUsers()  # #2295: classified as full
    app.state.app_context.audit._writer = fakes.Audit()
    app.state.drawings_repository = fakes.FakeDrawingRepo()
    h, peer = {"Authorization": "Bearer tok-a"}, ("127.0.0.1", 50000)
    c = arm_csrf(TestClient(app, client=peer), app.state.csrf_codec, SID)

    ok = {"operations": [{"op": "create", "drawing": TRENDLINE}] * 3}
    assert c.post("/drawings/batch", json=wire(ok, BATCH), headers=h).status_code == 200
    stale = "2026-10-14T12:00:00.000000Z"
    bad = {"operations": [{"op": "delete", "id": MISSING, "if_match": stale}]}
    r = c.post("/drawings/batch", json=wire(bad, BATCH), headers=h)
    assert r.status_code == 409 and r.json()["errors"][0]["rule"] == "target_unavailable"

    series = _scrape(app)
    count = next(v for k, v in series.items() if k.startswith("cv_drawings_batch_ops_count"))
    total = next(v for k, v in series.items() if k.startswith("cv_drawings_batch_ops_sum"))
    assert count == 2 and total == 4  # one batch of 3 ops, one of 1
    conflict = [v for k, v in series.items() if k.startswith("cv_drawings_conflicts_total{")]
    assert conflict == [1.0]
