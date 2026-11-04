"""#5435: every `/workspaces*` write route, and `exportWorkspace` (SR-E15-19), is refused in a live
view-as context, one test per route.

The real workspaces router behind the real view-as guard (`make_view_as_guard`), over the guard
tests' rig (`tests.unit.api.test_view_as_gate`): a write made while viewing answers
`403 view_as_read_only`, writes exactly one refusal record naming the viewer and the operation's
template, and never reaches the router (no store call, no router audit record). No sleep: the
clocks are fake.
"""

from __future__ import annotations

import re
from typing import Any, cast

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from starlette.routing import Match, Route

from candleviewer.api.deny_by_default import rbac_permissions
from candleviewer.api.view_as_guard import (
    _compile_refused_reads,
    _refused_read,
    make_view_as_guard,
)
from candleviewer.api.view_as_policy import (
    OWN_OPERATIONS,
    PROTECTIVE_WRITES,
    REFUSED_READ_OPERATIONS,
    REFUSED_READS,
)
from candleviewer.api.view_as_refusals import VIEW_AS_REFUSED
from candleviewer.api.workspaces import make_workspaces_router
from candleviewer.auth.models import SessionRecord
from tests.unit.admin.test_view_as_service import _VIEWER
from tests.unit.api.test_view_as_gate import _code, _declared, _Gate, _guard, _spec
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
#: The `/workspaces*` reads refused while viewing: `exportWorkspace`, not mounted until E15-S07.
_EXPORT = ("GET", "/workspaces/{workspaceId}/export")


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
        body = _WRITES.get((method, template))
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
        for route in make_workspaces_router(
            lambda: None, None, Audit(), catalogue=lambda: None
        ).routes
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
    # The whole refused set: a new refused read, in any path, fails here until it has its own test.
    assert dict(REFUSED_READS) == {"exportWorkspace": (_EXPORT, "E15-S07")}
    assert REFUSED_READ_OPERATIONS == {_EXPORT}


def _shared_operations(refused: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """The refused reads that are also the viewer's own or a protective write: the guard decides
    those first, so such a refusal would never be reached."""
    protective = {operation for operation, _ in PROTECTIVE_WRITES.values()}
    return refused & (OWN_OPERATIONS | protective)


def test_refused_reads_share_no_operation_with_own_or_protective_operations() -> None:
    assert _shared_operations(set(REFUSED_READ_OPERATIONS)) == set()


@pytest.mark.parametrize(
    "injected",
    [("GET", "/auth/session"), ("DELETE", "/orders/{orderId}")],
)
def test_an_injected_overlap_with_own_or_protective_operations_is_caught(
    injected: tuple[str, str],
) -> None:
    assert _shared_operations({*REFUSED_READ_OPERATIONS, injected}) == {injected}


def test_export_workspace_is_a_refused_read_of_the_contract() -> None:
    """SR-E15-19 (#5435): the policy names `exportWorkspace` by its operationId and its
    (METHOD, template), which the contract declares, and E15-S07 as the ticket that mounts it;
    22 says it is refused in a live view-as context."""
    assert REFUSED_READS["exportWorkspace"] == (_EXPORT, "E15-S07")
    operation = _spec()["paths"][_EXPORT[1]]["get"]
    assert operation["operationId"] == "exportWorkspace"
    assert "view_as_read_only" in " ".join(operation["description"].split())


async def test_export_workspace_live_view_as_refused_one_record() -> None:
    """Refused before routing, so the refusal holds before E15-S07 mounts the route."""
    await _assert_refused_once(*_EXPORT)


async def test_export_workspace_head_live_view_as_refused() -> None:
    """A refused HEAD's record names the `GET` template it reads, with its own method."""
    viewing = _Viewing()
    await viewing.seed()
    record = await viewing.gate.rig.viewing()
    response = await viewing.write("HEAD", _EXPORT[1], record)
    assert response.status_code == 403 and viewing.env.repo.calls == []
    (only,) = viewing.gate.writer.records
    assert only[1]["reason"] == "view_as_read_only"
    assert only[1]["after_state"] == {"method": "HEAD", "path": _EXPORT[1]}


#: Percent-encoded control characters; the server unquotes them into the routed path.
_CONTROLS = ("%0A", "%0a", "%0D", "%00")


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("suffix", _CONTROLS)
async def test_export_path_with_a_control_character_live_view_as_refused(
    method: str, suffix: str
) -> None:
    """#5435: a path with a control character is refused while viewing, for every method, with
    the CSRF layer's step 0 problem (`400 validation_failed`), before any routing or record."""
    viewing = _Viewing()
    await viewing.seed()
    record = await viewing.gate.rig.viewing()
    path = _EXPORT[1].replace("{workspaceId}", viewing.wid) + suffix
    response = await viewing.client.request(
        method, path, headers={"Authorization": f"Bearer {record.id}"}
    )
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    if method == "GET":
        assert _code(response) == (400, "validation_failed")
    assert viewing.env.repo.calls == [] and viewing.env.audit.calls == []
    assert viewing.gate.writer.records == []


@pytest.mark.parametrize("suffix", _CONTROLS)
async def test_path_with_a_control_character_without_view_as_unchanged(suffix: str) -> None:
    """The control-character refusal applies to a session holding a context only: a GET with no
    view-as session gets the router's answer, as before (the export route is not mounted yet)."""
    viewing = _Viewing()
    await viewing.seed()
    path = _EXPORT[1].replace("{workspaceId}", viewing.wid) + suffix
    response = await viewing.client.get(path)
    assert response.status_code == 404
    assert viewing.gate.writer.records == []


@pytest.mark.parametrize("suffix", ["", "\n", "\r", "\x00", "/", "/x", "\n\n"])
def test_refused_read_match_agrees_with_routing(suffix: str) -> None:
    """The guard's refused-read match and the router's route match agree on every path."""
    reads = _compile_refused_reads(REFUSED_READ_OPERATIONS)
    route = Route(_EXPORT[1], lambda _: None, methods=["GET"])
    path = "/workspaces/w1/export" + suffix
    for method in ("GET", "HEAD"):
        scope = {"type": "http", "method": method, "path": path, "root_path": ""}
        routed = route.matches(scope)[0] is Match.FULL
        assert (_refused_read(method, path, reads) == _EXPORT[1]) is routed


async def test_workspace_read_live_view_as_still_passes_as_target() -> None:
    """The refused set is that one read: the workspace itself still reads as the target."""
    viewing = _Viewing()
    await viewing.seed()
    record = await viewing.gate.rig.viewing()
    response = await viewing.write("GET", "/workspaces/{workspaceId}", record)
    assert response.status_code != 403 and viewing.gate.writer.records == []


def test_guard_build_refuses_an_undeclared_refused_read() -> None:
    with pytest.raises(ValueError, match="undeclared refused reads"):
        _guard_without(_EXPORT)


def _guard_without(operation: tuple[str, str]) -> Any:
    gate = _Gate()
    return make_view_as_guard(
        cast(Any, gate.auth), views=lambda: gate.service, refusals=lambda: gate.refusals,
        protective=gate.protective, operations=_declared() - {operation}, clock=gate.rig.clock,
    )  # fmt: skip
