"""#3085: a read of another user's object, made while viewing, is recorded as the viewer's.

The workspaces, alerts and alert-deliveries reads answer as the target while a session views as it
(Q2), so a foreign id is the target's to be refused. Each refusal's record names the viewer as its
actor, as every record a viewing session causes does, and the app's tripwire would refuse a record
naming the target (`_LazyAuditEmitter`). The deliveries denial spends the viewer's own budget.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.testclient import TestClient

from candleviewer.api.alert_deliveries import DenialBudget
from candleviewer.api.workspaces import make_workspaces_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.view_as import ViewAsPhase, ViewAsRequestContext, bound_view_as
from tests.alerts._alert_api_env import USER_B as ALERT_USER_B
from tests.alerts._alert_api_env import Env as AlertsEnv
from tests.alerts._deliveries_env import ALERT_B
from tests.alerts._deliveries_env import Env as DeliveriesEnv
from tests.workspaces._workspaces_api_env import PERMS, SID, USER_A, USER_B
from tests.workspaces._workspaces_api_env import Env as WorkspacesEnv

_VIEWER = uuid.UUID("00000000-0000-4000-8000-0000000000d1")


def _bound_while_viewing(target: str) -> Callable[..., Awaitable[Response]]:
    """Binds the context the view-as guard binds for `_VIEWER`'s session viewing as `target`."""
    context = ViewAsRequestContext(
        viewer_user_id=_VIEWER,
        viewer_session_id=uuid.uuid4(),
        viewer_label="owner-anna",
        target_user_id=uuid.UUID(target),
        context_id=uuid.uuid4(),
        subject_user_id=uuid.UUID(target),
        phase=ViewAsPhase.LIVE,
    )

    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Any:
        with bound_view_as(context):
            return await call_next(request)

    return guard


# --- workspaces: the principal carries the viewer as its actor ------------------------------------


class _ViewingPrincipal:
    """`USER_A`'s principal as the session resolver builds it while `_VIEWER` views as it."""

    async def resolve(self, _request: Request) -> AuditPrincipal:
        return AuditPrincipal(
            USER_A,
            "manager-ben",
            frozenset(PERMS[USER_A]),
            session_id=SID,
            actor_user_id=_VIEWER,
            actor_username="owner-anna",
        )


def _workspaces_while_viewing(env: WorkspacesEnv) -> TestClient:
    app = FastAPI()
    app.include_router(make_workspaces_router(lambda: env.repo, _ViewingPrincipal(), env.audit))
    return TestClient(app)


def test_a_foreign_workspace_read_while_viewing_is_recorded_as_the_viewers() -> None:
    env = WorkspacesEnv().as_user(USER_B)
    theirs = env.create()
    assert _workspaces_while_viewing(env).get(f"/workspaces/{theirs['id']}").status_code == 404
    (denied,) = env.audit.denied()
    assert (denied["actor_user_id"], denied["actor_label"]) == (_VIEWER, str(_VIEWER))


def test_a_foreign_layout_read_while_viewing_is_recorded_as_the_viewers() -> None:
    env = WorkspacesEnv().as_user(USER_B)
    theirs = env.create()
    layout = env.make_layout(theirs["id"])
    path = f"/workspaces/{theirs['id']}/layouts/{layout['id']}"
    assert _workspaces_while_viewing(env).get(path).status_code == 404
    (denied,) = env.audit.denied()
    assert (denied["object_kind"], denied["actor_user_id"]) == ("layout", _VIEWER)


# --- alerts and deliveries: the rules actor is the target's; the bound view names the viewer ----


def test_a_foreign_alert_read_while_viewing_is_recorded_as_the_viewers() -> None:
    env = AlertsEnv()
    env.c.app.middleware("http")(  # type: ignore[attr-defined]  # `app` is typed as ASGI
        _bound_while_viewing(ALERT_USER_B)
    )
    theirs = env.create()  # the env's first user's
    env.user = ALERT_USER_B  # the target: the rules actor while viewing
    assert env.c.get(f"/alerts/{theirs['id']}").status_code == 404
    action, record = env.audit.calls[-1]
    assert (action, record["actor_user_id"], record["actor_label"]) == (
        "alert.denied",
        str(_VIEWER),
        str(_VIEWER),
    )


class _KeyedBudget(DenialBudget):
    def __init__(self) -> None:
        super().__init__(clock=lambda: 0.0)
        self.callers: list[str] = []

    def admit(self, user_id: str) -> int | None:
        self.callers.append(user_id)
        return super().admit(user_id)


def _deliveries_while_viewing() -> tuple[DeliveriesEnv, _KeyedBudget]:
    """The deliveries routes as `USER_A`, their caller, reads them while `_VIEWER` views as it."""
    budget = _KeyedBudget()
    env = DeliveriesEnv(denials=budget)
    env.c.app.middleware("http")(  # type: ignore[attr-defined]  # `app` is typed as ASGI
        _bound_while_viewing(str(env.user))
    )
    return env, budget


def test_a_deliveries_read_of_a_foreign_alert_while_viewing_is_recorded_as_the_viewers() -> None:
    env, _ = _deliveries_while_viewing()
    assert env.c.get("/alerts/deliveries", params={"alert_id": ALERT_B}).status_code == 404
    (denial,) = env.denials()
    assert (denial["actor_user_id"], denial["actor_label"]) == (str(_VIEWER), str(_VIEWER))


def test_a_deliveries_denial_while_viewing_spends_the_viewers_own_budget() -> None:
    env, budget = _deliveries_while_viewing()
    env.c.get("/alerts/deliveries", params={"alert_id": ALERT_B})
    assert budget.callers == [str(_VIEWER)]
