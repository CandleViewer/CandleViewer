"""Admin read-model slice names (E42-T01): the one place a slice is named.

Typed so a name can never drift into an unbounded metric label: `source` on
`cv_admin_overview_source_*` is bounded by this enum. Extensible: E42-T05 adds health,
incidents and backups slices here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class AdminSlice(StrEnum):
    USERS = "users"
    ACCOUNTS = "accounts"
    RECORDER = "recorder"
    STORAGE = "storage"
    TRADING = "trading"
    INCIDENTS = "incidents"
    CAPACITY_STORAGE = "capacity_storage"
    INGESTION = "ingestion"
    RATE_BUDGET = "rate_budget"
    SUBACCOUNTS = "subaccounts"
    STATECHART_SNAPSHOTS = "statechart_snapshots"
    STATECHART_METRICS = "statechart_metrics"


#: `GET /admin/overview` slices and `GET /admin/capacity` sections: disjoint cache keys.
#: Explicit membership: a slice added to the enum must be placed in a set on purpose.
OVERVIEW_SLICES: Final = frozenset(
    {
        AdminSlice.USERS,
        AdminSlice.ACCOUNTS,
        AdminSlice.RECORDER,
        AdminSlice.STORAGE,
        AdminSlice.TRADING,
        AdminSlice.INCIDENTS,
    }
)
CAPACITY_SLICES: Final = frozenset(
    {
        AdminSlice.CAPACITY_STORAGE,
        AdminSlice.INGESTION,
        AdminSlice.RATE_BUDGET,
        AdminSlice.SUBACCOUNTS,
    }
)
#: The statechart inspector's sources (E42-T07).
INSPECTOR_SLICES: Final = frozenset(
    {AdminSlice.STATECHART_SNAPSHOTS, AdminSlice.STATECHART_METRICS}
)
