"""§9.6 (#3085): a viewing socket's scope is its target's, and its actor the viewer.

While the session holds a live context, the `auth` resolves the target's principal: `auth_ok`
carries the session's own `user_id` and `session_id` with the target's roles, permissions and
account scope, and the socket is registered under the target, so the target's own data and role
changes reach it. The viewer acts: the socket's audit rows name the viewer, and its per-user
quotas (rebuilds, indicator instances) are the viewer's, so a viewer cannot spend the target's.
The registry never lets a viewing socket take an Owner's snapshot (a target is never an Owner),
and a disable of the target ends the view (`view_as_expired`), not the viewer (`user_disabled`);
a disable of the viewer closes its viewing sockets `user_disabled`, as its own.
A viewing close is no revocation of the socket's own: `cv_ws_revoked_total` does not move.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import pytest
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.auth.view_as import ViewAsBinding, ViewAsPhase
from candleviewer.bars.models import BarSpec
from candleviewer.orderflow.indicators.engine import Requested
from candleviewer.ws.permissions import (
    AuditSink,
    ConnectionAuthz,
    ConnectionRegistry,
    SubscriptionServices,
    VersionedSnapshot,
    _audit_denials,
    audit_rebuild_refusal,
)
from candleviewer.ws.revocation import RevocationHub, ViewAsClose, ws_revoked_total
from tests.unit.ws._auth_rig import DEADLINE_S, LATER, Rig, Sock, bye_of, hang_up, user_of
from tests.unit.ws._seq_support import ACC_A, ACC_B

_VIEWER, _TARGET = user_of("good-1"), user_of("good-9")


def _viewing(rig_kw: dict[str, Any] | None = None) -> Rig:
    binding = ViewAsBinding(
        context_id=uuid.uuid4(), target_user_id=_TARGET, expires_at=LATER, phase=ViewAsPhase.LIVE
    )

    async def view_as(session_id: str) -> ViewAsBinding:
        return binding

    return Rig(options={"view_as": view_as}, **(rig_kw or {}))


async def test_auth_ok_names_the_session_with_the_targets_scope_and_registers_the_target() -> None:
    rig, sock = _viewing(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        ok = await rig.auth(sock, "good-1")
        assert ok["t"] == "auth_ok"
        assert (ok["p"]["user_id"], ok["p"]["session_id"]) == (str(_VIEWER), "sess-good-1")
        assert ok["p"]["roles"] == ["viewer"] and ok["p"]["permissions"]  # the target's
        assert set(rig.registry._conns) == {_TARGET}  # the target's changes reach it
        ((authz, _, _),) = rig.registry._conns[_TARGET]
        assert (authz.principal.user_id, authz.actor_user_id) == (_TARGET, _VIEWER)
        hang_up(sock)
        await handler


async def test_a_viewing_sockets_flag_push_is_resolved_for_its_target() -> None:
    """Its flags are its subject's, with the subject's roles, as REST resolves them (plan §1.5):
    never the viewer's overrides or rollout bucket."""
    rig, sock = _viewing(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
        ((user_id, roles, _push),) = rig.hub.system_sessions()
        assert (user_id, roles) == (_TARGET, frozenset({"viewer"}))
        hang_up(sock)
        await handler


async def test_a_viewing_sockets_permission_change_names_the_session_as_auth_ok_did() -> None:
    """§9.5: its identity is a subset of `auth_ok`'s, which names the session's own user."""
    rig, sock = _viewing(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
        await rig.registry.roles_changed(_TARGET)
        change = await sock.sent.get()
        assert (change["t"], change["p"]["user_id"]) == ("permission_change", str(_VIEWER))
        hang_up(sock)
        await handler


async def test_a_disable_of_the_viewed_target_ends_the_view_not_the_viewer() -> None:
    rig, sock = _viewing(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
        assert await rig.registry.user_disabled(_TARGET) == 1
        assert bye_of(await sock.sent.get()) == ("bye", "view_as_expired", 4403)
        hang_up(sock)
        await handler


async def test_a_disable_of_the_viewer_closes_its_viewing_socket_user_disabled() -> None:
    """§9.5: the viewer is the disabled user, and the socket, registered under the target, is
    still the viewer's: `bye user_disabled`, 4403, though the view's target is not disabled."""
    rig, sock = _viewing(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
        assert await rig.registry.user_disabled(_VIEWER) == 1
        assert bye_of(await sock.sent.get()) == ("bye", "user_disabled", 4403)
        hang_up(sock)
        await handler


async def test_a_target_who_becomes_an_owner_ends_the_view() -> None:
    """§9.6: a target is never an Owner, so the socket never applies an Owner's snapshot."""
    rig, sock = _viewing(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"

        async def promoted(uid: uuid.UUID) -> PrincipalSnapshot:
            return PrincipalSnapshot(uid, frozenset({"owner"}), frozenset(Permission))

        rig.registry._resolve = promoted
        await rig.registry.roles_changed(_TARGET)
        assert bye_of(await sock.sent.get()) == ("bye", "view_as_expired", 4403)
        assert _TARGET not in rig.registry._conns
        hang_up(sock)
        await handler


async def _owner(uid: uuid.UUID) -> PrincipalSnapshot:
    return PrincipalSnapshot(uid, frozenset({"owner"}), frozenset(Permission))


async def test_a_target_already_an_owner_at_the_auth_is_refused_view_as_expired() -> None:
    """The `auth` resolves the target before it registers anything: an Owner ends the view."""
    rig, sock = _viewing(), Sock()
    rig.registry._resolve = _owner
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert bye_of(await rig.auth(sock, "good-1")) == ("bye", "view_as_expired", 4403)
        assert not rig.registry._conns
        hang_up(sock)
        await handler


def _registered_view(registry: ConnectionRegistry) -> tuple[ConnectionAuthz, list[Any]]:
    principal = PrincipalSnapshot(_TARGET, frozenset({"viewer"}), frozenset())
    authz = ConnectionAuthz(principal, registry.services, viewer_user_id=_VIEWER)
    closes: list[Any] = []

    async def closer(frame: dict[str, Any], code: int) -> None:
        closes.append(bye_of(frame))

    registry.register(authz, None, None, closer)
    return authz, closes


async def test_a_recheck_that_reads_an_owner_target_ends_the_view_instead_of_applying() -> None:
    """SR-189's re-read: the change it catches may be the target's promotion."""
    registry = ConnectionRegistry(_owner, lambda: 0, services=SubscriptionServices())
    authz, closes = _registered_view(registry)
    await registry.roles_changed(uuid.uuid4())  # a change after the socket's own read
    await registry.recheck(authz)
    assert closes == [("bye", "view_as_expired", 4403)] and not registry._conns


async def test_an_applied_owner_snapshot_ends_the_view_and_yields_no_frames() -> None:
    registry = ConnectionRegistry(_owner, lambda: 0, services=SubscriptionServices())
    authz, closes = _registered_view(registry)
    snap = await registry.resolve(_TARGET)
    assert await registry.apply(authz, snap, 0, event="reauth") == []
    assert closes == [("bye", "view_as_expired", 4403)] and not registry._conns


# --- a viewing close is no revocation: `cv_ws_revoked_total` (#3085) --------------------------


def _revoked_total() -> float:
    """`cv_ws_revoked_total` over every reason now: read it before and after, as the counter is
    global and no test resets it."""
    return sum(
        sample.value
        for family in ws_revoked_total.collect()
        for sample in family.samples
        if sample.name.endswith("_total")
    )


async def test_a_disable_of_the_viewed_target_counts_no_revocation_for_the_viewing_socket() -> None:
    """The view ends (`view_as_expired`); the socket is not the disabled user's own, so it is not
    a `user_disabled` revocation, as the target's own sockets are."""
    registry = ConnectionRegistry(_owner, lambda: 0, services=SubscriptionServices())
    _authz, closes = _registered_view(registry)
    before = _revoked_total()
    await registry.user_disabled(_TARGET)
    assert (closes, _revoked_total() - before) == ([("bye", "view_as_expired", 4403)], 0)


async def test_ending_the_view_of_a_target_who_became_an_owner_counts_no_revocation() -> None:
    registry = ConnectionRegistry(_owner, lambda: 0, services=SubscriptionServices())
    authz, closes = _registered_view(registry)
    snap = await registry.resolve(_TARGET)
    before = _revoked_total()
    await registry.apply(authz, snap, 0, event="reauth")
    assert (closes, _revoked_total() - before) == ([("bye", "view_as_expired", 4403)], 0)


@pytest.mark.parametrize("reason", ["view_as_changed", "view_as_expired"])
async def test_a_view_as_contexts_close_counts_no_revocation(reason: ViewAsClose) -> None:
    """The hub's per-context close, which a start, an end and the sweeper's ends run."""
    hub, closed = RevocationHub(), list[int]()

    async def closer(frame: dict[str, Any], code: int) -> None:
        closed.append(code)

    hub.register("s1", closer)
    hub.bind("s1", closer, "x")
    before = _revoked_total()
    await hub.close_context("s1", "x", reason)
    assert (len(closed), _revoked_total() - before) == (1, 0)


async def test_an_owner_promotion_of_the_users_own_socket_still_applies() -> None:
    rig, sock = Rig(), Sock()
    async with asyncio.timeout(DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "good-9"))["t"] == "auth_ok"

        async def promoted(uid: uuid.UUID) -> PrincipalSnapshot:
            return PrincipalSnapshot(uid, frozenset({"owner"}), frozenset(Permission))

        rig.registry._resolve = promoted
        await rig.registry.roles_changed(_TARGET)
        assert (await sock.sent.get())["t"] == "permission_change"
        hang_up(sock)
        await handler


def test_the_quotas_are_the_actors_and_the_principal_the_targets() -> None:
    principal = PrincipalSnapshot(_TARGET, frozenset({"viewer"}), frozenset())
    viewing = ConnectionAuthz(principal, viewer_user_id=_VIEWER)
    own = ConnectionAuthz(principal)
    assert viewing.rebuilds._user is not None and viewing.rebuilds._user[1] == _VIEWER
    assert (viewing.actor_user_id, own.actor_user_id) == (_VIEWER, _TARGET)


class _Leases:
    """`BarLeases` recording the user each bar lease is charged to."""

    def __init__(self) -> None:
        self.users: list[str | None] = []

    def check(self, spec: BarSpec, symbol: str, user: str | None = None) -> None:
        self.users.append(user)

    async def register(self, *_args: Any, user: str | None = None) -> None:
        self.users.append(user)

    def release(self, spec_hash: str, symbol: str, consumer: str) -> None:
        return None


async def test_a_viewing_sockets_bar_lease_is_charged_to_the_viewer() -> None:
    """The per-user bar and indicator quotas are the viewer's, as the rebuild budget is."""
    leases = _Leases()
    principal = PrincipalSnapshot(
        _TARGET, frozenset({"manager"}), frozenset({Permission.MARKETDATA_READ})
    )
    authz = ConnectionAuthz(principal, SubscriptionServices(bars=leases), viewer_user_id=_VIEWER)
    sub = authz.admit("footprint.BTCUSDT.tick.100")[1]
    assert sub is not None and await authz.subscribe_upstream(sub) is None
    assert leases.users == [str(_VIEWER)]


class _Indicators:
    """`IndicatorInstances` recording the user each `check` and `admit` is charged to."""

    def __init__(self) -> None:
        self.checked: list[str | None] = []
        self.admitted: list[str | None] = []

    def check(
        self,
        symbol: str,
        spec: BarSpec,
        requested: tuple[Requested, ...],
        user: str | None,
        *,
        history: int,
        consumer: str | None = None,
    ) -> None:
        self.checked.append(user)

    def admit(
        self,
        symbol: str,
        spec: BarSpec,
        requested: tuple[Requested, ...],
        consumer: str,
        user: str | None,
        *,
        history: int,
        replacing: tuple[str, ...] = (),
        reason: Literal["param_change"] | None = None,
    ) -> None:
        self.admitted.append(user)

    def release(self, symbol: str, keys: tuple[str, ...], consumer: str) -> None:
        return None


_EMA = {"instances": [{"indicator": "ema", "params": {"n": 5}}]}
_EMA_8 = {"instances": [{"indicator": "ema", "params": {"n": 8}}]}
_INDICATORS_CH = "indicators.BTCUSDT.time.1"


async def _subscribed_with_instances(viewer: uuid.UUID) -> tuple[ConnectionAuthz, _Indicators]:
    """A viewing socket (the target's principal, `viewer` acting) whose `sub` of instances has
    gone upstream; the engine holds what that `sub` charged and nothing else."""
    engine = _Indicators()
    services = SubscriptionServices(bars=_Leases(), indicators=engine)
    principal = PrincipalSnapshot(
        _TARGET, frozenset({"manager"}), frozenset({Permission.MARKETDATA_READ})
    )
    authz = ConnectionAuthz(principal, services, viewer_user_id=viewer)
    sub = authz.admit({"ch": _INDICATORS_CH, "opts": _EMA})[1]
    assert sub is not None and await authz.subscribe_upstream(sub) is None
    return authz, engine


async def _charged_for_a_sub(viewer: uuid.UUID) -> _Indicators:
    """What the engine is charged for a viewing socket's `sub` of instances: `_upstream`'s own
    `check` and `admit`, with nothing cleared and no `ctl` after it."""
    _authz, engine = await _subscribed_with_instances(viewer)
    return engine


async def _charged_for_a_ctl(viewer: uuid.UUID) -> _Indicators:
    """What the engine is charged when a viewing socket's `ctl` retunes the instances its `sub`
    held, apart from the `sub`'s own charges."""
    authz, engine = await _subscribed_with_instances(viewer)
    engine.checked.clear()
    engine.admitted.clear()
    authz.ctl(_INDICATORS_CH, _EMA_8)
    return engine


async def test_a_viewing_sockets_sub_is_checked_against_the_viewers_instance_quota() -> None:
    """The `sub`'s own per-user cap check, `_upstream`'s `engine.check`, asks about the viewer and
    never the target, so the check and the hold that follows it agree whose quota it is (#4269's
    security look)."""
    viewer = uuid.uuid4()
    assert (await _charged_for_a_sub(viewer)).checked == [str(viewer)]


async def test_a_viewing_sockets_sub_holds_its_instances_for_the_viewer() -> None:
    """`_upstream`'s `engine.admit` records the holder as the viewer, so a viewer cannot fill the
    target's `INSTANCE_CAP_PER_USER` and refuse the target's own sockets (#4269's security look)."""
    viewer = uuid.uuid4()
    assert (await _charged_for_a_sub(viewer)).admitted == [str(viewer)]


async def test_a_viewing_sockets_ctl_is_checked_against_the_viewers_instance_quota() -> None:
    """A `ctl` of `instances` asks the engine's per-user cap about the viewer, as the `sub` did,
    never about the target."""
    viewer = uuid.uuid4()
    assert (await _charged_for_a_ctl(viewer)).checked == [str(viewer)]


async def test_a_viewing_sockets_ctl_holds_its_new_instances_for_the_viewer() -> None:
    viewer = uuid.uuid4()
    assert (await _charged_for_a_ctl(viewer)).admitted == [str(viewer)]


class _Rows:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self.rows.append({"action": action, **fields})


async def test_a_viewing_sockets_audit_rows_name_the_viewer_and_its_session() -> None:
    """§9.6: every record for a socket of the session names the viewer and the viewer's session
    as the actor, never the target."""
    sink = _Rows()
    principal = PrincipalSnapshot(_TARGET, frozenset({"viewer"}), frozenset())
    authz = ConnectionAuthz(principal, SubscriptionServices(audit=sink), viewer_user_id=_VIEWER)
    authz.session_id = "sess-good-1"
    await _audit_denials(authz, [("orders", "forbidden", "missing_permission")])
    (row,) = sink.rows
    assert (row["action"], row["actor_user_id"], row["session_id"]) == (
        "ws.subscribe.denied",
        _VIEWER,
        "sess-good-1",
    )


# --- the viewer acts: the other row emitters (#3085) ------------------------------------------


async def _unread(user_id: uuid.UUID) -> PrincipalSnapshot:
    raise AssertionError("this registry reads no principal")


async def _revoke_a_subscription(sink: AuditSink, viewer: uuid.UUID) -> None:
    """The target loses market data while the viewing socket holds `trades`: the change revokes
    it (`_revocation_rows`)."""

    async def withdrawn(user_id: uuid.UUID) -> PrincipalSnapshot:
        return PrincipalSnapshot(user_id, frozenset({"viewer"}), frozenset())

    async def send(frame: dict[str, Any]) -> None:
        return None

    registry = ConnectionRegistry(withdrawn, lambda: 0, SubscriptionServices(audit=sink))
    held = PrincipalSnapshot(
        _TARGET, frozenset({"viewer"}), frozenset({Permission.MARKETDATA_READ})
    )
    authz = ConnectionAuthz(held, registry.services, viewer_user_id=viewer)
    assert authz.admit("trades.BTCUSDT")[1] is not None
    registry.register(authz, send)
    await registry.roles_changed(_TARGET)


async def _refuse_a_stale_snapshot(sink: AuditSink, viewer: uuid.UUID) -> None:
    """A read begun before the socket's applied snapshot lands late (SR-189): `_swap` refuses and
    records it."""
    registry = ConnectionRegistry(_unread, lambda: 0, SubscriptionServices(audit=sink))
    principal = PrincipalSnapshot(_TARGET, frozenset({"viewer"}), frozenset())
    authz = ConnectionAuthz(principal, registry.services, version=2, viewer_user_id=viewer)
    await registry.apply(authz, VersionedSnapshot(principal, 1), 0, event="reauth")


async def _refuse_a_rebuild(sink: AuditSink, viewer: uuid.UUID) -> None:
    """The viewer's one rebuild a minute is spent, so the next is refused for the user, and the
    user's first such refusal is recorded (`audit_rebuild_refusal`)."""
    services = SubscriptionServices(audit=sink)
    services.user_rebuilds.limit = 1
    principal = PrincipalSnapshot(_TARGET, frozenset({"viewer"}), frozenset())
    authz = ConnectionAuthz(principal, services, clock=lambda: 0.0, viewer_user_id=viewer)
    spent, refused = ("book.BTCUSDT.50", None), ("heatmap.BTCUSDT", None)
    assert authz.rebuilds.take(spent, "ctl") is None
    scope = authz.rebuilds.take(refused, "ctl")
    assert scope is not None
    authz.rebuilds.count_refusal("ctl", scope, refused)  # leaves the record due
    await audit_rebuild_refusal(authz)


#: The rows no test above pins, by action: how to have one written for a viewing socket.
_ROW_EMITTERS: dict[str, Callable[[AuditSink, uuid.UUID], Awaitable[None]]] = {
    "ws.subscription.revoked": _revoke_a_subscription,
    "ws.permission_snapshot.refused": _refuse_a_stale_snapshot,
    "ws.rebuild.refused": _refuse_a_rebuild,
}


@pytest.mark.parametrize("action", _ROW_EMITTERS)
async def test_a_viewing_sockets_row_names_the_viewer_whichever_emitter_writes_it(
    action: str,
) -> None:
    """§9.6: the viewer acts, so no record of the socket names the target whose scope it holds.
    `ws.subscribe.denied` is pinned above, and `ws.subscribe.granted` in
    `test_ws_audit_trail.py`."""
    sink, viewer = _Rows(), uuid.uuid4()
    await _ROW_EMITTERS[action](sink, viewer)
    assert {(row["action"], row["actor_user_id"]) for row in sink.rows} == {(action, viewer)}


class _Down:
    """An audit sink whose store is down."""

    async def emit(self, action: str, **fields: Any) -> None:
        raise OSError("the audit store is down")


async def test_a_viewing_sockets_unconfirmed_rebuild_record_is_logged_for_the_viewer() -> None:
    """The line `audit_rebuild_refusal` logs when it cannot confirm the record says whose it was:
    the viewer's."""
    viewer = uuid.uuid4()
    with capture_logs() as logs:
        await _refuse_a_rebuild(_Down(), viewer)  # never raises
    (line,) = [e for e in logs if e["event"] == "ws audit not confirmed"]
    assert line["actor_user_id"] == viewer


# --- S16's scope, the Owner viewing a Manager (#3085; the S11 security look's M-2) ---------------

#: The viewer an Owner, the target a Manager granted account A only (23 §9.6, S16).
_S16 = {
    _VIEWER: PrincipalSnapshot(_VIEWER, frozenset({"owner"}), frozenset(Permission)),
    _TARGET: PrincipalSnapshot(
        _TARGET,
        frozenset({"manager"}),
        frozenset({Permission.ORDERS_READ, Permission.MARKETDATA_READ}),
        (AccountGrant(ACC_A, True, False, False),),
    ),
}


async def _owner_viewing_a_manager() -> tuple[Rig, Sock, Any]:
    rig, sock = _viewing({"principals": _S16}), Sock()
    handler = await rig.open(sock)
    assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
    return rig, sock, handler


async def _frames_before_a_pong(sock: Sock) -> list[dict[str, Any]]:
    sock.feed({"t": "ping", "id": "barrier"})
    frames: list[dict[str, Any]] = []
    while (frame := await sock.sent.get())["t"] != "pong":
        frames.append(frame)
    return frames


async def test_s16_a_viewing_socket_is_refused_an_account_outside_its_targets_grants() -> None:
    """The Owner's reach is not the view's: `orders` on account B is refused as the Manager's own
    `sub` would be (`23-ws-protocol.md` S16, §9.6 scope)."""
    async with asyncio.timeout(DEADLINE_S):
        _rig, sock, handler = await _owner_viewing_a_manager()
        entry = {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_B)]}}
        sock.feed({"t": "sub", "id": "s", "p": {"topics": [entry]}})
        (result,) = (await sock.sent.get())["p"]["results"]
        assert (result["ok"], result["error"]["code"]) == (False, "account_scope_denied")
        hang_up(sock)
        await handler


async def test_s16_an_owner_only_system_frame_never_reaches_a_viewing_socket() -> None:
    """A `feature_flags` frame with no flag predicate reaches only an Owner (§15.9); the viewing
    socket's role is its target's, so it is withheld there."""
    async with asyncio.timeout(DEADLINE_S):
        rig, sock, handler = await _owner_viewing_a_manager()
        flags = {"kind": "feature_flags", "feature_flags": {"trading.one_click": True}}
        rig.hub.broadcast_system(flags)
        assert [f for f in await _frames_before_a_pong(sock) if f.get("ch") == "system"] == []
        hang_up(sock)
        await handler
