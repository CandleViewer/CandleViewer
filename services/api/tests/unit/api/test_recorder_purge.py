"""Unit (E16-T06): `POST /admin/recorder/purge` security + contract matrix.

202 happy path (write-ahead `retention.purge` with the exact window before the job, then each
deletion's `data.deleted`), no step-up 403, viewer 403 (RBAC before the body), bad reason 422,
confirm mismatch 422, pinned without `include_pinned` 422 / with it 202, Idempotency-Key reuse
(same body -> same job; different body -> 422; another actor -> independent, IDOR), 409 while a
purge runs, audit failure -> 503 and no job, unauthenticated 401, unwired 503.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from candleviewer.api.recorder_admin import AdminJobStore, make_recorder_admin_router
from candleviewer.api.recorder_purge import make_recorder_purge_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.recorder.retention import PrunePlan, RetentionManager, RunReport, day_key
from tests.unit.recorder._retention_fakes import NOW, T, World, day, manager

OWNER = {"recording:write", "admin:read"}
BODY = {"symbol": "BTCUSDT", "confirm_symbol": "BTCUSDT", "reason": "free disk"}


class _Audit:
    def __init__(self, w: World, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail, self.w = fail, w

    async def emit(self, action: str, **kw: Any) -> None:
        if self.fail:
            raise RuntimeError("audit down")
        self.calls.append((action, kw | {"_deleted_so_far": len(self.w.deletes)}))


class _Resolver:
    def __init__(self) -> None:
        self.p: AuditPrincipal | None = None

    def as_(
        self, perms: set[str] | None, uid: uuid.UUID | None = None, *, owner: bool = True
    ) -> None:
        self.p = (
            None
            if perms is None
            else AuditPrincipal(
                uid or uuid.uuid4(),
                "u",
                frozenset(perms),
                uuid.uuid4(),
                request_id=uuid.uuid4(),
                is_owner=owner,
            )
        )

    async def resolve(self, request: Any) -> AuditPrincipal | None:
        return self.p


class _Gated:
    """Backend wrapper whose `run` waits on a gate (to observe 409 / in-flight jobs)."""

    def __init__(self, m: RetentionManager) -> None:
        self.m, self.gate = m, asyncio.Event()
        self.gate.set()
        self.runs = 0
        self.plans = 0

    async def is_pinned(self, symbol: str) -> bool:
        return await self.m.is_pinned(symbol)

    async def plan_purge(self, symbol: str, before_us: int, *, include_pinned: bool) -> PrunePlan:
        self.plans += 1
        return await self.m.plan_purge(symbol, before_us, include_pinned=include_pinned)

    async def run(self, plan: PrunePlan, dry_run: bool) -> RunReport:
        self.runs += 1
        await self.gate.wait()
        return await self.m.run(plan, dry_run)


class _Env:
    def __init__(self, *, fail_audit: bool = False, elevated: bool = True) -> None:
        self.w = World()
        self.w.add_cold("BTCUSDT", T, 2)
        self.w.add_cold("BTCUSDT", T, 40)
        self.audit = _Audit(self.w, fail=fail_audit)
        self.res = _Resolver()
        self.res.as_(OWNER)
        self.backend = _Gated(manager(self.w))
        self.elevated = elevated
        self.elevation_checks = 0
        app = FastAPI()
        self.jobs = jobs = AdminJobStore()

        async def elevation(request: Request, action_class: str) -> JSONResponse | None:
            self.elevation_checks += 1
            assert action_class == "recorder"
            if self.elevated:
                return None
            return JSONResponse(
                status_code=403, content={"code": "step_up_required", "action_class": "recorder"}
            )

        app.include_router(
            make_recorder_purge_router(
                jobs, self.backend, self.audit, self.res, elevation, clock=lambda: NOW
            )
        )
        app.include_router(make_recorder_admin_router(jobs, None, self.audit, self.res))
        self.c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def post(self, body: object, key: str | None = None) -> httpx.Response:
        return await self.c.post(
            "/admin/recorder/purge",
            json=body,
            headers={"Idempotency-Key": key or str(uuid.uuid4())},
        )

    async def wait(self, job_id: str, status: str = "succeeded") -> dict[str, Any]:
        for _ in range(500):
            body: dict[str, Any] = (await self.c.get(f"/admin/jobs/{job_id}")).json()
            if body["status"] == status:
                return body
            await asyncio.sleep(0)
        raise AssertionError(f"job never reached {status}")


def _actions(env: _Env) -> list[str]:
    return [a for a, _ in env.audit.calls]


def test_purge_audit_actions_are_registered() -> None:
    assert {"retention.purge", "retention.run", "data.deleted"} <= AUDIT_ACTIONS


async def test_purge_accepted_audits_exact_window_before_job_then_executes() -> None:
    env = _Env()
    r = await env.post(BODY)
    assert r.status_code == 202
    job = await env.wait(r.json()["job_id"])
    assert job["kind"] == "retention_purge" and job["result"]["deleted"] == 2
    first = env.audit.calls[0]
    assert first[0] == "retention.purge" and first[1]["_deleted_so_far"] == 0
    window = first[1]["before_state"]["window"]
    assert (window["symbol"], window["partitions"], window["rows"]) == ("BTCUSDT", 2, 200)
    assert window["from_us"] < window["to_us"] and first[1]["reason"] == "free disk"
    assert first[1]["object_id"] == r.json()["job_id"]
    assert env.w.cold[("BTCUSDT", T)] == {} and len(env.w.data_deleted()) == 2
    assert _actions(env)[-1] == "retention.purge"  # outcome record after the job


async def test_purge_day_shared_after_plan_is_kept_and_outcome_audit_names_reason() -> None:
    """Review round 4 (2): another symbol's rows land in the purged symbol's sole-symbol day
    after the plan (and its write-ahead audit) -> the day is kept, no `data.deleted` for it,
    and the `retention.purge` outcome record names `shared_partition`."""
    env = _Env()
    env.w.add_hot(T, 3, {"BTCUSDT": 4})
    env.backend.gate.clear()
    r = await env.post(BODY)
    assert r.status_code == 202
    env.w.hot[T][day(3)]["ETHUSDT"] = 2  # lands between plan_purge and the drop
    env.backend.gate.set()
    job = await env.wait(r.json()["job_id"])
    skipped = [{"partition": day_key(day(3)), "reason": "shared_partition"}]
    assert job["result"]["skipped"] == skipped and day(3) in env.w.hot[T]
    assert [d["tier"] for d in env.w.data_deleted()] == ["cold", "cold"]
    action, outcome = env.audit.calls[-1]
    assert action == "retention.purge" and outcome["after_state"]["result"]["skipped"] == skipped


async def test_purge_plan_time_holds_are_listed_in_the_job_result_and_outcome_audit() -> None:
    """Review round 5 (Low): a day held while PLANNING (shared with another symbol) never reaches
    the delete-time re-check, so `skipped` stays empty. The write-ahead record carries only its
    count (`window.protected`); the job result and the closing `retention.purge` list it."""
    env = _Env()
    env.w.add_hot(T, 3, {"BTCUSDT": 4, "ETHUSDT": 2})  # already shared when the plan is made
    r = await env.post(BODY)
    assert r.status_code == 202
    job = await env.wait(r.json()["job_id"])
    held = [{"partition": day_key(day(3)), "reason": "shared_partition"}]
    assert job["result"]["protected"] == held and job["result"]["skipped"] == []
    assert env.audit.calls[0][1]["before_state"]["window"]["protected"] == 1
    action, outcome = env.audit.calls[-1]
    assert action == "retention.purge" and outcome["after_state"]["result"]["protected"] == held
    assert day(3) in env.w.hot[T] and [d["tier"] for d in env.w.data_deleted()] == ["cold", "cold"]


async def test_purge_without_step_up_is_403_and_nothing_deleted() -> None:
    env = _Env(elevated=False)
    r = await env.post(BODY)
    assert r.status_code == 403 and r.json()["code"] == "step_up_required"
    assert env.backend.runs == 0 and env.w.deletes == []
    assert env.audit.calls[0][1]["reason"] == "purge_requires_elevation"


async def test_purge_viewer_is_403_before_body_or_step_up() -> None:
    env = _Env()
    env.res.as_({"admin:read"})
    r = await env.c.post("/admin/recorder/purge", content=b"not json")
    assert r.status_code == 403 and env.elevation_checks == 0
    assert env.audit.calls[0][1]["outcome"].value == "denied"


async def test_purge_unauthenticated_is_401() -> None:
    env = _Env()
    env.res.as_(None)
    assert (await env.post(BODY)).status_code == 401


async def test_purge_bad_reason_is_422() -> None:
    env = _Env()
    for reason in ("no", "x" * 281):
        r = await env.post(BODY | {"reason": reason})
        assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert env.backend.runs == 0


async def test_purge_reason_with_nul_is_the_same_422_and_nothing_runs() -> None:
    env = _Env()
    r = await env.post(BODY | {"reason": "free\x00disk"})
    assert r.status_code == 422
    assert r.json() == (await env.post(BODY | {"reason": "no"})).json()  # no echo, same shape
    assert env.backend.runs == 0 and env.audit.calls == []


async def test_purge_confirm_mismatch_is_422_and_nothing_deleted() -> None:
    env = _Env()
    r = await env.post(BODY | {"confirm_symbol": "BTCUSD"})
    assert r.status_code == 422
    r = await env.post(BODY | {"confirm_symbol": "ETHUSDT"})
    assert r.status_code == 422 and r.json()["code"] == "purge_confirmation_mismatch"
    assert env.w.deletes == [] and env.backend.runs == 0


async def test_purge_pinned_without_include_pinned_is_422_with_it_202() -> None:
    env = _Env()
    env.w.pinned = {"BTCUSDT"}
    r = await env.post(BODY)
    assert r.status_code == 422 and r.json()["code"] == "retention_pinned_refused"
    r = await env.post(BODY | {"include_pinned": True})
    assert r.status_code == 202
    await env.wait(r.json()["job_id"])
    assert env.w.cold[("BTCUSDT", T)] == {}


async def test_purge_before_bounds_the_window() -> None:
    env = _Env()
    r = await env.post(BODY | {"before": "2026-09-20T00:00:00Z"})
    await env.wait(r.json()["job_id"])
    assert len(env.w.cold[("BTCUSDT", T)]) == 1  # the 2-day-old partition survives


async def test_purge_naive_before_is_422() -> None:
    env = _Env()
    r = await env.post(BODY | {"before": "2026-09-20T00:00:00"})
    assert r.status_code == 422


async def test_purge_idempotency_same_body_same_job_different_body_422() -> None:
    env = _Env()
    key = str(uuid.uuid4())
    first = await env.post(BODY, key)
    again = await env.post(BODY, key)
    assert first.json()["job_id"] == again.json()["job_id"]
    other = await env.post(BODY | {"reason": "something else"}, key)
    assert other.status_code == 422 and other.json()["code"] == "idempotency_key_reused"
    assert env.backend.runs <= 1


async def test_purge_idempotency_key_never_crosses_actors_idor() -> None:
    env = _Env()
    env.backend.gate.clear()
    key = str(uuid.uuid4())
    a = await env.post(BODY, key)
    env.res.as_(OWNER)  # a different user, same key
    b = await env.post(BODY, key)
    assert a.status_code == 202 and b.status_code == 409  # not A's job id
    env.backend.gate.set()


async def test_purge_concurrent_is_409() -> None:
    env = _Env()
    env.backend.gate.clear()
    assert (await env.post(BODY)).status_code == 202
    r = await env.post(BODY)
    assert r.status_code == 409 and r.json()["code"] == "job_running"
    env.backend.gate.set()


async def test_purge_audit_failure_is_503_and_no_job() -> None:
    env = _Env(fail_audit=True)
    r = await env.post(BODY)
    assert r.status_code == 503 and r.json()["code"] == "audit_unavailable"
    assert env.backend.runs == 0 and env.w.deletes == []


async def test_purge_missing_idempotency_key_is_400() -> None:
    env = _Env()
    r = await env.c.post("/admin/recorder/purge", json=BODY)
    assert r.status_code == 400


async def test_purge_unwired_backend_is_503() -> None:
    app = FastAPI()
    res = _Resolver()
    res.as_(OWNER)
    app.include_router(make_recorder_purge_router(AdminJobStore(), None, None, res, None))
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    assert (await c.post("/admin/recorder/purge", json=BODY)).status_code == 503
    app2 = FastAPI()
    app2.include_router(make_recorder_purge_router(AdminJobStore(), None, None, None, None))
    c2 = httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://t")
    assert (await c2.post("/admin/recorder/purge", json=BODY)).status_code == 501


async def test_purge_manager_with_recording_write_is_403_owner_only_and_audited() -> None:
    env = _Env()
    env.res.as_(OWNER, owner=False)
    r = await env.post(BODY)
    assert r.status_code == 403
    assert env.elevation_checks == 0 and env.backend.runs == 0 and env.w.deletes == []
    action, kw = env.audit.calls[0]
    assert action == "retention.purge" and kw["reason"] == "purge_owner_only"
    assert kw["outcome"].value == "denied"


async def test_purge_elevated_manager_is_403_before_body_read_and_starts_nothing() -> None:
    """#2575 / 04 §7.2.2 row 9a: Managers hold `recording:write`, so the handler's owner check is
    all that stands between them and an irreversible delete. It runs before the body and the
    Idempotency-Key are looked at (an unparseable body and no key still read as the owner-only
    403, not 400/422) and before step-up (a completed elevation never widens who may purge).
    No job is created, nothing is planned or deleted, and the only audit record is the denied
    `retention.purge` naming `purge_owner_only` (not a purge intent)."""
    env = _Env()  # elevated
    env.res.as_(OWNER, owner=False)
    r = await env.c.post("/admin/recorder/purge", content=b"{not json")
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert env.elevation_checks == 0
    assert env.backend.plans == 0 and env.backend.runs == 0 and env.w.deletes == []
    assert env.jobs._jobs == {}
    ((action, kw),) = env.audit.calls
    assert (action, kw["outcome"].value, kw["reason"]) == (
        "retention.purge",
        "denied",
        "purge_owner_only",
    )
    assert "before_state" not in kw


async def test_purge_concurrent_loser_writes_no_intent_record() -> None:
    """Review (b): the 409 loser must not leave an orphan `retention.purge` intent entry."""
    env = _Env()
    gate = asyncio.Event()
    real_plan = env.backend.plan_purge

    async def slow_plan(symbol: str, before_us: int, *, include_pinned: bool) -> PrunePlan:
        await gate.wait()
        return await real_plan(symbol, before_us, include_pinned=include_pinned)

    env.backend.plan_purge = slow_plan  # type: ignore[method-assign]  # hold the winner mid-flight
    winner = asyncio.ensure_future(env.post(BODY))
    for _ in range(50):
        await asyncio.sleep(0)
    loser = await env.post(BODY | {"reason": "second"})
    gate.set()
    assert (await winner).status_code == 202
    assert loser.status_code == 409
    intents = [kw for a, kw in env.audit.calls if a == "retention.purge" and "before_state" in kw]
    assert len(intents) == 1 and intents[0]["reason"] == "free disk"


async def test_purge_non_owner_never_reaches_step_up_even_unelevated() -> None:
    """Review (a): an unelevated manager sees the audited owner-only 403, not a step-up prompt."""
    env = _Env(elevated=False)
    env.res.as_(OWNER, owner=False)
    r = await env.post(BODY)
    assert r.status_code == 403 and r.json().get("code") != "step_up_required"
    assert env.elevation_checks == 0
    assert env.audit.calls[0][1]["reason"] == "purge_owner_only"
