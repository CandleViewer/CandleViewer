"""A cv-api stand-in for E29-Q04's s14 (#1148, C-13.6 #12; the precedent is
`tests/chaos/audit/_lane_child.py`): one process over the test's database (`_pg.running`), ready
and its account's startup pass reported, that takes an entry to the point the parent named and
parks there: the venue's state handed over (`HANDED`, in the host directory), `parked` said on its
stdout, then its order lane stopped where it is until the SIGKILL. The parent's order (the DSN,
the account, the user, the point and the host directory) comes on stdin, never in argv, the
environment or a file; once it is read, the child's stderr, its logs among it, goes to `LOG` in
the host directory, so its stdout says `parked` alone. The stdin pipe stays open: it is the child's
lifeline (`watch_parent`), and once it is closed, the parent done or gone, the child exits.

The points, each on the order lane:
- `door`: the order `submitting`, its create at the venue's door when the process went down:
  nothing reached the venue;
- `taken`: the venue took the create, and its answer never came back (the process went down
  after the send);
- `filled`: the order acknowledged, then part filled while the account had no stream, the fill
  never pushed."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
import threading
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, NoReturn, TextIO

import structlog

from candleviewer.exchange.base.models import AccountRef, OrderAck, PlaceOrderRequest
from tests.chaos.oms import _pg
from tests.chaos.oms._venue import Venue
from tests.chaos.oms._world import PRICE

API_DIR: Final = Path(__file__).resolve().parents[3]  # services/api, where the child runs
#: The part of the entry's 0.010 that the venue fills at `filled`.
PART: Final = Decimal("0.004")
#: In the host directory: the venue's state at the kill point, and the child's log.
HANDED: Final = "venue.json"
LOG: Final = "child.log"


class Parking(_pg.HostPort):
    """The venue's port of a process to be killed (module docstring): its create parks the
    process at `door`, before the venue takes it, or at `taken`, once the venue has."""

    def __init__(self, ref: AccountRef, point: str, host: Path) -> None:
        super().__init__(ref)
        self.point, self.host = point, host

    async def place_order(self, req: PlaceOrderRequest) -> OrderAck:
        if self.point == "door":
            self.park()
        ack = await super().place_order(req)
        if self.point == "taken":
            self.park()
        return ack

    def park(self) -> NoReturn:
        """The venue's state handed over (`HANDED`), `parked` said, then this thread, the order
        lane's, stopped where it is until the SIGKILL, as `_lane_child.park` stops its lane's."""
        (self.host / HANDED).write_text(json.dumps(self.handed()))
        sys.stdout.write(f"@@ parked {self.point}\n")
        sys.stdout.flush()
        threading.Event().wait()
        raise AssertionError("unreachable")


async def filled(port: Parking) -> NoReturn:
    """`filled`, on the order lane: part of the entry filled at the venue, unpushed; parked."""
    [link] = port.creates()
    await Venue(port, port.ref, _pg.now_us).fill(link, PART, PRICE, push=False)
    port.park()


async def run(order: dict[str, str]) -> None:
    db, host = _pg.Db.given(order), Path(order["host"])
    port = Parking(db.ref, order["point"], host)
    async with _pg.running(db, host, _pg.Host(held=port)) as world:
        outcome = await world.submit()  # at `door` and `taken`, never answered
        assert (outcome.status, outcome.lifecycle) == (202, "submitted"), outcome
        await world.on_lane(filled(port))


def watch_parent(pipe: TextIO, leave: Callable[[int], object] = os._exit) -> threading.Thread:
    """The parent's pipe is the child's lifeline: once it is closed, the parent done or gone, the
    child `leave`s (parked or not), so none outlives its test or its killed parent."""

    def until_closed() -> None:
        with pipe:
            pipe.read()  # the order came first: this returns at the pipe's end
        leave(1)

    watcher = threading.Thread(target=until_closed, name="parent-pipe", daemon=True)
    watcher.start()
    return watcher


def main() -> None:
    order = json.loads(sys.stdin.readline())
    with (Path(order["host"]) / LOG).open("ab") as log:
        os.dup2(log.fileno(), sys.stderr.fileno())
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(sys.stderr))
    watch_parent(sys.stdin)
    asyncio.run(run(order))


async def killed(db: _pg.Db, host: Path, point: str) -> dict[str, Any]:
    """This module run as a child (`main`) until it parks at `point`, within `WAIT_S`, then
    SIGKILLed: what its venue held then (`HANDED`). A failure shows the child's own output and
    its log's last lines."""
    child = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tests.chaos.oms._child", cwd=API_DIR,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )  # fmt: skip
    assert child.stdin is not None and child.stdout is not None
    child.stdin.write(json.dumps(db.order(point=point, host=str(host))).encode() + b"\n")
    parked, seen = f"@@ parked {point}\n".encode(), list[bytes]()
    try:
        async with asyncio.timeout(_pg.WAIT_S):
            await child.stdin.drain()
            while (line := await child.stdout.readline()) != parked:
                assert line, "the child ended before it parked:\n" + _told(seen, host)
                seen.append(line)
    except TimeoutError:
        raise AssertionError("the child never parked:\n" + _told(seen, host)) from None
    finally:
        with contextlib.suppress(ProcessLookupError):
            child.kill()
        await child.wait()
        child.stdin.close()  # the lifeline's end, released here and not left to the GC
    assert child.returncode == -signal.SIGKILL
    return _handed(host)


def _told(seen: list[bytes], host: Path) -> str:
    """The child's own output, then the last 40 lines of its log."""
    log = host / LOG
    tail = log.read_text(errors="replace").splitlines()[-40:] if log.exists() else []
    return b"".join(seen).decode(errors="replace") + "\n".join(tail)


def _handed(host: Path) -> dict[str, Any]:
    handed: dict[str, Any] = json.loads((host / HANDED).read_text())
    return handed


if __name__ == "__main__":
    main()
