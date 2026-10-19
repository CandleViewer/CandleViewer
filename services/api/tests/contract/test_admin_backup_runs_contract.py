"""Contract (E42-T05 #966 BK-8): `createBackup`. CSRF (SR-041) is refused before any route runs on
the real `create_app` (the RBAC pack's world); the `202` is the contract's `Backup`, and each
refusal a registered problem the operation declares, with its code. `scope: none`: no
cross-account (IDOR) cell; the other roles' cells are the matrix's (`executed`)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from candleviewer.admin.backups.ports import RunPlan
from tests.contract._admin_support import SPEC, validate_example
from tests.contract.rbac.rbac_harness import bearer, build_world
from tests.unit.admin._run_fakes import PLAN, World, run_app

_URL = "/admin/backups"
_CREATED = "/paths/~1admin~1backups/post/responses/202/content/application~1json/schema"
_REGISTERED = {entry["code"] for entry in SPEC["x-error-codes"]}
_DECLARED = SPEC["paths"][_URL]["post"]["responses"]


async def _post(app: FastAPI, body: dict[str, Any], role: str = "owner") -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.post(_URL, json=body, headers={"x-role": role})


def test_missing_csrf_is_403_csrf_token_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    world = build_world(monkeypatch)
    written = len(world.audit.records)
    headers = {"Authorization": bearer("owner")["Authorization"]}  # a bearer is no exemption
    response = world.client.post(_URL, json={"kind": "pg_dump"}, headers=headers)
    assert (response.status_code, response.json()["code"]) == (403, "csrf_token_invalid")
    # No route ran: the one record is the CSRF refusal's, no `admin.area_entered`, no run.
    assert [r["action"] for r in world.audit.records[written:]] == ["auth.csrf_refused"]


async def test_the_202_is_the_contracts_backup() -> None:
    w = World()
    created = await _post(run_app(w)[0], {"kind": "questdb_snapshot", "note": "before 2.4"})
    await w.ended()
    assert created.status_code == 202
    validate_example(_CREATED, created.json())


@pytest.mark.parametrize(
    ("role", "cause", "status", "code"),
    [("", None, 401, "unauthenticated"), ("viewer", None, 403, "forbidden"),
     ("owner", "running", 409, "conflict"), ("owner", "member", 422, "validation_failed"),
     ("owner", "limited", 429, "rate_limited"), ("owner", "unwired", 501, "not_implemented"),
     ("owner", "plan", 503, "store_unavailable"), ("owner", "requested", 503, "audit_unavailable"),
     ("owner", "unencrypted", 503, "backup_engine_invalid")],
    ids=["401", "403", "409", "422", "429", "501", "503-store", "503-audit", "503-engine"],
)  # fmt: skip
async def test_every_refusal_is_a_registered_problem_its_operation_declares(
    role: str, cause: str | None, status: int, code: str
) -> None:
    w = World(engine=cause != "unwired")
    body: dict[str, Any] = {"kind": "pg_dump"} | ({"retain": True} if cause == "member" else {})
    w.limit.wait = 60 if cause == "limited" else None
    if cause in ("plan", "requested"):
        w.faults.raises[str(cause)] = OSError("down")
    if cause == "unencrypted":
        w.engine.plan_given = RunPlan(PLAN.location, False)
    if cause == "running":
        w.engine.go.clear()
        await w.start()  # another run, still running
    response = await _post(run_app(w)[0], body, role)
    problem = response.json()
    assert (response.status_code, problem["code"]) == (status, code)
    assert response.headers["content-type"] == "application/problem+json"
    validate_example("/components/schemas/Problem", problem)
    assert problem["type"].rsplit("/", 1)[1] == code and code in _REGISTERED
    assert str(status) in _DECLARED
    if status in (429, 503) and code != "backup_engine_invalid":  # 429: the oldest start's
        retry = 60 if status == 429 else 5  # leaving the hour
        assert (response.headers["retry-after"], problem["retry_after_seconds"]) == (
            str(retry),
            retry,
        )
    if code == "backup_engine_invalid":  # not retryable: the engine's configuration must change
        assert "retry-after" not in response.headers and "retry_after_seconds" not in problem
    if status == 409:
        rule = {"field": "", "rule": "backup_or_restore_running"}
        assert problem["errors"] == [rule | {"message": "a backup or a restore is running"}]
        assert problem["detail"] == "A backup or a restore is running."
        w.engine.go.set()
        await w.ended()
