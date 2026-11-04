"""GENERATED FILE - DO NOT EDIT BY HAND.

Generator: packages/protocol/scripts/generate-notification-overrides.mjs (E40-S02, #1130).
Source: packages/protocol/notification-overrides.json (E40-D01 section 5, E40-D02 section 6.2).
Run `pnpm --filter @candleviewer/protocol generate`.
"""

from __future__ import annotations

from typing import Final, NamedTuple


class Override(NamedTuple):
    id: str
    label: str
    category: str
    toast: str
    audience: str


VERSION: Final = 1
STATUS: Final = "PROPOSED"
USER_ALERTS_OVERRIDE: Final = False
CATEGORIES: Final[tuple[str, ...]] = ("alerts", "rule_actions", "order_rejects", "risk_events", "system_health", "recorder")
CHANNELS: Final[tuple[str, ...]] = ("toast", "centre", "desktop", "sound")
LOCKED_CELLS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("order_rejects", "toast"),
        ("risk_events", "toast"),
    }
)
OVERRIDES: Final[tuple[Override, ...]] = (
    Override("CO-1", "Daily-loss lockout", "risk_events", "banner", "every_role"),
    Override("CO-2", "Liquidation proximity", "risk_events", "banner", "every_role"),
    Override("CO-3", "Connection lost with open positions", "system_health", "banner", "every_role"),
    Override("CO-4", "Kill switch engaged", "risk_events", "banner", "every_role"),
    Override("CO-5", "Trade group incomplete", "order_rejects", "toast", "every_role"),
    Override("CO-6", "Position without an exchange stop", "risk_events", "banner", "every_role"),
    Override("CO-7", "API key self-check failed", "system_health", "toast", "owner"),
    Override("CO-8", "Recorder not writing", "recorder", "toast", "owner"),
    Override("CO-9", "Disk threshold", "recorder", "toast", "owner"),
    Override("CO-10", "Rate limit used up", "system_health", "toast", "owner"),
    Override("CO-11", "Reconciliation mismatch", "system_health", "toast", "owner"),
    Override("CO-12", "Rule engine errors", "system_health", "banner", "owner"),
)
OVERRIDE_CHANNELS: Final[tuple[str, ...]] = ("toast", "desktop", "sound")
OVERRIDE_TONE: Final = "critical"
