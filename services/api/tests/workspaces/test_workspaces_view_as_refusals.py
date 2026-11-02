"""#5435: every `/workspaces*` write route is refused in a live view-as context, one test per route.

The real workspaces router behind the real view-as guard (`make_view_as_guard`), over the guard
tests' rig (`tests.unit.api.test_view_as_gate`): a write made while viewing answers
`403 view_as_read_only`, writes exactly one refusal record naming the viewer and the operation's
template, and never reaches the router (no store call, no router audit record). No sleep: the
clocks are fake.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from candleviewer.api.deny_by_default import rbac_permissions
from candleviewer.api.view_as_refusals import VIEW_AS_REFUSED
from candleviewer.api.workspaces import make_workspaces_router
from candleviewer.auth.models import SessionRecord
from tests.unit.admin.test_view_as_service import _VIEWER
from tests.unit.api.test_view_as_gate import _code, _Gate, _guard, _spec
from tests.workspaces._workspaces_api_env import LAYOUT, Audit, Env, wire

#: The router's write operations: (method, contract template) -> the body a client sends.
_WRITES: dict[tuple[str, str], dict[str, Any] | None] = {
    ("POST", "/workspaces"): {"name": "Scalping"},
    ("PUT", "/workspaces/{workspaceId}"): {"name": "Renamed"},
    ("DELETE", "/workspaces/{workspaceId}"): None,
    ("POST", "/workspaces/{workspaceId}/layouts"): LAYOUT,
    ("PUT", "/workspaces/{workspaceId}/layouts/{layoutId}"): LAYOUT | {"name": "Other"},
    ("DELETE", "/workspaces/{workspaceId}/layouts/{layoutId}"): None,
}
_SAFE = frozenset({"GET", "HEAD", "OPTIONS"})


class _Viewing:
    """The workspaces router as `USER_A`, guarded; the gate's rig holds a live context."""

    def __init__(self) -> None:
        self.env, self.gate = Env(), _Gate()
        app: Any = self.env.c.app
        app.middleware("http")(
            _guard(
                self.gate,
                permissions=rbac_permissions(_spec()),
                identity=self.gate.identity,
                denials=self.gate.writer,
            )
        )
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        self.wid = self.lid = ""

    async def seed(self) -> None:
        """A workspace with one layout, made outside any view-as session (no bearer)."""
        r = await self.client.post("/workspaces", json=wire({"name": "Main"}))
        assert r.status_code == 201, r.text
        self.wid = r.json()["id"]
        r = await self.client.post(
            f"/workspaces/{self.wid}/layouts", json=wire(LAYOUT, "LayoutInput")
        )
        assert r.status_code == 201, r.text
        self.lid = r.json()["id"]
        self.env.repo.calls.clear()
        self.env.audit.calls.clear()

    async def write(self, method: str, template: str, record: SessionRecord) -> Any:
        path = template.replace("{workspaceId}", self.wid).replace("{layoutId}", self.lid)
        body = _WRITES[(method, template)]
        model = "LayoutInput" if "layouts" in template else "WorkspaceInput"
        return await self.client.request(
            method,
            path,
            json=None if body is None else wire(body, model),
            headers={"Authorization": f"Bearer {record.id}"},
        )


async def _assert_refused_once(method: str, template: str) -> None:
    viewing = _Viewing()
    await viewing.seed()
    record = await viewing.gate.rig.viewing()
    response = await viewing.write(method, template, record)
    assert _code(response) == (403, "view_as_read_only")
    (only,) = viewing.gate.writer.records  # exactly one audit record: the refusal
    action, refusal, _ = only
    assert action == VIEW_AS_REFUSED and refusal["reason"] == "view_as_read_only"
    assert (refusal["actor_user_id"], refusal["session_id"]) == (_VIEWER, record.id)
    assert refusal["after_state"] == {"method": method, "path": template}
    assert viewing.env.repo.calls == [] and viewing.env.audit.calls == []  # never reached


async def test_create_workspace_live_view_as_refused_one_record() -> None:
    await _assert_refused_once("POST", "/workspaces")


async def test_update_workspace_live_view_as_refused_one_record() -> None:
    await _assert_refused_once("PUT", "/workspaces/{workspaceId}")


async def test_delete_workspace_live_view_as_refused_one_record() -> None:
    await _assert_refused_once("DELETE", "/workspaces/{workspaceId}")


async def test_create_layout_live_view_as_refused_one_record() -> None:
    await _assert_refused_once("POST", "/workspaces/{workspaceId}/layouts")


async def test_update_layout_live_view_as_refused_one_record() -> None:
    await _assert_refused_once("PUT", "/workspaces/{workspaceId}/layouts/{layoutId}")


async def test_delete_layout_live_view_as_refused_one_record() -> None:
    await _assert_refused_once("DELETE", "/workspaces/{workspaceId}/layouts/{layoutId}")


def test_workspaces_write_routes_each_have_a_view_as_refusal_test() -> None:
    """The routes above are every write the router mounts and every `/workspaces*` write the
    contract declares: a new write route fails here until it has its own refusal test."""
    mounted = {
        (method, route.path)
        for route in make_workspaces_router(lambda: None, None, Audit()).routes
        if isinstance(route, APIRoute) and route.path.startswith("/workspaces")
        for method in (route.methods or set()) - _SAFE
    }
    declared = {
        (method.upper(), path)
        for path, ops in _spec()["paths"].items()
        if re.match(r"/workspaces(/|$)", path)
        for method in ops
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
    }
    assert mounted == declared == set(_WRITES)
