"""The sidecar's handlers for the five ops of §15.8 (ADR-0041 sections 1 and 3).

- `plan` checks the kind and the pinned recipient, pre-checks the run cap, and mints
  `<root>/<kind>/<uuid4>.age`, so the client never chooses a location.
- `run` is the run path of #3319 B1c. Here it checks the request (the kind, a well-formed name
  for it that does not exist yet, a backup the record does not know) and then answers
  `tool_failed`: this build carries no tool, so no artefact is produced and the run cap is not
  spent.
- `verify` checks only the location its own record holds for the backup, on one descriptor: the
  age header, then the SHA-256 of every byte, compared with the digest it recorded when the run
  finished. It records each conclusive outcome as a `checked` entry and answers the digest it
  computed. One at a time (`busy`).
- `remove` checks the location against its record and the floor, then renames the file into
  the quarantine and records it; one already quarantined or purged is `already_removed`.
- `restore` is validated and always answered `restore_not_available` until #3319 B2.

Every refusal is an `OpError` with a §15.8 code and no text.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Final
from uuid import uuid4

from cvbackup import age_format
from cvbackup.config import SidecarConfig
from cvbackup.floor import Floor, FloorRefusal
from cvbackup.ledger import Artefact, Ledger, LedgerUnreadable, quarantine_name, timestamp
from cvbackup.paths import PathFault, Root
from cvbackup.protocol import Request
from cvbackup.tasks import TaskLimit, spawn, uninterrupted

KINDS: Final = frozenset({"pg_dump", "config_bundle"})
CHUNK: Final = 1 << 20
Progress = Callable[[float], None]
Result = dict[str, object]


class OpError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sha256(fd: int, size: int, stop: threading.Event, report: Callable[[float], None]) -> str:
    """In a worker thread: the SHA-256 of `fd`'s bytes, read `CHUNK` at a time from offset 0;
    `stop` ends it within one chunk."""
    digest, offset = hashlib.sha256(), 0
    while chunk := os.pread(fd, CHUNK, offset):
        if stop.is_set():
            raise OpError("deadline")
        digest.update(chunk)
        offset += len(chunk)
        report(100.0 * min(offset, size) / size if size else 100.0)
    return digest.hexdigest()


class Ops:
    def __init__(
        self, config: SidecarConfig, root: Root, ledger: Ledger, floor: Floor, *,
        clock: Callable[[], datetime], new_name: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:  # fmt: skip
        self._config, self._root, self._ledger, self._floor = config, root, ledger, floor
        self._clock, self._new_name = clock, new_name
        self._verifying = asyncio.Lock()
        self._writing = asyncio.Lock()  # removals and sweeps, one at a time

    async def handle(self, request: Request, progress: Progress) -> Result:
        handler = {
            "plan": self._plan, "run": self._run, "verify": self._verify,
            "remove": self._remove, "restore": self._restore,
        }[request.op]  # fmt: skip
        try:
            return await handler(request, progress)
        except FloorRefusal as refusal:
            raise OpError(refusal.code) from None
        except LedgerUnreadable:
            raise OpError("ledger_unreadable") from None
        except PathFault as fault:
            raise OpError(fault.code) from None
        except OSError:  # the volume's read or sync, past the walk
            raise OpError("volume_unavailable") from None
        except TaskLimit:  # before any step: a removal's own entries append `inline`
            raise OpError("busy") from None

    async def sweep(self) -> int:
        async with self._writing:
            return await self._floor.sweep(self._clock())

    async def _plan(self, request: Request, _: Progress) -> Result:
        kind = request.args["kind"]
        if kind not in KINDS:
            raise OpError("kind_not_supported")
        ref = age_format.fingerprint(self._config.recipient)
        if not hmac.compare_digest(ref, self._config.pin):
            raise OpError("recipient_mismatch")
        self._floor.check_run(self._clock())
        location = f"{self._root.path}/{kind}/{self._new_name()}.age"
        return {"location": location, "encrypted": True, "encryption_ref": ref}

    async def _run(self, request: Request, _: Progress) -> Result:
        kind, location = request.args["kind"], request.args["location"]
        if kind not in KINDS:
            raise OpError("kind_not_supported")
        below = self._root.relative(location)
        if below is None or len(below) != 2 or below[0] != kind:
            raise OpError("bad_request")
        try:
            self._ledger.get(request.args["backup_id"])
        except KeyError:
            pass
        else:
            raise OpError("location_mismatch")  # a finished backup is never run again
        if await asyncio.to_thread(self._root.exists, location):
            raise OpError("location_mismatch")
        raise OpError("tool_failed")  # #3319 B1c: no tool in this build, nothing produced

    def _recorded(self, request: Request) -> Artefact:
        """The record's artefact for the request's backup, at the location it holds."""
        try:
            artefact = self._ledger.get(request.args["backup_id"])
        except KeyError:
            raise OpError("unknown_backup") from None
        if not hmac.compare_digest(artefact.location, request.args["location"]):
            raise OpError("location_mismatch")
        return artefact

    async def _verify(self, request: Request, progress: Progress) -> Result:
        artefact = self._recorded(request)
        if self._verifying.locked():
            raise OpError("busy")
        async with self._verifying:
            if artefact.state != "present":
                return await self._checked(artefact, "artefact_missing", None)
            try:
                fd, size = await asyncio.to_thread(self._root.open_artefact, artefact.location)
            except PathFault as fault:
                if fault.code == "artefact_missing":
                    return await self._checked(artefact, "artefact_missing", None)
                raise
            try:
                prefix = await asyncio.to_thread(os.pread, fd, age_format.MAX_HEADER, 0)
                if not age_format.header_ok(prefix, size):
                    return await self._checked(artefact, "header_malformed", None)
                digest = await self._hash(fd, size, progress)
            finally:
                os.close(fd)
            same = hmac.compare_digest(digest, artefact.digest)
            return await self._checked(artefact, "ok" if same else "digest_mismatch", digest)

    async def _hash(self, fd: int, size: int, progress: Progress) -> str:
        """The digest, off the loop; a cancel stops the thread and waits for it, so the caller
        closes the descriptor only once nothing reads it."""
        loop, stop = asyncio.get_running_loop(), threading.Event()

        def report(pct: float) -> None:
            loop.call_soon_threadsafe(progress, pct)

        hashing = spawn(asyncio.to_thread(_sha256, fd, size, stop, report), name="cvbackup.hash")
        try:
            return await asyncio.shield(hashing)
        except asyncio.CancelledError:
            stop.set()
            await asyncio.wait([hashing])
            raise
        except OSError:
            raise OpError("volume_unavailable") from None

    async def _checked(self, artefact: Artefact, outcome: str, digest: str | None) -> Result:
        await self._ledger.append("checked", artefact.backup_id, outcome=outcome, digest=digest)
        if outcome != "ok":
            raise OpError(outcome)
        return {"method": "checksum", "checksum_sha256": digest}

    async def _remove(self, request: Request, _: Progress) -> Result:
        """Whole or not at all: a cancel (the peer gone, the deadline) lets a removal it caught
        mid-way finish its rename and its entry, under the lock, so the record never misses a
        quarantined file."""
        return await uninterrupted(self._removal(request), name="cvbackup.remove")

    async def _removal(self, request: Request) -> Result:
        async with self._writing:
            artefact = self._recorded(request)
            if artefact.state != "present":
                after = artefact.purge_after or self._clock()
                return {"state": "already_removed", "purge_after": timestamp(after)}
            self._floor.check_remove(artefact)
            now = self._clock()
            name = quarantine_name(artefact.backup_id)
            moved = await asyncio.to_thread(self._root.quarantine, artefact.location, name)
            if not moved:  # nothing at its location: recorded gone, nothing left to purge
                await self._ledger.append("purged", artefact.backup_id, inline=True)
                return {"state": "already_removed", "purge_after": timestamp(now)}
            after = self._floor.purge_after(now)
            await self._ledger.append("quarantined", artefact.backup_id, inline=True, name=name,
                                      purge_after=timestamp(after))  # fmt: skip
            return {"state": "quarantined", "purge_after": timestamp(after)}

    async def _restore(self, request: Request, _: Progress) -> Result:
        raise OpError("restore_not_available")  # #3319 B2: the executor and the halt latch
