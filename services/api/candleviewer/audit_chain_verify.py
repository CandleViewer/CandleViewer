"""Offline, read-only audit-integrity check (E43-T10): `python -m candleviewer.audit_chain_verify
[--mirror FILE] [--mirror-sha256 HEX] | --check | --self-test`.

A thin composition like `audit_ack_break.py`: it imports no `audit` (C-3.3). The flow
(`admin.audit_chain_verify`) runs over the read-only Postgres reader built here from
`CV_AUDIT_VERIFY_DSN`. Runbook: `docs/ops/runbooks/audit-chain-verify.md`.
"""

from __future__ import annotations

from collections.abc import Sequence

from candleviewer.admin import audit_chain_verify as flow
from candleviewer.storage.repositories.audit_offline_sqlalchemy import (
    SqlAlchemyAuditOfflineReader,
)


def main(argv: Sequence[str] | None = None) -> int:
    return flow.main(argv, open_reader=SqlAlchemyAuditOfflineReader)


if __name__ == "__main__":  # pragma: no cover - `python -m`
    raise SystemExit(main())
