"""SR-013 (#2101) through the real `create_app()`: HTTP, the CSRF guard, the step-up and users
routers, the B16 chart and the WebSocket gateway's revocation hub (the ruling's C-9 evidence;
Playwright on staging stays with #2491).

- A role change ends every session of its target: each of the target's sockets gets
  `bye session_revoked` and closes `4401`, the target's tokens are refused at REST and at
  refresh, and the actor's socket stays open (C-1, C-3). A refused caller ends nothing.
- A step-up rotates its session: the old bearer is refused at REST, the socket stays open and
  re-`auth`s in place with the new token, as after a refresh (C-3), and a replay of the old
  refresh token kills the family, that socket included (C-8).

`_stack.open_stack`: the real `AuthService` over the in-memory fakes, real password and TOTP
users, a fixed clock shared with the gateway; no network, no sleeps.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.owner_floor import assert_owner_floor
from candleviewer.ws.revocation import CLOSE_TOKEN_EXPIRED
from tests.csrf_helpers import csrf_headers
from tests.security.auth._stack import ORIGIN, PW, Grants, Stack, open_stack
from tests.security.auth.test_revocation_closes_sockets import _authenticate, _recv

_JSON = ["cv.v1.json"]
_PACED = 6  # the paced frames a read skips, at most (`test_disable_user_e2e._ended`, #5041)


def _paced(frame: dict[str, Any]) -> bool:
    """The pipeline's own §8.3 traffic, sent on its schedule when the flow crosses the probe
    interval (`test_lifecycle_socket._paced`): the RTT probe's `ping` (`s-rtt-…`) and the
    `connection_quality` notice. Neither is an application frame."""
    if frame["t"] == "ping":
        return str(frame.get("id", "")).startswith("s-rtt-")
    body = frame.get("p")
    quality = isinstance(body, dict) and body.get("kind") == "connection_quality"
    return frame["t"] == "d" and frame.get("ch") == "system" and quality


def _next(ws: Any) -> dict[str, Any]:
    """The next application frame: up to `_PACED` paced frames may come first."""
    frame = _recv(ws)
    for _ in range(_PACED):
        if not _paced(frame):
            break
        frame = _recv(ws)
    assert not _paced(frame), f"more than {_PACED} paced frames: {frame}"
    return frame


def _still_open(ws: Any) -> bool:
    """The socket answers a client `ping` with its `pong` (paced frames skipped)."""
    ws.send_json({"t": "ping", "id": "p", "p": {}})
    return _next(ws)["t"] == "pong"


class _Roles:
    """`UserRoleStore` in memory, as the SQL store runs it: the owner floor, then the write-ahead
    `audit` with the roles read under the lock, then the commit."""

    def __init__(self) -> None:
        self.roles: dict[uuid.UUID, frozenset[str]] = {}

    async def get_roles(self, user_id: uuid.UUID) -> frozenset[str] | None:
        return self.roles.get(user_id)

    async def get_status(self, user_id: uuid.UUID) -> str | None:
        return "active" if user_id in self.roles else None

    async def count_active_owners(self) -> int:
        return sum("owner" in held for held in self.roles.values())

    async def apply_roles(
        self,
        user_id: uuid.UUID,
        roles: frozenset[str],
        *,
        actor: uuid.UUID,
        audit: Callable[[frozenset[str]], Awaitable[None]],
    ) -> bool:
        if user_id not in self.roles:
            return False
        before = self.roles[user_id]
        owners = await self.count_active_owners()
        assert_owner_floor(current_roles=before, new_roles=roles, active_owner_count=owners)
        await audit(before)
        self.roles[user_id] = roles
        return True


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Stack, _Roles]]:
    """The stack with the role store, and a WS principal source (as the `ws_world` fixture's)."""
    roles = _Roles()
    with open_stack(monkeypatch, user_role_store=roles, snapshot_loader=Grants().load) as stack:
        yield stack, roles


def _connect(stack: Stack) -> Any:
    return stack.client.websocket_connect("/ws", subprotocols=_JSON, headers={"origin": ORIGIN})


def _bearer(headers: dict[str, str]) -> str:
    return headers["Authorization"].removeprefix("Bearer ")


def _change_roles(stack: Stack, actor: dict[str, str], target: uuid.UUID, seed: bytes) -> Any:
    """The owner's role change as the client sends it: refused with a challenge, answered with
    a step-up (which moves *actor* to the rotated session), then sent again."""
    path, body = f"/users/{target}/roles", {"roles": ["viewer"]}
    challenged = stack.client.put(path, headers=actor, json=body)
    assert challenged.json()["code"] == "step_up_required", challenged.text
    granted = stack.step_up(actor, seed, challenged.json()["challenge_id"])
    assert granted.status_code == 200, granted.text
    return stack.client.put(path, headers=actor, json=body)


def test_a_role_change_ends_every_session_of_the_target_over_http_and_its_sockets(
    world: tuple[Stack, _Roles],
) -> None:
    stack, roles = world
    owner, owner_seed = stack.principal("owner-a", "owner", *Permission)
    target, _seed = stack.principal("target-m", "manager")
    owner_id = stack.resolver.by_token[_bearer(owner)].user_id
    target_id = stack.resolver.by_token[_bearer(target)].user_id
    roles.roles.update({owner_id: frozenset({"owner"}), target_id: frozenset({"manager"})})
    second = stack.call(stack.auth.sessions.mint, str(target_id))
    with _connect(stack) as ws_phone, _connect(stack) as ws_desk, _connect(stack) as ws_owner:
        assert _authenticate(ws_phone, _bearer(target))["t"] == "auth_ok"
        assert _authenticate(ws_desk, second.access_token)["t"] == "auth_ok"
        assert _authenticate(ws_owner, _bearer(owner))["t"] == "auth_ok"

        changed = _change_roles(stack, owner, target_id, owner_seed)

        assert changed.status_code == 200, changed.text
        assert changed.json() == {"id": str(target_id), "roles": ["viewer"]}
        for ws in (ws_phone, ws_desk):
            bye = _next(ws)
            assert bye["t"] == "bye", str(bye)  # named: the frame that came instead
            assert (bye["t"], bye["p"]["reason"]) == ("bye", "session_revoked")
            assert bye["p"]["code"] == CLOSE_TOKEN_EXPIRED  # 4401
        # The owner's socket stays: its step-up rotated the owner's session, which publishes
        # nothing, and the role change ends only the target's sessions.
        assert _still_open(ws_owner)
    assert stack.client.get("/auth/session", headers=target).status_code == 401
    sid = stack.call(stack.auth.sessions.peek_access_token, second.access_token).id
    refreshed = stack.client.post(
        "/auth/refresh",
        headers=csrf_headers(stack.state.csrf_codec, sid),
        json={"refresh_token": second.refresh_token},
    )
    assert (refreshed.status_code, refreshed.json()["code"]) == (401, "refresh_token_invalid")
    revoked = stack.audit.of("auth.session_revoked")
    ended = [r for r in revoked if r["reason"] == "role_changed"]
    assert {r["session_id"] for r in ended} == {
        str(stack.call(stack.auth.sessions.peek_access_token, _bearer(target)).id),
        str(sid),
    }
    assert stack.client.get("/auth/session", headers=owner).status_code == 200


def test_a_refused_role_change_ends_no_session(world: tuple[Stack, _Roles]) -> None:
    """The forbidden-role case: a manager's call is refused before anything is recorded."""
    stack, roles = world
    manager, _ = stack.principal("manager-b", "manager")
    target, _ = stack.principal("target-n", "manager")
    target_id = stack.resolver.by_token[_bearer(target)].user_id
    roles.roles[target_id] = frozenset({"manager"})
    with _connect(stack) as ws:
        assert _authenticate(ws, _bearer(target))["t"] == "auth_ok"

        refused = stack.client.put(
            f"/users/{target_id}/roles", headers=manager, json={"roles": ["viewer"]}
        )

        assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
        assert _still_open(ws)
    assert stack.client.get("/auth/session", headers=target).status_code == 200
    assert not stack.audit.of("auth.session_revoked")


def test_a_step_up_socket_reauths_in_place_and_the_old_bearer_is_refused(
    world: tuple[Stack, _Roles],
) -> None:
    stack, _roles = world
    headers, seed = stack.principal("owner-c", "owner", *Permission)
    old = dict(headers)
    with _connect(stack) as ws:
        assert _authenticate(ws, _bearer(old))["t"] == "auth_ok"
        body = {"code": stack.code(seed), "password": PW, "action_class": "users"}

        granted = stack.client.post("/auth/step-up", headers=headers, json=body)

        assert granted.status_code == 200, granted.text
        assert _still_open(ws), "a step-up's rotation is no revocation (23 section 4.1)"
        new = granted.json()["tokens"]["access_token"]
        ws.send_json({"t": "auth", "id": "r", "p": {"access_token": new}})
        ok = _next(ws)
        assert ok["t"] == "auth_ok"
        assert ok["p"]["session_id"] == str(
            stack.call(stack.auth.sessions.peek_access_token, new).id
        )
    assert stack.client.get("/auth/session", headers=old).status_code == 401
    stack.adopt(headers, new)
    assert stack.client.get("/auth/session", headers=headers).status_code == 200


def test_a_replayed_pre_step_up_refresh_token_kills_the_family_and_its_socket(
    world: tuple[Stack, _Roles],
) -> None:
    """C-8: a client that lost the `200` keeps only the old tokens: its refresh trips reuse
    detection, which revokes the new session too and closes the socket now on it."""
    stack, _roles = world
    uid, seed = stack.add_user("owner-d")
    minted = stack.call(stack.auth.sessions.mint, str(uid))  # the step-up reads no principal
    headers = {
        "Authorization": f"Bearer {minted.access_token}",
        **csrf_headers(stack.state.csrf_codec, minted.session_id),
    }
    body = {"code": stack.code(seed), "password": PW, "action_class": "users"}
    granted = stack.client.post("/auth/step-up", headers=headers, json=body)
    assert granted.status_code == 200, granted.text
    new = granted.json()["tokens"]["access_token"]
    with _connect(stack) as ws:
        assert _authenticate(ws, new)["t"] == "auth_ok"

        replay = stack.client.post(
            "/auth/refresh",
            headers=csrf_headers(stack.state.csrf_codec, minted.session_id),
            json={"refresh_token": minted.refresh_token},
        )

        assert (replay.status_code, replay.json()["code"]) == (401, "refresh_token_invalid")
        bye = _next(ws)
        assert (bye["t"], bye["p"]["reason"]) == ("bye", "session_revoked")
    gone = stack.client.get("/auth/session", headers={"Authorization": f"Bearer {new}"})
    assert gone.status_code == 401
