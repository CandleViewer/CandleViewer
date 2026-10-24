"""`SqlAlchemyRetentionPolicies` (E16-T08, #492): the `retention_policies` set the policy routes
read and replace. A replace deletes every row and inserts the new set in ONE transaction, so a row
the table refuses leaves the old set (the reaper and the roll-off read the enabled rows). The list
shows enabled rows only, while a replace deletes every row: a disabled row (none is written today)
goes with it unlisted, and the replaced rows start with no `last_run_at` or deleted-row count (no
code writes them today). Static, parameterised SQL; M10 returns rows, the route maps them."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_LIST: Final = sa.text(
    "SELECT id::text AS id, scope, symbol::text AS symbol, stream::text AS stream, retain_days, "
    "action::text AS action, updated_at FROM retention_policies WHERE enabled "
    "ORDER BY scope, symbol::text NULLS FIRST, stream::text"
)
_CLEAR: Final = sa.text("DELETE FROM retention_policies")
_INSERT: Final = sa.text(
    "INSERT INTO retention_policies (id, scope, symbol, stream, retain_days, action, created_by) "
    "VALUES (gen_random_uuid(), CASE WHEN CAST(:symbol AS text) IS NULL THEN 'default' "
    "ELSE 'symbol' END, CAST(:symbol AS text), CAST(:stream AS stream_kind), :retain_days, "
    "CAST(:action AS retention_action), CAST(:actor AS uuid))"
)


class SqlAlchemyRetentionPolicies:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def list_policies(self) -> list[dict[str, Any]]:
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_LIST)).mappings().all()
            await uow.commit()
        return [dict(r) for r in rows]

    async def replace(
        self, rows: Sequence[Mapping[str, Any]], *, actor: str | None
    ) -> list[dict[str, Any]]:
        """Replace the whole set with `rows` (`symbol`, `stream`, `retain_days`, `action`; a
        `None` symbol is the global row), created by `actor`; the stored set after it."""
        params = [{"symbol": r["symbol"], "stream": r["stream"], "retain_days": r["retain_days"],
                   "action": r["action"], "actor": actor} for r in rows]  # fmt: skip
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_CLEAR)
            if params:
                await uow.session.execute(_INSERT, params)
            stored = (await uow.session.execute(_LIST)).mappings().all()
            await uow.commit()
        return [dict(r) for r in stored]
