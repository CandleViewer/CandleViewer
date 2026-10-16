"""#2304 over HTTP: every `403 step_up_required` is a challenge for the one request it refused,
restated from server-side records, and `POST /auth/step-up` answers the live one by its id.

The harness routes stand in for the routes the route slice of #2304 wires: they validate their
request, compose the restatement from server records, then call the route-level gate.
`POST /trading/kill-switch` has E39's shape (not mounted yet).
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import BaseModel, ConfigDict

from candleviewer.api.step_up import (
    make_read_only_guard,
    make_step_up_router,
    require_elevation_for,
    require_session_elevation,
)
from candleviewer.api.step_up_challenge import (
    ChallengeText,
    account_reference,
    raw_request_target,
    request_fingerprint,
    typed_target,
)
from candleviewer.api.users import make_users_router
from candleviewer.audit.models import AuditOutcome
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.mfa_service import MfaService
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind, SessionRecord
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.step_up import StepUpService
from candleviewer.auth.throttle import PerIpLoginThrottle
from candleviewer.auth.totp import generate_code, time_step_for
from candleviewer.statechart.bindings import b16_session
from tests.contract.test_step_up_challenge_contract import (
    _PROBLEM,
    _SPEC,
    _STEP_UP_REQUIRED_BODY,
    _account_reference,
    _ref,
    _validator,
)
from tests.unit.api.test_step_up_router import (
    _H,
    _PW,
    _T0,
    _Auth,
    _build,
    _Clock,
    _code,
    _Emitter,
    _record,
    _Sessions,
)
from tests.unit.api.test_users_router import _Notifier, _Resolver, _Store
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository

_KEY = "5f0c6b1e-2d3a-4c4b-9e8f-7a6b5c4d3e2f"  # the held request's Idempotency-Key
_RELEASE = {"engaged": False, "scope": "global"}
#: The server's account records (label, environment, exchange UID), by account id.
_ACCOUNTS = {
    "acc-1": ("sub_002", "live", "1001234"),
    "acc-2": ("Main", "live", "1001235"),
    "acc-3": ("MAIN", "demo", "2002001"),
    "acc-4": ("demo-1' (demo)\u202e", "demo", "2002002"),
}


class _KillSwitch(BaseModel):
    """The harness body (`POST /trading/kill-switch`, E39 shape)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    engaged: bool
    scope: Literal["global", "account"]
    account_ids: tuple[str, ...] = ()
    reason: str | None = None


@dataclass
class _World:
    client: TestClient
    audit: _Emitter
    seed: bytes
    clock: _Clock
    auth: _Auth
    rows: FakeSessionRepository
    sessions: dict[str, SessionRecord]
    executed: list[dict[str, Any]]

    def h(self, who: str = "tok") -> dict[str, str]:
        return {"Authorization": f"Bearer {who}", "Idempotency-Key": _KEY}

    # Starlette types `TestClient` against `httpx2`, which is not installed, so mypy sees `Any`;
    # the runtime object is an `httpx.Response`, which the typed locals below state.
    def send(self, body: dict[str, Any], *, who: str = "tok", path: str = "") -> Response:
        sent: Response = self.client.post(
            f"/trading/kill-switch{path}", headers=self.h(who), json=body
        )
        return sent

    def step_up(self, who: str = "tok", **body: Any) -> Response:
        payload = {"code": _code(self.seed, self.clock), "password": _PW, **body}
        answered: Response = self.client.post("/auth/step-up", headers=self.h(who), json=payload)
        return answered

    def of(self, action: str) -> list[dict[str, Any]]:
        return [c for c in self.audit.calls if c["action"] == action]


async def _world() -> _World:
    clock, repo, enc = _Clock(), FakeMfaRepository(), TotpEncryptor(os.urandom(32))
    clock.now = _T0
    mfa = MfaService(repo, enc, recovery_code_key=b"k" * 32, clock=clock)
    user = uuid.uuid4()
    res = await mfa.enroll(
        str(user), MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="o"
    )
    seed = enc.decrypt(repo.methods[str(res.method_id)].secret_enc)  # type: ignore[arg-type]
    first = generate_code(seed, time_step_for(_T0.timestamp()) - 1)
    await mfa.confirm_enrollment(str(user), method_id=str(res.method_id), code=first)
    rows = FakeSessionRepository()
    sessions = {"tok": _record(user), "tok2": _record(user), "other": _record(uuid.uuid4())}
    for record in sessions.values():
        await rows.create_session(record)
    hasher, users = Hasher(), FakeUserRepository()
    users.add(make_user(password_hash=await hasher.hash(_PW)).model_copy(update={"id": user}))
    auth = _Auth(StepUpService(repo, rows, enc, users, hasher, clock=clock), _Sessions(sessions))
    audit = _Emitter()
    b16_session.set_audit_sink(audit)
    app = FastAPI()
    app.include_router(make_step_up_router(auth, audit, audit_ready=lambda: True))
    app.middleware("http")(make_read_only_guard(auth, audit))
    executed: list[dict[str, Any]] = []

    def _sid(request: Request) -> str:
        return str(sessions[request.headers["authorization"].removeprefix("Bearer ")].id)

    @app.put("/users/{uid}/roles")
    async def roles(uid: str) -> dict[str, bool]:
        return {"ok": True}

    @app.post("/trading/kill-switch")
    async def kill_switch(request: Request) -> Any:
        body = _KillSwitch.model_validate(await request.json()).model_dump(mode="json")
        if not body["engaged"]:  # release: a no-grace step-up bound to this request
            denied = await require_elevation_for(
                auth,
                _sid(request),
                "killswitch",
                text=ChallengeText(f"Release kill switch, scope {body['scope']}"),
                fingerprint=request_fingerprint(request.method, raw_request_target(request), body),
                emitter=audit,
            )
            if denied is not None:
                return denied
        executed.append(body)
        return {"ok": True}

    @app.post("/harness/accounts/{account_id}/keys/rotate")
    async def rotate(account_id: str, request: Request) -> Any:
        label, environment, uid = _ACCOUNTS[account_id]  # server records, never the body
        others = [other[0] for key, other in _ACCOUNTS.items() if key != account_id]
        text = ChallengeText(
            f"Rotate API key for account {account_reference(label, environment, uid)}",
            typed_target(label, account_id, others),
        )
        return await require_elevation_for(auth, _sid(request), "keys", text=text) or {}

    return _World(TestClient(app), audit, seed, clock, auth, rows, sessions, executed)


async def test_refusal_is_a_challenge_that_restates_what_would_execute() -> None:
    """AC "Challenge restates what will execute" (release the kill switch, scope global)."""
    w = await _world()
    denied = w.send(_RELEASE)
    assert denied.status_code == 403
    body = denied.json()
    _validator(_SPEC, _STEP_UP_REQUIRED_BODY).validate(body)  # provider side (C-6.2)
    assert body["action_class"] == "killswitch"
    assert body["action_summary"] == "Release kill switch, scope global" and body["target"] is None
    assert uuid.UUID(body["challenge_id"]).version == 4
    expires = datetime.fromisoformat(body["challenge_expires_at"])
    assert expires == w.clock.now + timedelta(minutes=5)
    (required,) = w.of("auth.step_up_required")
    assert required["object_id"] == body["challenge_id"]
    assert w.executed == []


@pytest.mark.parametrize(
    ("account", "summary", "target"),
    [
        ("acc-1", "Rotate API key for account 'sub_002' (live, UID 1001234)", "sub_002"),
        ("acc-2", "Rotate API key for account 'Main' (live, UID 1001235)", "acc-2"),
        (
            "acc-4",
            "Rotate API key for account 'demo-1\\' (demo)\\u{202E}' (demo, UID 2002002)",
            "acc-4",
        ),
    ],
    ids=["unique-label", "label-shared-case-insensitively", "escaped-label"],
)
async def test_restatement_comes_from_server_records_never_the_request(
    account: str, summary: str, target: str
) -> None:
    w = await _world()
    forged = {"action_summary": "Rotate nothing", "target": "x", "label": "sub_002"}
    denied = w.client.post(f"/harness/accounts/{account}/keys/rotate", headers=w.h(), json=forged)
    body = denied.json()
    _validator(_SPEC, _STEP_UP_REQUIRED_BODY).validate(body)
    assert (body["action_summary"], body["target"]) == (summary, target)
    account_part = summary.removeprefix("Rotate API key for account ")
    assert _account_reference(_SPEC).fullmatch(account_part)


@pytest.mark.parametrize("stale", ["expired", "unknown", "superseded"])
async def test_stale_challenge_id_is_400_challenge_expired(stale: str) -> None:
    """AC "Challenge expiry": a challenge issued more than 5 minutes ago is refused 400. The
    refusal is audited with the presented id (a replayed or probed id is visible); no factor
    is checked or counted."""
    w = await _world()
    challenge_id = w.send(_RELEASE).json()["challenge_id"]
    if stale == "expired":
        w.clock.now += timedelta(minutes=5, seconds=1)
    elif stale == "unknown":
        challenge_id = str(uuid.uuid4())
    else:
        w.send({"engaged": False, "scope": "account"})
    code = _code(w.seed, w.clock)
    r = w.step_up(challenge_id=challenge_id)
    assert r.status_code == 400 and r.json()["errors"][0]["rule"] == "challenge_expired"
    _validator(_SPEC, _ref(_PROBLEM)).validate(r.json())
    (refused,) = w.of("auth.step_up_failed")
    assert (refused["outcome"], refused["reason"]) == (AuditOutcome.DENIED, "challenge_expired")
    assert (refused["object_kind"], refused["object_id"]) == ("step_up_challenge", challenge_id)
    assert all(secret not in repr(refused) for secret in (_PW, f"'{code}'", f'"{code}"'))
    assert w.rows.sessions[str(w.sessions["tok"].id)].step_up_failures == 0


async def test_challenge_refusals_are_audited_within_a_per_session_budget() -> None:
    w = await _world()
    budget = PerIpLoginThrottle(max_attempts=2, window_s=60.0, clock=lambda: 0.0)
    app = FastAPI()
    app.include_router(
        make_step_up_router(w.auth, w.audit, audit_ready=lambda: True, refusal_budget=budget)
    )
    probe = {"code": "000000", "password": _PW, "action_class": "keys"}
    for _ in range(3):  # each presents an id the session never issued
        sent = probe | {"challenge_id": str(uuid.uuid4())}
        assert TestClient(app).post("/auth/step-up", headers=w.h(), json=sent).status_code == 400
    assert len(w.of("auth.step_up_failed")) == 2  # the third is refused, not audited


async def test_refused_challenge_and_wrong_factor_rows_are_told_apart() -> None:
    """Both rows are `auth.step_up_failed`. Triage tells them apart by the discriminator that
    `24-internal-schemas.md` section 15.5 and the auth runbook (section 2) state: a step-up
    refused before any factor is checked is outcome `denied` with object kind
    `step_up_challenge` and the refusal rule as reason; a wrong password or code is outcome
    `failure`, has no object and gives `<class>:remaining=<n>`."""
    w = await _world()
    w.client.put(f"/users/{uuid.uuid4()}/roles", headers=w.h())  # a live `users` challenge
    assert w.step_up(challenge_id=str(uuid.uuid4())).status_code == 400
    assert w.step_up(code="000000").status_code == 401

    refused, wrong = w.of("auth.step_up_failed")

    assert (refused["outcome"], refused["object_kind"], refused["reason"]) == (
        AuditOutcome.DENIED,
        "step_up_challenge",
        "challenge_expired",
    )
    assert (wrong["outcome"], wrong["object_kind"], wrong["reason"]) == (
        AuditOutcome.FAILURE,
        None,
        "users:remaining=2",
    )


@pytest.mark.parametrize(
    ("member", "rule"),
    [({"remember": True}, "extra_forbidden"), ({"code": "12345"}, "string_pattern_mismatch")],
    ids=["unknown-member", "code-not-six-digits"],
)
async def test_step_up_body_outside_its_schema_is_400_before_any_factor(
    member: dict[str, Any], rule: str
) -> None:
    """`extra="forbid"` and the contract's `code` pattern hold server-side: nothing is checked,
    counted or elevated."""
    w = await _world()
    w.client.put(f"/users/{uuid.uuid4()}/roles", headers=w.h())  # a live grace challenge
    r = w.step_up(**member)
    assert r.status_code == 400
    _validator(_SPEC, _ref(_PROBLEM)).validate(r.json())
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [(next(iter(member)), rule)]
    assert w.rows.sessions[str(w.sessions["tok"].id)].step_up_failures == 0
    assert not w.of("auth.step_up_failed") and not w.of("auth.step_up_granted")


@pytest.mark.parametrize("who", ["tok2", "other"], ids=["other-session", "other-user"])
async def test_challenge_id_is_unknown_to_any_other_session(who: str) -> None:
    w = await _world()
    challenge_id = w.send(_RELEASE).json()["challenge_id"]
    stolen = w.step_up(who, challenge_id=challenge_id)
    assert stolen.status_code == 400 and stolen.json()["errors"][0]["rule"] == "challenge_expired"
    assert w.step_up(challenge_id=challenge_id).status_code == 200  # still live for its owner


@pytest.mark.parametrize("answer", ["with-challenge-id", "without-challenge-id"])
async def test_grace_challenge_is_answered_with_or_without_challenge_id(answer: str) -> None:
    w = await _world()
    path = f"/users/{uuid.uuid4()}/roles"
    denied = w.client.put(path, headers=w.h())
    assert denied.status_code == 403
    _validator(_SPEC, _STEP_UP_REQUIRED_BODY).validate(denied.json())
    sent = {"challenge_id": denied.json()["challenge_id"]} if answer == "with-challenge-id" else {}
    ok = w.step_up(**sent)
    assert ok.status_code == 200 and ok.json()["action_class"] == "users"
    expires = datetime.fromisoformat(ok.json()["step_up_expires_at"])
    assert expires == w.clock.now + timedelta(minutes=5)
    assert w.client.put(path, headers=w.h()).status_code == 200


@pytest.mark.parametrize("value", ["challenge-1", 7], ids=["not-a-uuid", "not-a-string"])
async def test_malformed_challenge_id_is_400(value: object) -> None:
    w = await _world()
    w.client.put(f"/users/{uuid.uuid4()}/roles", headers=w.h())
    r = w.step_up(challenge_id=value)
    assert r.status_code == 400 and r.json()["errors"][0]["field"] == "challenge_id"
    assert not w.of("auth.step_up_failed")


async def test_step_up_on_a_revoked_session_is_401_never_a_challenge() -> None:
    w = await _world()
    await w.rows.revoke(str(w.sessions["tok"].id), reason="logout", now=w.clock.now)
    r = w.step_up(action_class="keys")
    assert r.status_code == 401 and "challenge_id" not in r.json()


async def test_unregistered_class_fails_closed_without_a_challenge() -> None:
    w = await _world()
    sid = str(w.sessions["tok"].id)
    denied = await require_elevation_for(w.auth, sid, "bogus")
    assert denied is not None and denied.status_code == 500
    assert b"challenge_id" not in denied.body
    assert await w.auth.step_up.live_challenge(sid) is None


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="#2304 route slice: the path-gated middleware (`make_read_only_guard`) challenges "
    "before the route's own RBAC; remove this marker when the route slice gates behind it",
)
async def test_challenge_not_issued_to_a_refused_caller() -> None:
    """Contract: a challenge goes only to a caller the operation would otherwise admit, so a
    Manager without `users:write` gets `403 forbidden`, never a challenge (threat model U34)."""
    w = await _world()
    manager = PrincipalSnapshot(
        user_id=w.sessions["tok"].user_id, roles=frozenset({"manager"}), permissions=frozenset()
    )
    app = FastAPI()
    app.include_router(
        make_users_router(
            _Store({"viewer"}, 1), w.audit, _Resolver(manager), _Notifier(), auth=w.auth
        )
    )
    app.middleware("http")(make_read_only_guard(w.auth, w.audit))
    roles = {"roles": ["viewer"]}
    r = TestClient(app).put(f"/users/{uuid.uuid4()}/roles", headers=w.h(), json=roles)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert "challenge_id" not in r.json() and not w.of("auth.step_up_required")


async def test_elevated_owner_self_reset_is_403_forbidden_not_another_challenge() -> None:
    """No step-up cures a self-reset, so the re-sent request must not be challenged again (a
    client holding it would loop). The path-gated middleware still challenges the first send
    until the route slice of #2304 moves the gate behind the route's own checks."""
    c, em, seed, clock, owner = await _build()
    body = {"code": _code(seed, clock), "password": _PW, "action_class": "users"}
    assert c.post("/auth/step-up", headers=_H, json=body).status_code == 200
    r = c.post(f"/users/{owner}/mfa/reset", headers=_H)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert "challenge_id" not in r.json() and "auth.step_up_required" not in em.actions()


async def test_no_password_code_or_request_body_reaches_logs_or_audit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    w = await _world()
    path = f"/users/{uuid.uuid4()}/roles"
    challenge_id = w.client.put(path, headers=w.h(), json={"note": "private-note-7731"}).json()[
        "challenge_id"
    ]
    code = _code(w.seed, w.clock)
    payload = {"code": code, "password": _PW, "challenge_id": challenge_id}
    assert w.client.post("/auth/step-up", headers=w.h(), json=payload).status_code == 200
    recorded = repr(w.audit.calls)
    for secret in (_PW, f"'{code}'", f'"{code}"', "private-note-7731"):
        assert secret not in caplog.text and secret not in recorded


@pytest.mark.parametrize(
    ("session", "wired", "status"),
    [(False, True, 401), (True, False, 503), (True, True, 403)],
    ids=["no-session", "step-up-not-wired", "challenged"],
)
async def test_handler_gate_challenges_only_a_session_it_can_challenge(
    session: bool, wired: bool, status: int
) -> None:
    """A handler that resolved its caller itself (the recorder purge) refuses without a challenge
    when there is no session to challenge or no step-up service to issue one (#2304)."""
    w = await _world()
    w.auth.step_up_is_active = wired
    sid = w.sessions["tok"].id if session else None
    denied = await require_session_elevation(w.auth, sid, "keys")
    assert denied is not None and denied.status_code == status
    assert (b"challenge_id" in denied.body) is (status == 403)
    assert len(w.of("auth.step_up_required")) == (status == 403)
