"""#3085 S9 (plan section 4, item 6): every record a viewing session causes names the viewer.

While the Owner's session views as a user, each request it sends is read in the target's scope,
refused read-only, or, for the viewer's own and the protective operations, served as the viewer.
Every audit record any of them writes (a denied read's `rbac.denied`, a refused write's
`admin.view_as_refused`, ...) names the viewer as its actor, never the target, and a record that
names a session names the viewer's own: S8 splits the actor from the subject, and the app's
emitter refuses a record that names the target as its actor. (`rbac.denied` on the `users:write`
routes names no session for any caller; that predates view-as.) Each executed operation of
`matrix.yaml` that acts in a session is sent once per target: not the viewer's own, and not one
the unauthenticated caller may use, as an invite's redemption, which acts without the session.
The world is `test_route_matrix.py`'s: the real app with the identity and backend seams faked, no
network (C-13.5).
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from candleviewer.api.view_as_policy import OWN_OPERATIONS
from tests.contract.rbac.rbac_harness import (
    MATRIX_PATH,
    VIEW_TARGETS,
    World,
    bearer_viewing,
    fill_path,
    session_id_of,
    user_id_of,
)

with MATRIX_PATH.open(encoding="utf-8") as _fh:
    _OPS: dict[str, dict[str, Any]] = yaml.safe_load(_fh)["operations"]

#: Every executed operation that acts in the session, but the viewer's own (leave, logout,
#: refresh, ...), which act on the viewer's session itself.
_SENT = tuple(
    key
    for key, row in _OPS.items()
    if row["state"] == "executed"
    and row["outcomes"]["unauthenticated"] != "allow"
    and tuple(key.split(" ", 1)) not in OWN_OPERATIONS
)


def _send_all(world: World, target: str) -> None:
    for key in _SENT:
        method, path = key.split(" ", 1)
        req = _OPS[key].get("request", {})
        body = req.get("json")
        world.client.request(
            method,
            fill_path(path, req.get("path")),
            params=req.get("params"),
            json=body if body is not None else ({} if method in ("POST", "PUT", "PATCH") else None),
            headers={**bearer_viewing(target), **req.get("headers", {})},
        )


@pytest.mark.parametrize("target", VIEW_TARGETS)
def test_every_record_names_the_viewer_as_its_actor(world: World, target: str) -> None:
    _send_all(world, target)
    actors = {(r["action"], str(r.get("actor_user_id"))) for r in world.audit.records}
    viewer = str(user_id_of("owner"))
    assert actors and {actor for _, actor in actors} == {viewer}, sorted(actors)


@pytest.mark.parametrize("target", VIEW_TARGETS)
def test_a_record_naming_a_session_names_the_viewers(world: World, target: str) -> None:
    _send_all(world, target)
    named = {str(r["session_id"]) for r in world.audit.records if r.get("session_id") is not None}
    assert named == {str(session_id_of("owner", viewing=target))}
