"""`CvAuditPlugin` — `machine_events` rows, hash-chained (E50-T60, M19).

Write-ahead for the order family (24-internal-schemas.md §17.6): before the
first action of a transition runs, an `ahead` row is appended *synchronously*
to the sink; the commit row (`to_states`, the actual `actions_run`, MUST-02)
follows in `on_transition`. Other families are write-behind (commit row only).
A failed transition writes a row with `fault` set (CvErrorHooks companion).

Every row carries `prev_hash`/`row_hash` (sha256 over canonical JSON), so a
gap or edit in the per-machine stream is detectable — the same chaining
discipline as the M19 audit log. The sink is an injected Protocol:
`statechart` may not import `audit`/`storage` (import-linter). The
`machine_events` table (24-internal-schemas.md §17.6, E50-T61) stores `phase`,
`prev_hash` and `row_hash` as columns; the Postgres sink is E50-T63's
WAL-backed `audit.machine_events.MachineEventWalSink`.

Chain continuity (E50-T63): one chain per machine key, advanced by every writer
and continuous across restarts. An optional `head` provider returns the sink's
held head for this machine, or `None` when the sink does not hold it (then the
plugin's own last hash applies); it is asked on every row, so the fault rows
other writers appended are picked up. An optional `redactor` (the shared audit
serializer) runs on the payload before it is hashed, so the stored payload is
the hashed one. Without either, the behaviour is the earlier one, from
`GENESIS_HASH`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from candleviewer.statechart.plugins._base import (
    HookFailureCounter,
    contained,
    event_type,
    logger,
    state_ids,
)

Phase = Literal["ahead", "commit", "fault"]
GENESIS_HASH = "0" * 64


@dataclass(frozen=True, slots=True)
class MachineEventRow:
    machine_kind: str
    entity_id: str
    env: str
    event_type: str
    payload: dict[str, Any]
    from_states: list[str]
    to_states: list[str]
    actions_run: list[str]
    fault: dict[str, Any] | None
    occurred_at: str
    phase: Phase
    prev_hash: str
    row_hash: str = field(default="")


class MachineEventSink(Protocol):
    """Synchronous, durable append (hooks cannot await). Must raise on
    failure; the plugin then counts it and pages."""

    def append(self, row: MachineEventRow) -> None: ...


class InMemoryMachineEventSink:
    """Test/contract-suite sink."""

    def __init__(self) -> None:
        self.rows: list[MachineEventRow] = []

    def append(self, row: MachineEventRow) -> None:
        self.rows.append(row)


def row_digest(row: MachineEventRow) -> str:
    body = asdict(row)
    body.pop("row_hash")
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode()).hexdigest()


def verify_chain(rows: list[MachineEventRow]) -> bool:
    prev = GENESIS_HASH
    for r in rows:
        if r.prev_hash != prev or r.row_hash != row_digest(r):
            return False
        prev = r.row_hash
    return True


def _utc_now() -> datetime:
    return datetime.now(UTC)


#: The payload redactor's shape: the audit serializer (`audit.redact.redact`), injected.
Redactor = Callable[[dict[str, Any] | None], dict[str, Any] | None]
#: The sink's held head for one machine, or `None` when it does not hold it.
HeadProvider = Callable[[], str | None]


def _safe_payload(event: Any, redactor: Redactor | None = None) -> dict[str, Any]:
    data = getattr(event, "data", None)
    if not isinstance(data, dict):
        return {}
    try:
        payload = dict(json.loads(json.dumps(data, default=str)))
    except (TypeError, ValueError):
        return {}
    return payload if redactor is None else (redactor(payload) or {})


class CvAuditPlugin(HookFailureCounter):
    """One instance per interpreter (the hash chain is per machine)."""

    def __init__(
        self,
        *,
        machine_kind: str,
        entity_id: str,
        env: str,
        sink: MachineEventSink,
        write_ahead: bool,
        clock: Callable[[], datetime] = _utc_now,
        head: HeadProvider | None = None,
        redactor: Redactor | None = None,
    ) -> None:
        super().__init__()
        self.machine_kind = machine_kind
        self.entity_id = entity_id
        self.env = env
        self.sink = sink
        self.write_ahead = write_ahead
        self._clock = clock
        self._head = head
        self._redactor = redactor
        self._prev = GENESIS_HASH
        self._event: Any = None
        self._ahead_written = False
        self._actions: list[str] = []
        self.sink_failures = 0

    def _append(
        self,
        phase: Phase,
        *,
        from_states: list[str],
        to_states: list[str],
        fault: dict[str, Any] | None = None,
        event_name: str | None = None,
    ) -> None:
        row = MachineEventRow(
            machine_kind=self.machine_kind,
            entity_id=self.entity_id,
            env=self.env,
            event_type=event_name if event_name is not None else event_type(self._event),
            payload=_safe_payload(self._event, self._redactor),
            from_states=from_states,
            to_states=to_states,
            actions_run=list(self._actions),
            fault=fault,
            occurred_at=self._clock().isoformat(),
            phase=phase,
            prev_hash=(self._head() if self._head is not None else None) or self._prev,
        )
        row = MachineEventRow(**{**asdict(row), "row_hash": row_digest(row)})
        try:
            self.sink.append(row)
        except Exception as exc:
            self.sink_failures += 1
            logger().critical(
                "statechart_audit_sink_failed", kind=self.machine_kind, error=type(exc).__name__
            )
            raise
        self._prev = row.row_hash

    def _reset_step(self) -> None:
        self._ahead_written = False
        self._actions = []

    @contained
    def on_event_received(self, interpreter: Any, event: Any) -> None:
        self._event = event
        self._reset_step()

    @contained
    def on_action_execute(self, interpreter: Any, action: Any) -> None:
        if self.write_ahead and not self._ahead_written:
            current = state_ids(getattr(interpreter, "_active_state_nodes", ()))
            # Durable before the action body runs (write-ahead, order family).
            self._append("ahead", from_states=current, to_states=[])
            self._ahead_written = True
        self._actions.append(str(getattr(action, "type", action)))

    @contained
    def on_transition(
        self, interpreter: Any, from_states: Any, to_states: Any, transition: Any
    ) -> None:
        name = str(getattr(transition, "event", "") or event_type(self._event))
        self._append(
            "commit",
            from_states=state_ids(from_states),
            to_states=state_ids(to_states),
            event_name=name,
        )
        self._reset_step()

    @contained
    def on_transition_failed(self, interpreter: Any, transition: Any, failed_actions: Any) -> None:
        current = state_ids(getattr(interpreter, "_active_state_nodes", ()))
        fault = {
            "failed": [
                {"action": str(getattr(a, "type", a)), "error": type(e).__name__}
                for a, e in (failed_actions or ())
            ]
        }
        self._append(
            "fault",
            from_states=current,
            to_states=current,
            fault=fault,
            event_name=str(getattr(transition, "event", "") or event_type(self._event)),
        )
        self._reset_step()
