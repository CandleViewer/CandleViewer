"""E29-T04 (#913, slice 3): the OMS's principal-free account read, which no route may reach.

`TradingAccountReads` reads any account and its active key's id with no scope check (C-12.4): only
`oms_wiring.TradingAccountsBinding` may bind it, the OMS's `TradingAccounts` port, which the order
route asks only after its RBAC check (24 Sec.8.4 steps 2 and 4). Each consumer PR adds its file to
`ALLOWED` and is reviewed as an RBAC bypass first (the `test_order_submission_store_callers.py`
precedent).

The pattern names the types, the statement and the protocol method's call (`.read_account(`), so
an instance handed on by injection is fenced too. It is a tripwire, not a boundary: it stops an
honest regression, not a re-export under another name inside an allowed file, a `getattr` on a
built string, or a call through a name it does not know. The control is the review of each
`ALLOWED` change (C-12.4), as the sibling fences say of themselves (SEC-S3C1B-01).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import candleviewer

PKG = Path(candleviewer.__file__).resolve().parent
ACCOUNT_READ = re.compile(
    r"(?<!\w)(TradingAccountReads|SqlAlchemyTradingAccountReads|InMemoryTradingAccountReads"
    r"|TRADING_ACCOUNT_SQL)\b"
    r"|\.read_account\("  # the protocol method, called on any instance handed on
)
ALLOWED = {
    ACCOUNT_READ: frozenset(
        {
            "oms_wiring.py",
            "storage/repositories/trading_accounts.py",
            "storage/repositories/trading_accounts_sqlalchemy.py",
        }
    ),
}


@pytest.mark.parametrize("names", list(ALLOWED), ids=["account_read"])
def test_each_principal_free_oms_read_is_named_only_where_it_was_reviewed(
    names: re.Pattern[str],
) -> None:
    users = {
        p.relative_to(PKG).as_posix()
        for p in PKG.rglob("*.py")
        if names.search(p.read_text(encoding="utf-8"))
    }
    assert users == ALLOWED[names]


def test_the_patterns_match_the_names_and_not_their_longer_neighbours() -> None:
    assert ACCOUNT_READ.search("reads: TradingAccountReads")
    assert not ACCOUNT_READ.search("accounts: TradingAccounts")  # the OMS port it implements


def test_the_pattern_matches_a_call_of_the_protocol_method_and_not_its_definition() -> None:
    """The call on an instance handed on by injection is fenced, under whatever name it holds."""
    assert ACCOUNT_READ.search("row = await deps.reads.read_account(account_id)")
    assert ACCOUNT_READ.search("await reader.read_account(\n    account_id\n)")
    assert not ACCOUNT_READ.search("async def read_account(self, account_id: UUID)")
    assert not ACCOUNT_READ.search("reads.read_accounts(environment)")  # a longer name
