"""Postgres read of the runtime role's guarded privileges (#3998, `storage.guarded_privileges`).

One literal statement with bound parameters only: the pinned pairs go in as two parallel text
arrays and come back one row each. Each table is looked up by name in schema `public`
(`pg_class` joined to `pg_namespace`), never through the session's `search_path`, so a table the
path hides is still checked and one missing from `public` is `present = false`, its pair not
checked. `has_table_privilege(current_user, ...)` says whether the role the app logs in as holds a
pair; `via_owner` is `pg_has_role(current_user, <the table's owner>, 'USAGE')`: the role owns the
table or has its owner's privileges, as a superuser has every role's.
"""

from __future__ import annotations

from typing import Final

import sqlalchemy as sa

from candleviewer.storage.guarded_privileges import (
    GUARDED_PAIRS,
    GUARDED_PRIVILEGES,
    HeldPrivilege,
    PrivilegeReport,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_HELD: Final = sa.text(
    "SELECT g.tbl AS table_name, g.priv AS privilege, c.oid IS NOT NULL AS present, "
    "c.oid IS NOT NULL AND has_table_privilege(current_user, c.oid, g.priv) AS held, "
    "c.oid IS NOT NULL AND pg_has_role(current_user, c.relowner, 'USAGE') AS via_owner, "
    "(SELECT r.rolsuper FROM pg_roles r WHERE r.rolname = current_user) AS superuser "
    "FROM unnest(CAST(:tables AS text[]), CAST(:privileges AS text[])) AS g(tbl, priv) "
    "LEFT JOIN pg_namespace n ON n.nspname = 'public' "
    "LEFT JOIN pg_class c ON c.relnamespace = n.oid AND c.relname = CAST(g.tbl AS name) "
    "ORDER BY g.tbl, g.priv"
)


class SqlAlchemyGuardedPrivileges:
    """Reads, on `relational`'s connection, which pinned pairs its login holds."""

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def held(self) -> PrivilegeReport:
        """The pinned pairs the role holds, ordered by table and privilege for the log line, and
        the pinned tables not in `public`: one with no row counts as missing (fail closed)."""
        params = {
            "tables": [table for table, _ in GUARDED_PAIRS],
            "privileges": [privilege for _, privilege in GUARDED_PAIRS],
        }
        async with self._relational.unit_of_work() as uow:  # a read: nothing to commit
            rows = (await uow.session.execute(_HELD, params)).mappings().all()
        present = {str(row["table_name"]) for row in rows if row["present"]}
        return PrivilegeReport(
            superuser=any(bool(row["superuser"]) for row in rows),
            held=tuple(
                HeldPrivilege(str(row["table_name"]), str(row["privilege"]), bool(row["via_owner"]))
                for row in rows
                if row["held"]
            ),
            missing=tuple(sorted(GUARDED_PRIVILEGES.keys() - present)),
        )
