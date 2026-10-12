"""#2259: a WS socket never outlives the access token it authenticated with.

Composed path: the real `create_app()` -> `_session_authenticator` -> real
`AuthService` / `SessionService` over the in-memory `FakeSessionRepository` ->
the real `/ws` gateway. Only time is faked: one fake instant drives the session
service and the gateway's monotonic and wall clocks. Those two clocks go into
`make_ws_router`, which `create_app()` does not expose. Every receive is
bounded (`_recv`), so a socket that outlives its token fails fast, not hangs.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer import app as app_module
from candleviewer.auth.models import MintedSession
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.service import AuthService
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL
from candleviewer.ws import gateway
from candleviewer.ws.metrics import AUTH_FAILURE_REASONS, cv_ws_auth_failures_total
from candleviewer.ws.permissions import ConnectionRegistry
from candleviewer.ws.revocation import RevocationHub
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.ws.test_lifecycle_socket import _closed, _recv, _recv_type

_T0 = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_JSON = ["cv.v1.json"]
_USER = uuid.uuid4()


def _ms(at: datetime) -> int:
    return (at - _EPOCH) // timedelta(milliseconds=1)


class _Clock:
    """One fake instant behind every clock: the session service's `datetime`,
    the gateway's monotonic seconds and its wall-clock epoch ms."""

    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return (self.now - _T0).total_seconds()

    def wall_ms(self) -> int:
        return _ms(self.now)


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


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Stack]:
    clock = _Clock()
    auth = AuthService(session_repository=FakeSessionRepository(), clock=clock)
    monkeypatch.setattr(app_module, "build_auth_service", lambda *_a, **_k: auth)
    monkeypatch.setattr(
        app_module,
        "make_ws_router",
        functools.partial(
            gateway.make_ws_router, clock=clock.monotonic, wall_ms=clock.wall_ms, tick_s=0.005
        ),
    )
    app = app_module.create_app()
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
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


def _bare_gateway(result: Any, clock: _Clock) -> TestClient:
    """A bare `/ws` router whose authenticator returns `result` verbatim."""

    async def authenticate(_token: str) -> Any:
        return result

    async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
        return PrincipalSnapshot(uid, frozenset(), frozenset())

    app = FastAPI()
    app.include_router(
        gateway.make_ws_router(
            authenticate=authenticate,
            registry=ConnectionRegistry(resolve, clock.wall_ms),
            revocation_hub=RevocationHub(),
            clock=clock.monotonic,
            wall_ms=clock.wall_ms,
            tick_s=0.005,
        )
    )
    return TestClient(app)


def _failures(reason: str) -> float:
    value: float = cv_ws_auth_failures_total.labels(reason=reason)._value.get()
    return value


@pytest.mark.parametrize("left", [timedelta(0), timedelta(seconds=-30)], ids=["now", "past"])
def test_gateway_refuses_a_token_expired_by_its_own_clock(left: timedelta) -> None:
    clock = _Clock()
    before = _failures("token_expired")
    client = _bare_gateway(("sess", _USER, clock.now + left), clock)
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
    client = _bare_gateway(result, clock)
    with client, client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        bye = _open(ws, "any")  # never auth_ok, never a default lifetime
        code = _closed(ws)
    assert (bye["t"], bye["p"]["reason"], code) == ("bye", "internal_error", 1011)


def test_expiry_is_floored_to_the_ms_and_honours_the_utc_offset() -> None:
    clock = _Clock()
    plus5 = timezone(timedelta(hours=5))
    expires = (_T0 + timedelta(minutes=10, microseconds=999)).astimezone(plus5)
    client = _bare_gateway(("sess", _USER, expires), clock)
    with client, client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        ok = _open(ws, "any")
    assert ok["p"]["token_expires_at_ms"] == _ms(_T0 + timedelta(minutes=10))
