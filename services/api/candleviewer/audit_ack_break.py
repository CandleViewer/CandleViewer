"""Host-console acknowledgement of an audit-chain break (#2904; 04 §8.1 "Enforced posture",
SR-086): `python -m candleviewer.audit_ack_break --owner <username or email> --first-bad-id <id>
--kind <kind> --reason "<text>" [--live]`, run on the trading host while cv-api runs or not.
Runbook: `docs/plan/07-release-and-prr.md#alert-auditbreakhaltengaged`.

A thin composition like `breakglass.py`: logging is configured first, from the settings, then the
flow (`admin.audit_break_ack`) runs over the CLI's own Postgres side. It imports no `audit`
(C-3.3). The named Owner must be an active Owner and the break must be the one engaged
(`first_bad_id`, `kind`, as the halt record and the `audit_chain_break` system event name it);
either refusal is recorded (`audit.chain_break_ack_denied`). The acknowledgement is written ahead
(`audit.chain_break_acknowledged`); each cv-api process clears the halt at its next read.

Exit status: 0 acknowledged; 1 refused, or nothing written (Postgres unreachable, the halt state
unreadable, the record refused); 2 a usage or settings error, nothing run.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import Any, Final

import structlog

from candleviewer.admin.audit_break_ack import (
    AckOutcome,
    BreakIdentity,
    ConsoleAckUnavailable,
    acknowledge_from_console,
)
from candleviewer.observability.logging import configure_logging
from candleviewer.settings import Settings
from candleviewer.storage.repositories.break_glass_cli_sqlalchemy import (
    SqlAlchemyAuditAckDatabase,
)

EXIT_OK: Final = 0
EXIT_REFUSED: Final = 1
EXIT_INVALID: Final = 2
#: 24 §15.5's typed reason, as for an incident acknowledgement: 3 to 280 characters.
REASON_MIN, REASON_MAX = 3, 280
KINDS: Final = (
    "prev_hash_mismatch",
    "entry_hash_mismatch",
    "checkpoint_mismatch",
    "checkpoint_missing",
    "tail_truncated",
    "unknown",
)
DISPOSE_TIMEOUT_S: Final = 10.0
_MESSAGES: Final = {
    AckOutcome.ACKNOWLEDGED: "acknowledged: order entry resumes at each API process's next read",
    AckOutcome.NOT_OWNER: "refused: that name is not an active Owner (recorded)",
    AckOutcome.NOT_ENGAGED: "refused: no halt is engaged on that break (recorded)",
    AckOutcome.RECORD_FAILED: "not acknowledged: the record could not be written; the halt stays",
}


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    reason = args.reason.strip()
    if not REASON_MIN <= len(reason) <= REASON_MAX or not reason.isprintable():
        sys.stderr.write(f"audit-ack-break: --reason must be {REASON_MIN} to {REASON_MAX} ")
        sys.stderr.write("printable characters; nothing ran\n")
        return EXIT_INVALID
    try:
        settings = Settings()
        env, level, fmt = settings.environment.value, settings.log_level, settings.log_format
        configure_logging(env=env, level=level, fmt=fmt)
    except ValueError as exc:  # a pydantic ValidationError among them; never print a value
        sys.stderr.write(f"audit-ack-break: invalid settings ({type(exc).__name__}); nothing ran\n")
        return EXIT_INVALID
    if env == "live" and not args.live:
        sys.stderr.write("audit-ack-break: this is a live deployment: add --live; nothing ran\n")
        return EXIT_INVALID
    identity = BreakIdentity(args.first_bad_id, args.kind)
    return asyncio.run(run(settings, args.owner, identity, reason))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m candleviewer.audit_ack_break",
        description="Acknowledge a verified audit-chain break so order entry resumes (#2904). "
        "Owner only; every run is audited. See docs/plan/07-release-and-prr.md "
        "(AuditBreakHaltEngaged).",
    )
    parser.add_argument("--owner", required=True, help="username or email of an active Owner")
    parser.add_argument("--first-bad-id", required=True, type=int, help="the break's first id")
    parser.add_argument("--kind", required=True, choices=KINDS, help="the break's kind")
    parser.add_argument("--reason", required=True, help="why it is acknowledged (3-280)")
    parser.add_argument(
        "--live", action="store_true", help="confirm a live deployment (required in live only)"
    )
    return parser


async def run(
    settings: Settings,
    owner: str,
    identity: BreakIdentity,
    reason: str,
    *,
    stores: Any = None,
) -> int:
    """One run over the CLI's Postgres side (or `stores`), its pool released at the end."""
    database = None
    if stores is None:
        stores = database = SqlAlchemyAuditAckDatabase(settings.pg_dsn.get_secret_value())
    try:
        try:
            outcome = await acknowledge_from_console(
                stores, owner=owner, identity=identity, reason=reason
            )
        except ConsoleAckUnavailable as exc:
            _log().error("audit.break_ack.unavailable", error=str(exc))
            sys.stderr.write("audit-ack-break: the audit store is unavailable; nothing written\n")
            return EXIT_REFUSED
        sys.stdout.write(f"audit-ack-break: {_MESSAGES[outcome]}\n")
        return EXIT_OK if outcome is AckOutcome.ACKNOWLEDGED else EXIT_REFUSED
    finally:
        if database is not None:
            await _dispose(database)


async def _dispose(database: SqlAlchemyAuditAckDatabase) -> None:
    try:
        async with asyncio.timeout(DISPOSE_TIMEOUT_S):
            await database.dispose()
    except Exception as exc:  # the run has ended and is recorded; exiting releases the rest
        _log().warning("audit.break_ack.pool_not_released", error=type(exc).__name__)


if __name__ == "__main__":  # pragma: no cover - `python -m`
    raise SystemExit(main())
