"""Fakes for the #492 recording tests (no I/O, no clock). `FakeRecorder` mirrors #2188's
`PolicyControlSurface` member for member, raises its errors, and serves reads over it. Like the
policy, it checks the actor and the settings first, then records each write through `audit` in
the policy's shape before the row changes (none on a raise, none for a change to nothing)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from candleviewer.recorder import control as rc
from candleviewer.recorder.errors import (
    InvalidRecorderActorError,
    RecorderRelaxRefusedError,
    RecorderSymbolNotManualError,
)
from candleviewer.recorder.errors import RecorderInvalidUpdateError as InvalidUpdate
from candleviewer.recorder.errors import RecorderSymbolLimitError as LimitError
from candleviewer.recorder.errors import RecorderSymbolNotRecordedError as NotRecorded
from candleviewer.recorder.models import Actor
from candleviewer.recorder.policy import (
    PolicyConfig,
    RefusalCause,
    StartRefused,
    _check_retention,
    _check_settings,
    _lowers,
    _str,
)
from candleviewer.recorder.sessions import DEFAULT_STREAMS

NOW: Final = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
GRACE: Final = timedelta(minutes=30)
STREAMS: Final = ("trades", "orderbook_delta", "tickers", "liquidations")  # the add's default
DEFAULT_DAYS: Final = PolicyConfig().default_retention_days  # what a NULL keeps


def _user(actor: Actor) -> None:
    if actor.kind != "user":
        raise InvalidRecorderActorError("a manual change needs a user actor")


class FakeRecorder:
    def __init__(self, max_symbols: int = 20) -> None:
        self.entries: dict[str, rc.RecordedEntry] = {}
        self.refused: dict[str, RefusalCause] = {}
        self.refused_reasons: dict[str, tuple[rc.RecordReason, ...]] = {}  # default: chart_open
        self.max_symbols = max_symbols
        self.status_fields: dict[str, Any] = {}  # `ControlStatus` beside its entries
        self.audit: Any = None  # the policy's injected `AuditSink`; `None`: no records
        self.adders: dict[str, str] = {}  # symbol -> the user who made it manual

    async def _record(self, action: str, symbol: str, actor: Actor, reason: str,
                      before: Mapping[str, str | bool | None] | None = None, *,
                      outcome: str = "success", **extra: str | bool | None) -> None:  # fmt: skip
        user, label = actor.id if actor.kind == "user" else None, f"{actor.kind}:{actor.id}"
        after = {"symbol": symbol, "reason": reason, "actor": actor.id, **extra}
        if self.audit is not None:  # the policy's `_audit_emit`, keyword for keyword
            await self.audit.emit(action, actor_label=label, actor_user_id=user,
                                  object_kind="recorded_symbol", object_id=symbol, reason=reason,
                                  before_state=before, after_state=after, env="demo",
                                  outcome=outcome)  # fmt: skip

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

    def relax_allowed(self, symbol: str, *, restricted: bool) -> bool:
        e = self.entries.get(symbol)
        return restricted is False or e is None or not rc.HIDDEN_CAUSES.intersection(e.reasons)

    async def _refuse_relax(self, symbol: str, actor: Actor, restricted: bool) -> None:
        """The policy's refusal: the denied twin, ids only, then the error; nothing else."""
        if not self.relax_allowed(symbol, restricted=restricted):
            await self._record("retention.change", symbol, actor, "relax_refused",
                               outcome="denied")  # fmt: skip
            raise RecorderRelaxRefusedError

    async def set_pin(self, symbol: str, pinned: bool, actor: Actor, *, restricted: bool,
                      retention_days: int | None = None) -> None:  # fmt: skip
        _user(actor)
        _check_retention(retention_days)
        if (e := self.entries.get(symbol)) is None:  # no active row
            raise NotRecorded(symbol)
        if e.pinned == pinned:
            return
        if not pinned:
            await self._refuse_relax(symbol, actor, restricted)
        days = None if pinned else retention_days  # a pin nulls the days (22)
        await self._record("retention.change", symbol, actor, "pin" if pinned else "unpin",
                           {"pinned": e.pinned, "retention_days": _str(e.retention_days)},
                           pinned=pinned, retention_days=_str(days))  # fmt: skip
        if not pinned and e.state == "stopped":  # an idle row unpinned goes
            del self.entries[symbol]
        else:
            self.entries[symbol] = replace(e, pinned=pinned, retention_days=days)

    async def set_retention(self, symbol: str, retention_days: int | None, actor: Actor, *,
                            restricted: bool) -> None:  # fmt: skip
        _user(actor)
        _check_retention(retention_days)
        if (e := self.entries.get(symbol)) is None:  # no active row
            raise NotRecorded(symbol)
        if e.retention_days == retention_days:
            return  # a change to nothing: no write, no record
        if _lowers(e.pinned, e.retention_days, retention_days, DEFAULT_DAYS):
            await self._refuse_relax(symbol, actor, restricted)
        await self._record("retention.change", symbol, actor, "retention",
                           {"retention_days": _str(e.retention_days)},
                           retention_days=_str(retention_days))  # fmt: skip
        self.entries[symbol] = replace(e, retention_days=retention_days)

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

    def start_refused(self) -> tuple[StartRefused, ...]:
        return tuple(StartRefused(sym, cause, self.refused_reasons.get(sym, ("chart_open",)))
                     for sym, cause in sorted(self.refused.items()))  # fmt: skip

    def chart_open(self, symbol: str) -> bool:
        return symbol in self.entries and "chart_open" in self.entries[symbol].reasons

    @staticmethod
    def _target(e: rc.RecordedEntry, spec: rc.EntrySpec) -> tuple[bool, int | None]:
        """As S9's control: a pin nulls the days; an unpin takes the named ones (or none)."""
        pinned = e.pinned if spec.pinned is None else spec.pinned
        if pinned:
            return True, None
        if (
            spec.retention_days is not None
            or spec.default_retention
            or (spec.pinned is False and e.pinned)
        ):
            return False, spec.retention_days
        return False, e.retention_days

    def _relax(self, e: rc.RecordedEntry, spec: rc.EntrySpec, restricted: bool) -> None:
        """The port's check ahead of any write (unrecorded: the route records it)."""
        pinned, days = self._target(e, spec)
        unpin = e.pinned and not pinned
        lower = not pinned and (days or DEFAULT_DAYS) < (e.retention_days or DEFAULT_DAYS)
        if (unpin or lower) and not self.relax_allowed(e.symbol, restricted=restricted):
            raise rc.RelaxRefused(e.symbol, recorded=False)

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

    async def add(self, symbol: str, spec: rc.EntrySpec, actor: Actor, *, restricted: bool,
                  ) -> tuple[rc.RecordedEntry, rc.RecordedEntry | None]:  # fmt: skip
        old = self.entries.get(symbol)
        streams, depth = (old.streams, old.depth) if old else (STREAMS, 200)
        join = restricted and old is not None and rc.restricted_view(old) is None
        if old is not None and not join:  # as S9's control: before any write
            self._relax(old, spec, restricted)
        await self.add_manual(symbol, actor, spec.streams or streams, spec.depth or depth,
                              held_hidden=join)  # fmt: skip
        return await self._settle(symbol, spec, actor, restricted) or self.entries[symbol], old

    async def pin(self, entry_id: str, pinned: bool, actor: Actor, *, restricted: bool,
                  retention_days: int | None = None) -> rc.RecordedEntry | None:  # fmt: skip
        """Unpin takes `retention_days` (none: the default); no active row: `None`, as S9 maps."""
        if (symbol := self._symbol(entry_id)) is None:
            return None
        spec = rc.EntrySpec(pinned=pinned, retention_days=retention_days)
        self._relax(self.entries[symbol], spec, restricted)
        return await self._settle(symbol, spec, actor, restricted)

    async def update(
        self, entry_id: str, spec: rc.EntrySpec, actor: Actor, *, restricted: bool
    ) -> rc.RecordedEntry | None:
        """Streams and depth through `update_manual`, as S9 maps its refusals: a symbol with no
        manual reason -> `ChangeRefused("not_manual")`; an invalid change -> its field's rule."""
        if (symbol := self._symbol(entry_id)) is None:
            return None
        self._relax(self.entries[symbol], spec, restricted)
        if spec.streams is not None or spec.depth is not None:
            try:
                await self.update_manual(symbol, actor, streams=spec.streams, depth=spec.depth)
            except RecorderSymbolNotManualError:
                raise rc.ChangeRefused("not_manual") from None
            except InvalidUpdate:
                raise rc.ChangeRefused(*rc.setting_rule(spec.depth)) from None
        return await self._settle(symbol, spec, actor, restricted)

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

    async def _settle(self, symbol: str, spec: rc.EntrySpec, actor: Actor,
                      restricted: bool) -> rc.RecordedEntry | None:  # fmt: skip
        """The pin, else the retention, through the policy members, as S9's control does."""
        e = self.entries[symbol]
        pinned, days = self._target(e, spec)
        try:
            if pinned != e.pinned:
                await self.set_pin(symbol, pinned, actor, restricted=restricted,
                                   retention_days=days)  # fmt: skip
            elif days != e.retention_days:
                await self.set_retention(symbol, days, actor, restricted=restricted)
        except NotRecorded:
            return None
        except RecorderRelaxRefusedError:
            raise rc.RelaxRefused(symbol, recorded=True) from None
        return self.entries.get(symbol) or replace(e, pinned=pinned, retention_days=days)

    async def status(self) -> rc.ControlStatus:
        entries = tuple(e for _, e in sorted(self.entries.items()))
        return rc.ControlStatus(entries, **self.status_fields)


class EmptyRows:
    """A fresh database's row port: nothing recorded yet."""

    async def recorded_page(self, **query: object) -> list[dict[str, Any]]:
        return []

    async def recorded_row(self, entry_id: str, **query: object) -> dict[str, Any] | None:
        return None
