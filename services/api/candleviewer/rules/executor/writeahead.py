"""The records written ahead of an armed fire's actions (24 §11.5; the E35 threat model's RE-R1,
AC-14; C-2.9).

`FireRecords` keeps one armed fire's records and its event `seq`, from 1: the run row with its
first event in one write, then per action `action_start` and `rules.fired` before the hand-over, its
`action_ok` or `action_fail` after it, a refusal's `action_fail` and `rules.blocked`, and the run
row's close. Each write has its own bound (`FIRE_RECORD_TIMEOUT_S`); a write that fails or outlasts
it raises `WriteAheadFailed`, naming the write and the cause's class alone (C-12.6), and a
hand-over never runs after one. Nothing here retries, catches a cancel or logs the snapshot.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any, Final, Literal, TypeVar

from candleviewer.rules.executor.ports import (
    ActionAudit,
    ActionAuditFields,
    EventKind,
    EventRow,
    EventSeverity,
    RunRecords,
    RunRow,
    RunStatus,
)
from candleviewer.rules.executor.results import ActionResult

#: Each write's own bound (BQ-9): the bound the rule-row read and the audit writer's callers use,
#: inside the action's dispatch bound. Read at each write.
FIRE_RECORD_TIMEOUT_S: Final = 2.0
#: The `error_code` of an action whose write ahead failed: it was not sent (24 §11.5).
WRITE_AHEAD_FAILED: Final = "write_ahead_failed"
WriteKind = Literal["run", "event", "audit"]
_T = TypeVar("_T")
_SEVERITY: Final[dict[str, EventSeverity]] = {
    "ok": "info", "simulated": "info", "blocked": "warning", "skipped": "warning",
    "failed": "error", "unknown": "error",
}  # fmt: skip


class WriteAheadFailed(Exception):
    """A write ahead failed or outlasted its bound: the action it was for is not sent."""

    def __init__(self, write: WriteKind, cause: BaseException) -> None:
        self.write: WriteKind = write
        self.cause = type(cause).__name__
        super().__init__(f"the {write} write ahead failed: {self.cause}")


class FireRecords:
    """One armed fire's records, its run row begun by its first write."""

    def __init__(self, run: RunRow, records: RunRecords, audit: ActionAudit) -> None:
        self._run, self._records, self._audit = run, records, audit
        self._seq = 0
        self._begun = False

    async def admitted(self, fields: ActionAuditFields, send: Callable[[], Awaitable[_T]]) -> _T:
        """The records written ahead, then the hand-over: `action_start` (with the run row on the
        fire's first write), then `rules.fired`, each under its own bound; `send` runs only once
        both have landed and never after a failure, which raises `WriteAheadFailed`."""
        payload = {
            "action_type": fields.action_type, "dedupe_key": fields.dedupe_key,
            "account_id": None if fields.account_id is None else str(fields.account_id),
        }  # fmt: skip
        await self._event("action_start", fields.node_id, payload, "info")
        await self._bounded("audit", lambda: self._audit.fired(fields))
        return await send()

    async def answered(
        self, result: ActionResult, journal: Mapping[str, str | None] | None = None
    ) -> None:
        """A result's event: `action_ok` for `ok` or `simulated`, else `action_fail`, with the
        `ActionResult` as its payload; and for an `ok` result with a `journal`, the `log` row its
        tag rides (E35-T13, `log_journal_tag`), in the same write."""
        kind: EventKind = "action_ok" if result.outcome in ("ok", "simulated") else "action_fail"
        dump = result.model_dump(mode="json")
        events = [(kind, result.node_id, dump, _SEVERITY[result.outcome])]
        if journal is not None and result.outcome == "ok":
            events.append(("log", result.node_id, dict(journal), "info"))
        await self._events(events)

    async def refused(self, result: ActionResult, fields: ActionAuditFields) -> None:
        """A refusal (`blocked`, or a `mode_changed` skip): its `action_fail`, then `rules.blocked`
        with its `blocked_by`, never `rules.fired`."""
        if result.blocked_by is None:
            raise ValueError("a refusal names its blocked_by")
        severity = _SEVERITY[result.outcome]
        await self._event("action_fail", result.node_id, result.model_dump(mode="json"), severity)
        denied = replace(fields, blocked_by=result.blocked_by)
        await self._bounded("audit", lambda: self._audit.blocked(denied))

    async def closed(self, status: RunStatus, duration_ms: int) -> None:
        """The run row's close, once its last result is recorded; nothing for a fire that wrote
        nothing, which has no row."""
        if self._seq:
            run_id = self._run.run_id
            await self._bounded("run", lambda: self._records.close(run_id, status, duration_ms))

    async def _event(
        self, kind: EventKind, node: str, payload: dict[str, Any], severity: EventSeverity
    ) -> None:
        await self._events([(kind, node, payload, severity)])

    async def _events(
        self, events: Sequence[tuple[EventKind, str, dict[str, Any], EventSeverity]]
    ) -> None:
        """The next events, each with its own `seq`: through `begin`, with the run row, until one
        `begin` has landed (the first event there), then appended together, in one write."""
        rows = []
        for kind, node, payload, severity in events:
            self._seq += 1
            rows.append(
                EventRow(
                    seq=self._seq, kind=kind, node_ref=node, payload=payload, severity=severity
                )
            )
        if not self._begun:
            first, rows = rows[0], rows[1:]
            await self._bounded("run", lambda: self._records.begin(self._run, first))
            self._begun = True
        if rows:
            run_id = self._run.run_id
            await self._bounded("event", lambda: self._records.append(run_id, tuple(rows)))

    async def _bounded(self, write: WriteKind, start: Callable[[], Awaitable[None]]) -> None:
        """`start()` under its bound. A failure is raised outside the handler, so the error that
        caused it, whose text may hold a value, is neither its cause nor its context."""
        failed: WriteAheadFailed | None = None
        try:
            async with asyncio.timeout(FIRE_RECORD_TIMEOUT_S):
                await start()
        except Exception as exc:  # never `CancelledError`, which is no `Exception`
            failed = WriteAheadFailed(write, exc)
        if failed is not None:
            raise failed
