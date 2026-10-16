"""E42-T03: the flag registry refuses a definition that gates a security control (C-4.14) or whose
class disagrees with its gates (D2a), at construction (import) and again at startup."""

from __future__ import annotations

import dataclasses
import functools
import operator
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.flags import (
    Category,
    FlagKind,
    FlagRegistry,
    FlagSpec,
    FlagValue,
    UnsafeFlagDefinitionError,
    Visibility,
    value_matches,
)

_B = FlagKind.BOOLEAN
#: The five categories a flag may gate; every other one is a security control (C-4.14).
_ALLOWED = {"UI_SURFACE", "FEATURE_ROLLOUT", "OPERATIONS", "LIVE_GATE", "KILL_SWITCH"}


def _spec(
    key: str = "ui.panel",
    gates: Category = Category.UI_SURFACE,
    *,
    kind: FlagKind = _B,
    default: FlagValue = False,
    variants: tuple[str, ...] = (),
    restrictive: FlagValue | None = None,
    is_killswitch: bool = False,
    requires_evidence: bool = False,
    visibility: Visibility = Visibility.ALL_ROLES,
) -> FlagSpec:
    return FlagSpec(
        key,
        kind,
        "d",
        gates,
        default,
        visibility,
        variants=variants,
        restrictive=restrictive,
        is_killswitch=is_killswitch,
        requires_evidence=requires_evidence,
    )


def test_the_denied_category_truth_table() -> None:
    """All 8,192 gate sets, each with its class booleans: only a non-empty set of the five allowed
    categories is accepted, and a refused security control is named with the flag and C-4.14."""
    members = list(Category)
    for bits in range(1 << len(members)):
        chosen = [m for i, m in enumerate(members) if bits >> i & 1]
        gates = functools.reduce(operator.or_, chosen, Category(0))
        kill, live = Category.KILL_SWITCH in gates, Category.LIVE_GATE in gates
        try:
            _spec("ui.sneaky", gates, is_killswitch=kill, requires_evidence=live)
        except UnsafeFlagDefinitionError as exc:
            denied = [str(m.name).lower() for m in chosen if m.name not in _ALLOWED]
            assert not gates or (denied and "C-4.14" in str(exc) and "'ui.sneaky'" in str(exc))
            assert all(name in str(exc) for name in denied)
        else:
            assert chosen and all(m.name in _ALLOWED for m in chosen), gates


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [("gates", Category.RBAC, r"'auth\.bypass'.*'rbac'"), ("visibility", None, "no visibility")],
)
def test_registry_rechecks_every_spec_at_startup(field: str, value: object, match: str) -> None:
    """A spec that escaped its constructor check (here forced past it) still stops startup."""
    smuggled, valid = object.__new__(FlagSpec), _spec("auth.bypass")
    for each in dataclasses.fields(FlagSpec):  # every field, so a new one never leaves this stale
        object.__setattr__(smuggled, each.name, getattr(valid, each.name))
    object.__setattr__(smuggled, field, value)
    with pytest.raises(UnsafeFlagDefinitionError, match=match):
        FlagRegistry([_spec(), smuggled])


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"key": "Bad.Key"}, "malformed"),
        ({"key": "single"}, "malformed"),
        ({"key": "a.b.c.d.e"}, "malformed"),
        ({"key": "a_b.c"}, "malformed"),
        ({"key": "a.b."}, "malformed"),
        ({"key": "a.b\n"}, "malformed"),  # fullmatch: `$` alone would admit a trailing newline
        ({"key": "a." + "b" * 79}, "malformed"),  # 81 characters: over the flagKey maxLength
        ({"gates": Category(0)}, "no gate category"),
        ({"default": 1}, "is not a boolean"),
        ({"kind": FlagKind.PERCENTAGE, "default": 101}, "is not a percentage"),
        ({"kind": FlagKind.VARIANT, "default": "c", "variants": ("a",)}, "is not a variant"),
        ({"default": False, "restrictive": "yes"}, "is not a boolean"),
        ({"visibility": "all_roles"}, "declares no visibility"),
        ({"kind": FlagKind.PERCENTAGE, "default": 5, "is_killswitch": True}, "must be boolean"),
        ({"kind": FlagKind.PERCENTAGE, "default": 5, "requires_evidence": True}, "must be boolean"),
        ({"gates": Category.KILL_SWITCH}, "class and gates disagree"),
        ({"is_killswitch": True}, "class and gates disagree"),
        ({"gates": Category.LIVE_GATE}, "class and gates disagree"),
        ({"requires_evidence": True}, "class and gates disagree"),
        ({"key": "killswitch.foo", "gates": Category.OPERATIONS}, "class and gates disagree"),
    ],
)
def test_malformed_definitions_are_refused(kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(UnsafeFlagDefinitionError, match=match):
        _spec(**kwargs)


def test_duplicate_keys_are_refused() -> None:
    with pytest.raises(UnsafeFlagDefinitionError, match="defined twice"):
        FlagRegistry([_spec(), _spec()])


@pytest.mark.parametrize(
    ("kind", "value", "ok"),
    [
        (_B, True, True),
        (_B, 1, False),
        (FlagKind.PERCENTAGE, 0, True),
        (FlagKind.PERCENTAGE, 100, True),
        (FlagKind.PERCENTAGE, True, False),
        (FlagKind.PERCENTAGE, -1, False),
        (FlagKind.VARIANT, "a", True),
        (FlagKind.VARIANT, "z", False),
    ],
)
def test_value_matches_the_kind_strictly(kind: FlagKind, value: object, ok: bool) -> None:
    defaults: dict[FlagKind, FlagValue] = {_B: False, FlagKind.PERCENTAGE: 0, FlagKind.VARIANT: "a"}
    default = defaults[kind]
    spec = _spec(kind=kind, default=default, variants=("a",) if kind is FlagKind.VARIANT else ())
    assert value_matches(spec, value) is ok


def test_fail_closed_value_is_the_restrictive_value_when_declared() -> None:
    assert _spec().fail_closed_value is False
    assert _spec(restrictive=True).fail_closed_value is True


def test_startup_log_lists_every_flag_with_its_gates() -> None:
    registry = FlagRegistry(
        [_spec(), _spec("ops.halt", Category.KILL_SWITCH | Category.OPERATIONS, is_killswitch=True)]
    )
    with capture_logs() as logs:
        registry.log_startup()
    (entry,) = logs
    assert entry["event"] == "feature_flag_registry"
    by_key = {f["key"]: f for f in entry["flags"]}
    assert set(by_key) == set(registry) == {"ui.panel", "ops.halt"}
    assert by_key["ops.halt"]["gates"] == ["operations", "kill_switch"]
    assert by_key["ops.halt"]["is_killswitch"] is True
    assert by_key["ui.panel"] == {
        "key": "ui.panel",
        "kind": "boolean",
        "gates": ["ui_surface"],
        "visibility": "all_roles",
        "is_killswitch": False,
    }
    assert registry["ui.panel"].key == "ui.panel" and len(registry) == 2


@pytest.mark.parametrize("key", ["a.b", "a1.b_2", "a.b.c.d", "a." + "b" * 78])
def test_keys_of_two_to_four_segments_are_accepted(key: str) -> None:
    assert _spec(key).key == key


@pytest.mark.parametrize(
    ("kwargs", "overridable"),
    [
        ({}, True),
        ({"requires_evidence": True, "gates": Category.LIVE_GATE}, False),
        ({"is_killswitch": True, "gates": Category.KILL_SWITCH}, False),
    ],
)
def test_only_ordinary_flags_are_overridable(kwargs: dict[str, Any], overridable: bool) -> None:
    assert _spec(**kwargs).overridable is overridable


def test_visibility_is_mandatory_with_no_default() -> None:
    with pytest.raises(TypeError, match="visibility"):
        FlagSpec("ui.panel", _B, "d", Category.UI_SURFACE, False)  # type: ignore[call-arg]  # visibility has no default (D6a)
