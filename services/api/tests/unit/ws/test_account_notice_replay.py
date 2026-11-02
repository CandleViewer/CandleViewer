"""E29-S07 (#1028; 23-ws-protocol.md Sec.15.9 "Replay at connect"): each account's latest notice of
the `oms.` family reaches a socket right after its first `auth_ok` and the `system` snap, through
the gateway's `system_notices` port bound as `create_app` binds it, cut as every `account_notice`
is (SR-E29-10), and never on an in-place re-`auth`. The real `/ws` router runs on the test's loop
behind a fake socket (`test_system_topic_roles`' rig), its port reading `AccountNoticeStates`; the
notices are published by reconciliation's own binding over `StatesBroadcast`, on a fake clock. No
threads, no sleeps."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Iterable
from typing import Any
from unittest.mock import patch

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.auth.view_as import ViewAsBinding, ViewAsPhase
from candleviewer.domain.primitives import AccountId
from candleviewer.oms.reconcile_report import STALE_NOTICE, Notice
from candleviewer.oms.reconcile_standing import ReconcileStanding
from candleviewer.oms_reconcile_wiring import ReconcileNoticesBinding
from candleviewer.oms_stream_wiring import AccountNoticeStates, StatesBroadcast, account_notice
from candleviewer.ws.gateway import FlagSnapshot, make_ws_router
from tests.unit.ws import _auth_rig
from tests.unit.ws import test_system_topic_roles as roles
from tests.unit.ws.test_system_filter import ACC_A, ACC_B
from tests.unit.ws.test_system_topic_roles import _DEADLINE_S, _as, _Rig, _Socket, _system

T1 = 1_789_132_262_000
#: What `create_app`'s port answers before the account states: the read-only gate's notice and an
#: unresolved break-glass (role-neutral, as `client_notice` and `BreakGlassNotice` build them).
READ_ONLY = {"kind": "notice", "severity": "critical", "message": "Read only.", "reason": "ro.x"}
BREAK_GLASS = {"kind": "notice", "severity": "critical", "message": "Reset.", "reason": "bg.x"}
DESYNC = Notice("oms.account_desync", "warning")


class _Serving:
    def notify(self, fn: Callable[..., object], /, *args: Any, **kwargs: Any) -> None:
        fn(*args, **kwargs)


def _rig(
    states: AccountNoticeStates,
    first: Iterable[dict[str, Any]] = (),
    flags: FlagSnapshot | None = None,
) -> _Rig:
    """The real router, its port answering `first`, then `states.notices()`, at each first
    `auth_ok`."""

    def port() -> list[dict[str, Any]]:
        return [*first, *states.notices()]

    def router(**kwargs: Any) -> Any:
        return make_ws_router(**kwargs | {"system_notices": port})

    with patch.object(roles, "make_ws_router", router):
        return _Rig(flag_snapshot=flags)


def _locked(*accounts: uuid.UUID) -> tuple[AccountNoticeStates, ReconcileStanding]:
    """States bound to a standing that holds `accounts` locked, as the job sets it first."""
    standing, states = ReconcileStanding(), AccountNoticeStates()
    for account in accounts:
        standing.mark_stale(AccountId(account))
    states.bind_standing(standing)
    return states, standing


def _publish(
    rig: _Rig, states: AccountNoticeStates, account: uuid.UUID, notice: Notice, at: int = T1
) -> None:
    """`notice` about `account` as the reconciliation job publishes it, its clock reading `at`."""
    kept = StatesBroadcast(states, rig.hub)
    ReconcileNoticesBinding(kept, _Serving(), now_ms=lambda: at).publish(AccountId(account), notice)


async def test_scenario_repeated_reconciliation_failure_a_client_connecting_during_the_lock_learns_it() -> (  # noqa: E501 - the Gherkin scenario's name
    None
):
    """Account A's job locks (`oms.account_stale`, sent once per episode at T1): a socket open
    then is sent it live, and one that connects during the lock right after its snap, with the
    time the lock began."""
    states, standing = _locked()
    rig = _rig(states)
    async with asyncio.timeout(_DEADLINE_S):
        early = await rig.connect(_as(uuid.uuid4(), "viewer"))
        standing.mark_stale(AccountId(ACC_A))  # the job's standing first (C-2.21), then B19's
        _publish(rig, states, ACC_A, STALE_NOTICE)
        late = await rig.connect(_as(uuid.uuid4(), "viewer"))
        stale = account_notice(ACC_A, "oms.account_stale", changed_at_ms=T1)
        assert await _system(early) == [(2, stale)]
        assert await _system(late) == [(2, stale)]
        await rig.close()


async def test_scenario_reconnect_with_a_correction_a_reconnecting_client_learns_the_desync_it_missed() -> (  # noqa: E501 - the Gherkin scenario's name
    None
):
    states = AccountNoticeStates()
    rig, user = _rig(states), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        first = await rig.connect(_as(user, "manager"))
        first.inbound.put_nowait({"type": "websocket.disconnect", "code": 1006})
        await rig.handlers[0][1]  # the socket is gone before the pass corrects A
        _publish(rig, states, ACC_A, DESYNC)
        second = await rig.connect(_as(user, "manager"))
        desync = account_notice(ACC_A, "oms.account_desync", changed_at_ms=T1)
        assert await _system(second) == [(2, desync)]
        _publish(rig, states, ACC_A, Notice("oms.account_synced", "info"), at=T1 + 30_000)
        synced = account_notice(ACC_A, "oms.account_synced", changed_at_ms=T1 + 30_000)
        assert await _system(second) == [(3, synced)]
        third = await rig.connect(_as(user, "manager"))
        assert await _system(third) == []  # nothing for A once it is synced
        await rig.close()


async def test_first_auth_pushes_account_states_after_the_snap() -> None:
    """The snap (`s` 1), then a frame held while it was built, then the port's frames in its order:
    the read-only and break-glass notices, then the account states, the standing's locks last. The
    notice broadcast during the snap is held and replayed too: equal in account, `reason` and
    `changed_at_ms`, the client keeps it as the one state it is."""
    gate, reading = asyncio.Event(), asyncio.Event()

    async def slow(user: uuid.UUID, roles: frozenset[str]) -> dict[str, Any] | None:
        reading.set()
        await gate.wait()
        return None

    states, _ = _locked(ACC_B)
    states.offer(account_notice(ACC_B, "oms.account_stale", changed_at_ms=T1 - 120_000))
    rig, principal = _rig(states, (READ_ONLY, BREAK_GLASS), slow), _as(uuid.uuid4(), "owner")
    async with asyncio.timeout(_DEADLINE_S):
        rig.principals[principal.user_id] = principal
        sock = _Socket()
        rig.handlers.append((sock, asyncio.create_task(rig.endpoint(sock))))
        sock.feed({"t": "hello", "id": "h"})
        assert (await sock.sent.get())["t"] == "welcome"
        sock.feed({"t": "auth", "id": "a", "p": {"access_token": str(principal.user_id)}})
        await reading.wait()
        _publish(rig, states, ACC_A, DESYNC)  # it reaches this socket, held before its snap
        gate.set()
        frames = [await sock.sent.get() for _ in range(7)]
        await rig.close()
    desync = account_notice(ACC_A, "oms.account_desync", changed_at_ms=T1)
    stale = account_notice(ACC_B, "oms.account_stale", changed_at_ms=T1 - 120_000)
    assert [(f["t"], f.get("s")) for f in frames] == [
        ("auth_ok", None), ("snap", 1), *(("d", s) for s in range(2, 7)),
    ]  # fmt: skip
    assert [f["p"] for f in frames[2:]] == [desync, READ_ONLY, BREAK_GLASS, desync, stale]


async def test_in_place_reauth_pushes_no_account_state() -> None:
    states, _ = _locked(ACC_A)
    states.offer(account_notice(ACC_A, "oms.account_stale", changed_at_ms=T1))
    rig, user = _rig(states, (READ_ONLY,)), uuid.uuid4()
    async with asyncio.timeout(_DEADLINE_S):
        sock = await rig.connect(_as(user, "manager"))
        assert [p["reason"] for _, p in await _system(sock)] == ["ro.x", "oms.account_stale"]
        states.offer(account_notice(ACC_B, "oms.account_desync", changed_at_ms=T1 + 1))
        sock.feed({"t": "auth", "id": "re", "p": {"access_token": str(user)}})
        assert (await sock.sent.get())["t"] == "auth_ok"
        assert await _system(sock) == []  # the socket keeps the state it holds
        await rig.close()


def _two_accounts(states: AccountNoticeStates) -> None:
    """A's and B's lock in one notice, as `checked_notice` admits one naming several."""
    both = [str(ACC_A), str(ACC_B)]
    states.offer(account_notice(ACC_A, "oms.account_stale", changed_at_ms=T1) | {
        "exchange_account_ids": both
    })  # fmt: skip


async def test_replay_owner_gets_every_entry_whole() -> None:
    states, _ = _locked(ACC_A, ACC_B)
    _two_accounts(states)
    rig = _rig(states)
    async with asyncio.timeout(_DEADLINE_S):
        owner = await rig.connect(_as(uuid.uuid4(), "owner"))
        got = await _system(owner)
        await rig.close()
    assert got == [
        (2, account_notice(ACC_A, "oms.account_stale", changed_at_ms=T1)),
        (3, account_notice(ACC_B, "oms.account_stale", changed_at_ms=T1)),
    ]


async def test_replay_manager_gets_only_scoped_accounts() -> None:
    """The notice naming A and B reaches a Manager holding A as A alone, with its time; one holding
    neither is sent nothing, and its `s` does not move (S3)."""
    states, _ = _locked(ACC_A, ACC_B)
    _two_accounts(states)
    rig, other = _rig(states), AccountId(uuid.UUID(int=0xC))
    async with asyncio.timeout(_DEADLINE_S):
        a_only = await rig.connect(_as(uuid.uuid4(), "manager", accounts=(ACC_A,)))
        neither = await rig.connect(_as(uuid.uuid4(), "manager", accounts=(other,)))
        got, none = await _system(a_only), await _system(neither)
        await rig.close()
    assert got == [(2, account_notice(ACC_A, "oms.account_stale", changed_at_ms=T1))]
    assert none == []


async def test_replay_reaches_no_socket_whose_principal_holds_no_role() -> None:
    """The deny-all principal (a failed load) is sent no `system` frame, the replay included."""
    states, _ = _locked(ACC_A)
    rig = _rig(states)
    async with asyncio.timeout(_DEADLINE_S):
        nobody = await rig.connect(_as(uuid.uuid4()))
        got = await _system(nobody)
        await rig.close()
    assert got == [] and nobody.snap is None


async def test_replay_never_crosses_environments() -> None:
    """C-2.11: a state is keyed by its account's id, and an account is of one environment, so a
    socket granted the demo account is replayed none of the live account's, and a pass that
    clears one leaves the other."""
    demo, live = ACC_A, AccountId(uuid.UUID("0a000000-0000-4000-8000-0000000000fe"))
    states, _ = _locked(live)
    states.offer(account_notice(live, "oms.account_stale", changed_at_ms=T1))
    states.offer(account_notice(demo, "oms.account_desync", changed_at_ms=T1))
    states.offer(account_notice(demo, "oms.account_synced", changed_at_ms=T1 + 1))
    rig = _rig(states)
    async with asyncio.timeout(_DEADLINE_S):
        on_demo = await rig.connect(_as(uuid.uuid4(), "manager", accounts=(demo,)))
        owner = await rig.connect(_as(uuid.uuid4(), "owner"))
        got, whole = await _system(on_demo), await _system(owner)
        await rig.close()
    assert got == []
    assert whole == [(2, account_notice(live, "oms.account_stale", changed_at_ms=T1))]


async def test_replay_under_view_as_is_cut_to_the_target() -> None:
    """23 Sec.9.6: a viewing socket's first `auth_ok` holds the target's scope, so the replay is the
    target's accounts, never the viewing Owner's whole set."""
    viewer, target = _auth_rig.user_of("good-1"), _auth_rig.user_of("good-9")
    states, _ = _locked(ACC_A, ACC_B)
    states.offer(account_notice(ACC_A, "oms.account_stale", changed_at_ms=T1))
    binding = ViewAsBinding(
        context_id=uuid.uuid4(), target_user_id=target, expires_at=_auth_rig.LATER,
        phase=ViewAsPhase.LIVE,
    )  # fmt: skip

    async def view_as(session_id: str) -> ViewAsBinding:
        return binding

    perms = frozenset({Permission.ORDERS_READ, Permission.POSITIONS_READ})
    grant = AccountGrant(ACC_A, True, True, False)
    rig = _auth_rig.Rig(
        options={"view_as": view_as, "system_notices": states.notices},
        principals={
            viewer: PrincipalSnapshot(viewer, frozenset({"owner"}), frozenset(Permission)),
            target: PrincipalSnapshot(target, frozenset({"manager"}), perms, (grant,)),
        },
    )
    sock = _auth_rig.Sock()
    async with asyncio.timeout(_DEADLINE_S):
        handler = await rig.open(sock)
        assert (await rig.auth(sock, "good-1"))["t"] == "auth_ok"
        sock.feed({"t": "ping", "id": "barrier"})
        frames = []
        while (frame := await sock.sent.get())["t"] != "pong":
            frames.append(frame)
        _auth_rig.hang_up(sock)
        await handler
    stale_a = account_notice(ACC_A, "oms.account_stale", changed_at_ms=T1)
    assert [(f["s"], f["p"]) for f in frames if f.get("ch") == "system"] == [(2, stale_a)]
