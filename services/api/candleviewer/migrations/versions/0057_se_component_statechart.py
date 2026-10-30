"""`statechart` in system_events.se_component (E42-T07 #1025)

Revision ID: 0057_se_component_statechart
Revises: 0056_sessions_lock_state
Create Date: 2026-10-29

`22` `listStatecharts`: a snapshot whose HMAC seal does not verify writes one `system_events` row
with component `statechart`, so it shows in `listIncidents`. 0008's `se_component` does not admit
that component, so this revision widens it (`21-database-schema.md` Sec.3.10.2). `incidents`
needs nothing: its `component` copies the closed one and carries no CHECK (Sec.3.10.2a).

* Additive (C-5.1): the CHECK admits one more value; every existing row passes it. It is replaced
  `NOT VALID` and validated in its own statement, so the scan of existing rows holds SHARE UPDATE
  EXCLUSIVE, not ACCESS EXCLUSIVE (C-5.6), as 0054 widened `lp_kind`.
* `lock_timeout = 5s` both ways (C-5.6): the ALTER waits at most 5 s for its lock.
* No GRANT and no new column: no credential, token or PII (Sec.12, P0).
* Reversible (C-5.2): the downgrade locks the table and refuses while any `statechart` row exists
  (0008's CHECK cannot hold it, and deleting an operational record to fit it is not a rollback);
  otherwise it restores 0008's 14 values.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0057_se_component_statechart"
down_revision: str | None = "0056_sessions_lock_state"
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


# 21-database-schema.md Sec.3.10.2, the 0057 block, verbatim.
_UPGRADE_SQL = """
ALTER TABLE system_events
  DROP CONSTRAINT se_component,
  ADD CONSTRAINT se_component CHECK (component IN ('ingestion','book_engine','bars','orderflow','oms','rules','recorder','replay','api','ws','db','exchange','auth','backup','statechart')) NOT VALID;
ALTER TABLE system_events VALIDATE CONSTRAINT se_component;
"""

# The refusal, then 0008's `se_component` (verbatim but for NOT VALID and its validation).
_DOWNGRADE_SQL = """
LOCK TABLE system_events IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM system_events WHERE component = 'statechart') THEN
    RAISE EXCEPTION '0057_se_component_statechart downgrade refused: system_events holds statechart rows, which the earlier se_component cannot hold. Fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
ALTER TABLE system_events
  DROP CONSTRAINT se_component,
  ADD CONSTRAINT se_component CHECK (component IN ('ingestion','book_engine','bars','orderflow','oms','rules','recorder','replay','api','ws','db','exchange','auth','backup')) NOT VALID;
ALTER TABLE system_events VALIDATE CONSTRAINT se_component;
"""
