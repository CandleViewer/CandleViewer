"""Postgres read of the account an order is signed for (E29-T04 #913 slice 3; `trading_accounts`).

Static SQL text, as every reader of `api_keys` outside `db/models.py` is
(`test_write_once_surface.py`), under the OMS stores' statement cap and error mapping
(`CappedStore`): a failure leaves as a `StorageError`, never with the driver's text.
`ux_api_keys_active` admits at most one active, unrevoked key; no key column is read (C-2.7).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

import sqlalchemy as sa

from candleviewer.storage.repositories.orders_sqlalchemy import CappedStore
from candleviewer.storage.repositories.trading_accounts import TradingAccountRow

TRADING_ACCOUNT_SQL: Final = sa.text(
    "SELECT ea.id, ea.env::text AS env, ea.exchange_uid, ea.deleted_at IS NOT NULL AS deleted, "
    "(SELECT k.id FROM api_keys k WHERE k.exchange_account_id = ea.id AND k.status = 'active' "
    "AND k.revoked_at IS NULL) AS active_key_id "
    "FROM exchange_accounts ea WHERE ea.id = CAST(:id AS uuid)"
)


class SqlAlchemyTradingAccountReads(CappedStore):
    async def read_account(self, account_id: UUID) -> TradingAccountRow | None:
        async with self._unit_of_work() as uow:
            found = await uow.session.execute(TRADING_ACCOUNT_SQL, {"id": str(account_id)})
            row = found.mappings().first()
        if row is None:
            return None
        key = row["active_key_id"]
        return TradingAccountRow(
            account_id=UUID(str(row["id"])),
            environment=row["env"],
            exchange_uid=str(row["exchange_uid"]),
            deleted=bool(row["deleted"]),
            active_key_id=None if key is None else UUID(str(key)),
        )
