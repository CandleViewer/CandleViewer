"""Unit (E42-T05 #966 BK-8): `POST /admin/backups` over the run service's fakes: the `202` and its
job, the key's replay and reuse, a refusal never kept under the key, the closed body, and the
guard's 403 cells (a record and a count). CSRF, 401 and the problems: `tests/contract/`."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from prometheus_client import REGISTRY

from candleviewer.admin.backups.gate import BackupConflict, BackupJobGate, ConflictRule
from candleviewer.admin.backups.ports import RunPlan
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.admin_backups import _refusal
from candleviewer.api.idempotency import IdempotencyCache
from candleviewer.auth.generated_permissions import Permission
from tests.unit.admin._admin_fakes import expected_record
from tests.unit.admin._run_fakes import OWNER, PLAN, World, run_app

_PATH, _KEY = "/admin/backups", str(UUID(int=0xA11CE))
_BODY = {"kind": "pg_dump"}


async def _call(
    app: FastAPI, body: Any = _BODY, role: str = "owner", key: str | None = None
) -> httpx.Response:
    headers = {"x-role": role} | ({} if key is None else {"idempotency-key": key})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        if isinstance(body, bytes):
            headers["content-type"] = "application/json"
            return await c.post(_PATH, content=body, headers=headers)
        return await c.post(_PATH, json=body, headers=headers)


async def _poll(app: FastAPI, job_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        polled = await c.get(f"/admin/jobs/{job_id}", headers={"x-role": "owner"})
    assert polled.status_code == 200
    job: dict[str, Any] = polled.json()
    api.Job.model_validate(job)  # the contract's `Job`
    return job


async def test_create_returns_202_with_the_backup_whose_id_is_the_job_id() -> None:
    w, sent = World(), {"kind": "config_bundle", "verify": False, "note": "ad hoc"}
    created = await _call(run_app(w)[0], sent)  # the run is of the client's kind
    await w.ended()
    body = created.json()
    assert (created.status_code, body["status"], body["location"], body["kind"]) == (
        202,
        "running",
        PLAN.location,
        "config_bundle",
    )
    assert api.Backup.model_validate(body).model_dump(mode="json", exclude_unset=True) == body
    job = w.jobs.store.get(body["id"])
    assert job is not None and (job.kind, job.result) == ("backup", {"backup_id": body["id"]})
    requested = w.audit.records[0]
    state, note = requested["after_state"], requested["reason"]
    assert (state["kind"], state["verify"], note) == ("config_bundle", False, "ad hoc")


async def test_verify_defaults_to_true_and_the_note_to_none() -> None:
    w = World()
    await _call(run_app(w)[0], {"kind": "pg_dump"})  # the contract's default: `verify: true`
    await w.ended()
    requested = w.audit.records[0]
    assert (requested["after_state"]["verify"], requested["reason"]) == (True, None)


async def test_job_is_pollable_with_kind_backup() -> None:
    w = World()
    app, _ = run_app(w)
    w.engine.go.clear()
    created = (await _call(app)).json()
    running = await _poll(app, created["id"])
    assert (running["kind"], running["result"]) == ("backup", None)
    w.engine.go.set()
    await w.ended()
    done = await _poll(app, created["id"])
    assert (done["status"], done["result"]) == ("succeeded", {"backup_id": created["id"]})


async def test_replay_with_the_same_key_returns_the_original_202() -> None:
    w, cache = World(), IdempotencyCache()
    app, _ = run_app(w, cache)
    first = await _call(app, key=_KEY.upper())  # one key, however the UUID is written
    assert cache.get(str(OWNER.user_id), f"createBackup:{_KEY}") is not None
    await w.ended()
    again = await _call(app, key=_KEY)
    assert (again.status_code, again.content) == (202, first.content)
    assert again.headers["idempotency-replayed"] == "true"
    reused = await _call(app, {"kind": "config_bundle"}, key=_KEY)
    assert (reused.status_code, reused.json()["code"]) == (409, "idempotency_key_reuse")
    assert len(w.audit.records) == 2  # one run, its two records: the replay ran nothing


@pytest.mark.parametrize("cause", ["running", "limited", "unrecorded", "unencrypted"])
async def test_a_refused_run_is_not_stored_under_the_key(cause: str) -> None:
    w = World()
    app, _ = run_app(w)
    if cause == "running":
        w.engine.go.clear()
        await _call(app)  # another run, with no key
    elif cause == "limited":
        w.limit.wait = 60
    elif cause == "unrecorded":
        w.faults.raises["requested"] = OSError("audit WAL unavailable")
    else:
        w.engine.plan_given = RunPlan(PLAN.location, False)
    refused = await _call(app, key=_KEY)
    statuses = {"running": 409, "limited": 429, "unrecorded": 503, "unencrypted": 503}
    assert refused.status_code == statuses[cause]
    w.engine.go.set()
    w.limit.wait, w.faults.raises, w.engine.plan_given = None, {}, PLAN
    if cause == "running":
        await w.ended()
    accepted = await _call(app, key=_KEY)  # the cause cleared: evaluated afresh, never a replay
    await w.ended()
    assert accepted.status_code == 202 and "idempotency-replayed" not in accepted.headers


async def test_a_busy_admission_lock_is_503_with_retry_after_and_writes_nothing() -> None:
    """#3695's sentence: `Retry-After`, before any record, and nothing starts or counts."""
    w, cache = World(gate=BackupJobGate(admit_wait_s=0.05)), IdempotencyCache()
    app, _ = run_app(w, cache)
    async with w.gate.admit_delete(UUID(int=99)):  # held past the run's wait
        refused = await _call(app, key=_KEY)
    answer = (refused.status_code, refused.json()["code"], refused.headers["retry-after"])
    assert (answer, w.trail, w.limit.starts) == ((503, "store_unavailable", "5"), [], [])
    assert len(cache) == 0  # never kept under the key: evaluated afresh once the lock is free


def test_each_conflict_rule_has_its_own_message() -> None:
    """BK-9 and BK-12 answer `verify_running` and `backup_in_use` through the same refusal."""
    rules: list[ConflictRule] = ["backup_or_restore_running", "verify_running", "backup_in_use"]
    problems = [json.loads(bytes(_refusal(BackupConflict(rule)).body)) for rule in rules]
    assert [problem["errors"][0]["rule"] for problem in problems] == rules
    messages = [problem["errors"][0]["message"] for problem in problems]
    details = [f"{message.capitalize()}." for message in messages]
    assert (len(set(messages)), [problem["detail"] for problem in problems]) == (3, details)


async def test_unknown_body_member_is_422() -> None:
    w = World()
    refused = await _call(run_app(w)[0], {"kind": "pg_dump", "schedule_name": "hourly"})
    problem = refused.json()
    assert (refused.status_code, problem["code"]) == (422, "validation_failed")
    assert problem["errors"] == [
        {"field": "", "rule": "extra_forbidden", "message": "Extra inputs are not permitted"}
    ]
    assert "schedule_name" not in refused.text and w.trail == []


_INVALID: dict[str, Any] = {
    "unknown-kind": {"kind": "pg_dumpall"},
    "no-kind": {"verify": True},
    "verify-not-a-boolean": {"kind": "pg_dump", "verify": "yes"},
    "null-note": {"kind": "pg_dump", "note": None},
    "long-note": {"kind": "pg_dump", "note": "n" * 281},
    "unstorable-note": {"kind": "pg_dump", "note": "before\x00after"},
    "not-json": b'{"kind": "pg_dump"',
    "over-the-cap": b'{"kind": "pg_dump", "note": "' + b" " * 4096 + b'"}',
}


@pytest.mark.parametrize("case", [*_INVALID, "malformed-key"])
async def test_every_other_invalid_request_is_422_and_starts_nothing(case: str) -> None:
    w = World()
    body, key = _INVALID.get(case, _BODY), "not-a-uuid" if case == "malformed-key" else None
    refused = await _call(run_app(w)[0], body, key=key)
    assert (refused.status_code, refused.json()["code"]) == (422, "validation_failed")
    if case == "over-the-cap":
        assert refused.json()["errors"][0]["rule"] == "body_too_large"
    assert (w.trail, w.limit.starts) == ([], [])


async def test_a_note_of_280_characters_is_kept_whole() -> None:
    w = World()
    created = await _call(run_app(w)[0], {"kind": "pg_dump", "note": "é" * 280})
    await w.ended()
    assert (created.status_code, w.audit.records[0]["reason"]) == (202, "é" * 280)


def _denied() -> float:
    """`authz_denied_total` for `backups:write` (SR-125); a test asserts the delta."""
    labels = {"permission": "backups:write"}
    return float(REGISTRY.get_sample_value("authz_denied_total", labels) or 0.0)


@pytest.mark.parametrize("role", ["manager", "viewer"])
async def test_manager_and_viewer_get_403(role: str) -> None:
    w, before = World(), _denied()
    app, spy = run_app(w)
    refused = await _call(app, {"kind": "pg_dumpall"}, role)  # RBAC before the body
    assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
    assert spy.records == [expected_record(role, _PATH, Permission.BACKUPS_WRITE)]
    assert (_denied(), w.trail) == (before + 1, [])
