"""#3085: the composition root's view-as ports and build. The eligibility port reads the viewer's
permissions and the target's status and roles as the request resolvers do, failing closed; the
labels port reads usernames; the service and its sweeper exist on the real backend only, ticking
every `CV_VIEW_AS_SWEEP_INTERVAL_S` with a `CV_VIEW_AS_ROTATED_GRACE_S` floored past a refresh's
claim-to-insert gap (`SessionService.refresh`)."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr, ValidationError

from candleviewer.admin.view_as import ViewAsService
from candleviewer.admin.view_as_sweeper import ViewAsSweeper
from candleviewer.app import _LazyAuditEmitter, create_app
from candleviewer.auth.service import AuthService
from candleviewer.settings import Settings
from candleviewer.view_as_wiring import (
    HOOK_TIMEOUT_S,
    IdentityEligibility,
    IdentityLabels,
    RoleChangeNotifier,
    build_view_as,
)
from tests.unit.admin.test_view_as_service import _TARGET, _VIEWER, _Ports, _Runner
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.auth.test_step_up import _Clock, _session


class _Identity:
    """`SqlAlchemyIdentityProvider`'s two reads: an unknown user raises `LookupError`."""

    def __init__(self, target: dict[str, Any] | None, permissions: list[str]) -> None:
        self.users = {str(_VIEWER): {"username": "ana"}}
        if target is not None:
            self.users[str(_TARGET)] = {"username": "bo", **target}
        self.permissions = permissions

    async def user(self, user_id: str) -> dict[str, Any]:
        if user_id not in self.users:
            raise LookupError("unknown user")
        return self.users[user_id]

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {
            "permissions": self.permissions if user_id == str(_VIEWER) else [],
            "account_scope": [],
        }


_WRITE = ["users:read", "users:write"]


@pytest.mark.parametrize(
    ("permissions", "target", "expected"),
    [
        (_WRITE, {"status": "active", "roles": ["manager"]}, None),
        (_WRITE, {"status": "locked", "roles": ["viewer"]}, None),  # 22: a locked target is viewed
        (["users:read"], {"status": "active", "roles": ["manager"]}, "viewer_ineligible"),
        ([], {"status": "active", "roles": ["manager"]}, "viewer_ineligible"),  # disabled viewer
        (_WRITE, {"status": "active", "roles": ["owner", "manager"]}, "target_ineligible"),
        (_WRITE, {"status": "disabled", "roles": ["manager"]}, "target_ineligible"),
        (_WRITE, {"status": "invited", "roles": []}, "target_ineligible"),
        (_WRITE, {"status": "suspended", "roles": ["manager"]}, "target_ineligible"),
        (_WRITE, {"roles": ["manager"]}, "target_ineligible"),  # no status: never read as active
        (_WRITE, {"status": "active", "roles": ["superuser"]}, "target_ineligible"),
        (_WRITE, None, "target_ineligible"),  # gone
    ],
    ids=[
        "ok",
        "locked",
        "no-write",
        "viewer-off",
        "owner",
        "disabled",
        "invited",
        "unknown-status",
        "no-status",
        "unknown-role",
        "gone",
    ],
)
async def test_eligibility_reads_the_viewer_permissions_and_the_target_status_and_roles(
    permissions: list[str], target: dict[str, Any] | None, expected: str | None
) -> None:
    """An unknown role or status fails closed: the context ends, never a wider scope."""
    port = IdentityEligibility(_Identity(target, permissions))
    assert await port.ineligible(_session(_VIEWER), _TARGET) == expected


@pytest.mark.parametrize("read", ["session_info", "user"])
async def test_eligibility_raises_on_a_failed_read_and_never_reads_it_as_gone(read: str) -> None:
    identity = _Identity({"status": "active", "roles": ["manager"]}, _WRITE)
    setattr(identity, read, AsyncMock(side_effect=ConnectionError("identity store unreachable")))
    with pytest.raises(ConnectionError):
        await IdentityEligibility(identity).ineligible(_session(_VIEWER), _TARGET)


async def test_the_lazy_audit_emitter_forwards_a_keyed_emit_with_its_name() -> None:
    handle: Any = SimpleNamespace(writer=(ports := _Ports()))
    await _LazyAuditEmitter(handle).emit_keyed("admin.view_as_ended", "context", reason="ended")
    assert ports.calls == [{"action": "admin.view_as_ended", "name": "context", "reason": "ended"}]


async def test_labels_read_each_username_and_leave_a_gone_user_out() -> None:
    labels = IdentityLabels(_Identity(None, []))
    assert await labels.usernames((_VIEWER, _TARGET)) == {_VIEWER: "ana"}


def test_the_service_and_its_sweeper_are_built_on_the_real_backend_only() -> None:
    ports: dict[str, Any] = {"audit": object(), "runner": _Runner(), "clock": _Clock()}
    real = AuthService(session_repository=FakeSessionRepository())
    identity = _Identity(None, [])
    assert build_view_as(Settings(), auth=AuthService(), identity=identity, **ports) is None
    assert build_view_as(Settings(), auth=real, identity=None, **ports) is None
    built = build_view_as(Settings(), auth=real, identity=identity, **ports)
    assert built is not None
    service, sweeper = built
    assert sweeper._service is service and sweeper._store is real.view_as_store
    assert (sweeper._interval_s, sweeper._grace) == (5.0, timedelta(seconds=600))  # the defaults


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("view_as_sweep_interval_s", 0.5), ("view_as_sweep_interval_s", 61),
        ("view_as_rotated_grace_s", 599), ("view_as_rotated_grace_s", 3_601),
    ],
)  # fmt: skip
def test_the_sweeper_settings_outside_their_bounds_are_refused(name: str, value: float) -> None:
    with pytest.raises(ValidationError):
        Settings(**{name: value})


def _real() -> Settings:
    return Settings(
        storage_backend="real",
        auth_pepper=SecretStr("test-pepper"),
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
    )


def test_create_app_gives_both_users_routers_the_role_change_notifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A role change by `PUT /users/{id}/roles` or `PATCH /users/{id}` runs the view-as hook, so
    both routers get the app's one `RoleChangeNotifier` around its service and its registry."""
    import candleviewer.app as appmod

    seen: dict[str, list[Any]] = {}
    for name in ("make_users_router", "make_user_admin_router"):
        real = getattr(appmod, name)

        def capture(*args: Any, _real: Any = real, _name: str = name, **kwargs: Any) -> Any:
            given = (*args, *kwargs.values())
            seen[_name] = [a for a in given if isinstance(a, RoleChangeNotifier)]
            return _real(*args, **kwargs)

        monkeypatch.setattr(appmod, name, capture)
    state = create_app(_real()).state
    assert set(seen) == {"make_users_router", "make_user_admin_router"}
    (one,), (other,) = seen.values()
    assert one is other and one._view_as is state.view_as
    assert one._registry is state.ws_registry and one._timeout_s == HOOK_TIMEOUT_S


def test_create_app_puts_the_service_and_its_sweeper_on_app_state() -> None:
    """So the lifespan, which reads `app.state.view_as_sweeper`, starts and stops it."""
    state = create_app(_real()).state
    assert isinstance(state.view_as, ViewAsService)
    assert isinstance(state.view_as_sweeper, ViewAsSweeper)
    assert state.view_as_sweeper._service is state.view_as
