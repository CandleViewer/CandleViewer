"""E28-X03 (#976): the `trade_groups` topic's scope, end to end through `create_app()`'s gateway.

`tests/security/ws/test_account_scope.py` proves narrowing, refusal and the no-frame rule for every
account-scoped family on the conformance gateway, and `tests/unit/ws/test_trade_groups_scope.py`
the topic on a bare hub. This extends them to the app as composed: the topic `create_app()` builds
and serves (captured, seeded with a group per situation), the RBAC pack's actors, and every frame
a socket is sent read off the wire:

- the topic row of `matrix.yaml` holds for each actor, asking for the granted, the foreign and an
  absent account at once: the Owner's `sub` is every group, `manager_with_grant`'s is narrowed
  silently (an `ok` result whose `effective` names its grant alone, the narrowing audited, never
  answered), and the others are refused as the row says;
- no frame, the `sub_ok`, the snapshot and every delta included, ever names an account the caller
  does not hold; a group with one leg outside the grants is never sent, not even in part
  (SR-E28-21), while the granted one is.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from tests.contract.rbac.rbac_harness import ABSENT, ACTORS, FOREIGN, GRANTED, actor_grants
from tests.contract.rbac.test_scope_and_ws import _MARK, _auth, _recv
from tests.security.e28 import _cells as cells
from tests.security.e28._world import E28World
from tests.unit.accounts.test_trade_group_topic import _stored

_ASKED = (GRANTED, FOREIGN, ABSENT)
#: One group per situation, seeded before any socket.
_SEEDED = [_stored(21, GRANTED), _stored(22, FOREIGN), _stored(23, GRANTED, FOREIGN)]
_LEGS: dict[str, set[Any]] = {}  # every group the topic was given: its legs' accounts


def _later(actor: str) -> list[Any]:
    """The groups created while `actor`'s socket listens, the granted one last: ids of its own,
    so no test depends on another's."""
    n = 40 + 10 * ACTORS.index(actor)
    legs = [(FOREIGN,), (FOREIGN, GRANTED), (ABSENT,), (GRANTED,)]
    return [_stored(n + i, *accounts) for i, accounts in enumerate(legs)]


def _known(*groups: Any) -> None:
    _LEGS.update({str(g.group.group_id): {leg.account_id for leg in g.legs} for g in groups})


@pytest.fixture(scope="module")
def seeded(_e28: E28World) -> Iterator[E28World]:
    _known(*_SEEDED)
    _e28.topic.seed(_SEEDED)  # once: the topic refuses a second seed
    yield _e28


def _ids(frames: list[dict[str, Any]]) -> set[str]:
    return {
        str(item["id"])
        for f in frames
        if f.get("ch") == cells.WS_TOPIC and isinstance(f.get("p"), dict)
        for item in f["p"].get("trade_groups", [])
    }


def _read(ws: Any, hub: Any, until: str) -> list[dict[str, Any]]:
    """Every frame up to the one carrying group `until`, then up to a marker broadcast after it,
    so whatever was queued behind it is read too; pings are answered (`_until_body`'s rule)."""
    frames: list[dict[str, Any]] = []
    marks = sent = 0

    def mark() -> None:
        nonlocal sent
        ws.portal.call(hub.broadcast_system, _MARK)
        sent += 1

    mark()
    while until not in _ids(frames) or marks < sent:
        frame = _recv(ws)
        if frame["t"] == "ping":
            ws.send_json({"t": "pong", "id": frame["id"]})
        elif frame.get("p") == _MARK:
            marks += 1
        else:
            frames.append(frame)
            if until in _ids([frame]):
                mark()
    return frames


def _code(reply: dict[str, Any]) -> str:
    if reply["t"] != "sub_ok":
        return str(reply["p"]["code"])
    (result,) = reply["p"]["results"]
    return "sub_ok" if result["ok"] else str(result["error"]["code"])


@pytest.mark.parametrize("actor", list(cells.ws_outcomes()))
def test_a_trade_groups_sub_beyond_the_grants_is_narrowed_or_refused_and_never_echoed(
    seeded: E28World, actor: str
) -> None:
    world, hub, want = seeded.writes.world, seeded.app.state.ws_hub, cells.ws_outcomes()[actor]
    held = set(_ASKED) if actor == "owner" else set(actor_grants(actor))
    seeded.reset()
    later = _later(actor)
    _known(*later)
    entry = {"ch": cells.WS_TOPIC, "opts": {"exchange_account_ids": [str(a) for a in _ASKED]}}
    with world.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        if actor == "unauthenticated":
            ws.send_json({"t": "hello", "id": "h"})
            assert _recv(ws)["t"] == "welcome"
        else:
            assert _auth(ws, actor)["t"] == "auth_ok"
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": [entry]}})
        frames = [reply := _recv(ws)]
        assert _code(reply) == want, reply
        if want == "sub_ok":  # narrowed silently: an `ok` result, its scope the grants alone
            effective = reply["p"]["results"][0]["effective"]["exchange_account_ids"]
            assert {str(a) for a in effective} == {str(a) for a in _ASKED if a in held}
            for group in later:  # created while the socket listens, the granted one last
                ws.portal.call(seeded.topic.created, group)
            frames += _read(ws, hub, str(later[-1].group.group_id))
    sent = json.dumps(frames)
    assert not [a for a in _ASKED if a not in held and str(a) in sent], "a denied id was echoed"
    assert all(_LEGS[g] <= held for g in _ids(frames)), "a group with a leg outside the grants"
    if want == "sub_ok":  # and every group the grants cover is sent: the seeded and the later
        mine = [g for g in [*_SEEDED, *later] if _LEGS[str(g.group.group_id)] <= held]
        assert {str(g.group.group_id) for g in mine} <= _ids(frames)
    reasons = [r["reason"] for r in seeded.records if r["action"] == "ws.subscribe.denied"]
    narrowed = ["narrowed"] if actor == "manager_with_grant" else []
    assert reasons == (["account_scope_denied"] if want == "account_scope_denied" else narrowed)
