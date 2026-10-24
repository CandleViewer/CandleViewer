"""Fakes for the #492 recording tests (no I/O, no clock). `FakeRecorder` mirrors #2188's
`PolicyControlSurface` member for member, raises its errors, and serves reads over it. Like the
policy, it checks the actor and the settings first, then records each write through `audit` in
the policy's shape before the row changes (none on a raise, none for a change to nothing)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from candleviewer.recorder import control as rc
from candleviewer.recorder.errors import InvalidRecorderActorError, RecorderSymbolNotManualError
from candleviewer.recorder.errors import RecorderInvalidUpdateError as InvalidUpdate
from candleviewer.recorder.errors import RecorderSymbolLimitError as LimitError
from candleviewer.recorder.errors import RecorderSymbolNotRecordedError as NotRecorded
from candleviewer.recorder.models import Actor
from candleviewer.recorder.policy import RefusalCause, _check_settings
from candleviewer.recorder.sessions import DEFAULT_STREAMS

NOW: Final = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
GRACE: Final = timedelta(minutes=30)
STREAMS: Final = ("trades", "orderbook_delta", "tickers", "liquidations")  # the add's default


def _user(actor: Actor) -> None:
    if actor.kind != "user":
        raise InvalidRecorderActorError("a manual change needs a user actor")


class FakeRecorder:
    def __init__(self, max_symbols: int = 20) -> None:
        self.entries: dict[str, rc.RecordedEntry] = {}
        self.refused: dict[str, RefusalCause] = {}
        self.max_symbols = max_symbols
        self.status_fields: dict[str, Any] = {}  # `ControlStatus` beside its entries
        self.audit: Any = None  # the policy's injected `AuditSink`; `None`: no records
        self.adders: dict[str, str] = {}  # symbol -> the user who made it manual

    async def _record(self, action: str, symbol: str, actor: Actor, reason: str,
                      before: dict[str, str | None] | None = None,
                      **extra: str | bool | None) -> None:  # fmt: skip
        user, label = actor.id if actor.kind == "user" else None, f"{actor.kind}:{actor.id}"
        after = {"symbol": symbol, "reason": reason, "actor": actor.id, **extra}
        if self.audit is not None:  # the policy's `_audit_emit`, keyword for keyword
            await self.audit.emit(action, actor_label=label, actor_user_id=user,
                                  object_kind="recorded_symbol", object_id=symbol, reason=reason,
                                  before_state=before, after_state=after, env="demo",
                                  outcome="success")  # fmt: skip

    def put(self, symbol: str, *reasons: rc.RecordReason, **fields: Any) -> rc.RecordedEntry:
        """Seed (or replace) an entry recording for `reasons`; ids follow creation order."""
        old = self.entries.get(symbol)
        uid = old.id if old else f"e1000000-0000-4000-8000-{len(self.entries) + 1:012d}"
        new = rc.RecordedEntry(uid, symbol, reasons or ("manual",), "recording", lingering=False)
        self.entries[symbol] = replace(new, **fields)
        return self.entries[symbol]

    async def add_manual(
        self,
        symbol: str,
        actor: Actor,
        streams: tuple[str, ...] = (),
        depth: int | None = None,
        *,
        held_hidden: bool = False,
    ) -> None:
        _user(actor)
        _check_settings(streams, depth)  # the policy's own check, before any record
        if (old := self.entries.get(symbol)) and "manual" in old.reasons and not old.lingering:
            return  # the policy's no-op: no write, no record
        if old is None and len(self.entries) >= self.max_symbols:  # a re-add is never capped
            raise LimitError(f"max {self.max_symbols} recorded symbols")
        held = () if old is None or old.lingering else old.reasons
        # upsert_manual: the policy names its default streams; no depth keeps a promoted row's
        streams, depth = streams or DEFAULT_STREAMS, depth or (old.depth if old and held else 200)
        await self._record("recorder.start", symbol, actor, "manual",
                           trigger_ref=f"manual:{actor.id}")  # fmt: skip
        self.adders[symbol] = actor.id
        row = old or self.put(symbol, added_by=actor.id, state="starting")
        reasons = ("manual", *(r for r in held if r != "manual"))  # a re-add keeps the rest
        self.entries[symbol] = replace(row, reasons=reasons, streams=streams, depth=depth,
                                       added_by=actor.id, lingering=False,
                                       linger_until=None)  # fmt: skip

    async def remove_manual(self, symbol: str, actor: Actor) -> None:
        _user(actor)
        e = self.entries.get(symbol)
        if e is not None and "manual" in e.reasons and not e.lingering:
            rest = tuple(r for r in e.reasons if r != "manual")
            adder = self.adders.pop(symbol, e.added_by)
            await self._record("recorder.stop", symbol, actor, "manual",
                               trigger_ref=f"manual:{adder}")  # fmt: skip
            self.entries[symbol] = replace(e, reasons=rest or e.reasons, lingering=not rest,
                                           linger_until=None if rest else NOW + GRACE)  # fmt: skip

    async def set_pin(self, symbol: str, pinned: bool, actor: Actor) -> None:
        _user(actor)
        if (e := self.entries.get(symbol)) is None:  # no active row
            raise NotRecorded(symbol)
        if e.pinned == pinned:
            return
        await self._record("retention.change", symbol, actor, "pin" if pinned else "unpin",
                           pinned=pinned)  # fmt: skip
        if not pinned and e.state == "stopped":  # an idle row unpinned goes
            del self.entries[symbol]
        else:
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
        _check_settings(streams, depth)
        e = self.entries.get(symbol)
        if e is None or "manual" not in e.reasons or e.lingering:
            raise RecorderSymbolNotManualError(symbol)
        streams, depth = streams or e.streams, depth or e.depth
        if (streams, depth) == (e.streams, e.depth):
            return  # a change to nothing: no write, no record
        held = {"streams": ",".join(e.streams), "depth": None if e.depth is None else str(e.depth)}
        await self._record("recorder.update", symbol, actor, "manual", held,
                           streams=",".join(streams), depth=str(depth))  # fmt: skip
        self.entries[symbol] = replace(e, streams=streams, depth=depth)

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

    # The `RecordingControl` writes, by entry id, over the policy members above (as S9 maps them).
    def _symbol(self, entry_id: str) -> str | None:
        return next((s for s, e in self.entries.items() if e.id == entry_id), None)

    async def add(self, symbol: str, spec: rc.EntrySpec,
                  actor: Actor) -> tuple[rc.RecordedEntry, rc.RecordedEntry | None]:  # fmt: skip
        old = self.entries.get(symbol)
        streams, depth = (old.streams, old.depth) if old else (STREAMS, 200)
        await self.add_manual(symbol, actor, spec.streams or streams, spec.depth or depth)
        return await self._settle(symbol, spec, actor), old

    async def pin(self, entry_id: str, pinned: bool, actor: Actor, *,
                  retention_days: int | None = None) -> rc.RecordedEntry | None:  # fmt: skip
        """Unpin takes `retention_days` (none: the default); no active row: `None`, as S9 maps."""
        if (symbol := self._symbol(entry_id)) is None:
            return None
        kept = replace(self.entries[symbol], pinned=pinned,
                       retention_days=None if pinned else retention_days)  # fmt: skip
        try:
            await self.set_pin(symbol, pinned, actor)
        except NotRecorded:
            return None
        if symbol in self.entries:
            self.entries[symbol] = kept
        return kept

    async def update(
        self, entry_id: str, spec: rc.EntrySpec, actor: Actor
    ) -> rc.RecordedEntry | None:
        """Streams and depth through `update_manual`, as S9 maps its refusals: a symbol with no
        manual reason -> `ChangeRefused("not_manual")`; an invalid change -> its field's rule."""
        if (symbol := self._symbol(entry_id)) is None:
            return None
        if spec.streams is not None or spec.depth is not None:
            try:
                await self.update_manual(symbol, actor, streams=spec.streams, depth=spec.depth)
            except RecorderSymbolNotManualError:
                raise rc.ChangeRefused("not_manual") from None
            except InvalidUpdate:
                raise rc.ChangeRefused(*rc.setting_rule(spec.depth)) from None
        return await self._settle(symbol, spec, actor)

    async def remove(
        self, entry_id: str, actor: Actor, *, force: bool = False
    ) -> rc.RecordedEntry | None:
        """Ends the manual reason; refused, with nothing changed, while a trigger holds."""
        if (symbol := self._symbol(entry_id)) is None:
            return None
        causes = tuple(c for c in self.entries[symbol].refusals if c in rc.STOP_CAUSES)
        if causes and not force:
            raise rc.StopRefused(causes)
        await self.remove_manual(symbol, actor)
        return self.entries.get(symbol)

    async def _settle(self, symbol: str, spec: rc.EntrySpec, actor: Actor) -> rc.RecordedEntry:
        e = self.entries[symbol]
        if spec.pinned is not None:
            return await self.pin(e.id, spec.pinned, actor, retention_days=spec.retention_days) or e
        if spec.retention_days is not None:
            self.entries[symbol] = e = replace(e, retention_days=spec.retention_days)
        return e

    async def status(self) -> rc.ControlStatus:
        entries = tuple(e for _, e in sorted(self.entries.items()))
        return rc.ControlStatus(entries, **self.status_fields)


class EmptyRows:
    """A fresh database's row port: nothing recorded yet."""

    async def recorded_page(self, **query: object) -> list[dict[str, Any]]:
        return []

    async def recorded_row(self, entry_id: str, **query: object) -> dict[str, Any] | None:
        return None
