"""Feature-flag service of the admin module (E42-T03): the code-only registry with its
security-control allowlist, the flag definitions, the pure resolver, the cached read path and
the write path (`FlagWriter`, its evidence rules and its store and user-directory ports).
The `MaintenanceGate` and the order-entry refusal counter, which the API-edge order-entry gate
uses, are exported here too."""

from __future__ import annotations

from candleviewer.admin.flags.catalogue import (
    FLAGS,
    LIVE_ENABLED,
    MAINTENANCE_KEEP_RECORDER,
    MAINTENANCE_MODE,
    default_registry,
)
from candleviewer.admin.flags.maintenance import (
    AlgoCanceller,
    MaintenanceController,
    MaintenanceGate,
    RecorderControl,
    chain_hooks,
)
from candleviewer.admin.flags.metrics import order_entry_refusals_total
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
from candleviewer.admin.flags.store import (
    FlagStore,
    FlagWrite,
    Prepare,
    StaleWriteError,
    StoreUnavailableError,
    UserDirectory,
)
from candleviewer.admin.flags.writes import (
    FlagConflictError,
    FlagsWriteDenied,
    FlagValidationError,
    FlagWriter,
    UnknownFlagError,
)

__all__ = [
    "DENIED",
    "FLAGS",
    "LIVE_ENABLED",
    "MAINTENANCE_KEEP_RECORDER",
    "MAINTENANCE_MODE",
    "AlgoCanceller",
    "Category",
    "FlagConflictError",
    "FlagKind",
    "FlagList",
    "FlagRegistry",
    "FlagService",
    "FlagSpec",
    "FlagStore",
    "FlagValidationError",
    "FlagValue",
    "FlagWrite",
    "FlagWriter",
    "FlagsWriteDenied",
    "MaintenanceController",
    "MaintenanceGate",
    "Prepare",
    "RecorderControl",
    "Resolution",
    "ResolvedFlag",
    "StaleWriteError",
    "StoreUnavailableError",
    "StoredFlag",
    "UnknownFlagError",
    "UnsafeFlagDefinitionError",
    "UserDirectory",
    "Visibility",
    "chain_hooks",
    "default_registry",
    "order_entry_refusals_total",
    "resolve",
    "rollout_bucket",
    "value_matches",
]
