"""E42-T04 S6 (#965): the composition root's `UserDisableService` (`build_user_disable_service`).

The real builder over the S4 test world's fakes at the edges only: the S3 store runs over its fake
unit of work (its `disable`, and the session repository's `find_by_id`, are patched on the real
classes, as `test_owner_routes_composition.py` patches the other stores). What is under test is the
wiring: every port reaches the service it names, and the auth services are looked up when a step
runs, not when the service is built (they exist only once `AuthService.start()` has).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.admin import errors
from candleviewer.admin.user_disable import DisableResult, UserDisableService
from candleviewer.settings import Settings
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from candleviewer.storage.repositories.user_lifecycle_sqlalchemy import SqlAlchemyUserLifecycleStore
from candleviewer.user_cascade_wiring import NoOrderCounter, build_user_disable_service
from tests.unit.admin.test_user_disable import _OWNER, _S1, _TARGET, _Rel, _World
from tests.unit.storage.test_user_lifecycle_sqlalchemy import _store

_ACK = {"acknowledge_unknown_positions": True}


def _world(mp: pytest.MonkeyPatch, **kw: Any) -> tuple[_World, list[datetime]]:
    """An `invited` user with a session. The SQL edges are patched on the real classes: the S3
    store over this world's unit of work, and the session row the B16 step reads. Also returns the
    instants the store was given."""
    w, seen = _World(_Rel(status="invited", sessions=(_S1,)), **kw), list[datetime]()
    real = SqlAlchemyUserLifecycleStore.disable

    async def disable(self: Any, user_id: Any, *, actor: Any, now: datetime, audit: Any) -> Any:
        seen.append(now)
        return await real(_store(w.rel), user_id, actor=actor, now=now, audit=audit)

    mp.setattr(SqlAlchemyUserLifecycleStore, "disable", disable)
    mp.setattr(SqlAlchemySessionRepository, "find_by_id", lambda self, sid: w.find_by_id(sid))
    return w, seen


def _build(w: _World, auth: Any = None, **kw: Any) -> UserDisableService:
    """The builder over the world: a rule of the user is armed, the rule engine marks the log."""

    row = SimpleNamespace(id="r1", owner=str(_TARGET), mode="armed", deleted=False)

    async def all_rows() -> list[Any]:
        w.mark("rules")
        return [row]

    async def get(rule_id: str) -> Any:  # the adapter checks the rule is the user's (S5)
        return row

    async def set_mode(rule_id: str, mode: str, actor: Any, key: str) -> None:
        assert mode == "disabled"  # a failed assert would fail the step: the result says so
        w.mark(f"disarm:{rule_id}")

    engine = SimpleNamespace(
        manager=lambda: SimpleNamespace(set_mode=set_mode),
        scope_state=SimpleNamespace(refresh=w.refresh_scope),
    )
    auth = auth or SimpleNamespace(
        sessions=w,
        step_up=SimpleNamespace(chart=SimpleNamespace(revoke=w.record)),
        invites=SimpleNamespace(revoke=w.revoke_invite),
    )
    service = build_user_disable_service(
        Settings(storage_backend="real"),
        auth=auth,
        rules=engine,  # the parts of `RulesService` the adapters read
        rule_store=SimpleNamespace(all=all_rows, get=get),
        audit=w,
        positions=w,
        publish_revocation=w.publish,
        **kw,
    )
    assert service is not None
    return service


async def test_the_real_backend_wires_every_port_to_the_service_it_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R7, in order: the revoked sessions' sockets, the sweep, B16, the scope refresh, the rules
    (listed, then disarmed) and the invite, all after the commit; `users.disable` ahead of it."""
    w, _ = _world(monkeypatch, positions=None)
    result = await _build(w).disable(_TARGET, actor=_OWNER, **_ACK)
    assert result == DisableResult(changed=True)
    assert w.log == [
        *("positions", "users.disable", "socket:user_disabled", "sweep:user_disabled"),
        *("b16:user_disabled", "scope", "rules", "disarm:r1", "invite", "users.invite_revoked"),
    ]


@pytest.mark.parametrize("positions", [None, 0], ids=["positions-unknown", "orders-unknown"])
async def test_orders_are_unknown_never_zero(
    positions: int | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UL-F9: no order has a user on main, so the order count is unknown, never 0, and a disable
    that has not acknowledged it is refused (409), whatever the position count says."""
    w, _ = _world(monkeypatch, positions=positions)
    with pytest.raises(errors.PositionsUnknownError):
        await _build(w).disable(_TARGET, actor=_OWNER)
    assert w.calls == [] and not w.rel.committed
    assert await NoOrderCounter().open_order_count(str(_TARGET)) is None


async def test_the_auth_services_are_looked_up_when_a_step_runs_not_when_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An auth module with none of its services yet (before `start()`): the build must not touch
    them, and the steps that need them fail alone (R7): the commit stands and the others run."""
    w, _ = _world(monkeypatch, positions=None)
    result = await _build(w, auth=object()).disable(_TARGET, actor=_OWNER, **_ACK)
    failed = ("session_sweep", "b16_revoke", "invite_revoke")
    assert result == DisableResult(changed=True, failed_steps=failed)
    assert w.post_commit() == ["socket:user_disabled", "scope", "rules", "disarm:r1"]


async def test_the_instant_is_the_apps_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """The keyless-testnet clock (#2086) stamps sessions and B16: the revoke instant matches it."""
    w, seen = _world(monkeypatch, positions=None)
    stamp = datetime(2030, 1, 2, 3, 4, tzinfo=UTC)
    await _build(w, clock=lambda: stamp).disable(_TARGET, actor=_OWNER, **_ACK)
    assert seen == [stamp]
