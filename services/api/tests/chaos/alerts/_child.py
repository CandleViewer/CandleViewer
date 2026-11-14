"""A cv-api stand-in for the alert chaos scenarios: it runs the production firing transaction or
the production dispatcher over Postgres and parks at the named point, says so on stdout, and waits
for its SIGKILL (or, for `stall`, for the parent's `go`). The order (DSN, ids, mode) comes on
stdin, never in argv, the environment or a file. No network: the email relay is a stand-in.

- `fire`: one firing (`in_app` + `email`) commits through `WakingFiringStore`; the dispatcher's
  wake, the first thing after the commit, parks: killed between the delivery insert and the poll.
- `send`: the dispatcher runs one poll; the `email` relay parks inside `send`, after `in_app`
  settled: killed mid-dispatch, the email row leased and unsettled.
- `stall`: one poll with a short lease; the relay says which key it sends and blocks on stdin, so
  the parent can SIGSTOP the poller holding a batch; after `go` the poll finishes and the child
  reports how many settles it won.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading

from candleviewer.alerts.ports import WakingFiringStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.chaos.alerts._pg import dispatcher, fire, firing_store
from tests.chaos.alerts._rig import Wins


def say(line: str) -> None:
    sys.stdout.write(f"@@ {line}\n")
    sys.stdout.flush()


def park(point: str) -> None:
    say(f"parked {point}")
    threading.Event().wait()  # until SIGKILL


class Relay:
    def __init__(self, mode: str) -> None:
        self.mode = mode

    async def send(self, *, user_id: str, subject: str, body: str, idempotency_key: str) -> None:
        say(f"send {idempotency_key}")
        if self.mode == "send":
            park("send")
        await asyncio.to_thread(sys.stdin.readline)  # `stall`: held until the parent's `go`


async def main() -> None:
    order = json.loads(sys.stdin.readline())
    repo = SqlAlchemyRelationalRepository(order["dsn"], f"alert-chaos-{order['mode']}")
    if order["mode"] == "fire":
        store = WakingFiringStore(firing_store(repo), lambda: park("fire"))
        await fire(store, order["user"], order["alert"], ("in_app", "email"))
        return
    wins = Wins()
    d = dispatcher(repo, Relay(order["mode"]), worker=f"child-{order['mode']}",
                   lease_s=float(order.get("lease_s", 60)), batch=8, metric=wins)  # fmt: skip
    await d.run_once()
    say(f"done won={wins.sent}")
    await repo.dispose()


if __name__ == "__main__":
    asyncio.run(main())
