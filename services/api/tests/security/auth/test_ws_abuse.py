"""E09-X02 WebSocket attack cases (U13, U32, `23-ws-protocol.md` §4.3/§6/§9.5; #2144).

In-process through the real `create_app()` gateway, `SessionService`, `RevocationHub` and
`ConnectionRegistry`; fixed clock shared with the gateway, no network. Every read has a hard
deadline so a frame that never arrives fails fast instead of hanging. No WS production code is
changed here; where a case shows a gap it is recorded as a finding in the catalogue.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

import pytest

from tests.csrf_helpers import csrf_headers
from tests.unit.auth.auth_fakes import make_user

from ._stack import GRANTED_ACCOUNT, ORIGIN, Grants, Stack

_JSON = ["cv.v1.json"]
_ORDERS = {"ch": "orders", "opts": {"exchange_account_ids": [str(GRANTED_ACCOUNT)]}}
_DEADLINE_S = 5.0
_INERT = "unused"  # stored-hash placeholder: no password is verified on these sockets
#: Not topic names (`common.schema.json#/$defs/topic`): a `sub` with one is refused whole (#2399).
#: Keyed by a short label, so a test id never carries a raw control character or 300 characters.
_MALFORMED = {
    "path-traversal": "../admin",
    "wildcard": "orders.*",
    "embedded-traversal": "book.BTCUSDT.50/../../admin",
    "newline": "system\nadmin",
    "nul-byte": "orders\u0000",
    "upper-case": "Book.btcusdt.50",
    "overlong": "x" * 300,
}
_MALFORMED_NAMES = pytest.mark.parametrize("name", list(_MALFORMED.values()), ids=list(_MALFORMED))
#: Well-formed names the catalogue does not serve: refused per topic. `orders` is a private family.
_UNCATALOGUED = ["admin", "orders.admin", "book.BTCUSDT.50.admin"]
_PER_TOPIC_REFUSALS = {"unknown_topic", "invalid_topic_format"}  # their result codes


def _member(stack: Stack, username: str) -> uuid.UUID:
    """A user the store knows, with a confirmed TOTP method. Every WS `auth` is classified from
    the user's state (#2295), and a user the store cannot read fails closed."""
    user = make_user(username=username, email=f"{username}@example.test", password_hash=_INERT)
    stack.users.add(user)
    return user.id


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


def _sub_refused(ws: Any, *topics: Any) -> dict[str, Any]:
    """A `sub` whose shape breaks §13.5 gets one `err` instead of a `sub_ok` (§5.2, #2399)."""
    ws.send_json({"t": "sub", "id": "s", "p": {"topics": list(topics)}})
    reply = _recv(ws)
    assert (reply["t"], reply["id"]) == ("err", "s"), reply
    return dict(reply["p"])


def _unsub(ws: Any, *topics: str) -> list[dict[str, Any]]:
    ws.send_json({"t": "unsub", "id": "u", "p": {"topics": list(topics)}})
    reply = _recv(ws)
    assert reply["t"] == "unsub_ok", reply
    return list(reply["p"]["results"])


@contextlib.contextmanager
def _authenticated(stack: Stack) -> Iterator[Any]:
    """A socket past `hello` and `auth`, for a fresh session of the stack's manager."""
    minted = stack.call(stack.auth.sessions.mint, str(_member(stack, "ws-manager")))
    with _connect(stack) as ws:
        _hello(ws)
        assert _auth(ws, minted.access_token)["t"] == "auth_ok"
        yield ws


def test_ac_ws_01_private_subscribe_before_auth_ok_is_refused_then_closed(
    ws_world: tuple[Stack, Grants],
) -> None:  # §4.3: nothing is served before auth_ok
    stack, _ = ws_world
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
    # no topic reached authorisation, and an unauthenticated close writes no row (#2528)
    assert stack.audit.records == []


def test_ac_ws_02_auth_frame_replayed_on_second_socket_accepted_while_session_is_live(
    ws_world: tuple[Stack, Grants],
) -> None:  # U13; finding F-4: the replay is bounded by the session, not by the socket
    stack, _ = ws_world
    minted = stack.call(stack.auth.sessions.mint, str(_member(stack, "ws-victim")))
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
    # #2528: each authenticated socket's end is audited, so the replayed one shows afterwards
    ended = [r["reason"] for r in stack.audit.of("ws.connection.closed")]
    assert ended == ["session_revoked", "session_revoked"]
    with _connect(stack) as late:
        _hello(late)
        assert [_auth(late, minted.access_token)["t"] for _ in range(3)] == ["err", "err", "bye"]
    (row,) = stack.audit.of("auth.login_failed")
    assert (row["reason"], row["severity"].value) == ("ws_auth_failed", "warning")
    assert stack.scraped("cv_ws_auth_failures_total", reason="rejected") - failures == 3


def test_ac_ws_03_socket_held_across_grant_revocation_loses_and_cannot_regain_the_topic(
    ws_world: tuple[Stack, Grants],
) -> None:  # U32 / §9.5 (the re-auth snapshot race, SR-189, was #2172: fixed by #2318)
    stack, grants = ws_world
    user = _member(stack, "ws-grantee")
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


@_MALFORMED_NAMES
def test_ac_ws_04_name_that_is_not_a_topic_name_refuses_its_whole_sub(
    ws_world: tuple[Stack, Grants], name: str
) -> None:  # §5.2/§6: one `err` naming the entry, no `sub_ok`, nothing attached, no strike (§4.3)
    stack, _ = ws_world
    with _authenticated(stack) as ws:
        err = _sub_refused(ws, name)
        assert (err["code"], err["field"], err["close"]) == ("invalid_options", "topics[0]", False)
        assert [r.get("noop") for r in _unsub(ws, name)] == [True]  # nothing was attached


@_MALFORMED_NAMES
def test_ac_ws_04_refusal_of_a_malformed_name_never_echoes_it(
    ws_world: tuple[Stack, Grants], name: str
) -> None:  # the reply is built from the shape alone: no reflected control characters
    stack, _ = ws_world
    with _authenticated(stack) as ws:
        err = _sub_refused(ws, name)
    assert name not in err["message"] + err["field"]


def test_ac_ws_04_granted_topic_cannot_carry_a_malformed_name_along(
    ws_world: tuple[Stack, Grants],
) -> None:  # the frame is refused whole, so the topic the principal may hold is not attached either
    stack, _ = ws_world
    with _authenticated(stack) as ws:
        mixed = _sub_refused(ws, _ORDERS, "../admin")
        assert (mixed["code"], mixed["field"]) == ("invalid_options", "topics[1]")
        assert [r.get("noop") for r in _unsub(ws, "orders")] == [True]


@_MALFORMED_NAMES
def test_ac_ws_04_malformed_name_leaves_no_scraped_sample_audit_row_or_strike(
    ws_world: tuple[Stack, Grants], name: str
) -> None:  # refused before any topic is read: only the unscraped error counter moves (O-2)
    stack, _ = ws_world
    subscribed = stack.scraped("cv_ws_subscribe_total")  # summed over every topic and result label
    closes = stack.scraped("cv_ws_closes_total")
    refusals = stack.in_process("cv_ws_errors_total", code="invalid_options")
    with _authenticated(stack) as ws:
        _sub_refused(ws, name)
        assert stack.scraped("cv_ws_closes_total") == closes  # no strike: the socket stayed open
    assert stack.scraped("cv_ws_subscribe_total") == subscribed
    assert stack.audit.of("ws.subscribe.denied") == []
    assert stack.in_process("cv_ws_errors_total", code="invalid_options") - refusals == 1
    assert stack.scraped("cv_ws_errors_total") == 0.0  # in-process only: no alert can read it


def test_ac_ws_04_well_formed_unknown_names_are_refused_per_topic_and_attach_nothing(
    ws_world: tuple[Stack, Grants],
) -> None:  # a well-formed name is a topic name, so each gets its own result (§5.2)
    stack, _ = ws_world
    with _authenticated(stack) as ws:
        results = _sub(ws, *_UNCATALOGUED)
        assert [r["ok"] for r in results] == [False] * len(_UNCATALOGUED)
        assert {r["error"]["code"] for r in results} <= _PER_TOPIC_REFUSALS, results
        noops = [r.get("noop") for r in _unsub(ws, *_UNCATALOGUED)]
        assert noops == [True] * len(_UNCATALOGUED)  # nothing was attached


def test_ac_ws_04_well_formed_unknown_names_are_counted_once_each_on_the_scraped_counter(
    ws_world: tuple[Stack, Grants],
) -> None:  # summed over every label, so a name filed under any other result would show too
    stack, _ = ws_world
    counted = stack.scraped("cv_ws_subscribe_total")
    with _authenticated(stack) as ws:
        _sub(ws, *_UNCATALOGUED)
    assert stack.scraped("cv_ws_subscribe_total") - counted == len(_UNCATALOGUED)


def test_ac_ws_04_unknown_private_name_is_audited_by_family_never_by_its_raw_name(
    ws_world: tuple[Stack, Grants],
) -> None:  # only `orders.admin` is a private family; `admin` and the `book` name are not audited
    stack, _ = ws_world
    with _authenticated(stack) as ws:
        _sub(ws, *_UNCATALOGUED)
    (row,) = stack.audit.of("ws.subscribe.denied")
    assert (row["object_id"], row["reason"]) == ("orders", "invalid_topic_format")
