"""Shared fakes for the recorder unit tests: a settable clock, a recording bus, an audit sink and
the `recorded_symbols` store (no I/O, no sleeps). Tests import them from here, never from
`conftest.py` or a test module."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from candleviewer.bus.models import Topic
from candleviewer.recorder.policy import ManualCleared


class FakeClock:
    def __init__(self, t: float = 1_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


@dataclass
class FakeBus:
    """Records each publish as `(topic key, event)`; `fail_next` makes the next publish raise."""

    events: list[tuple[str, Any]] = field(default_factory=list)
    fail_next: bool = False

    async def publish(self, topic: Topic, event: Any) -> None:
        if self.fail_next:
            self.fail_next = False
            raise OSError("bus unavailable")
        self.events.append((topic.key, event))


class FakeAudit:
    def __init__(self, trace: list[str] | None = None) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []
        self.trace = [] if trace is None else trace  # shared with `MemRecordedStore`: the order

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.trace.append(f"audit:{action}")
        self.records.append((action, kwargs))

    def envs(self) -> list[tuple[str, str]]:
        return [(a, kw["env"]) for a, kw in self.records]

    def actions(self) -> list[str]:
        return [a for a, _ in self.records]


class MemRecordedStore:
    """`recorded_symbols` in memory with the SQL semantics the policy relies on: one active row per
    symbol, `soft_remove` unconditional, `clear_manual` demoting a row that holds a ref or a pin.
    `fail` names the methods that raise `OSError`, `hold` parks one on an event (to force an
    interleaving), `trace` lists the calls (shared with `FakeAudit`, for the order)."""

    def __init__(self, trace: list[str] | None = None) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.trace = [] if trace is None else trace
        self.fail: set[str] = set()
        self.hold: dict[str, asyncio.Event] = {}

    async def _enter(self, op: str) -> None:
        self.trace.append(op)
        if op in self.fail:
            raise OSError("pg down")
        if op in self.hold:
            await self.hold[op].wait()

    def active(self, symbol: str, env: str | None = None) -> dict[str, Any] | None:
        """The symbol's active row, in `env` when one is given (the policy always gives its own)."""
        rows = self.rows.values()
        found = (r for r in rows if r["symbol"] == symbol and not r["removed"])
        return next((r for r in found if env is None or r["env"] == env), None)

    def _new(self, symbol: str, env: str, reason: str) -> dict[str, Any]:
        rid = str(uuid.uuid4())
        self.rows[rid] = dict(id=rid, symbol=symbol, env=env, reason=reason, reason_refs=[],
                              pinned=False, added_by=None, streams=[], orderbook_depth=None,
                              removed=False, retention_days=None)  # fmt: skip
        return self.rows[rid]

    async def _live(self, op: str, recorded_id: str) -> dict[str, Any] | None:
        await self._enter(op)
        row = self.rows.get(recorded_id)
        return None if row is None or row["removed"] else row

    async def list_recorded(self, env: str) -> list[dict[str, Any]]:
        await self._enter("list_recorded")
        return [dict(r) for r in self.rows.values() if r["env"] == env and not r["removed"]]

    async def get_by_symbol(self, symbol: str, env: str) -> dict[str, Any] | None:
        await self._enter("get_by_symbol")
        return self.active(symbol, env)

    async def upsert_auto(self, symbol: str, reason: str, ref: dict[str, str], env: str) -> str:
        await self._enter("upsert_auto")
        row = self.active(symbol, env) or self._new(symbol, env, reason)
        if ref not in row["reason_refs"]:
            row["reason_refs"].append(ref)
        return str(row["id"])

    async def add_reason_ref(self, recorded_id: str, ref: dict[str, str]) -> bool:
        row = await self._live("add_reason_ref", recorded_id)
        if row is not None and ref not in row["reason_refs"]:
            row["reason_refs"].append(ref)
        return row is not None

    async def remove_reason_ref(self, recorded_id: str, ref: dict[str, str]) -> bool:
        row = await self._live("remove_reason_ref", recorded_id)
        if row is not None:
            row["reason_refs"] = [r for r in row["reason_refs"] if r != ref]
        return row is not None

    async def soft_remove(self, recorded_id: str) -> bool:
        row = await self._live("soft_remove", recorded_id)
        if row is not None:
            row["removed"] = True
        return row is not None

    async def set_pinned(self, recorded_id: str, pinned: bool) -> bool:
        row = await self._live("set_pinned", recorded_id)
        if row is not None:
            row["pinned"] = pinned
        return row is not None

    async def set_retention(self, recorded_id: str, retention_days: int | None) -> bool:
        row = await self._live("set_retention", recorded_id)
        if row is not None:
            row["retention_days"] = retention_days
        return row is not None

    async def upsert_manual(
        self, symbol: str, added_by: str | None, streams: Sequence[str], depth: int | None, env: str
    ) -> dict[str, Any]:
        await self._enter("upsert_manual")
        row = self.active(symbol, env) or self._new(symbol, env, "manual")
        kept = depth if depth is not None else row["orderbook_depth"]  # 0 is a depth, not "keep"
        row.update(reason="manual", added_by=added_by or row["added_by"],
                   streams=list(streams) or row["streams"], orderbook_depth=kept)  # fmt: skip
        return row

    async def clear_manual(self, symbol: str, env: str) -> ManualCleared:
        await self._enter("clear_manual")
        row = self.active(symbol, env)
        if row is None or row["reason"] != "manual":
            return "absent"
        if not (row["reason_refs"] or row["pinned"]):
            row["removed"] = True
            return "removed"
        has_position = any(r["kind"] == "position" for r in row["reason_refs"])
        row["reason"] = "position_open" if has_position else "chart_open"
        return "demoted"


Mem = MemRecordedStore  # short, so the `RecordingPolicy(...)` call sites stay on three lines


class FakeSeed:
    """A `PositionSeed`: the `(symbol, position id)` pairs it reports, or None (no source)."""

    def __init__(self, pairs: Sequence[tuple[str, str]] | None = ()) -> None:
        self.pairs = pairs

    async def open_positions(self) -> Sequence[tuple[str, str]] | None:
        return self.pairs


async def no_restore() -> None:
    """A startup's restore step with no B11 snapshot to restore."""


def _shape(member: Callable[..., object]) -> tuple[inspect.Signature, bool] | None:
    """A member's signature (annotations resolved) and whether it is a coroutine function; None
    when an annotation cannot be resolved."""
    try:
        return inspect.signature(member, eval_str=True), inspect.iscoroutinefunction(member)
    except (NameError, AttributeError):  # a missing name, or a missing module attribute
        return None


def surface_mismatches(candidate: type, surface: type) -> list[str]:
    """The members of the Protocol `surface` that `candidate` lacks or declares differently:
    names, kinds, defaults, (resolved) annotations and sync versus async, so a rename or a swap
    on either side is caught. An annotation that cannot be resolved counts as a mismatch."""
    wanted = {n: m for n, m in vars(surface).items() if callable(m) and not n.startswith("_")}
    return [
        name
        for name, member in wanted.items()
        if not callable(getattr(candidate, name, None))
        or (got := _shape(getattr(candidate, name))) is None
        or got != _shape(member)
    ]
