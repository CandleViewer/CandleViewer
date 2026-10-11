"""kek_versions: non-secret KEK key-check values (E27-T02 #835, E27-K01 FU-4)

Revision ID: 0018_kek_versions
Revises: 0017_exchange_accounts_api_keys

Additive (C-5.1). `kcv` = first 8 bytes of HMAC-SHA256(KEK, "cv-kek-kcv-v1"): it identifies a
KEK version without revealing it (e27-kek.md §5). Compared in constant time by M2.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018_kek_versions"
down_revision: str | None = "0017_exchange_accounts_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UP = """
CREATE TABLE kek_versions (
  version    integer PRIMARY KEY,
  kcv        bytea NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  retired_at timestamptz,
  CONSTRAINT kv_version_pos CHECK (version >= 1),
  CONSTRAINT kv_kcv_len     CHECK (octet_length(kcv) = 8)
);
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kek_versions;")
