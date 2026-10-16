"""Feature-flag service of the admin module (E42-T03): the code-only registry with its
security-control allowlist, the flag definitions, the pure resolver and the cached read path."""

from __future__ import annotations

from candleviewer.admin.flags.catalogue import (
    FLAGS,
    LIVE_ENABLED,
    MAINTENANCE_KEEP_RECORDER,
    MAINTENANCE_MODE,
    default_registry,
)
from candleviewer.admin.flags.registry import (
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
from candleviewer.admin.flags.resolver import StoredFlag, resolve, rollout_bucket
from candleviewer.admin.flags.service import FlagList, FlagService, Resolution, ResolvedFlag
from candleviewer.admin.flags.store import FlagStore, StoreUnavailableError

__all__ = [
    "DENIED",
    "FLAGS",
    "LIVE_ENABLED",
    "MAINTENANCE_KEEP_RECORDER",
    "MAINTENANCE_MODE",
    "Category",
    "FlagKind",
    "FlagList",
    "FlagRegistry",
    "FlagService",
    "FlagSpec",
    "FlagStore",
    "FlagValue",
    "Resolution",
    "ResolvedFlag",
    "StoreUnavailableError",
    "StoredFlag",
    "UnsafeFlagDefinitionError",
    "Visibility",
    "default_registry",
    "resolve",
    "rollout_bucket",
    "value_matches",
]
