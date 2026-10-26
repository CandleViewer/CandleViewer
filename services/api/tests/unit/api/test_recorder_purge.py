"""Unit (E16-T06): `POST /admin/recorder/purge` security + contract matrix.

202 happy path (write-ahead `retention.purge` with the exact window before the job, then each
deletion's `data.deleted`), no step-up 403, viewer 403 (RBAC before the body), bad reason 422,
confirm mismatch 422, a missing or future `before` 422 (all three before the step-up, spending no
code), pinned without `include_pinned` 422 / with it 202, Idempotency-Key reuse (same body -> same
job; another `before` -> 409 naming the anchored bound; another difference -> 422; another actor
-> independent, IDOR), the anchor surviving a restart (a fresh router over the same durable
store), 409 while a purge runs, audit failure -> 503 and no job, unauthenticated 401, unwired 503.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from candleviewer.api.recorder_admin import AdminJobStore
from candleviewer.api.recorder_purge import _holds, make_recorder_purge_router
from candleviewer.api.step_up import SpentGrant
from candleviewer.api.step_up_challenge import request_fingerprint
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.auth.step_up import StepUpChallenge
from candleviewer.recorder.retention import (
    Protected,
    PruneItem,
    PrunePlan,
    RetentionManager,
    RunReport,
    day_key,
)
from tests.unit.api._job_poll import mount_job_poll
from tests.unit.api._purge_anchors import InMemoryPurgeAnchors
from tests.unit.recorder._retention_fakes import NOW, NOW_US, T, World, day, manager

OWNER = {"recording:write", "admin:read"}
#: `before` is the server clock's instant (the latest bound a purge may name).
BODY = {
    "symbol": "BTCUSDT",
    "confirm_symbol": "BTCUSDT",
    "reason": "free disk",
    "before": NOW.isoformat().replace("+00:00", "Z"),
}
_PATH = "/admin/recorder/purge"


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
    """One process: its job store, its lock and its router. `anchors` is the durable store; a
    fresh `_Env` over the same `anchors` (and tiers) models a restart of the service."""

    def __init__(
        self,
        *,
        fail_audit: bool = False,
        elevated: bool = True,
        anchors: InMemoryPurgeAnchors | None = None,
        tiers: World | None = None,
        resolver: _Resolver | None = None,
        now: datetime = NOW,
    ) -> None:
        if tiers is None:
            tiers = World()
            tiers.add_cold("BTCUSDT", T, 2)
            tiers.add_cold("BTCUSDT", T, 40)
        self.w = tiers
        self.audit = _Audit(self.w, fail=fail_audit)
        if resolver is None:
            resolver = _Resolver()
            resolver.as_(OWNER)
        self.res = resolver
        self.backend = _Gated(manager(self.w))
        self.anchors = InMemoryPurgeAnchors() if anchors is None else anchors
        self.elevated = elevated
        self.elevation_checks = 0
        self.fingerprints: list[str] = []
        app = FastAPI()
        self.jobs = jobs = AdminJobStore()

        async def elevation(
            request: Request, action_class: str, fingerprint: str
        ) -> JSONResponse | SpentGrant:
            self.elevation_checks += 1
            self.fingerprints.append(fingerprint)
            assert action_class == "recorder_purge"
            if self.elevated:
                expires = NOW + timedelta(minutes=5)
                return SpentGrant(
                    StepUpChallenge(uuid.UUID(int=self.elevation_checks), action_class, expires)
                )
            content = {"code": "step_up_required", "action_class": "recorder_purge"}
            return JSONResponse(status_code=403, content=content)

        app.include_router(
            make_recorder_purge_router(
                jobs,
                self.backend,
                self.audit,
                self.res,
                elevation,
                anchors=self.anchors,
                clock=lambda: now,
            )
        )
        mount_job_poll(app, jobs, self.res)  # the poll, on the audited admin router
        self.c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def post(self, body: object, key: str | None = None) -> httpx.Response:
        return await self.c.post(
            _PATH,
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
    assert env.elevation_checks == 0  # decided before the gate: no code is spent


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


@pytest.mark.parametrize(
    "symbol",
    ["", "*", "BTC*", "../BTCUSDT", "BTCUSDT/..", "btcusdt", "A" * 30 + "USDT", "BTCUSDT\x00"],
    ids=["empty", "star", "prefix-glob", "dot-dot-lead", "dot-dot-tail", "lower", "long", "nul"],
)
async def test_purge_symbol_outside_the_closed_charset_is_422_and_nothing_is_planned(
    symbol: str,
) -> None:
    """The purge scope is one exact symbol: no wildcard, traversal or case fold widens it."""
    env = _Env()
    r = await env.post(BODY | {"symbol": symbol, "confirm_symbol": symbol})
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert env.backend.plans == 0 and env.backend.runs == 0 and env.w.deletes == []


async def test_purge_unknown_body_field_is_422_and_nothing_is_planned() -> None:
    env = _Env()
    r = await env.post(BODY | {"all": True})
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert env.backend.plans == 0 and env.w.deletes == []


async def test_purge_unelevated_owner_gets_the_body_422_first_then_step_up_for_a_valid_body() -> (
    None
):
    """The contract's order: RBAC, then the body (a refusal there spends no code), then the
    step-up. An unelevated Owner's invalid body is its 422 and never reaches the gate; a valid
    one is `403 step_up_required` for `recorder_purge`, and nothing is planned either way."""
    env = _Env(elevated=False)
    env.w.pinned.add("BTCUSDT")
    r = await env.post(BODY | {"include_pinned": True, "junk": 1})
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert env.elevation_checks == 0 and env.audit.calls == []
    r = await env.post(BODY | {"include_pinned": True})
    assert r.status_code == 403 and r.json()["code"] == "step_up_required"
    assert r.json()["action_class"] == "recorder_purge" and env.elevation_checks == 1
    assert env.backend.plans == 0 and env.w.deletes == []
    assert [kw["reason"] for _, kw in env.audit.calls] == ["purge_requires_elevation"]


async def test_purge_replayed_with_the_same_key_and_body_deletes_once() -> None:
    env = _Env()
    key = str(uuid.uuid4())
    first = await env.post(BODY, key)
    replay = await env.post(BODY, key)
    assert first.status_code == replay.status_code == 202 and first.json() == replay.json()
    await env.wait(first.json()["job_id"])
    again = await env.post(BODY, key)
    assert again.json() == first.json()
    assert env.backend.plans == 1 and env.backend.runs == 1 and len(env.w.deletes) == 2


def test_purge_holds_name_the_partition_key_and_reason_only() -> None:
    """A held partition is reported by its key and reason; the hold's internal detail stays out."""
    key = "trades/symbol=BTCUSDT/dt=2026-01-01"
    item = PruneItem("cold", "trades", ("BTCUSDT",), key, 0, 1, 1, 1)
    held = [Protected(item, "leased", "lease=replay-1 volume=/srv/rec")]
    assert _holds(held) == [{"partition": key, "reason": "leased"}]


def _iso(us: int) -> str:
    return (NOW + timedelta(microseconds=us)).isoformat().replace("+00:00", "Z")


async def test_purge_without_before_is_422_and_spends_no_code() -> None:
    env = _Env()
    body = {k: v for k, v in BODY.items() if k != "before"}
    r = await env.post(body)
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert env.elevation_checks == 0 and env.backend.plans == 0 and env.anchors.rows == {}


async def test_purge_before_later_than_the_server_clock_is_422_before_in_future() -> None:
    env = _Env()
    r = await env.post(BODY | {"before": _iso(1)})
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert r.json()["errors"][0]["field"] == "before"
    assert r.json()["errors"][0]["rule"] == "before_in_future"
    assert env.elevation_checks == 0 and env.backend.plans == 0 and env.anchors.rows == {}


async def test_purge_before_the_epoch_is_422_and_spends_no_code() -> None:
    env = _Env()
    r = await env.post(BODY | {"before": "1969-12-31T23:59:59.999999Z"})
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert env.elevation_checks == 0 and env.anchors.rows == {}
    r = await env.post(BODY | {"before": "1970-01-01T00:00:00Z"})
    assert r.status_code == 202 and env.anchors.creates == 1


async def test_purge_before_in_future_message_carries_the_server_clock_rfc3339() -> None:
    env = _Env()
    r = await env.post(BODY | {"before": _iso(1)})
    assert BODY["before"] == "2026-10-20T02:15:00Z"  # NOW, the injected clock
    assert "2026-10-20T02:15:00Z" in r.json()["errors"][0]["message"]


async def test_purge_before_equal_to_the_server_clock_is_accepted_and_never_clamped() -> None:
    env = _Env()
    r = await env.post(BODY)  # `before` is NOW exactly
    assert r.status_code == 202
    await env.wait(r.json()["job_id"])
    window = env.audit.calls[0][1]["before_state"]["window"]
    assert window["before_us"] == NOW_US
    early = _Env()
    r = await early.post(BODY | {"before": _iso(-1)})
    await early.wait(r.json()["job_id"])
    assert early.audit.calls[0][1]["before_state"]["window"]["before_us"] == NOW_US - 1


async def test_purge_gate_is_given_the_fingerprint_of_the_validated_request() -> None:
    env = _Env()
    r = await env.post(BODY)
    assert r.status_code == 202
    sent = json.loads(json.dumps(BODY))
    assert env.fingerprints == [request_fingerprint("POST", _PATH.encode(), sent)]


async def test_purge_same_key_another_before_is_409_naming_the_anchored_bound() -> None:
    env = _Env()
    key = str(uuid.uuid4())
    first = await env.post(BODY, key)
    await env.wait(first.json()["job_id"])
    other = await env.post(BODY | {"before": _iso(-60_000_000)}, key)
    assert other.status_code == 409 and other.json()["code"] == "idempotency_key_reuse"
    (error,) = other.json()["errors"]
    assert (error["field"], error["rule"]) == ("before", "idempotency_bound_mismatch")
    assert error["message"] == f"anchored before is {BODY['before']}"
    assert env.backend.plans == 1 and env.backend.runs == 1


async def test_purge_same_key_same_before_other_difference_stays_422() -> None:
    env = _Env()
    key = str(uuid.uuid4())
    await env.post(BODY, key)
    other = await env.post(BODY | {"include_pinned": True}, key)
    assert other.status_code == 422 and other.json()["code"] == "idempotency_key_reused"
    assert env.backend.plans == 1


async def test_purge_same_body_after_a_restart_is_a_new_purge_of_the_same_window() -> None:
    """The anchored bound holds across a restart: the retry is a new job over `[earliest,
    before)`, so data recorded at or after the first request's `before` is never deleted."""
    bound = _iso(day(5) - NOW_US)  # five days ago, a day boundary
    first = _Env()
    key = str(uuid.uuid4())
    one = await first.post(BODY | {"before": bound}, key)
    await first.wait(one.json()["job_id"])
    assert first.w.cold[("BTCUSDT", T)] != {}  # the 2-day-old partition is after the bound
    first.w.add_cold("BTCUSDT", T, 30)  # older than the bound: the new purge deletes it
    after = _Env(anchors=first.anchors, tiers=first.w, resolver=first.res)  # a restart
    two = await after.post(BODY | {"before": bound}, key)
    assert two.status_code == 202 and two.json()["job_id"] != one.json()["job_id"]
    await after.wait(two.json()["job_id"])
    window = after.audit.calls[0][1]["before_state"]["window"]
    assert window["before_us"] == day(5) and after.backend.plans == 1
    kept = after.w.cold[("BTCUSDT", T)]
    assert len(kept) == 1 and all(start >= day(5) for start, _ in kept.values())
    assert first.anchors.creates == 1 and len(first.anchors.rows) == 1  # anchored once, for good


async def test_purge_same_body_after_a_restart_still_spends_its_own_fresh_code() -> None:
    first = _Env()
    key = str(uuid.uuid4())
    await first.wait((await first.post(BODY, key)).json()["job_id"])
    after = _Env(anchors=first.anchors, tiers=first.w, resolver=first.res, elevated=False)
    r = await after.post(BODY, key)
    assert r.status_code == 403 and r.json()["code"] == "step_up_required"
    assert after.backend.plans == 0


async def test_purge_same_body_while_the_job_is_known_is_that_job() -> None:
    env = _Env()
    env.backend.gate.clear()  # the job is still running
    key = str(uuid.uuid4())
    first = await env.post(BODY, key)
    again = await env.post(BODY, key)
    assert again.status_code == 202 and again.json()["job_id"] == first.json()["job_id"]
    env.backend.gate.set()
    await env.wait(first.json()["job_id"])
    done = await env.post(BODY, key)  # finished, still known to this process
    assert done.json()["job_id"] == first.json()["job_id"] and env.backend.plans == 1


async def test_purge_retry_compares_before_first_whatever_else_differs() -> None:
    env = _Env()
    key = str(uuid.uuid4())
    await env.post(BODY, key)
    other = await env.post(BODY | {"before": _iso(-1), "reason": "another reason"}, key)
    assert other.status_code == 409 and other.json()["code"] == "idempotency_key_reuse"
    assert other.json()["errors"][0]["field"] == "before"


async def test_purge_retry_compares_before_as_an_instant_not_as_text() -> None:
    env = _Env()
    key = str(uuid.uuid4())
    await env.post(BODY, key)
    same_instant = (NOW + timedelta(hours=2)).isoformat().replace("+00:00", "+02:00")
    assert same_instant == "2026-10-20T04:15:00+02:00"
    r = await env.post(BODY | {"before": same_instant}, key)
    assert r.status_code == 422 and r.json()["code"] == "idempotency_key_reused"


async def test_purge_anchor_answers_at_any_age() -> None:
    first = _Env()
    key = str(uuid.uuid4())
    await first.wait((await first.post(BODY, key)).json()["job_id"])
    later = NOW + timedelta(days=400)
    after = _Env(anchors=first.anchors, tiers=first.w, resolver=first.res, now=later)
    r = await after.post(BODY | {"before": _iso(-1)}, key)
    assert r.status_code == 409 and r.json()["errors"][0]["message"].endswith(BODY["before"])


async def test_purge_refusals_and_503s_anchor_nothing() -> None:
    pinned = _Env()
    pinned.w.pinned = {"BTCUSDT"}
    assert (await pinned.post(BODY)).status_code == 422
    running = _Env()
    running.backend.gate.clear()
    assert (await running.post(BODY)).status_code == 202
    assert (await running.post(BODY)).status_code == 409  # job_running, another key
    running.backend.gate.set()
    unaudited = _Env(fail_audit=True)
    assert (await unaudited.post(BODY)).status_code == 503
    unelevated = _Env(elevated=False)
    assert (await unelevated.post(BODY)).status_code == 403
    assert pinned.anchors.rows == {} and unaudited.anchors.rows == {}
    assert unelevated.anchors.rows == {} and len(running.anchors.rows) == 1


async def test_purge_anchor_survives_a_restart_another_before_is_still_409() -> None:
    before = _Env()
    key = str(uuid.uuid4())
    first = await before.post(BODY, key)
    await before.wait(first.json()["job_id"])
    after = _Env(anchors=before.anchors, tiers=before.w, resolver=before.res)
    later = await after.post(BODY | {"before": _iso(-1)}, key)
    assert later.status_code == 409 and later.json()["code"] == "idempotency_key_reuse"
    assert later.json()["errors"][0]["message"] == f"anchored before is {BODY['before']}"
    assert after.backend.plans == 0 and after.audit.calls == []


async def test_purge_anchor_records_the_actor_key_fingerprint_bound_and_job() -> None:
    env = _Env()
    key = str(uuid.uuid4())
    r = await env.post(BODY, key)
    assert env.res.p is not None
    (((created_by, client_ref), anchor),) = env.anchors.rows.items()
    assert (created_by, client_ref) == (env.res.p.user_id, key)
    assert anchor.before_us == NOW_US and str(anchor.id) == r.json()["job_id"]
    assert anchor.request_sha256 == env.fingerprints[0]


async def test_purge_anchor_store_outage_is_503_and_nothing_runs() -> None:
    env = _Env()
    env.anchors.fail = OSError("down")
    r = await env.post(BODY)
    assert r.status_code == 503 and r.json()["code"] == "store_unavailable"
    assert env.backend.plans == 0 and env.backend.runs == 0 and env.jobs._jobs == {}


async def test_purge_anchor_write_failure_after_the_intent_is_503_and_no_job() -> None:
    env = _Env()
    real = env.anchors.create

    async def broken(anchor: Any) -> bool:
        raise OSError("down")

    env.anchors.create = broken  # type: ignore[method-assign]  # an outage at the insert only
    r = await env.post(BODY)
    assert r.status_code == 503 and r.json()["code"] == "store_unavailable"
    assert env.backend.runs == 0 and env.jobs._jobs == {} and env.w.deletes == []
    outcome = env.audit.calls[-1][1]
    assert outcome["outcome"].value == "failure" and outcome["reason"] == "anchor_unavailable"
    env.anchors.create = real  # type: ignore[method-assign]


async def test_purge_without_an_anchor_store_is_503_before_the_gate() -> None:
    app = FastAPI()
    res = _Resolver()
    res.as_(OWNER)
    checks: list[str] = []

    async def elevation(request: Request, action_class: str, fingerprint: str) -> JSONResponse:
        checks.append(action_class)
        return JSONResponse(status_code=403, content={})

    tiers = World()
    router = make_recorder_purge_router(
        AdminJobStore(), _Gated(manager(tiers)), _Audit(tiers), res, elevation, anchors=None
    )
    app.include_router(router)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    r = await c.post(_PATH, json=BODY, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 503 and checks == []
