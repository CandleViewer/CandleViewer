"""risk_lockouts + risk_policy + kill_switch_state (E39-T02 #882)

Revision ID: 0038_risk_state
Revises: 0037_account_profiles
Create Date: 2026-10-20

Purely additive (C-5.1). The three tables, their named CHECKs, both unique indexes, the
classification comment and the seed rows are `docs/plan/21-database-schema.md` Sec.3.11 verbatim:
the *state* E39 produces (active and released lockouts, the global risk policy, the kill switch per
target), where Sec.3.2.4 and Sec.3.1.3 already hold its *inputs*. Bounds mirror
`22-api-openapi.yaml` `RiskCaps` and `SetKillSwitchRequest`, so the database refuses a value the
API would accept only through a bug.

* Deviations from the ticket text, each argued in the PR: `until` is the absolute end B20 computes
  when a lockout opens (INV-B20-d), NULL meaning "never released by a clock" (INV-B20-e), not
  "until the day boundary"; the two unique indexes use `NULLS NOT DISTINCT` (Postgres 15+) instead
  of a `coalesce` to a sentinel uuid; the hot-path probe uses `ux_risk_lockout_active` (same
  predicate, leading column) instead of a second, redundant partial index; no audit or
  `system_events` row is written here: the audit writer owns the hash chain and no revision
  writes either table.
* `risk_lockouts.actual_value` is class P1 (Sec.12, financial data of the account, as the
  monetary columns of `positions`), so it carries a `PII:` comment that the model mirrors. No
  other column can hold a credential, token or PII; the free-text reasons are operator text, as
  `feature_flag_overrides.reason`.
* Seed rows only (Sec.9.3 rule 5), one named constant: the policy singleton with every limit set
  (the interim defaults ruled on #2701; `updated_by` NULL until the Owner saves SCR-134) and the
  disengaged `global` kill-switch row, so a reader can tell "never engaged" from "no state".
* `risk_policy.override_extra_loss_max_usd` (default 0) is the bound of an override's loss
  allowance (E39-X01 D-4, decided on #2701); the allowance and grace columns are E39-S02's.
* No triggers: the services set `updated_at` (0022/0025 precedent). `cv_app` keeps INSERT, SELECT
  and UPDATE from the default privileges in `infra/scripts/pg_bootstrap.sql`; DELETE is revoked on
  the three tables where the role exists (0024 idiom), since a release updates and never deletes.
* Both `upgrade()` and `downgrade()` bracket their statements with `SET LOCAL lock_timeout =
  '5s'` (0019/0022/0025/0027 pattern, C-5.6): the FKs take a SHARE ROW EXCLUSIVE lock on
  `exchange_accounts` and `users` on the way in and the drops an ACCESS EXCLUSIVE one on the way
  out, so each wait is bounded instead of queueing logins and order entry.
* Downgrade locks the three tables and refuses while any of them holds more than its seed: a
  lockout row (evidence, kept indefinitely), a kill-switch row other than the never-engaged global
  one, or a policy written by a person (`updated_by` set). Otherwise it drops the three tables.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0038_risk_state"
down_revision: str | None = "0037_account_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_TABLES_SQL)
    op.execute(_INTERIM_POLICY_SEED_SQL)
    op.execute(_REVOKE_DELETE)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DOWNGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.11, first block (the three tables and both indexes), verbatim.
_TABLES_SQL = """
CREATE TABLE risk_lockouts (
  id                  uuid PRIMARY KEY,
  exchange_account_id uuid NOT NULL REFERENCES exchange_accounts(id) ON DELETE RESTRICT,
  user_id             uuid REFERENCES users(id) ON DELETE RESTRICT,  -- NULL: the whole account; set: one manager
  reason              text NOT NULL,           -- RiskSummary.accounts[].lockout.reason
  threshold           numeric(38,18),          -- the limit that was breached
  actual_value        numeric(38,18),          -- the measured value that breached it
  since               timestamptz NOT NULL DEFAULT now(),
  until               timestamptz,             -- absolute end (B20 compute_until); NULL: never released by a clock
  released_at         timestamptz,
  released_by         uuid REFERENCES users(id) ON DELETE RESTRICT,  -- with release_reason: a person's release
  release_reason      text,                    -- the override's reason, operator free text
  actions_taken       jsonb NOT NULL DEFAULT '{}'::jsonb,  -- counts, 24 §8.11
  CONSTRAINT rl_reason   CHECK (reason IN ('daily_loss','consecutive_losses','max_positions','manual')),
  CONSTRAINT rl_manual   CHECK (reason <> 'manual' OR until IS NULL),
  CONSTRAINT rl_until    CHECK (until IS NULL OR until > since),
  CONSTRAINT rl_released CHECK (released_at IS NULL OR released_at >= since),
  CONSTRAINT rl_release  CHECK ((released_at IS NULL AND released_by IS NULL AND release_reason IS NULL)
                                OR (released_at IS NOT NULL AND released_by IS NOT NULL
                                    AND release_reason IS NOT NULL)
                                OR (released_at IS NOT NULL AND released_by IS NULL AND release_reason IS NULL
                                    AND until IS NOT NULL AND released_at >= until)),
  CONSTRAINT rl_text     CHECK (release_reason IS NULL OR (char_length(release_reason) <= 280
                                                           AND char_length(btrim(release_reason, E' \\t\\r\\n')) >= 3)),
  CONSTRAINT rl_numbers  CHECK (threshold <> 'NaN'::numeric AND actual_value <> 'NaN'::numeric),
  CONSTRAINT rl_actions  CHECK (jsonb_typeof(actions_taken) = 'object')
);
CREATE UNIQUE INDEX ux_risk_lockout_active ON risk_lockouts (exchange_account_id, user_id) NULLS NOT DISTINCT
  WHERE released_at IS NULL;
COMMENT ON COLUMN risk_lockouts.actual_value IS
  'PII: financial data of the account (a measured loss), as positions; never sent to third parties';

CREATE TABLE risk_policy (
  id                              uuid PRIMARY KEY,
  singleton                       boolean NOT NULL DEFAULT true UNIQUE,
  max_total_notional_usd          numeric(38,18) NOT NULL,
  max_daily_loss_usd              numeric(38,18) NOT NULL,
  max_drawdown_pct                numeric(9,6) NOT NULL,
  max_open_positions              smallint NOT NULL,
  max_leverage                    numeric(10,2) NOT NULL,
  max_orders_per_minute           smallint NOT NULL,
  per_symbol_concentration_pct    numeric(9,6) NOT NULL,
  override_extra_loss_max_usd     numeric(38,18) NOT NULL DEFAULT 0,  -- E39-X01 D-4: an override's largest allowance
  breach_behaviour                jsonb NOT NULL,     -- one 'warn' | 'block' | 'flatten' per limit, 24 §8.11
  lockout_minutes_default         smallint NOT NULL DEFAULT 60,
  block_trading_when_degraded     boolean NOT NULL DEFAULT true,
  day_boundary_utc_offset_minutes smallint NOT NULL DEFAULT 0,
  updated_by                      uuid REFERENCES users(id) ON DELETE RESTRICT,  -- NULL: never owner-confirmed
  updated_at                      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT rp_singleton CHECK (singleton),
  CONSTRAINT rp_money     CHECK (max_total_notional_usd >= 0 AND max_daily_loss_usd >= 0
                                 AND override_extra_loss_max_usd >= 0
                                 AND max_total_notional_usd <> 'NaN'::numeric
                                 AND max_daily_loss_usd <> 'NaN'::numeric
                                 AND override_extra_loss_max_usd <> 'NaN'::numeric),
  CONSTRAINT rp_pct       CHECK (max_drawdown_pct BETWEEN 0 AND 100
                                 AND per_symbol_concentration_pct BETWEEN 0 AND 100),
  CONSTRAINT rp_positions CHECK (max_open_positions BETWEEN 0 AND 100),
  CONSTRAINT rp_leverage  CHECK (max_leverage BETWEEN 1 AND 100),
  CONSTRAINT rp_orders    CHECK (max_orders_per_minute BETWEEN 1 AND 600),
  CONSTRAINT rp_lockout   CHECK (lockout_minutes_default BETWEEN 0 AND 1440),
  CONSTRAINT rp_day       CHECK (day_boundary_utc_offset_minutes BETWEEN -720 AND 840),
  CONSTRAINT rp_behaviour CHECK (jsonb_typeof(breach_behaviour) = 'object'
                                 AND breach_behaviour ?& ARRAY['max_total_notional_usd','max_daily_loss_usd','max_drawdown_pct','max_open_positions',
                                                 'max_leverage','max_orders_per_minute','per_symbol_concentration_pct']
                                 AND breach_behaviour - ARRAY['max_total_notional_usd','max_daily_loss_usd','max_drawdown_pct','max_open_positions',
                                                 'max_leverage','max_orders_per_minute','per_symbol_concentration_pct'] = '{}'::jsonb
                                 AND NOT jsonb_path_exists(breach_behaviour,
                                   'strict $.* ? (@.type() != "string" || (@ != "warn" && @ != "block" && @ != "flatten"))'))
);

CREATE TABLE kill_switch_state (
  id                  uuid PRIMARY KEY,
  scope               text NOT NULL,
  exchange_account_id uuid REFERENCES exchange_accounts(id) ON DELETE RESTRICT,
  engaged             boolean NOT NULL,
  engaged_at          timestamptz,
  engaged_by          uuid REFERENCES users(id) ON DELETE RESTRICT,  -- NULL on an engaged row: automatic
  reason              text,
  options             jsonb NOT NULL DEFAULT '{}'::jsonb,  -- SetKillSwitchRequest options, 24 §8.11
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT kss_scope   CHECK (scope IN ('global','accounts')),
  CONSTRAINT kss_target  CHECK ((scope = 'global') = (exchange_account_id IS NULL)),
  CONSTRAINT kss_engaged CHECK (NOT engaged OR (engaged_at IS NOT NULL AND reason IS NOT NULL)),
  CONSTRAINT kss_reason  CHECK (reason IS NULL OR (char_length(reason) <= 280
                                                   AND char_length(btrim(reason, E' \\t\\r\\n')) >= 3)),
  CONSTRAINT kss_options CHECK (jsonb_typeof(options) = 'object')
);
CREATE UNIQUE INDEX ux_kill_switch_state_scope ON kill_switch_state (scope, exchange_account_id) NULLS NOT DISTINCT;
"""

# 21-database-schema.md Sec.3.11, second block (the seed), verbatim: the interim policy ruled on #2701
# (every limit set, `breach_behaviour` `block`, `updated_by` NULL = never owner-confirmed) and the
# never-engaged global kill-switch row. Its numbers live here and nowhere else in the revision.
_INTERIM_POLICY_SEED_SQL = """
INSERT INTO risk_policy (id, max_total_notional_usd, max_daily_loss_usd, max_drawdown_pct, max_open_positions,
                         max_leverage, max_orders_per_minute, per_symbol_concentration_pct, breach_behaviour)
VALUES (gen_random_uuid(), 10000, 250, 5, 3, 5, 30, 50,
        '{"max_total_notional_usd": "block", "max_daily_loss_usd": "block", "max_drawdown_pct": "block",
          "max_open_positions": "block", "max_leverage": "block", "max_orders_per_minute": "block",
          "per_symbol_concentration_pct": "block"}'::jsonb);
INSERT INTO kill_switch_state (id, scope, engaged) VALUES (gen_random_uuid(), 'global', false);
"""

# Runs only where `pg_bootstrap.sql` created `cv_app` (0024 idiom). A release updates its row and
# nothing deletes one, so the runtime role keeps no DELETE; dropping a table drops its grants, so
# the downgrade re-grants nothing. Static literal: SQL built at runtime trips bandit B608.
_REVOKE_DELETE = (
    "DO $BODY$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN "
    "EXECUTE 'REVOKE DELETE ON risk_lockouts, risk_policy, kill_switch_state FROM cv_app'; "
    "END IF; END $BODY$;"
)

_DOWNGRADE_SQL = """
LOCK TABLE risk_lockouts, risk_policy, kill_switch_state IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM risk_lockouts)
     OR EXISTS (SELECT 1 FROM kill_switch_state
                WHERE scope <> 'global' OR engaged OR engaged_at IS NOT NULL)
     OR EXISTS (SELECT 1 FROM risk_policy WHERE updated_by IS NOT NULL) THEN
    RAISE EXCEPTION '0038_risk_state downgrade refused: risk state exists beyond the seed (a lockout row, an engaged or account kill-switch row, or a policy written by a person). It is part of the accountability trail and retained indefinitely (21-database-schema.md Sec.3.11): export it, delete it deliberately, and retry';
  END IF;
END $BODY$;
DROP TABLE kill_switch_state;
DROP TABLE risk_policy;
DROP TABLE risk_lockouts;
"""
