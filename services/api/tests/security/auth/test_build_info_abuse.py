"""E09-X02 information-disclosure case AC-INFO-01 (X01 U26; finding F-8, #298).

Before authentication a WS client is given the build label, never the exact build: `welcome`
carries no git sha (`23-ws-protocol.md` §2.3, §4.3). After `auth` the sha comes in `auth_ok`;
that case is the control: the sha is configured, so its absence before authentication is not
vacuous. In process through the real `create_app()` stack of `_stack.py`: no credential is
presented before the `auth`, and there is no network. The health probes' half is #4222's, behind
the deploy smoke test's switch (#4221).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from ._stack import Grants, Stack, open_stack
from .test_ws_abuse import _auth, _connect, _full_session, _recv

_LABEL = "9.8.7"  # `CV_VERSION`: the build label, which any client may read
_SHA = "0f8e09ac2b1d"  # `CV_GIT_SHA`: a made-up build sha, not a commit of this repository


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


def test_ac_info_01_welcome_before_auth_gives_the_label_never_the_sha(stack: Stack) -> None:
    welcome = _welcome(stack)
    assert (welcome["t"], welcome["p"]["server_version"]) == ("welcome", _LABEL)
    assert "git_sha" not in welcome["p"]
    assert _SHA not in json.dumps(welcome)


def test_ac_info_01_auth_ok_gives_the_sha_after_authentication(stack: Stack) -> None:
    """The control: the sha withheld above is configured, and an authenticated socket gets it."""
    minted = _full_session(stack)
    with _connect(stack) as ws:
        ws.send_json({"t": "hello", "id": "h"})
        assert _recv(ws)["t"] == "welcome"
        ok = _auth(ws, minted.access_token)
    assert (ok["t"], ok["p"]["git_sha"]) == ("auth_ok", _SHA)
