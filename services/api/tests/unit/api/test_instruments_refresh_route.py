"""Unit: `POST /instruments/refresh` (`refreshInstruments`, E08-T10, #5111) with fakes.

The route over the admin job store and the catalogue scheduler (a fake, or the real one over
recorded-shape pages, no network, C-13.5): the `202` that never awaits the fetch, RBAC fail-closed
(501, 401, 403, Owner only), the `instruments` step-up demanded after RBAC (the orchestrator's
ruling of 2026-10-31 on #5111), the 503 causes, the join (Q1), the 60 s limit (Q2), the per-user
bucket and venue-budget `429`s, the idempotent replay, and the write-ahead audit with the job's
`instruments.refresh.completed` (Q3), polled through `getJob` (Q4). CSRF is the edge middleware's
(SR-041); its refusal is asserted on the mounted app (`tests/contract/
test_instruments_refresh_route_contract.py`), as is the gate over the real step-up service below.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from candleviewer.api.instruments import (
    REFRESH_JOB_KIND,
    REFRESH_STEP_UP_CLASS,
    CatalogueReader,
    make_instruments_refresh_router,
    make_instruments_router,
)
from candleviewer.api.recorder_admin import AdminJobStore
from candleviewer.api.step_up_challenge import ChallengeText
from candleviewer.audit.access import AuditPrincipal
from candleviewer.ingestion.instruments_refresh import (
    InstrumentRefreshError,
    InstrumentsRefreshScheduler,
)
from tests.unit.api._job_poll import mount_job_poll
from tests.unit.ingestion.test_instruments_refresh import _count, make, raw

OWNER = frozenset({"*"})
#: The seeded Manager and Viewer hold no `instruments:write` (`auth/rbac_seed.json`).
MANAGER = frozenset({"instruments:read", "marketdata:read", "orders:write", "admin:read"})
VIEWER = frozenset({"instruments:read", "marketdata:read"})


class Audit:
    def __init__(self, *, fail: bool = False, jobs: AdminJobStore | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail
        self.jobs = jobs
        self.held_at_write: list[int] = []

    async def emit(self, action: str, **kw: Any) -> None:
        if self.jobs is not None:
            self.held_at_write.append(self.jobs.held())
        if self.fail:
            raise RuntimeError("wal down")
        self.calls.append((action, kw))

    def actions(self) -> list[str]:
        return [a for a, _ in self.calls]


class Resolver:
    def __init__(self, perms: frozenset[str] | None, *, owner: bool = True) -> None:
        self.principal = (
            None
            if perms is None
            else AuditPrincipal(
                uuid.uuid4(),
                "owner",
                perms,
                session_id=uuid.uuid4(),
                ip="100.64.0.1",
                request_id=uuid.uuid4(),
                is_owner=owner,
            )
        )

    async def resolve(self, request: Any) -> AuditPrincipal | None:
        return self.principal


class Refresher:
    """A scheduler fake: `refresh_now` parks until `gate` is set (or forever), then fails or not."""

    def __init__(self, *, fail: bool = False) -> None:
        self.gate = asyncio.Event()
        self.calls = 0
        self.stopped = False
        self.fail = fail

    async def refresh_now(self) -> None:
        self.calls += 1
        await self.gate.wait()
        if self.fail:
            raise InstrumentRefreshError("upstream said <html>secret body</html>")


class Elevation:
    """A `RequestElevation` fake: admits while `held`, else answers the `403 step_up_required`
    of the route's class, as `required_problem` shapes it; records what each demand restated."""

    def __init__(self, *, held: bool = True) -> None:
        self.held = held
        self.texts: list[ChallengeText] = []

    async def __call__(self, request: Request, text: ChallengeText) -> JSONResponse | None:
        self.texts.append(text)
        if self.held:
            return None
        body = {
            "code": "step_up_required",
            "action_class": REFRESH_STEP_UP_CLASS,
            "action_summary": text.action_summary,
        }
        return JSONResponse(body, 403, media_type="application/problem+json")


class Mono:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


class World:
    def __init__(
        self,
        perms: frozenset[str] | None = OWNER,
        *,
        refresher: Any = None,
        provide: bool = True,
        audit: Audit | None = None,
        wired_audit: bool = True,
        resolver: bool = True,
        headroom: tuple[float, float] | None = None,
        bucket_wait: int | None = None,
        reads: bool = False,
        elevation: Elevation | None = None,
        wired_elevation: bool = True,
        reads_now_us: Any = None,
    ) -> None:
        self.jobs = AdminJobStore()
        self.audit = audit or Audit(jobs=self.jobs)
        self.audit.jobs = self.jobs
        self.refresher = refresher if refresher is not None else Refresher()
        self.resolver = Resolver(perms)
        self.mono = Mono()
        self.elevation = elevation or Elevation()
        self.bucket_calls: list[uuid.UUID] = []

        def bucket(user: uuid.UUID) -> int | None:
            self.bucket_calls.append(user)
            return bucket_wait

        app = FastAPI()
        app.include_router(
            make_instruments_refresh_router(
                (lambda: self.refresher) if provide else (lambda: None),
                self.jobs,
                audit=self.audit if wired_audit else None,
                environment="demo",
                principal_resolver=self.resolver if resolver else None,
                venue_headroom=(lambda: headroom) if headroom is not None else None,
                user_bucket=bucket,
                elevation=self.elevation if wired_elevation else None,
                monotonic=self.mono,
                wall_clock=lambda: datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC),
            )
        )
        if reads:
            app.include_router(
                make_instruments_router(
                    lambda: cast(CatalogueReader, self.refresher),  # the real scheduler here
                    principal_resolver=self.resolver,
                    **({} if reads_now_us is None else {"now_us": reads_now_us}),
                )
            )
        mount_job_poll(app, self.jobs, self.resolver)
        self.c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def post(self, key: str | None = None) -> httpx.Response:
        headers = {"Idempotency-Key": key} if key is not None else {}
        return await self.c.post("/instruments/refresh", headers=headers)

    async def poll(self, job_id: str, status: str) -> dict[str, Any]:
        for _ in range(200):
            body: dict[str, Any] = (await self.c.get(f"/admin/jobs/{job_id}")).json()
            if body["status"] == status:
                return body
            await asyncio.sleep(0)
        raise AssertionError(f"job never reached {status}: {body}")


# -- the 202 and the job ----------------------------------------------------------------------


async def test_refresh_owner_answers_202_without_awaiting_the_fetch() -> None:
    w = World()  # the fake's fetch never returns until its gate opens
    r = await w.post()
    assert r.status_code == 202 and "Idempotency-Replayed" not in r.headers
    body = r.json()
    assert set(body) == {"job_id", "scheduled_at"}
    assert str(uuid.UUID(body["job_id"])) == body["job_id"]
    assert body["scheduled_at"] == "2026-10-31T12:00:00+00:00"
    running = await w.poll(body["job_id"], "running")
    assert running["kind"] == REFRESH_JOB_KIND and running["result"] is None
    assert w.refresher.calls == 1


async def test_refresh_job_succeeds_with_the_envelope_and_a_completed_record() -> None:
    w = World()
    job_id = (await w.post()).json()["job_id"]
    w.refresher.gate.set()
    done = await w.poll(job_id, "succeeded")
    assert done["kind"] == REFRESH_JOB_KIND and done["result"] == {} and done["error"] is None
    assert w.audit.actions() == ["instruments.refresh.requested", "instruments.refresh.completed"]
    completed = w.audit.calls[1][1]
    assert completed["object_id"] == job_id and completed["outcome"].value == "success"
    assert completed["after_state"] == {"env": "demo", "status": "succeeded"}


async def test_refresh_job_failure_keeps_a_stable_code_and_no_message() -> None:
    w = World(refresher=Refresher(fail=True))
    job_id = (await w.post()).json()["job_id"]
    w.refresher.gate.set()
    failed = await w.poll(job_id, "failed")
    assert failed["error"] == "InstrumentRefreshError" and failed["result"] is None
    assert "secret" not in str(failed)
    completed = w.audit.calls[-1]
    assert completed[0] == "instruments.refresh.completed"
    assert completed[1]["outcome"].value == "failure"
    assert completed[1]["reason"] == "InstrumentRefreshError"
    assert completed[1]["after_state"]["status"] == "failed"
    assert "secret" not in str(w.audit.calls)


async def test_refresh_job_cancelled_at_stop_writes_no_completed_record() -> None:
    w = World()
    job_id = (await w.post()).json()["job_id"]
    await w.poll(job_id, "running")
    await w.jobs.stop()
    assert (await w.poll(job_id, "cancelled"))["error"] is None
    assert w.audit.actions() == ["instruments.refresh.requested"]


# -- RBAC, wiring, CSRF-free unit refusals ----------------------------------------------------


async def test_refresh_manager_viewer_and_anonymous_are_refused_and_start_nothing() -> None:
    statuses = []
    for perms in (MANAGER, VIEWER, None):
        w = World(perms)
        r = await w.post()
        statuses.append(r.status_code)
        assert w.jobs.held() == 0 and w.refresher.calls == 0 and w.audit.calls == []
    assert statuses == [403, 403, 401]


async def test_refresh_no_resolver_answers_501() -> None:
    w = World(resolver=False)
    r = await w.post()
    assert r.status_code == 501 and r.json()["code"] == "not_implemented"
    assert w.jobs.held() == 0


async def test_refresh_unwired_or_stopped_scheduler_or_audit_answers_503() -> None:
    stopped = Refresher()
    stopped.stopped = True
    for w in (World(provide=False), World(refresher=stopped), World(wired_audit=False)):
        r = await w.post()
        assert r.status_code == 503 and r.json()["code"] == "instrument_cache_unavailable"
        assert w.jobs.held() == 0 and w.audit.calls == []


async def test_refresh_malformed_idempotency_key_answers_400() -> None:
    w = World()
    r = await w.post("not-a-uuid")
    assert r.status_code == 400 and r.json()["code"] == "validation_failed"
    assert w.jobs.held() == 0


# -- the `instruments` step-up (04 §7.2.2 row 5a, SR-025; ruling of 2026-10-31) --------------


async def test_refresh_without_step_up_answers_403_step_up_required_and_starts_nothing() -> None:
    w = World(headroom=(5.0, 0.0), elevation=Elevation(held=False))
    r = await w.post(str(uuid.uuid4()))
    assert r.status_code == 403
    assert r.json()["code"] == "step_up_required"
    assert r.json()["action_class"] == REFRESH_STEP_UP_CLASS == "instruments"
    assert w.jobs.held() == 0 and w.refresher.calls == 0 and w.audit.calls == []
    assert w.bucket_calls == []  # nothing counted or spent before the gate


async def test_refresh_challenge_restates_the_servers_environment() -> None:
    w = World()
    assert (await w.post()).status_code == 202
    assert w.elevation.texts == [ChallengeText("Refresh the demo instrument catalogue from Bybit")]


async def test_refresh_forbidden_role_is_refused_before_any_challenge() -> None:
    for perms in (MANAGER, VIEWER, None):
        w = World(perms, elevation=Elevation(held=False))
        assert (await w.post()).status_code in (401, 403)
        assert w.elevation.texts == []


async def test_refresh_scheduler_down_or_bad_key_answers_before_any_challenge() -> None:
    w = World(provide=False, elevation=Elevation(held=False))
    assert (await w.post()).status_code == 503
    w2 = World(elevation=Elevation(held=False))
    assert (await w2.post("not-a-uuid")).status_code == 400
    assert w.elevation.texts == [] and w2.elevation.texts == []


async def test_refresh_step_up_unwired_answers_503_and_starts_nothing() -> None:
    w = World(wired_elevation=False)
    r = await w.post()
    assert r.status_code == 503 and r.json()["code"] == "service_unavailable"
    assert w.jobs.held() == 0 and w.audit.calls == []


async def test_refresh_join_and_replay_still_demand_the_step_up() -> None:
    w = World()
    key = str(uuid.uuid4())
    assert (await w.post(key)).status_code == 202
    w.elevation.held = False
    assert (await w.post(key)).status_code == 403  # the replay
    assert (await w.post()).status_code == 403  # the join
    assert w.audit.actions() == ["instruments.refresh.requested"]


# -- Q1 join, Q2 limit, the two 429s ----------------------------------------------------------


async def test_refresh_while_one_runs_joins_it_never_409() -> None:
    w = World()
    first = (await w.post()).json()
    await w.poll(first["job_id"], "running")
    w.mono.t += 5
    r = await w.post()
    assert r.status_code == 202 and r.json() == first
    assert "Idempotency-Replayed" not in r.headers
    assert w.jobs.held() == 1 and w.refresher.calls == 1
    requested = [kw for a, kw in w.audit.calls if a == "instruments.refresh.requested"]
    assert [kw["after_state"]["joined"] for kw in requested] == [False, True]
    assert {kw["object_id"] for kw in requested} == {first["job_id"]}


async def test_refresh_join_spends_no_bucket_or_venue_and_is_not_counted_by_the_limit() -> None:
    w = World(headroom=(5.0, 0.0))
    await w.post()
    bucket_after_first = len(w.bucket_calls)
    w.mono.t += 59  # a join inside the window: answered, not refused, not counted
    assert (await w.post()).status_code == 202
    assert len(w.bucket_calls) == bucket_after_first
    w.refresher.gate.set()
    await w.poll((await w.post()).json()["job_id"], "succeeded")
    w.mono.t += 1  # 60 s after the accepted refresh, not after the join
    r = await w.post()
    assert r.status_code == 202 and w.jobs.held() == 2


async def test_refresh_second_inside_60s_is_refused_with_retry_after() -> None:
    w = World()
    w.refresher.gate.set()
    first = (await w.post()).json()["job_id"]
    await w.poll(first, "succeeded")
    w.mono.t += 59.5
    r = await w.post()
    assert r.status_code == 429 and r.json()["code"] == "rate_limited"
    assert r.headers["Retry-After"] == "1" and r.json()["retry_after_seconds"] == 1
    assert w.jobs.held() == 1 and w.refresher.calls == 1
    w.mono.t += 0.5
    second = await w.post()
    assert second.status_code == 202
    await w.poll(second.json()["job_id"], "succeeded")
    assert w.refresher.calls == 2


async def test_refresh_over_the_per_user_bucket_answers_429_rate_limited() -> None:
    w = World(bucket_wait=7)
    r = await w.post()
    assert r.status_code == 429 and r.json()["code"] == "rate_limited"
    assert r.headers["Retry-After"] == "7" and r.json()["retry_after_seconds"] == 7
    assert w.jobs.held() == 0 and w.audit.calls == []
    principal = w.resolver.principal
    assert principal is not None and w.bucket_calls == [principal.actor_id]


async def test_refresh_without_venue_budget_answers_429_exchange_rate_limited() -> None:
    w = World(headroom=(0.4, 3.2))
    r = await w.post()
    assert r.status_code == 429 and r.json()["code"] == "exchange_rate_limited"
    assert r.headers["Retry-After"] == "4" and r.json()["retry_after_seconds"] == 4
    assert w.jobs.held() == 0 and w.refresher.calls == 0 and w.audit.calls == []
    w2 = World(headroom=(1.0, 0.0))
    assert (await w2.post()).status_code == 202


# -- idempotency ------------------------------------------------------------------------------


async def test_refresh_same_key_replays_the_original_202() -> None:
    w = World()
    key = str(uuid.uuid4())
    first = await w.post(key)
    w.refresher.gate.set()
    await w.poll(first.json()["job_id"], "succeeded")
    w.mono.t += 3_600
    again = await w.post(key)
    assert again.status_code == 202 and again.json() == first.json()
    assert again.headers["Idempotency-Replayed"] == "true"
    assert w.jobs.held() == 1 and w.refresher.calls == 1
    assert w.audit.actions().count("instruments.refresh.requested") == 1


async def test_refresh_key_older_than_24h_is_a_new_request() -> None:
    w = World()
    key = str(uuid.uuid4())
    w.refresher.gate.set()
    first = (await w.post(key)).json()
    await w.poll(first["job_id"], "succeeded")
    w.mono.t += 86_400
    again = await w.post(key)
    assert again.status_code == 202 and "Idempotency-Replayed" not in again.headers
    assert again.json()["job_id"] != first["job_id"]


# -- the write-ahead audit (Q3) ---------------------------------------------------------------


async def test_refresh_requested_is_written_before_the_job_exists() -> None:
    w = World()
    job_id = (await w.post()).json()["job_id"]
    assert w.audit.held_at_write == [0]
    action, kw = w.audit.calls[0]
    assert action == "instruments.refresh.requested" and kw["object_id"] == job_id
    assert kw["object_kind"] == REFRESH_JOB_KIND and kw["actor_label"] == "owner"
    principal = w.resolver.principal
    assert principal is not None
    assert kw["actor_user_id"] == principal.actor_id
    assert kw["session_id"] == principal.session_id and kw["actor_ip"] == "100.64.0.1"
    assert kw["after_state"] == {"env": "demo", "role": "owner", "joined": False}


async def test_refresh_audit_failure_answers_503_and_starts_nothing() -> None:
    w = World(audit=Audit(fail=True))
    r = await w.post()
    assert r.status_code == 503 and r.json()["code"] == "audit_unavailable"
    assert w.jobs.held() == 0 and w.refresher.calls == 0
    w.audit.fail = False  # nothing was counted by the limit: the next request is accepted
    assert (await w.post()).status_code == 202


async def test_refresh_join_whose_record_fails_answers_503() -> None:
    w = World()
    await w.post()
    w.audit.fail = True
    r = await w.post()
    assert r.status_code == 503 and r.json()["code"] == "audit_unavailable"
    assert w.jobs.held() == 1


async def test_refresh_completed_record_failure_is_logged_not_raised() -> None:
    w = World()
    job_id = (await w.post()).json()["job_id"]
    w.audit.fail = True
    w.refresher.gate.set()
    assert (await w.poll(job_id, "succeeded"))["error"] is None


# -- through the real scheduler (recorded shapes, no network) ---------------------------------


async def test_refresh_real_scheduler_succeeds_and_the_read_reports_a_fresh_catalogue() -> None:
    sched, _repo, _pub, clock = make([[raw("BTCUSDT")], [raw("BTCUSDT"), raw("ETHUSDT")]])
    await sched.refresh_now()
    w = World(refresher=sched, reads=True, reads_now_us=clock)
    clock.us += 3_600_000_000
    job_id = (await w.post()).json()["job_id"]
    await w.poll(job_id, "succeeded")
    meta = (await w.c.get("/instruments")).json()["meta"]
    assert meta["stale_since"] is None and meta["count"] == 2
    assert meta["cache_age_s"] < 3_600


async def test_refresh_real_scheduler_failure_keeps_catalogue_stale_and_counts_error() -> None:
    sched, _repo, _pub, _clock = make([[raw("BTCUSDT")], RuntimeError("venue 503")])
    await sched.refresh_now()
    errors = _count("error")
    w = World(refresher=sched, reads=True)
    job_id = (await w.post()).json()["job_id"]
    failed = await w.poll(job_id, "failed")
    assert failed["error"] == "InstrumentRefreshError"
    listing = (await w.c.get("/instruments")).json()
    assert [i["symbol"] for i in listing["items"]] == ["BTCUSDT"]
    assert listing["meta"]["stale_since"] is not None
    assert _count("error") == errors + 1


async def test_refresh_scheduler_stopped_answers_503() -> None:
    sched, *_ = make([[raw("BTCUSDT")]])
    assert isinstance(sched, InstrumentsRefreshScheduler) and not sched.stopped
    await sched.stop()
    w = World(refresher=sched)
    assert (await w.post()).status_code == 503


async def test_refresh_route_serves_a_delisting_and_a_tick_size_change() -> None:
    """E08-TC-A05 and A08, re-pointed at the route: a refresh through it serves the venue's
    delisting (`Closed`, `delisted: true`) and BTCUSDT's new tick size with a new revision."""
    wider = {"tickSize": "0.50", "minPrice": "0.50", "maxPrice": "999999.00"}
    sched, *_ = make(
        [
            [raw("BTCUSDT"), raw("XYZUSDT")],
            [raw("BTCUSDT", priceFilter=wider), raw("XYZUSDT", status="Closed")],
        ]
    )
    await sched.refresh_now()
    w = World(refresher=sched, reads=True)
    before = (await w.c.get("/instruments/BTCUSDT")).json()
    await w.poll((await w.post()).json()["job_id"], "succeeded")
    after = (await w.c.get("/instruments/BTCUSDT")).json()
    assert (before["tick_size"], after["tick_size"]) == ("0.10", "0.50")
    assert after["revision"] != before["revision"]
    delisted = (await w.c.get("/instruments/XYZUSDT")).json()
    assert (delisted["status"], delisted["delisted"]) == ("Closed", True)
    listing = (await w.c.get("/instruments")).json()["items"]
    assert [i["symbol"] for i in listing] == ["BTCUSDT"]
