"""E09-X02 information-disclosure case AC-INFO-01 (X01 U26; finding F-8, #298).

Before authentication a client is given the build label, never the exact build. On the WS,
`welcome` carries no git sha (`23-ws-protocol.md` §2.3, §4.3), and nor do the `err` and `bye`
frames or the close of a socket that fails to authenticate, that never authenticates (the auth
window's `auth_timeout`), or that arrives at a full house (`server_shedding_load`). On REST
(#4222), the probes
`/healthz` and `/readyz` give the label (`version`) and the `environment`, and no key or text of
their body names the build: not when ready, not when degraded; `/health/live` and `/health/ready`
never did. After authentication the sha is served as it was: in `auth_ok` on a first auth and an
in-place re-auth alike, and in an Owner's `GET /admin/health`; and `getBuildInfo` declares it as
`commit`. Those cases are the control: the sha is configured, so its absence before authentication
is not vacuous. In process, through the real `create_app()` stack of `_stack.py` (the degraded
probe and the schema cases say how they differ): no credential is presented before the `auth`,
and there is no network.
"""

from __future__ import annotations

import contextlib
import functools
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

import candleviewer.app as appmod
from candleviewer.api._generated.openapi_models import BuildInfo as ContractBuildInfo
from candleviewer.api.health import make_health_router
from candleviewer.api.models import LivenessResponse, ReadinessResponse
from candleviewer.auth.generated_permissions import Permission
from candleviewer.observability.health_probes import HOT_TIER_WRITE_BEHIND
from candleviewer.settings import Settings
from candleviewer.ws.gateway import GatewayHub

from ._stack import Grants, Stack, open_stack
from .test_ws_abuse import _ORDERS, _auth, _connect, _full_session, _hello, _recv

_LABEL = "9.8.7"  # `CV_VERSION`: the build label, which any client may read
_SHA = "0f8e09ac2b1d"  # `CV_GIT_SHA`: a made-up build sha, not a commit of this repository
_PREFIX = _SHA[:7]  # the short form of a commit names a build as well as the whole sha
#: What the app serves with no credential: `/healthz` and `/readyz` (#4222), and the contract's
#: `getLiveness` and `getReadiness`, at their contract paths (the `/api/v1` server base is not
#: routed by the app).
_LABELLED_PROBES = ["/healthz", "/readyz"]
_PROBES = [*_LABELLED_PROBES, "/health/live", "/health/ready"]


@contextlib.contextmanager
def _open(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    """The shared abuse-case stack with a WS principal source, built with a known label and
    sha (`get_settings()` reads the environment afresh for every app)."""
    monkeypatch.setenv("CV_VERSION", _LABEL)
    monkeypatch.setenv("CV_GIT_SHA", _SHA)
    with open_stack(monkeypatch, snapshot_loader=Grants().load) as s:
        yield s


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    with _open(monkeypatch) as s:
        yield s


@pytest.fixture
def window_stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    """`stack` with the auth window cut to 0.2 s (`CV_WS_AUTH_TIMEOUT_S`), so a socket that never
    authenticates is closed by it inside a test's own deadline: the gateway runs on the real
    clock here, and nothing sleeps."""
    monkeypatch.setenv("CV_WS_AUTH_TIMEOUT_S", "0.2")
    with _open(monkeypatch) as s:
        yield s


@pytest.fixture
def full_house_stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    """`stack` whose gateway admits one socket awaiting `auth` (the cap, 64, is a `GatewayHub`
    argument that no setting reaches), so the second one is shed."""
    monkeypatch.setattr(appmod, "GatewayHub", functools.partial(GatewayHub, max_unauthenticated=1))
    with _open(monkeypatch) as s:
        yield s


def _welcome(stack: Stack) -> dict[str, Any]:
    with _connect(stack) as ws:
        ws.send_json({"t": "hello", "id": "h"})
        return _recv(ws)


def _assert_no_sha(seen: object) -> None:
    """Neither the sha nor its 7-character prefix is anywhere in `seen` (frames, a close reason,
    the text of a response body)."""
    text = seen if isinstance(seen, str) else json.dumps(seen)
    assert _SHA not in text
    assert _PREFIX not in text


def _keys(node: object) -> Iterator[str]:
    """Every object key anywhere in a decoded JSON body."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _keys(item)


#: The labelled probes' whole bodies: no member but these may reach an unauthenticated caller.
_PROBE_KEYS = {
    "/healthz": {"status", "version", "environment"},
    "/readyz": {
        "status",
        "checks",
        "mesh_binding_safe",
        "mesh_reason_code",
        "version",
        "environment",
    },
}


def _assert_probe_gives_no_sha(response: Response) -> None:
    """A probe that answered, whose body has no `git_sha` key at any depth and whose text has
    neither the sha nor its prefix (so no other key, and no `version` suffix, carries it)."""
    assert response.status_code == 200
    assert "git_sha" not in set(_keys(response.json()))
    _assert_no_sha(response.text)
    _assert_no_sha(dict(response.headers))


def _closed_by(ws: Any) -> tuple[dict[str, Any], WebSocketDisconnect]:
    """The `bye` a server sends to end a socket, and the close that follows it."""
    bye = _recv(ws)
    with pytest.raises(WebSocketDisconnect) as close:
        _recv(ws)
    return bye, close.value


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


def test_ac_info_01_auth_window_close_gives_neither_the_sha_nor_its_prefix(
    window_stack: Stack,
) -> None:
    """A socket that sends nothing is ended by the auth window: `bye auth_timeout` and 4401."""
    with _connect(window_stack) as ws:
        bye, close = _closed_by(ws)
    assert (bye["t"], bye["p"]["reason"], close.code) == ("bye", "auth_timeout", 4401)
    _assert_no_sha([bye, close.reason])


def test_ac_info_01_shed_close_gives_neither_the_sha_nor_its_prefix(
    full_house_stack: Stack,
) -> None:
    """With the one admitted socket awaiting `auth`, the next is shed at once: `bye
    server_shedding_load` and 1013, before any frame of its own is read."""
    with _connect(full_house_stack) as waiting:
        _hello(waiting)  # its `welcome`: it is the socket the hub counts
        with _connect(full_house_stack) as shed:
            bye, close = _closed_by(shed)
    assert (bye["t"], bye["p"]["reason"], close.code) == ("bye", "server_shedding_load", 1013)
    _assert_no_sha([bye, close.reason])


@pytest.mark.parametrize("path", _PROBES)
def test_ac_info_01_health_probe_before_auth_gives_no_sha(stack: Stack, path: str) -> None:
    """#4222: no credential, and no probe names the build: no `git_sha` key, and neither the sha
    nor its prefix in the body text (any other key, or a `version` with the sha appended)."""
    _assert_probe_gives_no_sha(stack.client.get(path))


@pytest.mark.parametrize("path", _LABELLED_PROBES)
def test_ac_info_01_health_probe_still_gives_the_build_label_and_the_environment(
    stack: Stack, path: str
) -> None:
    """The control for the case above: the probes still answer with the label and the
    environment, so the sha's absence is not an empty or changed body."""
    body = stack.client.get(path).json()
    environment = stack.state.app_context.settings.environment.value
    assert (body["version"], body["environment"]) == (_LABEL, environment)
    assert set(body) == _PROBE_KEYS[path]  # a new member is a deliberate change (lens F3)


class _Retrying:
    """A hot-tier write-behind buffer that is retrying: its `/readyz` check fails (#1918)."""

    degraded = True


def test_ac_info_01_degraded_readyz_before_auth_gives_no_sha() -> None:
    """The stack has no seam that fails a check, so `make_health_router` (what the app mounts) is
    bound to a retrying buffer directly: ready and degraded answers take the build facts from
    one place, and the degraded one gives no sha either."""
    app = FastAPI()
    settings = Settings(git_sha=_SHA, version=_LABEL)
    app.include_router(make_health_router(settings, write_behind=lambda: [_Retrying()]))
    response = TestClient(app).get("/readyz")
    body = response.json()
    assert (body["status"], body["checks"]) == (
        "degraded",
        [{"name": HOT_TIER_WRITE_BEHIND, "ok": False, "detail": ""}],
    )
    assert (body["version"], body["environment"]) == (_LABEL, settings.environment.value)
    _assert_probe_gives_no_sha(response)


@pytest.mark.parametrize("model", [LivenessResponse, ReadinessResponse])
def test_ac_info_01_probe_bodies_have_no_sha_member_and_refuse_one(
    model: type[LivenessResponse] | type[ReadinessResponse],
) -> None:
    """The probe models are `extra="forbid"` and hold no sha: handing one to a probe body is an
    error, not a response, so a restored `git_sha` in `_build_info` alone breaks the probes."""
    assert "git_sha" not in model.model_fields
    with pytest.raises(ValidationError):
        model(git_sha=_SHA, version=_LABEL, environment="demo")


def test_ac_info_01_admin_health_gives_the_sha_to_an_authenticated_owner(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the probes: the sha they withhold is served, unchanged, by `GET
    /admin/health` (`getHealth`, `admin:read`) once an Owner is authenticated, and the same
    route gives nothing to a caller with no credential. The admin guard reads the stack's fake
    identity store, which knows only a Viewer, so that live instance answers for an Owner."""

    async def owner(user_id: str) -> dict[str, Any]:
        return {"id": user_id, "username": "owner", "roles": ["owner"], "status": "active"}

    async def grants(_user_id: str) -> dict[str, Any]:
        return {"permissions": [Permission.ADMIN_READ.value], "account_scope": []}

    monkeypatch.setattr(stack.state.identity_provider, "user", owner)
    monkeypatch.setattr(stack.state.identity_provider, "session_info", grants)
    bearer = {"Authorization": f"Bearer {_full_session(stack).access_token}"}
    # the snapshot the report reads: no health ticker runs in this stack
    stack.call(stack.state.health_registry.refresh)
    refused = stack.client.get("/admin/health")
    report = stack.client.get("/admin/health", headers=bearer)
    assert refused.status_code == 401
    _assert_no_sha(refused.text)
    assert report.status_code == 200
    assert (report.json()["version"], report.json()["git_sha"]) == (_LABEL, _SHA)


def test_ac_info_01_get_build_info_declares_the_sha_as_the_required_commit() -> None:
    """`getBuildInfo` (`GET /system/build`, any authenticated user: the RBAC matrix row) is in the
    contract but not mounted yet, so its control is the contract's own schema: the build is the
    required `commit` there, as it is `git_sha` in `auth_ok`. The two names are the two contracts'
    own (22 and 23): renaming either is a contract change, not part of this case. When the route
    is mounted (`E49-K01-F4-baseline`), its response-level case joins this one."""
    assert ContractBuildInfo.model_fields["commit"].is_required()
    assert "git_sha" not in ContractBuildInfo.model_fields


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
