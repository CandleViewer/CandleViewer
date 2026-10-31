"""Unit (E29-T06 #914): the two routes over the real job driver (`ReconcileJobs`: the real B19 on
its binding and the pass's recording doubles), reached through the runtime's own
`OnLaneReconciliation` on an inline lane, its record hopping back through the runtime's `Serving`,
as the composition reaches them. The record is durable before B19 is told, while the account is
still refused and B19 still rests where it was; an unwritten record tells B19 nothing (C-2.9,
C-2.21, BQ-5). The step-up is granted by a stand-in here: `test_admin_reconciliation.py` holds the
real gate."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from candleviewer.accounts.models import AccountKind, ExchangeAccount, ExchangeEnv
from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.api.admin_reconciliation import make_admin_reconciliation_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.step_up import StepUpChallenge
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.reconcile_job import ReconcileJobs, RetryHop, leaf_of
from candleviewer.oms_lane import Serving
from candleviewer.oms_wiring import OnLaneReconciliation
from candleviewer.statechart.bindings import b19_reconciliation as b19
from candleviewer.storage.repositories.accounts import OwnerScope
from tests.unit.oms.reconcile_rig import ACCOUNT, Job
from tests.unit.oms.test_oms_runtime import InlineLane
from tests.unit.oms.test_reconcile_driver import Timers, _driver, _locked, _resting, _sent

OWNER, SESSION = UUID(int=0x0E), UUID(int=0x5E)
BODY = {"reason": "Exchange reachable again; positions checked by hand."}
HEADERS = {"Authorization": "Bearer tok", "Idempotency-Key": str(UUID(int=0x914C))}
T0 = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


@pytest.fixture
async def timers() -> Timers:
    return Timers()


@pytest.fixture
async def job() -> AsyncIterator[Job]:
    wired = Job(retries=cast(Any, RetryHop()))  # the driver's hop, as its phases take it
    yield wired
    b19.set_ports(None)


class Owner:
    """The guard's resolver: every request is the Owner's, with a session."""

    async def resolve(self, request: Request) -> AuditPrincipal:
        perms = frozenset({"admin:read", "admin:write"})
        return AuditPrincipal(OWNER, "owner", perms, SESSION, "10.0.0.9", UUID(int=9), True)


class Accounts:
    async def get_account(self, scope: OwnerScope, account_id: UUID) -> ExchangeAccount:
        return ExchangeAccount(
            id=account_id, env=ExchangeEnv.DEMO, kind=AccountKind.MAIN, exchange_uid="1001234",
            label="Main", created_at=T0, updated_at=T0,
        )  # fmt: skip


class Granting:
    """A step-up that grants each `accounts` request its one-shot grant."""

    step_up_is_active = sessions_is_active = True
    sessions = None

    def __init__(self) -> None:
        self.step_up = self

    async def consume_single_use(
        self, session_id: str, action_class: str, *, fingerprint: str
    ) -> StepUpChallenge:
        return StepUpChallenge(uuid4(), action_class, T0 + timedelta(minutes=1), fingerprint)


class Recorder:
    """The serving loop's audit writer, noting at each `oms.reconcile` record whether the account
    is still refused and where its B19 rests; `fail` makes that record not durable."""

    def __init__(self, job: Job) -> None:
        self.job, self.fail = job, False
        self.driver: ReconcileJobs | None = None
        self.seen: list[tuple[str, bool, str]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        if action != "oms.reconcile":
            return
        if self.fail:
            raise AuditUnavailable("WAL unwritable")
        assert self.driver is not None
        state = leaf_of(self.driver._jobs[ACCOUNT].interp)
        self.seen.append((kw["after_state"]["stage"], self.job.standing.is_stale(ACCOUNT), state))


def _app(driver: ReconcileJobs, audit: Recorder) -> FastAPI:
    audit.driver = driver
    serving = Serving(asyncio.get_running_loop(), Metrics("demo"))
    parts = SimpleNamespace(
        reconcile=SimpleNamespace(jobs=driver), serving=serving, lane=InlineLane()
    )
    runtime = SimpleNamespace(readiness="ok", reconciliation=OnLaneReconciliation(cast(Any, parts)))
    app = FastAPI()
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    app.include_router(
        make_admin_reconciliation_router(
            Accounts(), lambda: runtime, environment="demo", auth=cast(Any, Granting()),
            resolver=Owner(), audit=audit,
        )
    )  # fmt: skip
    return app


async def _post(app: FastAPI, path: str, **kw: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, headers=HEADERS, **kw)


async def test_the_resolve_is_recorded_while_locked_then_b19_unlocks_and_the_standing_clears(
    job: Job, timers: Timers
) -> None:
    driver = _driver(job, timers)
    await driver.start([])
    await _locked(job, driver, timers)
    audit = Recorder(job)
    try:
        sent = await _post(
            _app(driver, audit), f"/admin/reconciliation/{ACCOUNT}/resolve", json=BODY
        )
        assert sent.status_code == 200 and sent.json()["resolved"] == "stale_lockout"
        assert audit.seen == [("resolved", True, "stale_lockout")]  # ahead of the unlock
        assert not job.standing.is_stale(ACCOUNT) and await _resting(driver) == "idle"
    finally:
        await driver.stop()


async def test_an_unwritten_decision_leaves_b19_locked_and_the_account_refused(
    job: Job, timers: Timers
) -> None:
    driver = _driver(job, timers)
    await driver.start([])
    await _locked(job, driver, timers)
    audit = Recorder(job)
    audit.fail = True
    try:
        sent = await _post(
            _app(driver, audit), f"/admin/reconciliation/{ACCOUNT}/resolve", json=BODY
        )
        assert (sent.status_code, sent.json()["code"]) == (503, "audit_unavailable")
        assert job.standing.is_stale(ACCOUNT) and await _resting(driver) == "stale_lockout"
    finally:
        await driver.stop()


async def test_the_manual_pass_is_recorded_before_b19_is_sent_its_sweep(
    job: Job, timers: Timers, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver = _driver(job, timers)
    await driver.start([ACCOUNT])
    await _resting(driver)
    sent_events = _sent(driver, monkeypatch)
    audit = Recorder(job)
    try:
        sent = await _post(_app(driver, audit), f"/admin/reconciliation/{ACCOUNT}")
        assert sent.status_code == 202 and sent.json()["joined"] is False
        assert audit.seen == [("requested", False, "idle")]  # B19 still idle: nothing sent yet
        assert sent_events == ["SWEEP_DUE"] and await _resting(driver) == "idle"
        finished = job.records.rows[-1][2]
        assert (finished["trigger"], finished["pass_id"]) == ("manual", sent.json()["pass_id"])
    finally:
        await driver.stop()


async def test_an_unwritten_request_sends_b19_nothing(
    job: Job, timers: Timers, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver = _driver(job, timers)
    await driver.start([ACCOUNT])
    await _resting(driver)
    sent_events = _sent(driver, monkeypatch)
    audit = Recorder(job)
    audit.fail = True
    try:
        sent = await _post(_app(driver, audit), f"/admin/reconciliation/{ACCOUNT}")
        assert (sent.status_code, sent.json()["code"]) == (503, "audit_unavailable")
        assert sent_events == [] and await _resting(driver) == "idle"
    finally:
        await driver.stop()


async def test_a_manual_request_opens_the_job_of_an_account_that_has_none(
    job: Job, timers: Timers
) -> None:
    """24 Sec.8.5: an on-demand request is a trigger, so it opens the account's job."""
    driver = _driver(job, timers)
    await driver.start([])
    audit = Recorder(job)
    try:
        assert ACCOUNT not in driver._jobs
        sent = await _post(_app(driver, audit), f"/admin/reconciliation/{ACCOUNT}")
        assert sent.status_code == 202 and ACCOUNT in driver._jobs
        assert audit.seen == [("requested", False, "idle")]
        assert await _resting(driver) == "idle"
    finally:
        await driver.stop()


async def test_a_locked_job_refuses_the_manual_pass_through_the_driver(
    job: Job, timers: Timers
) -> None:
    driver = _driver(job, timers)
    await driver.start([])
    await _locked(job, driver, timers)
    audit = Recorder(job)
    try:
        sent = await _post(_app(driver, audit), f"/admin/reconciliation/{ACCOUNT}")
        assert (sent.status_code, sent.json()["errors"][0]["rule"]) == (
            409, "reconciliation_locked",
        )  # fmt: skip
        assert audit.seen == [] and await _resting(driver) == "stale_lockout"
    finally:
        await driver.stop()
