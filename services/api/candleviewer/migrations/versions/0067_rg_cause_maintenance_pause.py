"""`maintenance_pause` in recording_gaps.rg_cause (#5629)

Revision ID: 0067_rg_cause_maintenance_pause
Revises: 0064_orders_origin
Create Date: 2026-11-03

Maintenance mode with `keep_recorder = false` holds the recorder's capture (`24` Sec.13.3): the
paused interval is a gap, but none of 0011's causes names an operator-requested hold
(`ws_disconnect`, `backpressure_drop`, `process_restart`, `seq_jump`, `exchange_outage` all name a
fault). This revision widens `rg_cause` by one value (`21-database-schema.md` Sec.3.6.2).

* Slot 0067 is provisional (orchestrator ruling on #5629): re-parent `down_revision` onto
  whatever revision lands first (C-5.3).
* Additive (C-5.1): the CHECK admits one more value; every existing row passes it. It is replaced
  `NOT VALID` and validated in its own statement, so the scan of existing rows holds SHARE UPDATE
  EXCLUSIVE, not ACCESS EXCLUSIVE (C-5.6), as 0057 widened `se_component`.
* `lock_timeout = 5s` both ways (C-5.6): the ALTER waits at most 5 s for its lock.
* No GRANT and no new column: no credential, token or PII (Sec.12).
* Reversible (C-5.2): the downgrade locks the table and refuses while any `maintenance_pause` row
  exists (0011's CHECK cannot hold it, and deleting a coverage record to fit it is not a
  rollback); otherwise it restores 0011's five values.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0067_rg_cause_maintenance_pause"
down_revision: str | None = "0064_orders_origin"
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


# 21-database-schema.md Sec.3.6.2, the 0067 block, verbatim.
_UPGRADE_SQL = """
ALTER TABLE recording_gaps
  DROP CONSTRAINT rg_cause,
  ADD CONSTRAINT rg_cause CHECK (cause IN ('ws_disconnect','backpressure_drop','process_restart','seq_jump','exchange_outage','maintenance_pause')) NOT VALID;
ALTER TABLE recording_gaps VALIDATE CONSTRAINT rg_cause;
"""

# The refusal, then 0011's `rg_cause` (verbatim but for NOT VALID and its validation).
_DOWNGRADE_SQL = """
LOCK TABLE recording_gaps IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM recording_gaps WHERE cause = 'maintenance_pause') THEN
    RAISE EXCEPTION '0067_rg_cause_maintenance_pause downgrade refused: recording_gaps holds maintenance_pause rows, which the earlier rg_cause cannot hold. Fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
ALTER TABLE recording_gaps
  DROP CONSTRAINT rg_cause,
  ADD CONSTRAINT rg_cause CHECK (cause IN ('ws_disconnect','backpressure_drop','process_restart','seq_jump','exchange_outage')) NOT VALID;
ALTER TABLE recording_gaps VALIDATE CONSTRAINT rg_cause;
"""
