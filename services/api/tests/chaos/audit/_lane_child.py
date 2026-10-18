"""A cv-api stand-in for C-13.6 scenario 12 (#3009, ADR-0037): it boots `AuditService` with its lane
over Postgres, journals sign-outs through the façade, then parks inside the append or the marker
write that the parent named, says so on stdout and waits for its SIGKILL. The parent's order (the
lane key, the DSN and the paths) comes on stdin, never in argv, the environment or a file.

Kill points, each in the lane's worker thread while it holds the lane lock:
- `append-torn`: half of the last record's frame is written;
- `append-unsynced`: all of it is written, and its fsync never runs;
- `drain-marker`: the drain has handed every record over and Postgres has committed them, and the
  new marker is in `confirmed.tmp`, not yet renamed over `confirmed`.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from candleviewer.audit import lane_journal as lj
from candleviewer.audit.service import AuditService
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: The sign-outs journaled before the kill; the lane's two boot rows are seq 1 and 2.
RECORDS = 4


def say(line: str) -> None:
    sys.stdout.write(f"@@ {line}\n")
    sys.stdout.flush()


def park(point: str) -> None:
    say(f"parked {point}")
    threading.Event().wait()  # until SIGKILL


def arm(point: str, victim: bytes) -> None:
    """Patch the lane's file seam (`LaneFiles`) for this process's lifetime."""
    if point.startswith("append-"):
        write = lj.LaneFiles.write

        def writing(files: lj.LaneFiles, fd: int, data: bytes) -> None:
            if victim in data:
                write(files, fd, data if point == "append-unsynced" else data[: len(data) // 2])
                park(point)
            write(files, fd, data)

        mock.patch.object(lj.LaneFiles, "write", writing).start()
        return
    mark = lj.LaneFiles.mark

    def marking(files: lj.LaneFiles, body: bytes) -> None:
        if json.loads(body.split(b"\n", 1)[0])["next_seq"] > RECORDS + 2:  # past every record
            files._put(files.dir / "confirmed.tmp", body)
            park(point)
        mark(files, body)

    mock.patch.object(lj.LaneFiles, "mark", marking).start()


async def main() -> None:
    order = json.loads(sys.stdin.readline())
    key, tag, point = bytes.fromhex(order["key"]), order["tag"], order["point"]
    arm(point, f'"object_id":"{tag}-victim"'.encode())
    relational = SqlAlchemyRelationalRepository(order["dsn"], "lane-chaos-child")
    svc = AuditService(SqlAlchemyAuditRepository(relational), lane_keys=lambda: (key, None))
    svc.use_lane_flag(lambda: True)
    wal = f"{order['wal']}/audit.wal"
    settings = SimpleNamespace(audit_wal_path=wal, audit_page_structure_budget=50_000)
    await svc.start(cast(Any, SimpleNamespace(settings=settings)))
    for n in range(RECORDS):
        await svc.lane.emit("auth.logout", actor_label="owner", object_id=f"{tag}-{n}")
        say(f"acked {tag}-{n}")
    if point.startswith("append-"):
        # Straight to the lane: the façade's wait would fall back to the sink while the append
        # is parked, and the record the kill lands in must be one nobody saw acknowledged.
        record = svc.writer.build("auth.logout", actor_label="owner", object_id=f"{tag}-victim")
        assert svc._lane is not None
        await svc._lane.append(record)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
