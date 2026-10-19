"""`POST /admin/keys/kek-rewrap` (`rewrapKek`, #2266 PR D2) through the real `create_app()`: CSRF,
the step-up middleware (class `keys`), `AuthService`, RBAC and the route, as
`test_invites_create_app_e2e.py` builds them on the fake backend, with M2 booted for a v1 to v2
rotation of two keys on its in-memory store, injected as the secrets bundle."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer import app as app_module
from candleviewer.admin.wiring import SecretsBundle
from candleviewer.api.admin_kek import MAX_BODY_BYTES, make_admin_kek_router
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.service import AuthService
from candleviewer.secrets import (
    SecretsLifecycleFacade,
    SecretsMetadataFacade,
    SecretsService,
    mint_borrower,
    mint_candidate_keys,
)
from candleviewer.secrets.store import InMemoryAuthKeyStore, InMemoryCredentialStore
from tests.unit.api.test_invites_create_app_e2e import _h, _login, _World
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.credentials_m2._service_fakes import _boot, _Src, _store_one, _svc
from tests.unit.credentials_m2._vectors import KEK_V1, KEK_V2, AuditLog
from tests.unit.credentials_m2.test_rotation_preconditions import _hold

PATH = "/admin/keys/kek-rewrap"
BODY = {"environment": "demo", "to_version": 2}
OWNER = frozenset({Permission.KEYS_MANAGE})
_REFUSED, _STARTED = "security.kek_rotation_refused", "security.kek_rotation_started"
_IN_PROGRESS = "kek_rotation_in_progress"


def deploy(monkeypatch: pytest.MonkeyPatch, svc: SecretsService) -> tuple[_World, Any]:
    """The invites world's app, with `svc` as its M2 (not started: the caller starts it)."""
    w = _World()
    w.auth = AuthService(
        w.users,
        mfa_repository=FakeMfaRepository(),
        totp_encryption_key=os.urandom(32),
        recovery_code_hmac_key=os.urandom(32),
        session_repository=FakeSessionRepository(),
        pepper="test-pepper",
        clock=w.clock,
    )
    monkeypatch.setattr(app_module, "build_auth_service", lambda *_a, **_k: w.auth)
    bundle = SecretsBundle(
        SecretsLifecycleFacade(svc),
        SecretsMetadataFacade(svc),
        mint_borrower(svc, "exchange_adapter"),
        mint_candidate_keys(svc),
    )
    app = app_module.create_app(principal_resolver=w.resolver, secrets_bundle=bundle)
    ctx = app.state.app_context
    ctx.audit._writer = w.audit  # the lazy emitter resolves `audit.writer` per call
    w.codec = app.state.csrf_codec
    w.client = TestClient(app, client=("127.0.0.1", 50000))
    return w, ctx


async def elevated(w: _World, role: str, perms: frozenset[Permission]) -> str:
    """A session of `role` stepped up for class `keys`: a refused call's challenge, answered."""
    token = await _login(w, role, perms)
    assert w.client.post(PATH, headers=_h(token), json=BODY).json()["code"] == "step_up_required"
    assert w.elevate(token).json()["action_class"] == "keys"
    return token


@dataclass
class _Kek:
    w: _World
    ctx: Any
    svc: SecretsService
    store: InMemoryCredentialStore
    audit: AuditLog  # M2's own records

    def post(self, token: str, body: dict[str, Any] = BODY) -> Any:
        return self.w.client.post(PATH, headers=_h(token), json=body)

    def runs(self) -> list[str]:
        """M2's rotation records: a refusal's, or a run's."""
        return [action for action in self.audit.actions() if "rotation" in action]


@pytest.fixture
async def kek(monkeypatch: pytest.MonkeyPatch) -> _Kek:
    store, audit = InMemoryCredentialStore(), AuditLog()
    v1 = await _boot(store, _Src(KEK_V1, 1))
    for _ in range(2):
        await _store_one(v1)
    staged = (_Src(KEK_V2, 2), _Src(KEK_V1, 1))
    svc = _svc(*staged, store=store, audit=audit, auth_keys=InMemoryAuthKeyStore())
    w, ctx = deploy(monkeypatch, svc)
    await w.auth.start(ctx)
    await svc.start(ctx)
    return _Kek(w, ctx, svc, store, audit)


async def test_an_owner_with_step_up_and_csrf_gets_the_run_counts(kek: _Kek) -> None:
    r = kek.post(await elevated(kek.w, "owner", OWNER))
    assert r.status_code == 200, r.text
    run = {k: v for k, v in r.json().items() if k != "run_id"}
    versions = {"environment": "demo", "from_version": 1, "to_version": 2, "resumed": False}
    assert run == versions | {"rewrapped": 2, "remaining": 0, "failed": 0, "complete": True}


async def test_every_record_of_the_run_carries_its_run_id_and_the_owner(kek: _Kek) -> None:
    booted, owner = len(kek.audit.records), await elevated(kek.w, "owner", OWNER)
    run_id, by = kek.post(owner).json()["run_id"], str(kek.w.resolver.by_token[owner].user_id)
    records = [f for _, f in kek.audit.records[booted:] + kek.store.rewrap_audit]
    assert [(f["run_id"], f["actor_user_id"]) for f in records] == [(run_id, by)] * 4


async def test_the_run_latches_order_entry_with_the_rotation_reason(kek: _Kek) -> None:
    kek.post(await elevated(kek.w, "owner", OWNER))
    assert kek.ctx.oms_read_only_gate.reason_code == "secrets.kek_rotation"


async def test_the_answer_names_no_key_id_and_no_kcv(kek: _Kek) -> None:
    text = kek.post(await elevated(kek.w, "owner", OWNER)).text
    hidden = [str(k) for k in kek.store.rows] + [kcv.hex() for kcv in kek.store.kcvs.values()]
    assert len(hidden) == 4 and not [h for h in hidden if h in text]


class _Nobody:
    def resolve(self, request: Any) -> None:
        return None


@pytest.mark.parametrize(
    ("resolver", "status", "code"),
    [(None, 501, "not_implemented"), (_Nobody(), 401, "unauthenticated")],
    ids=["no_resolver_wired", "no_verified_session"],
)
def test_a_caller_the_route_cannot_resolve_is_refused_before_anything_runs(
    resolver: Any, status: int, code: str
) -> None:
    """The route's own checks, behind the middleware: neither the M2 run nor RBAC is reached."""
    app = FastAPI()
    app.include_router(make_admin_kek_router(cast(Any, None), cast(Any, None), resolver))
    r = TestClient(app).post(PATH, json=BODY)
    assert (r.status_code, r.json()["code"]) == (status, code)


async def test_an_owner_without_step_up_is_challenged_for_class_keys(kek: _Kek) -> None:
    r = kek.post(await _login(kek.w, "owner", OWNER))
    assert (r.status_code, r.json()["code"], r.json()["action_class"]) == (
        403,
        "step_up_required",
        "keys",
    )
    assert (kek.runs(), kek.ctx.oms_read_only_gate.is_read_only) == ([], False)


@pytest.mark.parametrize("role", ["manager", "viewer"])
async def test_a_manager_or_viewer_is_challenged_then_forbidden_and_nothing_runs(
    kek: _Kek, role: str
) -> None:
    """The step-up gate precedes RBAC (`test_invites_create_app_e2e.py`): no `rbac.denied` until
    the session is elevated, then exactly one, naming the caller's address and request id."""
    token = await _login(kek.w, role, frozenset())
    first = kek.post(token)
    assert (first.json()["code"], kek.w.audit.of("rbac.denied")) == ("step_up_required", [])
    assert kek.w.elevate(token).status_code == 200
    second = kek.post(token)
    assert (second.status_code, second.json()["code"]) == (403, "forbidden")
    [denial] = kek.w.audit.of("rbac.denied")
    rid = uuid.UUID(second.headers["x-correlation-id"])
    assert (denial["actor_ip"], denial["request_id"]) == ("127.0.0.1", rid)
    assert (kek.runs(), kek.ctx.oms_read_only_gate.is_read_only) == ([], False)


@pytest.mark.parametrize("perms", [frozenset(), OWNER], ids=["no_keys_manage", "not_the_owner"])
async def test_a_denial_that_cannot_be_recorded_answers_audit_unavailable(
    kek: _Kek, perms: frozenset[Permission]
) -> None:
    """C-2.9: `rbac.denied` is written ahead of the 403; if it cannot be, the answer is a 503."""
    token, emit = await elevated(kek.w, "viewer", perms), kek.w.audit.emit

    async def refuse_denials(action: str, **kw: Any) -> None:
        if action == "rbac.denied":
            raise AuditError(action)
        await emit(action, **kw)  # the step-up's own records still land

    kek.ctx.audit._writer = SimpleNamespace(emit=refuse_denials)
    r = kek.post(token)
    assert (r.status_code, r.json()["code"], kek.runs()) == (503, "audit_unavailable", [])


@pytest.mark.parametrize("perms", [frozenset(), OWNER], ids=["no_keys_manage", "not_the_owner"])
async def test_a_denial_after_a_stop_unwired_the_writer_answers_audit_unavailable(
    kek: _Kek, perms: frozenset[Permission]
) -> None:
    """`AuditService.writer` raises `RuntimeError` once unwired: unrecordable, so a `503`."""
    token, emit = await elevated(kek.w, "viewer", perms), kek.w.audit.emit

    async def then_unwired(action: str, **kw: Any) -> None:  # B16's `grace_used`, then a stop()
        await emit(action, **kw)
        kek.ctx.audit._writer = None  # as `AuditService.stop()` leaves it

    kek.ctx.audit._writer = SimpleNamespace(emit=then_unwired)
    r = kek.post(token)
    assert (r.status_code, r.json()["code"], kek.runs()) == (503, "audit_unavailable", [])


async def test_keys_manage_without_the_owner_role_is_forbidden(kek: _Kek) -> None:
    """Defence in depth: the RBAC seed gives `keys:manage` to the Owner alone."""
    r = kek.post(await elevated(kek.w, "manager", OWNER))
    assert (r.status_code, r.json()["code"], kek.runs()) == (403, "forbidden", [])


async def test_the_owner_role_refusal_is_one_denial_of_the_caller_at_warning(kek: _Kek) -> None:
    """As complete as `enforce`'s record: the caller's id, address and request id."""
    token = await elevated(kek.w, "manager", OWNER)
    r = kek.post(token)
    [denial] = kek.w.audit.of("rbac.denied")
    keys = ("reason", "actor_user_id", "actor_ip", "request_id", "outcome", "severity")
    caller = kek.w.resolver.by_token[token].user_id, "127.0.0.1"
    rid = uuid.UUID(r.headers["x-correlation-id"])
    want = ("owner_only", *caller, rid, AuditOutcome.DENIED, Severity.WARNING)
    assert tuple(denial.get(k) for k in keys) == want


async def test_a_call_without_its_csrf_token_is_refused(kek: _Kek) -> None:
    owner = await elevated(kek.w, "owner", OWNER)
    r = kek.w.client.post(PATH, headers={"Authorization": f"Bearer {owner}"}, json=BODY)
    assert (r.status_code, r.json()["code"], kek.runs()) == (403, "csrf_token_invalid", [])


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({**BODY, "from_version": 1}, ""),  # the caller's member name is never echoed
        ({"environment": "demo", "to_version": 1}, "to_version"),
        ({"environment": "mainnet", "to_version": 2}, "environment"),
        ({"environment": "demo"}, "to_version"),
        ({"environment": "demo", "to_version": "2"}, "to_version"),
    ],
    ids=["other_member", "version_1", "unknown_env", "no_version", "string_version"],
)
async def test_a_body_unlike_the_contract_is_unprocessable(
    kek: _Kek, body: dict[str, Any], field: str
) -> None:
    r = kek.post(await elevated(kek.w, "owner", OWNER), body)
    assert (r.status_code, r.json()["code"], kek.runs()) == (422, "validation_failed", [])
    assert r.json()["errors"][0]["field"] == field


async def test_a_body_past_its_cap_is_refused_unread(kek: _Kek) -> None:
    """A valid body padded past 1 KiB, so only the cap can refuse it."""
    headers = {**_h(await elevated(kek.w, "owner", OWNER)), "content-type": "application/json"}
    raw = json.dumps(BODY) + " " * MAX_BODY_BYTES
    r = kek.w.client.post(PATH, headers=headers, content=raw)
    assert (r.status_code, r.json()["errors"][0]["rule"], kek.runs()) == (422, "body_too_large", [])


async def _as_booted(kek: _Kek) -> None:
    return None


async def _stopped(kek: _Kek) -> None:
    await kek.svc.stop(0)  # no usable KEK


@pytest.mark.parametrize(
    ("brake", "body", "status", "code"),
    [
        (_as_booted, {"environment": "demo", "to_version": 3}, 409, "kek_rotation_not_staged"),
        (_as_booted, {"environment": "live", "to_version": 2}, 409, "kek_rotation_not_staged"),
        (_stopped, BODY, 403, "kek_unavailable"),
    ],
    ids=["other_version", "other_environment", "kek_unavailable"],
)
async def test_an_m2_refusal_answers_its_status_and_code_and_latches_nothing(
    kek: _Kek,
    brake: Callable[[_Kek], Awaitable[None]],
    body: dict[str, Any],
    status: int,
    code: str,
) -> None:
    owner = await elevated(kek.w, "owner", OWNER)
    await brake(kek)
    r = kek.post(owner, body)
    assert (r.status_code, r.json()["code"], "Retry-After" in r.headers) == (status, code, False)
    assert (kek.runs(), kek.ctx.oms_read_only_gate.is_read_only) == ([_REFUSED], False)


async def test_a_call_while_a_run_holds_the_lock_answers_in_progress_with_retry_after(
    kek: _Kek,
) -> None:
    """A real run, held at its first store call, then released: the call's refusal is recorded
    before that run opens, and the run still completes."""
    owner = await elevated(kek.w, "owner", OWNER)
    entered, release = _hold(kek.store, "count_at_kek_version")  # a run's first store call
    held = asyncio.create_task(kek.ctx.admin.rewrap_kek("demo", 2, "owner-1"))
    await entered.wait()
    r = kek.post(owner)
    release.set()
    assert (r.status_code, r.json()["code"], r.headers["Retry-After"]) == (409, _IN_PROGRESS, "5")
    assert ((await held).complete, kek.runs()) == (True, [_REFUSED, _STARTED])


def _audit_down(kek: _Kek) -> None:
    kek.audit.fail = True


def _store_down(kek: _Kek) -> None:
    async def down(version: int, env: str) -> int:
        raise RuntimeError("store down")

    kek.store.count_at_kek_version = down  # type: ignore[method-assign]  # a failing fake store


@pytest.mark.parametrize(
    ("brake", "code"),
    [(_audit_down, "audit_unavailable"), (_store_down, "store_unavailable")],
    ids=["audit", "store"],
)
async def test_a_run_that_fails_after_the_latch_answers_503_and_keeps_it(
    kek: _Kek, brake: Callable[[_Kek], None], code: str
) -> None:
    owner = await elevated(kek.w, "owner", OWNER)
    brake(kek)
    r = kek.post(owner)
    assert (r.status_code, r.json()["code"], r.headers["Retry-After"]) == (503, code, "5")
    assert kek.ctx.oms_read_only_gate.reason_code == "secrets.kek_rotation"
