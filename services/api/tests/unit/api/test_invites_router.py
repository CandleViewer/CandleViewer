"""HTTP-level E09-S05 tests through the real step-up middleware + invites router."""

from __future__ import annotations

import io
import uuid
from collections.abc import Callable, Iterator
from contextlib import redirect_stdout
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
import structlog
from fastapi import Request
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from candleviewer.api.invites import _AUDIT_DOWN, make_invites_router
from candleviewer.api.step_up import request_elevation
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.invite_service import INVITE_TTL, InviteService, hash_token
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.observability import logging as logging_mod
from candleviewer.observability.correlation import CorrelationMiddleware
from candleviewer.storage.errors import WriteAheadTimeout
from tests.unit.api.test_step_up_router import _H, _build, _code, _Emitter
from tests.unit.auth.test_invite_service import (
    GOOD_PW,
    FakeHasher,
    FakeMfa,
    FakeRepo,
)
from tests.unit.auth.test_step_up import PASSWORD


class _InvAuth:
    invites_is_active = True
    sessions_is_active = False  # no session to name a refusal's (`_SessionAuth`: one)

    def __init__(self, svc: InviteService) -> None:
        self.invites = svc


class _SessionAuth(_InvAuth):
    """`_InvAuth` with the session read a refusal's record names (#4174)."""

    sessions_is_active = True

    def __init__(self, svc: InviteService) -> None:
        super().__init__(svc)
        self.sessions = self

    async def peek_access_token(self, token: str) -> Any:
        return SimpleNamespace(id=_SESSION)


_SESSION = uuid.UUID(int=4174)


class _Statuses:
    """`UserRoleStore.get_status` over the fake repo: `invited` while a row of the user is."""

    def __init__(self, repo: FakeRepo) -> None:
        self.repo = repo

    async def get_status(self, user_id: uuid.UUID) -> str | None:
        rows = [r for r in self.repo.rows.values() if r.user_id == user_id]
        return None if not rows else rows[-1].user_status.value


class _Resolver:
    def __init__(self, snap: PrincipalSnapshot) -> None:
        self.snap = snap

    def resolve(self, request: Request) -> PrincipalSnapshot | None:
        return self.snap if request.headers.get("authorization") else None


async def _setup(
    role: str = "owner", audit_ok: bool = True, auth: type[_InvAuth] = _InvAuth
) -> tuple[TestClient, _Emitter, Any, Any, FakeRepo, Any]:
    c, em, seed, clock, user = await _build(gated_stub=False)  # the real invite routes
    repo = FakeRepo()
    svc = InviteService(repo, FakeHasher(), FakeMfa(), clock=clock)  # type: ignore[arg-type]  # fakes
    snap = PrincipalSnapshot(
        user_id=user,
        roles=frozenset({role}),
        permissions=frozenset({Permission.USERS_WRITE}) if role == "owner" else frozenset(),
    )
    gate = request_elevation(c.app.state.step_up_auth, "users")  # type: ignore[attr-defined]
    router = make_invites_router(
        auth(svc), em, _Resolver(snap), audit_ready=lambda: audit_ok, elevation=gate,
        users=_Statuses(repo),
    )  # fmt: skip
    c.app.include_router(router)  # type: ignore[attr-defined]
    return c, em, seed, clock, repo, svc


_BODY = {"email": "ann@example.com", "username": "annie", "roles": ["viewer"]}


def _elevate(c: TestClient, seed: bytes, clock: Any) -> None:
    c.post(
        "/auth/step-up",
        headers=_H,
        json={"code": _code(seed, clock), "password": PASSWORD, "action_class": "users"},
    )


async def test_create_user_requires_step_up_then_returns_link_once() -> None:
    c, em, seed, clock, _, _ = await _setup()
    r = c.post("/users", headers=_H, json=_BODY)
    assert r.status_code == 403 and r.json()["code"] == "step_up_required"
    _elevate(c, seed, clock)
    r = c.post("/users", headers=_H, json=_BODY)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "invited" and body["invite_url"].startswith("/invite/")
    assert "users.invited" in em.actions()
    pending = c.get("/users/invites", headers=_H).json()["items"]
    assert len(pending) == 1 and "invite_url" not in pending[0] and "token" not in pending[0]


async def test_non_owner_forbidden_on_create() -> None:
    c, _, seed, clock, repo, _ = await _setup(role="viewer")
    _elevate(c, seed, clock)
    r = c.post("/users", headers=_H, json=_BODY)
    assert r.status_code in (403,) and not repo.rows


async def test_invite_actions_refused_with_503_before_any_change_when_audit_unavailable() -> None:
    c, em, seed, clock, repo, _ = await _setup(audit_ok=False)
    _elevate(c, seed, clock)
    assert c.post("/users", headers=_H, json=_BODY).status_code == 503
    assert c.post(f"/invites/{'t' * 43}", json={"password": GOOD_PW}).status_code == 503
    assert not repo.rows and "users.invited" not in em.actions()


async def test_create_rejects_owner_role_and_duplicate() -> None:
    c, _, seed, clock, _, _ = await _setup()
    _elevate(c, seed, clock)
    bad = {**_BODY, "roles": ["owner"]}
    assert c.post("/users", headers=_H, json=bad).status_code == 422
    assert c.post("/users", headers=_H, json=_BODY).status_code == 201
    assert c.post("/users", headers=_H, json=_BODY).status_code == 409


async def test_create_rejects_manager_role_with_generic_422_and_audit() -> None:
    c, em, seed, clock, repo, _ = await _setup()
    _elevate(c, seed, clock)
    r = c.post("/users", headers=_H, json={**_BODY, "roles": ["manager"]})
    assert r.status_code == 422 and r.json()["detail"] == "invalid invite request"
    assert not repo.rows and "users.invite_refused" in em.actions()


async def test_legacy_manager_invite_redeems_as_viewer_and_audits_downgrade() -> None:
    c, em, seed, clock, repo, _ = await _setup()
    tok = await _invite(c, seed, clock)
    h = hash_token(tok)
    repo.rows[h] = repo.rows[h].model_copy(update={"role": "manager"})
    start = c.post(f"/invites/{tok}", json={"password": GOOD_PW})
    done = c.post(
        f"/invites/{tok}/confirm", json={"method_id": start.json()["method_id"], "code": "123456"}
    )
    assert done.status_code == 200 and done.json()["role"] == "viewer"
    assert "users.invite_role_downgraded" in em.actions()
    assert "users.invite_redeemed" in em.actions()


async def _invite(c: TestClient, seed: bytes, clock: Any) -> str:
    _elevate(c, seed, clock)
    url = c.post("/users", headers=_H, json=_BODY).json()["invite_url"]
    return url.rsplit("/", 1)[1]


async def test_invite_accepted_flow_over_http() -> None:
    c, em, seed, clock, _, _ = await _setup()
    tok = await _invite(c, seed, clock)
    assert c.get(f"/invites/{tok}").json()["role"] == "viewer"
    start = c.post(f"/invites/{tok}", json={"password": GOOD_PW})
    assert start.status_code == 200
    done = c.post(
        f"/invites/{tok}/confirm", json={"method_id": start.json()["method_id"], "code": "123456"}
    )
    assert done.status_code == 200 and done.json()["status"] == "active"
    assert done.json()["recovery_codes"] == ["rc-1", "rc-2"]
    assert "users.invite_redeemed" in em.actions()


async def test_reuse_is_uniform_404_and_audited_warning() -> None:
    c, em, seed, clock, _, _ = await _setup()
    tok = await _invite(c, seed, clock)
    assert c.post(f"/invites/{tok}", json={"password": GOOD_PW}).status_code == 200
    again = c.post(f"/invites/{tok}", json={"password": GOOD_PW})
    unknown = c.get("/invites/" + "z" * 40)
    assert again.status_code == unknown.status_code == 404
    assert again.json() == unknown.json()
    rej = [x for x in em.calls if x["action"] == "users.invite_rejected"]
    assert rej[0]["reason"] == "redeemed" and rej[0]["severity"].value == "warning"


async def test_expired_invite_is_404_after_72h() -> None:
    c, em, seed, clock, _, _ = await _setup()
    tok = await _invite(c, seed, clock)
    clock.now += INVITE_TTL + timedelta(seconds=1)
    assert c.get(f"/invites/{tok}").status_code == 404
    assert [x["reason"] for x in em.calls if x["action"] == "users.invite_rejected"] == ["expired"]


async def test_role_tamper_on_redeem_is_403_and_audited_without_consuming() -> None:
    c, em, seed, clock, _, _ = await _setup()
    tok = await _invite(c, seed, clock)
    r = c.post(f"/invites/{tok}", json={"password": GOOD_PW, "role": "owner"})
    assert r.status_code == 403
    rej = [x for x in em.calls if x["action"] == "users.invite_rejected"]
    assert rej and rej[-1]["reason"] == "role_tamper" and rej[-1]["severity"].value == "warning"
    assert c.post(f"/invites/{tok}", json={"password": GOOD_PW}).status_code == 200
    t2 = c.post(f"/invites/{tok}/confirm", json={"method_id": "m", "code": "1", "roles": ["owner"]})
    assert t2.status_code == 403


async def test_revoke_and_reissue_invalidate_old_link() -> None:
    c, _, seed, clock, _, _ = await _setup()
    tok = await _invite(c, seed, clock)
    uid = c.get("/users/invites", headers=_H).json()["items"][0]["user_id"]
    assert c.delete(f"/users/{uid}/invite", headers=_H).status_code == 200
    assert c.get(f"/invites/{tok}").status_code == 404
    assert c.delete(f"/users/{uuid.uuid4()}/invite", headers=_H).status_code == 404


async def test_brute_force_token_guessing_trips_429_even_for_valid_token() -> None:
    c, _, seed, clock, _, _ = await _setup()
    tok = await _invite(c, seed, clock)
    bad = "A" * 43
    codes = [c.get(f"/invites/{bad}").status_code for _ in range(10)]
    assert set(codes) == {404}
    assert c.get(f"/invites/{bad}").status_code == 429
    assert c.get(f"/invites/{tok}").status_code == 429


# -- #2319 item 3: identity claims and the tamper budget --------------------------------------

_CLAIMS = [{"username": "bob"}, {"user_id": "u-1c0ffee"}, {"email": "b@x.test"}]


def _rejected(reason: str) -> float:
    sample = REGISTRY.get_sample_value("users_invites_rejected_total", {"reason": reason})
    return float(sample or 0.0)


def _tamper_rows(em: _Emitter) -> list[tuple[Any, ...]]:
    rows = (x for x in em.calls if x["action"] == "users.invite_rejected")
    return [(x["reason"], x["outcome"].value, x["severity"].value) for x in rows]


@pytest.mark.parametrize("claim", _CLAIMS)
async def test_identity_claim_is_the_same_400_audited_counted_and_consumes_nothing(
    claim: dict[str, str],
) -> None:
    c, em, seed, clock, _, _ = await _setup()
    tok = await _invite(c, seed, clock)
    plain = c.post(f"/invites/{tok}", json={"password": GOOD_PW, "undeclared": "x"})
    assert _tamper_rows(em) == []  # an undeclared non-identity field stays a silent 400
    before = _rejected("identity_tamper")
    claimed = c.post(f"/invites/{tok}", json={"password": GOOD_PW, **claim})
    assert (claimed.status_code, claimed.json()) == (plain.status_code, plain.json())  # no oracle
    assert claimed.status_code == 400 and claimed.json()["detail"] == "password is required"
    assert _tamper_rows(em) == [("identity_tamper", "denied", "warning")]
    assert _rejected("identity_tamper") - before == 1
    assert next(iter(claim.values())) not in repr(em.calls)  # the claimed value is never recorded
    assert c.post(f"/invites/{tok}", json={"password": GOOD_PW}).status_code == 200  # not consumed


async def test_identity_claim_on_confirm_is_the_same_400_and_audited() -> None:
    c, em, seed, clock, _, _ = await _setup()
    tok = await _invite(c, seed, clock)
    start = c.post(f"/invites/{tok}", json={"password": GOOD_PW})
    ok = {"method_id": start.json()["method_id"], "code": "123456"}
    claimed = c.post(f"/invites/{tok}/confirm", json={**ok, "email": "b@x.test"})
    assert claimed.status_code == 400 and "method_id and code" in claimed.json()["detail"]
    assert _tamper_rows(em) == [("identity_tamper", "denied", "warning")]
    assert c.post(f"/invites/{tok}/confirm", json=ok).status_code == 200


async def test_tamper_requests_past_the_per_source_budget_get_429_and_write_no_row() -> None:
    c, em, seed, clock, _, _ = await _setup()
    tok = await _invite(c, seed, clock)
    role0, identity0 = _rejected("role_tamper"), _rejected("identity_tamper")
    role, identity = {"password": GOOD_PW, "roles": ["owner"]}, {"password": GOOD_PW, **_CLAIMS[2]}
    sent = [c.post(f"/invites/{tok}", json=role if i % 2 else identity) for i in range(10)]
    assert [r.status_code for r in sent] == [400, 403] * 5  # the budget is shared by both kinds
    assert (_rejected("role_tamper") - role0, _rejected("identity_tamper") - identity0) == (5, 5)
    assert c.post(f"/invites/{tok}", json=role).status_code == 429
    assert c.post(f"/invites/{tok}", json=identity).status_code == 429
    assert c.get(f"/invites/{tok}").status_code == 429  # the same budget as every invalid attempt
    assert len(_tamper_rows(em)) == 10  # no row past it


async def test_a_tamper_that_passed_the_gate_as_the_budget_filled_is_still_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The gate reads the budget before the body is read; a request let through while the budget
    # was filling must be refused where the budget is spent, not write a row past it.
    c, em, seed, clock, _, svc = await _setup()
    tok = await _invite(c, seed, clock)
    tamper = {"password": GOOD_PW, "role": "owner"}
    assert [c.post(f"/invites/{tok}", json=tamper).status_code for _ in range(10)] == [403] * 10
    real, reads = svc.is_blocked, []

    def gate_then_real(ip: str) -> bool:
        reads.append(ip)
        return False if len(reads) == 1 else real(ip)

    monkeypatch.setattr(svc, "is_blocked", gate_then_real)
    assert c.post(f"/invites/{tok}", json=tamper).status_code == 429
    assert len(_tamper_rows(em)) == 10 and len(reads) == 2  # the gate, then the spend point


# ---- #3990: every invite record names the id `CorrelationMiddleware` bound ----------------------

_BOUND = "3f2b8c1e-9d4a-4b7e-8a51-0c6d2e7f9a10"


def _correlated(c: TestClient) -> None:
    """The real middleware, which Starlette takes only before the first request."""
    c.app.add_middleware(CorrelationMiddleware)  # type: ignore[attr-defined]  # typed as ASGIApp


async def test_the_owner_check_denial_names_the_request_and_the_address() -> None:
    c, em, seed, clock, _, _ = await _setup(role="viewer")
    _correlated(c)
    _elevate(c, seed, clock)
    r = c.post("/users", headers=_H, json=_BODY)  # neither correlation header: the id is minted
    assert r.status_code == 403
    (denied,) = [x for x in em.calls if x["action"] == "rbac.denied"]
    assert str(denied["request_id"]) == r.headers["x-correlation-id"]
    assert denied["actor_ip"] == "testclient"


async def test_the_owner_records_carry_the_inbound_correlation_id() -> None:
    c, em, seed, clock, _, _ = await _setup()
    _correlated(c)
    _elevate(c, seed, clock)
    sent = {**_H, "X-Correlation-Id": _BOUND}
    assert c.post("/users", headers=sent, json=_BODY).status_code == 201
    refused = c.post("/users", headers=sent, json={**_BODY, "roles": ["manager"]})
    assert refused.status_code == 422
    seen = {x["action"]: x["request_id"] for x in em.calls if x["action"].startswith("users.")}
    assert {a: str(i) for a, i in seen.items()} == {
        "users.invited": _BOUND,
        "users.invite_refused": _BOUND,
    }


async def test_the_invitee_records_carry_the_minted_id_when_the_request_names_none() -> None:
    c, em, *_ = await _setup()
    _correlated(c)
    r = c.get(f"/invites/{'t' * 43}")  # an unknown link: rejected and audited
    assert r.status_code == 404
    (rejected,) = [x for x in em.calls if x["action"] == "users.invite_rejected"]
    assert str(rejected["request_id"]) == r.headers["x-correlation-id"]


async def test_the_owner_check_denial_names_the_callers_session() -> None:
    """#4174: as the `users:read` refusal names it."""
    c, em, seed, clock, _, _ = await _setup(role="viewer", auth=_SessionAuth)
    _elevate(c, seed, clock)
    r = c.post("/users", headers=_H, json=_BODY)
    assert r.status_code == 403
    (denied,) = [x for x in em.calls if x["action"] == "rbac.denied"]
    assert denied["session_id"] == _SESSION


# -- #4479: the bootstrap invite over HTTP -----------------------------------------------------


async def _bootstrap_token(
    c: TestClient, seed: bytes, clock: Any, repo: FakeRepo, name: str = "annie"
) -> str:
    """An invite turned into the marked `owner` invite the offline mint (C1) writes."""
    _elevate(c, seed, clock)
    body = {**_BODY, "email": f"{name}@example.com", "username": name}
    tok = str(c.post("/users", headers=_H, json=body).json()["invite_url"]).rsplit("/", 1)[1]
    h = hash_token(tok)
    repo.rows[h] = repo.rows[h].model_copy(update={"role": "owner"})
    repo.marked.add(repo.rows[h].id)
    return tok


def _redeem(c: TestClient, tok: str) -> Any:
    start = c.post(f"/invites/{tok}", json={"password": GOOD_PW})
    body = {"method_id": start.json()["method_id"], "code": "123456"}
    return c.post(f"/invites/{tok}/confirm", json=body)


async def test_bootstrap_invite_is_offered_and_redeemed_as_owner_with_a_critical_record() -> None:
    c, em, seed, clock, repo, _ = await _setup()
    tok = await _bootstrap_token(c, seed, clock, repo)
    assert c.get(f"/invites/{tok}").json()["role"] == "owner"  # DC-15: the role being offered
    done = _redeem(c, tok)
    assert done.status_code == 200 and done.json()["role"] == "owner"
    (rec,) = [x for x in em.calls if x["action"] == "users.owner_bootstrapped"]
    invite_id = str(repo.rows[hash_token(tok)].id)
    assert (rec["severity"].value, rec["after_state"]) == ("critical", {"invite_id": invite_id})
    assert {"actor_ip", "request_id"} <= rec.keys()
    assert "users.invite_role_downgraded" not in em.actions()
    assert em.actions().index("users.owner_bootstrapped") < em.actions().index(
        "users.invite_redeemed"
    )


async def test_bootstrap_confirm_answers_503_and_grants_nothing_when_its_record_is_refused() -> (
    None
):
    c, em, seed, clock, repo, _ = await _setup()
    tok = await _bootstrap_token(c, seed, clock, repo)
    em.fail_on = frozenset({"users.owner_bootstrapped"})
    assert _redeem(c, tok).status_code == 503
    assert repo.owners == 0 and "users.invite_redeemed" not in em.actions()


async def test_bootstrap_confirm_answers_503_when_its_record_misses_the_write_ahead_bound() -> None:
    c, em, seed, clock, repo, _ = await _setup()
    tok = await _bootstrap_token(c, seed, clock, repo)

    async def late(*_a: Any, **_kw: Any) -> str:
        raise WriteAheadTimeout("write-ahead audit exceeded 5.0 s")  # the store rolled back

    repo.activate_bootstrap_owner = late  # type: ignore[method-assign]  # the store's answer
    done = _redeem(c, tok)
    assert (done.status_code, done.json()["detail"]) == (503, _AUDIT_DOWN)
    assert repo.owners == 0 and "users.invite_redeemed" not in em.actions()


async def test_a_stale_bootstrap_invite_is_the_uniform_404_at_inspect_and_confirm() -> None:
    """DC-09: another Owner is active. `GET` refuses before a password is parked; a `/confirm`
    that started before that Owner existed is refused too, nothing activated (ruling 4)."""
    c, em, seed, clock, repo, _ = await _setup()
    tok = await _bootstrap_token(c, seed, clock, repo)
    unknown = c.get("/invites/" + "z" * 40)
    repo.owners = 1
    seen = c.get(f"/invites/{tok}")
    repo.owners = 0
    start = c.post(f"/invites/{tok}", json={"password": GOOD_PW})
    repo.owners = 1
    body = {"method_id": start.json()["method_id"], "code": "123456"}
    done = c.post(f"/invites/{tok}/confirm", json=body)
    assert seen.status_code == done.status_code == unknown.status_code == 404
    assert seen.json() == done.json() == unknown.json()
    rej = [x["reason"] for x in em.calls if x["action"] == "users.invite_rejected"]
    assert rej[-2:] == ["revoked", "revoked"]
    assert repo.owners == 1 and "users.owner_bootstrapped" not in em.actions()


@pytest.fixture
def json_logs() -> Iterator[Callable[[], str]]:
    """The shipped JSON logging into a buffer; calling the yield flushes and reads it. Teardown
    resets logging whatever the test did, a failed assertion included."""
    buf = io.StringIO()

    def read() -> str:
        logging_mod.reset_logging()  # stops the listener: every queued line is written
        return buf.getvalue()

    with redirect_stdout(buf):
        logging_mod.configure_logging(env="test", level="debug", fmt="json")
        try:
            yield read
        finally:
            logging_mod.reset_logging()


async def test_bootstrap_redemption_logs_no_token_or_password_through_the_real_redactor(
    json_logs: Callable[[], str],
) -> None:
    """DC-16: every log line of the flow, a refused record included, goes through the shipped
    processors; the probe line shows the redactor is live (its `token` value is masked)."""
    c, em, seed, clock, repo, _ = await _setup()
    tok = await _bootstrap_token(c, seed, clock, repo)
    spare = await _bootstrap_token(c, seed, clock, repo, name="spare")
    structlog.get_logger("cv.test").info("probe", token=tok)
    em.fail_on = frozenset({"users.owner_bootstrapped"})
    assert _redeem(c, spare).status_code == 503
    em.fail_on = frozenset()
    assert c.get(f"/invites/{tok}").status_code == 200
    assert _redeem(c, tok).status_code == 200
    out = json_logs()
    assert '"event":"probe"' in out.replace(" ", "")
    assert tok not in out and spare not in out and GOOD_PW not in out


# -- #2304 slice 3c: the invite writes gate in their handlers -----------------------------------


def _challenges(em: _Emitter) -> int:
    return em.actions().count("auth.step_up_required")


@pytest.mark.parametrize(
    ("body", "status"),
    [({**_BODY, "roles": ["manager"]}, 422), ({**_BODY, "nickname": "x"}, 422), ([], 400)],
    ids=["role", "unknown-field", "not-an-object"],
)
async def test_an_unelevated_owners_invalid_invite_is_refused_never_challenged(
    body: Any, status: int
) -> None:
    c, em, _, _, repo, _ = await _setup()
    r = c.post("/users", headers=_H, json=body)
    assert r.status_code == status and "challenge_id" not in r.json()
    assert _challenges(em) == 0 and not repo.rows


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/users"), ("POST", "/users/{}/invite"), ("DELETE", "/users/{}/invite")],
    ids=["createUser", "reissueInvite", "revokeInvite"],
)
async def test_an_unelevated_non_owner_invite_write_is_the_audited_403_never_a_challenge(
    method: str, path: str
) -> None:
    c, em, _, _, repo, _ = await _setup(role="viewer")
    r = c.request(method, path.format(uuid.uuid4()), headers=_H, json=_BODY)
    assert (r.status_code, r.json()["code"]) == (
        403,
        "forbidden",
    ) and "challenge_id" not in r.json()
    assert "rbac.denied" in em.actions() and _challenges(em) == 0 and not repo.rows


@pytest.mark.parametrize("method", ["POST", "DELETE"], ids=["reissueInvite", "revokeInvite"])
async def test_an_unelevated_owners_missing_invite_is_the_404_never_a_challenge(
    method: str,
) -> None:
    c, em, seed, clock, _, _ = await _setup()
    _elevate(c, seed, clock)
    assert c.post("/users", headers=_H, json=_BODY).status_code == 201
    clock.now += timedelta(minutes=5, seconds=1)  # the window ended: only the 404 is left
    for target in (uuid.uuid4(), uuid.UUID(int=0)):
        r = c.request(method, f"/users/{target}/invite", headers=_H)
        assert r.status_code == 404 and "challenge_id" not in r.json()
    assert _challenges(em) == 0


async def test_a_revoked_invite_is_the_404_of_a_revoke_and_a_challenge_of_a_reissue() -> None:
    """A revoke needs a pending invite and a re-issue an `invited` user (22): after a revoke
    the user stays invited, so a re-issue is challenged while a second revoke is the 404."""
    c, _em, seed, clock, _, _ = await _setup()
    _elevate(c, seed, clock)
    assert c.post("/users", headers=_H, json=_BODY).status_code == 201
    uid = c.get("/users/invites", headers=_H).json()["items"][0]["user_id"]
    assert c.delete(f"/users/{uid}/invite", headers=_H).status_code == 200
    clock.now += timedelta(minutes=5, seconds=1)
    assert c.delete(f"/users/{uid}/invite", headers=_H).status_code == 404
    again = c.post(f"/users/{uid}/invite", headers=_H)
    assert (again.status_code, again.json()["action_summary"]) == (
        403, f"Reissue the invite link of user {uid}",
    )  # fmt: skip


async def test_an_unelevated_owners_invite_is_challenged_naming_no_username_or_email() -> None:
    c, _em, _, _, repo, _ = await _setup()
    sent = {**_BODY, "display_name": "SENTINEL-free-text"}
    r = c.post("/users", headers=_H, json=sent)
    body = r.json()
    assert (r.status_code, body["code"], body["action_class"]) == (403, "step_up_required", "users")
    assert body["action_summary"] == "Invite a new user as viewer (MFA required)"
    assert not [word for word in ("ann@example.com", "annie", "SENTINEL") if word in r.text]
    assert not repo.rows


async def test_an_unelevated_owners_revoke_is_challenged_naming_the_user_by_id() -> None:
    c, _em, seed, clock, repo, _ = await _setup()
    _elevate(c, seed, clock)
    assert c.post("/users", headers=_H, json=_BODY).status_code == 201
    uid = c.get("/users/invites", headers=_H).json()["items"][0]["user_id"]
    clock.now += timedelta(minutes=5, seconds=1)
    r = c.delete(f"/users/{uid}/invite", headers=_H)
    assert (r.status_code, r.json()["action_summary"]) == (
        403, f"Revoke the pending invite of user {uid}",
    )  # fmt: skip
    assert "annie" not in r.text and len(repo.rows) == 1
    assert not any(row.revoked_at for row in repo.rows.values())


async def test_an_invite_resent_after_the_window_ends_is_challenged_never_answered() -> None:
    """The invite keeps no answer to replay: the identical re-send after the window is the
    challenge, never the store's `409` for the email the first send took."""
    c, _em, seed, clock, repo, _ = await _setup()
    _elevate(c, seed, clock)
    assert c.post("/users", headers=_H, json=_BODY).status_code == 201
    clock.now += timedelta(minutes=5, seconds=1)
    again = c.post("/users", headers=_H, json=_BODY)
    assert (again.status_code, again.json()["code"]) == (403, "step_up_required")
    assert len(repo.rows) == 1


async def test_an_invite_write_wired_without_its_step_up_fails_closed() -> None:
    c, em, seed, clock, user = await _build(gated_stub=False)
    repo = FakeRepo()
    svc = InviteService(repo, FakeHasher(), FakeMfa(), clock=clock)  # type: ignore[arg-type]  # fakes
    snap = PrincipalSnapshot(user_id=user, roles=frozenset({"owner"}),
                             permissions=frozenset({Permission.USERS_WRITE}))  # fmt: skip
    auth = cast(Any, _InvAuth(svc))  # a structural fake with no session read, as `_setup`'s
    router = make_invites_router(auth, em, _Resolver(snap), audit_ready=lambda: True)
    c.app.include_router(router)  # type: ignore[attr-defined]
    _elevate(c, seed, clock)
    r = c.post("/users", headers=_H, json=_BODY)
    assert (r.status_code, r.json()["code"]) == (503, "service_unavailable") and not repo.rows


async def test_a_reissue_wired_without_a_user_store_fails_closed() -> None:
    """The re-issue's target lookup is a port like the step-up's: unwired, the route answers 503
    before any gate or change, never skipping the lookup."""
    c, em, seed, clock, user = await _build(gated_stub=False)
    repo = FakeRepo()
    svc = InviteService(repo, FakeHasher(), FakeMfa(), clock=clock)  # type: ignore[arg-type]  # fakes
    snap = PrincipalSnapshot(user_id=user, roles=frozenset({"owner"}),
                             permissions=frozenset({Permission.USERS_WRITE}))  # fmt: skip
    gate = request_elevation(c.app.state.step_up_auth, "users")  # type: ignore[attr-defined]
    router = make_invites_router(
        cast(Any, _InvAuth(svc)), em, _Resolver(snap), audit_ready=lambda: True, elevation=gate,
    )  # fmt: skip
    c.app.include_router(router)  # type: ignore[attr-defined]
    _elevate(c, seed, clock)
    assert c.post("/users", headers=_H, json=_BODY).status_code == 201  # a create needs no store
    uid = c.get("/users/invites", headers=_H).json()["items"][0]["user_id"]
    clock.now += timedelta(minutes=5, seconds=1)  # no live window: a skipped lookup would challenge
    r = c.post(f"/users/{uid}/invite", headers=_H)
    assert (r.status_code, r.json()["detail"]) == (503, "the user store is not wired")
    assert "challenge_id" not in r.json() and len(repo.rows) == 1
    assert "users.invite_reissued" not in em.actions()
