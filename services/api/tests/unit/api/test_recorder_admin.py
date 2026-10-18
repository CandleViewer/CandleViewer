"""Unit: `POST /admin/recorder/compact` + `GET /admin/jobs/{jobId}` (E16-T05).

RBAC server-side (forbidden role -> 403 + denied audit, no job), fail-closed
without a resolver/session, Idempotency-Key replay, one job at a time, job
lifecycle polled to `succeeded`/`failed`, and job ids are unguessable UUIDs
(no enumeration of another job: unknown id -> 404 for an authorised caller).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from candleviewer.api.recorder_admin import AdminJobStore, make_recorder_admin_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.actions import AUDIT_ACTIONS
from tests.unit.api._job_poll import mount_job_poll


class _Audit:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append((action, kw))


class _Resolver:
    def __init__(self, perms: set[str] | None) -> None:
        self.p = (
            None
            if perms is None
            else AuditPrincipal(uuid.uuid4(), "own", frozenset(perms), request_id=uuid.uuid4())
        )

    async def resolve(self, request: Any) -> AuditPrincipal | None:
        return self.p


class _Runner:
    def __init__(self, *, fail: bool = False) -> None:
        self.gate = asyncio.Event()
        self.fail = fail
        self.calls: list[tuple[list[str] | None, int | None]] = []

    async def __call__(
        self, symbols: list[str] | None, days: int | None, progress: Callable[[float], None]
    ) -> dict[str, object]:
        self.calls.append((symbols, days))
        progress(50.0)
        await self.gate.wait()
        if self.fail:
            raise RuntimeError("disk full")
        return {"compacted": 2, "skipped": 0, "deferred": ["trades/symbol=BTCUSDT/dt=x"]}


def _client(perms: set[str] | None, runner: _Runner | None = None) -> tuple[Any, _Audit, Any]:
    audit = _Audit()
    run = runner or _Runner()
    app, store, res = FastAPI(), AdminJobStore(), _Resolver(perms)
    app.include_router(make_recorder_admin_router(store, run, audit, res))
    mount_job_poll(app, store, res)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    return c, audit, run


def _hdr() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


OWNER = {"recording:write", "admin:read"}


async def _poll(c: httpx.AsyncClient, job_id: str, status: str) -> dict[str, Any]:
    for _ in range(200):
        body: dict[str, Any] = (await c.get(f"/admin/jobs/{job_id}")).json()
        if body["status"] == status:
            return body
        await asyncio.sleep(0)
    raise AssertionError(f"job never reached {status}")


def test_recorder_compact_audit_action_is_registered() -> None:
    assert "recorder.compact" in AUDIT_ACTIONS


async def test_compact_job_lifecycle_succeeds_and_is_audited() -> None:
    c, audit, run = _client(OWNER)
    r = await c.post("/admin/recorder/compact", json={"symbols": ["BTCUSDT"]}, headers=_hdr())
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    running = await _poll(c, job_id, "running")
    assert running["progress_pct"] == 50.0 and running["kind"] == "retention_sweep"
    run.gate.set()
    done = await _poll(c, job_id, "succeeded")
    assert done["progress_pct"] == 100.0 and done["result"]["compacted"] == 2
    assert done["finished_at"].endswith("Z")
    assert run.calls == [(["BTCUSDT"], None)]
    actions = [(a, kw.get("outcome")) for a, kw in audit.calls]
    assert actions[0] == ("recorder.compact", None)  # accepted (write-ahead)
    last_outcome = audit.calls[-1][1]["outcome"]
    assert actions[-1][0] == "recorder.compact" and last_outcome.value == "success"


async def test_compact_job_failure_is_reported_and_audited() -> None:
    c, audit, run = _client(OWNER, _Runner(fail=True))
    job_id = (await c.post("/admin/recorder/compact", headers=_hdr())).json()["job_id"]
    run.gate.set()
    failed = await _poll(c, job_id, "failed")
    assert failed["error"] == "RuntimeError"  # type only, never the message
    assert audit.calls[-1][1]["outcome"].value == "failure"


@pytest.mark.parametrize("perms", [{"admin:read"}, {"recording:read"}, set()])
async def test_compact_forbidden_role_is_403_audited_and_starts_nothing(perms: set[str]) -> None:
    c, audit, run = _client(perms)
    r = await c.post("/admin/recorder/compact", headers=_hdr())
    assert r.status_code == 403
    assert audit.calls[0][1]["outcome"].value == "denied"
    assert run.calls == []


async def test_job_poll_requires_admin_read() -> None:
    owner, _, run = _client(OWNER)
    job_id = (await owner.post("/admin/recorder/compact", headers=_hdr())).json()["job_id"]
    manager, _, _ = _client({"recording:write"})
    assert (await manager.get(f"/admin/jobs/{job_id}")).status_code == 403
    run.gate.set()


async def test_unknown_or_foreign_job_id_is_404_not_leaked() -> None:
    c, _, _ = _client(OWNER)
    assert (await c.get(f"/admin/jobs/{uuid.uuid4()}")).status_code == 404
    assert (await c.get("/admin/jobs/../recorder")).status_code == 404


async def test_fail_closed_without_resolver_session_or_backend() -> None:
    app, store = FastAPI(), AdminJobStore()
    app.include_router(make_recorder_admin_router(store, None, None, None))
    mount_job_poll(app, store, None)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    assert (await c.post("/admin/recorder/compact", headers=_hdr())).status_code == 501
    assert (await c.get(f"/admin/jobs/{uuid.uuid4()}")).status_code == 501
    anon, _, _ = _client(None)
    assert (await anon.post("/admin/recorder/compact", headers=_hdr())).status_code == 401
    assert (await anon.get(f"/admin/jobs/{uuid.uuid4()}")).status_code == 401
    app2 = FastAPI()
    app2.include_router(
        make_recorder_admin_router(AdminJobStore(), None, _Audit(), _Resolver(OWNER))
    )
    c2 = httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://t")
    assert (await c2.post("/admin/recorder/compact", headers=_hdr())).status_code == 503


async def test_idempotency_key_required_and_replay_returns_same_job() -> None:
    c, _, run = _client(OWNER)
    assert (await c.post("/admin/recorder/compact")).status_code == 400
    bad = {"Idempotency-Key": "not-a-uuid"}
    assert (await c.post("/admin/recorder/compact", headers=bad)).status_code == 400
    h = _hdr()
    a = (await c.post("/admin/recorder/compact", headers=h)).json()["job_id"]
    b = (await c.post("/admin/recorder/compact", headers=h)).json()["job_id"]
    assert a == b and len(run.calls) <= 1
    run.gate.set()


async def test_second_concurrent_compaction_is_409() -> None:
    c, _, run = _client(OWNER)
    assert (await c.post("/admin/recorder/compact", headers=_hdr())).status_code == 202
    r = await c.post("/admin/recorder/compact", headers=_hdr())
    assert r.status_code == 409 and r.json()["code"] == "job_running"
    run.gate.set()


@pytest.mark.parametrize(
    "body",
    [
        {"symbols": ["../etc"]},
        {"symbols": ["btcusdt"]},
        {"older_than_days": 0},
        {"older_than_days": 4000},
        {"extra": 1},
    ],
)
async def test_compact_rejects_invalid_body(body: dict[str, object]) -> None:
    c, _, run = _client(OWNER)
    r = await c.post("/admin/recorder/compact", json=body, headers=_hdr())
    assert r.status_code == 400 and run.calls == []


async def test_job_store_stop_cancels_running_jobs() -> None:
    store = AdminJobStore()

    async def forever(progress: Callable[[float], None]) -> dict[str, object]:
        await asyncio.Event().wait()
        return {}

    async def done(job: object) -> None:
        return None

    job = store.submit("retention_sweep", ("a", "k", "h"), forever, done)
    await asyncio.sleep(0)
    await store.stop()
    assert job.status == "cancelled"


async def test_compact_audit_failure_is_503_and_no_job_starts() -> None:
    class BrokenAudit(_Audit):
        async def emit(self, action: str, **kw: Any) -> None:
            raise RuntimeError("wal down")

    run = _Runner()
    store = AdminJobStore()
    app = FastAPI()
    app.include_router(make_recorder_admin_router(store, run, BrokenAudit(), _Resolver(OWNER)))
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    r = await c.post("/admin/recorder/compact", headers=_hdr())
    assert r.status_code == 503 and r.json()["code"] == "audit_unavailable"
    await asyncio.sleep(0)
    assert run.calls == [] and store._jobs == {}


async def test_compact_accepted_audit_is_written_before_job_runs() -> None:
    order: list[str] = []

    class OrderAudit(_Audit):
        async def emit(self, action: str, **kw: Any) -> None:
            order.append("audit" if kw.get("outcome") is None else "done")

    class OrderRunner(_Runner):
        async def __call__(self, s, d, p):  # type: ignore[no-untyped-def]  # test override
            order.append("run")
            return {}

    app = FastAPI()
    app.include_router(
        make_recorder_admin_router(AdminJobStore(), OrderRunner(), OrderAudit(), _Resolver(OWNER))
    )
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    assert (await c.post("/admin/recorder/compact", headers=_hdr())).status_code == 202
    for _ in range(20):
        await asyncio.sleep(0)
    assert order[:2] == ["audit", "run"]


async def test_idempotency_key_is_bound_to_actor_and_body() -> None:
    store, run = AdminJobStore(), _Runner()
    audit = _Audit()

    def client(res: _Resolver) -> httpx.AsyncClient:
        app = FastAPI()
        app.include_router(make_recorder_admin_router(store, run, audit, res))
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    alice, bob = client(_Resolver(OWNER)), client(_Resolver(OWNER))
    h = _hdr()
    a = await alice.post("/admin/recorder/compact", json={"older_than_days": 7}, headers=h)
    assert a.status_code == 202
    other_body = await alice.post("/admin/recorder/compact", json={"older_than_days": 9}, headers=h)
    assert other_body.status_code == 422
    stolen = await bob.post("/admin/recorder/compact", json={"older_than_days": 7}, headers=h)
    assert stolen.status_code == 409  # bob's own key namespace: not alice's job id
    assert stolen.json().get("job_id") is None
    run.gate.set()
