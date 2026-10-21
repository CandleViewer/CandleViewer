"""the order submission: the replay anchor, the recorded stops, the order's provenance (E29-T04)

Revision ID: 0043_order_submission
Revises: 0044_account_no_hard_delete
Create Date: 2026-10-21

Slice 2a of E29-T04 (#913), the storage of the order-submission pipeline. The tables, functions
and triggers are `docs/plan/21-database-schema.md` Sec.3.3.10 and Sec.3.3.11 verbatim, and the
`orders` column with its CHECK is Sec.3.3.4's third block; no earlier revision created them.
`users` (0001), `exchange_accounts` (0017), `orders` (0029), `trade_groups` (0039), the
`sha256_hex` (0001) and `symbol_code` (0004) domains and `audit_refuse_truncate()` (0003) exist
already.

* `idempotency_anchors` (SR-E29-07, #913 ruling R3): the permanent, principal-scoped replay
  anchor of an order-creating request. `ux_ia_principal_ref` is its one key, and
  `trg_ia_write_once` freezes the request and, once it is set, the outcome.
* `recorded_stops` (SR-E29-06, G-6 ruling 1): one row per stop the OMS requests, written ahead.
  `ux_rs_in_flight` admits one request in flight per position and `ux_rs_in_force` one row in
  force per side; `trg_rs_guard` keeps the request and admits only the lifecycle moves, one bind
  of the TP/SL order and one stamped release.
* `orders.provenance` (22 `OrderProvenance`): how the row came to exist. Every row that exists is
  `placed`, so the NOT NULL default needs no backfill and `ord_provenance` reads each row once.
* No row leaves either table: `trg_ia_no_truncate` and `trg_rs_no_truncate` (0003's
  `audit_refuse_truncate()`, SR-E29-05's pattern) refuse a TRUNCATE by any role, and DELETE and
  TRUNCATE are revoked from `cv_app` and `cv_ro` where those roles exist. The anchor's trigger is
  the orchestrator's Q8 ruling on #913, in Sec.3.3.10's second block.
* Every trigger is `ENABLE ALWAYS`, so `session_replication_role = replica` cannot switch one
  off; each guard pins `search_path` and refuses with SQLSTATE 23514 naming itself, never a
  value.
* C-5.9 / Sec.12, class P1: the anchor's `client_ref` and `request_sha256` and the stops' four
  money columns carry a `PII:` comment; `db.models` mirrors the texts byte for byte.
* `SET LOCAL lock_timeout = '5s'` brackets both directions (C-5.6).
* The downgrade locks the three tables and refuses while an anchor, a recorded stop or an order
  of another provenance than `placed` exists (C-5.2): dropping them would lose permanent replay
  anchors, protective-stop history or how an order came to exist. Otherwise it drops both
  tables, their functions, and the column with its CHECK.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0043_order_submission"
down_revision: str | None = "0044_account_no_hard_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_ORDERS_SQL)
    op.execute(_ANCHORS_SQL)
    op.execute(_ANCHOR_GUARD_SQL)
    op.execute(_STOPS_SQL)
    op.execute(_STOP_GUARD_SQL)
    op.execute(_GRANTS_SQL)
    op.execute(_COMMENT_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_REFUSE_SQL)
    op.execute(_DROP_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.3.4, third block, verbatim: the order's provenance.
_ORDERS_SQL = """
ALTER TABLE orders ADD COLUMN provenance text NOT NULL DEFAULT 'placed';
ALTER TABLE orders ADD CONSTRAINT ord_provenance CHECK (provenance IN ('placed','reconciliation','recorded_stop'));
"""

# Sec.3.3.10, first block, verbatim: the anchor, after the `trade_groups` and `orders` it names.
_ANCHORS_SQL = """
CREATE TABLE idempotency_anchors (
  id               uuid PRIMARY KEY,
  created_by       uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  operation        text NOT NULL,
  client_ref       text NOT NULL,
  request_sha256   sha256_hex NOT NULL,
  trade_group_id   uuid REFERENCES trade_groups(id) ON DELETE RESTRICT,
  order_id         uuid REFERENCES orders(id) ON DELETE RESTRICT,
  outcome_status   smallint,
  outcome_code     text,
  outcome_ret_code integer,
  created_at       timestamptz NOT NULL DEFAULT now(),
  decided_at       timestamptz,
  CONSTRAINT ia_operation CHECK (operation IN ('placeOrder','closePosition','reversePosition','closeAllPositions')),
  CONSTRAINT ia_ref_fmt   CHECK (client_ref ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
  CONSTRAINT ia_target    CHECK (num_nonnulls(trade_group_id, order_id) <= 1
    AND (operation <> 'placeOrder' OR num_nonnulls(trade_group_id, order_id) = 1)),
  CONSTRAINT ia_decided   CHECK ((outcome_status IS NULL) = (decided_at IS NULL)
    AND (outcome_status IS NULL OR outcome_status BETWEEN 200 AND 599)),
  CONSTRAINT ia_code      CHECK ((outcome_code IS NOT NULL) = COALESCE(outcome_status >= 400, false)
    AND (outcome_code IS NULL OR outcome_code ~ '^[a-z][a-z0-9_]{1,63}$')),
  CONSTRAINT ia_ret_code  CHECK ((outcome_ret_code IS NULL OR outcome_code = 'exchange_error') IS TRUE),
  CONSTRAINT ux_ia_principal_ref UNIQUE (created_by, operation, client_ref)
);
"""

# Sec.3.3.10, second block, verbatim: the anchor's write-once trigger and, as the orchestrator's
# Q8 ruling on #913 has it (the anchor is permanent), its TRUNCATE refusal.
_ANCHOR_GUARD_SQL = """
CREATE FUNCTION ia_write_once() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.id IS DISTINCT FROM OLD.id THEN 'id'
    WHEN NEW.created_by IS DISTINCT FROM OLD.created_by THEN 'created_by'
    WHEN NEW.operation IS DISTINCT FROM OLD.operation THEN 'operation'
    WHEN NEW.client_ref IS DISTINCT FROM OLD.client_ref THEN 'client_ref'
    WHEN NEW.request_sha256 IS DISTINCT FROM OLD.request_sha256 THEN 'request_sha256'
    WHEN NEW.trade_group_id IS DISTINCT FROM OLD.trade_group_id THEN 'trade_group_id'
    WHEN NEW.order_id IS DISTINCT FROM OLD.order_id THEN 'order_id'
    WHEN NEW.created_at IS DISTINCT FROM OLD.created_at THEN 'created_at'
    WHEN OLD.outcome_status IS NOT NULL
      AND (NEW.outcome_status, NEW.outcome_code, NEW.outcome_ret_code, NEW.decided_at)
        IS DISTINCT FROM (OLD.outcome_status, OLD.outcome_code, OLD.outcome_ret_code, OLD.decided_at)
      THEN 'outcome'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_ia_write_once: idempotency_anchors.% is write-once', changed
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ia_write_once';
  END IF;
  RETURN NEW;
END $BODY$;
CREATE TRIGGER trg_ia_write_once BEFORE UPDATE ON idempotency_anchors
  FOR EACH ROW EXECUTE FUNCTION ia_write_once();
ALTER TABLE idempotency_anchors ENABLE ALWAYS TRIGGER trg_ia_write_once;
CREATE TRIGGER trg_ia_no_truncate BEFORE TRUNCATE ON idempotency_anchors
  FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();
ALTER TABLE idempotency_anchors ENABLE ALWAYS TRIGGER trg_ia_no_truncate;
"""

# Sec.3.3.11, first block, verbatim: the recorded stops and their five indexes.
_STOPS_SQL = """
CREATE TABLE recorded_stops (
  id                    uuid PRIMARY KEY,
  exchange_account_id   uuid NOT NULL REFERENCES exchange_accounts(id) ON DELETE RESTRICT,
  symbol                symbol_code NOT NULL,
  position_idx          smallint NOT NULL,
  position_side         text NOT NULL,
  kind                  text NOT NULL,
  source                text NOT NULL,
  order_id              uuid REFERENCES orders(id) ON DELETE RESTRICT,
  tpsl_mode             text NOT NULL,
  trigger_price         numeric(38,18) NOT NULL,
  size                  numeric(38,18),
  trailing_distance     numeric(38,18),
  trailing_active_price numeric(38,18),
  exchange_order_id     text,
  status                text NOT NULL DEFAULT 'pending',
  audit_record_id       uuid NOT NULL,
  actor_user_id         uuid REFERENCES users(id) ON DELETE RESTRICT,
  created_at            timestamptz NOT NULL DEFAULT now(),
  answered_at           timestamptz,
  in_force_at           timestamptz,
  closed_at             timestamptz,
  released_at           timestamptz,
  position_marker       text,
  CONSTRAINT rs_posidx  CHECK (position_idx IN (0,1,2)),
  CONSTRAINT rs_side    CHECK (position_side IN ('Buy','Sell')),
  CONSTRAINT rs_kind    CHECK (kind IN ('stop_loss','take_profit')),
  CONSTRAINT rs_source  CHECK (source IN ('entry_attach','trading_stop','restore')),
  CONSTRAINT rs_entry   CHECK ((source = 'entry_attach') = (order_id IS NOT NULL)),
  CONSTRAINT rs_restore CHECK (source <> 'restore' OR kind = 'stop_loss'),
  CONSTRAINT rs_mode    CHECK (tpsl_mode IN ('Full','Partial')),
  CONSTRAINT rs_px      CHECK (trigger_price > 0),
  CONSTRAINT rs_size    CHECK ((tpsl_mode = 'Partial' AND size > 0 OR tpsl_mode = 'Full' AND size IS NULL) IS TRUE),
  CONSTRAINT rs_trail   CHECK (num_nonnulls(trailing_distance, trailing_active_price) <> 1
    AND (trailing_distance IS NULL OR (kind = 'stop_loss' AND trailing_distance > 0 AND trailing_active_price > 0))),
  CONSTRAINT rs_finite  CHECK (trigger_price <> 'NaN' AND size <> 'NaN' AND trailing_distance <> 'NaN'
    AND trailing_active_price <> 'NaN'),
  CONSTRAINT rs_status  CHECK (status IN ('pending','in_force','replaced','ended','void')),
  CONSTRAINT rs_times   CHECK ((closed_at IS NOT NULL) = (status IN ('replaced','ended','void'))
    AND (in_force_at IS NOT NULL OR status NOT IN ('in_force','ended'))
    AND (in_force_at IS NULL OR status IN ('in_force','replaced','ended'))),
  CONSTRAINT rs_release CHECK (released_at IS NULL OR exchange_order_id IS NULL),
  CONSTRAINT rs_marker  CHECK (position_marker IS NULL OR char_length(position_marker) BETWEEN 1 AND 64)
);
CREATE UNIQUE INDEX ux_rs_in_flight ON recorded_stops (exchange_account_id, symbol, position_idx)
  WHERE status = 'pending' AND answered_at IS NULL AND kind = 'stop_loss';
CREATE UNIQUE INDEX ux_rs_in_force  ON recorded_stops (exchange_account_id, symbol, position_idx, kind)
  WHERE status = 'in_force';
CREATE INDEX ix_rs_live    ON recorded_stops (exchange_account_id, symbol, position_idx)
  WHERE status IN ('pending','in_force');
CREATE INDEX ix_rs_exch_id ON recorded_stops (exchange_account_id, exchange_order_id)
  WHERE exchange_order_id IS NOT NULL;
CREATE INDEX ix_rs_order   ON recorded_stops (order_id) WHERE order_id IS NOT NULL;
"""

# Sec.3.3.11, second block, verbatim: the guard and the TRUNCATE trigger.
_STOP_GUARD_SQL = """
CREATE FUNCTION rs_guard() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN (NEW.id, NEW.exchange_account_id, NEW.symbol, NEW.position_idx, NEW.position_side, NEW.kind,
          NEW.source, NEW.order_id, NEW.tpsl_mode, NEW.trigger_price, NEW.size, NEW.trailing_distance,
          NEW.trailing_active_price, NEW.audit_record_id, NEW.actor_user_id, NEW.created_at)
      IS DISTINCT FROM (OLD.id, OLD.exchange_account_id, OLD.symbol, OLD.position_idx, OLD.position_side,
          OLD.kind, OLD.source, OLD.order_id, OLD.tpsl_mode, OLD.trigger_price, OLD.size,
          OLD.trailing_distance, OLD.trailing_active_price, OLD.audit_record_id, OLD.actor_user_id,
          OLD.created_at) THEN 'request'
    WHEN OLD.answered_at IS NOT NULL AND NEW.answered_at IS DISTINCT FROM OLD.answered_at THEN 'answered_at'
    WHEN OLD.in_force_at IS NOT NULL AND NEW.in_force_at IS DISTINCT FROM OLD.in_force_at THEN 'in_force_at'
    WHEN OLD.closed_at IS NOT NULL AND NEW.closed_at IS DISTINCT FROM OLD.closed_at THEN 'closed_at'
    WHEN OLD.released_at IS NOT NULL AND NEW.released_at IS DISTINCT FROM OLD.released_at THEN 'released_at'
    WHEN OLD.position_marker IS NOT NULL AND NEW.position_marker IS DISTINCT FROM OLD.position_marker THEN 'position_marker'
    WHEN NEW.exchange_order_id IS DISTINCT FROM OLD.exchange_order_id
      AND NOT (OLD.exchange_order_id IS NULL AND OLD.released_at IS NULL)      -- the one bind
      AND NOT (NEW.exchange_order_id IS NULL AND NEW.released_at IS NOT NULL)  -- the one release
      THEN 'exchange_order_id'
    WHEN NEW.released_at IS DISTINCT FROM OLD.released_at AND OLD.exchange_order_id IS NULL THEN 'released_at'
    WHEN NEW.status <> OLD.status AND (OLD.status, NEW.status) NOT IN (('pending','in_force'),
      ('pending','void'), ('pending','replaced'), ('in_force','replaced'), ('in_force','ended')) THEN 'status'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_rs_guard: recorded_stops.% may not change so', changed
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_rs_guard';
  END IF;
  RETURN NEW;
END $BODY$;
CREATE TRIGGER trg_rs_guard BEFORE UPDATE ON recorded_stops
  FOR EACH ROW EXECUTE FUNCTION rs_guard();
ALTER TABLE recorded_stops ENABLE ALWAYS TRIGGER trg_rs_guard;
CREATE TRIGGER trg_rs_no_truncate BEFORE TRUNCATE ON recorded_stops
  FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();
ALTER TABLE recorded_stops ENABLE ALWAYS TRIGGER trg_rs_no_truncate;
"""

# Neither table loses a row (Sec.3.3.10, Sec.3.3.11, Sec.7): the 0029 grant pattern, each REVOKE
# run only where `pg_bootstrap.sql` made its role (a migration-only test cluster has neither).
_GRANTS_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN
    EXECUTE 'REVOKE DELETE, TRUNCATE ON idempotency_anchors, recorded_stops FROM cv_app';
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_ro') THEN
    EXECUTE 'REVOKE DELETE, TRUNCATE ON idempotency_anchors, recorded_stops FROM cv_ro';
  END IF;
END
$BODY$;
"""

# C-5.9 / Sec.12, class P1. Keep the texts byte-identical to `db.models` (`alembic check` diffs
# comments): the money one is 0029's, shared through `db.models`.
_MONEY_COMMENT = "PII: financial personal data (21 Sec.12, class P1); never sent to third parties"
_ANCHOR_KEY_COMMENT = (
    "PII: a client idempotency key or the digest of its order request (21 Sec.12, class P1); "
    "never logged or returned"
)
_COMMENTED: dict[str, dict[str, tuple[str, ...]]] = {
    _MONEY_COMMENT: {
        "recorded_stops": ("trigger_price", "size", "trailing_distance", "trailing_active_price"),
    },
    _ANCHOR_KEY_COMMENT: {"idempotency_anchors": ("client_ref", "request_sha256")},
}
_COMMENT_SQL = "\n".join(
    f"COMMENT ON COLUMN {table}.{column} IS '{comment}';"
    for comment, groups in _COMMENTED.items()
    for table, columns in groups.items()
    for column in columns
)

_REFUSE_SQL = """
LOCK TABLE recorded_stops, idempotency_anchors, orders IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM recorded_stops) OR EXISTS (SELECT 1 FROM idempotency_anchors)
     OR EXISTS (SELECT 1 FROM orders WHERE provenance <> 'placed') THEN
    RAISE EXCEPTION '0043_order_submission downgrade refused: a recorded stop, an idempotency anchor or an order of another provenance than placed exists, and dropping them would lose protective-stop history, permanent replay anchors or how an order came to exist. Fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
"""

_DROP_SQL = """
DROP TABLE recorded_stops;
DROP FUNCTION rs_guard();
DROP TABLE idempotency_anchors;
DROP FUNCTION ia_write_once();
ALTER TABLE orders DROP CONSTRAINT ord_provenance;
ALTER TABLE orders DROP COLUMN provenance;
"""
