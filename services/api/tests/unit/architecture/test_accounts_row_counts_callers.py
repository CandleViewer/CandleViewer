"""#2314: the M13 row-gauge aggregates take no principal scope, so no route may reach them.

`count_accounts_by_kind` / `count_api_keys_by_status` return counts for the process environment
only (no rows, no ids). They are system telemetry: `accounts.service.AccountsService` is the one
caller, and the M10 port and its Postgres adapter are the only definitions. A reference anywhere
else in `candleviewer` (an `api/` router, the `AccountsRepository` facade, a WS topic) fails here
and must be reviewed as an RBAC bypass first (C-12.4, SR-051).
"""

from __future__ import annotations

from pathlib import Path

import candleviewer

PKG = Path(candleviewer.__file__).resolve().parent
NAMES = ("count_accounts_by_kind", "count_api_keys_by_status")
ALLOWED = frozenset(
    {
        "accounts/service.py",
        "storage/repositories/accounts.py",
        "storage/repositories/accounts_sqlalchemy.py",
    }
)


def test_row_count_reads_are_referenced_only_by_the_gauge_loop_and_the_store() -> None:
    users = {
        p.relative_to(PKG).as_posix()
        for p in PKG.rglob("*.py")
        if any(name in p.read_text(encoding="utf-8") for name in NAMES)
    }
    assert users == ALLOWED
