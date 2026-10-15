"""#2558: the per-user WS connect rate (`23-ws-protocol.md` §4.3, §4.4, §10.2, §16.2).

At most `CV_WS_MAX_AUTHS_PER_USER_PER_MIN` new sockets may complete their first successful `auth`
per user in any sliding 60 s window. The socket that would exceed it gets `bye client_rate_limited`
(`retry_after_ms`, `reconnect: true`) and `4429` INSTEAD of `auth_ok`: it never authenticates, so it
writes no `ws.connection.closed` row. That is the point of the limit (a valid token cannot add one
audit row per close in a tight loop).

Every window runs on the injected fake clock; no test sleeps. Receives are bounded by the helpers of
`test_lifecycle_socket` (worker thread + deadline), so a regression fails fast instead of hanging.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.app import create_app
from candleviewer.ws.gateway import GatewayHub
from candleviewer.ws.lifecycle import (
    AUTH_RATE_WINDOW_S,
    CLOSE_REASONS,
    CONNECT_RATE_MESSAGE,
    MAX_AUTHS_PER_USER_PER_MIN,
    MIN_CONNECT_RETRY_AFTER_MS,
    ConnectRateLimiter,
    bye_frame,
)
from candleviewer.ws.metrics import cv_ws_closes_total
from tests.unit.ws.test_app_wiring import ORIGIN, _Kill, _settings
from tests.unit.ws.test_app_wiring import _authenticate as _wiring_authenticate
from tests.unit.ws.test_lifecycle_contract import _validate
from tests.unit.ws.test_lifecycle_socket import (
    BASE_MS,
    CLOSED,
    JSON,
    SESSION,
    USER,
    _auth,
    _bye_then_close,
    _hello,
    _no_sleep,
    _recv,
    _settle,
    _World,
)

A = uuid.UUID(int=1)
B = uuid.UUID(int=2)
REASON = "client_rate_limited"


# -- the limiter, pure ------------------------------------------------------------------------


def test_documented_defaults_are_20_per_60_s_and_a_retry_hint_of_at_least_1_s() -> None:
    assert MAX_AUTHS_PER_USER_PER_MIN == 20 and AUTH_RATE_WINDOW_S == 60.0
    assert MIN_CONNECT_RETRY_AFTER_MS == 1000
    assert GatewayHub().connect_rate.limit == 20


def test_limiter_admits_up_to_the_limit_then_refuses_with_the_time_to_the_oldest_leaving() -> None:
    limiter = ConnectRateLimiter(3)
    assert [limiter.admit(A, float(t)) for t in (0, 1, 2)] == [None, None, None]
    assert limiter.admit(A, 3.0) == 57_000  # t=0 leaves the window at t=60


def test_limiter_window_is_sliding_and_the_oldest_leaves_exactly_at_60_s() -> None:
    limiter = ConnectRateLimiter(2)
    assert limiter.admit(A, 0.0) is None and limiter.admit(A, 10.0) is None
    assert limiter.admit(A, 59.999) is not None  # t=0 is still 59.999 s old
    assert limiter.admit(A, 60.0) is None  # exactly 60 s old: it has left
    assert limiter.admit(A, 60.0) is not None  # t=10 and t=60 fill the window again
    assert limiter.admit(A, 69.999) is not None
    assert limiter.admit(A, 70.0) is None  # t=10 left


def test_limiter_retry_after_rounds_up_to_the_millisecond_and_is_at_least_one_second() -> None:
    limiter = ConnectRateLimiter(1)
    assert limiter.admit(A, 0.0) is None
    assert limiter.admit(A, 10.0) == 50_000
    assert limiter.admit(A, 30.0004) == 30_000  # 29 999.6 ms rounds UP, never down
    assert limiter.admit(A, 59.0) == 1000
    assert limiter.admit(A, 59.25) == 1000  # 750 ms is clamped up to the floor
    assert limiter.admit(A, 59.9995) == 1000  # 0.5 ms rounds to 1 ms, then to the floor


def test_limiter_refusals_neither_consume_nor_extend_the_window() -> None:
    limiter = ConnectRateLimiter(2)
    assert limiter.admit(A, 0.0) is None and limiter.admit(A, 1.0) is None
    assert all(limiter.admit(A, float(t)) is not None for t in range(2, 11))  # nine refusals
    assert limiter.admit(A, 60.0) is None  # t=0 left; the refusals left nothing behind
    assert limiter.admit(A, 60.5) is not None  # window: t=1 and t=60
    assert limiter.admit(A, 61.0) is None  # t=1 left


def test_limiter_users_are_independent() -> None:
    limiter = ConnectRateLimiter(1)
    assert limiter.admit(A, 0.0) is None
    assert limiter.admit(A, 1.0) is not None
    assert limiter.admit(B, 1.0) is None  # A's refusal cost B nothing
    assert limiter.admit(B, 2.0) is not None


def test_limiter_drops_a_user_once_its_window_is_empty() -> None:
    limiter = ConnectRateLimiter(2)
    limiter.admit(A, 0.0)
    limiter.admit(B, 1.0)
    assert len(limiter) == 2
    limiter.admit(B, 60.0)  # A's only stamp (t=0) is 60 s old: A is gone, B's t=1 is not
    assert len(limiter) == 1 and A not in limiter._stamps
    limiter.admit(A, 61.0)  # B's t=1 left, but t=60 keeps B; A returns fresh with one stamp
    assert len(limiter) == 2 and len(limiter._stamps[A]) == 1
    limiter.admit(A, 200.0)  # everything older than 60 s is gone, including B
    assert len(limiter) == 1 and list(limiter._stamps) == [A]


def test_limiter_keeps_users_in_the_order_of_their_newest_stamp() -> None:
    limiter = ConnectRateLimiter(3)
    limiter.admit(A, 0.0)
    limiter.admit(B, 10.0)
    limiter.admit(A, 20.0)  # A, not B, now holds the newest stamp
    limiter.admit(uuid.UUID(int=3), 75.0)  # B's only stamp (t=10) has left the window; A's has not
    assert B not in limiter._stamps and A in limiter._stamps


def test_limiter_never_holds_more_than_the_limit_per_user() -> None:
    limiter = ConnectRateLimiter(4)
    for i in range(100):
        limiter.admit(A, i * 0.1)
    assert len(limiter._stamps[A]) == 4


@pytest.mark.parametrize("limit", [0, -1])
def test_limiter_refuses_a_limit_below_one(limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        ConnectRateLimiter(limit)


@given(
    limit=st.integers(min_value=1, max_value=5),
    steps=st.lists(
        st.tuples(st.integers(min_value=0, max_value=2), st.floats(0.0, 40.0, allow_nan=False)),
        max_size=80,
    ),
)
def test_limiter_matches_a_brute_force_sliding_window(
    limit: int, steps: list[tuple[int, float]]
) -> None:
    users = [uuid.UUID(int=i + 1) for i in range(3)]
    limiter = ConnectRateLimiter(limit)
    admitted: dict[uuid.UUID, list[float]] = {}
    now = 0.0
    for who, dt in steps:
        now += dt
        user = users[who]
        live = [t for t in admitted.get(user, []) if now - t < 60.0]
        got = limiter.admit(user, now)
        if len(live) >= limit:
            wait_ms = math.ceil((min(live) + 60.0 - now) * 1000)
            assert got == max(1000, wait_ms)
        else:
            assert got is None
            admitted.setdefault(user, []).append(now)
        # C-2.18: bounded per user, and no user is retained once its window is empty.
        assert all(len(s) <= limit for s in limiter._stamps.values())
        assert all(now - s[-1] < 60.0 for s in limiter._stamps.values())


@given(st.lists(st.floats(0.0, 30.0, allow_nan=False), min_size=1, max_size=40))
def test_waiting_the_advised_retry_after_is_admitted(gaps: list[float]) -> None:
    limiter = ConnectRateLimiter(2)
    now = 0.0
    for gap in gaps:
        now += gap
        advice = limiter.admit(A, now)
        if advice is not None:
            # 1e-6 s of slack: the advice is whole milliseconds and `now` is a float.
            assert limiter.admit(A, now + advice / 1000 + 1e-6) is None
            return


# -- the refusal frame ------------------------------------------------------------------------


def test_bye_frame_message_can_be_overridden_and_defaults_stay_as_they_were() -> None:
    assert bye_frame(REASON)["p"]["message"] == "Inbound frame rate exceeded."
    custom = bye_frame(REASON, now_ms=5, retry_after_ms=7, message="x")
    assert custom == {
        "t": "bye",
        "ts": 5,
        "p": {
            "code": 4429,
            "reason": REASON,
            "message": "x",
            "reconnect": True,
            "retry_after_ms": 7,
        },
    }


def test_connect_rate_message_names_the_cause_and_fits_the_schema() -> None:
    assert "connect rate" in CONNECT_RATE_MESSAGE
    assert 0 < len(CONNECT_RATE_MESSAGE) <= 1000  # §13.6 `bye.message`
    assert CLOSE_REASONS[REASON][1] is True  # `reconnect: true`


# -- the gateway, over real sockets -----------------------------------------------------------


def _closes(reason: str) -> float:
    for family in cv_ws_closes_total.collect():
        for sample in family.samples:
            if sample.name == "cv_ws_closes_total" and sample.labels.get("reason") == reason:
                return float(sample.value)
    return 0.0


def _closed_rows(world: _World) -> list[dict[str, Any]]:
    return [r for r in world.audit.records if r["action"] == CLOSED]


def _drain(world: _World) -> None:
    """A few more turns of the app loop, so a teardown that would still write a row has done so."""
    for _ in range(5):
        world.client.portal.call(_no_sleep, 0)  # type: ignore[union-attr]  # portal set in ctx


def _admit_one(world: _World, who: str = "good-1", *, bad_auths: int = 0) -> str:
    """One admitted socket: `bad_auths` failed `auth`s, then `auth_ok`, then a client close.

    Returns its connection id once its close audit row is written (waited for inside the `with`:
    leaving it cancels a teardown still under way)."""
    before = len(_closed_rows(world))
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        connection_id = str(_hello(ws)["p"]["connection_id"])
        for i in range(bad_auths):
            assert _auth(ws, f"bad-{i}")["p"]["code"] == "auth_failed"
        assert _auth(ws, who)["t"] == "auth_ok"
        ws.close(1000)
        _settle(world, lambda: len(_closed_rows(world)) == before + 1)
    return connection_id


def _refused(
    world: _World, who: str = "good-1", *, still_open: int = 0
) -> tuple[dict[str, Any], int, str]:
    """One socket whose first successful `auth` is over the limit: its `bye`, close code and
    connection id, once its connection is gone (`still_open` other sockets stay in the hub)."""
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        connection_id = str(_hello(ws)["p"]["connection_id"])
        ws.send_json({"t": "auth", "id": "c-2", "p": {"access_token": who}})
        bye, code = _bye_then_close(ws)  # the FIRST frame after `auth` is the `bye`: no `auth_ok`
        _settle(world, lambda: len(world.hub) == still_open)
        _drain(world)
    return bye, code, connection_id


def _fail_out(world: _World) -> None:
    """A socket that spends its three failed `auth`s; the third closes it `auth_failed`."""
    with world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _hello(ws)
        for i in range(2):
            assert _auth(ws, f"bad-{i}")["p"]["code"] == "auth_failed"
        ws.send_json({"t": "auth", "id": "a3", "p": {"access_token": "bad-2"}})
        bye, code = _bye_then_close(ws)
    assert (bye["p"]["reason"], code) == ("auth_failed", 4401)


def test_the_connect_over_the_limit_gets_bye_4429_before_auth_ok_and_writes_no_audit_row() -> None:
    w = _World(max_auths_per_min=3)
    with w.client:
        admitted = []
        for i in range(3):  # N successful connects inside 60 s pass
            w.clock.now = float(i)
            admitted.append(_admit_one(w))
        w.clock.now = 3.0
        before = _closes(REASON)
        bye, code, refused_id = _refused(w)  # the (N+1)th
        assert code == 4429
        assert bye["ts"] == BASE_MS + 3000
        assert {k: v for k, v in bye["p"].items() if k != "message"} == {
            "code": 4429,
            "reason": REASON,
            "reconnect": True,
            "retry_after_ms": 57_000,  # t=0 leaves the window at t=60
        }
        assert bye["p"]["message"] == CONNECT_RATE_MESSAGE
        _validate(bye)  # §13.1 envelope + §13.6 `bye`
        assert _closes(REASON) == before + 1
        # No `ws.connection.closed` row for the refused socket: only the N admitted ones wrote one.
        rows = _closed_rows(w)
        assert sorted(r["object_id"] for r in rows) == sorted(admitted)
        assert refused_id not in {r["object_id"] for r in w.audit.records}
        assert [r["action"] for r in w.audit.records] == [CLOSED] * 3
        # Nothing of it is left: the SR-189 permission registration was undone by its teardown, and
        # it never got a revocation hook.
        assert not w.registry._conns.get(USER)
        revoked = w.client.portal.call(w.revocation.revoke, SESSION)  # type: ignore[union-attr]
        assert revoked == 0  # portal is set inside `with w.client`


def test_a_connect_passes_again_once_the_window_slides() -> None:
    w = _World(max_auths_per_min=2)
    with w.client:
        for t in (0.0, 10.0):
            w.clock.now = t
            _admit_one(w)
        w.clock.now = 59.5  # t=0 is still in the window, by 500 ms
        bye, code, _ = _refused(w)
        assert code == 4429 and bye["p"]["retry_after_ms"] == 1000  # at least 1 s
        w.clock.now = 60.0  # t=0 has left the window
        _admit_one(w)
        w.clock.now = 60.5  # the window holds t=10 and t=60
        bye, code, _ = _refused(w)
        assert code == 4429 and bye["p"]["retry_after_ms"] == 9500
        w.clock.now = 70.0  # t=10 has left too
        _admit_one(w)


def test_in_place_reauth_on_a_live_socket_does_not_consume_the_budget() -> None:
    w = _World(max_auths_per_min=2)
    with w.client, w.client.websocket_connect("/ws", subprotocols=JSON) as first:
        _hello(first)
        assert _auth(first)["t"] == "auth_ok"  # this new socket's first auth: 1 of 2
        for i in range(5):
            assert _auth(first, f"good-r{i}", f"r-{i}")["t"] == "auth_ok"  # token refreshes: free
        with w.client.websocket_connect("/ws", subprotocols=JSON) as second:
            _hello(second)
            assert _auth(second)["t"] == "auth_ok"  # 2 of 2: the re-auths cost nothing
            with w.client.websocket_connect("/ws", subprotocols=JSON) as third:
                _hello(third)
                third.send_json({"t": "auth", "id": "c-2", "p": {"access_token": "good-1"}})
                bye, code = _bye_then_close(third)
        assert (bye["p"]["reason"], code) == (REASON, 4429)
        first.send_json({"t": "ping", "id": "p"})
        assert _recv(first)["t"] == "pong"  # the live socket is untouched


def test_failed_auths_do_not_consume_the_budget() -> None:
    w = _World(max_auths_per_min=2)
    with w.client:
        for _ in range(3):  # nine failed `auth`s on three sockets: none is a successful one
            _fail_out(w)
        _admit_one(w, bad_auths=1)  # fails once, then succeeds: spends exactly one
        _admit_one(w)  # the second of two
        bye, code, _ = _refused(w)
    assert (bye["p"]["reason"], code) == (REASON, 4429)


def test_two_users_have_independent_budgets() -> None:
    w = _World(max_auths_per_min=1)
    with w.client:
        _admit_one(w)  # USER 1 of 1
        assert _refused(w)[1] == 4429
        _admit_one(w, "good-other")  # OTHER is not affected by USER's refusal
        assert _refused(w, "good-other")[1] == 4429
        assert _refused(w)[1] == 4429  # and OTHER's connect did not refund USER


def test_a_users_state_is_dropped_once_its_window_empties() -> None:
    w = _World(max_auths_per_min=2)
    with w.client:
        _admit_one(w)  # USER at t=0
        assert len(w.hub.connect_rate) == 1
        w.clock.now = 61.0
        _admit_one(w, "good-other")  # OTHER at t=61: USER's window is empty, so its entry is gone
        assert len(w.hub.connect_rate) == 1
        _admit_one(w)  # USER returns with a fresh budget
        assert len(w.hub.connect_rate) == 2


def test_a_refused_connect_never_evicts_a_live_socket() -> None:
    w = _World(max_per_user=1, max_auths_per_min=1)
    with w.client, w.client.websocket_connect("/ws", subprotocols=JSON) as live:
        _hello(live)
        assert _auth(live)["t"] == "auth_ok"
        bye, code, _ = _refused(w, still_open=1)  # would evict `live` (cap 1) if admitted
        assert (bye["p"]["reason"], code) == (REASON, 4429)
        live.send_json({"t": "ping", "id": "p"})
        assert _recv(live)["t"] == "pong"  # not closed `too_many_connections`


def test_the_refusal_is_logged_with_the_user_and_never_the_token() -> None:
    w = _World(max_auths_per_min=1)
    with w.client:
        _admit_one(w)
        w.clock.now = 5.0
        with capture_logs() as logs:
            _refused(w, "good-probe-7")
    (entry,) = [e for e in logs if e["event"] == "ws connect rate limited"]
    assert entry["user_id"] == str(USER) and entry["limit"] == 1
    assert entry["retry_after_ms"] == 55_000 and entry["connection_id"].startswith("ws_")
    assert "good-probe-7" not in repr(logs)


# -- wiring -----------------------------------------------------------------------------------


def test_create_app_builds_the_hub_with_the_default_limit() -> None:
    app = create_app(
        _settings(), snapshot_loader=_Kill().load, ws_authenticate=_wiring_authenticate
    )
    assert app.state.ws_hub.connect_rate.limit == MAX_AUTHS_PER_USER_PER_MIN


def test_create_app_builds_the_hub_from_the_connect_rate_setting() -> None:
    settings = _settings().model_copy(update={"ws_max_auths_per_user_per_min": 7})
    app = create_app(settings, snapshot_loader=_Kill().load, ws_authenticate=_wiring_authenticate)
    assert app.state.ws_hub.connect_rate.limit == 7


def test_a_socket_through_create_app_is_refused_over_the_configured_limit() -> None:
    settings = _settings().model_copy(update={"ws_max_auths_per_user_per_min": 1})
    app = create_app(settings, snapshot_loader=_Kill().load, ws_authenticate=_wiring_authenticate)
    with TestClient(app, client=("127.0.0.1", 50000), headers={"origin": ORIGIN}) as client:
        outcomes = []
        for _ in range(2):
            with client.websocket_connect("/ws", subprotocols=JSON) as ws:
                ws.send_json({"t": "hello", "id": "h", "p": {}})
                assert ws.receive_json()["t"] == "welcome"
                ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "tok"}})
                frame = ws.receive_json()
                outcomes.append((frame["t"], frame["p"].get("reason")))
    assert outcomes == [("auth_ok", None), ("bye", REASON)]
