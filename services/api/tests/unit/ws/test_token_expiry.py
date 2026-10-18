"""#2259: a WS socket never outlives the access token it authenticated with.

Composed path: the real `create_app()` -> `_session_authenticator` -> real
`AuthService` / `SessionService` over the in-memory `FakeSessionRepository` ->
the real `/ws` gateway. Only time is faked: one fake instant drives the session
service and the gateway's monotonic and wall clocks. Those two clocks go into
`make_ws_router`, which `create_app()` does not expose. Every receive is
bounded (`_recv`), so a socket that outlives its token fails fast, not hangs.
"""

from __future__ import annotations

import asyncio
import functools
import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer import app as app_module
from candleviewer.auth.models import MintedSession
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.service import AuthService
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL
from candleviewer.settings import Settings
from candleviewer.ws import gateway
from candleviewer.ws.metrics import (
    AUTH_FAILURE_REASONS,
    cv_ws_auth_failures_total,
    cv_ws_closes_total,
)
from candleviewer.ws.permissions import ConnectionRegistry
from candleviewer.ws.revocation import RevocationHub
from tests.unit.auth.auth_fakes import FullUsers
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.ws.test_lifecycle_socket import _closed, _no_sleep, _recv, _recv_type

_T0 = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_JSON = ["cv.v1.json"]
_USER = uuid.uuid4()
_ORIGIN = "http://testserver"  # §2.5: allow-listed and sent on every upgrade


def _ms(at: datetime) -> int:
    return (at - _EPOCH) // timedelta(milliseconds=1)


class _Clock:
    """One fake instant behind every clock: the session service's `datetime`,
    the gateway's monotonic seconds and its wall-clock epoch ms. `wall_step`
    moves only the wall clock, like an NTP step or a resume."""

    def __init__(self) -> None:
        self.now = _T0
        self.wall_step = timedelta(0)

    def __call__(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return (self.now - _T0).total_seconds()

    def wall_ms(self) -> int:
        return _ms(self.now + self.wall_step)


class _Stack:
    def __init__(self, client: TestClient, clock: _Clock, auth: AuthService) -> None:
        self.client, self.clock, self.auth = client, clock, auth

    def mint(self, **kw: Any) -> MintedSession:
        assert self.client.portal is not None
        minted: MintedSession = self.client.portal.call(
            lambda: self.auth.sessions.mint(str(_USER), **kw)
        )
        return minted

    def refresh(self, refresh_token: str) -> MintedSession:
        """E09 rotation, as the client does over REST before re-`auth`."""
        assert self.client.portal is not None
        outcome = self.client.portal.call(lambda: self.auth.sessions.refresh(refresh_token))
        minted: MintedSession = outcome.minted
        return minted


@pytest.fixture(params=[False, True], ids=["flag_off", "flag_on"])
def stack(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Iterator[_Stack]:
    """The composed path, with `CV_WS_BACKPRESSURE_ENABLED` off and on (#412 S2a)."""
    clock = _Clock()
    auth = AuthService(session_repository=FakeSessionRepository(), clock=clock)
    cast(Any, auth)._repository = FullUsers()  # #2295: the WS classifies every session
    monkeypatch.setattr(app_module, "build_auth_service", lambda *_a, **_k: auth)
    monkeypatch.setattr(
        app_module,
        "make_ws_router",
        functools.partial(
            gateway.make_ws_router, clock=clock.monotonic, wall_ms=clock.wall_ms, tick_s=0.005
        ),
    )
    app = app_module.create_app(
        Settings(allowed_origins=_ORIGIN, ws_backpressure_enabled=request.param)
    )
    with TestClient(app, client=("127.0.0.1", 50000), headers={"origin": _ORIGIN}) as client:
        assert client.portal is not None
        client.portal.call(auth.start, app.state.app_context)
        yield _Stack(client, clock, auth)


def _open(ws: Any, token: str) -> dict[str, Any]:
    """`hello` -> `welcome`, then one `auth`; returns the reply to the `auth`."""
    ws.send_json({"t": "hello", "id": "h", "p": {}})
    assert _recv(ws)["t"] == "welcome"
    ws.send_json({"t": "auth", "id": "a", "p": {"access_token": token}})
    return _recv(ws)


def _advance(ws: Any, clock: _Clock, to: datetime) -> None:
    """Move the fake clock to `to` in 30 s steps, pinging at each step so the
    45 s heartbeat timeout never fires. Each pong proves the socket still serves."""
    while clock.now < to:
        clock.now = min(to, clock.now + timedelta(seconds=30))
        ws.send_json({"t": "ping", "id": "keepalive"})
        _recv_type(ws, "pong")


def _expire_at(ws: Any, clock: _Clock, expiry: datetime) -> tuple[dict[str, Any], int]:
    """Still served 1 ms before `expiry`; at `expiry` -> (`bye`, close code)."""
    _advance(ws, clock, expiry - timedelta(milliseconds=1))
    clock.now = expiry
    bye = _recv_type(ws, "bye")
    return bye, _closed(ws)


# -- composed path: create_app() + the real session service ------------------------------------


def test_auth_ok_reports_the_real_expiry_of_a_token_with_one_minute_left(stack: _Stack) -> None:
    minted = stack.mint()
    real_expiry = minted.issued_at + ACCESS_TOKEN_TTL
    stack.clock.now = real_expiry - timedelta(minutes=1)
    with stack.client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        ok = _open(ws, minted.access_token)
    assert ok["t"] == "auth_ok", ok
    reported = ok["p"]["token_expires_at_ms"]
    # Within 1 s of the real expiry and never after it (the old 12 min default
    # counted from the WS auth overshot it by 660 s).
    assert _ms(real_expiry) - 1000 <= reported <= _ms(real_expiry)


def test_already_expired_token_is_refused_and_nothing_is_served(stack: _Stack) -> None:
    minted = stack.mint()
    stack.clock.now = minted.issued_at + ACCESS_TOKEN_TTL  # the first refused instant
    with stack.client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        err = _open(ws, minted.access_token)
        assert (err["t"], err["p"]["code"]) == ("err", "auth_failed")
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": ["book.BTCUSDT.50"]}})
        assert _recv(ws)["p"]["code"] == "not_authenticated"


def test_socket_closes_token_expired_4401_at_the_real_expiry(stack: _Stack) -> None:
    minted = stack.mint()
    real_expiry = minted.issued_at + ACCESS_TOKEN_TTL
    stack.clock.now = real_expiry - timedelta(minutes=1)
    with stack.client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        assert _open(ws, minted.access_token)["t"] == "auth_ok"
        bye, code = _expire_at(ws, stack.clock, real_expiry)
    assert (bye["p"]["reason"], bye["p"]["code"], code) == ("token_expired", 4401, 4401)


def test_in_place_reauth_takes_the_new_tokens_real_expiry(stack: _Stack) -> None:
    first = stack.mint()
    with stack.client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        ok = _open(ws, first.access_token)
        assert ok["p"]["token_expires_at_ms"] == _ms(first.issued_at + ACCESS_TOKEN_TTL)
        _advance(ws, stack.clock, _T0 + timedelta(minutes=10))
        second = stack.refresh(first.refresh_token)
        second_expiry = second.issued_at + ACCESS_TOKEN_TTL
        # Re-auth one minute after the refresh: the expiry is the new token's,
        # not "12 minutes from this frame".
        _advance(ws, stack.clock, _T0 + timedelta(minutes=11))
        ws.send_json({"t": "auth", "id": "re", "p": {"access_token": second.access_token}})
        ok = _recv_type(ws, "auth_ok")
        assert ok["p"]["session_id"] == str(second.session_id)
        assert ok["p"]["token_expires_at_ms"] == _ms(second_expiry)
        # Served past the first token's expiry, closed at the second's.
        bye, code = _expire_at(ws, stack.clock, second_expiry)
    assert (bye["p"]["reason"], code) == ("token_expired", 4401)


def test_expiry_is_capped_by_the_sessions_absolute_lifetime(stack: _Stack) -> None:
    # A rotated session 5 min before its 12 h absolute end: the 12 min access
    # TTL would outlive the session, which the service refuses from `absolute` on.
    absolute = _T0 + timedelta(minutes=5)
    minted = stack.mint(expires_at=absolute)
    with stack.client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        ok = _open(ws, minted.access_token)
        assert ok["p"]["token_expires_at_ms"] == _ms(absolute)
        bye, code = _expire_at(ws, stack.clock, absolute)
    assert (bye["p"]["reason"], code) == ("token_expired", 4401)


# -- gateway contract: whatever the injected authenticator reports -----------------------------


class _Gate:
    """ASGI wrapper that can hold every outbound WS frame. While it is held the
    writer waits inside `send_text`, like one whose client stopped reading."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.hold: asyncio.Event | None = None

    def block(self) -> None:
        self.hold = asyncio.Event()

    def release(self) -> None:
        if self.hold is not None:
            self.hold.set()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        async def gated(message: Any) -> None:
            if message["type"] == "websocket.send" and self.hold is not None:
                await self.hold.wait()
            await send(message)

        await self.app(scope, receive, gated)


@dataclass
class _Bare:
    client: TestClient
    hub: gateway.GatewayHub
    revocation: RevocationHub
    gate: _Gate

    def call(self, fn: Callable[[], Any]) -> Any:
        """Run `fn` in the app's event loop. Nothing else runs there until it
        returns, so the writer cannot interleave with what `fn` does."""
        assert self.client.portal is not None
        return self.client.portal.call(fn)


def _bare_gateway(result: Any, clock: _Clock, *, tick_s: float = 0.005, audit: Any = None) -> _Bare:
    """A bare `/ws` router whose authenticator returns `result` verbatim, or
    awaits `result(token)` when `result` is an authenticator itself."""

    async def authenticate(token: str) -> Any:
        return await result(token) if callable(result) else result

    async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
        # A role, so `system` frames reach it: none reach a principal without one (SR-188).
        return PrincipalSnapshot(uid, frozenset({"viewer"}), frozenset())

    hub, revocation = gateway.GatewayHub(), RevocationHub()
    app = FastAPI()
    app.include_router(
        gateway.make_ws_router(
            authenticate=authenticate,
            registry=ConnectionRegistry(resolve, clock.wall_ms),
            revocation_hub=revocation,
            hub=hub,
            audit=audit,
            clock=clock.monotonic,
            wall_ms=clock.wall_ms,
            tick_s=tick_s,
            allowed_origins=frozenset({_ORIGIN}),
        )
    )
    gate = _Gate(app)
    return _Bare(TestClient(gate, headers={"origin": _ORIGIN}), hub, revocation, gate)


def _failures(reason: str) -> float:
    value: float = cv_ws_auth_failures_total.labels(reason=reason)._value.get()
    return value


def _closes(reason: str) -> float:
    value: float = cv_ws_closes_total.labels(reason=reason)._value.get()
    return value


@pytest.mark.parametrize("left", [timedelta(0), timedelta(seconds=-30)], ids=["now", "past"])
def test_gateway_refuses_a_token_expired_by_its_own_clock(left: timedelta) -> None:
    clock = _Clock()
    before = _failures("token_expired")
    client = _bare_gateway(("sess", _USER, clock.now + left), clock).client
    with client, client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        err = _open(ws, "any")
        assert (err["t"], err["p"]["code"]) == ("err", "auth_failed")
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": ["book.BTCUSDT.50"]}})
        assert _recv(ws)["p"]["code"] == "not_authenticated"
    assert "token_expired" in AUTH_FAILURE_REASONS
    assert _failures("token_expired") == before + 1


@pytest.mark.parametrize(
    "result",
    [
        ("sess", _USER),
        ("sess", _USER, None),
        ("sess", _USER, datetime(2026, 10, 12, 9, 12)),  # naive on purpose
    ],
    ids=["no_expiry", "none_expiry", "naive_expiry"],
)
def test_authenticator_without_a_tz_aware_expiry_is_a_server_fault_1011(result: Any) -> None:
    clock = _Clock()
    client = _bare_gateway(result, clock).client
    with client, client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        bye = _open(ws, "any")  # never auth_ok, never a default lifetime
        code = _closed(ws)
    assert (bye["t"], bye["p"]["reason"], code) == ("bye", "internal_error", 1011)


def test_expiry_is_floored_to_the_ms_and_honours_the_utc_offset() -> None:
    clock = _Clock()
    plus5 = timezone(timedelta(hours=5))
    expires = (_T0 + timedelta(minutes=10, microseconds=999)).astimezone(plus5)
    client = _bare_gateway(("sess", _USER, expires), clock).client
    with client, client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        ok = _open(ws, "any")
    assert ok["p"]["token_expires_at_ms"] == _ms(_T0 + timedelta(minutes=10))


# -- a busy socket still expires (#2259 review: watchdog starvation) ---------------------------

#: The writer's idle tick in these tests: an hour, so a deadline can only fire from the
#: check before each dequeue and send, never from an idle poll (the old code's only check).
_NO_IDLE_TICK_S = 3600.0
_FEED_PERIOD = timedelta(milliseconds=10)  # 100 Hz on the fake clock
#: A role-neutral `system` frame (an unknown `kind` would reach nobody, SR-188).
_TICK = {"kind": "notice", "message": "tick"}


def _broadcast(gw: _Bare, ws: Any, clock: _Clock) -> dict[str, Any]:
    """Advance one feed period, broadcast one `system` frame, return the next frame."""
    clock.now += _FEED_PERIOD
    gw.call(lambda: gw.hub.broadcast_system(_TICK))
    return _recv(ws)


def test_busy_socket_expires_with_bye_instead_of_the_first_frame_at_the_expiry() -> None:
    clock = _Clock()
    expiry = _T0 + timedelta(seconds=1)
    gw = _bare_gateway(("sess", _USER, expiry), clock, tick_s=_NO_IDLE_TICK_S)
    data: list[dict[str, Any]] = []
    with gw.client, gw.client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        assert _open(ws, "any")["t"] == "auth_ok"
        while (frame := _broadcast(gw, ws, clock))["t"] != "bye":
            data.append(frame)
            assert len(data) < 150, "the socket kept serving past its token expiry"
        code = _closed(ws)
    assert (frame["p"]["reason"], code) == ("token_expired", 4401)
    # Frames at 10 ms .. 990 ms are served; the one stamped at the expiry is not.
    assert len(data) == 99
    assert max(f["ts"] for f in data) < _ms(expiry)


def test_expiry_drops_the_queued_backlog_and_sends_bye_next() -> None:
    clock = _Clock()
    expiry = _T0 + timedelta(minutes=1)
    gw = _bare_gateway(("sess", _USER, expiry), clock, tick_s=_NO_IDLE_TICK_S)
    with gw.client, gw.client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        assert _open(ws, "any")["t"] == "auth_ok"

        def burst_then_expire() -> None:
            for _ in range(gateway.OUTBOUND_QUEUE_MAX - 1):
                gw.hub.broadcast_system(_TICK)
            clock.now = expiry

        gw.call(burst_then_expire)
        bye = _recv(ws)  # not one of the 1023 queued frames
        assert (bye["t"], bye["p"]["reason"]) == ("bye", "token_expired"), bye
        assert _closed(ws) == 4401


def test_revocation_drops_the_queued_backlog_and_sends_bye_next() -> None:
    clock = _Clock()
    gw = _bare_gateway(("sess", _USER, _T0 + ACCESS_TOKEN_TTL), clock, tick_s=_NO_IDLE_TICK_S)
    with gw.client, gw.client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        assert _open(ws, "any")["t"] == "auth_ok"

        async def burst_then_revoke() -> int:
            for _ in range(gateway.OUTBOUND_QUEUE_MAX - 1):
                gw.hub.broadcast_system(_TICK)
            return await gw.revocation.revoke("sess")

        assert gw.call(burst_then_revoke) == 1
        bye = _recv(ws)
        assert (bye["t"], bye["p"]["reason"]) == ("bye", "session_revoked"), bye
        assert _closed(ws) == 4401


def test_an_enrolment_refused_re_auth_drops_the_queued_backlog_and_sends_bye_next() -> None:
    """#2295 (§4.3): a refused re-`auth` ends the socket's identity, so its close is sealed: the
    `bye` is the next frame, never one queued for the identity the socket held until then."""
    clock, presented = _Clock(), list[str]()
    gw: _Bare | None = None

    async def authenticate(token: str) -> Any:
        presented.append(token)
        if len(presented) == 1:  # the first `auth`: a full session
            return ("sess", _USER, _T0 + ACCESS_TOKEN_TTL)
        assert gw is not None
        for _ in range(gateway.OUTBOUND_QUEUE_MAX - 1):  # queued for the earlier identity
            gw.hub.broadcast_system(_TICK)
        raise gateway.AuthRefused("mfa_enrollment_required")

    gw = _bare_gateway(authenticate, clock, tick_s=_NO_IDLE_TICK_S)
    with gw.client, gw.client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        assert _open(ws, "full")["t"] == "auth_ok"
        ws.send_json({"t": "auth", "id": "a2", "p": {"access_token": "password-only"}})
        bye = _recv(ws)
        assert (bye["t"], bye["p"]["reason"]) == ("bye", "mfa_enrollment_required"), bye
        assert _closed(ws) == 4403


def test_expiry_during_a_close_under_way_still_drops_the_backlog() -> None:
    clock = _Clock()
    expiry = _T0 + timedelta(minutes=1)
    gw = _bare_gateway(("sess", _USER, expiry), clock, tick_s=_NO_IDLE_TICK_S)
    before = _closes("token_expired")
    with capture_logs() as logs:
        with gw.client, gw.client.websocket_connect("/ws", subprotocols=_JSON) as ws:
            assert _open(ws, "any")["t"] == "auth_ok"

            async def burst_shutdown_then_expire() -> None:
                for _ in range(gateway.OUTBOUND_QUEUE_MAX - 2):
                    gw.hub.broadcast_system(_TICK)
                # A planned shutdown is an ordinary close: its `bye` follows the backlog...
                await gw.hub.shutdown(grace_ms=0, sleep=_no_sleep)
                clock.now = expiry  # ...until the identity ends while it drains.

            gw.call(burst_shutdown_then_expire)
            bye = _recv(ws)
            assert (bye["t"], bye["p"]["reason"]) == ("bye", "shutdown"), bye
            assert _closed(ws) == 1001
    sealed = [e for e in logs if e["event"] == "ws close sealed"]
    # One tick was in the writer's hand; the other 1021 ticks and the shutdown notice dropped.
    assert [(e["reason"], e["dropped"]) for e in sealed] == [
        ("token_expired", gateway.OUTBOUND_QUEUE_MAX - 2)
    ]
    assert _closes("token_expired") == before + 1


def test_a_forward_wall_clock_step_expires_the_token_on_the_wall_clock() -> None:
    # An NTP step or a resume moves only the wall clock. REST then refuses the
    # token at once, so the socket must not wait for the monotonic deadline.
    clock = _Clock()
    gw = _bare_gateway(("sess", _USER, _T0 + ACCESS_TOKEN_TTL), clock)
    with gw.client, gw.client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        assert _open(ws, "any")["t"] == "auth_ok"
        clock.wall_step = ACCESS_TOKEN_TTL  # 0 s elapsed on the monotonic clock
        bye = _recv(ws)
        assert (bye["t"], bye["p"]["reason"]) == ("bye", "token_expired"), bye
        assert _closed(ws) == 4401


@pytest.mark.parametrize("outcome", ["accepted", "refused"])
def test_a_revocation_during_a_reauth_still_closes_with_bye_4401(outcome: str) -> None:
    # The session is revoked while the re-auth awaits the session service. The
    # sealed close must finish (`bye session_revoked` + 4401); the late auth
    # result must not hit the closing lifecycle and fault the socket into 1011.
    clock = _Clock()
    calls: list[str] = []
    gw: _Bare

    async def authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
        calls.append(token)
        if len(calls) == 2:
            await gw.revocation.revoke("sess")
            if outcome == "refused":
                raise PermissionError("revoked")
        return "sess", _USER, _T0 + ACCESS_TOKEN_TTL

    gw = _bare_gateway(authenticate, clock)
    with gw.client, gw.client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        assert _open(ws, "first")["t"] == "auth_ok"
        ws.send_json({"t": "auth", "id": "re", "p": {"access_token": "second"}})
        bye = _recv(ws)
        assert (bye["t"], bye["p"]["reason"]) == ("bye", "session_revoked"), bye
        assert _closed(ws) == 4401


class _SlowAudit:
    """Audit sink whose `emit` yields once, as the real WAL append does."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.written = threading.Event()

    async def emit(self, action: str, **kw: Any) -> None:
        await asyncio.sleep(0)  # a scheduling point, not a wait
        self.records.append({"action": action, **kw})
        self.written.set()


def test_third_failed_auth_is_audited_while_a_close_is_in_flight() -> None:
    # C-2.9: a planned shutdown has queued its `bye`, but the writer is blocked
    # (the client stopped reading). The 3rd failed `auth` that lands meanwhile is
    # still counted and audited; the shutdown close then completes as queued.
    clock = _Clock()
    audit = _SlowAudit()

    async def authenticate(_token: str) -> Any:
        raise PermissionError("bad token")

    gw = _bare_gateway(authenticate, clock, audit=audit)
    before = _failures("rejected")
    with gw.client, gw.client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        assert _open(ws, "bad-1")["p"]["code"] == "auth_failed"
        ws.send_json({"t": "auth", "id": "a2", "p": {"access_token": "bad-2"}})
        assert _recv(ws)["p"]["code"] == "auth_failed"

        async def block_writer_then_shut_down() -> None:
            gw.gate.block()
            await gw.hub.shutdown(grace_ms=0, sleep=_no_sleep)

        gw.call(block_writer_then_shut_down)
        try:
            ws.send_json({"t": "auth", "id": "a3", "p": {"access_token": "bad-3"}})
            assert audit.written.wait(timeout=5.0), "the 3rd failed auth was not audited"
        finally:
            gw.call(gw.gate.release)
        bye = _recv(ws)
        assert (bye["t"], bye["p"]["reason"]) == ("bye", "shutdown"), bye
        assert _closed(ws) == 1001
    assert [(r["action"], r["reason"]) for r in audit.records] == [
        ("auth.login_failed", "ws_auth_failed")
    ]
    assert _failures("rejected") == before + 3
