"""The two `DrainJournal` subjects of the contract suite's journal cases (E50-T62 #3793).

`InMemoryDrainJournal` is the reference. `RowStoreDrainJournal` is the Postgres journal, here over
`FakeJournalRows`, an in-memory `JournalRowStore` that keeps `machine_drain_journal`'s semantics:
an append inserts the new `send_id`s and reports each one that already has a row (stamped or not,
and whether its stored `payload` text, `json.dumps` as SQLAlchemy binds it, is the entry's),
unreplayed rows come back in `ordinal` order, and a stamp is set once. Both subjects expose
`rows(key)` and `stamped(key)` for the asserts, and take the writes that go around the persister
for the refusal cases (24 §17.6): `plant` (cv_app's own INSERT, stamped or not), `tamper` (the
table owner rewriting a column) and `drop` (a row removed).
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from xstate_statemachine import Interpreter

from candleviewer.statechart.persistence import (
    DrainSeal,
    InMemoryDrainJournal,
    JournalConflict,
    JournalEntry,
    MachineKey,
    ReplayReport,
    RowStoreDrainJournal,
)


class JournalSubject(Protocol):
    async def append(
        self, key: MachineKey, entries: Sequence[JournalEntry]
    ) -> Sequence[JournalConflict]: ...

    async def list_unreplayed(self, key: MachineKey) -> Sequence[JournalEntry]: ...

    async def replay_once(
        self, key: MachineKey, interp: Interpreter[Any], drain: DrainSeal
    ) -> ReplayReport: ...

    def rows(self, key: MachineKey) -> list[JournalEntry]: ...

    def stamped(self, key: MachineKey) -> set[str]: ...

    def plant(self, key: MachineKey, entry: JournalEntry, *, stamped: bool = False) -> None: ...

    def tamper(self, key: MachineKey, send_id: str, **changes: Any) -> None: ...

    def drop(self, key: MachineKey, send_id: str) -> None: ...


class InMemorySubject(InMemoryDrainJournal):
    """The reference, plus the out-of-band writes on its (private) tables."""

    def stamped(self, key: MachineKey) -> set[str]:
        return {send_id for k, send_id in self._replayed if k == key}

    def plant(self, key: MachineKey, entry: JournalEntry, *, stamped: bool = False) -> None:
        self._rows.setdefault(key, {})[entry.send_id] = entry
        if stamped:
            self._replayed.add((key, entry.send_id))

    def tamper(self, key: MachineKey, send_id: str, **changes: Any) -> None:
        rows = self._rows[key]
        rows[send_id] = dataclasses.replace(rows[send_id], **changes)

    def drop(self, key: MachineKey, send_id: str) -> None:
        del self._rows[key][send_id]


class FakeJournalRows:
    def __init__(self) -> None:
        self._rows: dict[MachineKey, dict[str, JournalEntry]] = {}
        self._stamped: set[tuple[MachineKey, str]] = set()

    async def append(
        self, key: MachineKey, entries: Sequence[JournalEntry]
    ) -> list[JournalConflict]:
        rows, conflicts = self._rows.setdefault(key, {}), []
        for entry in entries:
            held = rows.get(entry.send_id)
            if held is None:
                rows[entry.send_id] = entry
                continue
            same = json.dumps(held.record) == json.dumps(entry.record)
            stamped = (key, entry.send_id) in self._stamped
            conflicts.append(JournalConflict(entry.send_id, stamped, same))
        return conflicts

    async def list_unreplayed(self, key: MachineKey) -> Sequence[JournalEntry]:
        return [e for e in self.rows(key) if (key, e.send_id) not in self._stamped]

    async def present(self, key: MachineKey, send_ids: Sequence[str]) -> frozenset[str]:
        held = self._rows.get(key, {})
        return frozenset(send_id for send_id in send_ids if send_id in held)

    async def mark_replayed(self, key: MachineKey, send_ids: Sequence[str]) -> None:
        self._stamped.update((key, send_id) for send_id in send_ids)

    def rows(self, key: MachineKey) -> list[JournalEntry]:
        return sorted(self._rows.get(key, {}).values(), key=lambda e: e.ordinal)


class RowStoreSubject:
    """`RowStoreDrainJournal` over `FakeJournalRows`, with the reference's helpers."""

    def __init__(self) -> None:
        self.store = FakeJournalRows()
        self.journal = RowStoreDrainJournal(self.store)

    async def append(
        self, key: MachineKey, entries: Sequence[JournalEntry]
    ) -> Sequence[JournalConflict]:
        return await self.journal.append(key, entries)

    async def list_unreplayed(self, key: MachineKey) -> Sequence[JournalEntry]:
        return await self.journal.list_unreplayed(key)

    async def replay_once(
        self, key: MachineKey, interp: Interpreter[Any], drain: DrainSeal
    ) -> ReplayReport:
        return await self.journal.replay_once(key, interp, drain)

    def rows(self, key: MachineKey) -> list[JournalEntry]:
        return self.store.rows(key)

    def stamped(self, key: MachineKey) -> set[str]:
        return {send_id for k, send_id in self.store._stamped if k == key}

    def plant(self, key: MachineKey, entry: JournalEntry, *, stamped: bool = False) -> None:
        self.store._rows.setdefault(key, {})[entry.send_id] = entry
        if stamped:
            self.store._stamped.add((key, entry.send_id))

    def tamper(self, key: MachineKey, send_id: str, **changes: Any) -> None:
        rows = self.store._rows[key]
        rows[send_id] = dataclasses.replace(rows[send_id], **changes)

    def drop(self, key: MachineKey, send_id: str) -> None:
        del self.store._rows[key][send_id]


JOURNALS: dict[str, Callable[[], JournalSubject]] = {
    "in-memory": InMemorySubject,
    "row-store": RowStoreSubject,
}
