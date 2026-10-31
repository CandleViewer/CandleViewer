"""`alerts.disarm_reason` (E40-S01, E40-D02 CC-3)

Revision ID: 0059_alerts_disarm_reason
Revises: 0058_oms_handovers
Create Date: 2026-10-31

The evaluator disarms an alert whose metric source is lost (`enabled = false`) and says why only in
a delivery context. The Alerts centre must show that reason on the row, so it is kept on the alert.

* Additive (C-5.1, C-5.6): one nullable column, no default, no rewrite; the CHECK admits NULL and the
  one reason the evaluator writes (`source_unavailable`), so every existing row passes it.
* Reversible (C-5.2): the downgrade drops the CHECK and the column; the reason is derived data (the
  disarm delivery keeps it), so nothing is lost that cannot be re-read.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0059_alerts_disarm_reason"
down_revision: str | None = "0058_oms_handovers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute("ALTER TABLE alerts ADD COLUMN disarm_reason text;")
    op.execute(
        "ALTER TABLE alerts ADD CONSTRAINT al_disarm_reason "
        "CHECK (disarm_reason IS NULL OR disarm_reason IN ('source_unavailable'));"
    )
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute("ALTER TABLE alerts DROP CONSTRAINT al_disarm_reason;")
    op.execute("ALTER TABLE alerts DROP COLUMN disarm_reason;")
    op.execute("SET LOCAL lock_timeout = DEFAULT;")
