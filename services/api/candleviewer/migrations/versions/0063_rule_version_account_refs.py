"""rule_versions: the account references a version's IR names, for the scoped reads (#2291)

Revision ID: 0063_rule_version_account_refs
Revises: 0061_password_history
Create Date: 2026-10-31

`rule_versions.account_refs`, nullable `text[]` with no default: the accounts a version's IR names
anywhere (its scope, metric references and action parameters), as the generic walker reads them
(`candleviewer.rules.ir.accounts.collect_account_ids`), the walker the reading rule
(`RulesManager._visible`) reads. SR-051 (`04-security-program.md` Sec.6.4): the scope is part of
the query, so `GET /rules`, a rule's reads by id and `GET /notifications`' rule ids read a
non-Owner caller's own rules only while every version's set lies within the caller's grants, in
the statement itself (`rules_store_pg.py`). The store writes the set with each version it saves.

* NULL means not yet computed, and no non-Owner read scope admits a version holding NULL. The store
  fills the versions saved before this revision from their stored IR with the same walker, in
  bounded batches and only where the column is still NULL, before its first grant-scoped read in
  a process; the Owner role's reads and the save's name check never read the column. The fill runs
  once per process, so a NULL written afterwards (by an older build still serving, or an
  out-of-band insert) is filled at the next start: deploy by migrating, then restarting every API
  process.
* No default and no rewrite: `ADD COLUMN` of a nullable column with no default changes only the
  catalogue. No index: the column is read per version, through `ix_rv_rule`, and never searched
  across the table.
* No GRANT: the default privileges in `infra/scripts/pg_bootstrap.sql` cover added columns (0009).
* `SET LOCAL lock_timeout = '5s'` brackets both directions (C-5.6): the ACCESS EXCLUSIVE lock on
  `rule_versions` is held for a catalogue change only, and its wait is bounded.
* The downgrade drops the column: it holds derived data the store computes again from each
  version's IR, so no value is lost.

Additive (C-5.1); reversible (C-5.2) on an empty or a seeded database (C-5.5).

Numbered 0063 on `0061_password_history`: 0062 is reserved for #5211, and whichever of the two
lands second re-parents onto the other (C-5.3).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0063_rule_version_account_refs"
down_revision: str | None = "0061_password_history"
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


_UPGRADE_SQL = """
ALTER TABLE rule_versions ADD COLUMN account_refs text[];
"""

_DOWNGRADE_SQL = """
ALTER TABLE rule_versions DROP COLUMN account_refs;
"""
