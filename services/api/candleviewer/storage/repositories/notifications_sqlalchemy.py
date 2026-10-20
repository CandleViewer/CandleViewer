"""`GET /notifications` read model (E40-T04): a UNION ALL over four append-only sources, never a
table - `alert_deliveries`, `rule_events`, `order_events` and `system_events`.

Each branch applies its own source's visibility before the merge (22-api-openapi.yaml
`listNotifications`: the union is "filtered to what the caller may see"); `NotificationScope`
carries the caller's view, already resolved from the caller's permissions and grants:

- alert: the caller's own deliveries (`alerts:read`), every channel and status;
- rule: `rule_events` of the rules the caller may read (`rules:read`; `rule_ids`, from the
  rules module's one visibility predicate; None for the Owner) - the action outcomes only, not
  the per-evaluation `condition_eval` / `action_start` / `log` rows; never `payload`;
- order: `order_events` of orders on the caller's accounts (`orders:read`; `accounts`, None for
  the Owner) - outcomes, not requests; `ret_code` only, never `ret_msg` (SR-E29-09) or `payload`;
- system: everything for the Owner; for anyone else no `auth` component row (other users'
  security events, which carry no user column) and only rows on no account or a granted one;
  `message` only, never `details`;
- risk: no source table yet (`risk_lockouts`, E39), so a `risk` filter matches nothing.

Ordering and the keyset are `(ts, src, src_id)` descending, `src` being the branch's rank, so
rows with identical timestamps from different sources keep one total order. Each branch is
pre-limited (`ORDER BY ts DESC, id DESC LIMIT n`) so the merge never sorts a whole table.
Static SQL with bound parameters only (Bandit B608 / Semgrep raw-SQL rule).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.notifications import (
    NotificationRow,
    NotificationScope,
    decode_cursor,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: One static statement (no string building, Bandit B608 / Semgrep). `:after_*` is the last row
#: of the previous page (NULL `after_ts` = the first page); each branch compares its rows as
#: `(ts, <its rank>, id)` against it, which is the outer `ORDER BY` read as a keyset.
_LIST = sa.text(
    "SELECT nkind, src, src_id, ts, severity, title, body, read_at, symbol, account_id, "
    "source_uuid, event, code FROM ("
    # alert: own deliveries; read state = acked_at
    "(SELECT 'alert' AS nkind, 1 AS src, d.id AS src_id, d.queued_at AS ts, "
    "a.severity::text AS severity, d.title AS title, NULLIF(d.body, '') AS body, "
    "d.acked_at AS read_at, d.context->>'symbol' AS symbol, "
    "a.scope_account_id::text AS account_id, d.alert_id::text AS source_uuid, "
    "d.channel::text AS event, NULL::text AS code "
    "FROM alert_deliveries d JOIN alerts a ON a.id = d.alert_id "
    "WHERE CAST(:alerts AS boolean) AND d.user_id = CAST(:user AS uuid) "
    "AND (NOT CAST(:unread_only AS boolean) OR d.acked_at IS NULL) "
    "AND (CAST(:after_ts AS timestamptz) IS NULL OR (d.queued_at, 1, d.id) < "
    "(CAST(:after_ts AS timestamptz), CAST(:after_src AS integer), CAST(:after_id AS bigint))) "
    "ORDER BY d.queued_at DESC, d.id DESC LIMIT :limit) "
    "UNION ALL "
    # rule: action outcomes of the rules the caller may read
    "(SELECT 'rule', 2, e.id, e.event_ts, e.severity::text, ru.name, NULL::text, "
    "NULL::timestamptz, r.scope_symbol::text, r.scope_account_id::text, r.rule_id::text, "
    "e.kind, NULL::text "
    "FROM rule_events e JOIN rule_runs r ON r.id = e.rule_run_id "
    "JOIN rules ru ON ru.id = r.rule_id "
    "WHERE CAST(:rules AS boolean) AND e.kind IN ('action_ok', 'action_fail', 'throttled') "
    "AND (CAST(:all_rules AS boolean) OR r.rule_id = ANY(CAST(:rule_ids AS uuid[]))) "
    "AND (CAST(:after_ts AS timestamptz) IS NULL OR (e.event_ts, 2, e.id) < "
    "(CAST(:after_ts AS timestamptz), CAST(:after_src AS integer), CAST(:after_id AS bigint))) "
    "ORDER BY e.event_ts DESC, e.id DESC LIMIT :limit) "
    "UNION ALL "
    # order: outcomes of orders on the caller's accounts
    "(SELECT 'order', 3, oe.id, oe.event_ts, NULL::text, NULL::text, NULL::text, "
    "NULL::timestamptz, o.symbol::text, o.exchange_account_id::text, oe.order_id::text, "
    "oe.kind::text, oe.ret_code "
    "FROM order_events oe JOIN orders o ON o.id = oe.order_id "
    "WHERE CAST(:orders AS boolean) AND oe.kind::text IN ('ack', 'reject', 'fill', "
    "'partial_fill', 'amend_ack', 'cancel_ack', 'expire', 'error') "
    "AND (CAST(:all_accounts AS boolean) "
    "OR o.exchange_account_id = ANY(CAST(:accounts AS uuid[]))) "
    "AND (CAST(:after_ts AS timestamptz) IS NULL OR (oe.event_ts, 3, oe.id) < "
    "(CAST(:after_ts AS timestamptz), CAST(:after_src AS integer), CAST(:after_id AS bigint))) "
    "ORDER BY oe.event_ts DESC, oe.id DESC LIMIT :limit) "
    "UNION ALL "
    # system: whole for the Owner; otherwise no auth rows and no other accounts' rows
    "(SELECT 'system', 4, se.id, se.event_ts, se.severity::text, se.message, NULL::text, "
    "NULL::timestamptz, se.symbol::text, se.exchange_account_id::text, "
    "se.correlation_id::text, se.kind, NULL::text "
    "FROM system_events se "
    "WHERE CAST(:system AS boolean) AND (CAST(:system_all AS boolean) OR "
    "(se.component <> 'auth' AND (se.exchange_account_id IS NULL "
    "OR se.exchange_account_id = ANY(CAST(:accounts AS uuid[]))))) "
    "AND (CAST(:after_ts AS timestamptz) IS NULL OR (se.event_ts, 4, se.id) < "
    "(CAST(:after_ts AS timestamptz), CAST(:after_src AS integer), CAST(:after_id AS bigint))) "
    "ORDER BY se.event_ts DESC, se.id DESC LIMIT :limit)"
    ") u ORDER BY ts DESC, src DESC, src_id DESC LIMIT :limit"
)


def _ids(values: frozenset[str] | None) -> list[str]:
    return sorted(values or ())


class SqlAlchemyNotificationRepository:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def list_page(
        self,
        scope: NotificationScope,
        *,
        unread_only: bool = False,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[NotificationRow], NotificationRow | None]:
        """Newest first: the page and, when there is more, the row the next cursor encodes."""
        after = decode_cursor(cursor) if cursor else (None, None, None)
        if scope.empty:
            return [], None
        params: dict[str, Any] = {
            "user": scope.user_id,
            "alerts": scope.alerts,
            "rules": scope.rules,
            "all_rules": scope.rule_ids is None,
            "rule_ids": _ids(scope.rule_ids),
            "orders": scope.orders,
            "all_accounts": scope.accounts is None,
            "accounts": _ids(scope.accounts),
            "system": scope.system,
            "system_all": scope.system_all,
            "unread_only": unread_only,
            "after_ts": after[0],
            "after_src": after[1],
            "after_id": after[2],
            "limit": limit + 1,
        }
        async with self._relational.unit_of_work() as uow:
            got = (await uow.session.execute(_LIST, params)).mappings().all()
        rows = [NotificationRow(**dict(m)) for m in got]
        more = len(rows) > limit
        rows = rows[:limit]
        return rows, (rows[-1] if more and rows else None)


__all__ = ["SqlAlchemyNotificationRepository"]
