"""E42-T03: the feature-flag registry refuses any definition that gates a security control
(C-4.14), at construction (import) and again when the service builds the registry at startup."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.flags import (
    DENIED,
    Category,
    FlagKind,
    FlagRegistry,
    FlagSpec,
    FlagValue,
    UnsafeFlagDefinitionError,
    Visibility,
    value_matches,
)

_DENIED_MEMBERS = [m for m in Category if m in DENIED]
_B = FlagKind.BOOLEAN


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


def test_denied_set_is_exactly_the_security_controls() -> None:
    names = {m.name for m in _DENIED_MEMBERS}
    assert names == {
        "AUTH",
        "RBAC",
        "AUDIT",
        "NATIVE_STOP_LOSS",
        "RISK_LIMITS",
        "WITHDRAWAL_CHECK",
        "RATE_LIMIT_RESERVE",
        "ENVIRONMENT_ISOLATION",
    }


@pytest.mark.parametrize("category", _DENIED_MEMBERS, ids=lambda c: c.name)
def test_spec_gating_a_denied_category_is_refused_naming_flag_and_category(
    category: Category,
) -> None:
    with pytest.raises(UnsafeFlagDefinitionError) as exc:
        _spec("ui.sneaky", Category.UI_SURFACE | category)
    message = str(exc.value)
    assert "'ui.sneaky'" in message
    assert str(category.name).lower() in message
    assert "C-4.14" in message


def test_registry_rechecks_every_spec_at_startup() -> None:
    """A spec that escaped its constructor check (here forced past it) still stops startup."""
    smuggled, valid = object.__new__(FlagSpec), _spec("auth.bypass")
    for field in dataclasses.fields(FlagSpec):  # every field, so a new one never leaves this stale
        object.__setattr__(smuggled, field.name, getattr(valid, field.name))
    object.__setattr__(smuggled, "gates", Category.RBAC)
    with pytest.raises(UnsafeFlagDefinitionError, match=r"'auth\.bypass'.*'rbac'"):
        FlagRegistry([_spec(), smuggled])


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"key": "Bad.Key"}, "malformed"),
        ({"key": "single"}, "malformed"),
        ({"key": "a.b.c.d.e"}, "malformed"),
        ({"key": "a_b.c"}, "malformed"),
        ({"key": "a.b."}, "malformed"),
        ({"gates": Category(0)}, "no gate category"),
        ({"default": 1}, "is not a boolean"),
        ({"kind": FlagKind.PERCENTAGE, "default": 101}, "is not a percentage"),
        ({"kind": FlagKind.VARIANT, "default": "c", "variants": ("a",)}, "is not a variant"),
        ({"default": False, "restrictive": "yes"}, "is not a boolean"),
        ({"visibility": "all_roles"}, "declares no visibility"),
        ({"kind": FlagKind.PERCENTAGE, "default": 5, "is_killswitch": True}, "must be boolean"),
        (
            {
                "kind": FlagKind.VARIANT,
                "default": "a",
                "variants": ("a",),
                "requires_evidence": True,
            },
            "must be boolean",
        ),
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


@pytest.mark.parametrize("key", ["a.b", "a1.b_2", "a.b.c.d"])
def test_keys_of_two_to_four_segments_are_accepted(key: str) -> None:
    assert _spec(key).key == key


@pytest.mark.parametrize(
    ("kwargs", "overridable"),
    [
        ({}, True),
        ({"requires_evidence": True}, False),
        ({"is_killswitch": True, "gates": Category.KILL_SWITCH}, False),
    ],
)
def test_only_ordinary_flags_are_overridable(kwargs: dict[str, Any], overridable: bool) -> None:
    assert _spec(**kwargs).overridable is overridable


def test_visibility_is_mandatory_with_no_default() -> None:
    with pytest.raises(TypeError, match="visibility"):
        FlagSpec("ui.panel", _B, "d", Category.UI_SURFACE, False)  # type: ignore[call-arg]  # pinned
