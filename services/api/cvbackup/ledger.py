"""The sidecar's own run record (ADR-0041 section 1, "the sidecar's own floor").

An append-only file on the backup volume, `<root>/.cvb/ledger.jsonl`: one canonical JSON line per
entry, chained by `seq` and `prev` (the SHA-256 of the line before), each append `fsync`ed before
it counts. The floor judges from it alone, never from a request or the API's catalogue:

- `started`: a run admitted (`kind`), counted against the run cap, so a restart does not reset it;
- `finished`: a run's artefact in place (`kind`, `location`, `digest`, `covers_to`, `size_bytes`);
- `checked`: one verification's own header and digest check (`outcome`, the `digest` it read);
- `quarantined`: a removal, renamed into the quarantine as `name`, purged after `purge_after`;
- `purged`: the quarantined file deleted, or found gone.

Replay at start checks every line, the chain and each entry's place in its backup's life. A
record that does not replay is unreadable, and stays so for this process: `verify`, `remove` and
the run cap then answer `ledger_unreadable` (fail closed), until the Owner repairs it on the host
(`check-ledger`, runbook `demo-host.md` §9); nothing truncates it.
An append that fails leaves it unreadable too, since its bytes may half exist.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Final

from cvbackup import protocol
from cvbackup.paths import LEDGER_DIR, PathFault, Root
from cvbackup.tasks import uninterrupted

FILE: Final = "ledger.jsonl"
GENESIS: Final = "0" * 64
_OPEN: Final = os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
_COMMON: Final = frozenset({"e", "seq", "prev", "at", "backup_id"})
_MEMBERS: Final[Mapping[str, frozenset[str]]] = {
    "started": _COMMON | {"kind"},
    "finished": _COMMON | {"kind", "location", "digest", "covers_to", "size_bytes"},
    "checked": _COMMON | {"outcome", "digest"},
    "quarantined": _COMMON | {"name", "purge_after"},
    "purged": _COMMON,
}
CHECK_OUTCOMES: Final = frozenset({"ok", "artefact_missing", "header_malformed", "digest_mismatch"})


class LedgerUnreadable(Exception):
    """The record does not replay, or an append failed: `ledger_unreadable`."""

    def __init__(self) -> None:
        super().__init__("ledger_unreadable")


def timestamp(at: datetime) -> str:
    """RFC 3339 in UTC with microseconds and `Z` (§15.8 `UtcTs`)."""
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_timestamp(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        at = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    return at if timestamp(at) == text else None


@dataclass(frozen=True, slots=True)
class Artefact:
    """One finished run, as the record holds it."""

    backup_id: str
    kind: str
    location: str
    digest: str
    covers_to: str
    seq: int  # of its `finished` entry: the order "newest" is judged by
    state: str = "present"  # `present`, `quarantined` or `purged`
    name: str | None = None  # its quarantine name
    purge_after: datetime | None = None


@dataclass(slots=True)
class _State:
    seq: int = 0
    prev: str = GENESIS
    artefacts: dict[str, Artefact] = field(default_factory=dict)
    started: list[datetime] = field(default_factory=list)
    started_ids: set[str] = field(default_factory=set)


def _valid(entry: object, state: _State) -> bool:
    """Whether `entry` may follow `state`: its members, their shapes and its place."""
    if not isinstance(entry, dict) or entry.get("e") not in _MEMBERS:
        return False
    kind = str(entry["e"])
    if set(entry) != _MEMBERS[kind] or entry["seq"] != state.seq + 1 or entry["prev"] != state.prev:
        return False
    if parse_timestamp(entry["at"]) is None or not protocol.is_uuid(entry["backup_id"]):
        return False
    known = state.artefacts.get(str(entry["backup_id"]))
    if kind == "started":
        return protocol.is_kind(entry["kind"]) and entry["backup_id"] not in state.started_ids
    if kind == "finished":
        size = entry["size_bytes"]
        return (
            known is None and protocol.is_kind(entry["kind"])
            and protocol.is_location(entry["location"]) and protocol.is_digest(entry["digest"])
            and parse_timestamp(entry["covers_to"]) is not None
            and type(size) is int and size > 0
        )  # fmt: skip
    if known is None:
        return False
    if kind == "checked":
        digest = entry["digest"]
        return entry["outcome"] in CHECK_OUTCOMES and (digest is None or protocol.is_digest(digest))
    if kind == "quarantined":
        name = entry["name"]
        return (
            known.state == "present" and isinstance(name, str)
            and name == quarantine_name(known.backup_id)
            and parse_timestamp(entry["purge_after"]) is not None
        )  # fmt: skip
    return known.state != "purged"  # `purged`: from the quarantine, or a file found gone


def _apply(entry: Mapping[str, object], line: bytes, state: _State) -> None:
    kind, backup_id = str(entry["e"]), str(entry["backup_id"])
    state.seq, state.prev = state.seq + 1, hashlib.sha256(line).hexdigest()
    if kind == "started":
        state.started.append(parse_timestamp(entry["at"]) or datetime.max.replace(tzinfo=UTC))
        state.started_ids.add(backup_id)
    elif kind == "finished":
        state.artefacts[backup_id] = Artefact(
            backup_id, str(entry["kind"]), str(entry["location"]), str(entry["digest"]),
            str(entry["covers_to"]), state.seq,
        )  # fmt: skip
    elif kind == "quarantined":
        known = state.artefacts[backup_id]
        after = parse_timestamp(entry["purge_after"])
        state.artefacts[backup_id] = replace(
            known, state="quarantined", name=str(entry["name"]), purge_after=after
        )
    elif kind == "purged":
        state.artefacts[backup_id] = replace(state.artefacts[backup_id], state="purged")


class Unreplayable(ValueError):
    """The record stops replaying at `line` (1-based): torn, malformed or out of its chain."""

    def __init__(self, line: int) -> None:
        super().__init__(f"line {line}")
        self.line = line


def replay(content: bytes) -> _State:
    """The state `content` replays to, else `Unreplayable` naming its first bad line."""
    state, lines = _State(), content.split(b"\n")
    if lines.pop() != b"":  # a last line without its newline was never acknowledged
        raise Unreplayable(len(lines) + 1)
    for number, line in enumerate(lines, 1):
        try:
            entry = protocol.loads(line) if line else None
        except (ValueError, protocol.ProtocolError):
            raise Unreplayable(number) from None
        if not (isinstance(entry, dict) and _valid(entry, state)):
            raise Unreplayable(number)
        _apply(entry, line, state)
    return state


def check(root: str) -> int:
    """The Owner's host check (runbook `demo-host.md` §9): how many entries the record at
    `<root>/.cvb/ledger.jsonl` holds, read only and never followed through a link; `Unreplayable`
    where it stops replaying, `FileNotFoundError` if there is none yet."""
    fd = os.open(os.path.join(root, LEDGER_DIR, FILE), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        return replay(_read_all(fd)).seq
    finally:
        os.close(fd)


def quarantine_name(backup_id: str) -> str:
    return f"{backup_id}.age"


class Ledger:
    """The record, replayed by `load` and appended to one entry at a time."""

    def __init__(self, root: Root, clock: Callable[[], datetime]) -> None:
        self._root, self._clock = root, clock
        self._state: _State | None = None
        self._fd = -1
        self._lock = asyncio.Lock()

    @property
    def readable(self) -> bool:
        return self._state is not None

    def _held(self) -> _State:
        if self._state is None:
            raise LedgerUnreadable
        return self._state

    async def load(self) -> None:
        """Open and replay the record; on any fault it stays unreadable."""
        self._state = None
        with contextlib.suppress(OSError, PathFault, ValueError):
            self._state = await asyncio.to_thread(self._replay)

    def _replay(self) -> _State:
        with self._root.directory((LEDGER_DIR,)) as directory:
            created = False
            try:
                fd = os.open(FILE, _OPEN & ~os.O_CREAT, dir_fd=directory)
            except FileNotFoundError:
                fd = os.open(FILE, _OPEN | os.O_EXCL, 0o600, dir_fd=directory)
                created = True
            if created:
                os.fsync(directory)
        try:
            info = os.fstat(fd)  # one regular file, as `paths.open_artefact` holds artefacts
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("not one regular file")
            state = replay(_read_all(fd))
        except (ValueError, OSError):
            os.close(fd)
            raise ValueError("does not replay") from None
        if self._fd >= 0:
            os.close(self._fd)
        self._fd = fd
        return state

    def get(self, backup_id: str) -> Artefact:
        """The finished run `backup_id` names, else `KeyError`."""
        return self._held().artefacts[backup_id]

    def newest(self, kind: str) -> str | None:
        """The backup id of the newest finished artefact of `kind` in the record."""
        runs = [a for a in self._held().artefacts.values() if a.kind == kind]
        return max(runs, key=lambda a: a.seq).backup_id if runs else None

    def started_since(self, since: datetime) -> int:
        return sum(1 for at in self._held().started if at > since)

    def due(self, now: datetime) -> list[Artefact]:
        """Quarantined artefacts whose grace is over."""
        return [
            a for a in self._held().artefacts.values()
            if a.state == "quarantined" and a.purge_after is not None and a.purge_after <= now
        ]  # fmt: skip

    async def append(self, entry: str, backup_id: str, *, inline: bool = False,
                     guard: Callable[[], None] = lambda: None,
                     **members: object) -> None:  # fmt: skip
        """Append one entry, `fsync`ed before this returns; its fault leaves the record
        unreadable (`LedgerUnreadable`). A cancel never cuts an append short (`uninterrupted`, or
        `inline` from a caller already uninterrupted): the entry still lands and counts. `guard`
        runs under the append's lock, so its decision and the entry are one step. Readers keep the
        durable state while the bytes are written; it advances only once they are durable."""
        work = self._append(entry, backup_id, members, guard)
        await (work if inline else uninterrupted(work, name="cvbackup.append"))

    async def _append(self, entry: str, backup_id: str, members: Mapping[str, object],
                      guard: Callable[[], None]) -> None:  # fmt: skip
        async with self._lock:
            state = self._held()
            guard()  # a decision the entry depends on, under the same lock
            line = protocol.dumps({
                "e": entry, "seq": state.seq + 1, "prev": state.prev,
                "at": timestamp(self._clock()), "backup_id": backup_id, **members,
            })  # fmt: skip
            decoded = protocol.loads(line)
            if not (isinstance(decoded, dict) and _valid(decoded, state)):
                raise ValueError("an entry the record refuses")  # a caller's bug, not the volume's
            try:
                await asyncio.to_thread(_write_all, self._fd, line + b"\n")
            except BaseException as fault:  # its bytes may half exist
                self._state = None
                if isinstance(fault, OSError):
                    raise LedgerUnreadable from None
                raise
            _apply(decoded, line, state)
            self._state = state

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1


def _read_all(fd: int) -> bytes:
    chunks, offset = [], 0
    while chunk := os.pread(fd, 1 << 20, offset):
        chunks.append(chunk)
        offset += len(chunk)
    return b"".join(chunks)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]
    os.fsync(fd)
