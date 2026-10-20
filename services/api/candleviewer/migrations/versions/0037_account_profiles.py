"""account_profiles, account_profile_revisions and the default-profile bootstrap (E28-T01 #905)

Revision ID: 0037_account_profiles
Revises: 0036_users_purge
Create Date: 2026-10-20

Part 1 of E28-T01, the persistence of per-account profiles. The tables, triggers and functions are
`docs/plan/21-database-schema.md` Sec.3.2.4 and Sec.3.2.5 verbatim, and `sizing_mode` and
`offset_unit` are Sec.1.2 verbatim; no earlier revision created them. `exchange_accounts` (0017),
`set_updated_at()` (0001), `forbid_mutation()` and `audit_refuse_truncate()` (0003) exist already.

* The DDL is Sec.3.2.4 as planned plus the E28-X01 schema findings raised on #905 before the DDL
  was written (`docs/security/threat-models/E28-profiles-trade-groups.md` Sec.11.1): F-04 / SR-E28-01
  (every cap the guard enforces, `enabled`, `trading_enabled`, `version`, an explicit
  `all_symbols`, and `ap_trading_caps`: no unbounded cap on a trading-enabled profile, decision
  D11) and F-06 / SR-E28-07 (`account_profile_revisions` is INSERT-only and `version` is set by
  the database). `ap_finite` keeps NaN out of every number: Postgres sorts NaN above every
  number, so it passes a bound alone and would count as a cap (a column with a precision cannot
  hold infinity). SR-E28-08 keeps `ap_native_sl` and adds `ap_sl_unit`: R is defined by the stop,
  so `r_multiple` never is one (24-internal-schemas.md Sec.9.3.1). The other added columns give
  every field of the Sec.9.2 `AccountProfile` model a column.
* `trg_ap_version` makes `version` 1 on insert and +1 on every update, and `id` and
  `exchange_account_id` write-once; `trg_ap_revision` copies the row into
  `account_profile_revisions` in the same transaction. Both are `ENABLE ALWAYS`, as are the
  ladder check, the bootstrap and the revisions' append-only triggers, so none is switched off by
  `session_replication_role = replica`; only `trg_account_profiles_touch` (bookkeeping) is not.
* `account_profile_revisions` copies the 0029 append-only pattern: `forbid_mutation()` per row,
  `audit_refuse_truncate()` per statement, and `REVOKE INSERT, UPDATE, DELETE, TRUNCATE` from
  `cv_app` and `cv_ro`, skipped where a role does not exist (a migration-only test cluster). It
  narrows grants and widens none. INSERT goes too: `ap_record_revision()` is `SECURITY DEFINER`
  (it runs as its owner, the migration role; `search_path` pinned, tables named in full) and
  executable by no other role, so only a profile write adds a revision; the runtime role cannot
  forge one, nor wedge a profile's next write on `ux_apr_version` with a planted row.
* `cv_app` holds no DELETE on `account_profiles` (0024's `api_keys` precedent): a profile leaves
  by soft delete, an update that leaves a revision. A hard delete would leave none and could take
  an account's ceiling with it; an account's own deletion still cascades to its profiles, as the
  RI action runs as the table's owner.
* The triggers' refusals name the trigger as the error's constraint (`USING CONSTRAINT`), so the
  store maps them by name like a CHECK.
* Bootstrap: `trg_ea_default_profile` gives every new exchange account a `Default` profile, and
  this revision gives one to every existing account (seed rows, Sec.9.3 rule 5). The profile is not
  trading-enabled, sizes `risk_based` at 1 % and allows no symbol, so it is inert until the owner
  completes it.
* Class P0 in Sec.12's scheme (asset A-08 of the E28 threat model: Confidential, integrity-critical):
  profile configuration holds no credential, token, key or personal data, so no
  column carries a `PII:` comment.
* `SET LOCAL lock_timeout = '5s'` brackets both directions (C-5.6): the FKs and the trigger lock
  `exchange_accounts` and `users` on the way in; the drops wait on readers on the way out.
* Downgrade locks both tables and refuses unless every profile is an untouched bootstrap default
  (version 1, `Default`, `is_default`) and every revision is one of theirs (the two counts match:
  each write leaves a revision and none can be deleted, so a profile edited or deleted, hard
  deletes and cascades included, leaves one more; a created one fails the name and default test). Profiles are user configuration and their
  history is append-only, so such a database is fixed forward (C-5.2). An empty or a seeded
  database (accounts with their bootstrap profiles only) round-trips (C-5.5).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0037_account_profiles"
down_revision: str | None = "0036_users_purge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_ENUM_SQL)
    op.execute(_PROFILES_SQL)
    op.execute(_REVISIONS_SQL)
    op.execute(_PROFILE_TRIGGERS_SQL)
    op.execute(_BOOTSTRAP_SQL)
    op.execute(_BACKFILL_SQL)
    op.execute(_GRANTS_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_REFUSE_SQL)
    op.execute(_DROP_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.1.2, verbatim.
_ENUM_SQL = """
CREATE TYPE sizing_mode         AS ENUM ('fixed_qty','fixed_notional','pct_equity','risk_based');
CREATE TYPE offset_unit         AS ENUM ('ticks','percent','r_multiple','atr');
"""

# 21-database-schema.md Sec.3.2.4, first block, verbatim.
_PROFILES_SQL = """
CREATE TABLE account_profiles (
  id                        uuid PRIMARY KEY,
  exchange_account_id       uuid NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
  name                      text NOT NULL,
  is_default                boolean NOT NULL DEFAULT false,
  enabled                   boolean NOT NULL DEFAULT true,
  trading_enabled           boolean NOT NULL DEFAULT false,
  version                   integer NOT NULL DEFAULT 1,
  leverage                  numeric(10,2) NOT NULL DEFAULT 1,
  margin_mode               text NOT NULL DEFAULT 'cross',
  position_mode             text NOT NULL DEFAULT 'one_way',
  sizing_mode               sizing_mode NOT NULL DEFAULT 'risk_based',
  size_fixed_qty            numeric(38,18),
  size_fixed_notional_usd   numeric(38,18),
  size_pct_equity           numeric(9,6),
  risk_pct_equity           numeric(9,6),
  risk_fixed_amount_usd     numeric(38,18),
  min_leg_notional_usd      numeric(38,18) NOT NULL DEFAULT 0,
  sl_offset_value           numeric(38,18) NOT NULL DEFAULT 10,
  sl_offset_unit            offset_unit NOT NULL DEFAULT 'ticks',
  sl_atr_period             smallint NOT NULL DEFAULT 14,
  sl_atr_multiple           numeric(10,4) NOT NULL DEFAULT 2,
  fallback_sl_offset_pct    numeric(9,6) NOT NULL DEFAULT 2,
  tp_offset_value           numeric(38,18),
  tp_offset_unit            offset_unit,
  tp_ladder                 jsonb,
  require_native_sl         boolean NOT NULL DEFAULT true,
  max_position_notional_usd numeric(38,18),
  max_position_pct_equity   numeric(9,6),
  max_daily_loss_usd        numeric(38,18),
  max_daily_loss_pct        numeric(9,6),
  max_open_positions        smallint,
  max_concurrent_orders     smallint,
  max_leverage_cap          numeric(10,2),
  max_orders_per_minute     smallint NOT NULL DEFAULT 30,
  all_symbols               boolean NOT NULL DEFAULT false,
  allowed_symbols           text[],
  blocked_symbols           text[],
  reduce_only_default       boolean NOT NULL DEFAULT false,
  time_in_force_default     text NOT NULL DEFAULT 'GTC',
  slippage_tolerance_bps    integer NOT NULL DEFAULT 10,
  created_by                uuid REFERENCES users(id) ON DELETE SET NULL,
  updated_by                uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now(),
  deleted_at                timestamptz,
  CONSTRAINT ap_leverage       CHECK (leverage BETWEEN 1 AND 100),
  CONSTRAINT ap_native_sl      CHECK (require_native_sl = true),
  CONSTRAINT ap_tif            CHECK (time_in_force_default IN ('GTC','IOC','FOK','PostOnly')),
  CONSTRAINT ap_slip           CHECK (slippage_tolerance_bps BETWEEN 0 AND 1000),
  CONSTRAINT ap_opm            CHECK (max_orders_per_minute BETWEEN 1 AND 600),
  CONSTRAINT ap_sl_pos         CHECK (sl_offset_value > 0),
  CONSTRAINT ap_tp_pair        CHECK ((tp_offset_value IS NULL) = (tp_offset_unit IS NULL)),
  CONSTRAINT ap_tp_pos         CHECK (tp_offset_value IS NULL OR tp_offset_value > 0),
  CONSTRAINT ap_maxpos         CHECK (max_open_positions IS NULL OR max_open_positions BETWEEN 1 AND 50),
  CONSTRAINT ap_sizing_shape   CHECK ((
      (sizing_mode = 'fixed_qty'       AND size_fixed_qty > 0          AND size_fixed_notional_usd IS NULL AND size_pct_equity IS NULL AND risk_pct_equity IS NULL AND risk_fixed_amount_usd IS NULL)
   OR (sizing_mode = 'fixed_notional'  AND size_fixed_notional_usd > 0 AND size_fixed_qty IS NULL          AND size_pct_equity IS NULL AND risk_pct_equity IS NULL AND risk_fixed_amount_usd IS NULL)
   OR (sizing_mode = 'pct_equity'      AND size_pct_equity > 0 AND size_pct_equity <= 100 AND size_fixed_qty IS NULL AND size_fixed_notional_usd IS NULL AND risk_pct_equity IS NULL AND risk_fixed_amount_usd IS NULL)
   OR (sizing_mode = 'risk_based'      AND size_fixed_qty IS NULL AND size_fixed_notional_usd IS NULL AND size_pct_equity IS NULL
       AND ((risk_pct_equity > 0 AND risk_pct_equity <= 100 AND risk_fixed_amount_usd IS NULL)
         OR (risk_fixed_amount_usd > 0 AND risk_pct_equity IS NULL)))
  ) IS TRUE),  -- a NULL size compares to NULL, which a bare CHECK would let pass
  CONSTRAINT ap_ladder_shape   CHECK (tp_ladder IS NULL OR jsonb_typeof(tp_ladder) = 'array'),
  CONSTRAINT ap_name           CHECK (char_length(name) BETWEEN 1 AND 80),
  CONSTRAINT ap_version        CHECK (version >= 1),
  CONSTRAINT ap_margin_mode    CHECK (margin_mode IN ('cross','isolated')),
  CONSTRAINT ap_position_mode  CHECK (position_mode IN ('one_way','hedge')),
  CONSTRAINT ap_sl_unit        CHECK (sl_offset_unit <> 'r_multiple'),
  CONSTRAINT ap_atr            CHECK (sl_atr_period BETWEEN 2 AND 200 AND sl_atr_multiple > 0),
  CONSTRAINT ap_fallback_sl    CHECK (fallback_sl_offset_pct > 0 AND fallback_sl_offset_pct < 100),
  CONSTRAINT ap_min_leg        CHECK (min_leg_notional_usd >= 0),
  CONSTRAINT ap_max_notional   CHECK (max_position_notional_usd IS NULL OR max_position_notional_usd > 0),
  CONSTRAINT ap_max_pos_pct    CHECK (max_position_pct_equity IS NULL OR (max_position_pct_equity > 0 AND max_position_pct_equity <= 100)),
  CONSTRAINT ap_daily_loss     CHECK (max_daily_loss_usd IS NULL OR max_daily_loss_usd > 0),
  CONSTRAINT ap_daily_loss_pct CHECK (max_daily_loss_pct IS NULL OR (max_daily_loss_pct > 0 AND max_daily_loss_pct <= 100)),
  CONSTRAINT ap_max_orders     CHECK (max_concurrent_orders IS NULL OR max_concurrent_orders BETWEEN 1 AND 500),
  CONSTRAINT ap_lev_cap        CHECK (max_leverage_cap IS NULL OR (max_leverage_cap BETWEEN 1 AND 100 AND leverage <= max_leverage_cap)),
  CONSTRAINT ap_trading_caps   CHECK (NOT trading_enabled OR (
        (max_position_notional_usd IS NOT NULL OR max_position_pct_equity IS NOT NULL)
    AND (max_daily_loss_usd IS NOT NULL OR max_daily_loss_pct IS NOT NULL)
    AND max_open_positions IS NOT NULL AND max_concurrent_orders IS NOT NULL AND max_leverage_cap IS NOT NULL)),
  CONSTRAINT ap_all_symbols    CHECK (NOT all_symbols OR allowed_symbols IS NULL),
  CONSTRAINT ap_finite         CHECK (
        leverage <> 'NaN' AND max_leverage_cap <> 'NaN' AND sl_atr_multiple <> 'NaN'
    AND size_fixed_qty <> 'NaN' AND size_fixed_notional_usd <> 'NaN' AND size_pct_equity <> 'NaN'
    AND risk_pct_equity <> 'NaN' AND risk_fixed_amount_usd <> 'NaN' AND min_leg_notional_usd <> 'NaN'
    AND sl_offset_value <> 'NaN' AND fallback_sl_offset_pct <> 'NaN' AND tp_offset_value <> 'NaN'
    AND max_position_notional_usd <> 'NaN' AND max_position_pct_equity <> 'NaN'
    AND max_daily_loss_usd <> 'NaN' AND max_daily_loss_pct <> 'NaN')  -- NaN passes a bound alone
);
CREATE UNIQUE INDEX ux_ap_name    ON account_profiles (exchange_account_id, lower(name)) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX ux_ap_default ON account_profiles (exchange_account_id) WHERE is_default AND deleted_at IS NULL;
"""

# 21-database-schema.md Sec.3.2.5, verbatim. Before the profile triggers, which write into it.
_REVISIONS_SQL = """
CREATE TABLE account_profile_revisions (
  id          bigserial PRIMARY KEY,
  profile_id  uuid NOT NULL,
  version     integer NOT NULL,
  payload     jsonb NOT NULL,
  changed_by  uuid REFERENCES users(id) ON DELETE SET NULL,
  changed_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT apr_version CHECK (version >= 1),
  CONSTRAINT apr_payload CHECK (jsonb_typeof(payload) = 'object'),
  CONSTRAINT ux_apr_version UNIQUE (profile_id, version)
);
CREATE TRIGGER trg_apr_append BEFORE UPDATE OR DELETE ON account_profile_revisions
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER trg_apr_no_truncate BEFORE TRUNCATE ON account_profile_revisions
  FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();
ALTER TABLE account_profile_revisions ENABLE ALWAYS TRIGGER trg_apr_append;
ALTER TABLE account_profile_revisions ENABLE ALWAYS TRIGGER trg_apr_no_truncate;
"""

# 21-database-schema.md Sec.3.2.4, second block, verbatim.
_PROFILE_TRIGGERS_SQL = """
CREATE FUNCTION ap_ladder_sum_check() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  IF NEW.tp_ladder IS NULL OR jsonb_typeof(NEW.tp_ladder) <> 'array' THEN
    RETURN NEW;  -- ap_ladder_shape refuses a non-array
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.tp_ladder) AS rung(v)
             WHERE CASE WHEN jsonb_typeof(rung.v) = 'object'
                         AND jsonb_typeof(rung.v -> 'pct') = 'number'
                         AND jsonb_typeof(rung.v -> 'r') = 'number'
                        THEN (rung.v ->> 'pct')::numeric <= 0 OR (rung.v ->> 'r')::numeric <= 0
                        ELSE true END) THEN
    RAISE EXCEPTION 'trg_ap_ladder_sum: every tp_ladder rung needs a number pct and r above 0'
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ap_ladder_sum';
  END IF;
  IF (SELECT sum((rung.v ->> 'pct')::numeric) FROM jsonb_array_elements(NEW.tp_ladder) AS rung(v)) > 100 THEN
    RAISE EXCEPTION 'trg_ap_ladder_sum: the tp_ladder pct values add up to more than the 100%% limit'
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ap_ladder_sum';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_ap_ladder_sum BEFORE INSERT OR UPDATE OF tp_ladder ON account_profiles
  FOR EACH ROW EXECUTE FUNCTION ap_ladder_sum_check();
ALTER TABLE account_profiles ENABLE ALWAYS TRIGGER trg_ap_ladder_sum;

CREATE FUNCTION ap_version_bump() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    NEW.version := 1;
    RETURN NEW;
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.exchange_account_id IS DISTINCT FROM OLD.exchange_account_id THEN
    RAISE EXCEPTION 'trg_ap_version: account_profiles.id and exchange_account_id are write-once (SR-E28-07)'
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ap_version';
  END IF;
  NEW.version := OLD.version + 1;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_ap_version BEFORE INSERT OR UPDATE ON account_profiles
  FOR EACH ROW EXECUTE FUNCTION ap_version_bump();
ALTER TABLE account_profiles ENABLE ALWAYS TRIGGER trg_ap_version;

CREATE TRIGGER trg_account_profiles_touch BEFORE UPDATE ON account_profiles
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE FUNCTION ap_record_revision() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  INSERT INTO public.account_profile_revisions (profile_id, version, payload, changed_by)
  VALUES (NEW.id, NEW.version, to_jsonb(NEW),
          CASE WHEN TG_OP = 'INSERT' THEN NEW.created_by ELSE NEW.updated_by END);
  RETURN NULL;
END $$;
REVOKE EXECUTE ON FUNCTION ap_record_revision() FROM PUBLIC;
CREATE TRIGGER trg_ap_revision AFTER INSERT OR UPDATE ON account_profiles
  FOR EACH ROW EXECUTE FUNCTION ap_record_revision();
ALTER TABLE account_profiles ENABLE ALWAYS TRIGGER trg_ap_revision;
"""

# 21-database-schema.md Sec.3.2.4, third block, verbatim.
_BOOTSTRAP_SQL = """
CREATE FUNCTION ea_default_profile() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  INSERT INTO public.account_profiles (id, exchange_account_id, name, is_default, risk_pct_equity, created_by, updated_by)
  VALUES (gen_random_uuid(), NEW.id, 'Default', true, 1, NEW.created_by, NEW.created_by);
  RETURN NULL;
END $$;
CREATE TRIGGER trg_ea_default_profile AFTER INSERT ON exchange_accounts
  FOR EACH ROW EXECUTE FUNCTION ea_default_profile();
ALTER TABLE exchange_accounts ENABLE ALWAYS TRIGGER trg_ea_default_profile;
"""

# The bootstrap for the accounts that exist already: the trigger's row, once per account. Seed
# rows only (Sec.9.3 rule 5); a few accounts in v1. Ordered so revision ids follow account age.
_BACKFILL_SQL = """
INSERT INTO account_profiles (id, exchange_account_id, name, is_default, risk_pct_equity, created_by, updated_by)
SELECT gen_random_uuid(), ea.id, 'Default', true, 1, ea.created_by, ea.created_by
FROM exchange_accounts ea ORDER BY ea.created_at, ea.id;
"""

# 0029's pattern for the revisions, and 0024's for the profiles (no DELETE: a profile leaves by
# soft delete); each REVOKE runs only where `pg_bootstrap.sql` made the role.
_GRANTS_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN
    EXECUTE 'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON account_profile_revisions FROM cv_app';
    EXECUTE 'REVOKE DELETE ON account_profiles FROM cv_app';
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_ro') THEN
    EXECUTE 'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON account_profile_revisions FROM cv_ro';
  END IF;
END
$BODY$;
"""

_REFUSE_SQL = """
LOCK TABLE account_profiles, account_profile_revisions IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM account_profiles WHERE version <> 1 OR name <> 'Default' OR NOT is_default)
     OR (SELECT count(*) FROM account_profile_revisions) <> (SELECT count(*) FROM account_profiles) THEN
    RAISE EXCEPTION '0037_account_profiles downgrade refused: a profile was created, edited or deleted after the bootstrap, and dropping the profile tables would lose that configuration and its append-only history. Fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
"""

_DROP_SQL = """
DROP TRIGGER trg_ea_default_profile ON exchange_accounts;
DROP FUNCTION ea_default_profile();
DROP TABLE account_profiles;
DROP FUNCTION ap_record_revision();
DROP FUNCTION ap_version_bump();
DROP FUNCTION ap_ladder_sum_check();
DROP TABLE account_profile_revisions;
DROP TYPE offset_unit;
DROP TYPE sizing_mode;
"""
