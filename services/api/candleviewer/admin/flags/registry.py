"""Feature-flag registry and security-control allowlist (E42-T03, module M21).

"No flag may weaken a security control" (US-ADMIN-007, C-4.14), so flag definitions are code,
reviewed like code and never editable at runtime. Each `FlagSpec` declares what it may gate as
`Category` members. The categories that are security controls (authentication, RBAC enforcement,
audit writing, the native stop-loss invariant, risk limits, the withdrawal check, the rate-limit
reserve and demo/live isolation) are in `DENIED`, and no spec may declare one:

`FlagSpec` refuses such a definition when constructed (so its module fails at import), and
`FlagRegistry` re-checks every spec at startup, so the process refuses to boot; the error names
the flag and the denied category. `restrictive` is the value while the store cannot be read
(fail closed): engaged for the order-entry kill switches, off for live trading.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Final

import structlog

#: A stored or resolved flag value: `boolean` -> bool, `percentage` -> rollout int (0-100),
#: `variant` -> one of the spec's variants.
FlagValue = bool | int | str

#: `ff_key` of `feature_flags` (21-database-schema.md 3.9) narrowed to at least two segments,
#: matching the `flagKey` path pattern of `PUT /admin/feature-flags/{flagKey}`.
_KEY_RE: Final = re.compile(r"^[a-z0-9]+(\.[a-z0-9_]+){1,3}$")


class Category(enum.Flag):
    """What a flag may gate. Members past `KILL_SWITCH` are security controls (`DENIED`)."""

    UI_SURFACE = enum.auto()
    FEATURE_ROLLOUT = enum.auto()
    OPERATIONS = enum.auto()
    LIVE_GATE = enum.auto()
    KILL_SWITCH = enum.auto()
    AUTH = enum.auto()
    RBAC = enum.auto()
    AUDIT = enum.auto()
    NATIVE_STOP_LOSS = enum.auto()
    RISK_LIMITS = enum.auto()
    WITHDRAWAL_CHECK = enum.auto()
    RATE_LIMIT_RESERVE = enum.auto()
    ENVIRONMENT_ISOLATION = enum.auto()


DENIED: Final = (
    Category.AUTH
    | Category.RBAC
    | Category.AUDIT
    | Category.NATIVE_STOP_LOSS
    | Category.RISK_LIMITS
    | Category.WITHDRAWAL_CHECK
    | Category.RATE_LIMIT_RESERVE
    | Category.ENVIRONMENT_ISOLATION
)


class FlagKind(enum.StrEnum):
    BOOLEAN = "boolean"
    PERCENTAGE = "percentage"
    VARIANT = "variant"


class Audience(enum.StrEnum):
    """Who may learn a flag's key and value (`GET`, `system` push): `owner` keys never reach a
    manager or viewer session."""

    OWNER = "owner"
    ALL = "all"


class UnsafeFlagDefinitionError(Exception):
    """A flag definition is refused; the process must not start with it."""


@dataclass(frozen=True, slots=True)
class FlagSpec:
    key: str
    kind: FlagKind
    description: str
    gates: Category
    default: FlagValue
    audience: Audience = Audience.ALL
    is_killswitch: bool = False
    #: Enabling it needs `reason` and `evidence_url` (`trading.live_enabled`, E44-T04 binds it).
    requires_evidence: bool = False
    variants: tuple[str, ...] = ()
    #: The value while the store cannot be read; `None` means `default`.
    restrictive: FlagValue | None = None

    def __post_init__(self) -> None:
        check_spec(self)

    @property
    def fail_closed_value(self) -> FlagValue:
        return self.default if self.restrictive is None else self.restrictive

    @property
    def overridable(self) -> bool:
        """D2: the live gate and kill-switch-class flags take no per-user or per-role override,
        so neither can differ from the value the gate enforces."""
        return not (self.requires_evidence or self.is_killswitch)


def _members(categories: Category) -> list[str]:
    return [m.name.lower() for m in Category if m in categories and m.name is not None]


def check_spec(spec: FlagSpec) -> None:
    """Every rule a definition must meet; raises `UnsafeFlagDefinitionError` naming the flag."""
    denied = spec.gates & DENIED
    if denied:
        raise UnsafeFlagDefinitionError(
            f"feature flag {spec.key!r} declares gate category {', '.join(_members(denied))!r}, "
            "which no flag may gate: flags never weaken a security control (C-4.14)"
        )
    if not _KEY_RE.fullmatch(spec.key):
        raise UnsafeFlagDefinitionError(f"feature flag key {spec.key!r} is malformed")
    if not spec.gates:
        raise UnsafeFlagDefinitionError(f"feature flag {spec.key!r} declares no gate category")
    for value in (spec.default, spec.fail_closed_value):
        if not value_matches(spec, value):
            raise UnsafeFlagDefinitionError(
                f"feature flag {spec.key!r}: {value!r} is not a {spec.kind}"
            )
    if (spec.is_killswitch or spec.requires_evidence) and spec.kind is not FlagKind.BOOLEAN:
        raise UnsafeFlagDefinitionError(f"feature flag {spec.key!r} must be boolean")


def value_matches(spec: FlagSpec, value: object) -> bool:
    """Whether `value` is a valid stored value for the spec's kind (bool is not an int here)."""
    if spec.kind is FlagKind.BOOLEAN:
        return isinstance(value, bool)
    if spec.kind is FlagKind.PERCENTAGE:
        return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100
    return isinstance(value, str) and value in spec.variants


class FlagRegistry(Mapping[str, FlagSpec]):
    """The validated, immutable set of flag definitions the service resolves against."""

    def __init__(self, specs: Iterable[FlagSpec]) -> None:
        by_key: dict[str, FlagSpec] = {}
        for spec in specs:
            check_spec(spec)  # again at startup: a spec built before a rule tightened is refused
            if spec.key in by_key:
                raise UnsafeFlagDefinitionError(f"feature flag {spec.key!r} is defined twice")
            by_key[spec.key] = spec
        self._specs = by_key

    def __getitem__(self, key: str) -> FlagSpec:
        return self._specs[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._specs)

    def __len__(self) -> int:
        return len(self._specs)

    def log_startup(self) -> None:
        """Log every definition with its declared gates, so an auditor sees what flags touch."""
        structlog.get_logger(__name__).info(
            "feature_flag_registry",
            flags=[
                {
                    "key": s.key,
                    "kind": s.kind.value,
                    "gates": _members(s.gates),
                    "audience": s.audience.value,
                    "is_killswitch": s.is_killswitch,
                }
                for s in self._specs.values()
            ],
        )
