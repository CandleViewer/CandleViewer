"""The feature-flag definitions (E42-T03): exactly `21-database-schema.md` 10.7, each with the
visibility its Visibility column gives. Adding a flag is a code change reviewed against the
allowlist in `registry.py`; `engine.fallback_lightweight_charts` from 10.7 is left out because a
third-party production chart library is out of scope (C-1.2)."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from candleviewer.admin.flags.registry import LIVE_ENABLED as LIVE_ENABLED
from candleviewer.admin.flags.registry import MAINTENANCE_MODE as MAINTENANCE_MODE
from candleviewer.admin.flags.registry import (
    Category,
    FlagKind,
    FlagRegistry,
    FlagSpec,
    FlagValue,
    Visibility,
)

_B = FlagKind.BOOLEAN
_UI, _ROLLOUT = Category.UI_SURFACE, Category.FEATURE_ROLLOUT
_OPS, _KILL = Category.OPERATIONS, Category.KILL_SWITCH
_ALL, _OWNER = Visibility.ALL_ROLES, Visibility.OWNER_ONLY

MAINTENANCE_KEEP_RECORDER = "maintenance.keep_recorder"
#: ADR-0038 2e: the composition root reads it with no principal for the CORS layer and the guard.
DESKTOP_BACKEND_CONNECTION = "desktop.backend_connection"
#: #913 slice 3 ruling Q3: new `placeOrder` admissions; the composition root reads it with no
#: principal (`flags_wiring.FlagView`).
TRADING_OMS_ENABLED = "trading.oms_enabled"
#: E28-T05 (#909): the definition writes and the preview, never a read; read as the OMS flag is.
#: Seeded on in demo (`ENVIRONMENT_SEEDS`) with the preview's audited refusals (S3c, ruling 6).
TRADING_TRADE_GROUPS = "trading.trade_groups"
#: E35-T10 (#5002; 24 Sec.16.2): the permanent master switch of rule actions, kill-switch class,
#: engaged at `false` (the value that is not its default), which is also its fail-closed value.
RULES_ENABLED = "rules.enabled"
#: Ruling Q3: the value the insert-only `ensure` gives a flag with no row in a process of an
#: environment, where it is not the flag's default (21 10.7), so an Owner's later write sticks.
#: Never a kill switch or the live gate (C-4.14): `flags_wiring._seeds` ignores such a seed, and
#: `test_flag_catalogue.py` holds the table. Read-only at both levels, so nothing edits it at
#: run time.
ENVIRONMENT_SEEDS: Final[Mapping[str, Mapping[str, FlagValue]]] = MappingProxyType(
    {
        TRADING_OMS_ENABLED: MappingProxyType({"demo": True}),
        TRADING_TRADE_GROUPS: MappingProxyType({"demo": True}),
    }
)

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
    FlagSpec(
        TRADING_OMS_ENABLED,
        _B,
        "New OMS order admissions (placeOrder); owner @basiltt, removal #4227",
        _ROLLOUT,
        False,
        _ALL,
        restrictive=False,
    ),
    FlagSpec(
        TRADING_TRADE_GROUPS,
        _B,
        "Trade-group definition writes and the preview; owner @basiltt, removal #4798",
        _ROLLOUT,
        False,
        _ALL,
        restrictive=False,
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
        RULES_ENABLED,
        _B,
        "Master switch of rule actions; off while unread.",
        _KILL,
        True,
        _ALL,
        is_killswitch=True,
        restrictive=False,
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
        DESKTOP_BACKEND_CONNECTION,
        _B,
        "CORS answers, the CSRF token response header and the desktop cookie attributes for the "
        "SR-042 allow-list (ADR-0038); owner @basiltt, removal #3931",
        _ROLLOUT,
        False,
        _OWNER,
        restrictive=False,
    ),
)


def default_registry() -> FlagRegistry:
    """Built by the service at startup; raises `UnsafeFlagDefinitionError` on a bad definition."""
    return FlagRegistry(FLAGS)
