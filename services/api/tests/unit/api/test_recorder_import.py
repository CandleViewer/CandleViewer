"""Unit: `POST /admin/recorder/import` (E16-T10) + `GET /admin/jobs/{jobId}` summary.

RBAC server-side (forbidden role -> 403 + denied audit, no job), unauthenticated 401, IDOR
(another actor's Idempotency-Key never resolves to their job; unknown job -> 404), key reuse
with a different body -> 422, concurrent import -> 409, write-ahead audit before the job
starts (symbol + range + actor), audit failure -> 503 and nothing runs.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
from fastapi import FastAPI

from candleviewer.api.recorder_admin import AdminJobStore, make_recorder_admin_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.actions import AUDIT_ACTIONS
from tests.unit.api._job_poll import mount_job_poll

OWNER = {"recording:write", "admin:read"}
BODY = {"symbol": "BTCUSDT", "from": "2026-06-01", "to": "2026-06-30"}
SUMMARY: dict[str, object] = {
    "files_processed": 29,
    "rows_written": 1000,
    "rows_discarded_overlap": 7,
    "files_skipped": [{"file": "BTCUSDT2026-06-07.csv.gz", "reason": "import_checksum_failed"}],
    "bytes_downloaded": 123,
}


class _Audit:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail
        self.runner: _Runner | None = None

    async def emit(self, action: str, **kw: Any) -> None:
        if self.fail:
            raise RuntimeError("audit down")
        started = bool(self.runner and self.runner.calls)
        self.calls.append((action, kw | {"_job_started": started}))


class _Resolver:
    def __init__(self) -> None:
        self.p: AuditPrincipal | None = None

    def as_(self, perms: set[str] | None, uid: uuid.UUID | None = None) -> None:
        self.p = (
            None
            if perms is None
            else AuditPrincipal(uid or uuid.uuid4(), "u", frozenset(perms), request_id=uuid.uuid4())
        )

    async def resolve(self, request: Any) -> AuditPrincipal | None:
        return self.p


class _Runner:
    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.calls: list[tuple[str, date, date]] = []

    async def __call__(
        self, symbol: str, start: date, end: date, progress: Callable[[float], None]
    ) -> dict[str, object]:
        self.calls.append((symbol, start, end))
        progress(40.0)
        await self.gate.wait()
        return SUMMARY


def _client(*, fail_audit: bool = False) -> tuple[httpx.AsyncClient, _Audit, _Runner, _Resolver]:
    audit, run, res = _Audit(fail=fail_audit), _Runner(), _Resolver()
    audit.runner = run
    res.as_(OWNER)
    app, store = FastAPI(), AdminJobStore()
    app.include_router(make_recorder_admin_router(store, None, audit, res, import_runner=run))
    mount_job_poll(app, store, res)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    return c, audit, run, res


def _hdr(key: str | None = None) -> dict[str, str]:
    return {"Idempotency-Key": key or str(uuid.uuid4())}


async def _poll(c: httpx.AsyncClient, job_id: str, status: str) -> dict[str, Any]:
    for _ in range(200):
        body: dict[str, Any] = (await c.get(f"/admin/jobs/{job_id}")).json()
        if body["status"] == status:
            return body
        await asyncio.sleep(0)
    raise AssertionError(f"job never reached {status}")


def test_recorder_import_audit_action_is_registered() -> None:
    assert "recorder.import" in AUDIT_ACTIONS


async def test_import_accepted_job_polls_to_summary_and_audits_write_ahead() -> None:
    c, audit, run, _ = _client()
    r = await c.post("/admin/recorder/import", json=BODY, headers=_hdr())
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    first = audit.calls[0]
    assert first[0] == "recorder.import" and first[1]["_job_started"] is False
    assert first[1]["before_state"] == {"params": BODY} and first[1]["object_id"] == job_id
    assert first[1]["actor_label"] == "u"
    running = await _poll(c, job_id, "running")
    assert running["kind"] == "archive_import" and running["progress_pct"] == 40.0
    run.gate.set()
    done = await _poll(c, job_id, "succeeded")
    assert done["result"] == SUMMARY and done["progress_pct"] == 100.0
    assert run.calls == [("BTCUSDT", date(2026, 6, 1), date(2026, 6, 30))]
    for _ in range(50):
        if len(audit.calls) == 2:
            break
        await asyncio.sleep(0)
    assert audit.calls[-1][1]["after_state"]["bytes_downloaded"] == 123


async def test_import_forbidden_role_403_denied_audit_and_no_job() -> None:
    c, audit, run, res = _client()
    res.as_({"admin:read", "market:read"})
    r = await c.post("/admin/recorder/import", json=BODY, headers=_hdr())
    assert r.status_code == 403
    assert audit.calls[0][1]["outcome"].value == "denied" and run.calls == []


async def test_import_unauthenticated_401() -> None:
    c, _, run, res = _client()
    res.as_(None)
    assert (await c.post("/admin/recorder/import", json=BODY, headers=_hdr())).status_code == 401
    assert run.calls == []


async def test_import_idempotency_key_replay_same_job_and_different_body_422() -> None:
    c, _, run, _ = _client()
    key = str(uuid.uuid4())
    a = await c.post("/admin/recorder/import", json=BODY, headers=_hdr(key))
    b = await c.post("/admin/recorder/import", json=BODY, headers=_hdr(key))
    assert a.json()["job_id"] == b.json()["job_id"]
    other = BODY | {"to": "2026-06-29"}
    r = await c.post("/admin/recorder/import", json=other, headers=_hdr(key))
    assert r.status_code == 422 and r.json()["code"] == "idempotency_key_reused"
    run.gate.set()


async def test_import_concurrent_second_import_409() -> None:
    c, _, run, _ = _client()
    assert (await c.post("/admin/recorder/import", json=BODY, headers=_hdr())).status_code == 202
    r = await c.post("/admin/recorder/import", json=BODY | {"symbol": "ETHUSDT"}, headers=_hdr())
    assert r.status_code == 409 and r.json()["code"] == "job_running"
    run.gate.set()


async def test_import_idor_other_actor_key_does_not_resolve_their_job() -> None:
    c, _, run, res = _client()
    key = str(uuid.uuid4())
    a = (await c.post("/admin/recorder/import", json=BODY, headers=_hdr(key))).json()["job_id"]
    run.gate.set()
    await _poll(c, a, "succeeded")
    res.as_(OWNER)  # a different user reusing the same key gets a NEW job, never `a`
    b = await c.post("/admin/recorder/import", json=BODY, headers=_hdr(key))
    assert b.status_code == 202 and b.json()["job_id"] != a
    assert (await c.get(f"/admin/jobs/{uuid.uuid4()}")).status_code == 404
    res.as_({"market:read"})
    assert (await c.get(f"/admin/jobs/{a}")).status_code == 403


async def test_import_audit_failure_503_and_job_never_starts() -> None:
    c, _, run, _ = _client(fail_audit=True)
    r = await c.post("/admin/recorder/import", json=BODY, headers=_hdr())
    assert r.status_code == 503 and r.json()["code"] == "audit_unavailable"
    await asyncio.sleep(0)
    assert run.calls == []


async def test_import_validation_400_and_range_422() -> None:
    c, _, run, _ = _client()
    bad = [
        BODY | {"symbol": "../x"},
        BODY | {"extra": 1},
        {"symbol": "BTCUSDT"},
        BODY | {"from": "June"},
    ]
    for body in bad:
        assert (
            await c.post("/admin/recorder/import", json=body, headers=_hdr())
        ).status_code == 400
    assert (await c.post("/admin/recorder/import", json=BODY, headers={})).status_code == 400
    for body in (BODY | {"to": "2026-05-01"}, BODY | {"from": "2025-01-01"}):
        r = await c.post("/admin/recorder/import", json=body, headers=_hdr())
        assert r.status_code == 422 and r.json()["code"] == "import_range_invalid"
    assert run.calls == []


async def test_import_not_wired_fails_closed() -> None:
    app = FastAPI()
    app.include_router(make_recorder_admin_router(AdminJobStore(), None, _Audit(), None))
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    assert (await c.post("/admin/recorder/import", json=BODY, headers=_hdr())).status_code == 501
    res = _Resolver()
    res.as_(OWNER)
    app2 = FastAPI()
    app2.include_router(make_recorder_admin_router(AdminJobStore(), None, _Audit(), res))
    c2 = httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://t")
    assert (await c2.post("/admin/recorder/import", json=BODY, headers=_hdr())).status_code == 503


async def test_import_job_failure_reports_typed_reason_code() -> None:
    from candleviewer.storage.cold.archive_import import LedgerCorrupt

    audit = _Audit()

    async def broken(*_a: object) -> dict[str, object]:
        raise LedgerCorrupt("import ledger is not valid")

    app, store, res = FastAPI(), AdminJobStore(), _Resolver()
    res.as_(OWNER)
    app.include_router(make_recorder_admin_router(store, None, audit, res, import_runner=broken))
    mount_job_poll(app, store, res)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    job_id = (await c.post("/admin/recorder/import", json=BODY, headers=_hdr())).json()["job_id"]
    body = await _poll(c, job_id, "failed")
    assert body["error"] == "import_ledger_corrupt"
