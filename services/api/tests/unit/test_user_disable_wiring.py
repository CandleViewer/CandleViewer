"""E42-T04 S6 (#965): the composition root's `UserDisableService` (`build_user_disable_service`).

The real builder, store and owner floor over the S4 test world's fake unit of work. What is under
test is the wiring: every port reaches the service it names, and the auth services are looked up
when a step runs, not when the service is built (they exist only once `AuthService.start()` has).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.admin import errors
from candleviewer.admin.user_disable import DisableResult, UserDisableService
from candleviewer.settings import Settings
from candleviewer.storage.repositories import user_lifecycle_sqlalchemy as store_module
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from candleviewer.user_cascade_wiring import NoOrderCounter, build_user_disable_service
from tests.unit.admin.test_user_disable import _OWNER, _TARGET, _World
from tests.unit.storage.test_user_lifecycle_sqlalchemy import _S1, _Rel

_ACK = {"acknowledge_unknown_positions": True}


def _world(mp: pytest.MonkeyPatch, rel: _Rel | None = None, **kw: Any) -> _World:
    """An `invited` user with a session unless `rel` says otherwise; the builder's repositories
    run over this world's unit of work."""
    w = _World(rel or _Rel(status="invited", sessions=(_S1,)), **kw)
    mp.setattr(
        "candleviewer.user_cascade_wiring.SqlAlchemyRelationalRepository", lambda dsn, name: w.rel
    )
    mp.setattr(SqlAlchemySessionRepository, "find_by_id", lambda self, sid: w.find_by_id(sid))
    return w


_RULE = str(uuid.UUID(int=1))  # rule ids are UUIDs: the adapter's lock is keyed by one (S7)


def _build(w: _World, auth: Any = None, **kw: Any) -> UserDisableService:
    """The builder over the world: a rule of the user is armed, the rule engine marks the log."""
    row = SimpleNamespace(id=_RULE, owner=str(_TARGET), mode="armed", deleted=False)

    async def all_rows() -> list[Any]:
        w.mark("rules")
        return [row]

    async def get(rule_id: str) -> Any:  # the adapter checks the rule is the user's (S5)
        return row

    async def set_mode(rule_id: str, mode: str, actor: Any, key: str) -> None:
        assert mode == "disabled"  # a failed assert would fail the step: the result says so
        row.mode = mode
        w.mark("disarm")

    engine: Any = SimpleNamespace(
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
    """R7, in order: `users.disable` ahead of the commit; then the sockets, the sweep, B16, the
    scope refresh, the rules (listed, then disarmed) and the invite."""
    w = _world(monkeypatch, positions=None)
    result = await _build(w).disable(_TARGET, actor=_OWNER, **_ACK)
    assert result == DisableResult(changed=True)
    assert w.log == [
        *("positions", "users.disable", "socket:user_disabled", "sweep:user_disabled"),
        *("b16:user_disabled", "scope", "rules", "disarm", "rules", "invite"),
        "users.invite_revoked",
    ]


@pytest.mark.parametrize("positions", [None, 0], ids=["positions-unknown", "orders-unknown"])
async def test_orders_are_unknown_never_zero(
    positions: int | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UL-F9: no order has a user on main, so the count is unknown, never 0: a disable that has
    not acknowledged it is refused (409), whatever the position count says."""
    w = _world(monkeypatch, positions=positions)
    with pytest.raises(errors.PositionsUnknownError):
        await _build(w).disable(_TARGET, actor=_OWNER)
    assert w.calls == [] and not w.rel.committed
    assert await NoOrderCounter().open_order_count(str(_TARGET)) is None


async def test_the_auth_services_are_looked_up_when_a_step_runs_not_when_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Before `start()` the build must not touch the auth services; the steps that need them fail
    alone (R7): the commit stands and the others run."""
    w = _world(monkeypatch, positions=None)
    result = await _build(w, auth=object()).disable(_TARGET, actor=_OWNER, **_ACK)
    failed = ("session_sweep", "b16_revoke", "invite_revoke")
    assert result == DisableResult(changed=True, failed_steps=failed)
    assert w.post_commit() == ["socket:user_disabled", "scope", "rules", "disarm", "rules"]


async def test_the_instant_is_the_apps_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """The keyless-testnet clock (#2086) stamps sessions and B16: the revoke instant matches it."""
    w = _world(monkeypatch, positions=None)
    stamp = datetime(2030, 1, 2, 3, 4, tzinfo=UTC)
    await _build(w, clock=lambda: stamp).disable(_TARGET, actor=_OWNER, **_ACK)
    (revoked,) = (p for stmt, p in w.rel.ran if stmt is store_module._REVOKE_SESSIONS)
    assert revoked["now"] == stamp


async def test_the_owner_floor_the_root_injects_refuses_the_last_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC6: the store is the real one, so the floor is the builder's own, not a test's."""
    w = _world(monkeypatch, _Rel(roles=("owner",), owners=1), positions=None)
    with pytest.raises(errors.LastOwnerError):
        await _build(w).disable(_TARGET, actor=_OWNER, **_ACK)
    assert not w.rel.committed and w.calls == []
