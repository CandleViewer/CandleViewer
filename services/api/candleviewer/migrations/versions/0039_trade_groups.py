"""trade groups, legs, group definitions and membership, and the leg foreign keys (E28-T01 #905)

Revision ID: 0039_trade_groups
Revises: 0038_risk_state
Create Date: 2026-10-20

Part 3 of E28-T01, the persistence of trade groups. The tables, triggers and functions are
`docs/plan/21-database-schema.md` Sec.3.3.2, Sec.3.3.3 and Sec.3.3.3a verbatim, and the three
enums are Sec.1.2 verbatim; no earlier revision created them. `exchange_accounts` (0017),
`rules` and `rule_runs` (0013), `orders` and `executions` (0029), `account_profiles` and
`account_profile_revisions` (0037), the `sha256_hex` (0001) and `symbol_code` (0004) domains and
`set_updated_at()` (0001) exist already.

* The DDL is the planned Sec.3.3.2/Sec.3.3.3 with what the E28-X01 and E29-X01 models and the
  plan's own defects required before it could land. G-6(b) of #2876 (SR-E29-07): the global
  UNIQUE on `client_group_ref` becomes `UNIQUE (created_by, client_group_ref)`, with the body
  fingerprint `client_body_sha256` and one format (`tg_ref_fmt`). SR-E28-07: the leg records
  `profile_version` (a composite FK to the revision) and a write-once `profile_snapshot` tied to
  its columns. SR-E28-16: `trg_tgl_env` names the leg-environment check the plan promised,
  `trg_tg_env` and `trg_tgdm_env` cover groups fired from definitions and members, and
  `trg_ea_env_in_use` fixes the environment of an account in use (blanket immutability stays
  #2333's). SR-E28-31 / F-03: definitions and membership get their own tables. SR-E28-08:
  `tgl_sl_px`. The plan's `ix_tgl_open` named a `leg_status` value that does not exist
  (`closing`), `ix_tgl_no_sl` missed filled legs, `tg_limit_px` and `tg_cond_px` let a NULL pass,
  and `tg_paper_env` contradicted 24's meaning of `is_paper` (orthogonal to the environment); all
  four are corrected in Sec.3.3.2/Sec.3.3.3 and here.
* Every integrity trigger is `ENABLE ALWAYS`, so `session_replication_role = replica` does not
  switch it off; only the four `updated_at` touch triggers are not. Each trigger function pins
  `search_path` and names tables in full; each refusal is SQLSTATE 23514 and names its trigger
  as the constraint (`USING CONSTRAINT`), never a value. The environment triggers read the
  account `FOR SHARE`, so an environment change and a leg or member insert serialise and
  `trg_ea_env_in_use` sees the committed row.
* The foreign keys 0013 and 0029 deferred to this revision (as recorded on #905,
  issuecomment-6220575333): `orders.trade_group_leg_id` and `executions.trade_group_leg_id` to
  `trade_group_legs`, and `rule_runs.trade_group_id` to `trade_groups`, `ON DELETE SET NULL`,
  named as Postgres names the plan's inline `REFERENCES`, added `NOT VALID` and then validated
  (C-5.6) after a pre-flight check that no row names a group or a leg yet (none can).
* `cv_app` holds no DELETE on `trade_groups`, `trade_group_legs` or `trade_group_definitions`
  where the role exists (0024's `api_keys` precedent): groups and legs are history, a
  definition leaves by soft delete; members keep DELETE.
* C-5.9 / Sec.12: the money columns of `trade_groups` and `trade_group_legs` (class P1, every
  `numeric(38,18)` column), `trade_groups.intent_note` and `algo_params` and the legs'
  `rejection_code` and `rejection_message` carry a `PII:` comment; `db.models` mirrors the texts
  byte for byte.
  `profile_snapshot` and the definitions are P0.
* `SET LOCAL lock_timeout = '5s'` brackets both directions (C-5.6).
* Downgrade locks the four tables and refuses unless all are empty (C-5.2: groups are trading
  history and definitions configuration); an empty or a seeded database (accounts, profiles and
  OMS rows with no leg) round-trips (C-5.5). It drops the guard on `exchange_accounts` and the
  three foreign keys before the tables.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0039_trade_groups"
down_revision: str | None = "0038_risk_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_ENUM_SQL)
    op.execute(_DEFINITIONS_SQL)
    op.execute(_GROUPS_SQL)
    op.execute(_LEGS_SQL)
    op.execute(_GROUP_TRIGGERS_SQL)
    op.execute(_LEG_TRIGGERS_SQL)
    op.execute(_GUARDS_SQL)
    op.execute(_PREFLIGHT_SQL)
    op.execute(_FK_SQL)
    op.execute("ALTER TABLE orders VALIDATE CONSTRAINT orders_trade_group_leg_id_fkey;")
    op.execute("ALTER TABLE executions VALIDATE CONSTRAINT executions_trade_group_leg_id_fkey;")
    op.execute("ALTER TABLE rule_runs VALIDATE CONSTRAINT rule_runs_trade_group_id_fkey;")
    op.execute(_GRANTS_SQL)
    op.execute(_COMMENT_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_REFUSE_SQL)
    op.execute(_DROP_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.1.2, the three trade-group enums, verbatim.
_ENUM_SQL = """
CREATE TYPE trade_group_status  AS ENUM ('draft','submitting','partially_open','open','closing','closed','failed','cancelled');
CREATE TYPE leg_status          AS ENUM ('pending','submitted','rejected','open','partially_filled','filled','cancelled','closed','error');
CREATE TYPE algo_kind           AS ENUM ('none','oco','iceberg','twap','chase','scaled','bracket');
"""

# 21-database-schema.md Sec.3.3.3a, first block, verbatim: `trade_groups` references it.
_DEFINITIONS_SQL = """
CREATE TABLE trade_group_definitions (
  id          uuid PRIMARY KEY,
  name        text NOT NULL,
  env         exchange_env NOT NULL,
  created_by  uuid REFERENCES users(id) ON DELETE SET NULL,
  updated_by  uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  deleted_at  timestamptz,
  CONSTRAINT tgd_name CHECK (char_length(name) BETWEEN 1 AND 80)
);
CREATE UNIQUE INDEX ux_tgd_name ON trade_group_definitions (lower(name)) WHERE deleted_at IS NULL;
CREATE TABLE trade_group_definition_members (
  definition_id       uuid NOT NULL REFERENCES trade_group_definitions(id) ON DELETE CASCADE,
  exchange_account_id uuid NOT NULL REFERENCES exchange_accounts(id) ON DELETE RESTRICT,
  enabled             boolean NOT NULL DEFAULT true,
  created_by          uuid REFERENCES users(id) ON DELETE SET NULL,
  updated_by          uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (definition_id, exchange_account_id)
);
CREATE INDEX ix_tgdm_account ON trade_group_definition_members (exchange_account_id);
"""

# 21-database-schema.md Sec.3.3.2, first block, verbatim.
_GROUPS_SQL = """
CREATE TABLE trade_groups (
  id                  uuid PRIMARY KEY,
  client_group_ref    text NOT NULL,
  client_body_sha256  sha256_hex NOT NULL,
  definition_id       uuid REFERENCES trade_group_definitions(id) ON DELETE RESTRICT,
  env                 exchange_env NOT NULL,
  symbol              symbol_code NOT NULL,
  side                text NOT NULL,
  status              trade_group_status NOT NULL DEFAULT 'draft',
  leg_failure_policy  text NOT NULL DEFAULT 'best_effort',
  algo                algo_kind NOT NULL DEFAULT 'none',
  algo_params         jsonb,
  intent_note         text,
  origin              text NOT NULL DEFAULT 'manual',
  origin_rule_id      uuid REFERENCES rules(id) ON DELETE SET NULL,
  origin_rule_run_id  uuid REFERENCES rule_runs(id) ON DELETE SET NULL,
  requested_qty_mode  sizing_mode NOT NULL DEFAULT 'risk_based',
  requested_qty_value numeric(38,18),
  entry_type          text NOT NULL DEFAULT 'Market',
  entry_price         numeric(38,18),
  trigger_price       numeric(38,18),
  trigger_by          text,
  sl_price_hint       numeric(38,18),
  tp_price_hint       numeric(38,18),
  is_paper            boolean NOT NULL DEFAULT false,
  submitted_at        timestamptz,
  opened_at           timestamptz,
  closed_at           timestamptz,
  created_by          uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT tg_side      CHECK (side IN ('Buy','Sell')),
  CONSTRAINT tg_origin    CHECK (origin IN ('manual','hotkey','dom_click','chart_click','rule','alert','replay_sim')),
  CONSTRAINT tg_policy    CHECK (leg_failure_policy IN ('best_effort','all_or_none','abort_on_first')),
  CONSTRAINT tg_entrytype CHECK (entry_type IN ('Market','Limit','Conditional')),
  CONSTRAINT tg_limit_px  CHECK ((entry_type <> 'Limit' OR entry_price > 0) IS TRUE),
  CONSTRAINT tg_cond_px   CHECK ((entry_type <> 'Conditional' OR (trigger_price > 0 AND trigger_by IS NOT NULL)) IS TRUE),
  CONSTRAINT tg_trigby    CHECK (trigger_by IS NULL OR trigger_by IN ('LastPrice','MarkPrice','IndexPrice')),
  CONSTRAINT tg_times     CHECK (closed_at IS NULL OR opened_at IS NULL OR closed_at >= opened_at),
  CONSTRAINT tg_ref_fmt   CHECK (client_group_ref ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
  CONSTRAINT tg_finite    CHECK (requested_qty_value <> 'NaN' AND entry_price <> 'NaN' AND trigger_price <> 'NaN'
    AND sl_price_hint <> 'NaN' AND tp_price_hint <> 'NaN'),
  CONSTRAINT ux_tg_creator_ref UNIQUE (created_by, client_group_ref)
);
CREATE INDEX ix_tg_open       ON trade_groups (symbol, created_at DESC) WHERE status IN ('submitting','partially_open','open','closing');
CREATE INDEX ix_tg_user_time  ON trade_groups (created_by, created_at DESC);
CREATE INDEX ix_tg_rule       ON trade_groups (origin_rule_id) WHERE origin_rule_id IS NOT NULL;
CREATE INDEX ix_tg_rule_run   ON trade_groups (origin_rule_run_id) WHERE origin_rule_run_id IS NOT NULL;
CREATE INDEX ix_tg_env_time   ON trade_groups (env, created_at DESC);
CREATE INDEX ix_tg_definition ON trade_groups (definition_id) WHERE definition_id IS NOT NULL;
"""

# 21-database-schema.md Sec.3.3.3, first block, verbatim.
_LEGS_SQL = """
CREATE TABLE trade_group_legs (
  id                    uuid PRIMARY KEY,
  trade_group_id        uuid NOT NULL REFERENCES trade_groups(id) ON DELETE CASCADE,
  exchange_account_id   uuid NOT NULL REFERENCES exchange_accounts(id) ON DELETE RESTRICT,
  account_profile_id    uuid REFERENCES account_profiles(id) ON DELETE SET NULL,
  profile_version       integer NOT NULL,
  profile_snapshot      jsonb NOT NULL,        -- frozen copy of the profile used
  status                leg_status NOT NULL DEFAULT 'pending',
  sequence_no           smallint NOT NULL,     -- fan-out order (rate-limit pacing)
  target_qty            numeric(38,18) NOT NULL,
  filled_qty            numeric(38,18) NOT NULL DEFAULT 0,
  avg_entry_price       numeric(38,18),
  avg_exit_price        numeric(38,18),
  resolved_leverage     numeric(10,2) NOT NULL,
  resolved_sl_price     numeric(38,18),
  resolved_tp_price     numeric(38,18),
  native_sl_confirmed   boolean NOT NULL DEFAULT false,
  native_sl_confirmed_at timestamptz,
  risk_usd              numeric(38,18),
  realised_pnl          numeric(38,18) NOT NULL DEFAULT 0,
  fees_paid             numeric(38,18) NOT NULL DEFAULT 0,
  rejection_code        text,
  rejection_message     text,
  submitted_at          timestamptz,
  closed_at             timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT tgl_qty_pos    CHECK (target_qty > 0),
  CONSTRAINT tgl_filled_rng CHECK (filled_qty >= 0 AND filled_qty <= target_qty),
  CONSTRAINT tgl_seq        CHECK (sequence_no BETWEEN 0 AND 100),
  CONSTRAINT tgl_lev        CHECK (resolved_leverage BETWEEN 1 AND 100),
  CONSTRAINT tgl_sl_conf    CHECK (native_sl_confirmed = false OR native_sl_confirmed_at IS NOT NULL),
  CONSTRAINT tgl_fees_nonneg CHECK (fees_paid >= 0),
  CONSTRAINT tgl_profile_version CHECK (profile_version >= 1),
  CONSTRAINT tgl_snapshot   CHECK ((jsonb_typeof(profile_snapshot) = 'object'
    AND profile_snapshot ->> 'account_id' = exchange_account_id::text
    AND profile_snapshot ->> 'version' = profile_version::text
    AND (account_profile_id IS NULL OR profile_snapshot ->> 'profile_id' = account_profile_id::text)) IS TRUE),
  CONSTRAINT tgl_sl_px      CHECK ((resolved_sl_price > 0 OR status IN ('rejected','cancelled','error')) IS TRUE),
  CONSTRAINT tgl_finite     CHECK (target_qty <> 'NaN' AND filled_qty <> 'NaN' AND avg_entry_price <> 'NaN'
    AND avg_exit_price <> 'NaN' AND resolved_leverage <> 'NaN' AND resolved_sl_price <> 'NaN'
    AND resolved_tp_price <> 'NaN' AND risk_usd <> 'NaN' AND realised_pnl <> 'NaN' AND fees_paid <> 'NaN'),
  CONSTRAINT tgl_profile_revision FOREIGN KEY (account_profile_id, profile_version)
    REFERENCES account_profile_revisions (profile_id, version),
  CONSTRAINT ux_tgl_group_account UNIQUE (trade_group_id, exchange_account_id)
);
CREATE INDEX ix_tgl_group   ON trade_group_legs (trade_group_id, sequence_no);
CREATE INDEX ix_tgl_account ON trade_group_legs (exchange_account_id, created_at DESC);
CREATE INDEX ix_tgl_open    ON trade_group_legs (exchange_account_id) WHERE status IN ('pending','submitted','open','partially_filled','filled');
CREATE INDEX ix_tgl_no_sl   ON trade_group_legs (trade_group_id) WHERE status IN ('open','partially_filled','filled') AND native_sl_confirmed = false;
CREATE INDEX ix_tgl_profile ON trade_group_legs (account_profile_id) WHERE account_profile_id IS NOT NULL;
"""

# 21-database-schema.md Sec.3.3.2, second block, verbatim.
_GROUP_TRIGGERS_SQL = """
CREATE FUNCTION tg_env_check() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE definition_env text;
BEGIN
  IF NEW.definition_id IS NOT NULL THEN
    SELECT d.env::text INTO definition_env FROM public.trade_group_definitions d WHERE d.id = NEW.definition_id;
    IF FOUND AND definition_env <> NEW.env::text THEN
      RAISE EXCEPTION 'trg_tg_env: a group fired from a definition is in the definition environment'
        USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_tg_env';
    END IF;
  END IF;
  RETURN NEW;
END $BODY$;
CREATE TRIGGER trg_tg_env BEFORE INSERT ON trade_groups
  FOR EACH ROW EXECUTE FUNCTION tg_env_check();
ALTER TABLE trade_groups ENABLE ALWAYS TRIGGER trg_tg_env;
CREATE FUNCTION tg_write_once() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.id IS DISTINCT FROM OLD.id THEN 'id'
    WHEN NEW.env IS DISTINCT FROM OLD.env THEN 'env'
    WHEN NEW.created_by IS DISTINCT FROM OLD.created_by THEN 'created_by'
    WHEN NEW.client_group_ref IS DISTINCT FROM OLD.client_group_ref THEN 'client_group_ref'
    WHEN NEW.client_body_sha256 IS DISTINCT FROM OLD.client_body_sha256 THEN 'client_body_sha256'
    WHEN NEW.definition_id IS DISTINCT FROM OLD.definition_id THEN 'definition_id'
    WHEN NEW.leg_failure_policy IS DISTINCT FROM OLD.leg_failure_policy THEN 'leg_failure_policy'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_tg_write_once: trade_groups.% is write-once', changed
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_tg_write_once';
  END IF;
  RETURN NEW;
END $BODY$;
CREATE TRIGGER trg_tg_write_once BEFORE UPDATE ON trade_groups
  FOR EACH ROW EXECUTE FUNCTION tg_write_once();
ALTER TABLE trade_groups ENABLE ALWAYS TRIGGER trg_tg_write_once;
CREATE TRIGGER trg_trade_groups_touch BEFORE UPDATE ON trade_groups
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
"""

# 21-database-schema.md Sec.3.3.3, second block, verbatim.
_LEG_TRIGGERS_SQL = """
CREATE FUNCTION tgl_env_check() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE group_env text; account_env text;
BEGIN
  SELECT g.env::text INTO group_env FROM public.trade_groups g WHERE g.id = NEW.trade_group_id;
  SELECT a.env::text INTO account_env FROM public.exchange_accounts a
    WHERE a.id = NEW.exchange_account_id FOR SHARE;
  IF group_env IS NOT NULL AND account_env IS NOT NULL AND group_env <> account_env THEN
    RAISE EXCEPTION 'trg_tgl_env: a leg account is outside its group environment'
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_tgl_env';
  END IF;
  RETURN NEW;
END $BODY$;
CREATE TRIGGER trg_tgl_env BEFORE INSERT OR UPDATE OF trade_group_id, exchange_account_id ON trade_group_legs
  FOR EACH ROW EXECUTE FUNCTION tgl_env_check();
ALTER TABLE trade_group_legs ENABLE ALWAYS TRIGGER trg_tgl_env;
CREATE FUNCTION tgl_profile_check() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
BEGIN
  IF NEW.account_profile_id IS NULL OR NOT EXISTS (
      SELECT FROM public.account_profiles p
      WHERE p.id = NEW.account_profile_id AND p.exchange_account_id = NEW.exchange_account_id
        AND p.deleted_at IS NULL) THEN
    RAISE EXCEPTION 'trg_tgl_profile: a leg is sized from a live profile of its own account'
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_tgl_profile';
  END IF;
  RETURN NEW;
END $BODY$;
CREATE TRIGGER trg_tgl_profile BEFORE INSERT ON trade_group_legs
  FOR EACH ROW EXECUTE FUNCTION tgl_profile_check();
ALTER TABLE trade_group_legs ENABLE ALWAYS TRIGGER trg_tgl_profile;
CREATE FUNCTION tgl_write_once() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.id IS DISTINCT FROM OLD.id THEN 'id'
    WHEN NEW.trade_group_id IS DISTINCT FROM OLD.trade_group_id THEN 'trade_group_id'
    WHEN NEW.exchange_account_id IS DISTINCT FROM OLD.exchange_account_id THEN 'exchange_account_id'
    WHEN NEW.profile_version IS DISTINCT FROM OLD.profile_version THEN 'profile_version'
    WHEN NEW.profile_snapshot IS DISTINCT FROM OLD.profile_snapshot THEN 'profile_snapshot'
    WHEN NEW.account_profile_id IS DISTINCT FROM OLD.account_profile_id
      AND (NEW.account_profile_id IS NOT NULL
        OR EXISTS (SELECT FROM public.account_profiles p WHERE p.id = OLD.account_profile_id))
      THEN 'account_profile_id'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_tgl_write_once: trade_group_legs.% is write-once', changed
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_tgl_write_once';
  END IF;
  RETURN NEW;
END $BODY$;
CREATE TRIGGER trg_tgl_write_once BEFORE UPDATE ON trade_group_legs
  FOR EACH ROW EXECUTE FUNCTION tgl_write_once();
ALTER TABLE trade_group_legs ENABLE ALWAYS TRIGGER trg_tgl_write_once;
CREATE TRIGGER trg_trade_group_legs_touch BEFORE UPDATE ON trade_group_legs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
"""

# 21-database-schema.md Sec.3.3.3a, second block, verbatim: the environment guards.
_GUARDS_SQL = """
CREATE FUNCTION tgd_write_once() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.id IS DISTINCT FROM OLD.id THEN 'id'
    WHEN NEW.env IS DISTINCT FROM OLD.env THEN 'env'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_tgd_write_once: trade_group_definitions.% is write-once', changed
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_tgd_write_once';
  END IF;
  RETURN NEW;
END $BODY$;
CREATE TRIGGER trg_tgd_write_once BEFORE UPDATE ON trade_group_definitions
  FOR EACH ROW EXECUTE FUNCTION tgd_write_once();
ALTER TABLE trade_group_definitions ENABLE ALWAYS TRIGGER trg_tgd_write_once;
CREATE TRIGGER trg_trade_group_definitions_touch BEFORE UPDATE ON trade_group_definitions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE FUNCTION tgdm_env_check() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE definition_env text; account_env text;
BEGIN
  SELECT d.env::text INTO definition_env FROM public.trade_group_definitions d WHERE d.id = NEW.definition_id;
  SELECT a.env::text INTO account_env FROM public.exchange_accounts a
    WHERE a.id = NEW.exchange_account_id FOR SHARE;
  IF definition_env IS NOT NULL AND account_env IS NOT NULL AND definition_env <> account_env THEN
    RAISE EXCEPTION 'trg_tgdm_env: a member account is outside its definition environment'
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_tgdm_env';
  END IF;
  RETURN NEW;
END $BODY$;
CREATE TRIGGER trg_tgdm_env BEFORE INSERT OR UPDATE OF definition_id, exchange_account_id
  ON trade_group_definition_members FOR EACH ROW EXECUTE FUNCTION tgdm_env_check();
ALTER TABLE trade_group_definition_members ENABLE ALWAYS TRIGGER trg_tgdm_env;
CREATE TRIGGER trg_trade_group_definition_members_touch BEFORE UPDATE ON trade_group_definition_members
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE FUNCTION ea_env_in_use_check() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
BEGIN
  IF NEW.env IS DISTINCT FROM OLD.env AND (
      EXISTS (SELECT FROM public.trade_group_definition_members m WHERE m.exchange_account_id = OLD.id)
      OR EXISTS (SELECT FROM public.trade_group_legs l WHERE l.exchange_account_id = OLD.id)) THEN
    RAISE EXCEPTION 'trg_ea_env_in_use: the environment of an account in a trade group or a definition is fixed'
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ea_env_in_use';
  END IF;
  RETURN NEW;
END $BODY$;
CREATE TRIGGER trg_ea_env_in_use BEFORE UPDATE OF env ON exchange_accounts
  FOR EACH ROW EXECUTE FUNCTION ea_env_in_use_check();
ALTER TABLE exchange_accounts ENABLE ALWAYS TRIGGER trg_ea_env_in_use;
"""

# No row can name a group or a leg before they exist; a value would be dangling and would fail
# the validation below with a less useful error (0022's pre-flight precedent).
_PREFLIGHT_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM orders WHERE trade_group_leg_id IS NOT NULL)
     OR EXISTS (SELECT 1 FROM executions WHERE trade_group_leg_id IS NOT NULL)
     OR EXISTS (SELECT 1 FROM rule_runs WHERE trade_group_id IS NOT NULL) THEN
    RAISE EXCEPTION '0039_trade_groups upgrade refused: an order, execution or rule run names a trade group or leg, and none can exist before this revision. Clear the dangling ids first';
  END IF;
END $BODY$;
"""

# The deferred FKs, named as Postgres names the plan's inline REFERENCES (Sec.3.3.4, Sec.3.3.6,
# Sec.3.4.3), NOT VALID; `upgrade()` validates each (C-5.6).
_FK_SQL = """
ALTER TABLE orders ADD CONSTRAINT orders_trade_group_leg_id_fkey
  FOREIGN KEY (trade_group_leg_id) REFERENCES trade_group_legs(id) ON DELETE SET NULL NOT VALID;
ALTER TABLE executions ADD CONSTRAINT executions_trade_group_leg_id_fkey
  FOREIGN KEY (trade_group_leg_id) REFERENCES trade_group_legs(id) ON DELETE SET NULL NOT VALID;
ALTER TABLE rule_runs ADD CONSTRAINT rule_runs_trade_group_id_fkey
  FOREIGN KEY (trade_group_id) REFERENCES trade_groups(id) ON DELETE SET NULL NOT VALID;
"""

# 0024's precedent: groups and legs are history, a definition leaves by soft delete. Each REVOKE
# runs only where `pg_bootstrap.sql` made the role.
_GRANTS_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN
    EXECUTE 'REVOKE DELETE ON trade_groups FROM cv_app';
    EXECUTE 'REVOKE DELETE ON trade_group_legs FROM cv_app';
    EXECUTE 'REVOKE DELETE ON trade_group_definitions FROM cv_app';
  END IF;
END
$BODY$;
"""

# C-5.9 / Sec.12, class P1. Keep the texts byte-identical to `db.models` (`alembic check` diffs
# comments): the money and exchange-text ones are 0029's, shared through `db.models`.
_MONEY_COMMENT = "PII: financial personal data (21 Sec.12, class P1); never sent to third parties"
_EXCHANGE_TEXT_COMMENT = (
    "PII: exchange answer text that can repeat order values (21 Sec.12, class P1); "
    "redacted before insert; never logged"
)
_NOTE_COMMENT = "PII: free text a user wrote (21 Sec.12, class P1); never logged"
_ALGO_COMMENT = (
    "PII: algo parameters that can repeat order prices and quantities (21 Sec.12, class P1); "
    "never logged"
)
_COMMENTED: dict[str, dict[str, tuple[str, ...]]] = {
    _MONEY_COMMENT: {
        "trade_groups": (
            "requested_qty_value", "entry_price", "trigger_price", "sl_price_hint", "tp_price_hint",
        ),
        "trade_group_legs": (
            "target_qty", "filled_qty", "avg_entry_price", "avg_exit_price", "resolved_sl_price",
            "resolved_tp_price", "risk_usd", "realised_pnl", "fees_paid",
        ),
    },
    _EXCHANGE_TEXT_COMMENT: {"trade_group_legs": ("rejection_code", "rejection_message")},
    _NOTE_COMMENT: {"trade_groups": ("intent_note",)},
    _ALGO_COMMENT: {"trade_groups": ("algo_params",)},
}  # fmt: skip
_COMMENT_SQL = "\n".join(
    f"COMMENT ON COLUMN {table}.{column} IS '{comment}';"
    for comment, groups in _COMMENTED.items()
    for table, columns in groups.items()
    for column in columns
)

_REFUSE_SQL = """
LOCK TABLE trade_groups, trade_group_legs, trade_group_definitions, trade_group_definition_members IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM trade_groups) OR EXISTS (SELECT 1 FROM trade_group_legs)
     OR EXISTS (SELECT 1 FROM trade_group_definitions)
     OR EXISTS (SELECT 1 FROM trade_group_definition_members) THEN
    RAISE EXCEPTION '0039_trade_groups downgrade refused: trade groups or group definitions exist, and dropping the tables would lose that trading history and configuration. Fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
"""

_DROP_SQL = """
DROP TRIGGER trg_ea_env_in_use ON exchange_accounts;
DROP FUNCTION ea_env_in_use_check();
ALTER TABLE rule_runs DROP CONSTRAINT rule_runs_trade_group_id_fkey;
ALTER TABLE executions DROP CONSTRAINT executions_trade_group_leg_id_fkey;
ALTER TABLE orders DROP CONSTRAINT orders_trade_group_leg_id_fkey;
DROP TABLE trade_group_legs;
DROP TABLE trade_groups;
DROP TABLE trade_group_definition_members;
DROP TABLE trade_group_definitions;
DROP FUNCTION tgl_write_once();
DROP FUNCTION tgl_profile_check();
DROP FUNCTION tgl_env_check();
DROP FUNCTION tg_write_once();
DROP FUNCTION tg_env_check();
DROP FUNCTION tgdm_env_check();
DROP FUNCTION tgd_write_once();
DROP TYPE algo_kind;
DROP TYPE leg_status;
DROP TYPE trade_group_status;
"""
