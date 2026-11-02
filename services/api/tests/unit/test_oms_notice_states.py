"""E29-S07 (#1028; 23-ws-protocol.md Sec.15.9 "Replay at connect" and "The transition time"):
`AccountNoticeStates` keeps each account's latest notice of the `oms.` family for the gateway's
`system_notices` port, `StatesBroadcast` keeps it and broadcasts it in one call, both OMS notice
bindings stamp `changed_at_ms`, and `create_app` binds it all. Recording doubles, a fake clock,
no sleeps; the socket-level cases are `tests/unit/ws/test_account_notice_replay.py`."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from structlog.testing import capture_logs

from candleviewer import app as app_module
from candleviewer.domain.primitives import AccountId
from candleviewer.oms.reconcile_report import STALE_NOTICE, Notice
from candleviewer.oms.reconcile_standing import ReconcileStanding
from candleviewer.oms_reconcile_wiring import ReconcileNoticesBinding
from candleviewer.oms_stream_wiring import (
    MAX_NOTICE_ACCOUNTS,
    AccountNoticeStates,
    StatesBroadcast,
    StreamNotices,
    account_notice,
)
from candleviewer.oms_wiring import build_oms_runtime
from candleviewer.profile_notices_wiring import profiles_notice
from tests.unit.auth.test_break_glass_notice import _app, _authenticated, _Events, _queued

A = AccountId(UUID("0a000000-0000-4000-8000-00000000000a"))
B = AccountId(UUID("0a000000-0000-4000-8000-00000000000b"))
T1, T2 = 1_789_132_262_000, 1_789_132_381_500  # epoch ms, the OMS's clock


def _stale(account: UUID, at: int = T1) -> dict[str, Any]:
    return account_notice(account, "oms.account_stale", changed_at_ms=at)


def _desync(account: UUID, at: int = T2) -> dict[str, Any]:
    return account_notice(account, "oms.account_desync", changed_at_ms=at)


class _Hub:
    """`GatewayHub.broadcast_system`, recording each body."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    def broadcast_system(self, body: dict[str, Any]) -> int:
        self.frames.append(body)
        return 1


class _Serving:
    """`Serving.notify`, recording each notified call, then running it as the serving loop does."""

    def __init__(self) -> None:
        self.calls: list[tuple[Callable[..., object], tuple[Any, ...]]] = []

    def notify(self, fn: Callable[..., object], /, *args: Any, **kwargs: Any) -> None:
        assert not kwargs
        self.calls.append((fn, args))
        fn(*args)


class _Standing:
    def __init__(self, *stale: AccountId) -> None:
        self.stale = frozenset(stale)

    def stale_accounts(self) -> frozenset[AccountId]:
        return self.stale


def _resyncing(account: UUID, at: int = T1) -> dict[str, Any]:
    return account_notice(account, "oms.account_resyncing", changed_at_ms=at)


def test_notice_states_keep_the_latest_notice_per_account() -> None:
    states = AccountNoticeStates()
    states.offer(_resyncing(A))
    states.offer(_desync(B))
    states.offer(_desync(A, at=T2))  # the account's latest state replaces its last
    assert states.notices() == [_desync(B), _desync(A, at=T2)]


def test_notice_states_synced_drops_the_entry() -> None:
    states = AccountNoticeStates()
    states.offer(_resyncing(A))
    states.offer(_desync(B))
    states.offer(account_notice(A, "oms.account_synced", changed_at_ms=T2))
    assert states.notices() == [_desync(B)]  # `synced` clears A, and is not kept itself


def test_notice_states_event_family_is_never_kept() -> None:
    """A `profiles.changed` notice is an event: it neither sets nor clears an `oms.` state."""
    states = AccountNoticeStates()
    states.offer(profiles_notice(B))
    assert states.notices() == []
    states.offer(_desync(A))
    states.offer(profiles_notice(A))
    assert states.notices() == [_desync(A)]


@pytest.mark.parametrize(
    "body",
    [
        account_notice(A, "oms.account_synced") | {"severity": "critical"},  # off the table
        _desync(A) | {"changed_at_ms": True},  # a `bool` is no time
        _desync(A) | {"label": "x"},  # a sixth key
        {"kind": "notice", "severity": "info", "message": "x", "reason": "oms.account_desync"},
    ],
    ids=["off-the-table", "bool-time", "sixth-key", "not-an-account-notice"],
)
def test_notice_states_refused_body_is_never_kept(body: dict[str, Any]) -> None:
    states = AccountNoticeStates()
    with pytest.raises(ValueError) as refused:
        states.offer(body)
    assert states.notices() == [] and str(A) not in str(refused.value)


def test_notice_states_keep_a_notice_naming_two_accounts_per_account() -> None:
    states = AccountNoticeStates()
    states.offer(_desync(A) | {"exchange_account_ids": [str(A), str(B)]})
    states.offer(account_notice(A, "oms.account_synced", changed_at_ms=T2))
    assert states.notices() == [_desync(B)]  # B's state stands alone, naming B only


def test_notice_states_restored_lock_from_standing_without_time() -> None:
    """A lock is the standing's: one B19 restored is answered with no time, never a restart's."""
    standing = ReconcileStanding()
    standing.restored(B, "stale_lockout")  # no notice since the start
    states = AccountNoticeStates()
    states.offer(_desync(A))
    assert states.notices() == [_desync(A)]  # until the standing is bound, no lock
    states.bind_standing(standing)
    restored = states.notices()[1]
    assert restored == account_notice(B, "oms.account_stale") and "changed_at_ms" not in restored
    states.offer(_resyncing(B))  # the lock wins over a later notice while the standing holds it
    assert states.notices() == [_desync(A), account_notice(B, "oms.account_stale")]
    standing.clear(B)  # the operator's unlock: the kept resync is B's state again
    assert states.notices() == [_desync(A), _resyncing(B)]


def test_notice_states_lock_carries_its_notices_time_while_the_standing_holds_it() -> None:
    standing = ReconcileStanding()
    states = AccountNoticeStates()
    states.bind_standing(standing)
    standing.mark_stale(A)  # before B19 is told (C-2.21), so the notice follows the standing
    states.offer(_stale(A))
    assert states.notices() == [_stale(A)]
    states.offer(_resyncing(A, at=T2))  # a stream drop during the lock keeps the lock's time
    assert states.notices() == [_stale(A)]
    standing.clear(A)  # the lock is over: its notice is no state to replay
    states.offer(_stale(B))  # a lock's notice the standing does not hold is not answered
    assert states.notices() == [_resyncing(A, at=T2)]
    standing.mark_stale(A)
    states.offer(_desync(A, at=T2 + 1))  # a pass ran: the old lock's time is gone
    assert states.notices() == [account_notice(A, "oms.account_stale")]


def test_notice_states_answer_entries_then_the_standings_locks_in_id_order() -> None:
    states = AccountNoticeStates()
    states.bind_standing(_Standing(B, A))
    states.offer(_desync(AccountId(UUID(int=2))))
    assert states.notices() == [
        _desync(UUID(int=2)),
        account_notice(A, "oms.account_stale"),
        account_notice(B, "oms.account_stale"),
    ]
    states.bind_standing(_Standing(B, A, AccountId(UUID(int=1))))
    assert [n["exchange_account_ids"] for n in states.notices()[1:]] == [
        [str(UUID(int=1))],
        [str(A)],
        [str(B)],
    ]


def test_notice_states_bounded_drops_the_oldest() -> None:
    assert MAX_NOTICE_ACCOUNTS == 4096
    states = AccountNoticeStates()
    accounts = [AccountId(UUID(int=n)) for n in range(1, MAX_NOTICE_ACCOUNTS + 3)]
    with capture_logs() as logs:
        for account in accounts[:-1]:
            states.offer(_desync(account))
        states.offer(_resyncing(accounts[1]))  # a change makes the account the newest
        states.offer(_desync(accounts[-1]))
    kept = [n["exchange_account_ids"][0] for n in states.notices()]
    assert len(kept) == MAX_NOTICE_ACCOUNTS
    assert str(accounts[0]) not in kept and str(accounts[2]) not in kept  # the two oldest went
    assert kept[-2:] == [str(accounts[1]), str(accounts[-1])]
    [full] = [log for log in logs if log["event"] == "account_notice_states_full"]
    assert (full["log_level"], full["accounts"]) == ("warning", MAX_NOTICE_ACCOUNTS)
    assert not any(str(account) in repr(logs) for account in accounts)  # a count, never an id


def test_notice_states_answers_copies() -> None:
    standing = ReconcileStanding()
    standing.mark_stale(B)
    states = AccountNoticeStates()
    states.bind_standing(standing)
    states.offer(_desync(A))
    states.offer(_stale(B))
    first = states.notices()
    for body in first:
        body["reason"] = "oms.account_synced"
        body["exchange_account_ids"].append(str(UUID(int=9)))
        body.pop("changed_at_ms")
    assert states.notices() == [_desync(A), _stale(B)]


def test_stream_and_reconcile_bindings_record_and_broadcast_together() -> None:
    """One notified call per notice, `StatesBroadcast.broadcast_system`: the state is kept and the
    frame broadcast together on the serving loop, each stamped with its binding's clock."""
    standing = ReconcileStanding()
    standing.mark_stale(B)  # the job sets the standing before B19 publishes the lock
    states, hub, serving = AccountNoticeStates(), _Hub(), _Serving()
    states.bind_standing(standing)
    kept = StatesBroadcast(states, hub)
    StreamNotices(kept, serving, now_ms=lambda: T1).publish(A, reason="oms.account_resyncing")
    ReconcileNoticesBinding(kept, serving, now_ms=lambda: T2).publish(B, STALE_NOTICE)
    assert [fn for fn, _ in serving.calls] == [kept.broadcast_system] * 2
    assert hub.frames == states.notices()  # what a later socket is replayed is what was sent
    assert [(f["reason"], f["changed_at_ms"]) for f in hub.frames] == [
        ("oms.account_resyncing", T1),
        ("oms.account_stale", T2),
    ]
    ReconcileNoticesBinding(kept, serving, now_ms=lambda: T2).publish(
        A, Notice("oms.account_synced", "info")
    )
    assert hub.frames[-1]["reason"] == "oms.account_synced" and states.notices() == hub.frames[1:2]


def test_a_body_the_states_refuse_is_not_broadcast() -> None:
    states, hub = AccountNoticeStates(), _Hub()
    with pytest.raises(ValueError):
        StatesBroadcast(states, hub).broadcast_system(_stale(A) | {"changed_at_ms": -1})
    assert hub.frames == [] and states.notices() == []


def test_create_app_replays_the_states_after_the_read_only_and_break_glass_notices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The composition root: the port answers the read-only gate's notice, an unresolved
    break-glass, then the account states; the OMS runtime is handed `StatesBroadcast` over the
    gateway's hub, and the reconciliation standing is bound (a restored lock, no time)."""
    handed: dict[str, Any] = {}
    build = build_oms_runtime

    def runtime(*args: Any, **kwargs: Any) -> Any:
        handed.update(kwargs)
        return build(*args, **kwargs)

    monkeypatch.setattr(app_module, "build_oms_runtime", runtime)
    with _app(monkeypatch, _Events(1), "owner") as (client, _auth):
        state = cast(FastAPI, client.app).state
        reason = "net.binding_check_failed"
        state.app_context.oms_read_only_gate.trip(reason_code=reason, reason_text="no mesh")
        state.reconcile_standing.mark_stale(A)
        hub = handed["hub"]
        assert isinstance(hub, StatesBroadcast)
        assert client.portal is not None
        client.portal.call(hub.broadcast_system, _desync(B))  # as the runtime's binding does
        with _authenticated(client) as ws:
            frames = [f["p"] for f in _queued(ws)]
    assert [(f["kind"], f["reason"]) for f in frames] == [
        ("notice", reason),
        ("notice", "auth.break_glass_used"),
        ("account_notice", "oms.account_desync"),
        ("account_notice", "oms.account_stale"),
    ]
    assert frames[2] == _desync(B) and frames[3] == account_notice(A, "oms.account_stale")
