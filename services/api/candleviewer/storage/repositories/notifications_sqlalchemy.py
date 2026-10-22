"""`GET /notifications` read model (E40-T04): a UNION ALL over four append-only sources, never a
table - `alert_deliveries`, `rule_events`, `order_events` and `system_events`.

Each branch applies its own source's visibility before the merge (22-api-openapi.yaml
`listNotifications`: the union is "filtered to what the caller may see"); `NotificationScope`
carries the caller's view, already resolved from the caller's permissions and grants:

- alert: the caller's own **in-app record** (`alerts:read`) - the `in_app` delivery of each
  firing, the storm summaries and the channel-failure notices, once delivered (`sent`/`acked`).
  The notification centre (SCR-014) mirrors the in-app toasts (US-ALRT-005); every channel's row
  stays in `GET /alerts/deliveries`, the alert centre's record, so an alert whose channels omit
  `in_app` has no history here beyond its channel-failure notices. Under `unread_only` an alert
  row is unread while `status = 'sent' AND acked_at IS NULL` (the in-app half of
  `unacked_count`), so an unread alert row can be acked; rule, order and system rows have no read
  state yet (`read_at` null), so `unread_only` keeps them all;
- rule: `rule_events` of exactly the rules the caller may read (`rules:read`; `rule_ids`, from the
  rules module's one visibility predicate) - the outcomes in `RULE_EVENT_KINDS`; never `payload`;
- order: `order_events` of orders on the caller's accounts (`orders:read`; `accounts`, None for
  the Owner) - the outcomes in `ORDER_EVENT_KINDS`; `ret_code` only, never `ret_msg`
  (SR-E29-09) or `payload`;
- system: the whole stream for the Owner, and to any caller the rows addressed to them
  (`recipient_user_id`; 04 §7.2.2 row 34b), `message` only, never `details`;
- risk: no source table yet (`risk_lockouts`, E39), so a `risk` filter matches nothing.

Order rows, rule-run rows and account-scoped system rows are the process's own exchange
environment only (C-2.11, as `dms_episodes_sqlalchemy.py` reads `system_events`): an order through
its account, a rule run or a system row through the account it names (a row naming an unknown
account is left out). Alert rows are the caller's own and carry no environment: an alert's
`scope_account_id` is served as its `exchange_account_id` unfiltered.

Ordering and the keyset are `(ts, src, src_id)` descending, `src` being the branch's rank, so
rows with identical timestamps from different sources keep one total order. Each branch is
pre-limited (`ORDER BY ts DESC, id DESC LIMIT n`), so the merge never sorts a whole table, and
carries `ts <= COALESCE(:after_ts, 'infinity')`, a bound an index range can use even under a
generic plan. Static SQL with bound parameters only (Bandit B608 / Semgrep raw-SQL rule); the
event kinds are bound from the port's constants, so the SQL never repeats them.
"""

from __future__ import annotations

from typing import Any, Final

import sqlalchemy as sa

from candleviewer.storage.repositories.notifications import (
    ORDER_EVENT_KINDS,
    RULE_EVENT_KINDS,
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
    # alert: the caller's own in-app record, once delivered; read state = acked_at
    "(SELECT 'alert' AS nkind, 1 AS src, d.id AS src_id, d.queued_at AS ts, "
    "a.severity::text AS severity, d.title AS title, NULLIF(d.body, '') AS body, "
    "d.acked_at AS read_at, d.context->>'symbol' AS symbol, "
    "a.scope_account_id::text AS account_id, d.alert_id::text AS source_uuid, "
    "d.channel::text AS event, NULL::text AS code "
    "FROM alert_deliveries d JOIN alerts a ON a.id = d.alert_id "
    "WHERE CAST(:alerts AS boolean) AND d.user_id = CAST(:user AS uuid) "
    "AND d.channel = 'in_app' AND d.status IN ('sent', 'acked') "
    "AND (NOT CAST(:unread_only AS boolean) OR (d.status = 'sent' AND d.acked_at IS NULL)) "
    "AND d.queued_at <= COALESCE(CAST(:after_ts AS timestamptz), 'infinity'::timestamptz) "
    "AND (CAST(:after_ts AS timestamptz) IS NULL OR (d.queued_at, 1, d.id) < "
    "(CAST(:after_ts AS timestamptz), CAST(:after_src AS integer), CAST(:after_id AS bigint))) "
    "ORDER BY d.queued_at DESC, d.id DESC LIMIT :limit) "
    "UNION ALL "
    # rule: the outcomes of exactly the rules the caller may read, this environment's runs
    "(SELECT 'rule', 2, e.id, e.event_ts, e.severity::text, ru.name, NULL::text, "
    "NULL::timestamptz, r.scope_symbol::text, r.scope_account_id::text, r.rule_id::text, "
    "e.kind, NULL::text "
    "FROM rule_events e JOIN rule_runs r ON r.id = e.rule_run_id "
    "JOIN rules ru ON ru.id = r.rule_id "
    "WHERE CAST(:rules AS boolean) AND e.kind = ANY(CAST(:rule_kinds AS text[])) "
    "AND r.rule_id = ANY(CAST(:rule_ids AS uuid[])) "
    "AND (r.scope_account_id IS NULL OR EXISTS (SELECT 1 FROM exchange_accounts ea "
    "WHERE ea.id = r.scope_account_id AND ea.env::text = :env)) "
    "AND e.event_ts <= COALESCE(CAST(:after_ts AS timestamptz), 'infinity'::timestamptz) "
    "AND (CAST(:after_ts AS timestamptz) IS NULL OR (e.event_ts, 2, e.id) < "
    "(CAST(:after_ts AS timestamptz), CAST(:after_src AS integer), CAST(:after_id AS bigint))) "
    "ORDER BY e.event_ts DESC, e.id DESC LIMIT :limit) "
    "UNION ALL "
    # order: outcomes of orders on the caller's accounts of this environment
    "(SELECT 'order', 3, oe.id, oe.event_ts, NULL::text, NULL::text, NULL::text, "
    "NULL::timestamptz, o.symbol::text, o.exchange_account_id::text, oe.order_id::text, "
    "oe.kind::text, oe.ret_code "
    "FROM order_events oe JOIN orders o ON o.id = oe.order_id "
    "JOIN exchange_accounts ea ON ea.id = o.exchange_account_id AND ea.env::text = :env "
    "WHERE CAST(:orders AS boolean) AND oe.kind::text = ANY(CAST(:order_kinds AS text[])) "
    "AND (CAST(:all_accounts AS boolean) "
    "OR o.exchange_account_id = ANY(CAST(:accounts AS uuid[]))) "
    "AND oe.event_ts <= COALESCE(CAST(:after_ts AS timestamptz), 'infinity'::timestamptz) "
    "AND (CAST(:after_ts AS timestamptz) IS NULL OR (oe.event_ts, 3, oe.id) < "
    "(CAST(:after_ts AS timestamptz), CAST(:after_src AS integer), CAST(:after_id AS bigint))) "
    "ORDER BY oe.event_ts DESC, oe.id DESC LIMIT :limit) "
    "UNION ALL "
    # system: the Owner's alone, and a row addressed to the caller theirs too (#3085); an
    # account-scoped row only for this environment's accounts
    "(SELECT 'system', 4, se.id, se.event_ts, se.severity::text, se.message, NULL::text, "
    "NULL::timestamptz, se.symbol::text, se.exchange_account_id::text, "
    "se.correlation_id::text, se.kind, NULL::text "
    "FROM system_events se "
    "WHERE (CAST(:system AS boolean) OR (CAST(:system_addressed AS boolean) "
    "AND se.recipient_user_id = CAST(:user AS uuid))) "
    "AND (se.exchange_account_id IS NULL OR EXISTS ("
    "SELECT 1 FROM exchange_accounts ea WHERE ea.id = se.exchange_account_id "
    "AND ea.env::text = :env)) "
    "AND se.event_ts <= COALESCE(CAST(:after_ts AS timestamptz), 'infinity'::timestamptz) "
    "AND (CAST(:after_ts AS timestamptz) IS NULL OR (se.event_ts, 4, se.id) < "
    "(CAST(:after_ts AS timestamptz), CAST(:after_src AS integer), CAST(:after_id AS bigint))) "
    "ORDER BY se.event_ts DESC, se.id DESC LIMIT :limit)"
    ") u ORDER BY ts DESC, src DESC, src_id DESC LIMIT :limit"
)
#: `exchange_accounts.env` values (as `dms_episodes_sqlalchemy._ENVS`).
_ENVS: Final = frozenset({"live", "demo", "testnet"})


class SqlAlchemyNotificationRepository:
    def __init__(self, relational: SqlAlchemyRelationalRepository, *, env: str) -> None:
        if env not in _ENVS:  # a misspelt environment would match no account and hide rows
            raise ValueError(f"unknown exchange environment: {env!r}")
        self._relational, self._env = relational, env

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
            "rules": scope.rules and bool(scope.rule_ids),
            "rule_ids": sorted(scope.rule_ids),
            "rule_kinds": list(RULE_EVENT_KINDS),
            "orders": scope.orders,
            "all_accounts": scope.accounts is None,
            "accounts": sorted(scope.accounts or ()),
            "order_kinds": list(ORDER_EVENT_KINDS),
            "system": scope.system,
            "system_addressed": scope.system_addressed,
            "env": self._env,
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
