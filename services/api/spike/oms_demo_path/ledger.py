"""No row, no order (#843 A4 fold 3): the run's intent ledger, `intents.jsonl` in its directory.

Each create's intent is written, scrubbed, before the create is sent (`GuardedPort.place_order`):
the run-scoped token of its `orderLinkId` (`link#3`), the side, the quantity, the price, the stop
and reduce-only, with the link's digest (`safety.digest`: the first 16 hex characters of its
sha256, a handle, never the id). The row passes the scrubber and its leak check, then, off the
event loop (`asyncio.to_thread`), one `write(2)` on the file opened for append (`0600`, no
symlink followed) and `fsync` of its descriptor (fold 4, the coordinator's ruling 3); until one
such row is down, the run directory is fsynced too, so the file's entry survives a crash (in
practice once: the first row creates the file). Only then does `record` return, so an order's row
is on disk before the order can exist, whatever ends the process: a kill, the OOM killer, a host
crash. A row that is not written (the leak check, the disk or an `fsync` refused it: a failed
`fsync` is a failed write) is `Refused`, and its create is not sent: no row, no order. Every row
goes this way: each create's, the flatten's closes and `flatten` mode's `adopted` rows. The row's
write and fsync happen before the create's measured window opens (`GuardedPort._call`), so neither
is in any timing the record reports.

The ledger is also the run's own state (ruling R1C-02 (b)): the run owns exactly the orders its
ledger lists and the fills of those orders (`safety.RunScope`), so the shutdown flatten cancels
and closes only those, and the owner's `flatten` adopts a failed run's orders from that run's
ledger (`adopt`), never from a guess at an id's form. A digest joins `digests` only once its row
is written, so the set in memory is the file's.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Final

from spike.oms_demo_path.safety import Refused, digest
from spike.oms_demo_path.scrub import LeakDetected, Scrubber

if TYPE_CHECKING:
    from candleviewer.exchange.base.models import PlaceOrderRequest

#: The ledger's file in a run's directory.
LEDGER: Final = "intents.jsonl"
_DIGEST: Final = re.compile(r"[0-9a-f]{16}")
_APPEND: Final = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC
#: A row's write: its bytes durable when it returns, else it raises (`IntentLedger.write`).
Append = Callable[[bytes], None]
#: `os.fsync`'s shape: the seam a test replaces (a slow disk, a failing one).
Sync = Callable[[int], None]


def _plain(value: object) -> str | None:
    return None if value is None else format(value, "f")


class IntentLedger:
    """One run's intent ledger (see the module docstring). `elapsed` is the run's clock in
    seconds (`RunOutputs.elapsed`), so a row's `t` is its events' `t`."""

    def __init__(
        self,
        directory: Path,
        scrubber: Scrubber,
        *,
        elapsed: Callable[[], float],
        write: Append | None = None,
        fsync: Sync = os.fsync,
    ) -> None:
        self.path = directory / LEDGER
        self.fsync = fsync
        #: The row's write (`durable` unless a test gives another), run off the event loop.
        self.write: Append = self.durable if write is None else write
        self._scrubber = scrubber
        self._elapsed = elapsed
        self._entry_synced = False
        #: The digest of every order the ledger lists: the run's own, and any it adopted.
        self.digests: set[str] = set()
        self.intents = 0
        self.adopted = 0

    def owns(self, link: str | None) -> bool:
        """`link` is an order this ledger lists (an order it does not list is never the run's)."""
        return link is not None and digest(link) in self.digests

    async def record(self, req: PlaceOrderRequest) -> None:
        """`req`'s intent, on disk before it is sent; `Refused` when it is not (nothing is sent)."""
        handle = digest(req.order_link_id)
        await self._append(
            {
                "order_link_id": req.order_link_id,
                "link_digest": handle,
                "side": req.side,
                "qty": _plain(req.qty),
                "price": _plain(req.price),
                "stop_loss": _plain(req.stop_loss),
                "reduce_only": req.reduce_only,
            }
        )
        self.digests.add(handle)
        self.intents += 1

    async def adopt(self, path: Path) -> int:
        """A failed run's orders, from its ledger at `path` (R1S-04's `flatten`): each digest it
        lists joins this ledger's, written here first as an `adopted` row, so this run's own
        ledger lists all it may touch and a later `flatten` of this run adopts them too. `Refused`
        (nothing touched) when that ledger is unreadable or lists no order. How many it lists."""
        try:
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            failed = type(exc).__name__
            raise Refused(f"no readable intent ledger in --run-dir ({failed})") from None
        listed = {handle for handle in map(_digest_of, text.splitlines()) if handle is not None}
        if not listed:
            raise Refused("that run's intent ledger lists no order: nothing to flatten from it")
        for handle in sorted(listed - self.digests):
            await self._append({"adopted": True, "link_digest": handle})
            self.digests.add(handle)
            self.adopted += 1
        return len(listed)

    def summary(self) -> dict[str, object]:
        """The summary's `ledger`: the file and its counts, never a digest or an id."""
        return {
            "file": LEDGER,
            "intents": self.intents,
            "adopted": self.adopted,
            "orders": len(self.digests),
        }

    def durable(self, data: bytes) -> None:
        """One row on disk (see the module docstring): `write(2)` of all of `data` on the file
        opened for append, then `fsync`; the directory's `fsync` until one row is down. Any
        failure raises `OSError`."""
        fd = os.open(self.path, _APPEND, 0o600)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view) :]
            self.fsync(fd)
        finally:
            os.close(fd)
        if not self._entry_synced:
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                self.fsync(directory)
            finally:
                os.close(directory)
            self._entry_synced = True

    async def _append(self, row: dict[str, object]) -> None:
        line = {"t": self._elapsed(), **row}
        try:
            text = self._scrubber.dumps(line)
            await asyncio.to_thread(self.write, (text + "\n").encode())
        except (LeakDetected, OSError) as exc:
            raise Refused(
                f"no row, no order: the ledger row was not written ({type(exc).__name__});"
                " nothing was sent"
            ) from None


def _digest_of(line: str) -> str | None:
    """A row's link digest; `None` for a line holding none (a row a kill cut short)."""
    try:
        row = json.loads(line)
    except ValueError:
        return None
    handle = row.get("link_digest") if isinstance(row, dict) else None
    return handle if isinstance(handle, str) and _DIGEST.fullmatch(handle) else None
