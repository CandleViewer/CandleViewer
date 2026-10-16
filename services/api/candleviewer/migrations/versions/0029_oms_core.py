"""orders, order_events, executions, positions, position_snapshots (E29-T01 #845)

Revision ID: 0029_oms_core
Revises: 0028_incidents_backups
Create Date: 2026-10-16

Purely additive (C-5.1). The tables are `docs/plan/21-database-schema.md` Sec.3.3.4-3.3.7 verbatim
and `order_intent`, `order_state`, `order_event_kind` are Sec.1.2 verbatim; no earlier revision
created them. `symbol_code` (0004), `forbid_mutation()` and `audit_refuse_truncate()` (0003) and
`exchange_accounts` (0017) already exist. Recorded in Sec.3.3.4 to Sec.3.3.6:

* `orders.take_profit`, `orders.stop_loss` and `orders.tpsl_mode` are new in Sec.3.3.4 with this
  revision: the TP/SL attached on create (24-internal-schemas.md Sec.8.1 `Order`, Sec.8.8 rule 1),
  so an order row carries its native stop from the first insert (C-2.6; the main-orchestrator
  ruling recorded on #845, issuecomment-6220571436). `ord_tp_px` and `ord_sl_px` refuse a price of
  0 or less: the exchange's "0" clears a TP/SL (24 Sec.8.9), so a stored 0 would read as an
  attached stop. `tpsl_mode` takes the `positions.tpsl_mode` values ('Full', 'Partial').
* `orders.trade_group_leg_id` and `executions.trade_group_leg_id` have NO foreign key yet:
  `trade_group_legs` does not exist (0013/0014/0022 precedent). The E28-T01 revision that creates
  it adds both FKs, NOT VALID then validated (C-5.6), as recorded on #905
  (issuecomment-6220575333). `ix_orders_leg` and `ix_exec_leg` exist already.
* `order_events` and `executions` are append-only (C-5.7, the same ruling): beside their
  `forbid_mutation()` row triggers they copy the 0003 pattern, a BEFORE TRUNCATE statement trigger
  (`audit_refuse_truncate()`) and `REVOKE UPDATE, DELETE, TRUNCATE` from `cv_app` and `cv_ro`,
  skipped where a role does not exist (a migration-only test cluster; `pg_bootstrap.sql` order).
* C-5.9 / Sec.12: the monetary columns of `orders`, `executions`, `positions` and
  `position_snapshots` (class P1, every `numeric(38,18)` column) carry a `PII:` comment, mirrored
  byte-for-byte by `db.models`.
* `SET LOCAL lock_timeout = '5s'` brackets both directions (0028 pattern, C-5.6): the FKs lock
  `exchange_accounts` on the way in and the drops wait on readers on the way out.
* Downgrade locks the five tables and refuses while any holds rows: order history is append-only
  (`order_events`, `executions`) and the order rows are its idempotency keys, so a database with
  OMS rows is fixed forward, never downgraded (C-5.2). An empty or a seeded database (rows in the
  tables the OMS hangs off, such as `exchange_accounts`) round-trips (C-5.5); that seeded case is
  how this revision reads #845's "reverts against populated databases".
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0029_oms_core"
down_revision: str | None = "0028_incidents_backups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_ENUM_SQL)
    op.execute(_ORDERS_SQL)
    op.execute(_ORDER_EVENTS_SQL)
    op.execute(_EXECUTIONS_SQL)
    op.execute(_POSITIONS_SQL)
    op.execute(_GRANTS_SQL)
    op.execute(_COMMENT_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DOWNGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.1.2, verbatim.
_ENUM_SQL = """
CREATE TYPE order_intent        AS ENUM ('entry','stop_loss','take_profit','scale_in','scale_out','flatten','reverse','algo_child');
CREATE TYPE order_state         AS ENUM ('new','pending_submit','submitted','accepted','partially_filled','filled','pending_cancel','cancelled','pending_amend','rejected','expired','untracked');
CREATE TYPE order_event_kind    AS ENUM ('local_create','submit_attempt','ack','reject','fill','partial_fill','amend_request','amend_ack','cancel_request','cancel_ack','expire','exchange_push','reconcile_diff','error');
"""

# 21-database-schema.md Sec.3.3.4, verbatim except the deferred `trade_group_leg_id` FK.
_ORDERS_SQL = """
CREATE TABLE orders (
  id                   uuid PRIMARY KEY,
  trade_group_leg_id   uuid,  -- FK to trade_group_legs(id) ON DELETE SET NULL: added by E28-T01 (#905)
  exchange_account_id  uuid NOT NULL REFERENCES exchange_accounts(id) ON DELETE RESTRICT,
  parent_order_id      uuid REFERENCES orders(id) ON DELETE SET NULL,
  oco_group_ref        text,
  order_link_id        text NOT NULL,
  exchange_order_id    text,
  symbol               symbol_code NOT NULL,
  side                 text NOT NULL,
  intent               order_intent NOT NULL,
  order_type           text NOT NULL,
  qty                  numeric(38,18) NOT NULL,
  price                numeric(38,18),
  trigger_price        numeric(38,18),
  trigger_by           text,
  trigger_direction    smallint,
  take_profit          numeric(38,18),
  stop_loss            numeric(38,18),
  tpsl_mode            text NOT NULL DEFAULT 'Full',
  time_in_force        text NOT NULL DEFAULT 'GTC',
  reduce_only          boolean NOT NULL DEFAULT false,
  close_on_trigger     boolean NOT NULL DEFAULT false,
  position_idx         smallint NOT NULL DEFAULT 0,
  state                order_state NOT NULL DEFAULT 'new',
  cum_exec_qty         numeric(38,18) NOT NULL DEFAULT 0,
  cum_exec_value       numeric(38,18) NOT NULL DEFAULT 0,
  avg_price            numeric(38,18),
  leaves_qty           numeric(38,18) GENERATED ALWAYS AS (qty - cum_exec_qty) STORED,
  fee_paid             numeric(38,18) NOT NULL DEFAULT 0,
  reject_code          text,
  reject_message       text,
  submit_attempts      smallint NOT NULL DEFAULT 0,
  idempotency_state    text NOT NULL DEFAULT 'unsent',
  created_ts           timestamptz NOT NULL DEFAULT now(),
  submitted_ts         timestamptz,
  exchange_created_ts  timestamptz,
  exchange_updated_ts  timestamptz,
  last_reconciled_at   timestamptz,
  is_paper             boolean NOT NULL DEFAULT false,
  CONSTRAINT ord_side      CHECK (side IN ('Buy','Sell')),
  CONSTRAINT ord_type      CHECK (order_type IN ('Market','Limit')),
  CONSTRAINT ord_qty       CHECK (qty > 0),
  CONSTRAINT ord_limit_px  CHECK (order_type <> 'Limit' OR price > 0),
  CONSTRAINT ord_cum       CHECK (cum_exec_qty >= 0 AND cum_exec_qty <= qty),
  CONSTRAINT ord_tif       CHECK (time_in_force IN ('GTC','IOC','FOK','PostOnly')),
  CONSTRAINT ord_posidx    CHECK (position_idx IN (0,1,2)),
  CONSTRAINT ord_trigdir   CHECK (trigger_direction IS NULL OR trigger_direction IN (1,2)),
  CONSTRAINT ord_trigby    CHECK (trigger_by IS NULL OR trigger_by IN ('LastPrice','MarkPrice','IndexPrice')),
  CONSTRAINT ord_tp_px     CHECK (take_profit IS NULL OR take_profit > 0),
  CONSTRAINT ord_sl_px     CHECK (stop_loss IS NULL OR stop_loss > 0),
  CONSTRAINT ord_tpslmode  CHECK (tpsl_mode IN ('Full','Partial')),
  CONSTRAINT ord_attempts  CHECK (submit_attempts BETWEEN 0 AND 10),
  CONSTRAINT ord_idem      CHECK (idempotency_state IN ('unsent','in_flight','acked','failed')),
  CONSTRAINT ord_link_fmt  CHECK (
    order_link_id ~ '^cv[ldtp]-[0-7][0-9A-Za-z]{21}-[0-9A-Za-z]{4}-[0-9A-Za-z]{2}(en|sl|tp|sc|fl|ac)$'
    OR order_link_id ~ '^ext-[0-9a-f]{32}$'),
  CONSTRAINT ord_no_self   CHECK (parent_order_id IS DISTINCT FROM id)
);
CREATE UNIQUE INDEX ux_orders_link     ON orders (order_link_id);
CREATE UNIQUE INDEX ux_orders_exch_id  ON orders (exchange_account_id, exchange_order_id) WHERE exchange_order_id IS NOT NULL;
CREATE INDEX ix_orders_open      ON orders (exchange_account_id, symbol)
  WHERE state IN ('pending_submit','submitted','accepted','partially_filled','pending_cancel','pending_amend');
CREATE INDEX ix_orders_leg       ON orders (trade_group_leg_id);
CREATE INDEX ix_orders_parent    ON orders (parent_order_id) WHERE parent_order_id IS NOT NULL;
CREATE INDEX ix_orders_oco       ON orders (oco_group_ref) WHERE oco_group_ref IS NOT NULL;
CREATE INDEX ix_orders_recent    ON orders (exchange_account_id, created_ts DESC);
CREATE INDEX ix_orders_inflight  ON orders (created_ts) WHERE idempotency_state = 'in_flight';
CREATE INDEX ix_orders_untracked ON orders (exchange_account_id) WHERE state = 'untracked';
"""

# 21-database-schema.md Sec.3.3.5, verbatim (with the C-5.7 TRUNCATE guard it now records).
_ORDER_EVENTS_SQL = """
CREATE TABLE order_events (
  id            bigserial PRIMARY KEY,
  order_id      uuid NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  seq           integer NOT NULL,             -- per-order monotone sequence
  kind          order_event_kind NOT NULL,
  from_state    order_state,
  to_state      order_state,
  source        text NOT NULL,                -- local | rest | ws_private | reconcile | paper
  payload       jsonb NOT NULL DEFAULT '{}'::jsonb,   -- raw exchange message, redacted of credentials
  ret_code      text,
  ret_msg       text,
  latency_ms    integer,                      -- submit → ack, when measurable
  event_ts      timestamptz NOT NULL,         -- exchange time if known, else local
  recv_ts       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT oe_source  CHECK (source IN ('local','rest','ws_private','reconcile','paper')),
  CONSTRAINT oe_seq     CHECK (seq >= 0),
  CONSTRAINT oe_latency CHECK (latency_ms IS NULL OR latency_ms >= 0),
  UNIQUE (order_id, seq)
);
CREATE INDEX ix_oe_order_time ON order_events (order_id, event_ts);
CREATE INDEX ix_oe_time       ON order_events (event_ts DESC);
CREATE INDEX ix_oe_kind_time  ON order_events (kind, event_ts DESC);
CREATE TRIGGER trg_oe_append BEFORE UPDATE OR DELETE ON order_events
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER trg_oe_no_truncate BEFORE TRUNCATE ON order_events
  FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();
"""

# 21-database-schema.md Sec.3.3.6, verbatim (deferred leg FK and C-5.7 guard as above); two
# SQL comments name the exchange generically (cv-adapter-isolation, C-2.2).
_EXECUTIONS_SQL = """
CREATE TABLE executions (
  id                  uuid PRIMARY KEY,
  order_id            uuid REFERENCES orders(id) ON DELETE SET NULL,
  exchange_account_id uuid NOT NULL REFERENCES exchange_accounts(id) ON DELETE RESTRICT,
  trade_group_leg_id  uuid,                        -- FK to trade_group_legs(id) ON DELETE SET NULL: added by E28-T01 (#905)
  exec_id             text NOT NULL,               -- execId from the exchange
  order_link_id       text,                        -- = its order's order_link_id, normalised per 24-internal-schemas.md §14.2 rule 11
  symbol              symbol_code NOT NULL,
  side                text NOT NULL,
  exec_qty            numeric(38,18) NOT NULL,
  exec_price          numeric(38,18) NOT NULL,
  exec_value          numeric(38,18) NOT NULL,
  exec_type           text NOT NULL,               -- Trade | AdlTrade | Funding | BustTrade | Settle
  exec_fee            numeric(38,18) NOT NULL DEFAULT 0,
  fee_rate            numeric(18,10),
  fee_currency        text NOT NULL DEFAULT 'USDT',
  is_maker            boolean NOT NULL,
  closed_pnl          numeric(38,18),
  mark_price          numeric(38,18),
  underlying_price    numeric(38,18),
  block_trade_id      text,
  position_idx        smallint NOT NULL DEFAULT 0,
  is_paper            boolean NOT NULL DEFAULT false,
  exec_ts             timestamptz NOT NULL,        -- execTime from the exchange
  recv_ts             timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ex_qty   CHECK (exec_qty > 0),
  CONSTRAINT ex_px    CHECK (exec_price > 0),
  CONSTRAINT ex_side  CHECK (side IN ('Buy','Sell')),
  CONSTRAINT ex_type  CHECK (exec_type IN ('Trade','AdlTrade','Funding','BustTrade','Settle','SessionSettlePnl')),
  CONSTRAINT ex_posidx CHECK (position_idx IN (0,1,2))
);
CREATE UNIQUE INDEX ux_exec_id     ON executions (exchange_account_id, exec_id);
CREATE INDEX ix_exec_order         ON executions (order_id, exec_ts);
CREATE INDEX ix_exec_acct_time     ON executions (exchange_account_id, exec_ts DESC);
CREATE INDEX ix_exec_symbol_time   ON executions (symbol, exec_ts DESC);
CREATE INDEX ix_exec_leg           ON executions (trade_group_leg_id) WHERE trade_group_leg_id IS NOT NULL;
CREATE TRIGGER trg_exec_append BEFORE UPDATE OR DELETE ON executions
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER trg_exec_no_truncate BEFORE TRUNCATE ON executions
  FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();
"""

# 21-database-schema.md Sec.3.3.7, verbatim.
_POSITIONS_SQL = """
CREATE TABLE positions (
  id                   uuid PRIMARY KEY,
  exchange_account_id  uuid NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
  symbol               symbol_code NOT NULL,
  position_idx         smallint NOT NULL DEFAULT 0,
  side                 text,                       -- Buy | Sell | None(flat)
  size                 numeric(38,18) NOT NULL DEFAULT 0,
  avg_price            numeric(38,18),
  position_value       numeric(38,18),
  leverage             numeric(10,2),
  mark_price           numeric(38,18),
  liq_price            numeric(38,18),
  bust_price           numeric(38,18),
  position_im          numeric(38,18),
  position_mm          numeric(38,18),
  unrealised_pnl       numeric(38,18),
  cur_realised_pnl     numeric(38,18),
  cum_realised_pnl     numeric(38,18),
  take_profit          numeric(38,18),
  stop_loss            numeric(38,18),
  trailing_stop        numeric(38,18),
  tpsl_mode            text,                       -- Full | Partial
  adl_rank_indicator   smallint,
  auto_add_margin      boolean NOT NULL DEFAULT false,
  is_paper             boolean NOT NULL DEFAULT false,
  exchange_updated_ts  timestamptz,
  recv_ts              timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pos_size    CHECK (size >= 0),
  CONSTRAINT pos_side    CHECK (side IS NULL OR side IN ('Buy','Sell','None')),
  CONSTRAINT pos_posidx  CHECK (position_idx IN (0,1,2)),
  CONSTRAINT pos_tpslmode CHECK (tpsl_mode IS NULL OR tpsl_mode IN ('Full','Partial')),
  UNIQUE (exchange_account_id, symbol, position_idx)
);
CREATE INDEX ix_pos_open      ON positions (exchange_account_id) WHERE size > 0;
CREATE INDEX ix_pos_symbol    ON positions (symbol) WHERE size > 0;
CREATE INDEX ix_pos_no_sl     ON positions (exchange_account_id, symbol) WHERE size > 0 AND stop_loss IS NULL;

CREATE TABLE position_snapshots (
  id                  bigserial PRIMARY KEY,
  exchange_account_id uuid NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
  symbol              symbol_code NOT NULL,
  position_idx        smallint NOT NULL DEFAULT 0,
  size                numeric(38,18) NOT NULL,
  avg_price           numeric(38,18),
  mark_price          numeric(38,18),
  unrealised_pnl      numeric(38,18),
  cum_realised_pnl    numeric(38,18),
  liq_price           numeric(38,18),
  equity_usd          numeric(38,18),
  reason              text NOT NULL,       -- 'ws_push' | 'rest_reconcile' | 'minute_tick' | 'risk_eval'
  snap_ts             timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT psnap_reason CHECK (reason IN ('ws_push','rest_reconcile','minute_tick','risk_eval'))
);
CREATE INDEX ix_psnap_acct_time ON position_snapshots (exchange_account_id, snap_ts DESC);
CREATE INDEX ix_psnap_sym_time  ON position_snapshots (symbol, snap_ts DESC);
"""

# C-5.7: the 0003 grant pattern. The roles are cluster objects made by `pg_bootstrap.sql`; a
# migration-only test cluster has neither, so each REVOKE runs only where its role exists.
_GRANTS_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN
    EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON order_events, executions FROM cv_app';
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_ro') THEN
    EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON order_events, executions FROM cv_ro';
  END IF;
END
$BODY$;
"""

# C-5.9 / Sec.12: the monetary columns (every numeric(38,18) column) of these four tables are P1.
# Keep the text byte-identical to `db.models.OMS_MONEY_COMMENT` (`alembic check` diffs comments).
_MONEY_COMMENT = "PII: financial personal data (21 Sec.12, class P1); never sent to third parties"
_MONEY_COLUMNS = {
    "orders": (
        "qty", "price", "trigger_price", "take_profit", "stop_loss", "cum_exec_qty", "cum_exec_value",
        "avg_price", "leaves_qty", "fee_paid",
    ),
    "executions": ("exec_qty", "exec_price", "exec_value", "exec_fee", "closed_pnl", "mark_price", "underlying_price"),
    "positions": (
        "size", "avg_price", "position_value", "mark_price", "liq_price", "bust_price", "position_im",
        "position_mm", "unrealised_pnl", "cur_realised_pnl", "cum_realised_pnl", "take_profit",
        "stop_loss", "trailing_stop",
    ),
    "position_snapshots": (
        "size", "avg_price", "mark_price", "unrealised_pnl", "cum_realised_pnl", "liq_price",
        "equity_usd",
    ),
}  # fmt: skip
_COMMENT_SQL = "\n".join(
    f"COMMENT ON COLUMN {table}.{column} IS '{_MONEY_COMMENT}';"
    for table, columns in _MONEY_COLUMNS.items()
    for column in columns
)

_DOWNGRADE_SQL = """
LOCK TABLE orders, order_events, executions, positions, position_snapshots IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM orders) OR EXISTS (SELECT 1 FROM order_events)
     OR EXISTS (SELECT 1 FROM executions) OR EXISTS (SELECT 1 FROM positions)
     OR EXISTS (SELECT 1 FROM position_snapshots) THEN
    RAISE EXCEPTION '0029_oms_core downgrade refused: the OMS tables hold rows. Order history is append-only and order rows are its idempotency keys, so a populated database is never downgraded: fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
DROP TABLE position_snapshots;
DROP TABLE positions;
DROP TABLE executions;
DROP TABLE order_events;
DROP TABLE orders;
DROP TYPE order_event_kind;
DROP TYPE order_state;
DROP TYPE order_intent;
"""
