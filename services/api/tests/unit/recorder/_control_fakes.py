"""Fakes for the #492 recording tests (no I/O, no clock). `FakeRecorder` mirrors #2188's agreed
`PolicyControlSurface` member for member until its S2b and S3 land, and serves reads over it."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from candleviewer.recorder import control as rc
from candleviewer.recorder.errors import InvalidRecorderActorError, RecorderError
from candleviewer.recorder.errors import RecorderSymbolLimitError as LimitError
from candleviewer.recorder.models import Actor
from candleviewer.recorder.policy import RefusalCause

NOW: Final = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
GRACE: Final = timedelta(minutes=30)


class RecorderSymbolNotManualError(RecorderError):
    """Mirrors #2188 S2b's `candleviewer.recorder.errors.RecorderSymbolNotManualError`."""


def _user(actor: Actor) -> None:
    if actor.kind != "user":
        raise InvalidRecorderActorError("a manual change needs a user actor")


class FakeRecorder:
    def __init__(self, max_symbols: int = 20) -> None:
        self.entries: dict[str, rc.RecordedEntry] = {}
        self.refused: dict[str, RefusalCause] = {}
        self.max_symbols = max_symbols
        self.status_fields: dict[str, Any] = {}  # `ControlStatus` beside its entries

    def put(self, symbol: str, *reasons: rc.RecordReason, **fields: Any) -> rc.RecordedEntry:
        """Seed (or replace) an entry recording for `reasons`; ids follow creation order."""
        old = self.entries.get(symbol)
        uid = old.id if old else f"e1000000-0000-4000-8000-{len(self.entries) + 1:012d}"
        new = rc.RecordedEntry(uid, symbol, reasons or ("manual",), "recording", lingering=False)
        self.entries[symbol] = replace(new, **fields)
        return self.entries[symbol]

    async def add_manual(
        self, symbol: str, actor: Actor, streams: tuple[str, ...] = (), depth: int | None = None
    ) -> None:
        _user(actor)
        old = self.entries.get(symbol)
        if old is None and len(self.entries) >= self.max_symbols:  # a re-add is never capped
            raise LimitError(f"max {self.max_symbols} recorded symbols")
        held = () if old is None or old.lingering else old.reasons
        kept = {"pinned": old.pinned, "added_by": old.added_by} if old else {"added_by": actor.id}
        self.put(symbol, "manual", *(r for r in held if r != "manual"),
                 streams=streams or ("trades",), depth=depth or 200, **kept)  # fmt: skip

    async def remove_manual(self, symbol: str, actor: Actor) -> None:
        e = self.entries.get(symbol)
        if e is not None and "manual" in e.reasons and not e.lingering:
            rest = tuple(r for r in e.reasons if r != "manual")
            self.entries[symbol] = replace(e, reasons=rest or e.reasons, lingering=not rest,
                                           linger_until=None if rest else NOW + GRACE)  # fmt: skip

    async def set_pin(self, symbol: str, pinned: bool, actor: Actor) -> None:
        e = self.entries.get(symbol)
        if e is not None and not pinned and e.state == "stopped":  # an idle row unpinned goes
            del self.entries[symbol]
        elif e is not None:
            self.entries[symbol] = replace(e, pinned=pinned)

    def lapse(self, symbol: str) -> None:
        """The grace window ends: a pinned row is demoted and kept, `stopped`; another goes."""
        e = self.entries.pop(symbol)
        if e.pinned:
            self.entries[symbol] = replace(e, state="stopped", lingering=False, linger_until=None)

    async def update_manual(self, symbol: str, actor: Actor, *,
                            streams: tuple[str, ...] | None = None,
                            depth: int | None = None) -> None:  # fmt: skip
        _user(actor)
        e = self.entries.get(symbol)
        if e is None or "manual" not in e.reasons or e.lingering:
            raise RecorderSymbolNotManualError(symbol)
        self.entries[symbol] = replace(e, streams=streams or e.streams, depth=depth or e.depth)

    def position_open(self, symbol: str) -> bool:
        return symbol in self.entries and "position_open" in self.entries[symbol].reasons

    def linger_until(self, symbol: str) -> datetime | None:
        return None if (e := self.entries.get(symbol)) is None else e.linger_until

    def start_refusal(self, symbol: str) -> RefusalCause | None:
        return self.refused.get(symbol)

    def chart_open(self, symbol: str) -> bool:
        return symbol in self.entries and "chart_open" in self.entries[symbol].reasons

    async def list(self, query: rc.EntryQuery) -> rc.EntryPage:
        q = query
        hits = [
            e for _, e in sorted(self.entries.items())
            if q.state in (None, e.state) and q.reason in (None, e.reason)
            and q.pinned in (None, e.pinned) and (q.after is None or (e.symbol, e.id) > q.after)
            and not (q.hidden and set(e.reasons) <= q.hidden)
        ]  # fmt: skip
        return rc.EntryPage(tuple(hits[: q.limit]), len(hits) > q.limit)

    async def get(self, entry_id: str) -> rc.RecordedEntry | None:
        return next((e for e in self.entries.values() if e.id == entry_id), None)

    async def status(self) -> rc.ControlStatus:
        entries = tuple(e for _, e in sorted(self.entries.items()))
        return rc.ControlStatus(entries, **self.status_fields)


class EmptyRows:
    """A fresh database's row port: nothing recorded yet."""

    async def recorded_page(self, **query: object) -> list[dict[str, Any]]:
        return []

    async def recorded_row(self, entry_id: str, **query: object) -> dict[str, Any] | None:
        return None
