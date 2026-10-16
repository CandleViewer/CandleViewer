"""E42-T03: the pure resolver. One table row per branch of user override, role override,
percentage rollout and stored value, for each flag kind, plus the fail-closed fallbacks; properties
pin totality, rollout monotonicity and the safety flags' indifference to every override (D2a)."""

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
    Visibility,
    default_registry,
    resolve,
    rollout_bucket,
)

_U1 = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001")
_U2 = UUID("9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002")
_ALL, _ROLL = Visibility.ALL_ROLES, Category.FEATURE_ROLLOUT
_BOOL = FlagSpec("ui.panel", FlagKind.BOOLEAN, "d", Category.UI_SURFACE, False, _ALL)
_PCT = FlagSpec("ui.rollout", FlagKind.PERCENTAGE, "d", _ROLL, 0, _ALL)
_VAR = FlagSpec("ui.renderer", FlagKind.VARIANT, "d", _ROLL, "a", _ALL, variants=("a", "b", "c"))
_ORDER = FlagSpec(
    "ui.order", FlagKind.VARIANT, "d", _ROLL, "s", _ALL, variants=("s", "o", "m", "v")
)
_OWNER, _MANAGER = frozenset({"owner"}), frozenset({"manager"})
_ROLES = ("owner", "manager", "viewer")
_VALUES = st.one_of(st.booleans(), st.integers(-1, 101), st.sampled_from(["a", "b", "c", "x"]))
_USERS, _BY_ROLE = (
    st.dictionaries(st.just(_U1), _VALUES),
    st.dictionaries(st.sampled_from(_ROLES), _VALUES),
)
_SAFETY = [spec for spec in default_registry().values() if not spec.overridable]


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
        (_PCT, StoredFlag(72), _U1, _OWNER, False),  # bucket(_U1) == 72: `<`, never `<=`
        (_PCT, StoredFlag(73), _U1, _OWNER, True),
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


@pytest.mark.parametrize(
    ("roles", "expected"),
    [({"owner", "manager", "viewer"}, "o"), ({"manager", "viewer"}, "m"), ({"viewer"}, "v")],
)
def test_role_overrides_rank_owner_then_manager_then_viewer(roles: set[str], expected: str) -> None:
    stored = StoredFlag("s", {}, {"owner": "o", "manager": "m", "viewer": "v"})
    assert resolve(_ORDER, stored, user_id=_U1, roles=frozenset(roles)) == expected


@given(st.uuids(), st.integers(0, 100), st.integers(0, 100))
def test_rollout_is_monotonic_in_the_percentage(user: UUID, a: int, b: int) -> None:
    in_low, in_high = (resolve(_PCT, StoredFlag(p), user_id=user) for p in sorted((a, b)))
    assert in_low <= in_high


@given(
    st.sampled_from([_BOOL, _PCT, _VAR]),
    st.none() | st.builds(StoredFlag, _VALUES, _USERS, _BY_ROLE),
    st.sampled_from([_U1, _U2, None]),
    st.frozensets(st.sampled_from(_ROLES)),
)
def test_resolution_is_total_and_of_the_flags_kind(
    spec: FlagSpec, stored: StoredFlag | None, user: UUID | None, roles: frozenset[str]
) -> None:
    value = resolve(spec, stored, user_id=user, roles=roles)
    assert value in spec.variants if spec.kind is FlagKind.VARIANT else isinstance(value, bool)


@given(st.sampled_from(_SAFETY), st.booleans(), _USERS, _BY_ROLE)
def test_safety_flags_ignore_every_override_and_fail_closed(
    spec: FlagSpec, value: bool, users: dict[UUID, FlagValue], roles: dict[str, FlagValue]
) -> None:
    """D2a for the live gate and every kill switch; an outage gives the restrictive value."""
    stored, everyone = StoredFlag(value, users, roles), frozenset(_ROLES)
    assert resolve(spec, stored, user_id=_U1, roles=everyone) is value
    assert resolve(spec, None, user_id=_U1) is spec.fail_closed_value


def test_an_unreadable_row_ignores_its_overrides_too() -> None:
    """D1b: a stored value of the wrong kind fails that flag alone closed, overrides included."""
    assert resolve(default_registry()["maintenance.mode"], StoredFlag("off"), user_id=None) is True
    stored = StoredFlag("zzz", {_U1: "c"}, {"owner": "b"})
    assert resolve(_VAR, stored, user_id=_U1, roles=_OWNER) == "a"


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


@pytest.mark.parametrize(
    ("user", "key", "bucket"),
    [(_U1, "ui.rollout", 72), (_U2, "ui.rollout", 15), (_U1, "engine.webgl_v2", 42)],
)
def test_rollout_bucket_golden_vectors(user: UUID, key: str, bucket: int) -> None:
    assert rollout_bucket(user, key) == bucket
