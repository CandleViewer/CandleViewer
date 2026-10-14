"""E17-Q01: one named test per normative server requirement S1-S13 (`23-ws-protocol.md` §16.1).

Every test drives the REAL gateway (`make_ws_router`, `ConnectionRegistry`, `SequencingHub`,
`TopicEmitter`) through a socket and validates every received frame against the §13-§15 schemas
(`_harness.validate_frame`). Test names start `test_sN_` so the coverage matrix in
`conftest.py` can report which requirements ran.

Every test in this module is negative-path (it sends deliberately invalid client frames), so
`connect()` below defaults to `conform=False`: outbound frames are NOT pre-validated against §13
here. The positive-path modules keep the validating default.
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant
from candleviewer.ws.errors import UnknownErrorCode, build_ws_error
from candleviewer.ws.topics import FAMILIES, UNIVERSAL
from tests.contract.ws._harness import (
    JSON,
    Client,
    World,
    all_private,
    delta_body,
    entry,
    wire_error_codes,
)
from tests.contract.ws._harness import (
    connect as _connect,
)
from tests.unit.ws._seq_support import ACC_A, ACC_B, USER

# -- S10 ---------------------------------------------------------------------------------------


def connect(*a: Any, **k: Any) -> Any:
    """Every test here is a negative-path test: it sends deliberately invalid client frames."""
    return _connect(*a, conform=False, **k)


def test_s10_only_catalogue_codes_can_be_built_and_an_injected_code_fails_the_suite() -> None:
    catalogue = wire_error_codes()
    assert {"protocol_violation", "slow_consumer", "internal_error"} <= catalogue
    with pytest.raises(UnknownErrorCode):
        build_ws_error("totally_made_up")
    with pytest.raises(AssertionError, match="outside"):
        _assert_closed([{"t": "err", "p": {"code": "totally_made_up"}}], catalogue)


def _codes_of(frames: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for f in frames:
        if f["t"] == "err":
            out.add(f["p"]["code"])
        elif f["t"] == "sub_ok":
            out |= {r["error"]["code"] for r in f["p"]["results"] if not r["ok"]}
    return out


def _assert_closed(frames: list[dict[str, Any]], catalogue: frozenset[str]) -> set[str]:
    codes = _codes_of(frames)
    assert codes <= catalogue, f"error codes outside §10.2: {sorted(codes - catalogue)}"
    return codes


#: Every error path reachable through the gateway today, as (label, expected code).
REACHABLE_CODES = {
    "frame_malformed",
    "protocol_violation",
    "not_authenticated",
    "auth_failed",
    "forbidden",
    "account_scope_denied",
    "unknown_topic",
    "invalid_topic_format",
    "invalid_options",
    "encoding_unsupported",
    "subscription_limit",
    "too_many_topics",
    "duplicate_subscription",
    "not_subscribed",
    "resync_rate_limited",
    "client_rate_limited",
}


def test_s10_error_catalogue_is_closed_over_a_full_run_of_every_error_path() -> None:
    catalogue = wire_error_codes()
    frames: list[dict[str, Any]] = []
    w = World()
    with connect(w, authed=False) as c:  # not_authenticated, auth_failed, protocol_violation
        c.send({"t": "sub", "id": "s", "p": {"topics": ["trades.BTCUSDT"]}})
        frames.append(c.recv_err())
        c.send({"t": "auth", "id": "a", "p": {"access_token": "bad-" + "x" * 20}})
        frames.append(c.recv_err())
        c.send({"t": "hello", "id": "again"})
        frames.append(c.recv_err())
        c.send_text("not json")
        frames.append(c.recv_err())
    w = World()
    w.perms = frozenset({Permission.MARKETDATA_READ})
    w.grants = (AccountGrant(ACC_A, True, False, False),)
    with connect(w) as c:
        res = c.sub(
            {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}},  # forbidden
            {"ch": "nope.X"},
            {"ch": "book.BTCUSDT.7"},
            {"ch": "ticker.BTCUSDT", "opts": {"bogus": 1}},
            {"ch": "trades.BTCUSDT"},
            {"ch": "trades.BTCUSDT"},
            {"ch": "ticker.ETHUSD"},
            {"ch": "profile.BTCUSDT.volume", "opts": {"encoding": "binary"}},
        )
        frames.append(res)
        c.send({"t": "ctl", "id": "k", "ch": "heatmap.BTCUSDT", "p": {"throttle_ms": 1}})
        frames.append(c.recv_err())  # not_subscribed
        many = [{"ch": f"bars.BTCUSDT.tick.{i}"} for i in range(1, 52)]
        frames.append(c.sub(*many))  # too_many_topics
    w = World()
    with connect(w) as c:
        c.sub("book.BTCUSDT.50")
        c.drain(1)
        for i in range(5):
            w.clock.now = float(i)
            c.send(
                {"t": "resync", "id": f"r{i}", "ch": "book.BTCUSDT.50", "p": {"reason": "manual"}}
            )
            c.next_of("snap")
        c.send({"t": "resync", "id": "r6", "ch": "book.BTCUSDT.50", "p": {"reason": "manual"}})
        frames.append(c.recv_err())
    w = World()
    with connect(w) as c:
        frames.append(c.sub({"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_B), "x"]}}))
        for i in range(40):  # inbound rate limit
            c.send({"t": "ping", "id": f"p{i}"})
        while (f := c.recv(validate=False))["t"] != "err":
            pass
        frames.append(f)
    codes = _assert_closed(frames, catalogue)
    assert codes >= REACHABLE_CODES - {"account_scope_denied", "subscription_limit"}, sorted(
        REACHABLE_CODES - codes
    )


# -- S11 ---------------------------------------------------------------------------------------


def test_s11_bye_precedes_close_for_a_client_that_never_authenticates() -> None:
    w = World()
    with connect(w, authed=False) as c:
        w.clock.now = 10.0  # the 10 s auth window lapses on the fake clock
        bye, code = c.bye_then_close()
        assert (bye["p"]["reason"], code) == ("auth_timeout", 4401)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("frame_too_big", 1009),
        ("bad_client", 4400),
        ("heartbeat_timeout", 1001),
        ("client_rate_limited", 4429),
        ("not_authenticated", 4401),
        ("auth_failed", 4401),
        ("token_expired", 4401),
        ("protocol_violation", 1002),
        ("shutdown", 1001),
        ("too_many_connections", 4429),
    ],
)
def test_s11_every_server_initiated_close_is_preceded_by_bye(label: str, expected: int) -> None:
    w = World()
    if label == "not_authenticated":
        with connect(w, authed=False) as c:
            for _ in range(3):
                c.send({"t": "sub", "id": "s", "p": {"topics": ["trades.BTCUSDT"]}})
            assert c.bye_then_close()[1] == expected
        return
    if label == "auth_failed":
        with connect(w, authed=False) as c:
            for i in range(3):
                c.send({"t": "auth", "id": f"a{i}", "p": {"access_token": "bad-" + "x" * 20}})
            assert c.bye_then_close()[1] == expected
        return
    if label == "protocol_violation":
        with connect(w, authed=False, handshake=False) as c:
            c.send({"t": "sub", "id": "s", "p": {"topics": ["trades.BTCUSDT"]}})  # before hello
            assert c.bye_then_close()[1] == expected
        return
    with connect(w) as c:
        if label == "frame_too_big":
            c.send_text('{"t":"ping","id":"' + "x" * (256 * 1024) + '"}')
        elif label == "bad_client":
            for _ in range(3):
                c.send_text("not json")
        elif label == "heartbeat_timeout":
            w.clock.now = 20.0
            c.recv(skip_ping=False)  # the server's unsolicited ping, left unanswered
            w.clock.now = 45.0
        elif label == "client_rate_limited":
            for i in range(60):
                c.send({"t": "ping", "id": f"p{i}"})
        elif label == "token_expired":
            w.clock.now = float(w.token_ttl_s)
        elif label == "shutdown":
            w.call(lambda: w.gateway.shutdown(sleep=_no_sleep))
        elif label == "too_many_connections":
            return _too_many_connections()  # opens its own sockets
        while True:
            f = c.recv(validate=False, skip_ping=True)
            if f["t"] == "bye":
                break
        assert f["p"]["code"] == expected and c.closed() == expected


async def _no_sleep(_s: float) -> None:
    return None


def _too_many_connections() -> None:
    """Per-user cap (§4): the oldest-idle socket gets `bye too_many_connections` / 4429. Distinct
    inbound times on the fake clock make "oldest idle" unambiguous."""
    w = World()
    w.gateway.max_per_user = 2
    with w.client:
        with w.client.websocket_connect("/ws", subprotocols=JSON) as old_ws:
            old = Client(old_ws, conform=False)
            old.open()
            with w.client.websocket_connect("/ws", subprotocols=JSON) as busy_ws:
                busy = Client(busy_ws, conform=False)
                busy.send({"t": "hello", "id": "h"})
                busy.recv()
                w.clock.now = 5.0
                busy.send({"t": "auth", "id": "a", "p": {"access_token": "good"}})
                busy.recv()
                with w.client.websocket_connect("/ws", subprotocols=JSON) as new_ws:
                    Client(new_ws, conform=False).open()
                    bye, code = old.bye_then_close()
                    assert (bye["p"]["reason"], code) == ("too_many_connections", 4429)


def test_s11_user_disabled_and_session_revoked_closes_are_preceded_by_bye() -> None:
    for trigger, reason in (("user_disabled", "user_disabled"), ("revoke", "session_revoked")):
        w = World()
        with connect(w) as c:
            if trigger == "user_disabled":
                w.call(w.registry.user_disabled, USER)
            else:
                w.call(w.revocation.revoke, w.session)
            bye, _ = c.bye_then_close()
            assert bye["p"]["reason"] == reason


def test_s11_a_sealed_close_drops_queued_frames_but_still_delivers_bye() -> None:
    w = World()
    with connect(w) as c:
        all_private(c, "orders")
        w.call(lambda: [w.hub.publish("orders", delta_body("orders"), account=ACC_A)] * 20)
        w.call(w.revocation.revoke, w.session)
        seen = []
        while True:
            f = c.recv(validate=False)
            seen.append(f["t"])
            if f["t"] == "bye":
                break
        assert seen[-1] == "bye" and c.closed() == 4401


# -- S12 ---------------------------------------------------------------------------------------

_OPTION_ROWS = [
    pytest.param(f.family, name, id=f"{f.family}.{name}")
    for f in FAMILIES.values()
    if f.family != "system"
    for name in sorted({**UNIVERSAL, **f.options})
]


@pytest.mark.parametrize(("family", "option"), _OPTION_ROWS)
def test_s12_a_typo_of_every_declared_option_is_rejected_not_ignored(
    family: str, option: str
) -> None:
    """Generated from the registry: every declared option, misspelt, is `invalid_options` with the
    offending key in `field`, and no subscription is created."""
    shape = FAMILIES[family].shapes[0]
    w = World()
    e = entry(family, shape)
    e["opts"][option + "_"] = 1
    with connect(w) as c:
        res = c.sub(e)["p"]["results"][0]
        assert res["ok"] is False
        assert (res["error"]["code"], res["error"]["field"]) == ("invalid_options", option + "_")
        c.send({"t": "ping", "id": "p"})
        assert c.recv()["t"] == "pong"  # and no snapshot followed: nothing was subscribed


def test_s12_unknown_options_on_ctl_and_unknown_entry_fields_are_rejected() -> None:
    w = World()
    with connect(w) as c:
        c.sub("trades.BTCUSDT")
        c.drain(1)
        c.send({"t": "ctl", "id": "k", "ch": "trades.BTCUSDT", "p": {"throttel_ms": 1}})
        err = c.recv_err()
        assert (err["p"]["code"], err["p"]["field"]) == ("invalid_options", "throttel_ms")
        res = c.sub({"ch": "ticker.BTCUSDT", "extra": 1})["p"]["results"][0]
        assert res["error"]["code"] == "invalid_options"


def test_s12_scope_options_cannot_be_widened_through_ctl() -> None:
    w = World()
    with connect(w) as c:
        c.sub({"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)]}})
        c.drain(1)
        c.send({"t": "ctl", "id": "k", "ch": "orders", "p": {"exchange_account_ids": [str(ACC_B)]}})
        assert c.recv_err()["p"]["code"] == "invalid_options"


# -- S13 ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({"origin": "https://evil.example"}, id="unlisted"),
        pytest.param({"origin": "null"}, id="null"),
    ],
)
def test_s13_a_bad_origin_is_refused_before_accept_and_never_reaches_auth(
    headers: dict[str, str],
) -> None:
    w = World()
    with pytest.raises(WebSocketDisconnect) as exc, w.client:
        with w.client.websocket_connect("/ws", subprotocols=["cv.v1.json"], headers=headers) as ws:
            ws.send_json({"t": "hello", "id": "h"})
            ws.receive_json()
    assert exc.value.code == 4403
    assert w.tokens_seen == []  # the verifier was never consulted


def test_s13_a_token_in_the_query_string_is_never_read() -> None:
    w = World()
    with w.client, w.client.websocket_connect("/ws?access_token=good", subprotocols=JSON) as ws:
        c = Client(ws)
        c.open(auth=False)
        w.clock.now = 10.0
        assert c.bye_then_close()[1] == 4401
    assert w.tokens_seen == []


def test_s13_a_client_offering_no_recognised_subprotocol_is_closed_1002() -> None:
    w = World()
    with pytest.raises(WebSocketDisconnect) as exc, w.client:
        with w.client.websocket_connect("/ws", subprotocols=["cv.v2.json"]) as ws:
            ws.receive_json()
    assert exc.value.code == 1002


@pytest.mark.xfail(strict=True, reason="#2395: err frames omit the required p.message")
def test_s10_xfail_f1_err_frame_validates_against_the_error_schema() -> None:
    with connect(World()) as c:
        c.send({"t": "bogus"})
        c.recv()  # validated: common#/$defs/error requires `message`


@pytest.mark.xfail(strict=True, reason="#377: cv.v1.msgpack codec not implemented (F7)")
def test_s13_xfail_f7_msgpack_only_offer_negotiates_cv_v1_msgpack() -> None:
    """The single F7 pin (§2.2): the preferred subprotocol must be served."""
    w = World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=["cv.v1.msgpack"]) as ws:
        assert ws.accepted_subprotocol == "cv.v1.msgpack"
