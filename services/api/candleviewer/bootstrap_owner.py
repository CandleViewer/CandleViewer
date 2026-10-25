"""Offline bootstrap of the first Owner (#4479 C2, SR-023, threat model U46, U49, U50):
`python -m candleviewer.bootstrap_owner --owner <email> [--live]`, only while cv-api is stopped
and no Owner is active. Runbook: `docs/ops/runbooks/auth-rbac.md` section 4.

It mirrors `candleviewer.breakglass` (decision R5) and reuses its terminal, pool release and
usage and interrupt statuses: logging first, then the flow (`admin.bootstrap_owner`) over this
CLI's own Postgres side (`SqlAlchemyBootstrapOwnerDatabase`: the mint, no reset store,
DC-4479-17). It needs no recovery-code key and imports neither `secrets` (C-3.2) nor `audit`
(C-3.3); nothing cv-api serves imports it (S8). Exit status: the flow's `BootstrapOwnerExit` (0
only after an invite whose records were all written, its token printed once), 2 for a usage or
settings error (nothing ran or was recorded), 130 after a second Ctrl-C.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import Any, Final

import structlog

from candleviewer.admin.bootstrap_owner import BootstrapOwnerExit, BootstrapOwnerFlow
from candleviewer.admin.breakglass import RunCancelled, Terminal
from candleviewer.admin.breakglass_wiring import BootstrapOwnerStores, build_bootstrap_owner_ports
from candleviewer.breakglass import EXIT_INTERRUPTED, EXIT_INVALID, _dispose, _Tty
from candleviewer.observability.logging import configure_logging
from candleviewer.settings import Settings
from candleviewer.storage.repositories.break_glass_cli_sqlalchemy import (
    SqlAlchemyBootstrapOwnerDatabase,
)

_INTERRUPTED: Final = (
    "Bootstrap interrupted: its outcome is unknown. Read the auth.bootstrap_owner_* rows in "
    "audit_log; a new run revokes any invite this one minted."
)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = Settings()
        env, level, fmt = settings.environment.value, settings.log_level, settings.log_format
        configure_logging(env=env, level=level, fmt=fmt)
    except ValueError as exc:  # a pydantic ValidationError among them; never print a value
        sys.stderr.write(f"bootstrap-owner: invalid settings ({type(exc).__name__}); nothing ran\n")
        return EXIT_INVALID
    terminal = _Tty(sys.stdin, sys.stdout)
    try:
        return asyncio.run(_exit_status(settings, args, terminal))
    except KeyboardInterrupt:  # `asyncio.run` cancelled every task: no summary may have shown
        _log().critical("bootstrap_owner.interrupted")
        terminal.write(_INTERRUPTED)
        return EXIT_INTERRUPTED


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m candleviewer.bootstrap_owner",
        description="Offline bootstrap of the first Owner (SR-023): one single-use Owner invite, "
        "only while no Owner is active. Run it only with cv-api stopped; every run is audited. "
        "See docs/ops/runbooks/auth-rbac.md section 4.",
    )
    parser.add_argument("--owner", required=True, help="email of the first Owner")
    parser.add_argument(
        "--live", action="store_true", help="confirm a live deployment (required in live only)"
    )
    return parser


async def _exit_status(settings: Settings, args: argparse.Namespace, terminal: Terminal) -> int:
    """The run's exit status. A cancelled run's too: `RunCancelled` must not escape
    `asyncio.run`, which turns it into `KeyboardInterrupt` and loses its status."""
    try:
        status: int = await run(settings, args.owner, live_flag=args.live, terminal=terminal)
    except RunCancelled as cut:
        status = cut.exit
    return int(status)


async def run(
    settings: Settings,
    owner: str,
    *,
    live_flag: bool,
    terminal: Terminal,
    stores: BootstrapOwnerStores | None = None,
) -> BootstrapOwnerExit:
    """One run over the CLI's Postgres side (or `stores`); raises `RunCancelled` as the flow
    does. The pool is released once the run has ended, its trail closed."""
    database = None
    if stores is None:
        stores = database = SqlAlchemyBootstrapOwnerDatabase(settings.pg_dsn.get_secret_value())
    try:
        ports = build_bootstrap_owner_ports(settings, stores, terminal)
        return await BootstrapOwnerFlow(ports).run(owner, live_flag=live_flag)
    finally:
        if database is not None:
            await _dispose(database)


if __name__ == "__main__":  # pragma: no cover - `python -m`, run by the e2e test on a pty
    raise SystemExit(main())
