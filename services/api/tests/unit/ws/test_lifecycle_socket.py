"""E17-S01 socket-level lifecycle (`23-ws-protocol.md` §2.2, §4, §8.5, §9.1, §9.4).

Every deadline runs on an injected fake clock (`_Clock`); no test sleeps. Every
receive is bounded by `_recv` (worker thread + `Future.result(timeout=5)`) so a
regression fails fast instead of hanging the suite.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import msgpack
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from starlette.websockets import WebSocketDisconnect
from structlog.testing import capture_logs

import candleviewer.ws.gateway as gateway
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.metrics import LOGIN_FAILURE_METHODS
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.observability.correlation import CorrelationMiddleware
from candleviewer.ws.gateway import GatewayHub, make_ws_router
from candleviewer.ws.permissions import ConnectionRegistry
from candleviewer.ws.revocation import RevocationHub

USER = uuid.uuid4()
OTHER = uuid.uuid4()
# Pinned to the UUID from CI run 38844674285: its "bad-" substring is what made the old
# `"bad-" not in repr(records)` assertion flaky (#2760), so this keeps the regression visible.
SESSION = "35aa4bad-7085-44f7-be13-d8c34121772e"
BASE_MS = 1_789_132_262_000
TOKEN_TTL_S = 600
JSON = ["cv.v1.json"]
MSGPACK = ["cv.v1.msgpack"]
# Rejected-token marker for the secrecy assertions. It must contain a character that can never
# occur in hex or UUID text (`z`): a random `session_id`/`request_id` like `35aa4bad-7085-…`
# contains "bad-", which made a `"bad-" not in repr(records)` assertion flaky (#2760).
REJECTED_MARK = "zz-rejected"
#: §2.5: the TestClient's own origin, allow-listed and sent on every upgrade.
ORIGIN = "http://testserver"
_TIMEOUT_S = 5.0


class _Clock:
    """Monotonic seconds, advanced only by the test."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def wall_ms(self) -> int:
        return BASE_MS + int(self.now * 1000)


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.records.append({"action": action, **kw})


class _World:
    def __init__(self, *, max_per_user: int = 8) -> None:
        self.clock = _Clock()
        self.audit = _Audit()
        self.tokens_seen: list[str] = []
        self.hub = GatewayHub(max_per_user=max_per_user)
        self.revocation = RevocationHub()

        async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
            perms = frozenset({Permission.MARKETDATA_READ})
            return PrincipalSnapshot(uid, frozenset({"viewer"}), perms)

        async def authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
            self.tokens_seen.append(token)
            if not token.startswith("good-"):
                raise PermissionError("bad token")
            # S105: "good-other" is a fake test token, not a credential.
            user = OTHER if token == "good-other" else USER  # noqa: S105
            exp_ms = self.clock.wall_ms() + TOKEN_TTL_S * 1000
            return SESSION, user, datetime.fromtimestamp(exp_ms / 1000, tz=UTC)

        self.registry = ConnectionRegistry(resolve, self.clock.wall_ms)
        app = FastAPI()
        app.add_middleware(CorrelationMiddleware)  # E04 `request_id`, as `create_app` mounts it
        app.include_router(
            make_ws_router(
                authenticate=authenticate,
                registry=self.registry,
                revocation_hub=self.revocation,
                allowed_origins=frozenset({ORIGIN}),
                hub=self.hub,
                audit=self.audit,
                clock=self.clock,
                wall_ms=self.clock.wall_ms,
                tick_s=0.005,
                server_version="1.2.3",
                git_sha="a91f0c3",
            )
        )
        self.client = TestClient(app, headers={"origin": ORIGIN})


@pytest.fixture
def world() -> Any:
    w = _World()
    with w.client:
        yield w


def _receive(ws: Any) -> dict[str, Any]:
    """One frame in the negotiated encoding (§2.2): binary MessagePack on `cv.v1.msgpack` (a text
    frame there fails the test), else JSON text."""
    if ws.accepted_subprotocol == "cv.v1.msgpack":
        frame: dict[str, Any] = msgpack.unpackb(ws.receive_bytes())
        return frame
    text_frame: dict[str, Any] = ws.receive_json()
    return text_frame


def _send(ws: Any, frame: dict[str, Any]) -> None:
    if ws.accepted_subprotocol == "cv.v1.msgpack":
        ws.send_bytes(msgpack.packb(frame))
    else:
        ws.send_json(frame)


def _recv(ws: Any) -> dict[str, Any]:
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        frame: dict[str, Any] = pool.submit(_receive, ws).result(timeout=_TIMEOUT_S)
    except FutureTimeout:
        pytest.fail(f"no WS frame within {_TIMEOUT_S}s")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return frame


def _closed(ws: Any) -> int:
    """The close code; fails if a frame arrives instead."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        frame = pool.submit(_receive, ws).result(timeout=_TIMEOUT_S)
    except WebSocketDisconnect as exc:
        return int(exc.code)
    except FutureTimeout:
        pytest.fail("socket neither closed nor sent within the deadline")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    pytest.fail(f"expected close, got {frame}")


def _hello(ws: Any, **p: Any) -> dict[str, Any]:
    _send(ws, {"t": "hello", "id": "c-1", "p": p})
    return _recv(ws)


# S107: "good-1" is a fake test token, not a credential.
def _auth(ws: Any, token: str = "good-1", fid: str = "c-2") -> dict[str, Any]:  # noqa: S107
    _send(ws, {"t": "auth", "id": fid, "p": {"access_token": token}})
    return _recv(ws)


def _recv_type(ws: Any, t: str) -> dict[str, Any]:
    """Next frame of type `t`, skipping unsolicited server pings."""
    for _ in range(10):
        frame = _recv(ws)
        if frame["t"] == t:
            return frame
        assert frame["t"] == "ping", frame
    pytest.fail(f"no {t} frame")


def _advance(ws: Any, world: _World, to: float) -> None:
    """Move the fake clock to `to` in 30 s steps, pinging each step so the
    45 s heartbeat timeout does not fire (the client is alive)."""
    while world.clock.now < to:
        world.clock.now = min(to, world.clock.now + 30.0)
        ws.send_json({"t": "ping", "id": "keepalive"})
        _recv_type(ws, "pong")


def _bye_then_close(ws: Any) -> tuple[dict[str, Any], int]:
    bye = _recv(ws)
    assert bye["t"] == "bye", bye
    return bye, _closed(ws)


# -- negotiation + hello -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "offer", [["cv.v1.msgpack", *JSON], MSGPACK, JSON], ids=["msgpack-first", "msgpack", "json"]
)
def test_happy_path_handshake_welcome_auth_ok_and_system(world: _World, offer: list[str]) -> None:
    """§2.2: `cv.v1.msgpack` whenever it is offered; every frame then goes both ways in it."""
    with world.client.websocket_connect("/ws", subprotocols=offer) as ws:
        assert ws.accepted_subprotocol == offer[0]
        welcome = _hello(ws, clock_ms=BASE_MS - 22)
        assert (welcome["t"], welcome["id"]) == ("welcome", "c-1")
        p = welcome["p"]
        assert p["protocol"] == "cv.v1" and p["encoding"] == offer[0].removeprefix("cv.v1.")
        assert (p["server_version"], p["git_sha"]) == ("1.2.3", "a91f0c3")
        assert p["clock_skew_ms"] == 22 and p["connection_id"].startswith("ws_")
        assert p["limits"]["max_symbols_per_connection"] == 40
        ok = _auth(ws)
        assert (ok["t"], ok["id"]) == ("auth_ok", "c-2")
        assert ok["p"]["roles"] == ["viewer"] and ok["p"]["permissions"] == ["marketdata:read"]
        assert ok["p"]["account_scope"] == [] and ok["p"]["session_id"] == SESSION
        assert ok["p"]["token_expires_at_ms"] == BASE_MS + TOKEN_TTL_S * 1000
        assert ok["p"]["kill_switch"] == {"engaged": False, "scope": "global"}
        _send(ws, {"t": "pong", "id": "s-hb-1"})  # taken silently: the next reply is the sub's
        _send(ws, {"t": "sub", "id": "s", "p": {"topics": [{"ch": "book.BTCUSDT.50"}]}})
        sub_ok = _recv(ws)
        assert (sub_ok["t"], sub_ok["p"]["results"][0]["ok"]) == ("sub_ok", True)
        _send(ws, {"t": "unsub", "id": "u", "p": {"topics": ["system"]}})
        assert _recv(ws)["t"] == "unsub_ok"
        # §6.2: `system` stays attached - the shutdown broadcast still reaches it.
        assert world.client.portal is not None
        world.client.portal.call(lambda: world.hub.shutdown(sleep=_no_sleep))
        notice = _recv(ws)
        assert (notice["t"], notice["ch"], notice["p"]["kind"]) == (
            "d",
            "system",
            "shutdown_notice",
        )


async def _no_sleep(_s: float) -> None:
    return None


@pytest.mark.parametrize("offered", [["cv.v2.json"], []])
def test_no_mutually_supported_subprotocol_closes_1002(world: _World, offered: list[str]) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        with world.client.websocket_connect("/ws", subprotocols=offered) as ws:
            ws.receive_json()
    assert exc.value.code == 1002


def test_anything_before_hello_is_bye_and_1002(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": ["book.BTCUSDT.50"]}})
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], bye["p"]["code"], code) == ("protocol_violation", 1002, 1002)


def test_auth_before_hello_is_a_protocol_error_not_an_auth(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "good-1"}})
        _, code = _bye_then_close(ws)
    assert code == 1002 and world.tokens_seen == []


def test_second_hello_is_a_protocol_violation_err(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        ws.send_json({"t": "hello", "id": "again"})
        err = _recv(ws)
    assert (err["t"], err["p"]["code"]) == ("err", "protocol_violation")


def test_repeated_malformed_frames_close_4400(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        for _ in range(2):
            ws.send_text("not json")
            assert _recv(ws)["p"]["code"] == "frame_malformed"
        ws.send_json({"no_type": 1})
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], code) == ("bad_client", 4400)


def test_unknown_frame_type_after_auth_is_err(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        ws.send_json({"t": "bogus", "id": "x"})
        assert _recv(ws)["p"]["code"] == "frame_malformed"
        ws.send_json({"t": "resync", "id": "r"})  # E17-S03: handled; no `ch` -> malformed
        assert _recv(ws)["p"]["code"] == "frame_malformed"
        ws.send_json({"t": "ping", "id": "p"})
        assert _recv(ws)["t"] == "pong"


# -- auth --------------------------------------------------------------------------------------


def test_token_in_query_string_is_ignored_and_auth_timeout_closes_4401(world: _World) -> None:
    with world.client.websocket_connect("/ws?access_token=good-1", subprotocols=JSON) as ws:
        _hello(ws)
        world.clock.now = 10.0
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], bye["p"]["code"], code) == ("auth_timeout", 4401, 4401)
    assert world.tokens_seen == []  # the URL token never reached the verifier


def test_auth_timeout_does_not_fire_before_10_seconds(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        world.clock.now = 9.999
        ws.send_json({"t": "ping", "id": "p"})
        assert _recv(ws)["t"] == "pong"
        assert _auth(ws)["t"] == "auth_ok"
        world.clock.now = 12.0
        ws.send_json({"t": "ping", "id": "p2"})
        assert _recv(ws)["t"] == "pong"


def test_three_failed_auth_attempts_bye_4401_and_warning_audit(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        for i in range(2):
            err = _auth(ws, f"{REJECTED_MARK}-{i}")
            assert (err["t"], err["p"]["code"]) == ("err", "auth_failed")
        ws.send_json({"t": "auth", "id": "a3", "p": {"access_token": f"{REJECTED_MARK}-2"}})
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], code) == ("auth_failed", 4401)
    assert len(world.audit.records) == 1
    rec = world.audit.records[0]
    assert rec["severity"] == "warning" and rec["reason"] == "ws_auth_failed"
    assert REJECTED_MARK not in repr(rec)  # the token never lands in the audit trail


def test_failed_auth_frames_count_as_ws_failures_not_as_login_failures(world: _World) -> None:
    # #2319: the audited `auth.login_failed` row (`ws_auth_failed`) of a socket is counted by
    # `cv_ws_auth_failures_total`; `auth_login_failures_total` is the /auth routes' failures only.
    read = REGISTRY.get_sample_value
    rejected = {"reason": "rejected"}
    logins = {m: read("auth_login_failures_total", {"method": m}) for m in LOGIN_FAILURE_METHODS}
    ws_failures = read("cv_ws_auth_failures_total", rejected) or 0.0
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        for i in range(2):
            _auth(ws, f"bad-{i}")
        ws.send_json({"t": "auth", "id": "a3", "p": {"access_token": "bad-2"}})
        _bye_then_close(ws)
    assert [r["action"] for r in world.audit.records] == ["auth.login_failed"]
    assert (read("cv_ws_auth_failures_total", rejected) or 0.0) - ws_failures == 3
    after = {m: read("auth_login_failures_total", {"method": m}) for m in LOGIN_FAILURE_METHODS}
    assert after == logins


def test_unauthenticated_frames_get_err_then_close_after_three(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        for _ in range(2):
            ws.send_json({"t": "sub", "id": "s", "p": {"topics": ["book.BTCUSDT.50"]}})
            assert _recv(ws)["p"]["code"] == "not_authenticated"
        ws.send_json({"t": "unsub", "id": "u", "p": {"topics": ["book.BTCUSDT.50"]}})
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], code) == ("not_authenticated", 4401)


# -- re-auth + expiry --------------------------------------------------------------------------


def test_reauth_in_place_preserves_subscriptions_and_sends_no_snapshot(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": [{"ch": "book.BTCUSDT.50"}]}})
        assert _recv(ws)["p"]["results"][0]["ok"] is True
        authz, _, _ = world.registry._conns[USER][0]
        before = set(authz.subs)
        _advance(ws, world, 540.0)  # client refreshes 60 s before expiry
        ws.send_json({"t": "auth", "id": "c-9", "p": {"access_token": "good-2"}})
        ok = _recv_type(ws, "auth_ok")
        assert (ok["t"], ok["id"]) == ("auth_ok", "c-9")
        assert ok["p"]["token_expires_at_ms"] == BASE_MS + (540 + TOKEN_TTL_S) * 1000
        assert world.registry._conns[USER][0][0] is authz and authz.subs == before
        ws.send_json({"t": "ping", "id": "p"})
        assert _recv(ws)["t"] == "pong"  # no snap/sub_ok was emitted in between
        _advance(ws, world, 700.0)  # past the FIRST token's expiry, inside the new one


def test_reauth_as_a_different_user_is_refused(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        err = _auth(ws, "good-other")
        assert (err["t"], err["p"]["code"]) == ("err", "auth_failed")
        assert world.registry._conns[USER][0][0].principal.user_id == USER


def test_failed_reauth_keeps_prior_identity_until_it_expires(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        assert _auth(ws, "bad")["p"]["code"] == "auth_failed"
        ws.send_json({"t": "unsub", "id": "u", "p": {"topics": ["book.BTCUSDT.50"]}})
        assert _recv(ws)["t"] == "unsub_ok"  # still authenticated
        _advance(ws, world, TOKEN_TTL_S - 1.0)
        world.clock.now = float(TOKEN_TTL_S)
        bye = _recv_type(ws, "bye")
    assert bye["p"]["reason"] == "token_expired"


def test_token_expiry_without_reauth_sends_bye_token_expired_4401(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        _advance(ws, world, TOKEN_TTL_S - 0.001)
        world.clock.now = float(TOKEN_TTL_S)
        bye = _recv_type(ws, "bye")
        code = _closed(ws)
    assert (bye["p"]["reason"], bye["p"]["reconnect"], code) == ("token_expired", True, 4401)
    assert not world.registry._conns.get(USER)  # identity no longer served


# -- heartbeats --------------------------------------------------------------------------------


def test_ping_gets_pong_echoing_id_with_server_clock(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        world.clock.now = 1.0
        ws.send_json({"t": "ping", "id": "c-hb-1", "p": {"client_ms": BASE_MS + 988}})
        pong = _recv(ws)
    assert pong == {
        "t": "pong",
        "id": "c-hb-1",
        "ts": BASE_MS + 1000,
        "p": {"server_ms": BASE_MS + 1000, "rtt_hint_ms": 12},
    }


def test_server_sends_unsolicited_ping_after_20s_outbound_silence(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        world.clock.now = 20.0
        ping = _recv(ws)
        assert (ping["t"], ping["p"]["server_ms"]) == ("ping", BASE_MS + 20_000)
        ws.send_json({"t": "pong", "id": ping["id"]})


def test_heartbeat_timeout_closes_after_45s_without_inbound(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        world.clock.now = 20.0
        assert _recv(ws)["t"] == "ping"  # client never answers
        world.clock.now = 45.0
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], code) == ("heartbeat_timeout", 1001)


def test_client_traffic_resets_the_heartbeat_timeout(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        world.clock.now = 19.0
        ws.send_json({"t": "ping", "id": "p"})
        assert _recv(ws)["t"] == "pong"
        world.clock.now = 63.0  # 44 s after the last inbound frame
        ws.send_json({"t": "ping", "id": "p2"})
        assert _recv_type(ws, "pong")["id"] == "p2"


# -- inbound limits ----------------------------------------------------------------------------


def test_inbound_rate_limit_err_then_bye_4429(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)  # frame 1 at t=0
        for i in range(29):
            ws.send_json({"t": "ping", "id": f"p{i}"})
            assert _recv(ws)["t"] == "pong"
        ws.send_json({"t": "ping", "id": "over"})
        err = _recv(ws)
        assert (err["t"], err["p"]["code"]) == ("err", "client_rate_limited")
        ws.send_json({"t": "ping", "id": "over-again"})
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], bye["p"]["retry_after_ms"], code) == (
        "client_rate_limited",
        1000,
        4429,
    )


def test_pong_frames_do_not_count_toward_the_rate_limit(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        for _ in range(40):
            ws.send_json({"t": "pong", "id": "s-hb-1"})
        ws.send_json({"t": "ping", "id": "p"})
        assert _recv(ws)["t"] == "pong"


def test_oversize_inbound_frame_bye_then_1009(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        ws.send_text('{"t":"ping","id":"' + "x" * (256 * 1024) + '"}')
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], code) == ("frame_too_big", 1009)


# -- per-user cap + shutdown + revocation ------------------------------------------------------


def test_ninth_connection_closes_the_oldest_idle_one() -> None:
    w = _World(max_per_user=2)
    with w.client:
        with w.client.websocket_connect("/ws", subprotocols=JSON) as old:
            _hello(old)
            _auth(old)
            with w.client.websocket_connect("/ws", subprotocols=JSON) as busy:
                _hello(busy)
                w.clock.now = 5.0
                _auth(busy)  # most recent inbound -> not the oldest idle
                with w.client.websocket_connect("/ws", subprotocols=JSON) as new:
                    _hello(new)
                    _auth(new)
                    bye, code = _bye_then_close(old)
                    assert (bye["p"]["reason"], code) == ("too_many_connections", 4429)
                    busy.send_json({"t": "ping", "id": "p"})
                    assert _recv(busy)["t"] == "pong"
                    assert len(w.hub.of_user(USER)) == 2


def test_cap_counts_per_user_not_globally() -> None:
    w = _World(max_per_user=1)
    with w.client:
        with w.client.websocket_connect("/ws", subprotocols=JSON) as a:
            _hello(a)
            _auth(a)
            with w.client.websocket_connect("/ws", subprotocols=JSON) as b:
                _hello(b)
                _auth(b, "good-other")
                a.send_json({"t": "ping", "id": "p"})
                assert _recv(a)["t"] == "pong"


def test_planned_shutdown_notice_then_bye_1001(world: _World) -> None:
    waited: list[float] = []

    async def sleep(s: float) -> None:
        waited.append(s)

    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        with world.client.websocket_connect("/ws", subprotocols=JSON) as unauth:
            _hello(ws)
            _auth(ws)
            _hello(unauth)
            assert world.client.portal is not None
            assert not world.hub.shutting_down
            assert (len(world.hub), world.hub.authenticated_count()) == (2, 1)  # the notice's count
            n = world.client.portal.call(
                lambda: world.hub.shutdown(expected_downtime_ms=20_000, sleep=sleep)
            )
            assert world.hub.shutting_down  # uvicorn's `1012` after this is the server's own
            notice = _recv(ws)
            assert notice["p"] == {
                "kind": "shutdown_notice",
                "reason": "deploy",
                "closing_in_ms": 5000,
                "message": "Backend restarting.",
                "expected_downtime_ms": 20_000,
            }
            assert (notice["ch"], notice["s"], notice["e"]) == ("system", 1, "j")
            bye, code = _bye_then_close(ws)
            assert (bye["p"]["reason"], bye["p"]["retry_after_ms"], code) == (
                "shutdown",
                20_000,
                1001,
            )
            ubye, ucode = _bye_then_close(unauth)  # not notified, still closed
            assert (ubye["p"]["reason"], ucode) == ("shutdown", 1001)
    assert n == 1 and waited == [5.0]


def test_session_revocation_closes_through_the_same_bye_path(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        assert world.client.portal is not None
        assert world.client.portal.call(world.revocation.revoke, SESSION) == 1
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], code) == ("session_revoked", 4401)


def test_hub_is_empty_after_every_socket_closes(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        assert len(world.hub) == 1
    for _ in range(100):
        if len(world.hub) == 0:
            break
        world.client.portal.call(_no_sleep, 0)  # type: ignore[union-attr]  # portal set in ctx
    assert len(world.hub) == 0
    assert not world.registry._conns.get(USER)


def test_reauth_with_narrowed_principal_revokes_now_forbidden_subscriptions() -> None:
    w = _World()
    narrowed = {"on": False}
    original = w.registry._resolve

    async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
        if narrowed["on"]:
            return PrincipalSnapshot(uid, frozenset({"viewer"}), frozenset())
        return await original(uid)

    w.registry._resolve = resolve
    with w.client, w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": [{"ch": "book.BTCUSDT.50"}]}})
        assert _recv(ws)["p"]["results"][0]["ok"] is True
        narrowed["on"] = True
        ok = _auth(ws, "good-2")
        assert (ok["t"], ok["p"]["permissions"]) == ("auth_ok", [])
        revoked = _recv(ws)
        assert (revoked["t"], revoked["ch"]) == ("revoked", "book.BTCUSDT.50")


# -- close audit (#2486) ------------------------------------------------------------------------

#: A canonical UUIDv4 the E04 middleware accepts as the upgrade's `request_id`.
REQUEST_ID = "5e0f6a1c-2b7d-4c3e-9f10-7a8b9c0d1e2f"
CLOSED = "ws.connection.closed"


#: Wall-clock bound for `_settle`: a count of loop turns ran out on a loaded machine before the
#: teardown's close audit landed (#2735). Only a hang ever reaches this bound.
_SETTLE_S = 5.0


def _settle(world: _World, done: Callable[[], bool]) -> None:
    """Let the handler's teardown run on the app loop until `done()` (bounded, no sleeps)."""
    deadline = time.monotonic() + _SETTLE_S
    while not done():
        if time.monotonic() > deadline:
            pytest.fail("the connection teardown did not finish")
        world.client.portal.call(_no_sleep, 0)  # type: ignore[union-attr]  # portal set in ctx


def _close_audits(world: _World) -> list[dict[str, Any]]:
    """Wait inside the socket's `with` block: leaving it cancels a teardown still under way."""
    _settle(world, lambda: any(r["action"] == CLOSED for r in world.audit.records))
    return [r for r in world.audit.records if r["action"] == CLOSED]


def test_close_audit_action_is_registered() -> None:
    assert CLOSED in AUDIT_ACTIONS  # `AuditWriter.emit` refuses an unregistered action


def test_client_close_of_an_authenticated_socket_writes_one_info_close_audit(
    world: _World,
) -> None:
    headers = {"x-correlation-id": REQUEST_ID}
    with world.client.websocket_connect("/ws", subprotocols=JSON, headers=headers) as ws:
        _hello(ws)
        assert _auth(ws)["t"] == "auth_ok"
        ws.close(1000)
        (rec,) = _close_audits(world)
    assert (rec["reason"], rec["severity"], rec["outcome"]) == ("client_closed", "info", "success")
    assert (rec["actor_user_id"], rec["session_id"], rec["actor_label"]) == (USER, SESSION, "ws")
    assert rec["object_kind"] == "ws_connection" and rec["object_id"]
    assert rec["request_id"] == REQUEST_ID
    assert "good-1" not in repr(rec)  # never the token


def test_slow_consumer_close_writes_a_warning_close_audit(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        (conn,) = world.hub.of_user(USER)
        world.client.portal.call(conn.evict)  # type: ignore[union-attr]  # portal set in ctx
        bye, _ = _bye_then_close(ws)
        (rec,) = _close_audits(world)
    assert bye["p"]["reason"] == "slow_consumer"
    assert (rec["reason"], rec["severity"]) == ("slow_consumer", "warning")


def test_failed_reauths_on_an_authenticated_socket_write_a_warning_close_audit(
    world: _World,
) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        assert _auth(ws)["t"] == "auth_ok"
        for i in range(2):
            assert _auth(ws, f"{REJECTED_MARK}-{i}")["p"]["code"] == "auth_failed"
        ws.send_json({"t": "auth", "id": "a3", "p": {"access_token": f"{REJECTED_MARK}-2"}})
        bye, code = _bye_then_close(ws)
        (rec,) = _close_audits(world)
    assert (bye["p"]["reason"], code) == ("auth_failed", 4401)
    assert (rec["reason"], rec["severity"]) == ("auth_failed", "warning")
    assert rec["actor_user_id"] == USER
    assert [r["action"] for r in world.audit.records] == ["auth.login_failed", CLOSED]
    assert REJECTED_MARK not in repr(world.audit.records)


def test_server_close_audits_the_bye_reason(world: _World) -> None:
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        assert world.client.portal is not None
        assert world.client.portal.call(world.revocation.revoke, SESSION) == 1
        _bye_then_close(ws)
        (rec,) = _close_audits(world)
    assert (rec["reason"], rec["severity"]) == ("session_revoked", "info")


def test_server_transport_close_is_audited_as_shutdown(world: _World) -> None:
    """When the planned §9.4 shutdown is cut short or fails, uvicorn's own shutdown closes
    every socket with 1012: the server has marked its hub as shutting down by then."""
    world.hub.shutting_down = True
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        ws.close(gateway.SERVER_RESTART_CLOSE)
        (rec,) = _close_audits(world)
    assert (rec["reason"], rec["severity"]) == ("shutdown", "info")


def test_a_1012_the_client_sends_is_a_client_close(world: _World) -> None:
    """A non-browser client may send 1012 itself, and uvicorn forwards it: while the server is
    not shutting down it is the client's close, not the server's."""
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        ws.close(gateway.SERVER_RESTART_CLOSE)
        (rec,) = _close_audits(world)
    assert (rec["reason"], rec["severity"]) == ("client_closed", "info")


_BYE = {"p": {"reason": "slow_consumer"}}


@pytest.mark.parametrize(
    ("bye", "fault", "code", "shutting_down", "expected"),
    [
        (_BYE, None, None, False, "slow_consumer"),  # the bye decides, whatever else is set
        ({"p": {"reason": "made_up"}}, None, None, False, "other"),  # bounded like the metric
        ({"t": "bye"}, None, None, False, "other"),  # malformed: no `p`
        ({"p": "slow_consumer"}, None, None, False, "other"),  # malformed: `p` is not a mapping
        (None, RuntimeError(), 1012, True, "internal_error"),
        # uvicorn's own 1012, which a client's own cannot be told from while the server shuts down:
        (None, None, gateway.SERVER_RESTART_CLOSE, True, "shutdown"),
        (None, None, None, True, "shutdown"),  # the host cancelled the handler
        (None, None, gateway.SERVER_RESTART_CLOSE, False, "client_closed"),  # the client's 1012
        (None, None, None, False, "client_closed"),
        (None, None, 1000, True, "client_closed"),  # the client closed first
    ],
)
def test_closed_reason_attribution(
    bye: dict[str, Any] | None,
    fault: BaseException | None,
    code: int | None,
    shutting_down: bool,
    expected: str,
) -> None:
    conn: Any = SimpleNamespace(bye_frame=bye, disconnect_code=code)
    assert gateway.closed_reason(conn, fault, server_shutting_down=shutting_down) == expected


def test_fault_close_is_audited_as_a_warning() -> None:
    conn: Any = SimpleNamespace(bye_frame=None, disconnect_code=None)
    reason = gateway.closed_reason(conn, RuntimeError("writer failed"))
    assert reason == "internal_error" and reason in gateway.WARNING_CLOSES


def test_unauthenticated_close_writes_no_close_audit(world: _World) -> None:
    """No row a peer without a session could multiply; the metric and log line remain."""
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        ws.close(1000)
        _settle(world, lambda: len(world.hub) == 0)
    assert world.audit.records == []


@pytest.mark.parametrize("failure", ["raises", "hangs", "reason"])
def test_close_audit_failure_never_holds_the_teardown(
    world: _World, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(action: str, **kw: Any) -> None:
        if failure == "raises":
            raise RuntimeError("audit sink down")
        await asyncio.Event().wait()  # never set: a stalled sink

    def broken_reason(conn: Any, fault: Any, **kw: Any) -> str:
        raise RuntimeError("reason lookup failed")  # runs inside the audit's own `try`

    if failure == "reason":
        monkeypatch.setattr(gateway, "closed_reason", broken_reason)
    else:
        monkeypatch.setattr(world.audit, "emit", broken)
    monkeypatch.setattr(gateway, "CLOSE_AUDIT_TIMEOUT_S", 0)
    with capture_logs() as logs:
        with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
            _hello(ws)
            _auth(ws)
            ws.close(1000)
            _settle(world, lambda: any(e["event"] == "ws close audit not confirmed" for e in logs))
    assert len(world.hub) == 0 and not world.registry._conns.get(USER)


def test_a_malformed_bye_still_writes_the_close_audit(world: _World) -> None:
    """Unreachable today (every bye is server-built), but a `bye` without `p` must not lose the
    row: its reason is the bounded `other`."""
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        _auth(ws)
        (conn,) = world.hub.of_user(USER)
        assert world.client.portal is not None
        world.client.portal.call(setattr, conn, "bye_frame", {"t": "bye"})
        ws.close(1000)
        (rec,) = _close_audits(world)
    assert (rec["reason"], rec["severity"]) == ("other", "info")
