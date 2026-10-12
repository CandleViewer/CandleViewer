"""api_keys.ak_snapshot_shape also refuses withdraw/transfer rights inside groups (#2240)

Revision ID: 0019_snapshot_withdraw_transfer
Revises: 0017_exchange_accounts_api_keys

Fix forward for 0017, which is immutable (C-5.4). 0017's `ak_snapshot_shape` refused only a
non-empty top-level `Withdraw` group. The exchange's key-info response (`GET /v5/user/query-api`)
reports rights as values inside a group (`"Wallet": ["AccountTransfer", "SubMemberTransfer",
"Withdraw"]`), and C-2.8 / SR-030a refuse transfer rights as well as withdrawal. The new CHECK
keeps 0017's expression verbatim and adds three SQL/JSON path scans of `permissions`. Each looks
for `withdraw` or `transfer`, ignoring case, in:
  1. a string at any depth (`"Wallet": ["AccountTransfer"]`);
  2. an object key below the group level;
  3. a group name whose value grants anything (null, "" and [] grant nothing).
That is the M13 predicate `candleviewer.accounts._permissions.reject_withdraw`, which mirrors
the M2 credential gate, with one difference: 0017's retained conjunct still requires the legacy
`Withdraw` group to be absent or an array. A `null`, `""`, scalar or object there raises SQLSTATE
22023 (`jsonb_array_length`) rather than a check violation; the write fails either way. Each scan
must be `IS FALSE`, so a NULL result fails closed. A plain CHECK suffices because `.**` walks the
document recursively: no trigger, and no helper function (replacing one would change the rule
under an already-validated constraint). Being 0017's rule plus extra conjuncts, the CHECK only
tightens, so the downgrade's VALIDATE always succeeds. The scans are a substring deny-list and
share its blind spots (inner spacing, lookalike characters); #2270 tracks an allow-list.

`ak_no_transfer CHECK (can_transfer = false)` pins the flag as `ak_no_withdraw` pins
`can_withdraw`: with transfer rights refused, a stored key can never claim one.

Locks and existing rows (C-5.6): each CHECK is added NOT VALID, then VALIDATE checks every
existing row (expected: none). Only then is 0017's constraint dropped and the new one renamed
into its place, so `ak_snapshot_shape` keeps its name. env.py runs every pending revision in one
transaction, so NOT VALID buys no lock relief here: the ACCESS EXCLUSIVE lock the first ADD takes
blocks reads and writes on api_keys until the whole upgrade commits. The scans are short (one row
per stored key). `lock_timeout` (5 s, reset to the default at the end) bounds the wait to acquire
that lock, so the migration fails fast instead of queueing api_keys traffic behind it.

If VALIDATE fails, a stored key grants withdraw or transfer rights: a C-2.8 incident. Never edit
api_keys by hand (C-2.9) or weaken a CHECK to get past it. Turn the right off on the exchange and
re-run the audited key verification (SR-031), which refreshes the stored snapshot and flags. A
key that cannot be re-verified is revoked through the audited key-management flow
(`api_key.revoke`) and escalated to the owner: no audited path removes a stored row yet.
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
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_ADD_0019)
    op.execute("ALTER TABLE api_keys VALIDATE CONSTRAINT ak_snapshot_shape_0019;")
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT ak_snapshot_shape;")
    op.execute(
        "ALTER TABLE api_keys RENAME CONSTRAINT ak_snapshot_shape_0019 TO ak_snapshot_shape;"
    )
    op.execute(
        "ALTER TABLE api_keys ADD CONSTRAINT ak_no_transfer CHECK (can_transfer = false) NOT VALID;"
    )
    op.execute("ALTER TABLE api_keys VALIDATE CONSTRAINT ak_no_transfer;")
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT ak_no_transfer;")
    op.execute(_ADD_0017)
    op.execute("ALTER TABLE api_keys VALIDATE CONSTRAINT ak_snapshot_shape_0017;")
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT ak_snapshot_shape;")
    op.execute(
        "ALTER TABLE api_keys RENAME CONSTRAINT ak_snapshot_shape_0017 TO ak_snapshot_shape;"
    )
    op.execute("SET LOCAL lock_timeout = DEFAULT;")
