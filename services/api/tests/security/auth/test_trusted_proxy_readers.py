"""#2275: behind the configured trusted proxy, `request.client` is the proxy. The SR-015 sign-in
throttle, the minted session's `ip` and the invite throttle and audit (C-2.9) use the hop MeshOnly
admitted instead, and a loopback peer that is not the proxy cannot name one. Real `create_app()`
and auth services over in-memory fakes, fixed clock, no network; `_Peer` stands in for TCP.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from starlette.types import ASGIApp, Receive, Scope, Send

import candleviewer.app as appmod
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind
from candleviewer.auth.service import AuthService
from candleviewer.auth.totp import generate_code, time_step_for
from tests.security.auth.test_csrf_double_submit import _ORIGIN, _PW, _Audit, _Clock, _Identity
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.auth.test_invite_service import FakeRepo

_PROXY = "127.0.0.1"
_OTHER = "127.0.0.2"  # a local process that is not the configured proxy
_CLIENT, _NEIGHBOUR = "100.64.1.2", "100.64.1.3"
_SIGN_IN_BUDGET = 20  # `PerIpLoginThrottle` default (SR-015)
_INVITE_BUDGET = 10  # `InviteService`'s per-address throttle
_UNKNOWN_INVITE = "unknown-invite-token-0123456789"

#: (TCP peer, the `X-Forwarded-For` it sends, the address every reader must record).
SOURCES = [
    pytest.param(_PROXY, f"203.0.113.9, {_CLIENT}", _CLIENT, id="client-via-trusted-proxy"),
    pytest.param(_OTHER, _NEIGHBOUR, _OTHER, id="other-loopback-peer-names-a-client"),
]


class _Peer:
    """Stands in for the TCP layer: each request arrives from `host`, as uvicorn reports it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.host = _PROXY

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            scope = {**scope, "client": (self.host, 50000)}
        await self.app(scope, receive, send)


@dataclass
class _Proxied:
    client: TestClient
    peer: _Peer
    ctx: Any
    audit: _Audit
    clock: _Clock
    seed: bytes

    def _from(self, peer: str, forwarded_for: str) -> dict[str, str]:
        self.peer.host = peer
        return {"X-Forwarded-For": forwarded_for}

    def login(self, peer: str, forwarded_for: str, identifier: str = "basiltt") -> Response:
        body = {"identifier": identifier, "password": _PW}
        r: Response = self.client.post(
            "/auth/login", json=body, headers=self._from(peer, forwarded_for)
        )
        return r

    def verify(self, peer: str, forwarded_for: str, mfa_token: str) -> Response:
        code = generate_code(self.seed, time_step_for(self.clock.now.timestamp()))
        body = {"mfa_token": mfa_token, "method": "totp", "code": code}
        headers = self._from(peer, forwarded_for)
        r: Response = self.client.post("/auth/mfa/verify", json=body, headers=headers)
        return r

    def inspect_invite(self, peer: str, forwarded_for: str) -> Response:
        r: Response = self.client.get(
            f"/invites/{_UNKNOWN_INVITE}", headers=self._from(peer, forwarded_for)
        )
        return r

    def session_ip(self, access_token: str) -> object:
        portal = self.client.portal
        assert portal is not None
        record = portal.call(self.ctx.auth.sessions.authenticate_access_token, access_token)
        return record.ip


@pytest.fixture
def proxied(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Proxied]:
    monkeypatch.setenv("CV_ALLOWED_ORIGINS", _ORIGIN)
    monkeypatch.setenv("CV_MESH_CIDRS_CSV", "100.64.0.0/10")
    monkeypatch.setenv("CV_MESH_TRUSTED_PROXY_HEADER", "x-forwarded-for")
    monkeypatch.setenv("CV_MESH_TRUSTED_PROXY_ADDRESS", _PROXY)
    clock, users, mfa_repo = _Clock(), FakeUserRepository(), FakeMfaRepository()
    pepper = os.urandom(8).hex()
    auth = AuthService(
        users,
        pepper=pepper,
        mfa_repository=mfa_repo,
        totp_encryption_key=os.urandom(32),
        recovery_code_hmac_key=os.urandom(32),
        session_repository=FakeSessionRepository(),
        clock=clock,
        invite_repository=FakeRepo(),
    )
    monkeypatch.setattr(appmod, "build_auth_service", lambda *_a, **_k: auth)
    monkeypatch.setattr(appmod, "build_identity_provider", lambda _s: _Identity())
    app = appmod.create_app(auth_clock=clock)
    ctx = app.state.app_context
    audit = _Audit()
    ctx.audit._writer = audit
    peer = _Peer(app)
    with TestClient(peer, base_url=_ORIGIN) as client:
        portal = client.portal
        assert portal is not None
        portal.call(ctx.auth.start, ctx)
        user = make_user(password_hash=portal.call(Hasher(pepper=pepper).hash, _PW))
        users.add(user)
        mfa = ctx.auth.mfa
        enrol = MfaEnrollRequest(method=MfaMethodKind.TOTP, label="")
        method = portal.call(lambda: mfa.enroll(str(user.id), enrol, account_name="o")).method_id
        seed = mfa._encryptor.decrypt(mfa_repo.methods[str(method)].secret_enc)
        code = generate_code(seed, time_step_for(clock.now.timestamp()) - 1)
        portal.call(lambda: mfa.confirm_enrollment(str(user.id), method_id=str(method), code=code))
        yield _Proxied(client, peer, ctx, audit, clock, seed)


@pytest.mark.parametrize(("peer", "forwarded_for", "recorded"), SOURCES)
def test_sign_in_throttle_keys_on_the_admitted_address(
    proxied: _Proxied, peer: str, forwarded_for: str, recorded: str
) -> None:
    """SR-015: a client that spends its budget through the proxy throttles only itself."""
    for _ in range(_SIGN_IN_BUDGET):
        assert proxied.login(peer, forwarded_for, identifier="nobody").status_code == 401
    assert proxied.login(peer, forwarded_for).status_code == 401  # its own bucket is spent
    assert proxied.audit.of("auth.login_failed")[-1]["actor_ip"] == recorded
    neighbour = proxied.login(_PROXY, f"203.0.113.7, {_NEIGHBOUR}")
    assert neighbour.status_code == 200, neighbour.text


@pytest.mark.parametrize(("peer", "forwarded_for", "recorded"), SOURCES)
def test_minted_session_records_the_admitted_address(
    proxied: _Proxied, peer: str, forwarded_for: str, recorded: str
) -> None:
    challenge = proxied.login(peer, forwarded_for)
    verified = proxied.verify(peer, forwarded_for, challenge.json()["mfa_token"])
    assert verified.status_code == 200, verified.text
    assert proxied.session_ip(verified.json()["tokens"]["access_token"]) == recorded
    assert proxied.audit.of("auth.session_created")[-1]["actor_ip"] == recorded


@pytest.mark.parametrize(("peer", "forwarded_for", "recorded"), SOURCES)
def test_invite_throttle_and_audit_use_the_admitted_address(
    proxied: _Proxied, peer: str, forwarded_for: str, recorded: str
) -> None:
    for _ in range(_INVITE_BUDGET):
        assert proxied.inspect_invite(peer, forwarded_for).status_code == 404
    assert proxied.inspect_invite(peer, forwarded_for).status_code == 429
    assert {r["actor_ip"] for r in proxied.audit.of("users.invite_rejected")} == {recorded}
    assert proxied.inspect_invite(_PROXY, f"203.0.113.7, {_NEIGHBOUR}").status_code == 404
