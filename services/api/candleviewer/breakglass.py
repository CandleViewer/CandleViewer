"""Offline break-glass reset of an Owner's MFA (E09-S11 #2119 slice 5, SR-023, threat model U10):
`python -m candleviewer.breakglass --owner <username or email> [--live]`, only while cv-api is
stopped. Runbook: `docs/ops/runbooks/auth-rbac.md` section 3.

The entry point of decision R5, a thin composition like `health_wiring.py`. Logging is configured
first, with the redaction filter, from the settings (which log nothing); then the slice-4 flow
(`admin.breakglass`) runs over real ports. This module imports neither `secrets` (C-3.2) nor
`audit` (C-3.3): `admin.breakglass_wiring` builds the journal, `audit_log` and KEK ports from the
CLI's Postgres side (`SqlAlchemyBreakGlassDatabase`, one pool, so the R2c probe can tell its
sessions from cv-api's). Nothing is mounted on cv-api (S8).

Exit status: the flow's `BreakGlassExit` (0 only after a reset whose records were all written),
2 for a usage or settings error (before any record or check), 130 after a second Ctrl-C.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import termios
from collections.abc import Sequence
from typing import Any, TextIO

import structlog
from pydantic import ValidationError

from candleviewer.admin.breakglass import BreakGlassExit, BreakGlassFlow, RunCancelled, Terminal
from candleviewer.admin.breakglass_wiring import BreakGlassStores, build_break_glass_ports
from candleviewer.observability.logging import configure_logging
from candleviewer.settings import UNKNOWN_HOME_REFUSAL, Settings, refusal_messages
from candleviewer.storage.repositories.break_glass_cli_sqlalchemy import (
    SqlAlchemyBootstrapOwnerDatabase,
    SqlAlchemyBreakGlassDatabase,
)

#: argparse's usage status, and a settings error: nothing ran and nothing was recorded.
EXIT_INVALID = 2
#: 128 + SIGINT: a second Ctrl-C cut the run short, so its outcome is unknown.
EXIT_INTERRUPTED = 130
#: Bound on releasing the pool once the run has ended.
DISPOSE_TIMEOUT_S = 10.0
_LINE_MAX = 4096  # one terminal line (the canonical-mode input buffer)
_KEY_BYTES = 32
_INTERRUPTED = (
    "Break-glass interrupted: its outcome is unknown. Read the auth.break_glass_* rows in "
    "audit_log (and any unresolved break_glass_used event) before running it again."
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
        sys.stderr.write(f"break-glass: invalid settings ({type(exc).__name__}); nothing ran\n")
        if isinstance(exc, ValidationError):  # #5303: the messages only, never an input
            sys.stderr.writelines(f"  {line}\n" for line in refusal_messages(exc))
        return EXIT_INVALID
    except RuntimeError:  # an unknown `~user` in a path setting; its text names the path
        sys.stderr.write(f"break-glass: {UNKNOWN_HOME_REFUSAL}; nothing ran\n")
        return EXIT_INVALID
    key = recovery_code_key(settings)
    if key is None:
        _log().critical("breakglass.recovery_code_key_unusable")
        sys.stderr.write("break-glass: the recovery-code key setting is unusable; nothing ran\n")
        return EXIT_INVALID
    terminal = _Tty(sys.stdin, sys.stdout)
    try:
        return asyncio.run(_exit_status(settings, args, key, terminal))
    except KeyboardInterrupt:  # `asyncio.run` cancelled every task: no summary may have shown
        _log().critical("breakglass.interrupted")
        terminal.write(_INTERRUPTED)
        return EXIT_INTERRUPTED


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m candleviewer.breakglass",
        description="Offline break-glass reset of an Owner's MFA (SR-023). Run it only with "
        "cv-api stopped; every run is audited. See docs/ops/runbooks/auth-rbac.md section 3.",
    )
    parser.add_argument("--owner", required=True, help="username or email of the Owner")
    parser.add_argument(
        "--live", action="store_true", help="confirm a live deployment (required in live only)"
    )
    return parser


def recovery_code_key(settings: Settings) -> bytes | None:
    """cv-api's recovery-code HMAC key (`CV_AUTH_RECOVERY_HMAC_KEY_HEX`, SR-022), which the live
    rule checks a code with: its 32 bytes, else None. Never logged."""
    configured = settings.auth_recovery_hmac_key_hex
    try:
        key = b"" if configured is None else bytes.fromhex(configured.get_secret_value())
    except ValueError:
        return None
    return key if len(key) == _KEY_BYTES else None


async def _exit_status(
    settings: Settings, args: argparse.Namespace, key: bytes, terminal: Terminal
) -> int:
    """The run's exit status. A cancelled run's too: `RunCancelled` must not escape
    `asyncio.run`, which turns it into `KeyboardInterrupt` and loses its status."""
    try:
        status: int = await run(
            settings, args.owner, live_flag=args.live, recovery_code_key=key, terminal=terminal
        )
    except RunCancelled as cut:
        status = cut.exit
    return int(status)


async def run(
    settings: Settings,
    owner: str,
    *,
    live_flag: bool,
    recovery_code_key: bytes,
    terminal: Terminal,
    stores: BreakGlassStores | None = None,
) -> BreakGlassExit:
    """One run over the CLI's Postgres side (or `stores`); raises `RunCancelled` as the flow
    does. The pool is released once the run has ended, its trail closed."""
    database = None
    if stores is None:
        stores = database = SqlAlchemyBreakGlassDatabase(settings.pg_dsn.get_secret_value())
    try:
        ports = build_break_glass_ports(
            settings, stores, terminal, recovery_code_key=recovery_code_key
        )
        return await BreakGlassFlow(ports).run(owner, live_flag=live_flag)
    finally:
        if database is not None:
            await _dispose(database)


async def _dispose(
    database: SqlAlchemyBreakGlassDatabase | SqlAlchemyBootstrapOwnerDatabase,  # #4479 C2
) -> None:
    try:
        async with asyncio.timeout(DISPOSE_TIMEOUT_S):
            await database.dispose()
    except Exception as exc:  # the run has ended and is recorded; exiting releases the rest
        _log().warning("breakglass.pool_not_released", error=type(exc).__name__)


class _Tty:
    """The operator's terminal: stdin and stdout, both a TTY. A line is read on the loop, so a
    prompt's timeout or a Ctrl-C ends it at once and no thread stays blocked on stdin. The
    recovery code is read with echo off; its buffer is zeroed after reading (best effort)."""

    def __init__(self, stdin: TextIO, stdout: TextIO) -> None:
        self._in, self._out = stdin, stdout

    def is_interactive(self) -> bool:
        return self._in.isatty() and self._out.isatty()

    def write(self, line: str) -> None:
        self._out.write(f"{line}\n")
        self._out.flush()

    async def ask(self, prompt: str) -> str:
        self._out.write(prompt)
        self._out.flush()
        return await self._read_line()

    async def ask_secret(self, prompt: str) -> str:
        fd = self._in.fileno()
        shown = termios.tcgetattr(fd)
        hidden = [*shown[:3], shown[3] & ~termios.ECHO, *shown[4:]]
        termios.tcsetattr(fd, termios.TCSAFLUSH, hidden)
        try:
            return await self.ask(prompt)
        finally:
            termios.tcsetattr(fd, termios.TCSAFLUSH, shown)
            self.write("")  # the operator's Enter was not echoed

    async def _read_line(self) -> str:
        """Up to and without the newline; `EOFError` at end of input (Ctrl-D)."""
        loop, fd, line = asyncio.get_running_loop(), self._in.fileno(), bytearray()
        try:
            while not line.endswith(b"\n") and len(line) < _LINE_MAX:
                readable: asyncio.Future[None] = loop.create_future()
                loop.add_reader(fd, _settle, readable)
                try:
                    await readable
                finally:
                    loop.remove_reader(fd)
                chunk = os.read(fd, _LINE_MAX - len(line))
                if not chunk:
                    raise EOFError
                line += chunk
            return line.decode(errors="replace").rstrip("\r\n")
        finally:
            line[:] = bytes(len(line))


def _settle(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)


if __name__ == "__main__":  # pragma: no cover - `python -m`, run by test_cli_end_to_end
    raise SystemExit(main())
