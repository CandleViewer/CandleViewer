"""E09-X02 information-disclosure case AC-INFO-01 (X01 U26; finding F-8, #298).

Before authentication a WS client is given the build label, never the exact build: `welcome`
carries no git sha (`23-ws-protocol.md` §2.3, §4.3), and nor do the `err` and `bye` frames and
the close of a socket that fails to authenticate. After `auth` the sha comes in `auth_ok`, on a
first auth and on an in-place re-auth alike; those cases are the control: the sha is configured,
so its absence before authentication is not vacuous. In process through the real `create_app()`
stack of `_stack.py`: no credential is presented before the `auth`, and there is no network. The
health probes' half is #4222's, behind the deploy smoke test's switch (#4221).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

from ._stack import Grants, Stack, open_stack
from .test_ws_abuse import _ORDERS, _auth, _connect, _full_session, _hello, _recv

_LABEL = "9.8.7"  # `CV_VERSION`: the build label, which any client may read
_SHA = "0f8e09ac2b1d"  # `CV_GIT_SHA`: a made-up build sha, not a commit of this repository
_PREFIX = _SHA[:7]  # the short form of a commit names a build as well as the whole sha


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    """The shared abuse-case stack with a WS principal source, built with a known label and
    sha (`get_settings()` reads the environment afresh for every app)."""
    monkeypatch.setenv("CV_VERSION", _LABEL)
    monkeypatch.setenv("CV_GIT_SHA", _SHA)
    with open_stack(monkeypatch, snapshot_loader=Grants().load) as s:
        yield s


def _welcome(stack: Stack) -> dict[str, Any]:
    with _connect(stack) as ws:
        ws.send_json({"t": "hello", "id": "h"})
        return _recv(ws)


def _assert_no_sha(seen: object) -> None:
    """Neither the sha nor its 7-character prefix is anywhere in `seen` (frames, a close reason)."""
    text = json.dumps(seen)
    assert _SHA not in text
    assert _PREFIX not in text


def test_ac_info_01_welcome_before_auth_gives_the_label_never_the_sha(stack: Stack) -> None:
    welcome = _welcome(stack)
    assert (welcome["t"], welcome["p"]["server_version"]) == ("welcome", _LABEL)
    assert "git_sha" not in welcome["p"]
    _assert_no_sha(welcome)


def test_ac_info_01_failed_pre_auth_sequence_gives_neither_the_sha_nor_its_prefix(
    stack: Stack,
) -> None:
    """A `sub` before `auth`, then bad tokens until the third ends the socket (AC-WS-02): no
    frame of that transcript, and no close reason, carries the sha whole or truncated."""
    with _connect(stack) as ws:
        ws.send_json({"t": "hello", "id": "h"})
        frames = [_recv(ws)]
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": [_ORDERS]}})
        frames.append(_recv(ws))
        frames += [_auth(ws, "a-token-this-server-never-issued") for _ in range(3)]
        with pytest.raises(WebSocketDisconnect) as close:
            _recv(ws)
    assert [f["t"] for f in frames] == ["welcome", "err", "err", "err", "bye"]  # the path ran
    assert (frames[-1]["p"]["reason"], close.value.code) == ("auth_failed", 4401)
    _assert_no_sha([frames, close.value.reason])


def test_ac_info_01_auth_ok_gives_the_sha_after_authentication(stack: Stack) -> None:
    """The control: the sha withheld above is configured, and an authenticated socket gets it."""
    minted = _full_session(stack)
    with _connect(stack) as ws:
        _hello(ws)
        ok = _auth(ws, minted.access_token)
    assert (ok["t"], ok["p"]["git_sha"]) == ("auth_ok", _SHA)


def test_ac_info_01_in_place_re_auth_gives_the_sha_again(stack: Stack) -> None:
    """§4.3: a token refresh re-`auth`s the socket, and its `auth_ok` carries the sha again."""
    minted = _full_session(stack)
    with _connect(stack) as ws:
        _hello(ws)
        replies = [_auth(ws, minted.access_token) for _ in range(2)]
    assert [(r["t"], r["p"]["git_sha"]) for r in replies] == [("auth_ok", _SHA)] * 2
