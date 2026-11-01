"""Unit (E29-T06 #914): `reconcileAccount` and `resolveReconciliation` over HTTP (22, BQ-7), on the
real step-up service (`test_step_up_challenge_router`'s world) and the audited admin guard, over a
fake account store and a fake OMS whose service runs the route's write-ahead before it tells B19,
and tells it nothing when that raises, as the driver (`ReconcileJobs`) does through
`OnLaneReconciliation`; `test_admin_reconciliation_driver.py` runs the routes over the driver.

Each route has a forbidden-role case (a Manager, with or without a grant, a Viewer, and no
session), a cross-account case (an account of another environment answers as an absent one, and a
caller the store finds no live owner is refused and recorded) and, on the resolve, the step-up
cases (missing, expired, of another class, bound to another request). A replayed key answers the
first answer; the record lands before the effect, and an unwritten one changes nothing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from httpx import Response

from candleviewer.accounts.errors import AccountNotFoundError, AccountScopeDeniedError
from candleviewer.accounts.models import AccountKind, ExchangeAccount, ExchangeEnv
from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.api.admin_reconciliation import (
    MAX_BODY_BYTES,
    MAX_IN_FLIGHT,
    make_admin_reconciliation_router,
)
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.step_up import SINGLE_USE_WINDOW
from candleviewer.domain.primitives import AccountId
from candleviewer.oms.errors import OmsNotReady, ReconciliationUnavailable
from candleviewer.oms.reconcile_job import JobLocked, NoSuchJob, NothingToResolve, PassTaken
from candleviewer.storage.repositories.accounts import OwnerScope
from tests.contract._admin_support import SPEC, validate_example
from tests.unit.api.test_step_up_challenge_router import _World, _world

ACCOUNT, OTHER_ENV, ABSENT, SECOND = UUID(int=0xA1), UUID(int=0xB2), UUID(int=0xC3), UUID(int=0xD4)
KEY, KEY2 = str(UUID(int=0x914A)), str(UUID(int=0x914B))
BODY = {"reason": "Exchange reachable again; positions checked by hand."}
RUN = "/admin/reconciliation/{}"
RESOLVE = "/admin/reconciliation/{}/resolve"
_OPERATIONS = {
    "reconcileAccount": SPEC["paths"]["/admin/reconciliation/{accountId}"]["post"],
    "resolveReconciliation": SPEC["paths"]["/admin/reconciliation/{accountId}/resolve"]["post"],
}
_ROLES = {
    "owner": {"admin:read", "admin:write", "accounts:write"},
    "manager_with_grant": {"accounts:read", "orders:write", "positions:write"},
    "manager_without_grant": {"accounts:read"},
    "viewer": {"audit:read"},
}
T0 = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _account(account_id: UUID, env: ExchangeEnv = ExchangeEnv.DEMO) -> ExchangeAccount:
    return ExchangeAccount(
        id=account_id, env=env, kind=AccountKind.MAIN, exchange_uid="1001234", label="Main",
        created_at=T0, updated_at=T0,
    )  # fmt: skip


class Accounts:
    """`AccountsRepository.get_account` over a dict: absent is `AccountNotFoundError`, `denied`
    the live-owner gate's refusal, `fault` an outage; each read noted with its scope."""

    def __init__(self, *rows: ExchangeAccount) -> None:
        self.rows = {row.id: row for row in rows}
        self.asked: list[tuple[UUID, UUID]] = []
        self.denied, self.fault = False, cast(Exception | None, None)

    async def get_account(self, scope: OwnerScope, account_id: UUID) -> ExchangeAccount:
        self.asked.append((scope.user_id, account_id))
        if self.fault is not None:
            raise self.fault
        if self.denied:
            raise AccountScopeDeniedError("account")
        if account_id not in self.rows:
            raise AccountNotFoundError("account")
        return self.rows[account_id]


@dataclass
class Service:
    """`OnLaneReconciliation` as the routes read it, over B19's state per account: the route's
    record is written ahead (a raise tells B19 nothing), then B19 is told (`told`), as the driver
    does. `witness` reads, as each event is told, how many `oms.reconcile` records exist."""

    witness: Any = None
    states: dict[UUID, str] = field(default_factory=dict)
    running: dict[UUID, str] = field(default_factory=dict)
    told: list[tuple[str, UUID, dict[str, Any], int]] = field(default_factory=list)
    raises: Exception | None = None
    wired: bool = True
    hold: asyncio.Event | None = None

    def _tell(self, event: str, account: UUID, payload: dict[str, Any]) -> None:
        self.told.append((event, account, payload, self.witness() if self.witness else 0))

    async def reconcile_now(self, account: AccountId, *, write_ahead: Any) -> PassTaken:
        if self.raises is not None:
            raise self.raises
        if self.hold is not None:
            await self.hold.wait()
        state = self.states.setdefault(account, "idle")  # a manual request opens a job
        if state == "stale_lockout":
            raise JobLocked(str(account))
        if state == "fetching":
            taken = PassTaken(self.running[account], joined=True)
            await write_ahead(taken)
            return taken
        taken = PassTaken(str(uuid4()), joined=False)
        await write_ahead(taken)
        self._tell("SWEEP_DUE", account, {"trigger": "manual", "pass_id": taken.pass_id})
        self.states[account], self.running[account] = "fetching", taken.pass_id
        return taken

    async def resolve(self, account: AccountId, *, decided_by: str, write_ahead: Any) -> str:
        if self.raises is not None:
            raise self.raises
        state = self.states.get(account)
        if state is None:
            raise NoSuchJob(str(account))
        if state not in ("stale_lockout", "divergent"):
            raise NothingToResolve(str(account))
        await write_ahead(state)
        self._tell("OPERATOR_RESOLVED", account, {"decided_by": decided_by})
        self.states[account] = "idle"
        return state


@dataclass
class Runtime:
    """`OmsRuntime` as the routes read it: its readiness and its reconciliation."""

    service: Service
    readiness: str = "ok"
    composed: bool = True

    @property
    def reconciliation(self) -> Service:
        if not self.composed:
            raise OmsNotReady
        return self.service


class Principals:
    """The guard's resolver: the bearer's session, with the permissions of `x-role`."""

    def __init__(self, w: _World) -> None:
        self._sessions = w.sessions

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        record = self._sessions.get(request.headers.get("authorization", "")[len("Bearer ") :])
        if record is None:
            return None
        role = request.headers.get("x-role", "owner")
        grant = frozenset(_ROLES[role])
        return AuditPrincipal(
            record.user_id, role, grant, record.id, "10.0.0.9", UUID(int=9), role == "owner"
        )


@dataclass
class Rig:
    w: _World
    accounts: Accounts
    service: Service
    runtime: Runtime
    oms: list[Runtime | None]

    def post(
        self, path: str, *, role: str = "owner", key: str | None = KEY, json: Any = None,
        who: str | None = "tok",
    ) -> Response:  # fmt: skip
        headers = {"x-role": role}
        if who is not None:
            headers["Authorization"] = f"Bearer {who}"
        if key is not None:
            headers["Idempotency-Key"] = key
        sent: Response = self.w.client.post(path, headers=headers, json=json)
        return sent

    def records(self, action: str = "oms.reconcile") -> list[dict[str, Any]]:
        return self.w.of(action)

    def stepped(
        self, account: UUID = ACCOUNT, body: Any = None, key: str = KEY
    ) -> tuple[dict[str, Any], Response]:
        """The challenge a first resolve gets, a step-up answering it, and the resolve again."""
        sent = BODY if body is None else body
        challenge: dict[str, Any] = self.post(RESOLVE.format(account), json=sent, key=key).json()
        assert challenge["code"] == "step_up_required", challenge
        self.w.clock.now += timedelta(seconds=30)  # a fresh TOTP step: a code is good once
        assert self.w.step_up(challenge_id=challenge["challenge_id"]).status_code == 200
        return challenge, self.post(RESOLVE.format(account), json=sent, key=key)


async def _rig(*, environment: str = "demo") -> Rig:
    w = await _world()
    app = cast(FastAPI, w.client.app)
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    accounts = Accounts(_account(ACCOUNT), _account(SECOND), _account(OTHER_ENV, ExchangeEnv.LIVE))
    service = Service(witness=lambda: len(w.of("oms.reconcile")))
    runtime = Runtime(service)
    oms: list[Runtime | None] = [runtime]
    app.include_router(
        make_admin_reconciliation_router(
            accounts, lambda: oms[0], environment=environment, auth=w.auth,
            resolver=Principals(w), audit=w.audit, clock=lambda: w.clock.now,
        )
    )  # fmt: skip
    return Rig(w, accounts, service, runtime, oms)


def _problem(
    response: Response, status: int, code: str, *, operation: str, rule: str | None = None
) -> dict[str, Any]:
    """A registered problem the operation declares (22), never kept by a cache."""
    body: dict[str, Any] = response.json()
    assert (response.status_code, body["code"]) == (status, code), body
    assert response.headers["content-type"] == "application/problem+json"
    assert str(status) in _OPERATIONS[operation]["responses"]
    validate_example("/components/schemas/Problem", body)
    assert [e["rule"] for e in body.get("errors", [])] == ([] if rule is None else [rule])
    retry = body.get("retry_after_seconds")
    assert response.headers.get("retry-after") == (None if retry is None else str(retry))
    return body


# --- reconcileAccount ----------------------------------------------------------------------------


async def test_the_pass_is_recorded_ahead_then_started_and_answered_202() -> None:
    r = await _rig()
    sent = r.post(RUN.format(ACCOUNT))
    body = sent.json()
    assert sent.status_code == 202 and sent.headers["cache-control"] == "no-store"
    validate_example("/components/schemas/ReconciliationPass", body)
    assert (body["exchange_account_id"], body["trigger"], body["joined"]) == (
        str(ACCOUNT), "manual", False,
    )  # fmt: skip
    (record,) = r.records()
    owner = r.w.sessions["tok"]
    assert record == {
        "action": "oms.reconcile", "actor_label": "owner", "actor_user_id": owner.user_id,
        "actor_ip": "10.0.0.9", "session_id": owner.id, "object_kind": "exchange_account",
        "object_id": str(ACCOUNT), "outcome": AuditOutcome.SUCCESS, "severity": Severity.INFO,
        "reason": "requested", "request_id": UUID(int=9), "env": ExchangeEnv.DEMO,
        "after_state": {"stage": "requested", "trigger": "manual", "pass_id": body["pass_id"],
                        "joined": False},
    }  # fmt: skip
    # the record was durable when B19 was told: one record, then the one SWEEP_DUE
    assert r.service.told == [
        ("SWEEP_DUE", ACCOUNT, {"trigger": "manual", "pass_id": body["pass_id"]}, 1)
    ]
    assert r.accounts.asked == [(owner.user_id, ACCOUNT)]  # in the Owner's own scope


async def test_a_running_pass_answers_its_own_pass_id_joined_and_starts_none() -> None:
    r = await _rig()
    first = r.post(RUN.format(ACCOUNT)).json()
    joined = r.post(RUN.format(ACCOUNT), key=KEY2)
    assert joined.status_code == 202
    assert joined.json() == {**first, "joined": True}
    assert [event for event, *_ in r.service.told] == ["SWEEP_DUE"]  # never a second pass
    assert [rec["after_state"]["joined"] for rec in r.records()] == [False, True]


async def test_a_replayed_key_answers_the_first_202_and_starts_nothing_again() -> None:
    r = await _rig()
    first = r.post(RUN.format(ACCOUNT))
    r.service.states[ACCOUNT] = "idle"  # the pass ended: a new request would start another
    again = r.post(RUN.format(ACCOUNT))
    assert (again.status_code, again.content) == (202, first.content)
    assert again.headers["idempotency-replayed"] == "true"
    assert again.headers["cache-control"] == "no-store"
    assert len(r.service.told) == len(r.records()) == 1


async def test_the_key_first_used_for_another_account_is_409_reuse() -> None:
    r = await _rig()
    assert r.post(RUN.format(ACCOUNT)).status_code == 202
    reused = r.post(RUN.format(SECOND))
    _problem(reused, 409, "idempotency_key_reuse", operation="reconcileAccount")
    assert [account for _, account, *_ in r.service.told] == [ACCOUNT]
    assert r.accounts.asked[-1][1] == ACCOUNT  # the second account was never read


async def test_a_key_whose_first_call_still_runs_is_409_in_flight() -> None:
    r = await _rig()
    r.service.hold = asyncio.Event()
    app = cast(FastAPI, r.w.client.app)
    headers = {"Authorization": "Bearer tok", "x-role": "owner", "Idempotency-Key": KEY}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = asyncio.ensure_future(client.post(RUN.format(ACCOUNT), headers=headers))
        for _ in range(50):
            await asyncio.sleep(0)
        busy = await client.post(RUN.format(ACCOUNT), headers=headers)
        _problem(busy, 409, "idempotency_in_flight", operation="reconcileAccount")
        assert busy.headers["retry-after"] == "1"
        r.service.hold.set()
        assert (await first).status_code == 202
        # past the guard's bound, a new key is told to come back too (C-2.18)
        r.service.hold.clear()
        pending = [
            asyncio.ensure_future(
                client.post(RUN.format(ACCOUNT), headers={**headers, "Idempotency-Key": str(k)})
            )
            for k in (uuid4() for _ in range(MAX_IN_FLIGHT))
        ]
        for _ in range(200):
            await asyncio.sleep(0)
        full = await client.post(RUN.format(ACCOUNT), headers={**headers, "Idempotency-Key": KEY2})
        _problem(full, 409, "idempotency_in_flight", operation="reconcileAccount")
        r.service.hold.set()
        assert {(await p).status_code for p in pending} == {202}


@pytest.mark.parametrize("key", [None, "not-a-uuid"], ids=["missing", "malformed"])
async def test_an_idempotency_key_that_is_no_uuid_is_422_and_nothing_is_read(
    key: str | None,
) -> None:
    r = await _rig()
    refused = r.post(RUN.format(ACCOUNT), key=key)
    body = _problem(refused, 422, "validation_failed", operation="reconcileAccount", rule="uuid")
    assert body["errors"] == [{"field": "Idempotency-Key", "rule": "uuid"}]
    assert r.accounts.asked == [] and r.records() == [] and r.service.told == []


async def test_a_locked_job_is_409_reconciliation_locked_and_records_nothing() -> None:
    r = await _rig()
    r.service.states[ACCOUNT] = "stale_lockout"
    locked = r.post(RUN.format(ACCOUNT))
    _problem(locked, 409, "conflict", operation="reconcileAccount", rule="reconciliation_locked")
    assert r.records() == [] and r.service.told == []
    r.service.states[ACCOUNT] = "idle"  # a refusal is never kept: the same key runs afresh
    assert r.post(RUN.format(ACCOUNT)).status_code == 202


async def test_an_unwritten_record_is_503_and_starts_no_pass() -> None:
    r = await _rig()
    r.w.audit.fail_on = frozenset({"oms.reconcile"})
    refused = r.post(RUN.format(ACCOUNT))
    _problem(refused, 503, "audit_unavailable", operation="reconcileAccount")
    assert r.service.told == [] and r.service.states[ACCOUNT] == "idle"
    r.w.audit.fail_on = frozenset()
    assert r.post(RUN.format(ACCOUNT)).status_code == 202  # evaluated afresh, not replayed
    assert len(r.service.told) == 1


@pytest.mark.parametrize(
    "role", ["manager_with_grant", "manager_without_grant", "viewer"], ids=lambda r: r
)
@pytest.mark.parametrize("template", [RUN, RESOLVE], ids=["pass", "resolve"])
async def test_a_role_without_admin_write_is_403_recorded_and_never_reads_or_challenges(
    role: str, template: str
) -> None:
    """A Manager granted the very account (the IDOR attempt) is refused like any other."""
    r = await _rig()
    refused = r.post(template.format(ACCOUNT), role=role, json=BODY)
    operation = "reconcileAccount" if template == RUN else "resolveReconciliation"
    _problem(refused, 403, "forbidden", operation=operation)
    (entered,) = r.records("admin.area_entered")
    assert (entered["outcome"], entered["reason"]) == (
        AuditOutcome.DENIED, "missing_permission:admin:write",
    )  # fmt: skip
    assert r.accounts.asked == [] and r.service.told == [] and r.records() == []
    assert r.records("auth.step_up_required") == []


@pytest.mark.parametrize("template", [RUN, RESOLVE], ids=["pass", "resolve"])
async def test_no_session_is_401_and_nothing_is_read(template: str) -> None:
    r = await _rig()
    refused = r.post(template.format(ACCOUNT), who=None, json=BODY)
    assert refused.status_code == 401 and refused.json()["code"] == "unauthenticated"
    assert r.accounts.asked == [] and r.service.told == [] and r.w.audit.calls == []


async def test_an_account_of_another_environment_answers_as_an_absent_one() -> None:
    """C-2.11: the process serves its own environment's accounts only; the two `404`s are one
    answer, byte for byte, and neither reaches the OMS."""
    r = await _rig()
    other, absent = r.post(RUN.format(OTHER_ENV)), r.post(RUN.format(ABSENT), key=KEY2)
    body = _problem(other, 404, "not_found", operation="reconcileAccount")
    assert absent.content == other.content and body["detail"] == "No such account."
    assert r.service.told == [] and r.records() == []


async def test_a_caller_the_store_finds_no_live_owner_is_403_and_recorded() -> None:
    r = await _rig()
    r.accounts.denied = True
    refused = r.post(RUN.format(ACCOUNT))
    _problem(refused, 403, "forbidden", operation="reconcileAccount")
    (denied,) = r.records("rbac.denied")
    assert (denied["object_id"], denied["reason"], denied["outcome"]) == (
        str(ACCOUNT), "owner_only", AuditOutcome.DENIED,
    )  # fmt: skip
    r.w.audit.fail_on = frozenset({"rbac.denied"})  # a refusal that cannot be recorded
    _problem(r.post(RUN.format(ACCOUNT)), 503, "audit_unavailable", operation="reconcileAccount")
    assert r.service.told == []


@pytest.mark.parametrize(
    ("fault", "code"),
    [(None, "store_unavailable"), (ConnectionError("down"), "store_unavailable")],
    ids=["no-store", "store-down"],
)
async def test_an_account_store_that_cannot_answer_is_503(
    fault: Exception | None, code: str
) -> None:
    w = await _world()
    app = cast(FastAPI, w.client.app)
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    accounts = Accounts(_account(ACCOUNT))
    accounts.fault = fault
    service = Service()
    app.include_router(
        make_admin_reconciliation_router(
            None if fault is None else accounts, lambda: Runtime(service), environment="demo",
            auth=w.auth, resolver=Principals(w), audit=w.audit,
        )
    )  # fmt: skip
    headers = {"Authorization": "Bearer tok", "x-role": "owner", "Idempotency-Key": KEY}
    refused = w.client.post(RUN.format(ACCOUNT), headers=headers)
    _problem(refused, 503, code, operation="reconcileAccount")
    assert service.told == []


async def test_no_oms_or_no_reconciliation_is_501_and_one_not_ready_is_503() -> None:
    r = await _rig()
    r.oms[0] = None
    _problem(r.post(RUN.format(ACCOUNT)), 501, "not_implemented", operation="reconcileAccount")
    r.oms[0] = r.runtime
    r.service.wired = False
    _problem(r.post(RUN.format(ACCOUNT)), 501, "not_implemented", operation="reconcileAccount")
    r.service.wired = True
    for readiness, composed in (("starting", True), ("degraded", True), ("ok", False)):
        r.runtime.readiness, r.runtime.composed = readiness, composed
        _problem(r.post(RUN.format(ACCOUNT)), 503, "oms_not_ready", operation="reconcileAccount")
    r.runtime.readiness, r.runtime.composed = "ok", True
    for raised in (OmsNotReady(), ReconciliationUnavailable("unwired")):  # the lane or the job
        r.service.raises = raised
        _problem(r.post(RUN.format(ACCOUNT)), 503, "oms_not_ready", operation="reconcileAccount")
    assert r.service.told == [] and r.records() == []


# --- resolveReconciliation -----------------------------------------------------------------------


@pytest.mark.parametrize("state", ["stale_lockout", "divergent"])
async def test_the_resolve_spends_one_fresh_accounts_code_records_ahead_and_unlocks(
    state: str,
) -> None:
    r = await _rig()
    r.service.states[ACCOUNT] = state
    challenge, resolved = r.stepped()
    assert challenge["action_class"] == "accounts"
    assert challenge["action_summary"] == f"Resolve the reconciliation of account {ACCOUNT}"
    body = resolved.json()
    assert resolved.status_code == 200 and resolved.headers["cache-control"] == "no-store"
    validate_example("/components/schemas/ReconciliationResolved", body)
    assert body == {
        "exchange_account_id": str(ACCOUNT), "resolved": state,
        "resolved_at": r.w.clock.now.isoformat().replace("+00:00", "Z"),
    }  # fmt: skip
    (record,) = r.records()
    owner = r.w.sessions["tok"]
    assert (record["reason"], record["severity"], record["actor_user_id"]) == (
        "resolved", Severity.WARNING, owner.user_id,
    )  # fmt: skip
    assert record["after_state"] == {
        "stage": "resolved", "state": state, "reason": BODY["reason"],
        "challenge_id": challenge["challenge_id"],
    }  # fmt: skip
    # recorded before B19 was told, which it was once, by the Owner's id
    assert r.service.told == [("OPERATOR_RESOLVED", ACCOUNT, {"decided_by": str(owner.user_id)}, 1)]
    again = r.post(RESOLVE.format(ACCOUNT), json=BODY, key=KEY2)  # the grant went with it
    assert again.json()["code"] == "step_up_required"
    assert again.json()["challenge_id"] != challenge["challenge_id"]


async def test_without_a_code_the_resolve_is_a_challenge_that_changes_nothing() -> None:
    r = await _rig()
    r.service.states[ACCOUNT] = "stale_lockout"
    refused = r.post(RESOLVE.format(ACCOUNT), json=BODY)
    body = _problem(refused, 403, "step_up_required", operation="resolveReconciliation")
    assert body["action_class"] == "accounts" and refused.headers["cache-control"] == "no-store"
    (required,) = r.records("auth.step_up_required")
    assert required["object_id"] == body["challenge_id"]
    assert r.service.told == [] and r.records() == [] and r.accounts.asked == []
    assert r.service.states[ACCOUNT] == "stale_lockout"


async def test_a_grant_that_lapsed_is_challenged_again() -> None:
    """Expired: a one-shot grant lives `SINGLE_USE_WINDOW`; once it lapses the request is a
    first one again."""
    r = await _rig()
    r.service.states[ACCOUNT] = "stale_lockout"
    challenge = r.post(RESOLVE.format(ACCOUNT), json=BODY).json()
    r.w.clock.now += timedelta(seconds=30)
    assert r.w.step_up(challenge_id=challenge["challenge_id"]).status_code == 200
    r.w.clock.now += SINGLE_USE_WINDOW + timedelta(seconds=1)
    lapsed = r.post(RESOLVE.format(ACCOUNT), json=BODY)
    body = _problem(lapsed, 403, "step_up_required", operation="resolveReconciliation")
    assert body["challenge_id"] != challenge["challenge_id"]
    assert r.service.told == [] and r.service.states[ACCOUNT] == "stale_lockout"


async def test_a_step_up_of_another_class_never_admits_the_resolve() -> None:
    r = await _rig()
    r.service.states[ACCOUNT] = "stale_lockout"
    assert r.w.step_up(action_class="keys").status_code == 200  # a live `keys` window
    refused = r.post(RESOLVE.format(ACCOUNT), json=BODY)
    body = _problem(refused, 403, "step_up_required", operation="resolveReconciliation")
    assert body["action_class"] == "accounts" and r.service.told == []


@pytest.mark.parametrize(
    ("account", "body"),
    [(SECOND, BODY), (ACCOUNT, {"reason": "Another reason, not the one confirmed."})],
    ids=["another-account", "another-body"],
)
async def test_a_grant_bound_to_another_request_is_a_mismatch_and_stays_bound(
    account: UUID, body: dict[str, str]
) -> None:
    """The grant binds the method, the raw target and the validated body."""
    r = await _rig()
    r.service.states[ACCOUNT] = r.service.states[SECOND] = "stale_lockout"
    challenge = r.post(RESOLVE.format(ACCOUNT), json=BODY).json()
    r.w.clock.now += timedelta(seconds=30)
    assert r.w.step_up(challenge_id=challenge["challenge_id"]).status_code == 200
    refused = r.post(RESOLVE.format(account), json=body)
    _problem(refused, 403, "step_up_required", operation="resolveReconciliation")
    (mismatch,) = r.records("auth.step_up_mismatch")
    assert mismatch["object_id"] == challenge["challenge_id"] and r.service.told == []
    assert r.post(RESOLVE.format(ACCOUNT), json=BODY).status_code == 200  # still bound


async def test_a_replayed_key_and_body_answer_the_first_200_behind_a_fresh_code() -> None:
    r = await _rig()
    r.service.states[ACCOUNT] = "stale_lockout"
    _, first = r.stepped()
    r.service.states[ACCOUNT] = "stale_lockout"  # locked again: a new decision would be told
    _, again = r.stepped()
    assert (again.status_code, again.content) == (200, first.content)
    assert again.headers["idempotency-replayed"] == "true"
    assert len(r.service.told) == len(r.records()) == 1  # resolved once, recorded once


async def test_the_key_with_another_body_is_409_reuse_after_the_step_up() -> None:
    r = await _rig()
    r.service.states[ACCOUNT] = "stale_lockout"
    r.stepped()
    other = {"reason": "A second decision under the same key."}
    _, reused = r.stepped(body=other)
    _problem(reused, 409, "idempotency_key_reuse", operation="resolveReconciliation")
    assert len(r.service.told) == 1


@pytest.mark.parametrize("state", ["idle", "fetching", None], ids=["idle", "running", "no-job"])
async def test_a_job_neither_locked_nor_waiting_is_409_nothing_to_resolve(
    state: str | None,
) -> None:
    r = await _rig()
    if state is not None:
        r.service.states[ACCOUNT] = state
    _, refused = r.stepped()
    rule = "nothing_to_resolve"
    _problem(refused, 409, "conflict", operation="resolveReconciliation", rule=rule)
    assert r.service.told == [] and r.records() == []


async def test_an_unwritten_decision_is_503_and_the_account_stays_locked() -> None:
    r = await _rig()
    r.service.states[ACCOUNT] = "stale_lockout"
    r.w.audit.fail_on = frozenset({"oms.reconcile"})
    _, refused = r.stepped()
    _problem(refused, 503, "audit_unavailable", operation="resolveReconciliation")
    assert r.service.told == [] and r.service.states[ACCOUNT] == "stale_lockout"


@pytest.mark.parametrize(
    ("body", "field", "rule"),
    [
        ({}, "reason", "missing"),
        ({"reason": "no"}, "reason", "string_too_short"),
        ({"reason": "x" * 281}, "reason", "string_too_long"),
        ({"reason": "Checked by hand.", "state": "idle"}, "", "extra_forbidden"),
        ({"reason": "y" * (MAX_BODY_BYTES + 1)}, "", "body_too_large"),
    ],
    ids=["missing", "short", "long", "extra", "too-large"],
)
async def test_a_body_off_the_contract_is_422_before_any_challenge(
    body: dict[str, Any], field: str, rule: str
) -> None:
    r = await _rig()
    refused = r.post(RESOLVE.format(ACCOUNT), json=body)
    problem = _problem(refused, 422, "validation_failed", operation="resolveReconciliation",
                       rule=rule)  # fmt: skip
    assert problem["errors"] == [{"field": field, "rule": rule}]
    assert "x" * 10 not in refused.text and "y" * 10 not in refused.text  # never echoed
    assert r.records("auth.step_up_required") == [] and r.accounts.asked == []


async def test_the_resolve_reads_the_account_after_the_step_up_as_22_orders_it() -> None:
    """22: the step-up is part of admission, so an absent account, or one of another environment,
    is a `404` behind a fresh code, the grant spent; the two answers are one."""
    r = await _rig()
    _, other = r.stepped(account=OTHER_ENV)
    _, absent = r.stepped(account=ABSENT, key=KEY2)
    _problem(other, 404, "not_found", operation="resolveReconciliation")
    assert absent.content == other.content and r.service.told == [] and r.records() == []


async def test_a_resolve_with_no_oms_is_501_and_one_whose_lane_is_gone_503() -> None:
    r = await _rig()
    r.oms[0] = None
    _, refused = r.stepped()
    _problem(refused, 501, "not_implemented", operation="resolveReconciliation")
    r.oms[0] = r.runtime
    r.service.raises = OmsNotReady()
    _, gone = r.stepped(key=KEY2)
    _problem(gone, 503, "oms_not_ready", operation="resolveReconciliation")
