"""The feature-flag definitions (E42-T03): `21-database-schema.md` 10.7 plus the contract's
examples. Adding a flag is a code change reviewed against the allowlist in `registry.py`;
`engine.fallback_lightweight_charts` from 10.7 is left out because a third-party production
chart library is out of scope (C-1.2)."""

from __future__ import annotations

from candleviewer.admin.flags.registry import (
    Audience,
    Category,
    FlagKind,
    FlagRegistry,
    FlagSpec,
)

_B = FlagKind.BOOLEAN
_UI, _ROLLOUT = Category.UI_SURFACE, Category.FEATURE_ROLLOUT
_OPS, _KILL = Category.OPERATIONS, Category.KILL_SWITCH

LIVE_ENABLED = "trading.live_enabled"
MAINTENANCE_MODE = "maintenance.mode"
MAINTENANCE_KEEP_RECORDER = "maintenance.keep_recorder"

FLAGS: tuple[FlagSpec, ...] = (
    FlagSpec(
        LIVE_ENABLED,
        _B,
        "Master switch for live-environment order entry; stays off until the pen-test passes.",
        Category.LIVE_GATE,
        default=False,
        requires_evidence=True,
        restrictive=False,
    ),
    FlagSpec("trading.one_click", _B, "One-click trading; requires an explicit arm.", _UI, False),
    FlagSpec("engine.webgl_v2", _B, "Custom WebGL engine rollout.", _ROLLOUT, False),
    FlagSpec(
        "engine.heatmap_renderer",
        FlagKind.VARIANT,
        "WebGL heatmap renderer implementation.",
        _ROLLOUT,
        "texture_v1",
        variants=("texture_v1", "texture_v2"),
    ),
    FlagSpec("rules.graph_editor", _B, "Node-graph rule editor surface.", _UI, True),
    FlagSpec("rules.form_editor", _B, "Form rule editor surface.", _UI, True),
    *(
        FlagSpec(f"algo.{name}", _B, f"Emulated {name} algo, enabled per release.", _ROLLOUT, False)
        for name in ("twap", "chase", "iceberg", "scaled", "oco")
    ),
    FlagSpec(
        "recorder.auto_record",
        _B,
        "Chart and position auto-record.",
        _OPS,
        True,
        audience=Audience.OWNER,
    ),
    FlagSpec(
        "storage.cold_tier", _B, "Parquet/DuckDB routing.", _OPS, True, audience=Audience.OWNER
    ),
    FlagSpec(
        "killswitch.ingestion", _B, "Stops market-data ingestion.", _KILL, False, is_killswitch=True
    ),
    FlagSpec(
        "killswitch.order_entry",
        _B,
        "Refuses order acceptance.",
        _KILL,
        False,
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
        is_killswitch=True,
        restrictive=True,
    ),
    FlagSpec(
        MAINTENANCE_KEEP_RECORDER,
        _B,
        "The recorder keeps running while maintenance mode is on.",
        _OPS,
        True,
        audience=Audience.OWNER,
    ),
)


def default_registry() -> FlagRegistry:
    """Built by the service at startup; raises `UnsafeFlagDefinitionError` on a bad definition."""
    return FlagRegistry(FLAGS)
