"""The feature-flag definitions (E42-T03): exactly `21-database-schema.md` 10.7, each with the
visibility its Visibility column gives. Adding a flag is a code change reviewed against the
allowlist in `registry.py`; `engine.fallback_lightweight_charts` from 10.7 is left out because a
third-party production chart library is out of scope (C-1.2)."""

from __future__ import annotations

from candleviewer.admin.flags.registry import LIVE_ENABLED as LIVE_ENABLED
from candleviewer.admin.flags.registry import MAINTENANCE_MODE as MAINTENANCE_MODE
from candleviewer.admin.flags.registry import (
    Category,
    FlagKind,
    FlagRegistry,
    FlagSpec,
    Visibility,
)

_B = FlagKind.BOOLEAN
_UI, _ROLLOUT = Category.UI_SURFACE, Category.FEATURE_ROLLOUT
_OPS, _KILL = Category.OPERATIONS, Category.KILL_SWITCH
_ALL, _OWNER = Visibility.ALL_ROLES, Visibility.OWNER_ONLY

MAINTENANCE_KEEP_RECORDER = "maintenance.keep_recorder"
#: ADR-0037 decision 12: the composition root reads it for `AuditService` with no principal.
AUDIT_LANE_JOURNAL_FIRST = "audit.lane_journal_first"

FLAGS: tuple[FlagSpec, ...] = (
    FlagSpec(
        LIVE_ENABLED,
        _B,
        "Master switch for live-environment order entry; stays off until the pen-test passes.",
        Category.LIVE_GATE,
        False,
        _ALL,
        requires_evidence=True,
        restrictive=False,
    ),
    FlagSpec(
        "trading.one_click", _B, "One-click trading; requires an explicit arm.", _UI, False, _ALL
    ),
    FlagSpec("engine.webgl_v2", _B, "Custom WebGL engine rollout.", _ROLLOUT, False, _ALL),
    FlagSpec("rules.graph_editor", _B, "Node-graph rule editor surface.", _UI, True, _ALL),
    FlagSpec("rules.form_editor", _B, "Form rule editor surface.", _UI, True, _ALL),
    *(
        FlagSpec(
            f"algo.{name}", _B, f"Emulated {name} algo, enabled per release.", _ROLLOUT, False, _ALL
        )
        for name in ("twap", "chase", "iceberg", "scaled", "oco")
    ),
    FlagSpec("recorder.auto_record", _B, "Chart and position auto-record.", _OPS, True, _OWNER),
    FlagSpec("storage.cold_tier", _B, "Parquet/DuckDB routing.", _OPS, True, _OWNER),
    FlagSpec(
        "killswitch.ingestion",
        _B,
        "Stops market-data ingestion.",
        _KILL,
        False,
        _OWNER,
        is_killswitch=True,
    ),
    FlagSpec(
        "killswitch.order_entry",
        _B,
        "Refuses order acceptance.",
        _KILL,
        False,
        _ALL,
        is_killswitch=True,
        restrictive=True,
    ),
    FlagSpec(
        MAINTENANCE_MODE,
        _B,
        "Maintenance mode: refuses order acceptance, cancels emulated algos, never touches "
        "native exchange stops.",
        _KILL,
        False,
        _ALL,
        is_killswitch=True,
        restrictive=True,
    ),
    FlagSpec(
        MAINTENANCE_KEEP_RECORDER,
        _B,
        "The recorder keeps running while maintenance mode is on.",
        _OPS,
        True,
        _OWNER,
    ),
    FlagSpec(
        AUDIT_LANE_JOURNAL_FIRST,
        _B,
        "Lane audit records go to the journal-first audit lane before the sink (ADR-0037); "
        "owner @basiltt, removal #3009",
        _ROLLOUT,
        False,
        _OWNER,
        restrictive=False,
    ),
)


def default_registry() -> FlagRegistry:
    """Built by the service at startup; raises `UnsafeFlagDefinitionError` on a bad definition."""
    return FlagRegistry(FLAGS)
