"""exchange_accounts: the stored-key self-check's durable policy disarm (#836 slice 2d)

Revision ID: 0031_policy_disarm
Revises: 0030_auth_keys
Create Date: 2026-10-18

Purely additive (C-5.1): three nullable columns with no default (no rewrite, Sec.9.3 rule 2) and
two named CHECKs, `docs/plan/21-database-schema.md` Sec.3.2.1 verbatim. The self-check's disarm
sets `trading_enabled` false with the failing rule's code and time in one conditional update, so
the force-disable and its reason commit together; `policy_disarm_audited_at` is set once the
disarm's `account.disabled_by_policy` record is written, so a record still owed outlives a restart
(decisions 2 and 5 on #836). `ea_disarm_code_fmt` admits a code only (the job's `_CODE`), never
message text; `ea_disarm_shape` pairs the code with its time and marks only a disarm.

* No column can hold a credential, token or PII (Sec.12, class P0), so none carries a
  classification comment.
* No GRANT: `cv_app` holds table-level DML on `exchange_accounts` from the default privileges in
  `infra/scripts/pg_bootstrap.sql`, which covers added columns (0009 precedent).
* One ALTER TABLE under `lock_timeout = 5s` (C-5.6): its ACCESS EXCLUSIVE lock waits at most 5 s,
  and the CHECKs validate a table of a handful of rows whose new columns are all NULL.
* The downgrade locks the table and refuses while a disarm's record is still owed: dropping the
  columns would lose it (C-2.9). Otherwise it drops the constraints and the columns; every record
  already written keeps its rule code in the audit log.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0031_policy_disarm"
down_revision: str | None = "0030_auth_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_UPGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DOWNGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.2.1, verbatim.
_UPGRADE_SQL = """
ALTER TABLE exchange_accounts
  ADD COLUMN policy_disarm_code       text,
  ADD COLUMN policy_disarmed_at       timestamptz,
  ADD COLUMN policy_disarm_audited_at timestamptz,
  ADD CONSTRAINT ea_disarm_code_fmt CHECK (policy_disarm_code ~ '^[a-z0-9_]{1,40}$'),
  ADD CONSTRAINT ea_disarm_shape CHECK (
    (policy_disarm_code IS NULL) = (policy_disarmed_at IS NULL)
    AND (policy_disarm_audited_at IS NULL OR policy_disarmed_at IS NOT NULL)
  );
"""

_DOWNGRADE_SQL = """
LOCK TABLE exchange_accounts IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM exchange_accounts
             WHERE policy_disarmed_at IS NOT NULL AND policy_disarm_audited_at IS NULL) THEN
    RAISE EXCEPTION '0031_policy_disarm downgrade refused: an account disarmed by the stored-key self-check is still owed its account.disabled_by_policy audit record, which dropping these columns would lose (C-2.9). Start cv-api so its self-check sends the record, then retry, or fix forward with a new revision instead (C-5.2); never mark the record written in SQL';
  END IF;
END $BODY$;
ALTER TABLE exchange_accounts
  DROP CONSTRAINT ea_disarm_shape,
  DROP CONSTRAINT ea_disarm_code_fmt,
  DROP COLUMN policy_disarm_audited_at,
  DROP COLUMN policy_disarmed_at,
  DROP COLUMN policy_disarm_code;
"""
