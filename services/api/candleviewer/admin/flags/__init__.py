"""Feature-flag service of the admin module (E42-T03): the code-only registry with its
security-control allowlist."""

from __future__ import annotations

from candleviewer.admin.flags.registry import (
    DENIED,
    Audience,
    Category,
    FlagKind,
    FlagRegistry,
    FlagSpec,
    FlagValue,
    UnsafeFlagDefinitionError,
    value_matches,
)

__all__ = [
    "DENIED",
    "Audience",
    "Category",
    "FlagKind",
    "FlagRegistry",
    "FlagSpec",
    "FlagValue",
    "UnsafeFlagDefinitionError",
    "value_matches",
]
