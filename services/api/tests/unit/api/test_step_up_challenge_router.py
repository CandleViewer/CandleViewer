"""#2304 over HTTP: every `403 step_up_required` is a challenge for the one request it refused,
and `POST /auth/step-up` answers the live one by its id.

The harness route stands in for the routes the route slice of #2304 wires: it validates its
request, then calls the route-level gate. `POST /trading/kill-switch` has E39's shape (not
mounted yet).
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
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.mfa_service import MfaService
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind, SessionRecord
from candleviewer.auth.step_up import StepUpService
from candleviewer.auth.totp import generate_code, time_step_for
from candleviewer.statechart.bindings import b16_session
from tests.contract.test_step_up_challenge_contract import (
    _PROBLEM,
    _SPEC,
    _STEP_UP_REQUIRED_BODY,
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
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository

_IDEM = str(uuid.UUID(int=0x5F0C6B1E2D3A4C4B9E8F7A6B5C4D3E2F))  # the held request's Idempotency-Key
_RELEASE = {"engaged": False, "scope": "global"}


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
        return {"Authorization": f"Bearer {who}", "Idempotency-Key": _IDEM}

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
        if not body["engaged"]:  # release needs a no-grace step-up
            denied = await require_elevation_for(auth, _sid(request), "killswitch")
            if denied is not None:
                return denied
        executed.append(body)
        return {"ok": True}

    return _World(TestClient(app), audit, seed, clock, auth, rows, sessions, executed)


async def test_refusal_is_a_challenge_for_the_refused_request() -> None:
    w = await _world()
    denied = w.send(_RELEASE)
    assert denied.status_code == 403
    body = denied.json()
    _validator(_SPEC, _STEP_UP_REQUIRED_BODY).validate(body)  # provider side (C-6.2)
    assert body["action_class"] == "killswitch"
    assert uuid.UUID(body["challenge_id"]).version == 4
    expires = datetime.fromisoformat(body["challenge_expires_at"])
    assert expires == w.clock.now + timedelta(minutes=5)
    (required,) = w.of("auth.step_up_required")
    assert required["object_id"] == body["challenge_id"]
    assert w.executed == []


@pytest.mark.parametrize("stale", ["expired", "unknown", "superseded"])
async def test_stale_challenge_id_is_400_challenge_expired(stale: str) -> None:
    """AC "Challenge expiry": a challenge issued more than 5 minutes ago is refused 400."""
    w = await _world()
    challenge_id = w.send(_RELEASE).json()["challenge_id"]
    if stale == "expired":
        w.clock.now += timedelta(minutes=5, seconds=1)
    elif stale == "unknown":
        challenge_id = str(uuid.uuid4())
    else:
        w.send({"engaged": False, "scope": "account"})
    r = w.step_up(challenge_id=challenge_id)
    assert r.status_code == 400 and r.json()["errors"][0]["rule"] == "challenge_expired"
    _validator(_SPEC, _ref(_PROBLEM)).validate(r.json())
    assert not w.of("auth.step_up_failed")


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
