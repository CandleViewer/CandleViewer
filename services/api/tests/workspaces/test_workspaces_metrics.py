"""E15-T01 (S6): router metrics (412s, panes, per-operation duration) and the log canary."""

from __future__ import annotations

import re
import uuid

import _workspaces_api_env as fakes
import structlog
from _workspaces_api_env import LAYOUT, PERMS, SID, USER_A, FakeWorkspaceRepo, wire
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from candleviewer.api.workspaces import OPERATIONS, make_workspaces_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.observability.metrics import Metrics
from candleviewer.storage.retention.workspaces_tasks import WorkspacesMetrics


def _metrics() -> tuple[Metrics, WorkspacesMetrics]:
    m = Metrics("demo")
    return m, WorkspacesMetrics(
        conflicts=m.counter("cv_workspace_conflicts_total", "x", ("resource",), max_series=2),
        layout_panes=m.histogram("cv_layout_panes", "x", buckets=(0, 1, 2, 4, 8, 12, 16)),
        users=m.gauge("cv_workspace_users", "x", ("bucket",), max_series=5),
        purged=m.counter("cv_workspaces_purged_total", "x", ("kind",), max_series=2),
        request_seconds=m.histogram(
            "cv_workspace_request_seconds", "x", ("operation",), buckets=(0.1, 1.0),
            max_series=len(OPERATIONS),
        ),
    )  # fmt: skip


class _Tick:
    """Fake monotonic clock: every read advances 0.25 s (no sleeping)."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 0.25
        return self.t


def _client(m: WorkspacesMetrics | None) -> tuple[TestClient, FakeWorkspaceRepo]:
    repo = fakes.FakeWorkspaceRepo()

    class _Resolver:
        async def resolve(self, _r: Request) -> AuditPrincipal:
            return AuditPrincipal(
                USER_A, "u", frozenset(PERMS[USER_A]), session_id=SID, ip="10.0.0.9"
            )

    app = FastAPI()
    app.include_router(
        make_workspaces_router(lambda: repo, _Resolver(), fakes.Audit(), metrics=m, timer=_Tick())
    )
    return TestClient(app), repo


def _series(reg: Metrics, name: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in generate_latest(reg.registry).decode().splitlines():
        if line.startswith(name) and not line.startswith("#"):
            k, _, v = line.rpartition(" ")
            out[re.sub(r',?env="demo",?', "", k).replace("{}", "")] = float(v)
    return out


def _ws(c: TestClient) -> str:
    return str(c.post("/workspaces", json=wire({"name": "Scalping"})).json()["id"])


def test_stale_workspace_and_layout_puts_count_one_conflict_each() -> None:
    reg, m = _metrics()
    c, _ = _client(m)
    ws = _ws(c)
    stale = {"If-Match": '"2000-01-01T00:00:00.000000Z"'}
    assert c.put(f"/workspaces/{ws}", json=wire({"name": "x"}), headers=stale).status_code == 412
    lay = c.post(f"/workspaces/{ws}/layouts", json=wire(LAYOUT, "LayoutInput")).json()["id"]
    body = wire(LAYOUT | {"name": "y"}, "LayoutInput")
    assert c.put(f"/workspaces/{ws}/layouts/{lay}", json=body, headers=stale).status_code == 412
    assert _series(reg, "cv_workspace_conflicts_total") == {
        'cv_workspace_conflicts_total{resource="workspace"}': 1.0,
        'cv_workspace_conflicts_total{resource="layout"}': 1.0,
    }


def test_panes_observed_on_create_and_changed_write_but_not_on_a_noop() -> None:
    reg, m = _metrics()
    c, _ = _client(m)
    ws = _ws(c)
    made = c.post(f"/workspaces/{ws}/layouts", json=wire(LAYOUT, "LayoutInput")).json()
    url = f"/workspaces/{ws}/layouts/{made['id']}"
    assert c.put(url, json=wire(LAYOUT, "LayoutInput")).status_code == 200  # no-op
    assert c.put(url, json=wire(LAYOUT | {"panes": []}, "LayoutInput")).status_code == 200
    s = _series(reg, "cv_layout_panes")
    assert s["cv_layout_panes_count"] == 2 and s["cv_layout_panes_sum"] == 4  # 4 panes, then 0
    assert s['cv_layout_panes_bucket{le="0.0"}'] == 1


def test_duration_is_recorded_per_operation_with_the_fake_clock() -> None:
    reg, m = _metrics()
    c, _ = _client(m)
    ws = _ws(c)
    c.get("/workspaces")
    c.get(f"/workspaces/{ws}")
    c.get("/workspaces/not-a-uuid")  # 422 still counts as a get_workspace call
    s = _series(reg, "cv_workspace_request_seconds")
    ops = {k.split('operation="')[1].split('"')[0] for k in s if "operation=" in k}
    assert ops == {"create_workspace", "list_workspaces", "get_workspace"} <= set(OPERATIONS)
    assert s['cv_workspace_request_seconds_count{operation="get_workspace"}'] == 2
    assert s['cv_workspace_request_seconds_sum{operation="list_workspaces"}'] == 0.25


def test_every_operation_name_is_a_real_route_name() -> None:
    c, _ = _client(None)
    fresh = make_workspaces_router(lambda: None, None, fakes.Audit())
    names = {getattr(r, "name", "") for r in fresh.routes}
    assert names == set(OPERATIONS) and c is not None


def test_no_metrics_means_nothing_recorded_and_no_error() -> None:
    c, _ = _client(None)
    assert c.get("/workspaces").status_code == 200


def test_logs_never_carry_names_pane_config_grid_spec_or_bodies() -> None:
    _, m = _metrics()
    c, _ = _client(m)
    secret = "CANARY-name-7731"  # noqa: S105 - a log-canary marker, not a credential
    ws = str(c.post("/workspaces", json=wire({"name": secret})).json()["id"])
    cfg = {"sync_group": "A", "settings": {"note": "CANARY-cfg-9921"}}
    pane = {"slot_index": 0, "pane_kind": "chart", "symbol": "BTCUSDT", "pane_config": cfg}
    lay = LAYOUT | {"name": secret + "-lay", "panes": [pane]}
    with structlog.testing.capture_logs() as logs:
        made = c.post(f"/workspaces/{ws}/layouts", json=wire(lay, "LayoutInput")).json()
        c.put(
            f"/workspaces/{ws}/layouts/{made['id']}", json=wire(lay | {"panes": []}, "LayoutInput")
        )
        c.put(f"/workspaces/{ws}", json=wire({"name": secret + "2"}))
        c.delete(f"/workspaces/{ws}/layouts/{made['id']}")
    assert logs
    allowed = {
        "event",
        "log_level",
        "user_id",
        "workspace_id",
        "layout_id",
        "pane_count",
        "changed",
    }
    assert {k for e in logs for k in e} <= allowed
    assert "CANARY" not in repr(logs)
    assert uuid.UUID(str(logs[0]["user_id"])) == USER_A
