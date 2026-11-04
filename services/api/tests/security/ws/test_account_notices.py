"""E29-X01 AC-07, seeded by #3864 (G-2, SR-E29-10; threat model `E29-oms.md` §11.1 and
`23-ws-protocol.md` §15.9): an account notice reaches only the sockets granted the account it names.
A Manager (M) granted account A only, on the implicit `system` topic, is sent no frame that names
or counts B when B resynchronises and goes stale, while a connection granted B (N) is sent each
notice, its `exchange_account_ids` naming B. A grant withdrawn from a live socket stops the notices
that follow it, and the `s` of its `system` frames stays gap-free (S3).

In process on the conformance gateway (fake clock, no sleeps), under both subprotocols, through the
real router and `GatewayHub.broadcast_system`; `Client.recv` schema-validates every frame it reads.
The notices are broadcast by hand here: E29-T05 and E29-T06 emit the real ones, and E29-X02 (#982)
runs these two tests again with those emitters in place of `_notice`. The AC-07 in
`test_account_scope.py` is E17-X02's (the `replay_session_id` refusal), not this one.

E29-S07 (#1028, 23 Sec.15.9 "Replay at connect") adds the replay after a first `auth_ok`: the
gateway's `system_notices` port answers each account's latest `oms.` notice
(`AccountNoticeStates`, and a lock the standing holds), and each socket is sent it cut to its
grants, as a live notice is: a socket that may not view B learns nothing of B's state, not even a
count.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from functools import partial
from typing import Any
from unittest.mock import patch

import pytest
from structlog.contextvars import merge_contextvars
from structlog.processors import format_exc_info
from structlog.testing import capture_logs

from candleviewer.domain.primitives import AccountId
from candleviewer.oms.reconcile_standing import ReconcileStanding
from candleviewer.oms_stream_wiring import AccountNoticeStates, account_notice
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.metrics import WITHHELD_REASONS
from tests.security.ws import _raw
from tests.security.ws._raw import RawWorld, authenticated, delta, drained, naming, raw_connect
from tests.unit.ws._seq_support import ACC_A, ACC_B

NAME = "cv_ws_system_frames_withheld_total"
LIST = "exchange_account_ids"
#: Global and role-neutral, so every role receives it whole: the last frame each socket is sent.
MARK = {"kind": "notice", "severity": "info", "message": "marker", "reason": "test.marker"}
#: One closed sentence per `reason`, as a producer keeps it (§15.9): none names an account.
_TEXT = {
    "oms.account_resyncing": "An account is resynchronising; its orders and positions are checked.",
    "oms.account_stale": "An account is stale; new orders for it are refused until it is synced.",
}


def _notice(reason: str, *accounts: uuid.UUID) -> dict[str, Any]:
    """An `account_notice` about `accounts`, which only its list names."""
    return {
        "kind": "account_notice",
        "severity": "warning",
        "message": _TEXT[reason],
        "reason": reason,
        LIST: [str(a) for a in accounts],
    }


def _system(frames: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    """`(s, p)` of the `system` frames among `frames`, in order."""
    return [(f["s"], f["p"]) for f in frames if f.get("ch") == "system"]


def _broadcast(world: RawWorld, *bodies: dict[str, Any]) -> None:
    for body in bodies:  # on the app's own loop, as a producer runs
        world.call(world.gateway.broadcast_system, body)


def test_e29_ac_07_a_manager_granted_a_is_sent_nothing_that_names_or_counts_b(
    world: RawWorld,
) -> None:
    m, n = world.login("m", ACC_A), world.login("n", ACC_B)
    resyncing, stale = _notice("oms.account_resyncing", ACC_B), _notice("oms.account_stale", ACC_B)
    counted = {reason: delta(NAME, reason=reason) for reason in WITHHELD_REASONS}
    with raw_connect(world) as cm, raw_connect(world) as cn:
        authenticated(cm, m)
        authenticated(cn, n)
        drained(cm)  # whatever `auth_ok` queued
        drained(cn)
        _broadcast(world, resyncing, stale, MARK)
        got_m, got_n = _system(drained(cm)), _system(drained(cn))
    assert got_m == [(2, MARK)]  # B's two notices took no `s` here (S3); `s` 1 is the snap
    assert naming(cm.seen, ACC_B) == []  # not one frame of M's whole stream, `auth_ok` included
    assert got_n == [(2, resyncing), (3, stale), (4, MARK)]
    assert [p[LIST] for _, p in got_n[:2]] == [[str(ACC_B)]] * 2  # the account is in the list ...
    rest = [{k: v for k, v in p.items() if k != LIST} for _, p in got_n]
    assert naming(rest, ACC_B) == []  # ... and in no other field of any frame
    assert {reason: count() for reason, count in counted.items()} == dict.fromkeys(
        WITHHELD_REASONS, 0
    )  # a notice cut to nothing is the contract: nothing is counted


def test_e29_a_withdrawn_grant_stops_later_account_notices_and_s_has_no_gap(
    world: RawWorld,
) -> None:
    n = world.login("n", ACC_A, ACC_B)
    granted = _notice("oms.account_stale", ACC_B)
    both = _notice("oms.account_resyncing", ACC_A, ACC_B)
    with raw_connect(world) as c:
        authenticated(c, n)
        drained(c)
        _broadcast(world, granted)  # N may view B now
        first = _system(drained(c))
        world.call(partial(world.amended, n, drop=(ACC_B,)))
        assert "permission_change" in [f["t"] for f in drained(c)]  # the withdrawal reached N
        mark = len(c.seen)
        _broadcast(world, granted, both, MARK)  # B alone, A and B, then the marker
        later = _system(drained(c))
    assert first == [(2, granted)]  # `s` 1 is the `system` snap (§12.1, #4992)
    # B's own notice is not sent and takes no `s`; the one naming both is cut to A
    assert later == [(3, both | {LIST: [str(ACC_A)]}), (4, MARK)]
    assert naming(c.seen[mark:], ACC_B) == []


# --- E29-S07: the replay after a first `auth_ok` (23 Sec.15.9) -----------------------------------

#: A third account, locked in the standing alone (a lock B19 restored: no notice since the start).
ACC_C = AccountId(uuid.UUID("0a000000-0000-4000-8000-00000000000c"))
CHANGED = 1_789_132_262_000


@pytest.fixture
def replayed(
    wire: str,
    flag: BackpressureConfig,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> Iterator[tuple[RawWorld, AccountNoticeStates]]:
    """The `world` fixture's `RawWorld`, its router's `system_notices` port the states' `notices`
    as `create_app` binds it (the read-only and break-glass notices before them send nothing)."""
    states = AccountNoticeStates()

    def router(**kwargs: Any) -> Any:
        return make_ws_router(**kwargs | {"system_notices": states.notices})

    with patch.object(_raw, "make_ws_router", router):
        w = RawWorld(caplog, capsys, flag)
    with capture_logs(processors=[merge_contextvars, format_exc_info]) as events, w.client:
        w.events = events
        yield w, states


def test_replay_manager_without_the_grant_gets_nothing(
    replayed: tuple[RawWorld, AccountNoticeStates],
) -> None:
    """Cross-account: B's lock, kept and held by the standing, reaches the socket granted B after
    its snap; the one granted A only is sent no frame that names or counts B."""
    world, states = replayed
    stale_b = account_notice(ACC_B, "oms.account_stale", changed_at_ms=CHANGED)
    standing = ReconcileStanding()
    standing.mark_stale(AccountId(ACC_B))
    states.bind_standing(standing)
    states.offer(stale_b)
    m, n = world.login("m", ACC_A), world.login("n", ACC_B)
    counted = {reason: delta(NAME, reason=reason) for reason in WITHHELD_REASONS}
    with raw_connect(world) as cm, raw_connect(world) as cn:
        authenticated(cm, m)
        authenticated(cn, n)
        got_m, got_n = _system(drained(cm)), _system(drained(cn))
    assert got_m == [] and naming(cm.seen, ACC_B) == []  # `auth_ok` and the snap included
    assert got_n == [(2, stale_b)]  # `s` 1 is the snap; the entry wins over the standing's lock
    assert {reason: count() for reason, count in counted.items()} == dict.fromkeys(
        WITHHELD_REASONS, 0
    )  # a replay cut to nothing is the contract: nothing is counted


def test_replay_viewer_never_learns_another_accounts_state(
    replayed: tuple[RawWorld, AccountNoticeStates],
) -> None:
    """SR-E29-10: a Viewer granted A is replayed A's state alone; B's notice and C's restored lock
    (the standing's, no time) reach it in no frame and no count, and neither moves its `s`."""
    world, states = replayed
    desync_a = account_notice(ACC_A, "oms.account_desync", changed_at_ms=CHANGED)
    standing = ReconcileStanding()
    standing.restored(ACC_C, "stale_lockout")
    states.bind_standing(standing)
    states.offer(desync_a)
    states.offer(account_notice(ACC_B, "oms.account_stale", changed_at_ms=CHANGED))
    v = world.login("v", ACC_A, role="viewer")
    counted = {reason: delta(NAME, reason=reason) for reason in WITHHELD_REASONS}
    with raw_connect(world) as c:
        authenticated(c, v)
        got = _system(drained(c))
        _broadcast(world, MARK)
        later = _system(drained(c))
    assert got == [(2, desync_a)] and later == [(3, MARK)]
    assert naming(c.seen, ACC_B) == [] and naming(c.seen, ACC_C) == []
    assert {reason: count() for reason, count in counted.items()} == dict.fromkeys(
        WITHHELD_REASONS, 0
    )
