"""Offline, read-only audit-chain check (E43-T10, #1238):
`python -m candleviewer.audit_chain_verify [--checkpoint-file FILE [--checkpoint-sha256 HEX]]
[--batch N] [--timeout S] | --check | --self-test`.
Runbook: `docs/ops/runbooks/audit-chain-verify.md`.

A thin composition like `audit_ack_break.py`: it imports no `audit` (C-3.3). The login is
`Settings.audit_verify_dsn` (`CV_AUDIT_VERIFY_DSN`, a read-only login such as `cv_ro`); unset, the
tool refuses to run and never falls back to `CV_PG_DSN`. The flow (`admin.audit_chain_verify`)
runs over the CLI's read-only Postgres side, under the in-app verify's statement budget and entry
cap. It opens no socket but the database's, and prints no connection string.
"""

from __future__ import annotations

from collections.abc import Sequence

from candleviewer.admin import audit_chain_verify as flow
from candleviewer.settings import Settings
from candleviewer.storage.repositories.break_glass_cli_sqlalchemy import (
    SqlAlchemyAuditVerifyDatabase,
)


def main(argv: Sequence[str] | None = None) -> int:
    return flow.main(argv, connect=connect)


def connect() -> SqlAlchemyAuditVerifyDatabase | None:
    """The stores from the settings, or `None` when no read-only login is set. No I/O."""
    settings = Settings()
    if settings.audit_verify_dsn is None:
        return None
    return SqlAlchemyAuditVerifyDatabase(
        settings.audit_verify_dsn.get_secret_value(),
        statement_timeout_ms=settings.audit_verify_statement_timeout_ms,
        max_entry_bytes=settings.audit_verify_max_entry_bytes,
    )


if __name__ == "__main__":  # pragma: no cover - `python -m`
    raise SystemExit(main())
