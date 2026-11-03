"""#2302 (`23-ws-protocol.md` §15.9, `24-internal-schemas.md` §8.13): each connection's view of
the `system` safety summary. An account-keyed class is counted over the connection's
`account_scope` (C-12.4), with its own raised/cleared edges, so a Manager scoped away from an
incident learns nothing of it: not its existence, its size or its timing. A process-global class
reaches every role whole. The in-process breakdown is never in any role's view."""

from __future__ import annotations

import json
from typing import Any

import pytest

from candleviewer.auth.scopes import AccountGrant
from candleviewer.ws.safety_view import SafetyEdges, dropped_items, frame_view, items_view
from candleviewer.ws.system_filter import system_view, withheld_reason
from tests.unit.ws.test_system_filter import ACC_A, ACC_B, MANAGER, OWNER, VIEWER, principal

_T0, _T1, _T2 = 1_789_133_000_000, 1_789_133_005_000, 1_789_133_009_000
MANAGER_B = principal("manager", grants=(AccountGrant(ACC_B, True, True, False),))
MANAGER_NONE = principal("manager")


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


def _send(edges: SafetyEdges, body: dict[str, Any], who: Any) -> Any:
    """What a connection of `who` is sent of `body`, as `_Connection.push_system` decides."""
    view = system_view(body, who)
    return None if view is None else edges.admit(body, view)


def test_idor_a_manager_scoped_to_a_gets_no_frame_for_a_subject_on_b() -> None:
    """Not a raised frame, not a cleared one, not a boolean: existence leaks too."""
    view = system_view(_ONLY_ON_B, MANAGER)
    assert view is not None and view["state"] == "cleared"  # its own state: nothing in scope
    assert _send(SafetyEdges(), _ONLY_ON_B, MANAGER) is None  # it never saw a `raised`
    assert str(ACC_B) not in json.dumps(view)


def test_a_manager_scoped_to_b_sees_the_incident_on_b() -> None:
    view = system_view(_ONLY_ON_B, MANAGER_B)
    assert view is not None
    assert (view["state"], view["affected_count"], view["since_ms"]) == ("raised", 2, _T0)


def test_a_count_change_on_another_account_sends_a_scoped_connection_nothing() -> None:
    """B's count moving is no frame for a Manager on A: no timing side channel."""
    edges = SafetyEdges()
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    b_grew = _raised(
        {
            ACC_A: {"affected_count": 1, "since_ms": _T1},
            ACC_B: {"affected_count": 5, "since_ms": _T0},
        }
    )
    assert _send(edges, b_grew, MANAGER) is None


def test_a_cleared_reaches_a_connection_only_after_its_own_raised() -> None:
    edges = SafetyEdges()
    assert _send(edges, _CLEARED, MANAGER) is None
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    assert _send(edges, _CLEARED, MANAGER) is not None
    assert _send(edges, _CLEARED, MANAGER) is None  # once only


def test_a_scoped_cleared_follows_its_last_account_leaving_while_others_stay() -> None:
    """A clears and B stays raised: the Manager on A gets its own `cleared` at the event time."""
    edges = SafetyEdges()
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    view = _send(edges, _ONLY_ON_B, MANAGER)
    assert view is not None
    assert (view["state"], view["severity"], view["affected_count"]) == ("cleared", "info", 0)


def test_the_episode_start_stays_put_on_count_updates() -> None:
    """L2: the connection's `since_ms` is its episode's start while its view stays raised, even
    when the account that raised first leaves and a later one stays."""
    who = principal(
        "manager",
        grants=(AccountGrant(ACC_A, True, True, False), AccountGrant(ACC_B, True, True, False)),
    )
    edges = SafetyEdges()
    first = _send(edges, _ON_A_AND_B, who)
    assert first is not None and (first["affected_count"], first["since_ms"]) == (3, _T0)
    a_only = _raised({ACC_A: {"affected_count": 2, "since_ms": _T1}})
    later = _send(edges, a_only, who)
    assert later is not None and (later["affected_count"], later["since_ms"]) == (2, _T0)


def test_a_revoked_grant_sends_cleared_at_once_stamped_with_the_change() -> None:
    """M2: the Manager loses A mid-session: `cleared` now, at the change's time; and B's later
    clear (which would carry B's event time) is never sent to it."""
    edges = SafetyEdges()
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    change_ms = 1_789_133_007_777
    sent = edges.rescope(lambda body: system_view(body, MANAGER_NONE), change_ms)
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
    assert edges.rescope(lambda body: system_view(body, MANAGER_NONE), change_ms + 1) == []


def test_an_added_grant_shows_its_live_incident_at_once() -> None:
    """M2: the Manager on A gains B while B's incident is live: `raised` without waiting for
    the publisher's next frame."""
    edges = SafetyEdges()
    assert _send(edges, _ONLY_ON_B, MANAGER) is None  # kept, though nothing was sent
    sent = edges.rescope(lambda body: system_view(body, MANAGER_B), 1_789_133_008_000)
    assert len(sent) == 1
    assert (sent[0]["state"], sent[0]["affected_count"], sent[0]["since_ms"]) == ("raised", 2, _T0)


def test_a_rescope_that_changes_nothing_sends_nothing() -> None:
    edges = SafetyEdges()
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    assert edges.rescope(lambda body: system_view(body, MANAGER), 1_789_133_008_000) == []


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
    ],
)
def test_a_faulty_safety_body_reaches_the_owner_only_counted_invalid(body: Any) -> None:
    assert system_view(body, MANAGER) is None and system_view(body, VIEWER) is None
    assert withheld_reason(body, MANAGER) == "invalid_body"
    owner = system_view(body, OWNER)
    assert owner is not None and "_by_account" not in owner and "_at_ms" not in owner


def test_snapshot_items_are_cut_like_frames() -> None:
    items = [
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
    edges = SafetyEdges()
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
    edges.seed(raw, snap)
    assert _send(edges, _ON_A_AND_B, MANAGER) is None  # the same count it holds
    assert _send(edges, _CLEARED, MANAGER) is not None


def test_frame_view_never_keeps_a_field_beyond_the_seven() -> None:
    body = _HALTED | {"message": "x", "reason": "y", "affected_symbols": ["BTCUSDT"]}
    assert frame_view(body, MANAGER) == _HALTED


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
    edges = SafetyEdges()
    assert _send(edges, _ON_A_AND_B, MANAGER) is not None
    assert edges.rescope(lambda body: None, 1) != []  # role removed: cleared
    edges.observe(_CLEARED)  # the publisher's clear, which the gateway sees whatever the cut
    assert edges.rescope(lambda body: system_view(body, MANAGER), 2) == []
