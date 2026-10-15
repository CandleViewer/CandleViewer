"""E09-Q05 auth chaos. Real `SessionService`, `MfaService`-level TOTP maths, `RevocationHub` and the
real WS gateway router; only the storage seam (in-memory repository) and the clock are faked.

C-13.6 mapping: #10 (datastore outage) -> s1/s1b. Clock drift: C-13.6 #6 is `recv_window` drift
on the exchange adapter and is NOT covered here; s2 is its analogue for TOTP step skew (SR-021).
The remaining scenarios (WS restart, revocation storm, session-store pressure) are auth-specific.
There is no dedicated session sweeper in `candleviewer/auth`; expiry is lazy inside
`SessionService.require_active`, so s5 drives that real path concurrently with live traffic.
T14: no wall-clock asserts, no sleeps; time is an injected clock or a fixed `unix_time`.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from starlette.websockets import WebSocketDisconnect

from candleviewer.auth.errors import SessionNotFound, SessionRevoked
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.session_service import (
    ABSOLUTE_LIFETIME,
    SessionService,
    access_token_expires_at,
)
from candleviewer.auth.totp import generate_code, time_step_for, verify_code
from candleviewer.auth.totp_skew import SKEW_HOLD_S, TotpSkewReporter
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.permissions import ConnectionRegistry
from candleviewer.ws.revocation import CLOSE_TOKEN_EXPIRED, RevocationHub
from tests.chaos.storage import _stack as st
from tests.unit.auth.mfa_fakes import RecordingSystemEvents
from tests.unit.auth.session_fakes import FakeSessionRepository

pytestmark = [pytest.mark.chaos, pytest.mark.integration]
_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
_ORIGIN = "http://testserver"  # `23-ws-protocol.md` §2.5: allow-listed, sent on every upgrade


class _Clock:
    def __init__(self) -> None:
        self.now = _NOW

    def __call__(self) -> datetime:
        return self.now


class _DownableRepo(FakeSessionRepository):
    """Storage seam: every read raises while 'Postgres' is down."""

    def __init__(self) -> None:
        super().__init__()
        self.down = False

    async def _gate(self) -> None:
        if self.down:
            raise ConnectionError("postgres unavailable")

    async def find_by_id(self, session_id: str) -> Any:
        await self._gate()
        return await super().find_by_id(session_id)

    async def find_by_access_token_jti(self, access_token_jti: str) -> Any:
        await self._gate()
        return await super().find_by_access_token_jti(access_token_jti)


def _service(repo: FakeSessionRepository, clock: _Clock | None = None) -> SessionService:
    return SessionService(repo, Hasher(pepper=os.urandom(16).hex()), clock=clock or _Clock())


async def _resolve(uid: uuid.UUID) -> PrincipalSnapshot:
    return PrincipalSnapshot(uid, frozenset({"viewer"}), frozenset({Permission.MARKETDATA_READ}))


def _gateway(svc: SessionService, hub: RevocationHub, clock: _Clock) -> FastAPI:
    async def authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
        rec = await svc.authenticate_access_token(token)  # real service; raises on bad/revoked
        return str(rec.id), uuid.UUID(str(rec.user_id)), access_token_expires_at(rec)

    app = FastAPI()
    reg = ConnectionRegistry(_resolve, lambda: 1)
    # The token's real expiry is read on the session service's clock (#2259).
    app.include_router(
        make_ws_router(
            authenticate=authenticate,
            registry=reg,
            revocation_hub=hub,
            wall_ms=lambda: int(clock.now.timestamp() * 1000),
            allowed_origins=frozenset({_ORIGIN}),
        )
    )
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, headers={"origin": _ORIGIN})


def _auth(ws: Any, token: str, attempts: int = 1) -> dict[str, Any]:
    """`hello` then `attempts` x `auth` (§4.3: a failure closes on the 3rd attempt)."""
    ws.send_json({"t": "hello", "id": "h"})
    assert ws.receive_json()["t"] == "welcome"
    out: dict[str, Any] = {}
    for _ in range(attempts):
        ws.send_json({"t": "auth", "id": "a", "p": {"access_token": token}})
        out = ws.receive_json()
    return out


def test_s1_postgres_outage_fails_closed_at_service_and_gateway_then_recovers() -> None:
    # C-13.6 #10. Real SessionService + real WS gateway over a downable storage seam.
    repo, clock = _DownableRepo(), _Clock()
    svc = _service(repo, clock)
    minted = asyncio.run(svc.mint(str(uuid.uuid4())))
    sid = str(minted.session_id)
    app = _gateway(svc, RevocationHub(), clock)
    with _client(app) as client:
        repo.down = True
        with pytest.raises(ConnectionError):
            asyncio.run(svc.require_active(sid))  # fail closed, never a granted session
        with client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
            bye = _auth(ws, minted.access_token, attempts=3)
            assert (bye["t"], bye["p"]["reason"]) == ("bye", "auth_failed")
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == CLOSE_TOKEN_EXPIRED
        repo.down = False  # recovery needs no manual step
        assert asyncio.run(svc.require_active(sid)).id is not None
        with client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
            assert _auth(ws, minted.access_token)["t"] == "auth_ok"


class _PgBackedRepo(FakeSessionRepository):
    """Seam variant: every session read first touches the REAL Postgres container."""

    async def find_by_id(self, session_id: str) -> Any:
        conn = await asyncpg.connect(st.pg_dsn().replace("+asyncpg", ""), timeout=3)
        try:
            await conn.execute("SELECT 1")
        finally:
            await conn.close()
        return await super().find_by_id(session_id)


async def _pg_reachable() -> bool:
    try:
        conn = await asyncpg.connect(st.pg_dsn().replace("+asyncpg", ""), timeout=3)
    except (OSError, asyncpg.PostgresError, TimeoutError):
        return False
    await conn.close()
    return True


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker stack unavailable")
async def test_s1b_real_postgres_restart_fails_closed_then_recovers() -> None:
    # Integration-only: needs the compose stack (CI `integration` job); skips otherwise.
    if not await _pg_reachable():
        pytest.skip("compose postgres not running")
    repo = _PgBackedRepo()
    svc = _service(repo)
    sid = str((await svc.mint(str(uuid.uuid4()))).session_id)
    assert (await svc.require_active(sid)).id is not None
    await st.compose("stop", "postgres")
    try:
        with pytest.raises((OSError, asyncpg.PostgresError, TimeoutError)):
            await svc.require_active(sid)  # fail closed while Postgres is down
    finally:
        await st.compose("start", "postgres")
    await st.until(_pg_reachable, "postgres recovery", 120)
    assert (await svc.require_active(sid)).id is not None  # recovered, no manual step


def _skew_metric(kind: str) -> float:
    return REGISTRY.get_sample_value("auth_totp_clock_skew_total", {"kind": kind}) or 0.0


async def test_s2_totp_step_skew_pm1_accepted_pm3_rejected_replay_refused() -> None:
    # Analogue of C-13.6 #6 (NOT recv_window drift): SR-021 +-1 step accepted, +-3 rejected. Each
    # rejected skew raises a system event and moves the metric once its hold has elapsed, so the
    # operator can diagnose it without reading logs (#2146).
    secret = bytes(range(1, 21))  # its codes for steps -30..+40 around `server_t` are distinct
    server_t = 1_800_000_000.0
    step = time_step_for(server_t)
    for k in (-1, 1):
        assert verify_code(secret, generate_code(secret, step + k), unix_time=server_t) == step + k
    events = RecordingSystemEvents()
    reporter = TotpSkewReporter(events)
    moved = {kind: _skew_metric(kind) for kind in ("authenticator_behind", "authenticator_ahead")}
    for k in (-3, 3):
        code = generate_code(secret, step + k)
        assert verify_code(secret, code, unix_time=server_t) is None
        reporter.report_rejection([(secret, None)], code, unix_time=server_t)
    assert events.written == []  # held until the matched codes are dead
    await reporter.publish_due(server_t + SKEW_HOLD_S)
    assert [e.details["offset_steps"] for e in events.written] == ["-3", "3"]
    assert all(_skew_metric(kind) == before + 1 for kind, before in moved.items())
    # Replay refusal (SR-021) is enforced by MfaService via the atomic record_time_step; it is
    # covered by tests/unit/auth/test_mfa_service.py::test_verify_reused_code_is_rejected.


def test_s3_gateway_restart_closes_old_sockets_and_requires_reauth_on_new_gateway() -> None:
    clock = _Clock()
    repo = FakeSessionRepository()
    svc = _service(repo, clock)
    minted = asyncio.run(svc.mint(str(uuid.uuid4())))
    old_hub = RevocationHub()
    with _client(_gateway(svc, old_hub, clock)) as old:
        with old.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
            assert _auth(ws, minted.access_token)["t"] == "auth_ok"
            asyncio.run(svc.revoke(str(minted.session_id), reason="logout"))
            assert old.portal is not None
            assert old.portal.call(old_hub.revoke, str(minted.session_id)) == 1
            bye = ws.receive_json()
            assert bye["t"] == "bye" and bye["p"]["code"] == CLOSE_TOKEN_EXPIRED
    # "Restart": a brand-new gateway + hub. The revoked session must not resume.
    with _client(_gateway(svc, RevocationHub(), clock)) as new:
        with new.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
            assert _auth(ws, minted.access_token, attempts=3)["p"]["reason"] == "auth_failed"
        # an unauthenticated frame on the new gateway gets nothing carried over
        with new.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
            ws.send_json({"t": "hello", "id": "h"})
            assert ws.receive_json()["t"] == "welcome"
            ws.send_json({"t": "sub", "id": "s", "p": {"topics": ["book.X"]}})
            assert ws.receive_json()["t"] == "err"


class _Sock:
    def __init__(self) -> None:
        self.frames: list[tuple[dict[str, Any], int]] = []

    async def close(self, bye: dict[str, Any], code: int) -> None:
        self.frames.append((bye, code))


async def test_s4_revocation_storm_every_socket_gets_bye_4401() -> None:
    svc = _service(FakeSessionRepository())
    hub = RevocationHub()
    socks: dict[str, list[_Sock]] = {}
    for _ in range(50):  # 50 managers, 2 sockets each
        sid = str((await svc.mint(str(uuid.uuid4()))).session_id)
        socks[sid] = [_Sock(), _Sock()]
        for s in socks[sid]:
            hub.register(sid, s.close)
    await asyncio.gather(*(svc.revoke(sid, reason="owner_revoked") for sid in socks))
    closed = await asyncio.gather(*(hub.revoke(sid) for sid in socks))
    assert sum(closed) == 100
    for ss in socks.values():
        for s in ss:
            assert s.frames and s.frames[0][1] == 4401 and s.frames[0][0]["t"] == "bye"
    assert await asyncio.gather(*(hub.revoke(sid) for sid in socks)) == [0] * 50  # none survive
    for sid in socks:
        with pytest.raises(SessionRevoked):
            await svc.require_active(sid)


async def test_s5_session_expiry_under_pressure_does_not_block_authentication() -> None:
    clock = _Clock()
    svc = _service(FakeSessionRepository(), clock)
    user = str(uuid.uuid4())
    stale = [await svc.mint(user) for _ in range(200)]
    clock.now = _NOW + ABSOLUTE_LIFETIME + timedelta(seconds=1)  # all 200 are now past expiry
    probe = await svc.mint(user)

    async def expire(sid: str) -> None:
        with pytest.raises(SessionRevoked):  # real lazy-expiry path revokes then refuses
            await svc.require_active(sid)

    async def authenticate() -> None:
        rec = await svc.authenticate_access_token(probe.access_token)
        assert str(rec.id) == str(probe.session_id)

    await asyncio.gather(
        *(expire(str(m.session_id)) for m in stale), *(authenticate() for _ in range(50))
    )
    assert [str(v.id) for v in await svc.list_sessions(user)] == [str(probe.session_id)]
    with pytest.raises(SessionNotFound):
        await svc.authenticate_access_token(stale[0].access_token)  # expired token refused
