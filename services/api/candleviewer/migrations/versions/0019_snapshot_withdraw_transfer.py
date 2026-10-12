"""api_keys.ak_snapshot_shape also refuses withdraw/transfer rights inside groups (#2240)

Revision ID: 0019_snapshot_withdraw_transfer
Revises: 0017_exchange_accounts_api_keys

Fix forward for 0017, which is immutable (C-5.4). 0017's `ak_snapshot_shape` refused only a
non-empty top-level `Withdraw` group. Bybit's `GET /v5/user/query-api` reports rights as values
inside a group (`"Wallet": ["AccountTransfer", "SubMemberTransfer", "Withdraw"]`), and C-2.8 /
SR-030a refuse transfer rights as well as withdrawal. The new CHECK keeps 0017's expression
verbatim and adds three SQL/JSON path scans of `permissions`. Each looks for `withdraw` or
`transfer`, ignoring case, in:
  1. a string at any depth (`"Wallet": ["AccountTransfer"]`);
  2. an object key below the group level;
  3. a group name whose value grants anything (null, "" and [] grant nothing).
That is the M13 predicate `candleviewer.accounts._permissions.reject_withdraw`, which mirrors
the M2 credential gate. Each scan must be `IS FALSE`, so a NULL result fails closed. A plain
CHECK suffices because `.**` walks the document recursively: no trigger, and no helper function
(replacing one would change the rule under an already-validated constraint). Being 0017's rule
plus extra conjuncts, the CHECK only tightens, so the downgrade's VALIDATE always succeeds.

Locks and existing rows (C-5.6): the CHECK is added NOT VALID, then VALIDATE checks every
existing row (expected: none). Only then is 0017's constraint dropped and the new one renamed
into its place, so `ak_snapshot_shape` keeps its name. Alembic runs the revision in one
transaction, so the scan runs under the ACCESS EXCLUSIVE lock the ADD took; api_keys holds one
row per stored key, which keeps that short. If VALIDATE fails, a stored key grants withdraw or
transfer rights: revoke the key at Bybit and remove its row, then upgrade. Never weaken the
CHECK to get past it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0019_snapshot_withdraw_transfer"
down_revision: str | None = "0017_exchange_accounts_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADD_0019 = """
ALTER TABLE api_keys ADD CONSTRAINT ak_snapshot_shape_0019 CHECK (
  permission_snapshot ? 'permissions'
  AND permission_snapshot ? 'uid'
  AND jsonb_typeof(permission_snapshot->'permissions') = 'object'
  AND COALESCE(jsonb_array_length(permission_snapshot->'permissions'->'Withdraw'), 0) = 0
  AND jsonb_path_exists(permission_snapshot->'permissions',
    'strict $.** ? (@.type() == "string" && @ like_regex "withdraw|transfer" flag "i")'
  ) IS FALSE
  AND jsonb_path_exists(permission_snapshot->'permissions',
    'strict $ ? (@.type() == "object").*.** ? (@.type() == "object").keyvalue()
       ? (@.key like_regex "withdraw|transfer" flag "i")'
  ) IS FALSE
  AND jsonb_path_exists(permission_snapshot->'permissions',
    'strict $ ? (@.type() == "object").keyvalue()
       ? (@.key like_regex "withdraw|transfer" flag "i"
          && !(@.value.type() == "null"
               || (@.value.type() == "string" && @.value == "")
               || (@.value.type() == "array" && @.value.size() == 0)))'
  ) IS FALSE
) NOT VALID;
"""

_ADD_0017 = """
ALTER TABLE api_keys ADD CONSTRAINT ak_snapshot_shape_0017 CHECK (
  permission_snapshot ? 'permissions'
  AND permission_snapshot ? 'uid'
  AND jsonb_typeof(permission_snapshot->'permissions') = 'object'
  AND COALESCE(jsonb_array_length(permission_snapshot->'permissions'->'Withdraw'), 0) = 0
) NOT VALID;
"""


def upgrade() -> None:
    op.execute(_ADD_0019)
    op.execute("ALTER TABLE api_keys VALIDATE CONSTRAINT ak_snapshot_shape_0019;")
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT ak_snapshot_shape;")
    op.execute(
        "ALTER TABLE api_keys RENAME CONSTRAINT ak_snapshot_shape_0019 TO ak_snapshot_shape;"
    )


def downgrade() -> None:
    op.execute(_ADD_0017)
    op.execute("ALTER TABLE api_keys VALIDATE CONSTRAINT ak_snapshot_shape_0017;")
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT ak_snapshot_shape;")
    op.execute(
        "ALTER TABLE api_keys RENAME CONSTRAINT ak_snapshot_shape_0017 TO ak_snapshot_shape;"
    )
