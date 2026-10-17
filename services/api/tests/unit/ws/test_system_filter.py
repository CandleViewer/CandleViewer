"""SR-188 (#2175): `system_view`, each role's view of a `system` frame (`23-ws-protocol.md` §15.9).

Pure: no socket, no clock. Every expected body is written out here, never derived from the
module's tables, so a widened table fails a test."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws.system_filter import (
    NEUTRAL_COMPONENT,
    NEUTRAL_FIELDS,
    NEUTRAL_KILL_SWITCH,
    kill_switch_view,
    system_view,
)
from tests.unit.ws._seq_support import validate

ACC_A = uuid.UUID("0a000000-0000-4000-8000-00000000000a")
ACC_B = uuid.UUID("0a000000-0000-4000-8000-00000000000b")
ENGAGER = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001"
_BUNDLE = Path(__file__).resolve().parents[5] / "docs" / "plan" / "ws-schema.json"
_SCHEMA = json.loads(_BUNDLE.read_text(encoding="utf-8"))["schemas"][
    "cv://ws/v1/system.schema.json"
]


def principal(*roles: str, grants: tuple[AccountGrant, ...] = ()) -> PrincipalSnapshot:
    return PrincipalSnapshot(uuid.UUID(int=0x2175), frozenset(roles), frozenset(), grants)


OWNER = principal("owner")
MANAGER = principal("manager", grants=(AccountGrant(ACC_A, True, True, False),))
VIEWER = principal("viewer", grants=(AccountGrant(ACC_A, True, False, False),))
DENY_ALL = principal()  # a failed principal load, and every socket on the fake backend


def _same(body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    return body, body  # role-neutral as emitted: every role gets this very object


_PART = {"name": "bybit_rest", "state": "degraded", "last_good_at": "2026-10-17T03:00:00Z"}
_HEALTH = {"kind": "health", "health": "degraded", "clock_offset_ms": 4, "degraded_topics": []}
_HALT = {"kind": "kill_switch", "severity": "critical", "message": "Trading halted."}
_STATE = {"engaged": True, "scope": "accounts", "engaged_at_ms": 1789133000000}
_WHO = {"engaged_by": ENGAGER, "engaged_by_username": "owner.alice", "reason": "B breached its cap"}
_BOTH = {"exchange_account_ids": [str(ACC_A), str(ACC_B)]}

#: kind -> (the frame as emitted, what a Manager or Viewer viewing account A gets; None: nothing).
SAMPLES: dict[str, tuple[dict[str, Any], dict[str, Any] | None]] = {
    "health": (
        _HEALTH
        | {"components": [_PART | {"detail": "acct 1"}], "feature_flags": {"a.b": True}}
        | {"kill_switch": {"engaged": True, "scope": "global", "engaged_by": ENGAGER}},
        _HEALTH | {"components": [_PART], "kill_switch": {"engaged": True, "scope": "global"}},
    ),
    "kill_switch": (
        _HALT | {"kill_switch": _STATE | _WHO | _BOTH, "actions": {"orders_cancelled": 7}},
        _HALT | {"kill_switch": _STATE | {"exchange_account_ids": [str(ACC_A)]}},
    ),
    "feature_flags": (
        {"kind": "feature_flags", "feature_flags": {"storage.cold_tier": False}},
        None,
    ),
    "exchange_state": _same({"kind": "exchange_state", "public_ws": "resyncing"}),
    "connection_quality": _same({"kind": "connection_quality", "class": "lagging", "rtt_ms": 200}),
    "shutdown_notice": _same(
        {"kind": "shutdown_notice", "reason": "deploy", "closing_in_ms": 5000}
    ),
    "degraded_data": _same({"kind": "degraded_data", "affected_symbols": ["BTCUSDT"]}),
    "clock_drift": _same({"kind": "clock_drift", "severity": "warning", "clock_offset_ms": 900}),
    "notice": _same({"kind": "notice", "severity": "critical", "reason": "net.binding_safe"}),
}


def _frame(body: Any) -> dict[str, Any]:
    return {"t": "d", "ch": "system", "s": 1, "ts": 1, "e": "j", "p": body}


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_owner_receives_every_contract_kind_whole(kind: str) -> None:
    body, _ = SAMPLES[kind]
    assert system_view(body, OWNER) is body
    validate(_frame(body))


@pytest.mark.parametrize("who", [MANAGER, VIEWER], ids=["manager", "viewer"])
@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_manager_and_viewer_receive_only_the_role_neutral_fields(
    kind: str, who: PrincipalSnapshot
) -> None:
    body, neutral = SAMPLES[kind]
    view = system_view(body, who)
    assert view == neutral
    if neutral is body:
        assert view is body  # nothing to leave out: passed on as is, never copied
    if view is not None:
        validate(_frame(view))


@pytest.mark.parametrize(
    ("grants", "ids", "kept"),
    [
        ((), [str(ACC_A), str(ACC_B)], []),  # no grant: the state still arrives, no account
        ((AccountGrant(ACC_A, False, True, False),), [str(ACC_A)], []),  # no view grant
        ((AccountGrant(ACC_A, True, False, True),), [str(ACC_A)], [str(ACC_A)]),  # frozen
        ((AccountGrant(ACC_A, True, False, False),), [str(ACC_A).upper(), ACC_A], [str(ACC_A)] * 2),
        ((AccountGrant(ACC_A, True, False, False),), ["no", 7, None, [str(ACC_A)]], []),
        ((AccountGrant(ACC_A, True, False, False),), str(ACC_A), []),  # not a list
    ],
    ids=["no-grant", "no-view", "frozen", "canonical", "malformed", "not-a-list"],
)
def test_kill_switch_accounts_are_cut_to_the_connections_account_scope(
    grants: tuple[AccountGrant, ...], ids: Any, kept: list[str]
) -> None:
    state = {"engaged": True, "scope": "accounts", "exchange_account_ids": ids}
    view = system_view(
        {"kind": "kill_switch", "kill_switch": state}, principal("viewer", grants=grants)
    )
    assert view == {"kind": "kill_switch", "kill_switch": state | {"exchange_account_ids": kept}}


@pytest.mark.parametrize("who", [OWNER, MANAGER, VIEWER, DENY_ALL])
def test_kill_switch_view_equals_the_system_frames_kill_switch(who: PrincipalSnapshot) -> None:
    state = SAMPLES["kill_switch"][0]["kill_switch"]  # what `auth_ok` carries is the same cut
    frame = system_view({"kind": "kill_switch", "kill_switch": state}, who)
    assert kill_switch_view(state, who) == (None if frame is None else frame["kill_switch"])


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "kill_switch"},
        {"kind": "kill_switch", "kill_switch": None},
        {"kind": "kill_switch", "kill_switch": "engaged", "severity": "critical"},
    ],
    ids=["missing", "null", "not-an-object"],
)
def test_a_kill_switch_frame_without_its_state_reaches_only_the_owner(body: dict[str, Any]) -> None:
    assert system_view(body, OWNER) is body
    assert system_view(body, MANAGER) is None and system_view(body, VIEWER) is None


def test_a_health_frame_drops_a_kill_switch_that_is_not_an_object() -> None:
    body = {"kind": "health", "health": "healthy", "kill_switch": ["engaged"]}
    assert system_view(body, VIEWER) == {"kind": "health", "health": "healthy"}


@pytest.mark.parametrize("who", [OWNER, MANAGER, VIEWER, DENY_ALL, None])
@pytest.mark.parametrize(
    "body",
    [
        *({"kind": kind} for kind in ("tick", "Notice", "", None, 7, ["notice"])),
        {"message": "no kind"},
        ["notice"],
        "notice",
        None,
    ],
)
def test_an_unknown_kind_or_a_non_object_reaches_nobody(
    body: Any, who: PrincipalSnapshot | None
) -> None:
    assert system_view(body, who) is None


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_a_connection_with_no_principal_or_no_role_gets_nothing(kind: str) -> None:
    body, _ = SAMPLES[kind]
    assert system_view(body, None) is None
    assert system_view(body, DENY_ALL) is None


def test_a_view_never_changes_the_frame_the_owner_still_gets_whole() -> None:
    body, neutral = SAMPLES["kill_switch"]
    before = copy.deepcopy(body)
    assert system_view(body, MANAGER) == neutral
    assert body == before
    assert system_view(body, OWNER) is body


def test_the_kind_table_is_the_contract_enum_and_names_only_schema_fields() -> None:
    """A `kind` added to §15.9 fails here until someone decides who may see it."""
    assert set(NEUTRAL_FIELDS) == set(_SCHEMA["properties"]["kind"]["enum"])
    assert all(fields <= set(_SCHEMA["properties"]) for fields in NEUTRAL_FIELDS.values())
    assert NEUTRAL_KILL_SWITCH < set(_SCHEMA["$defs"]["killSwitch"]["properties"])
    assert NEUTRAL_COMPONENT < set(_SCHEMA["properties"]["components"]["items"]["properties"])


_OWNER_ONLY = frozenset({"feature_flags", "actions"})
_OWNER_ONLY_STATE = frozenset({"engaged_by", "engaged_by_username", "reason"})
_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=4),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=4), inner),
    max_leaves=5,
)
_IDS = st.lists(st.sampled_from([str(ACC_A), str(ACC_B), str(ACC_B).upper(), "x"]), max_size=3)
_PART_KEYS = st.sampled_from(["name", "state", "detail", "last_good_at", "x"])
_STATE_KEYS = st.sampled_from([*sorted(_SCHEMA["$defs"]["killSwitch"]["properties"]), "x"])


@settings(max_examples=200, deadline=None)
@given(
    kind=st.sampled_from(sorted(NEUTRAL_FIELDS)),
    extra=st.dictionaries(
        st.sampled_from(sorted(_SCHEMA["properties"])) | st.text(max_size=6), _VALUES
    ),
    state=st.dictionaries(_STATE_KEYS, _VALUES | _IDS) | _VALUES,
    parts=st.lists(st.dictionaries(_PART_KEYS, _VALUES), max_size=3) | _VALUES,
    who=st.sampled_from([MANAGER, VIEWER, principal("manager"), principal("viewer", "manager")]),
)
def test_no_manager_or_viewer_view_carries_an_owner_only_field_or_a_foreign_account(
    kind: str, extra: dict[str, Any], state: Any, parts: Any, who: PrincipalSnapshot
) -> None:
    view = system_view(extra | {"kind": kind, "kill_switch": state, "components": parts}, who)
    if view is None:
        return
    assert set(view) <= NEUTRAL_FIELDS[kind] and not set(view) & _OWNER_ONLY
    for item in view.get("components") or ():
        assert set(item) <= {"name", "state", "last_good_at"}  # never `detail`
    held = view.get("kill_switch")
    if held is None:
        return
    assert set(held) <= NEUTRAL_KILL_SWITCH | {"exchange_account_ids"}
    assert not set(held) & _OWNER_ONLY_STATE
    viewable = {str(g.exchange_account_id) for g in who.account_grants if g.can_view}
    assert set(held.get("exchange_account_ids") or ()) <= viewable
