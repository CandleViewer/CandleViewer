"""indicator_presets and the 18 built-in presets (E13-T03, #427)

Revision ID: 0040_indicator_presets
Revises: 0039_trade_groups
Create Date: 2026-10-20

Purely additive (C-5.1). DDL mirrors `docs/plan/21-database-schema.md` Sec.3.8.4 (the register's
`0011_workspace`: number 0011 was taken, so `indicator_presets` ships alone, as `drawings` did in
0021). Documented additions, each in Sec.3.8.4 as amended by this PR (ruling Q5):

* `ip_builtin_owner`: a built-in has no owner and every other preset has one, the twin of
  `chart_templates.ct_builtin_owner` (Sec.3.8.2).
* `ip_params_shape` / `ip_style_shape`: each is a JSON object of at most 4096 bytes as Postgres
  prints jsonb, the DB half of SR-E13-06 (E13 threat model IR-33); the API measures the same text.
* `ip_name_len`: 1..80 characters, the API's `name` bound.

Seed (21 Sec.10.5): the 18 built-ins with `owner_user_id` NULL and `is_builtin` true, inserted
`ON CONFLICT DO NOTHING` under ids frozen here (uuid5 of `<code>/<name>`, recomputed by
`candleviewer/db/builtin_indicator_presets.py` and its test), so a re-run inserts nothing and
changes no `updated_at`. `db/seed.py` re-runs the same rows the same way.

* One CREATE TABLE under `lock_timeout = 5s` (C-5.6): the `users` foreign key takes a SHARE ROW
  EXCLUSIVE lock on `users` for the transaction, which then waits at most 5 s.
* No GRANT: `cv_app` holds table-level DML from the default privileges in
  `infra/scripts/pg_bootstrap.sql`. No column holds a credential, token or PII (Sec.12, P0).
* The downgrade locks the table and refuses while any user preset exists, a soft-deleted one
  included (dropping it would lose a user's data); the built-ins alone never block it, so
  `downgrade base` then `upgrade head` runs on a seeded database.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0040_indicator_presets"
down_revision: str | None = "0039_trade_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_UPGRADE_SQL)
    op.execute(_SEED_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DOWNGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.8.4, verbatim, plus the four CHECKs it lists after the first two.
_UPGRADE_SQL = """
CREATE TABLE indicator_presets (
  id             uuid PRIMARY KEY,
  owner_user_id  uuid REFERENCES users(id) ON DELETE CASCADE,   -- NULL = built-in
  indicator_code text NOT NULL,
  name           text NOT NULL,
  params         jsonb NOT NULL DEFAULT '{}'::jsonb,
  style          jsonb NOT NULL DEFAULT '{}'::jsonb,
  pane_target    text NOT NULL DEFAULT 'overlay',  -- overlay | subpane
  is_builtin     boolean NOT NULL DEFAULT false,
  is_favourite   boolean NOT NULL DEFAULT false,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  deleted_at     timestamptz,
  CONSTRAINT ip_target CHECK (pane_target IN ('overlay','subpane')),
  CONSTRAINT ip_code   CHECK (indicator_code ~ '^[a-z0-9_]{2,32}$'),
  CONSTRAINT ip_builtin_owner CHECK ((is_builtin = true AND owner_user_id IS NULL) OR (is_builtin = false AND owner_user_id IS NOT NULL)),
  CONSTRAINT ip_name_len CHECK (char_length(name) BETWEEN 1 AND 80),
  CONSTRAINT ip_params_shape CHECK (jsonb_typeof(params) = 'object' AND octet_length(params::text) <= 4096),
  CONSTRAINT ip_style_shape  CHECK (jsonb_typeof(style) = 'object' AND octet_length(style::text) <= 4096)
);
CREATE UNIQUE INDEX ux_ip_name ON indicator_presets (coalesce(owner_user_id,'00000000-0000-0000-0000-000000000000'::uuid), indicator_code, lower(name)) WHERE deleted_at IS NULL;
CREATE INDEX ix_ip_fav ON indicator_presets (owner_user_id) WHERE is_favourite AND deleted_at IS NULL;
"""

# 21 Sec.10.5, in its order (`\u03c3` is the Greek small sigma, Python-escaped for RUF001).
# Frozen: a later change to a built-in is a new revision (C-5.4).
_SEED_SQL = """
INSERT INTO indicator_presets (id, owner_user_id, indicator_code, name, params, style, pane_target, is_builtin, is_favourite) VALUES
  ('a9f5bf39-b784-5aaa-ba89-44913e44e85c', NULL, 'ema', 'ema(9)', '{"n": 9}', '{}', 'overlay', true, false),
  ('3b3dc488-4d3c-5e9c-aad0-ea73d0029699', NULL, 'ema', 'ema(21)', '{"n": 21}', '{}', 'overlay', true, false),
  ('2d9df74b-d718-5a1c-bd57-3cafd116d80a', NULL, 'ema', 'ema(50)', '{"n": 50}', '{}', 'overlay', true, false),
  ('515e3c5f-8504-5eef-8838-e005c5dda3bb', NULL, 'ema', 'ema(200)', '{"n": 200}', '{}', 'overlay', true, false),
  ('d4aaf9d5-6223-57c7-bba8-d2af49f40789', NULL, 'vwap', 'vwap(session)', '{"anchor": "session"}', '{}', 'overlay', true, false),
  ('9e84cbef-4759-5e1e-9b5d-3138046688af', NULL, 'vwap', 'vwap(session, ±1\u03c3, ±2\u03c3)', '{"anchor": "session"}', '{}', 'overlay', true, false),
  ('dee545ed-f288-5b06-b413-0beb58f12ebe', NULL, 'atr', 'atr(14)', '{"n": 14}', '{}', 'subpane', true, false),
  ('2dd34f1a-bc9d-5d6a-b9e5-0ce33f0df45d', NULL, 'cvd', 'cvd(session reset)', '{"anchor": "session"}', '{}', 'subpane', true, false),
  ('2c75f7dc-337b-51f9-87fe-b56e34faf492', NULL, 'cvd', 'cvd(never reset)', '{"anchor": "since_load"}', '{}', 'subpane', true, false),
  ('16875d45-7f91-5432-a146-600fc2ba5640', NULL, 'delta', 'delta(bar)', '{}', '{}', 'subpane', true, false),
  ('58d4656b-50aa-5d07-bcfd-7eb06427a64b', NULL, 'volume_profile', 'volume_profile(VA 70 %, session)', '{}', '{}', 'overlay', true, false),
  ('165600be-0b5c-5fb8-b294-047e75226993', NULL, 'delta_profile', 'delta_profile(VA 70 %)', '{}', '{}', 'overlay', true, false),
  ('9ce21029-22bc-590a-9eb7-066fbc73bc14', NULL, 'oi', 'oi(absolute)', '{}', '{}', 'subpane', true, false),
  ('d2aa8e19-11dc-5ebb-a0d8-79a7e0f0877b', NULL, 'oi', 'oi(delta per bar)', '{}', '{}', 'subpane', true, false),
  ('fa1acea8-1f00-59d4-87a6-6a75de3acc0c', NULL, 'funding', 'funding(annualised)', '{}', '{}', 'subpane', true, false),
  ('b7c139b9-aa44-56c7-98d8-c9a26046efd3', NULL, 'speed_of_tape', 'speed_of_tape(5 s)', '{}', '{}', 'subpane', true, false),
  ('76b18b62-2548-56db-854b-8c630a03c265', NULL, 'imbalance_tracker', 'imbalance_tracker(300 %, stack 3)', '{}', '{}', 'overlay', true, false),
  ('5a4d54b7-38fc-5cb4-8f03-60d16690d51b', NULL, 'market_regime', 'market_regime(default)', '{}', '{}', 'subpane', true, false)
ON CONFLICT DO NOTHING;
"""

_DOWNGRADE_SQL = """
LOCK TABLE indicator_presets IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM indicator_presets WHERE NOT is_builtin OR owner_user_id IS NOT NULL) THEN
    RAISE EXCEPTION '0040_indicator_presets downgrade refused: indicator_presets holds user presets (soft-deleted ones included), which dropping the table would lose. Fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
DROP TABLE IF EXISTS indicator_presets;
"""
