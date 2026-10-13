"""E09-X02 WebSocket attack cases (U13, U32, `23-ws-protocol.md` §4.3/§6/§9.5; #2144).

In-process through the real `create_app()` gateway, `SessionService`, `RevocationHub` and
`ConnectionRegistry`; fixed clock shared with the gateway, no network. Every read has a hard
deadline so a frame that never arrives fails fast instead of hanging. No WS production code is
changed here; where a case shows a gap it is recorded as a finding in the catalogue.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

import pytest

from tests.csrf_helpers import csrf_headers

from ._stack import GRANTED_ACCOUNT, ORIGIN, Grants, Stack

_JSON = ["cv.v1.json"]
_ORDERS = {"ch": "orders", "opts": {"exchange_account_ids": [str(GRANTED_ACCOUNT)]}}
_DEADLINE_S = 5.0


def _connect(stack: Stack) -> Any:
    """A browser-like upgrade: the allow-listed `Origin` is required since SR-042 (#2263)."""
    return stack.client.websocket_connect("/ws", subprotocols=_JSON, headers={"origin": ORIGIN})


def _recv(ws: Any) -> dict[str, Any]:
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        frame: dict[str, Any] = pool.submit(ws.receive_json).result(timeout=_DEADLINE_S)
    except FutureTimeout:
        pytest.fail(f"no WS frame within {_DEADLINE_S}s")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return frame


def _hello(ws: Any) -> None:
    ws.send_json({"t": "hello", "id": "h"})
    assert _recv(ws)["t"] == "welcome"


def _auth(ws: Any, token: str) -> dict[str, Any]:
    ws.send_json({"t": "auth", "id": "a", "p": {"access_token": token}})
    return _recv(ws)


def _sub(ws: Any, *topics: Any) -> list[dict[str, Any]]:
    ws.send_json({"t": "sub", "id": "s", "p": {"topics": list(topics)}})
    reply = _recv(ws)
    assert reply["t"] == "sub_ok", reply
    return list(reply["p"]["results"])


def test_ac_ws_01_private_subscribe_before_auth_ok_is_refused_then_closed(
    world: tuple[Stack, Grants],
) -> None:  # §4.3: nothing is served before auth_ok
    stack, _ = world
    closes = stack.scraped("cv_ws_closes_total", reason="not_authenticated")
    with _connect(stack) as ws:
        _hello(ws)
        for i in range(2):
            ws.send_json({"t": "sub", "id": f"s{i}", "p": {"topics": [_ORDERS]}})
            err = _recv(ws)
            assert (err["t"], err["p"]["code"]) == ("err", "not_authenticated")
        ws.send_json({"t": "sub", "id": "s2", "p": {"topics": [_ORDERS]}})
        bye = _recv(ws)
        assert (bye["t"], bye["p"]["reason"], bye["p"]["code"]) == (
            "bye",
            "not_authenticated",
            4401,
        )
    assert stack.scraped("cv_ws_closes_total", reason="not_authenticated") - closes == 1
    assert stack.audit.records == []  # no topic reached authorisation, so nothing to audit


def test_ac_ws_02_auth_frame_replayed_on_second_socket_accepted_while_session_is_live(
    world: tuple[Stack, Grants],
) -> None:  # U13; finding F-3: the replay is bounded by the session, not by the socket
    stack, _ = world
    minted = stack.call(stack.auth.sessions.mint, str(uuid.uuid4()))
    failures = stack.scraped("cv_ws_auth_failures_total", reason="rejected")
    with (
        _connect(stack) as victim,
        _connect(stack) as replay,
    ):
        _hello(victim)
        assert _auth(victim, minted.access_token)["t"] == "auth_ok"
        _hello(replay)
        accepted = _auth(replay, minted.access_token)  # the captured frame, second socket
        assert (accepted["t"], accepted["p"]["session_id"]) == ("auth_ok", str(minted.session_id))
        logout = {
            "Authorization": f"Bearer {minted.access_token}",
            **csrf_headers(stack.state.csrf_codec, minted.session_id),
        }
        assert stack.client.post("/auth/logout", headers=logout).status_code == 204
        for ws in (victim, replay):  # revocation ends every socket of the session
            bye = _recv(ws)
            assert (bye["t"], bye["p"]["reason"], bye["p"]["code"]) == (
                "bye",
                "session_revoked",
                4401,
            )
    with _connect(stack) as late:
        _hello(late)
        assert [_auth(late, minted.access_token)["t"] for _ in range(3)] == ["err", "err", "bye"]
    (row,) = stack.audit.of("auth.login_failed")
    assert (row["reason"], row["severity"].value) == ("ws_auth_failed", "warning")
    assert stack.scraped("cv_ws_auth_failures_total", reason="rejected") - failures == 3


def test_ac_ws_03_socket_held_across_grant_revocation_loses_and_cannot_regain_the_topic(
    world: tuple[Stack, Grants],
) -> None:  # U32 / §9.5 (the re-auth snapshot race, SR-189, is #2172)
    stack, grants = world
    user = uuid.uuid4()
    minted = stack.call(stack.auth.sessions.mint, str(user))
    revoked = stack.scraped("cv_ws_revoked_total", reason="account_scope_changed")
    with _connect(stack) as ws:
        _hello(ws)
        assert _auth(ws, minted.access_token)["t"] == "auth_ok"
        assert _sub(ws, _ORDERS)[0]["ok"] is True
        grants.granted = False
        stack.call(stack.state.ws_events.grants_changed, user)
        assert _recv(ws)["t"] == "permission_change"
        frame = _recv(ws)
        assert (frame["t"], frame["ch"], frame["p"]["reason"]) == (
            "revoked",
            "orders",
            "account_scope_changed",
        )
        assert frame["p"]["resubscribe_allowed"] is False
        assert _auth(ws, minted.access_token)["t"] == "auth_ok"  # re-auth: fresh snapshot only
        (again,) = _sub(ws, _ORDERS)
        assert (again["ok"], again["error"]["code"]) == (False, "account_scope_denied")
    (gone,) = stack.audit.of("ws.subscription.revoked")
    (denied,) = stack.audit.of("ws.subscribe.denied")
    assert (gone["reason"], denied["reason"]) == ("account_scope_changed", "account_scope_denied")
    assert stack.scraped("cv_ws_revoked_total", reason="account_scope_changed") - revoked == 1


def test_ac_ws_04_topic_name_injection_never_escapes_the_registry(
    world: tuple[Stack, Grants],
) -> None:  # §6: only catalogued topic names are parsed; nothing else is subscribed
    stack, _ = world
    minted = stack.call(stack.auth.sessions.mint, str(uuid.uuid4()))
    hostile = [
        "../admin",
        "orders.*",
        "book.BTCUSDT.50/../../admin",
        "system\nadmin",
        "orders\u0000",
        "Book.btcusdt.50",
        "x" * 300,
    ]
    refused = ("unknown_topic", "invalid_topic_format")
    before = sum(stack.scraped("cv_ws_subscribe_total", result=c) for c in refused)
    with _connect(stack) as ws:
        _hello(ws)
        assert _auth(ws, minted.access_token)["t"] == "auth_ok"
        results = _sub(ws, *hostile)
        assert [r["ok"] for r in results] == [False] * len(hostile)
        assert {r["error"]["code"] for r in results} <= set(refused), results
        ws.send_json({"t": "unsub", "id": "u", "p": {"topics": hostile}})
        assert all(r.get("noop") for r in _recv(ws)["p"]["results"])  # nothing was attached
    after = sum(stack.scraped("cv_ws_subscribe_total", result=c) for c in refused)
    assert after - before == len(hostile)
    (row,) = stack.audit.of("ws.subscribe.denied")  # only the attempt naming a private family
    assert (row["object_id"], row["reason"]) == ("orders", "invalid_topic_format")
