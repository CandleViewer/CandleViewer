"""`python -I -m cvbackup`: the backup sidecar's process (ADR-0041 sections 1 and 4).

At start it reads its configuration (`config.load`; a refusal names the variable and exits 2),
hardens the process (no core dumps, not dumpable, umask 077), lays out the backup root, replays
its run record, serves the socket and sweeps the quarantine every `SWEEP_S` until SIGTERM or
SIGINT. `python -I -m cvbackup check-ledger` only checks that the run record replays, for the
Owner on the host (runbook `demo-host.md` §9), and serves nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import logging
import os
import resource
import signal
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

from cvbackup import config as config_module
from cvbackup import ledger as ledger_module
from cvbackup.config import SidecarConfig
from cvbackup.floor import Floor
from cvbackup.ledger import Ledger
from cvbackup.ops import KINDS, Ops
from cvbackup.paths import LEDGER_DIR, QUARANTINE_DIR, Root
from cvbackup.server import Server
from cvbackup.tasks import spawn

SWEEP_S: Final = 300.0
_PR_SET_DUMPABLE: Final = 4


def harden() -> None:
    """No core file, not dumpable or ptrace-attachable by its uid, files private by default."""
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_DUMPABLE) refused")
    os.umask(0o077)


def utc_now() -> datetime:
    return datetime.now(UTC)


async def serve(
    config: SidecarConfig, stop: asyncio.Event, *, clock: Callable[[], datetime] = utc_now,
    ready: asyncio.Event | None = None,
) -> None:  # fmt: skip
    """Serve until `stop` is set, `ready` once the socket listens."""
    root = Root(config.root)
    await asyncio.to_thread(root.ensure, (LEDGER_DIR, QUARANTINE_DIR, *sorted(KINDS)))
    ledger = Ledger(root, clock)
    await ledger.load()
    if not ledger.readable:  # served anyway: plan still works, the floor's ops fail closed
        logging.getLogger("cvbackup").error("cvbackup.ledger_unreadable")
    floor = Floor(root, ledger, run_cap=config.run_cap, run_window=config.run_window,
                  grace=config.grace)  # fmt: skip
    ops = Ops(config, root, ledger, floor, clock=clock)
    server = await Server(ops, api_uid=config.api_uid).start(config.socket)
    sweeping = spawn(_sweep(ops, stop), name="cvbackup.sweep")
    try:
        async with server:
            if ready is not None:
                ready.set()
            await stop.wait()
    finally:
        sweeping.cancel()
        await asyncio.wait([sweeping])
        ledger.close()


async def _sweep(ops: Ops, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await ops.sweep()
        except Exception as exc:  # the next sweep tries again; its class only
            logging.getLogger("cvbackup").error("cvbackup.sweep_failed error=%s",
                                                type(exc).__name__)  # fmt: skip
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(SWEEP_S):
                await stop.wait()


async def _main(config: SidecarConfig) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    await serve(config, stop)


def check_ledger(root: str) -> int:
    """`python -I -m cvbackup check-ledger`: whether the run record replays (0) or not (1), and
    where it stops; it reads, never repairs (runbook `demo-host.md` §9)."""
    try:
        entries = ledger_module.check(root)
    except FileNotFoundError:
        print("cvbackup: no run record yet")
        return 0
    except ledger_module.Unreplayable as fault:
        print(f"cvbackup: the run record does not replay from line {fault.line}")
        return 1
    except OSError as exc:  # a link, a permission: its class only
        print(f"cvbackup: the run record cannot be read ({type(exc).__name__})")
        return 1
    print(f"cvbackup: the run record replays, {entries} entries")
    return 0


def main(env: dict[str, str] | None = None, argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    args = argv or []
    if args not in ([], ["check-ledger"]):
        print("usage: python -I -m cvbackup [check-ledger]", file=sys.stderr)
        return 2
    source = os.environ if env is None else env
    try:
        if args:
            return check_ledger(config_module.backup_root(source))
        config = config_module.load(source)
    except config_module.ConfigError as refused:
        print(f"cvbackup: {refused}", file=sys.stderr)
        return 2
    harden()
    asyncio.run(_main(config))
    return 0


if __name__ == "__main__":
    sys.exit(main(argv=sys.argv[1:]))
