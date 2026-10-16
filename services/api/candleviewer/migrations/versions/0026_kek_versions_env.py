"""kek_versions: one KEK lineage per environment, keyed (env, version) (#2338, KV-E04)

Revision ID: 0026_kek_versions_env
Revises: 0025_settings

The Alembic queue is 0023 (#2516), 0024 (#2614), 0025 (#2680), then this revision (C-5.3, single
head).

The KEK lineage was global while custody follows the process environment, so a demo or testnet
process on the shared database had to hold the KEK of every live DEK, under non-live custody,
and could stop live boots by enrolling a newer version (E27 threat model F-03). Now:

* `env exchange_env NOT NULL` is added with the constant default `'demo'` (§9.3 rule 2 fast
  path) and the default is dropped at once, so every later insert names its environment.
  Existing rows join `demo`, never `live`: nothing shows that a KCV enrolled before #2338 was
  loaded under live custody. The first live boot afterwards enrols a fresh live lineage (KV-S03,
  procedural check SR-E27-15).
* The primary key becomes `(env, version)`: versions are numbered per environment, each lineage
  from 1. `kv_kcv_unique UNIQUE (kcv)` stays global, so one KEK is never enrolled in two
  environments; `kv_version_pos` and `kv_kcv_len` are unchanged.
* The upgrade refuses while any `api_keys` row is usable (`revoked_at IS NULL AND status <>
  'revoked'`). Those rows hold environment-free `v1:` wraps, which M2 refuses after #2338, and a
  migration never holds the KEK to re-wrap them (ADR-0009 Amendment 1). Revoke them first, as
  `docs/ops/runbooks/kek-custody.md` describes. No deployment holds such rows today.
* Reversible (C-5.2) while no version is enrolled under two environments. Otherwise the
  downgrade refuses: one `version` key cannot hold two lineages.

Not backward compatible for one release: M2 before #2338 cannot enrol into this table (its
`ON CONFLICT (version)` matches no constraint, so it fails closed with `kcv_store_unavailable`) and
would read the rows as one lineage again, so a code rollback needs this downgrade first.
`lock_timeout` (5 s) bounds every lock wait on this table of a handful of rows (C-5.6).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0026_kek_versions_env"
down_revision: str | None = "0025_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_GUARD = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT FROM api_keys WHERE revoked_at IS NULL AND status <> 'revoked') THEN
    RAISE EXCEPTION '0026_kek_versions_env upgrade refused: usable api_keys rows hold v1 KEK wraps that a migration cannot re-wrap; revoke them first (docs/ops/runbooks/kek-custody.md, "Upgrading to per-environment KEK lineages")';
  END IF;
END $BODY$;
"""

_UPGRADE = """
ALTER TABLE kek_versions ADD COLUMN env exchange_env NOT NULL DEFAULT 'demo';
ALTER TABLE kek_versions ALTER COLUMN env DROP DEFAULT;
ALTER TABLE kek_versions DROP CONSTRAINT kek_versions_pkey;
ALTER TABLE kek_versions ADD CONSTRAINT kek_versions_pkey PRIMARY KEY (env, version);
"""

_DOWNGRADE_GUARD = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT FROM kek_versions GROUP BY version HAVING count(*) > 1) THEN
    RAISE EXCEPTION '0026_kek_versions_env downgrade refused: a KEK version is enrolled under two environments';
  END IF;
END $BODY$;
"""

_DOWNGRADE = """
ALTER TABLE kek_versions DROP CONSTRAINT kek_versions_pkey;
ALTER TABLE kek_versions ADD CONSTRAINT kek_versions_pkey PRIMARY KEY (version);
ALTER TABLE kek_versions DROP COLUMN env;
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_UPGRADE_GUARD)
    op.execute(_UPGRADE)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DOWNGRADE_GUARD)
    op.execute(_DOWNGRADE)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")
