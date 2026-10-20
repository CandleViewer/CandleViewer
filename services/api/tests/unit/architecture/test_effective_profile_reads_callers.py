"""SEC-1B-04: the order path's profile read takes no principal, so no route may reach it.

`EffectiveProfileReads.effective_profile` (and its statement, `effective_statement`) answer a
profile for an account with no scope check: a system read for the sizer, the guard and the
fan-out (24-internal-schemas.md Sec.9.3). `accounts.profile_cache` is its one caller, and the M10
port and its Postgres adapter are its only definitions; consumers read through the cache's
`get_effective_profile`. A reference anywhere else in `candleviewer` (an `api/` router, a WS
topic, the facade) fails here and must be reviewed as an RBAC bypass first (C-12.4, SR-051; the
#2314 precedent in test_accounts_row_counts_callers.py).
"""

from __future__ import annotations

import re
from pathlib import Path

import candleviewer

PKG = Path(candleviewer.__file__).resolve().parent
# `get_effective_profile`, the cache's own entry point, is not the store's system read.
NAMES = re.compile(r"(?<!\w)(effective_profile|EffectiveProfileReads|effective_statement)\b")
ALLOWED = frozenset(
    {
        "accounts/profile_cache.py",
        "storage/repositories/account_profiles.py",
        "storage/repositories/account_profiles_sqlalchemy.py",
    }
)


def test_the_principal_free_profile_read_is_referenced_only_by_the_cache_and_the_store() -> None:
    users = {
        p.relative_to(PKG).as_posix()
        for p in PKG.rglob("*.py")
        if NAMES.search(p.read_text(encoding="utf-8"))
    }
    assert users == ALLOWED
