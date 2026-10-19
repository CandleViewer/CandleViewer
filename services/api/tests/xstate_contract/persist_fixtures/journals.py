"""The two `DrainJournal` subjects of the contract suite's journal cases (E50-T62 #3793).

`InMemoryDrainJournal` is the reference. `RowStoreDrainJournal` is the Postgres journal's replay,
here over `FakeJournalRows`, an in-memory `JournalRowStore` that keeps `machine_drain_journal`'s
semantics: an append dedupes on `send_id` (`ON CONFLICT DO NOTHING`), unreplayed rows come back
in `ordinal` order, and a stamp is set once. Both expose `rows(key)` for the asserts.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

from xstate_statemachine import Interpreter

from candleviewer.statechart.persistence import (
    InMemoryDrainJournal,
    JournalEntry,
    MachineKey,
    RowStoreDrainJournal,
)


class JournalSubject(Protocol):
    async def append(self, key: MachineKey, entries: Sequence[JournalEntry]) -> None: ...

    async def replay_once(self, key: MachineKey, interp: Interpreter[Any]) -> int: ...

    def rows(self, key: MachineKey) -> list[JournalEntry]: ...


class FakeJournalRows:
    def __init__(self) -> None:
        self._rows: dict[MachineKey, dict[str, JournalEntry]] = {}
        self._stamped: set[tuple[MachineKey, str]] = set()

    async def append(self, key: MachineKey, entries: Sequence[JournalEntry]) -> None:
        rows = self._rows.setdefault(key, {})
        for entry in entries:
            rows.setdefault(entry.send_id, entry)

    async def list_unreplayed(self, key: MachineKey) -> Sequence[JournalEntry]:
        return [e for e in self.rows(key) if (key, e.send_id) not in self._stamped]

    async def mark_replayed(self, key: MachineKey, send_ids: Sequence[str]) -> None:
        self._stamped.update((key, send_id) for send_id in send_ids)

    def rows(self, key: MachineKey) -> list[JournalEntry]:
        return sorted(self._rows.get(key, {}).values(), key=lambda e: e.ordinal)


class RowStoreSubject:
    """`RowStoreDrainJournal` over `FakeJournalRows`, with the reference's `rows(key)`."""

    def __init__(self) -> None:
        self.store = FakeJournalRows()
        self.journal = RowStoreDrainJournal(self.store)

    async def append(self, key: MachineKey, entries: Sequence[JournalEntry]) -> None:
        await self.journal.append(key, entries)

    async def replay_once(self, key: MachineKey, interp: Interpreter[Any]) -> int:
        return await self.journal.replay_once(key, interp)

    def rows(self, key: MachineKey) -> list[JournalEntry]:
        return self.store.rows(key)


JOURNALS: dict[str, Callable[[], JournalSubject]] = {
    "in-memory": InMemoryDrainJournal,
    "row-store": RowStoreSubject,
}
