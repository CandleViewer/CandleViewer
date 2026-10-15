"""E42-T03: the pure resolver. One table row per branch of user override, role override,
percentage rollout and stored value, for each flag kind, plus the fail-closed fallbacks."""

from __future__ import annotations

from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.admin.flags import (
    Category,
    FlagKind,
    FlagSpec,
    FlagValue,
    StoredFlag,
    default_registry,
    resolve,
    rollout_bucket,
)

_U1 = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001")
_U2 = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002")
_BOOL = FlagSpec("ui.panel", FlagKind.BOOLEAN, "d", Category.UI_SURFACE, False)
_PCT = FlagSpec("ui.rollout", FlagKind.PERCENTAGE, "d", Category.FEATURE_ROLLOUT, 0)
_VAR = FlagSpec(
    "ui.renderer", FlagKind.VARIANT, "d", Category.FEATURE_ROLLOUT, "a", variants=("a", "b", "c")
)
_OWNER, _MANAGER = frozenset({"owner"}), frozenset({"manager"})


@pytest.mark.parametrize(
    ("spec", "stored", "user", "roles", "expected"),
    [
        # boolean: user override > role override > stored value
        (_BOOL, StoredFlag(False, {_U1: True}, {"owner": False}), _U1, _OWNER, True),
        (_BOOL, StoredFlag(False, {_U2: True}, {"owner": True}), _U1, _OWNER, True),
        (_BOOL, StoredFlag(True, {}, {"manager": False}), _U1, _MANAGER, False),
        (_BOOL, StoredFlag(True, {}, {"manager": False}), _U1, _OWNER, True),
        (_BOOL, StoredFlag(True), None, frozenset(), True),
        # percentage: overrides pin in/out; else the bucket; no user means 100 % only
        (_PCT, StoredFlag(100, {_U1: False}), _U1, _OWNER, False),
        (_PCT, StoredFlag(0, {}, {"owner": True}), _U1, _OWNER, True),
        (_PCT, StoredFlag(0), _U1, _OWNER, False),
        (_PCT, StoredFlag(100), _U1, _OWNER, True),
        (_PCT, StoredFlag(99), None, frozenset(), False),
        (_PCT, StoredFlag(100), None, frozenset(), True),
        # variant: user override > role override > stored value
        (_VAR, StoredFlag("a", {_U1: "c"}, {"owner": "b"}), _U1, _OWNER, "c"),
        (_VAR, StoredFlag("a", {}, {"owner": "b"}), _U1, _OWNER, "b"),
        (_VAR, StoredFlag("b"), _U1, _MANAGER, "b"),
    ],
)
def test_resolution_order_per_kind(
    spec: FlagSpec,
    stored: StoredFlag,
    user: UUID | None,
    roles: frozenset[str],
    expected: FlagValue,
) -> None:
    assert resolve(spec, stored, user_id=user, roles=roles) == expected


def test_role_overrides_follow_the_fixed_role_order() -> None:
    stored = StoredFlag(False, {}, {"viewer": False, "owner": True})
    assert resolve(_BOOL, stored, user_id=_U1, roles=frozenset({"viewer", "owner"})) is True


@pytest.mark.parametrize("pct", [1, 37, 50, 99])
def test_percentage_rollout_uses_the_users_stable_bucket(pct: int) -> None:
    expected = rollout_bucket(_U1, _PCT.key) < pct
    assert resolve(_PCT, StoredFlag(pct), user_id=_U1) is expected


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("maintenance.mode", True),
        ("killswitch.order_entry", True),
        ("trading.live_enabled", False),
        ("killswitch.ingestion", False),
        ("rules.graph_editor", True),
    ],
)
def test_unreachable_store_fails_closed_to_the_restrictive_value(key: str, expected: bool) -> None:
    assert resolve(default_registry()[key], None, user_id=_U1, roles=_OWNER) is expected


def test_a_stored_value_of_the_wrong_kind_is_ignored_and_fails_closed() -> None:
    maintenance = default_registry()["maintenance.mode"]
    assert resolve(maintenance, StoredFlag("off"), user_id=None) is True
    assert resolve(_VAR, StoredFlag("zzz"), user_id=_U1) == "a"


def test_overrides_of_the_wrong_kind_are_skipped() -> None:
    stored = StoredFlag(False, {_U1: "yes"}, {"owner": 1})
    assert resolve(_BOOL, stored, user_id=_U1, roles=_OWNER) is False
    assert resolve(_PCT, StoredFlag(0, {_U1: 100}), user_id=_U1) is False


def test_unreachable_percentage_flag_uses_its_fail_closed_rollout() -> None:
    assert resolve(_PCT, None, user_id=_U1) is False


@given(st.uuids(), st.from_regex(r"[a-z]+\.[a-z_]+", fullmatch=True))
def test_rollout_bucket_is_stable_and_in_range(user: UUID, key: str) -> None:
    bucket = rollout_bucket(user, key)
    assert 0 <= bucket < 100
    assert rollout_bucket(user, key) == bucket
