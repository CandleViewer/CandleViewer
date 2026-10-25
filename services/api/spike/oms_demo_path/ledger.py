"""No row, no order (#843 A4 fold 3): the run's intent ledger, `intents.jsonl` in its directory.

Each create's intent is written, scrubbed, before the create is sent (`GuardedPort.place_order`):
the run-scoped token of its `orderLinkId` (`link#3`), the side, the quantity, the price, the stop
and reduce-only, with the link's digest (`safety.digest`: the first 16 hex characters of its
sha256, a handle, never the id). The row passes the scrubber and its leak check, then one
`write(2)` on the file opened for append (`outputs.write_file`: `0600`, no symlink followed),
synchronously and never through the outputs' queue: once `record` returns, the row is the
operating system's, so a run killed right after it (SIGKILL, the OOM killer) leaves it, and an
order's row exists before the order can. A row that is not written (the leak check or the disk
refused it) is `Refused`, and its create is not sent: no row, no order.

The ledger is also the run's own state (ruling R1C-02 (b)): the run owns exactly the orders its
ledger lists and the fills of those orders (`safety.RunScope`), so the shutdown flatten cancels
and closes only those, and the owner's `flatten` adopts a failed run's orders from that run's
ledger (`adopt`), never from a guess at an id's form. A digest joins `digests` only once its row
is written, so the set in memory is the file's.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Final

from spike.oms_demo_path.outputs import Writer, write_file
from spike.oms_demo_path.safety import Refused, digest
from spike.oms_demo_path.scrub import LeakDetected, Scrubber

if TYPE_CHECKING:
    from candleviewer.exchange.base.models import PlaceOrderRequest

#: The ledger's file in a run's directory.
LEDGER: Final = "intents.jsonl"
_DIGEST: Final = re.compile(r"[0-9a-f]{16}")


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
        write: Writer = write_file,
    ) -> None:
        self.path = directory / LEDGER
        self.write = write
        self._scrubber = scrubber
        self._elapsed = elapsed
        #: The digest of every order the ledger lists: the run's own, and any it adopted.
        self.digests: set[str] = set()
        self.intents = 0
        self.adopted = 0

    def owns(self, link: str | None) -> bool:
        """`link` is an order this ledger lists (an order it does not list is never the run's)."""
        return link is not None and digest(link) in self.digests

    def record(self, req: PlaceOrderRequest) -> None:
        """`req`'s intent, written before it is sent; `Refused` when it is not (nothing is sent)."""
        handle = digest(req.order_link_id)
        self._append(
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

    def adopt(self, path: Path) -> int:
        """A failed run's orders, from its ledger at `path` (R1S-04's `flatten`): each digest it
        lists joins this ledger's, written here first as an `adopted` row, so this run's own
        ledger lists all it may touch and a later `flatten` of this run adopts them too. `Refused`
        (nothing touched) when that ledger is unreadable or lists no order. How many it lists."""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            failed = type(exc).__name__
            raise Refused(f"no readable intent ledger in --run-dir ({failed})") from None
        listed = {handle for handle in map(_digest_of, lines) if handle is not None}
        if not listed:
            raise Refused("that run's intent ledger lists no order: nothing to flatten from it")
        for handle in sorted(listed - self.digests):
            self._append({"adopted": True, "link_digest": handle})
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

    def _append(self, row: dict[str, object]) -> None:
        line = {"t": self._elapsed(), **row}
        try:
            text = self._scrubber.dumps(line)
            self.write(self.path, (text + "\n").encode(), True)
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
