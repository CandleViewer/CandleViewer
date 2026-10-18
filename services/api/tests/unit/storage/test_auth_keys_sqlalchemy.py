"""`SqlAlchemyAuthKeyStore`'s statements (#2152 S2). The SQL itself, the all-or-none insert, the
guards and the compare-and-set run on Postgres in
`tests/integration/storage/test_auth_keys_pg.py` (CI lane)."""

from __future__ import annotations

import re

import sqlalchemy as sa

from candleviewer.storage.repositories import auth_keys_sqlalchemy as m

# Self-discovering: a statement added later cannot dodge the scope guard.
_STATEMENTS = {n: v for n, v in vars(m).items() if isinstance(v, sa.TextClause)}


def test_statements_name_their_columns_and_never_delete() -> None:
    assert set(_STATEMENTS) == {"_ROWS", "_INSERT", "_REWRAP", "_COUNT", "_MFA_MATERIAL"}
    for name, stmt in _STATEMENTS.items():
        text = str(stmt)
        # 21 Sec.12 forbids `SELECT *` on auth_keys; for this module this test is the guard.
        assert not re.search(r"(?i)select\s+(distinct\s+)?\*|\w\.\*", text), name
        assert "DELETE" not in text.upper() and "TRUNCATE" not in text.upper(), name  # 0030
