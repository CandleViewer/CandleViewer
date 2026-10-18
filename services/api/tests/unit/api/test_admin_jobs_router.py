"""Unit (E42-T05, #966 Q10/Q15, AD-F22): `GET /admin/jobs/{jobId}` on the audited admin router;
the guard itself is tested in `tests/unit/admin/test_admin_http.py`."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from prometheus_client import REGISTRY

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.recorder_admin import AdminJobStore
from tests.unit.admin._admin_fakes import AuditSpy, Resolver, expected_record
from tests.unit.api._job_poll import mount_job_poll

_OWNER = Resolver()
_SPEC: dict[str, Any] = load_openapi_spec()
_404 = _SPEC["paths"]["/admin/jobs/{jobId}"]["get"]["responses"]["404"]["content"]
_JOB_UNKNOWN = _404["application/problem+json"]["examples"]["jobUnknown"]["value"]  # the contract's


async def _get(
    store: AdminJobStore, job: str, role: str = "owner", **wiring: Any
) -> httpx.Response:
    app = FastAPI()
    mount_job_poll(app, store, wiring.get("resolver", _OWNER), wiring.get("audit"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(f"/admin/jobs/{job}", headers={"x-role": role})


async def _finished(store: AdminJobStore, kind: str = "retention_sweep") -> str:
    async def work(progress: Callable[[float], None]) -> dict[str, object]:
        return {"compacted": 2}

    async def done(job: object) -> None:
        return None

    job = store.submit(kind, ("u", str(uuid4()), "h"), work, done)
    await asyncio.sleep(0)  # one scheduler turn: the job runs to its end in its first step
    assert job.status == "succeeded"
    return job.id


_CAUSES = ["never-issued", "malformed", "evicted", "lost-on-restart", "audit-export"]


@pytest.mark.parametrize("cause", _CAUSES)
async def test_every_404_is_not_found_with_rule_job_unknown(
    cause: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, job_id = AdminJobStore(), str(uuid4())
    if cause == "malformed":
        job_id = "not-a-uuid"
    elif cause == "evicted":
        monkeypatch.setattr("candleviewer.api.recorder_admin.MAX_JOBS", 1)
        job_id = await _finished(store)
        await _finished(store)  # the newer job evicts the finished one
    elif cause == "lost-on-restart":
        job_id = await _finished(store)
        store = AdminJobStore()  # the restarted process's empty store
    elif cause == "audit-export":  # its requester's alone, and no requester is recorded yet
        job_id = await _finished(store, "audit_export")
    refused = await _get(store, job_id)
    assert (refused.status_code, refused.json()) == (404, _JOB_UNKNOWN)
    assert refused.headers["content-type"] == "application/problem+json"
    assert api.Problem.model_validate(refused.json()).code == "not_found"


def _denied() -> float:
    return REGISTRY.get_sample_value("authz_denied_total", {"permission": "admin:read"}) or 0.0


@pytest.mark.parametrize("role", ["manager", "viewer"])
async def test_a_refused_poll_is_recorded_and_counted(role: str) -> None:
    store, audit, before = AdminJobStore(), AuditSpy(), _denied()
    refused = await _get(store, await _finished(store), role, audit=audit)
    assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
    assert audit.records == [expected_record(role, "/admin/jobs/{jobId}")]
    assert _denied() == before + 1  # SR-125, as on every admin route


async def _unwritable(action: str, **kwargs: Any) -> None:
    raise OSError("audit WAL unavailable")


@pytest.mark.parametrize(
    ("resolver", "status", "code"),
    [(None, 501, "not_implemented"), (_OWNER, 503, "audit_unavailable")],
)
async def test_unwired_is_501_and_an_unwritable_guard_record_is_503(
    resolver: Resolver | None, status: int, code: str
) -> None:
    store = AdminJobStore()
    refused = await _get(
        store, await _finished(store), audit=SimpleNamespace(emit=_unwritable), resolver=resolver
    )
    assert (refused.status_code, refused.json()["code"]) == (status, code)
    assert "compacted" not in refused.text
