"""E17-X02 AC-01 (#415, threat model `E17-ws-gateway.md` §7): no token path other than an `auth`
frame's `access_token` works. A token in the URL query string, in `hello` or in a `sub` option
authenticates nothing: the verifier is never asked, the 10 s window still ends the socket `bye
auth_timeout` + 4401, no audit row is written and the token reaches none of the gateway's sinks. A
token elsewhere in an `auth` frame is a missing token: three such frames end in `bye auth_failed`.
In process on the conformance gateway (fake clock, no sleeps), under both subprotocols.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from candleviewer.ws.limits import AUTH_TIMEOUT_S
from tests.security.ws._raw import Login, RawClient, RawWorld, delta, hello, raw_connect, strike_out

Place = Callable[[str], dict[str, Any]]
_QUERIES = ["access_token={t}", "token={t}&x=1", "Authorization={t}"]
_HELLO = {"t": "hello", "id": "h"}
_HELLOS: dict[str, Place] = {
    "in-p": lambda t: {**_HELLO, "p": {"client": "raw", "access_token": t}},
    "nested": lambda t: {**_HELLO, "p": {"client": "raw", "auth": {"access_token": t}}},
    "envelope": lambda t: {**_HELLO, "p": {"client": "raw"}, "access_token": t},
}


def _window_ends_it(world: RawWorld, c: RawClient) -> None:
    """The socket stayed unauthenticated, so the window closes it: `bye auth_timeout` + 4401."""
    assert AUTH_TIMEOUT_S == 10.0  # the model's window, which these tests step the clock by
    closes = delta("cv_ws_closes_total", reason="auth_timeout")
    world.clock.now += AUTH_TIMEOUT_S
    bye, code = c.bye_then_close()
    assert (bye["p"]["reason"], bye["p"]["code"], code) == ("auth_timeout", 4401, 4401)
    assert closes() == 1


def _unauthenticated(world: RawWorld, c: RawClient, login: Login) -> None:
    """Read after the handler's teardown: the verifier was never asked, no audit row was written
    (an unauthenticated close writes none, #2528) and the token is in no sink."""
    assert world.tokens_seen == []
    assert world.audit.records == []
    assert world.leaks(login.token, c) == []


@pytest.mark.parametrize("query", _QUERIES, ids=lambda q: q.split("=")[0])
def test_x02_ac_01_a_token_in_the_url_query_authenticates_nothing(
    world: RawWorld, query: str
) -> None:
    login = world.login("alice")
    with raw_connect(world, query.format(t=login.token)) as c:
        hello(c)
        world.clock.now += AUTH_TIMEOUT_S - 0.001  # the window is not cut short ...
        c.send({"t": "ping", "id": "p"})
        c.next_of("pong")
        _window_ends_it(world, c)  # ... and then it ends the socket
    _unauthenticated(world, c, login)


@pytest.mark.parametrize("place", _HELLOS.values(), ids=_HELLOS.keys())
def test_x02_ac_01_a_token_in_hello_authenticates_nothing(world: RawWorld, place: Place) -> None:
    login = world.login("alice")
    with raw_connect(world) as c:
        c.send(place(login.token))
        assert c.recv()["t"] == "welcome"
        _window_ends_it(world, c)
    _unauthenticated(world, c, login)


def test_x02_ac_01_a_token_in_a_sub_option_authenticates_nothing(world: RawWorld) -> None:
    login = world.login("alice")
    topic = {"ch": "book.BTCUSDT.50", "opts": {"access_token": login.token}}
    refused = delta("cv_ws_errors_total", code="not_authenticated")
    with raw_connect(world) as c:
        hello(c)
        c.send({"t": "sub", "id": "s", "p": {"topics": [topic]}})
        err = c.recv_err()
        assert (err["id"], err["p"]["code"]) == ("s", "not_authenticated")
        assert refused() == 1
        _window_ends_it(world, c)
    _unauthenticated(world, c, login)


def test_x02_ac_01_a_token_outside_access_token_is_a_missing_token(world: RawWorld) -> None:
    login = world.login("alice")
    placed: list[dict[str, Any]] = [  # in the envelope, under another key, not as a string
        {"t": "auth", "access_token": login.token},
        {"t": "auth", "p": {"token": login.token}},
        {"t": "auth", "p": {"access_token": {"value": login.token}}},
    ]
    with raw_connect(world) as c:
        hello(c)
        strike_out(world, c, placed, reason="missing_token", user=None)
    assert [r["action"] for r in world.audit.records] == ["auth.login_failed"]  # no close row
    assert world.tokens_seen == []
    assert world.leaks(login.token, c) == []
