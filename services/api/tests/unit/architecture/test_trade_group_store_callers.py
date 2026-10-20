"""E28-T01 (#905): the trade-group system store takes no principal, so no route may reach it.

`TradeGroupStore` (and its Postgres adapter `SqlAlchemyTradeGroupStore`) writes and reads any
group, leg and profile snapshot with no scope check: the OMS, the lifecycle and the safety
monitor call it through the M13 facade `TradeGroupRepository` after their own admission
(SR-E28-27). The scoped read is `TradeGroupReads.get_group`, through `TradeGroupReader`, whose
scope is in the SQL (SR-051, SR-E28-21). A reference to the system surface anywhere else in
`candleviewer` (an `api/` router, a WS topic, a job) fails here; each consumer PR (E29-T04,
E34-S02, E34-T01, E32-T01, E32-T02, E41-T02) adds its file to `ALLOWED` and is reviewed as an
RBAC bypass first (C-12.4; the #2314 precedent in test_accounts_row_counts_callers.py).
"""

from __future__ import annotations

import re
from pathlib import Path

import candleviewer

PKG = Path(candleviewer.__file__).resolve().parent
#: The system port, its adapter, the system facade and the port's system methods.
NAMES = re.compile(
    r"(?<!\w)(TradeGroupStore|SqlAlchemyTradeGroupStore|TradeGroupRepository|find_anchor"
    r"|create_group|load_group|load_leg|list_open_groups|list_unprotected_legs)\b"
)
ALLOWED = frozenset(
    {
        "storage/repositories/trade_groups.py",
        "storage/repositories/trade_groups_sqlalchemy.py",
        "accounts/trade_group_repository.py",
    }
)


def test_the_system_trade_group_store_is_referenced_only_by_the_store_and_its_facade() -> None:
    users = {
        p.relative_to(PKG).as_posix()
        for p in PKG.rglob("*.py")
        if NAMES.search(p.read_text(encoding="utf-8"))
    }
    assert users == ALLOWED


def test_the_pattern_matches_the_names_and_not_their_longer_neighbours() -> None:
    assert NAMES.search("store: TradeGroupStore") and NAMES.search("await s.load_leg(leg_id)")
    assert not NAMES.search("except TradeGroupStoreError:")  # the error names are not the port
    assert not NAMES.search("TradeGroupReader(store)") and not NAMES.search("reload_leg()")
