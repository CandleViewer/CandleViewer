"""#2302 (`23-ws-protocol.md` §15.9, `24-internal-schemas.md` §8.13): each connection's view of
the `system` safety summary. An account-keyed class is counted over the connection's
`account_scope` (C-12.4), with its own raised/cleared edges, so a Manager scoped away from an
incident learns nothing of it: not its existence, its size or its timing. A process-global class
reaches every role whole. The in-process breakdown is never in any role's view."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from candleviewer.auth.scopes import AccountGrant
from candleviewer.ws.safety_view import (
    WINDOW_S,
    Key,
    SafetyEdges,
    dropped_items,
    frame_view,
    is_unkeyed,
    items_view,
)
from candleviewer.ws.system_filter import system_view, withheld_reason
from tests.unit.ws.test_system_filter import ACC_A, ACC_B, MANAGER, OWNER, VIEWER, principal

_T0, _T1, _T2 = 1_789_133_000_000, 1_789_133_005_000, 1_789_133_009_000
#: The gateway's own time when a body reaches it (`now_ms`), after every event time here.
_NOW = 1_789_133_010_000
MANAGER_B = principal("manager", grants=(AccountGrant(ACC_B, True, True, False),))
MANAGER_NONE = principal("manager")


class _Timer:
    def __init__(self, delay: float, callback: Callable[[], None]) -> None:
        self.delay, self.callback, self.cancelled = delay, callback, False

    def cancel(self) -> None:
        self.cancelled = True


class _Loop:
    """A fake `call_later`: a window ends only when the test says so (`end_windows`)."""

    def __init__(self) -> None:
        self.timers: list[_Timer] = []
        self.due: list[Key] = []

    def __call__(self, delay: float, callback: Callable[[], None]) -> _Timer:
        timer = _Timer(delay, callback)
        self.timers.append(timer)
        return timer

    def live(self) -> list[_Timer]:
        return [timer for timer in self.timers if not timer.cancelled]

    def end_windows(self) -> None:
        for timer in self.live():
            timer.cancelled = True  # fired: it is not cancelled after
            timer.callback()


def _edges() -> tuple[SafetyEdges, _Loop]:
    loop = _Loop()
    return SafetyEdges(call_later=loop, due=loop.due.append), loop


def _raised(by_account: dict[Any, Any], *, at_ms: int = _T1) -> dict[str, Any]:
    """An account-keyed `risk_lockout` body as the publisher hands it to the gateway."""
    count = sum(entry["affected_count"] for entry in by_account.values())
    since = min(entry["since_ms"] for entry in by_account.values())
    return {
        "kind": "safety",
        "severity": "critical",
        "safety_class": "risk_lockout",
        "environment": "live",
        "state": "raised",
        "affected_count": count,
        "since_ms": since,
        "_by_account": {str(acc): entry for acc, entry in by_account.items()},
        "_at_ms": at_ms,
    }


_ON_A_AND_B = _raised(
    {ACC_A: {"affected_count": 1, "since_ms": _T1}, ACC_B: {"affected_count": 2, "since_ms": _T0}}
)
_ONLY_ON_B = _raised({ACC_B: {"affected_count": 2, "since_ms": _T0}}, at_ms=_T2)
_CLEARED = {
    "kind": "safety",
    "severity": "info",
    "safety_class": "risk_lockout",
    "environment": "live",
    "state": "cleared",
    "affected_count": 0,
    "since_ms": _T2,
    "_by_account": {},
    "_at_ms": _T2,
}
_HALTED = {
    "kind": "safety",
    "severity": "critical",
    "safety_class": "order_entry_halted",
    "environment": "demo",
    "state": "raised",
    "affected_count": 1,
    "since_ms": _T0,
}


def _public(body: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in body.items() if not key.startswith("_")}


def test_owner_gets_every_accounts_count_and_never_the_breakdown() -> None:
    view = system_view(_ON_A_AND_B, OWNER)
    assert view == _public(_ON_A_AND_B)
    assert "_by_account" not in json.dumps(view) and str(ACC_B) not in json.dumps(view)


@pytest.mark.parametrize("who", [MANAGER, VIEWER], ids=["manager", "viewer"])
def test_a_scoped_role_gets_the_count_and_since_time_of_its_own_accounts(who: Any) -> None:
    view = system_view(_ON_A_AND_B, who)
    assert view == _public(_ON_A_AND_B) | {"affected_count": 1, "since_ms": _T1}


def _send(edges: SafetyEdges, body: dict[str, Any], who: Any, now: int = _NOW) -> Any:
    """What a connection of `who` is sent of `body` at once, as `_Connection.push_system`
    decides with the gateway's time `now`."""
    view = system_view(body, who, now_ms=now)
    return None if view is None else edges.admit(body, view)


def _view_of(who: Any, now: int = _NOW) -> Callable[[Any], Any]:
    return lambda body: system_view(body, who, now_ms=now)


def test_idor_a_manager_scoped_to_a_gets_no_frame_for_a_subject_on_b() -> None:
    """Not a raised frame, not a cleared one, not a boolean: existence leaks too."""
    view = system_view(_ONLY_ON_B, MANAGER, now_ms=_NOW)
    assert view is not None and view["state"] == "cleared"  # its own state: nothing in scope
    assert view["since_ms"] == _NOW  # the gateway's time, not the body's
    assert _send(_edges()[0], _ONLY_ON_B, MANAGER) is None  # it never saw a `raised`
    assert str(ACC_B) not in json.dumps(view)


def test_a_scoped_cleared_without_the_gateways_time_is_nothing() -> None:
    """It is never stamped with the body's event time: with no time to stamp, nothing."""
    assert system_view(_ONLY_ON_B, MANAGER) is None


def test_a_manager_scoped_to_b_sees_the_incident_on_b() -> None:
    view = system_view(_ONLY_ON_B, MANAGER_B)
    assert view is not None
    assert (view["state"], view["affected_count"], view["since_ms"]) == ("raised", 2, _T0)


def test_a_count_change_on_another_account_sends_a_scoped_connection_nothing() -> None:
    """B's count moving is no frame for a Manager on A: no timing side channel."""
    edges, _ = _edges()
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    b_grew = _raised(
        {
            ACC_A: {"affected_count": 1, "since_ms": _T1},
            ACC_B: {"affected_count": 5, "since_ms": _T0},
        }
    )
    assert _send(edges, b_grew, MANAGER) is None


def test_a_cleared_reaches_a_connection_only_after_its_own_raised() -> None:
    edges, _ = _edges()
    assert _send(edges, _CLEARED, MANAGER) is None
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    assert _send(edges, _CLEARED, MANAGER) is not None
    assert _send(edges, _CLEARED, MANAGER) is None  # once only


def test_a_scoped_cleared_follows_its_last_account_leaving_while_others_stay() -> None:
    """A clears and B stays raised: the Manager on A gets its own `cleared` at the event time."""
    edges, _ = _edges()
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    view = _send(edges, _ONLY_ON_B, MANAGER)
    assert view is not None
    assert (view["state"], view["severity"], view["affected_count"]) == ("cleared", "info", 0)
    assert view["since_ms"] == _NOW  # the gateway's time on receipt, never B's `_at_ms`


def test_the_episode_start_stays_put_on_count_updates() -> None:
    """L2: the connection's `since_ms` is its episode's start while its view stays raised, even
    when the account that raised first leaves and a later one stays."""
    who = principal(
        "manager",
        grants=(AccountGrant(ACC_A, True, True, False), AccountGrant(ACC_B, True, True, False)),
    )
    edges, loop = _edges()
    first = _send(edges, _ON_A_AND_B, who)
    assert first is not None and (first["affected_count"], first["since_ms"]) == (3, _T0)
    loop.end_windows()  # the raise's window is over: the count update goes at once
    a_only = _raised({ACC_A: {"affected_count": 2, "since_ms": _T1}})
    later = _send(edges, a_only, who)
    assert later is not None and (later["affected_count"], later["since_ms"]) == (2, _T0)


def test_a_revoked_grant_sends_cleared_at_once_stamped_with_the_change() -> None:
    """M2: the Manager loses A mid-session: `cleared` now, at the change's time; and B's later
    clear (which would carry B's event time) is never sent to it."""
    edges, _ = _edges()
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    change_ms = 1_789_133_007_777
    sent = edges.rescope(_view_of(MANAGER_NONE, change_ms), change_ms, principal=MANAGER_NONE)
    assert sent == [
        {
            "kind": "safety",
            "severity": "info",
            "safety_class": "risk_lockout",
            "environment": "live",
            "state": "cleared",
            "affected_count": 0,
            "since_ms": change_ms,
        }
    ]
    assert _send(edges, _CLEARED, MANAGER_NONE) is None
    assert (
        edges.rescope(_view_of(MANAGER_NONE, change_ms + 1), change_ms + 1, principal=MANAGER_NONE)
        == []
    )


def test_an_added_grant_shows_its_live_incident_at_once() -> None:
    """M2: the Manager on A gains B while B's incident is live: `raised` without waiting for
    the publisher's next frame."""
    edges, _ = _edges()
    assert _send(edges, _ONLY_ON_B, MANAGER) is None  # kept, though nothing was sent
    sent = edges.rescope(_view_of(MANAGER_B), _NOW, principal=MANAGER_B)
    assert len(sent) == 1
    assert (sent[0]["state"], sent[0]["affected_count"], sent[0]["since_ms"]) == ("raised", 2, _T0)


def test_a_rescope_that_changes_nothing_sends_nothing() -> None:
    edges, _ = _edges()
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    assert edges.rescope(_view_of(MANAGER), _NOW, principal=MANAGER) == []


@pytest.mark.parametrize("who", [OWNER, MANAGER, VIEWER, MANAGER_NONE])
def test_a_process_global_class_reaches_every_role_whole(who: Any) -> None:
    assert system_view(_HALTED, who) is _HALTED


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({k: v for k, v in _ON_A_AND_B.items() if k != "_by_account"}, id="no-split"),
        pytest.param({k: v for k, v in _ON_A_AND_B.items() if k != "_at_ms"}, id="no-time"),
        pytest.param(_HALTED | {"_by_account": {}}, id="global-with-split"),
        pytest.param(_HALTED | {"environment": "paper"}, id="unknown-env"),
        pytest.param(_HALTED | {"safety_class": "naked"}, id="unknown-class"),
        pytest.param(_HALTED | {"exchange_account_ids": [str(ACC_A)]}, id="account-list"),
        pytest.param(_HALTED | {"affected_count": 0}, id="global-raised-with-none"),
        pytest.param(_HALTED | {"affected_count": True}, id="global-bool-count"),
        pytest.param(_HALTED | {"since_ms": -1}, id="global-negative-since"),
        pytest.param(_HALTED | {"state": "cleared"}, id="global-cleared-with-one"),
        pytest.param(_HALTED | {"state": "frob"}, id="global-unknown-state"),
    ],
)
def test_a_faulty_safety_body_reaches_the_owner_only_counted_invalid(body: Any) -> None:
    assert system_view(body, MANAGER) is None and system_view(body, VIEWER) is None
    assert withheld_reason(body, MANAGER) == "invalid_body"
    owner = system_view(body, OWNER)
    assert owner is not None and "_by_account" not in owner and "_at_ms" not in owner


def test_snapshot_items_are_cut_like_frames() -> None:
    items: list[dict[str, Any]] = [
        {
            "safety_class": "risk_lockout",
            "environment": "live",
            "state": "raised",
            "affected_count": 2,
            "since_ms": _T0,
            "_by_account": {str(ACC_B): {"affected_count": 2, "since_ms": _T0}},
        },
        {"safety_class": "native_sl_missing", "environment": "live", "state": "unknown"},
        {
            "safety_class": "order_entry_halted",
            "environment": "live",
            "state": "raised",
            "affected_count": 1,
            "since_ms": _T0,
        },
    ]
    body = {"kind": "health", "safety_classes": items}
    assert system_view(body, MANAGER) == {
        "kind": "health",
        "safety_classes": [
            {"safety_class": "risk_lockout", "environment": "live", "state": "clear"},
            items[1],
            items[2],
        ],
    }
    owner = system_view(body, OWNER)
    assert owner is not None
    assert owner["safety_classes"][0] == {k: v for k, v in items[0].items() if k[0] != "_"}


def test_a_raised_snapshot_item_without_its_breakdown_is_unknown_never_clear() -> None:
    item = {
        "safety_class": "risk_lockout",
        "environment": "live",
        "state": "raised",
        "affected_count": 1,
        "since_ms": _T0,
    }
    assert items_view([item], MANAGER) == [
        {"safety_class": "risk_lockout", "environment": "live", "state": "unknown"}
    ]


def test_the_snap_seeds_the_edges_so_a_cleared_after_it_is_sent() -> None:
    edges, _ = _edges()
    raw = {
        "kind": "health",
        "safety_classes": [
            {
                "safety_class": "risk_lockout",
                "environment": "live",
                "state": "raised",
                "affected_count": 1,
                "since_ms": _T1,
                "_by_account": {str(ACC_A): {"affected_count": 1, "since_ms": _T1}},
            }
        ],
    }
    snap = system_view(raw, MANAGER)
    assert snap is not None
    edges.seed(raw, snap, MANAGER)
    assert _send(edges, _ON_A_AND_B, MANAGER) is None  # the same count it holds
    assert _send(edges, _CLEARED, MANAGER) is not None


def test_frame_view_never_keeps_a_field_beyond_the_seven() -> None:
    body = _HALTED | {"message": "x", "reason": "y", "affected_symbols": ["BTCUSDT"]}
    assert frame_view(body, MANAGER) == _HALTED


def test_a_global_frame_is_rebuilt_with_the_severity_its_state_fixes() -> None:
    """Normalised as a snapshot item is: a scoped role never gets the producer's own severity."""
    assert frame_view(_HALTED | {"severity": "debug"}, MANAGER) == _HALTED


@pytest.mark.parametrize(
    "item",
    [
        pytest.param({"safety_class": "Risk_Lockout", "environment": "live"}, id="misspelled"),
        pytest.param({"safety_class": ["risk_lockout"], "environment": "live"}, id="list"),
        pytest.param({"safety_class": "risk_lockout", "environment": "paper"}, id="bad-env"),
        pytest.param({"safety_class": "order_entry_halted"}, id="no-env"),
    ],
)
def test_a_snapshot_item_outside_the_contract_reaches_no_scoped_role(item: Any) -> None:
    """M1, deny by default: the probe that passed whole before is dropped and counted."""
    probe = item | {
        "state": "raised",
        "affected_count": 7,
        "since_ms": 5,
        "_by_account": {str(ACC_B): {"affected_count": 7, "since_ms": 5}},
    }
    body = {"kind": "health", "safety_classes": [probe]}
    for who in (MANAGER, MANAGER_NONE, VIEWER):
        assert system_view(body, who) == {"kind": "health", "safety_classes": []}
    assert dropped_items(body["safety_classes"]) == 1


@pytest.mark.parametrize(
    "item",
    [
        pytest.param({"state": "raised", "affected_count": 0, "since_ms": 1}, id="zero"),
        pytest.param({"state": "raised"}, id="no-count"),
        pytest.param({"state": "clear", "since_ms": 1}, id="stray-since"),
        pytest.param({"state": "frob"}, id="unknown-state"),
    ],
)
def test_a_global_snapshot_item_is_rebuilt_canonical_for_a_scoped_role(item: Any) -> None:
    body = {"kind": "health", "safety_classes": [_GLOBAL_ITEM | item]}
    view = system_view(body, MANAGER)
    assert view is not None
    want = "clear" if item["state"] == "clear" else "unknown"
    assert view["safety_classes"] == [_GLOBAL_ITEM | {"state": want}]


_GLOBAL_ITEM = {"safety_class": "order_entry_halted", "environment": "live"}


def test_raised_elsewhere_and_nothing_anywhere_are_the_same_bytes() -> None:
    """L1: a scoped role cannot tell an incident on another account from none at all."""
    elsewhere = {
        "safety_class": "risk_lockout",
        "environment": "live",
        "state": "raised",
        "affected_count": 4,
        "since_ms": _T0,
        "_by_account": {str(ACC_B): {"affected_count": 4, "since_ms": _T0}},
    }
    nothing = {
        "environment": "live",
        "since_ms": 9,
        "state": "clear",
        "safety_class": "risk_lockout",
    }
    a = system_view({"kind": "health", "safety_classes": [elsewhere]}, MANAGER)
    b = system_view({"kind": "health", "safety_classes": [nothing]}, MANAGER)
    assert json.dumps(a) == json.dumps(b)


def test_the_owner_never_gets_an_in_process_key_on_any_kind() -> None:
    """L3: every `_`-prefixed key goes, on every kind, not only `safety`."""
    body = {"kind": "notice", "severity": "info", "reason": "x", "_by_account": {}, "_trace": 1}
    assert system_view(body, OWNER) == {"kind": "notice", "severity": "info", "reason": "x"}


def test_the_breakdown_may_be_keyed_by_uuid_objects() -> None:
    """L4: the publisher may hand `uuid.UUID` keys over, parsed once."""
    body = _ON_A_AND_B | {
        "_by_account": {
            ACC_A: {"affected_count": 1, "since_ms": _T1},
            ACC_B: {"affected_count": 2, "since_ms": _T0},
        }
    }
    view = system_view(body, MANAGER)
    assert view is not None and view["affected_count"] == 1


def test_observe_keeps_a_clear_the_connection_could_not_see() -> None:
    """L4: a clear seen while the cut is nothing still drops the kept body."""
    edges, _ = _edges()
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    assert edges.rescope(lambda body: None, 1, principal=None) != []  # role removed: cleared
    edges.observe(_CLEARED)  # the publisher's clear, which the gateway sees whatever the cut
    assert edges.rescope(_view_of(MANAGER, 2), 2, principal=MANAGER) == []


# -- the scoped stamp and the per-connection window (#2302) -----------------------------------

#: A on 1 and B on 2 at first; then B's count moves while A's stays.
_A1 = {ACC_A: {"affected_count": 1, "since_ms": _T1}}
_B = {ACC_B: {"affected_count": 2, "since_ms": _T0}}


def _with_b(n: int, at_ms: int) -> dict[str, Any]:
    return _raised(_A1 | {ACC_B: {"affected_count": n, "since_ms": _T0}}, at_ms=at_ms)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_CLEARED | {"_at_ms": 1_789_133_009_999}, id="shared-clear"),
        pytest.param(_raised(_B, at_ms=1_789_133_009_999), id="other-account-moves"),
    ],
)
def test_a_scoped_clear_is_stamped_at_the_gateway_whatever_shares_its_body(body: Any) -> None:
    """A's clear arrives in a body whose event time is another account's: the stamp is the
    gateway's own, so two bodies that differ only in it give the same frame."""
    edges, _ = _edges()
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    view = _send(edges, body, MANAGER)
    assert view is not None and (view["state"], view["since_ms"]) == ("cleared", _NOW)
    twin, _ = _edges()
    assert _send(twin, _ON_A_AND_B, MANAGER) is not None
    assert _send(twin, body | {"_at_ms": 1}, MANAGER) == view


def test_another_accounts_counts_start_no_window_on_a_scoped_connection() -> None:
    """B's count churns: the Manager on A is sent nothing and no window opens or moves, so its
    next own count update goes at once, exactly as on a connection that never saw B's churn."""
    churned, quiet = _edges(), _edges()
    for edges, loop in (churned, quiet):
        assert _send(edges, _raised(_A1), MANAGER) is not None
        loop.end_windows()
    edges, loop = churned
    for n in range(1, 6):
        assert _send(edges, _with_b(n, _T2 + n), MANAGER) is None
    assert loop.live() == []
    a_grew = _raised({ACC_A: {"affected_count": 4, "since_ms": _T1}} | _B)
    sent = [_send(e, a_grew, MANAGER) for e, _ in (churned, quiet)]
    assert sent[0] is not None and sent[0] == sent[1]
    assert [len(lp.live()) for _, lp in (churned, quiet)] == [1, 1]


def test_a_raise_reaches_a_scoped_connection_at_once_though_others_hold_the_key() -> None:
    """The view turning `raised` is a transition on this connection: sent at once whether or
    not another account already held the key, with the same frame either way."""
    held_elsewhere, empty = _edges(), _edges()
    assert _send(held_elsewhere[0], _ONLY_ON_B, MANAGER) is None
    a_too = _send(held_elsewhere[0], _ON_A_AND_B, MANAGER)
    alone = _send(empty[0], _raised(_A1), MANAGER)
    assert a_too is not None and a_too == alone
    assert (a_too["state"], a_too["since_ms"]) == ("raised", _T1)


def test_a_count_update_inside_the_window_waits_for_its_end_and_carries_the_latest() -> None:
    edges, loop = _edges()
    assert _send(edges, _raised(_A1), MANAGER) is not None
    assert [timer.delay for timer in loop.live()] == [WINDOW_S]
    for n in (2, 3):
        assert (
            _send(edges, _raised({ACC_A: {"affected_count": n, "since_ms": _T1}}), MANAGER) is None
        )
    loop.end_windows()
    assert loop.due == [("risk_lockout", "live")]
    sent = edges.release(("risk_lockout", "live"), _view_of(MANAGER))
    assert sent is not None and (sent["affected_count"], sent["since_ms"]) == (3, _T1)
    assert len(loop.live()) == 1  # the update it sent opened the next window


def test_a_count_back_to_what_was_sent_inside_the_window_is_never_due() -> None:
    edges, loop = _edges()
    assert _send(edges, _raised(_A1), MANAGER) is not None
    assert _send(edges, _raised({ACC_A: {"affected_count": 2, "since_ms": _T1}}), MANAGER) is None
    assert _send(edges, _raised(_A1), MANAGER) is None
    loop.end_windows()
    assert loop.due == []


def test_a_clear_inside_the_window_goes_at_once_and_discards_the_held_update() -> None:
    edges, loop = _edges()
    assert _send(edges, _raised(_A1), MANAGER) is not None
    assert _send(edges, _raised({ACC_A: {"affected_count": 2, "since_ms": _T1}}), MANAGER) is None
    cleared = _send(edges, _CLEARED, MANAGER)
    assert cleared is not None and cleared["state"] == "cleared"
    assert loop.live() == []  # its window is cancelled
    loop.end_windows()
    assert loop.due == []
    assert edges.release(("risk_lockout", "live"), _view_of(MANAGER)) is None


def test_a_rescope_sends_a_held_count_at_once_and_restarts_the_window() -> None:
    edges, loop = _edges()
    assert _send(edges, _raised(_A1), MANAGER) is not None
    assert _send(edges, _raised({ACC_A: {"affected_count": 2, "since_ms": _T1}}), MANAGER) is None
    (first,) = loop.live()
    sent = edges.rescope(_view_of(MANAGER), _NOW, principal=MANAGER)
    assert [(f["state"], f["affected_count"]) for f in sent] == [("raised", 2)]
    assert first.cancelled and len(loop.live()) == 1
    loop.end_windows()
    assert loop.due == []


def test_stop_cancels_every_window_and_starts_none_after() -> None:
    edges, loop = _edges()
    assert _send(edges, _raised(_A1), MANAGER) is not None
    edges.stop()
    assert loop.live() == []
    assert _send(edges, _raised({ACC_A: {"affected_count": 2, "since_ms": _T1}}), MANAGER)
    assert loop.live() == []


def test_the_owners_count_updates_are_windowed_on_its_own_connection() -> None:
    edges, loop = _edges()
    assert _send(edges, _ON_A_AND_B, OWNER) is not None
    assert _send(edges, _with_b(5, _T2), OWNER) is None
    loop.end_windows()
    sent = edges.release(("risk_lockout", "live"), _view_of(OWNER))
    assert sent is not None and sent["affected_count"] == 6


# -- deny by default: faulty bodies, malformed breakdowns, frozen grants ------------------------


def test_a_faulty_body_then_a_rescope_sends_no_false_clear() -> None:
    """A raised body that fails the fault check is not kept, so the rescope that follows sees
    the last valid body and ends nothing that is still raised."""
    edges, _ = _edges()
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    faulty = {k: v for k, v in _ON_A_AND_B.items() if k != "_at_ms"} | {"affected_count": 4}
    assert _send(edges, faulty, MANAGER) is None
    edges.observe(faulty)
    assert edges.rescope(_view_of(MANAGER), _NOW, principal=MANAGER) == []


def test_a_faulty_clear_drops_no_kept_body() -> None:
    edges, _ = _edges()
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    edges.observe({k: v for k, v in _CLEARED.items() if k != "_by_account"})
    assert (
        edges.rescope(_view_of(MANAGER_B), _NOW, principal=MANAGER_B) != []
    )  # B's raise is still known


@pytest.mark.parametrize(
    ("raw", "entry"),
    [
        pytest.param("not-a-uuid", {"affected_count": 9, "since_ms": 1}, id="bad-key"),
        pytest.param(12, {"affected_count": 9, "since_ms": 1}, id="int-key"),
        pytest.param(str(ACC_A), [9, 1], id="entry-not-a-map"),
        pytest.param(str(ACC_A), {"affected_count": 0, "since_ms": 1}, id="zero"),
        pytest.param(str(ACC_A), {"affected_count": True, "since_ms": 1}, id="bool-count"),
        pytest.param(str(ACC_A), {"affected_count": 9, "since_ms": -5}, id="negative-since"),
        pytest.param(str(ACC_A), {"affected_count": 9}, id="no-since"),
    ],
)
def test_a_malformed_breakdown_entry_is_dropped_and_counts_nothing(raw: Any, entry: Any) -> None:
    body = _raised(_A1) | {"_by_account": {raw: entry}}
    assert system_view(body, MANAGER, now_ms=_NOW) == _frame_cleared()
    good = body | {"_by_account": {raw: entry, ACC_A: {"affected_count": 1, "since_ms": 7}}}
    view = system_view(good, MANAGER, now_ms=_NOW)
    assert view is not None and (view["affected_count"], view["since_ms"]) == (1, 7)


def _frame_cleared() -> dict[str, Any]:
    return {
        "kind": "safety",
        "severity": "info",
        "safety_class": "risk_lockout",
        "environment": "live",
        "state": "cleared",
        "affected_count": 0,
        "since_ms": _NOW,
    }


def test_a_frozen_grant_clears_at_once_stamped_with_the_change() -> None:
    edges, _ = _edges()
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    frozen = principal("manager", grants=(AccountGrant(ACC_A, True, True, True),))
    assert edges.rescope(_view_of(frozen, _NOW + 1), _NOW + 1, principal=frozen) == [
        _frame_cleared() | {"since_ms": _NOW + 1}
    ]


def test_an_unknown_class_reaches_nobody_and_is_marked_for_the_count() -> None:
    """The Owner receives it whole from the filter; the edges send it nobody, and the gateway
    counts it `invalid_body` (`is_unkeyed`)."""
    body = _HALTED | {"safety_class": "naked"}
    owner = system_view(body, OWNER)
    assert owner is not None and is_unkeyed(owner)
    assert _edges()[0].admit(body, owner) is None
    assert not is_unkeyed(_HALTED)
