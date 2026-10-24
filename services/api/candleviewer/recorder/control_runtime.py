"""`RuntimeRecordingControl`: the `RecordingControl` over the composed recorder runtime (E16-T08
S9, #492), bound once #2188 puts its `RecorderWiring` on the app context.

Reads are the stored rows of the wiring's env (C-2.11), each completed from the policy's O(1)
accessors: a live chart or position adds its reason and refuses a stop, `start_refusal` heads
`refusals`, `linger_until` (the policy's wall clock) marks a lingering row. Status entries carry
the STORED row's streams and depth, never the policy's `()`/`None`. A row the stop soft-removed
stays listed in the status, and readable by id, while the policy says it lingers. Rows and resyncs
count over a rolling hour (`HourWindows`, bounded), fed by the ingestion feed through `note`.

Writes go through the policy, which records each ahead of its store (C-2.9), a pin, an unpin and
a retention change included (#2188 S3c). The caller's view (`restricted`) comes from the
server-side principal only: an add onto a row it hides is a join (`held_hidden=True`, the row's
own streams and depth, no other setting changed), and an unpin or a lower retention it does not
cover raises `RelaxRefused` before any write: checked here first, so no other part of a change
lands (the route records it), and by the policy again, which records its own refusal. This module
never calls the policy's `tick`: the lifespan drives it, so no record carries a request's id."""

from __future__ import annotations

import math
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Protocol

from candleviewer.recorder import control as rc
from candleviewer.recorder.errors import (
    RecorderError,
    RecorderInvalidUpdateError,
    RecorderSymbolNotManualError,
    RecorderSymbolNotRecordedError,
)
from candleviewer.recorder.models import Actor
from candleviewer.recorder.policy import PolicyConfig, RefusalCause
from candleviewer.recorder.status import Budget

#: Reasons, top first (`RecordReason`); a live position outranks a chart (`RecordRefusal`).
_ORDER: Final[tuple[rc.RecordReason, ...]] = (
    "manual", "position_open", "chart_open", "rule_dependency", "alert_dependency",
)  # fmt: skip
_STOPS: Final[tuple[rc.Refusal, ...]] = ("position_open", "chart_open")
_PAGE: Final = 100
#: Pages read for one full listing: the policy's chart bound plus its protected one (C-2.18).
_MAX_PAGES: Final = 21
#: Symbols counted, and stopped rows remembered, at most (the least recently seen go first).
MAX_SYMBOLS: Final = 1024
_MINUTE_S: Final = 60
_HOUR_MINUTES: Final = 60


class RecorderRelaxRefusedError(RecorderError):
    """Stand-in for #2188 S3c's error of this name in `recorder.errors` (swapped at the rebase):
    the policy refused an unpin or a lower retention, wrote its denied record, changed nothing."""


class RuntimePolicy(Protocol):
    """#2188 S3c's `PolicyControlSurface` as the orchestrator approved it (12:42Z), until it is on
    main: the S2b/S3b members, `set_pin` with the view and the unpin's retention, `set_retention`
    and `relax_allowed`. `restricted` is keyword-only and required: the server-side principal's
    view (C-12.4). Each write records `retention.change` ahead of its store; a refused relax
    raises `RecorderRelaxRefusedError` before any write, after its denied record."""

    async def add_manual(
        self,
        symbol: str,
        actor: Actor,
        streams: tuple[str, ...] = (),
        depth: int | None = None,
        *,
        held_hidden: bool = False,
    ) -> None: ...
    async def remove_manual(self, symbol: str, actor: Actor) -> None: ...
    async def set_pin(
        self,
        symbol: str,
        pinned: bool,
        actor: Actor,
        *,
        restricted: bool,
        retention_days: int | None = None,
    ) -> None: ...
    async def set_retention(
        self, symbol: str, retention_days: int | None, actor: Actor, *, restricted: bool
    ) -> None: ...
    async def update_manual(
        self,
        symbol: str,
        actor: Actor,
        *,
        streams: tuple[str, ...] | None = None,
        depth: int | None = None,
    ) -> None: ...
    def position_open(self, symbol: str) -> bool: ...
    def linger_until(self, symbol: str) -> datetime | None: ...
    def start_refusal(self, symbol: str) -> RefusalCause | None: ...
    def chart_open(self, symbol: str) -> bool: ...
    def relax_allowed(self, symbol: str, *, restricted: bool) -> bool: ...


class RecorderWiring(Protocol):
    """#2188 S4b's one frozen value: the composed policy, the rows, the budget and the env."""

    @property
    def policy(self) -> RuntimePolicy: ...
    @property
    def rows(self) -> rc.RecordedRows: ...
    @property
    def budget(self) -> Budget | None: ...
    @property
    def env(self) -> str: ...


@dataclass
class _Counts:
    minutes: deque[list[int]]  # [minute, rows, resyncs], oldest first, at most an hour's
    last_event_at: datetime | None = None


class HourWindows:
    """Rows and resyncs per symbol over the last hour, in one-minute buckets: at most 60 a
    symbol and `max_symbols` symbols (C-2.18); the clock is injected."""

    def __init__(self, now: Callable[[], datetime], *, max_symbols: int = MAX_SYMBOLS) -> None:
        self._now, self._cap = now, max_symbols
        self._symbols: OrderedDict[str, _Counts] = OrderedDict()

    def __len__(self) -> int:
        return len(self._symbols)

    def _minute(self) -> int:
        return math.floor(self._now().timestamp() / _MINUTE_S)

    def note(self, symbol: str, *, rows: int = 0, resyncs: int = 0) -> None:
        at, minute = self._now(), self._minute()
        counts = self._symbols.pop(symbol, None) or _Counts(deque(maxlen=_HOUR_MINUTES))
        self._symbols[symbol] = counts  # most recently seen last
        while len(self._symbols) > self._cap:
            self._symbols.popitem(last=False)
        if not counts.minutes or counts.minutes[-1][0] != minute:
            counts.minutes.append([minute, 0, 0])
        counts.minutes[-1][1] += rows
        counts.minutes[-1][2] += resyncs
        if rows:
            counts.last_event_at = at

    def totals(self, symbol: str) -> tuple[int, int, datetime | None]:
        """`(rows, resyncs, last event)` over the hour ending now."""
        counts = self._symbols.get(symbol)
        if counts is None:
            return 0, 0, None
        since = self._minute() - _HOUR_MINUTES
        held = [m for m in counts.minutes if m[0] > since]
        return sum(m[1] for m in held), sum(m[2] for m in held), counts.last_event_at


def _retention(pinned: bool, days: int | None, default_days: int) -> float:
    return math.inf if pinned else float(days or default_days)


class RuntimeRecordingControl:
    """The bound `RecordingControl` (see the module docstring)."""

    def __init__(
        self,
        wiring: RecorderWiring,
        *,
        config: PolicyConfig,
        default_retention_days: int,
        now: Callable[[], datetime],
    ) -> None:
        """`config` is the policy's own (the status reports it); `now` is the wall clock."""
        self._policy, self._rows, self._env = wiring.policy, wiring.rows, wiring.env
        self._config, self._default_days = config, default_retention_days
        self.windows = HourWindows(now)
        self._stopped: OrderedDict[str, rc.RecordedEntry] = OrderedDict()

    def note(self, symbol: str, *, rows: int = 0, resyncs: int = 0) -> None:
        """The feed's report: `rows` written and `resyncs` made for `symbol` just now."""
        self.windows.note(symbol, rows=rows, resyncs=resyncs)

    # --- reads -------------------------------------------------------------------------

    def _live(self, entry: rc.RecordedEntry) -> rc.RecordedEntry:
        p, symbol = self._policy, entry.symbol
        live = {"chart_open": p.chart_open(symbol), "position_open": p.position_open(symbol)}
        held = set(entry.reasons) | {r for r, on in live.items() if on}
        start = p.start_refusal(symbol)
        stops = tuple(c for c in _STOPS if live[c])
        until = p.linger_until(symbol)
        rows, resyncs, last = self.windows.totals(symbol)
        return replace(
            entry, reasons=tuple(r for r in _ORDER if r in held),
            refusals=((start,) if start else ()) + stops, lingering=until is not None,
            linger_until=until, rows_last_hour=rows, resyncs_last_hour=resyncs,
            last_event_at=last,
        )  # fmt: skip

    async def _stored(self) -> list[rc.RecordedEntry]:
        out: list[rc.RecordedEntry] = []
        after: tuple[str, str] | None = None
        for _ in range(_MAX_PAGES):
            rows = await self._rows.recorded_page(
                env=self._env, state=None, reason=None, pinned=None, hidden=(), after=after,
                limit=_PAGE,
            )  # fmt: skip
            out += map(rc.entry_from_row, rows)
            if len(rows) < _PAGE:
                break
            after = (rows[-1]["symbol"], rows[-1]["id"])
        return out

    def _lingering(self, stored: set[str]) -> list[rc.RecordedEntry]:
        """The stopped rows the policy still lingers on (those it no longer does are forgotten)."""
        for symbol in [s for s in self._stopped if self._policy.linger_until(s) is None]:
            del self._stopped[symbol]
        return [e for s, e in self._stopped.items() if s not in stored]

    async def _raw(self, *, symbol: str | None = None,
                   entry_id: str | None = None) -> rc.RecordedEntry | None:  # fmt: skip
        """The stored entry (by symbol or id), else a stopped one the policy still lingers on."""
        if entry_id is not None:
            if (row := await self._rows.recorded_row(entry_id, env=self._env)) is not None:
                return rc.entry_from_row(row)
        elif found := [e for e in await self._stored() if e.symbol == symbol]:
            return found[0]
        gone = self._lingering(set())
        return next((e for e in gone if entry_id == e.id or symbol == e.symbol), None)

    async def _find(self, symbol: str) -> rc.RecordedEntry | None:
        entry = await self._raw(symbol=symbol)
        return None if entry is None else self._live(entry)

    async def list(self, query: rc.EntryQuery) -> rc.EntryPage:
        q = query
        rows = await self._rows.recorded_page(
            env=self._env, state=q.state, reason=q.reason, pinned=q.pinned,
            hidden=tuple(sorted(q.hidden)), after=q.after, limit=q.limit + 1,
        )  # fmt: skip
        items = tuple(self._live(rc.entry_from_row(r)) for r in rows[: q.limit])
        return rc.EntryPage(items, len(rows) > q.limit)

    async def get(self, entry_id: str) -> rc.RecordedEntry | None:
        entry = await self._raw(entry_id=entry_id)
        return None if entry is None else self._live(entry)

    async def status(self) -> rc.ControlStatus:
        stored = await self._stored()
        held = stored + self._lingering({e.symbol for e in stored})
        entries = tuple(self._live(e) for e in sorted(held, key=lambda e: (e.symbol, e.id)))
        return rc.ControlStatus(entries, policy=self._config)

    # --- writes ---------------------------------------------------------------------

    def _target(self, entry: rc.RecordedEntry, spec: rc.EntrySpec) -> tuple[bool, int | None]:
        """The pin and `retention_days` after `spec`: a pin nulls it (22); an unpin takes the
        named days or the default; a row already unpinned keeps its days unless they are named."""
        pinned = entry.pinned if spec.pinned is None else spec.pinned
        if pinned:
            return True, None
        if (
            spec.retention_days is not None
            or spec.default_retention
            or (spec.pinned is False and entry.pinned)
        ):
            return False, spec.retention_days
        return False, entry.retention_days

    def _relax(self, entry: rc.RecordedEntry, spec: rc.EntrySpec, restricted: bool) -> None:
        """Ahead of any write of a change that also relaxes: `RelaxRefused` (unrecorded) when the
        view does not cover the row, so no other part of the change lands."""
        pinned, days = self._target(entry, spec)
        held = _retention(entry.pinned, entry.retention_days, self._default_days)
        relaxes = _retention(pinned, days, self._default_days) < held
        if relaxes and not self._policy.relax_allowed(entry.symbol, restricted=restricted):
            raise rc.RelaxRefused(entry.symbol, recorded=False)

    async def _settle(self, entry: rc.RecordedEntry, spec: rc.EntrySpec, actor: Actor,
                      restricted: bool) -> rc.RecordedEntry | None:  # fmt: skip
        """The pin, else the retention, through the policy, which records it ahead of its store."""
        pinned, days = self._target(entry, spec)
        try:
            if pinned != entry.pinned:
                await self._policy.set_pin(entry.symbol, pinned, actor, restricted=restricted,
                                           retention_days=days)  # fmt: skip
            elif days != entry.retention_days:
                await self._policy.set_retention(entry.symbol, days, actor, restricted=restricted)
        except RecorderSymbolNotRecordedError:
            return None
        except RecorderRelaxRefusedError:  # the view changed since `_relax`: the policy recorded it
            raise rc.RelaxRefused(entry.symbol, recorded=True) from None
        kept = replace(entry, pinned=pinned, retention_days=days)
        return await self._find(entry.symbol) or kept

    async def add(
        self, symbol: str, spec: rc.EntrySpec, actor: Actor, *, restricted: bool
    ) -> tuple[rc.RecordedEntry, rc.RecordedEntry | None]:
        old = await self._find(symbol)
        join = restricted and old is not None and rc.restricted_view(old) is None
        streams = spec.streams or (old.streams if old else ())
        depth = spec.depth if spec.depth is not None else (old.depth if old else None)
        if join and old is not None:  # the row's own, read now: a join changes no setting
            streams, depth, spec = old.streams, old.depth, rc.EntrySpec()
        if old is not None:
            self._relax(old, spec, restricted)
        await self._policy.add_manual(symbol, actor, tuple(streams), depth, held_hidden=join)
        entry = await self._find(symbol)
        if entry is None:  # the policy wrote it ahead of this read; a racing stop took it
            raise RecorderSymbolNotRecordedError("the recorded row was removed")
        return await self._settle(entry, spec, actor, restricted) or entry, old

    async def update(self, entry_id: str, spec: rc.EntrySpec, actor: Actor, *,
                     restricted: bool) -> rc.RecordedEntry | None:  # fmt: skip
        if (entry := await self.get(entry_id)) is None:
            return None
        self._relax(entry, spec, restricted)
        if spec.streams is not None or spec.depth is not None:
            try:  # the policy records `recorder.update` ahead of the row
                await self._policy.update_manual(
                    entry.symbol, actor, streams=spec.streams, depth=spec.depth
                )
            except RecorderSymbolNotManualError:
                raise rc.ChangeRefused("not_manual") from None
            except RecorderInvalidUpdateError:
                raise rc.ChangeRefused(*rc.setting_rule(spec.depth)) from None
            entry = await self._find(entry.symbol) or entry
        return await self._settle(entry, spec, actor, restricted)

    async def pin(self, entry_id: str, pinned: bool, actor: Actor, *, restricted: bool,
                  retention_days: int | None = None) -> rc.RecordedEntry | None:  # fmt: skip
        spec = rc.EntrySpec(pinned=pinned, retention_days=retention_days)
        if (entry := await self.get(entry_id)) is None:
            return None
        self._relax(entry, spec, restricted)
        return await self._settle(entry, spec, actor, restricted)

    async def remove(self, entry_id: str, actor: Actor, *,
                     force: bool = False) -> rc.RecordedEntry | None:  # fmt: skip
        if (raw := await self._raw(entry_id=entry_id)) is None:
            return None
        entry = self._live(raw)
        causes = tuple(c for c in entry.refusals if c in rc.STOP_CAUSES)
        if causes and not force:
            raise rc.StopRefused(causes)
        await self._policy.remove_manual(entry.symbol, actor)  # records `recorder.stop` first
        self._stopped.pop(entry.symbol, None)
        self._stopped[entry.symbol] = raw
        while len(self._stopped) > MAX_SYMBOLS:
            self._stopped.popitem(last=False)
        return await self._find(entry.symbol)
