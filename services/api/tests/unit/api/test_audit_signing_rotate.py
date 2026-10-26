"""`POST /admin/keys/audit-signing/rotate` (`rotateAuditSigningKey`, #889 S7; ADR-0039 decision 5)
through the real `create_app()`: CSRF, the step-up middleware (class `keys`), RBAC, the route and
`AdminService`, with M2 booted on its in-memory stores, its first signing key generated, and
injected as the secrets bundle (as `test_admin_kek.py` deploys it)."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.admin.errors import SigningKeyRotationError
from candleviewer.admin.service import AdminService
from candleviewer.api import audit_signing_keys as signing_api
from candleviewer.api.audit_budget import AuditRecordBudget
from candleviewer.api.audit_signing_keys import (
    MAX_BODY_BYTES,
    PATH,  # the fingerprint's path: the served one
    make_audit_signing_router,
)
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.secrets import SecretsService
from candleviewer.secrets.store import (
    InMemoryAuthKeyStore,
    InMemoryCredentialStore,
    InMemoryExportKeyStore,
)
from tests.unit.api.test_admin_kek import deploy
from tests.unit.api.test_invites_create_app_e2e import _h, _login, _World
from tests.unit.credentials_m2._service_fakes import _Src, _svc
from tests.unit.credentials_m2._vectors import KEK_V1, AuditLog

OWNER = frozenset({Permission.KEYS_MANAGE})
_ROTATED, _REFUSED = (
    "security.audit_signing_key_rotated",
    "security.audit_signing_key_rotation_refused",
)
_KEY = {"key_id", "alg", "public_key", "fingerprint_sha256", "status", "verified", "valid_from"}
_KEY |= {"valid_until", "retired_reason"}
_NO_KEY = object()  # `post()`'s request with no `Idempotency-Key` header


def _unstored(*answers: Any) -> bool:
    """Security Low: every answer of the router, a `200`, a replay or a problem, is no-store."""
    return all(a.headers.get("cache-control") == "no-store" for a in answers)


class _Rot:
    def __init__(self, w: _World, ctx: Any, svc: SecretsService, keys: Any, audit: AuditLog):
        self.w, self.ctx, self.svc, self.keys, self.audit = w, ctx, svc, keys, audit

    def post(self, token: str, ref: object = None, body: object = None) -> Any:
        """`ref` as the `Idempotency-Key` (a fresh one when None; `_NO_KEY` sends none)."""
        sent = {**_h(token), "Idempotency-Key": str(ref or uuid.uuid4())}
        if ref is _NO_KEY:
            del sent["Idempotency-Key"]
        return self.w.client.post(PATH, headers=sent, json=body or {"reason": "scheduled"})

    def refusals(self) -> list[str]:
        return [f["reason"] for a, f in self.audit.records if a == _REFUSED]


async def _deployed(monkeypatch: pytest.MonkeyPatch, keys: Any = None) -> _Rot:
    keys, audit = keys or InMemoryExportKeyStore(), AuditLog()
    svc = _svc(_Src(KEK_V1, 1), store=InMemoryCredentialStore(), audit=audit,
               auth_keys=InMemoryAuthKeyStore(), export_keys=keys)  # fmt: skip
    w, ctx = deploy(monkeypatch, svc)
    await w.auth.start(ctx)
    await svc.start(ctx)
    return _Rot(w, ctx, svc, keys, audit)


@pytest.fixture
async def rot(monkeypatch: pytest.MonkeyPatch) -> _Rot:
    return await _deployed(monkeypatch)


async def elevated(rot: _Rot, role: str = "owner", perms: frozenset[Permission] = OWNER) -> str:
    """A session of `role` stepped up for class `keys`, a grace class, by name: since #2304
    slice 3b a caller RBAC refuses is never challenged, so it has no challenge to answer."""
    token = await _login(rot.w, role, perms)
    assert rot.w.elevate(token, action_class="keys").json()["action_class"] == "keys"
    return token


async def test_an_owner_without_step_up_is_challenged_restating_the_rotation(rot: _Rot) -> None:
    """#2304 slice 3b: the handler's challenge, after the body and RBAC, restates the reason;
    nothing rotates, no `rbac.denied`, and the challenge is no-store as every answer here."""
    r = rot.post(await _login(rot.w, "owner", OWNER), body={"reason": "compromise"})
    assert (r.status_code, r.json()["code"], r.json()["action_class"]) == (
        403, "step_up_required", "keys"
    )  # fmt: skip
    summary = "Rotate the audit export signing key (compromise)"
    assert (r.json()["action_summary"], len(rot.keys.rows), _unstored(r)) == (summary, 1, True)
    assert rot.w.audit.of("rbac.denied") == [] and rot.w.audit.of("auth.step_up_required")


@pytest.mark.parametrize(
    ("role", "perms"), [("manager", frozenset()), ("viewer", frozenset()), ("manager", OWNER)]
)
async def test_anyone_but_the_owner_without_step_up_is_forbidden_never_challenged(
    rot: _Rot, role: str, perms: frozenset[Permission]
) -> None:
    r = rot.post(await _login(rot.w, role, perms))
    assert (r.status_code, r.json()["code"], "challenge_id" in r.json()) == (
        403, "forbidden", False
    )  # fmt: skip
    assert rot.w.audit.of("auth.step_up_required") == [] and len(rot.w.audit.of("rbac.denied")) == 1


@pytest.mark.parametrize(
    ("body", "key"),
    [({"reason": "weekly"}, None), ({"reason": "scheduled", "seed": "SENTINEL"}, None),
     ({"reason": "scheduled"}, _NO_KEY)],
    ids=["unknown-reason", "other-member", "no-idempotency-key"],
)  # fmt: skip
async def test_an_invalid_request_from_an_unelevated_owner_is_the_422_never_a_challenge(
    rot: _Rot, body: dict[str, Any], key: object
) -> None:
    r = rot.post(await _login(rot.w, "owner", OWNER), key, body)
    assert (r.status_code, r.json()["code"], len(rot.keys.rows)) == (422, "validation_failed", 1)
    assert rot.w.audit.of("auth.step_up_required") == [] and "SENTINEL" not in r.text


async def test_an_owner_with_step_up_and_csrf_rotates_and_gets_public_keys_only(rot: _Rot) -> None:
    token = await elevated(rot)
    r = rot.post(token)
    assert (r.status_code, "Idempotency-Replayed" in r.headers, _unstored(r)) == (200, False, True)
    v1, v2 = rot.keys.rows
    active, retired = r.json()["active"], r.json()["retired"]
    assert set(active) == set(retired) == _KEY
    assert (active["key_id"], active["status"], active["verified"]) == (
        v2["key_id"],
        "active",
        True,
    )
    assert (retired["key_id"], retired["retired_reason"], retired["verified"]) == (
        v1["key_id"], "scheduled", False
    )  # fmt: skip
    action, fields = rot.keys.audit[-1]  # committed with the keys, the Owner as the actor
    owner = str(rot.w.resolver.by_token[token].user_id)
    assert (action, fields["actor_user_id"], fields["retired_material_destroyed"]) == (
        _ROTATED, owner, "true"
    )  # fmt: skip
    hidden = [v2["dek_ref"], v2["sealed_seed"].hex(), v2["client_body_sha256"]]
    assert not [h for h in hidden if h in r.text]


async def test_a_repeat_after_a_restart_replays_its_200_and_another_body_is_reuse(
    rot: _Rot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision 5: the 200 is durable on the key rows, so a repeat reaches it once the process,
    and any in-memory record, is gone; the same key with another body is `409`."""
    token, ref = await elevated(rot), uuid.uuid4()
    first = rot.post(token, ref)
    later = await _deployed(monkeypatch, rot.keys)  # a new process over the same store
    again = await elevated(later)
    owner = rot.w.resolver.by_token[token]
    later.w.resolver.by_token[again] = PrincipalSnapshot(owner.user_id, owner.roles, OWNER)
    repeat = later.post(again, ref)
    assert (repeat.status_code, repeat.headers["Idempotency-Replayed"]) == (200, "true")
    assert repeat.json() == first.json() and len(rot.keys.rows) == 2
    reused = later.post(again, ref, {"reason": "compromise"})
    assert (reused.status_code, reused.json()["code"]) == (409, "idempotency_key_reuse")
    assert _unstored(repeat, reused)


async def test_another_owners_key_is_one_never_seen(rot: _Rot) -> None:
    """Cross-user (C-12.4, SR-E29-07): the first Owner's key from another Owner rotates afresh,
    and never reads the first Owner's answer back."""
    first, ref = await elevated(rot), uuid.uuid4()
    mine = rot.post(first, ref)
    theirs = rot.post(await elevated(rot), ref)
    assert (theirs.status_code, "Idempotency-Replayed" in theirs.headers) == (200, False)
    assert theirs.json()["active"]["key_id"] != mine.json()["active"]["key_id"]


@pytest.mark.parametrize(
    ("role", "perms"), [("manager", frozenset()), ("viewer", frozenset()), ("manager", OWNER)]
)
async def test_anyone_but_the_owner_is_forbidden_and_nothing_rotates(
    rot: _Rot, role: str, perms: frozenset[Permission]
) -> None:
    """Elevated or not, `keys:manage` without the Owner role is refused too. Each
    denial names the caller's session, as every `rbac.denied` does since #4174 (security Medium,
    code C4-1), and the 403 is no-store."""
    token = await elevated(rot, role, perms)
    r = rot.post(token)
    assert (r.status_code, r.json()["code"], len(rot.keys.rows)) == (403, "forbidden", 1)
    [denial] = rot.w.audit.of("rbac.denied")  # written ahead of the 403 (C-2.9)
    assert not perms or denial["reason"] == "owner_only"
    session = await rot.w.auth.sessions.peek_access_token(token)
    assert session is not None and denial["session_id"] == session.id and _unstored(r)


async def test_a_call_without_its_csrf_token_or_a_session_is_refused(rot: _Rot) -> None:
    token = await elevated(rot)
    bare = {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}
    r = rot.w.client.post(PATH, headers=bare, json={"reason": "scheduled"})
    assert (r.status_code, r.json()["code"], len(rot.keys.rows)) == (403, "csrf_token_invalid", 1)


@pytest.mark.parametrize(
    ("body", "key", "field"),
    [
        ({"reason": "weekly"}, None, "reason"),
        ({"reason": "scheduled", "by": "me"}, None, ""),  # the caller's member is never echoed
        ({"reason": None}, None, "reason"),
        ({"reason": "scheduled"}, "not-a-uuid", "Idempotency-Key"),
        ({"reason": "scheduled"}, _NO_KEY, "Idempotency-Key"),  # never minted here (code C4-2)
    ],
)
async def test_a_request_unlike_the_contract_is_unprocessable(
    rot: _Rot, body: dict[str, Any], key: object, field: str
) -> None:
    r = rot.post(await elevated(rot), key, body)
    assert (r.status_code, r.json()["errors"][0]["field"], len(rot.keys.rows)) == (
        422, field, 1
    )  # fmt: skip
    assert _unstored(r)


async def test_while_an_export_job_runs_the_rotation_is_a_recorded_conflict(rot: _Rot) -> None:
    jobs, release = rot.w.client.app.state.admin_jobs, asyncio.Event()

    async def export(_: Any) -> dict[str, object]:
        await release.wait()
        return {}

    async def done(_: Any) -> None:
        return None

    jobs.submit("audit_export", ("o", "k", "h"), export, done, requester="o")
    r = rot.post(await elevated(rot))
    release.set()
    assert (r.status_code, r.json()["code"], rot.refusals()) == (
        409,
        "conflict",
        ["export_in_progress"],
    )
    await jobs.stop()


async def test_past_the_hours_cap_it_is_429_counted_under_the_budget_and_not_recorded(
    rot: _Rot,
) -> None:
    """The wait is M2's, read on its clock (code C4-3); the summary that carries the count names
    the Owner as `queryAuditLog`'s does, by username (code C4-6)."""
    now = [1000.0]
    rot.svc._clock = lambda: now[0]
    token = await elevated(rot)
    for _ in range(3):
        assert rot.post(token).status_code == 200
        now[0] += 300
    r = rot.post(token)
    assert (r.status_code, r.json()["code"], rot.refusals()) == (429, "rate_limited", [])
    assert (r.headers["Retry-After"], r.json()["retry_after_seconds"]) == ("2700", 2700)
    assert len(rot.keys.rows) == 4 and _unstored(r)
    await rot.w.client.app.state.audit_budget_flush.stop()
    [summary] = rot.w.audit.of("admin.audit_denied")
    assert summary["after_state"]["suppressed"] == 1  # counted, carried by the summary
    owner = rot.w.resolver.by_token[token].user_id
    assert (summary["actor_label"], summary["actor_user_id"]) == ("basiltt", owner)  # make_user's


async def test_without_a_kek_it_is_a_recorded_403_and_a_failed_rotation_a_recorded_503(
    rot: _Rot,
) -> None:
    token = await elevated(rot)
    rot.keys.audit_fails = True  # the rotation's record, so the rotation, cannot be written
    failed = rot.post(token)
    assert (failed.status_code, failed.json()["code"], _unstored(failed)) == (
        503, "audit_unavailable", True
    )  # fmt: skip
    assert rot.audit.records[-1][0] == "security.audit_signing_key_rotation_failed"
    await rot.svc.stop(0)
    r = rot.post(token)
    assert (r.status_code, r.json()["code"], rot.refusals()) == (
        403,
        "kek_unavailable",
        ["kek_unavailable"],
    )


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
    app, budget = FastAPI(), AuditRecordBudget()
    nothing = cast(Any, None)  # neither AdminService nor the audit writer is reached
    app.include_router(make_audit_signing_router(nothing, nothing, resolver, budget=budget))
    r = TestClient(app).post(PATH, json={"reason": "scheduled"})
    assert (r.status_code, r.json()["code"], _unstored(r)) == (status, code, True)


async def _granted(_request: Any, _text: Any) -> None:
    """A `RequestElevation` whose session holds the `keys` elevation."""
    return None


def test_a_route_wired_without_its_step_up_fails_closed_and_rotates_nothing() -> None:
    """#2304 slice 3b: no `elevation` is a wiring fault, 503, never "no step-up needed"."""
    owner = PrincipalSnapshot(uuid.uuid4(), frozenset({"owner"}), OWNER)

    class _Never:
        async def rotate_audit_signing_key(self, *_: Any, **__: Any) -> Any:
            raise AssertionError("rotated without a step-up")

    app = FastAPI()
    who = SimpleNamespace(resolve=lambda _: owner)
    app.include_router(make_audit_signing_router(_Never(), cast(Any, None), who,
                                                 budget=AuditRecordBudget()))  # fmt: skip
    sent = {"Idempotency-Key": str(uuid.uuid4())}
    r = TestClient(app).post(PATH, headers=sent, json={"reason": "scheduled"})
    assert (r.status_code, r.json()["code"], _unstored(r)) == (503, "service_unavailable", True)


@pytest.mark.parametrize("store", ["down", "hung"])
async def test_a_429_whose_username_cannot_be_read_is_counted_under_the_id(
    store: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Code C4-6's fallback: a user store that cannot answer, or hangs past its bound (re-check
    C2), never loses the count and never holds the `429`."""
    monkeypatch.setattr(signing_api, "_USER_READ_S", 0.01)
    owner, records = PrincipalSnapshot(uuid.uuid4(), frozenset({"owner"}), OWNER), []

    class _Capped:  # AdminService, past the hour's cap
        async def rotate_audit_signing_key(self, *_: Any, **__: Any) -> Any:
            raise SigningKeyRotationError("rate_limited", 60)

    class _Down:  # AuthService, its user store down
        async def find_user(self, user_id: str) -> None:
            if store == "hung":
                await asyncio.Event().wait()  # never answers: the bound cuts it
            raise RuntimeError("user store down")

    class _Writer:
        async def emit(self, action: str, **fields: Any) -> None:
            records.append(fields)

    app, budget = FastAPI(), AuditRecordBudget()
    who = SimpleNamespace(resolve=lambda _: owner)
    app.include_router(make_audit_signing_router(
        _Capped(), cast(Any, None), who, budget=budget, auth=cast(Any, _Down()),
        elevation=_granted,
    ))  # fmt: skip
    sent = {"Idempotency-Key": str(uuid.uuid4())}
    r = TestClient(app).post(PATH, headers=sent, json={"reason": "scheduled"})
    assert (r.status_code, r.headers["retry-after"]) == (429, "60")
    await budget.drain(_Writer())
    assert [(f["actor_label"], f["after_state"]["suppressed"]) for f in records] == [
        (str(owner.user_id), 1)
    ]  # fmt: skip


async def test_a_body_past_its_cap_is_refused_unread(rot: _Rot) -> None:
    sent = {**_h(await elevated(rot)), "Idempotency-Key": str(uuid.uuid4())}
    raw = '{"reason": "scheduled"}' + " " * MAX_BODY_BYTES  # valid, so only the cap refuses it
    r = rot.w.client.post(PATH, headers=sent | {"content-type": "application/json"}, content=raw)
    assert (r.status_code, r.json()["errors"][0]["rule"]) == (422, "body_too_large")


async def test_a_denial_that_cannot_be_recorded_answers_audit_unavailable(rot: _Rot) -> None:
    """C-2.9: `rbac.denied` is written ahead of the 403; if it cannot be, the answer is a 503."""
    token, emit = await elevated(rot, "manager", OWNER), rot.w.audit.emit

    async def refuse_denials(action: str, **kw: Any) -> None:
        if action == "rbac.denied":
            raise AuditError(action)
        await emit(action, **kw)  # the step-up's own records still land

    rot.ctx.audit._writer = SimpleNamespace(emit=refuse_denials)
    r = rot.post(token)
    assert (r.status_code, r.json()["code"], len(rot.keys.rows)) == (503, "audit_unavailable", 1)


async def test_an_admin_service_without_m2s_rotator_records_nothing_so_answers_503() -> None:
    call = {"actor_user_id": uuid.uuid4(), "client_ref": uuid.uuid4()}
    with pytest.raises(SigningKeyRotationError, match=r"^audit_unavailable$"):
        await AdminService().rotate_audit_signing_key(
            "scheduled", client_body_sha256="a" * 64, export_running=lambda: False, **call
        )
