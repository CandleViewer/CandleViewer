"""`CvAuditPlugin`'s chain continuity and payload redaction (E50-T63).

An optional head provider gives each row's `prev_hash` from the sink's held head, so the chain of
one machine key continues across restarts and picks up the fault rows other writers appended; with
no provider, or a key the sink does not hold, the plugin's own last hash applies, from
`GENESIS_HASH`, as before. An optional redactor (the shared audit serializer) runs on the payload
before it is hashed, so the stored payload is the hashed one (scenario 9). The hooks are driven
directly with duck-typed interpreter and event doubles: no runtime import here."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from candleviewer.admin.wiring import system_event_redactor
from candleviewer.audit.redact import REDACTION_MARKER
from candleviewer.observability.metrics import Metrics
from candleviewer.statechart.plugins import CvAuditPlugin, InMemoryMachineEventSink, cv_plugins
from candleviewer.statechart.plugins.audit import (
    GENESIS_HASH,
    MachineEventRow,
    row_digest,
    verify_chain,
)

KIND, ENTITY, ENV = "persist_min", "00000000-0000-4000-8000-000000000009", "demo"


class HeldHeads:
    """The sink's held heads, as `MachineEventWalSink.head` serves them, plus its rows."""

    def __init__(self) -> None:
        self.held: str | None = None
        self.rows: list[MachineEventRow] = []

    def head(self) -> str | None:
        return self.held

    def append(self, row: MachineEventRow) -> None:
        self.rows.append(row)
        self.held = row.row_hash


def _commit(plugin: CvAuditPlugin, event: str = "PING", **data: Any) -> None:
    interp = SimpleNamespace(_active_state_nodes=())
    plugin.on_event_received(interp, SimpleNamespace(type=event, data=data))
    plugin.on_transition(interp, (), (), SimpleNamespace(event=event))


def _plugin(sink: Any, **kw: Any) -> CvAuditPlugin:
    return CvAuditPlugin(
        machine_kind=KIND, entity_id=ENTITY, env=ENV, sink=sink, write_ahead=False, **kw
    )


def _fault_row(prev: str) -> MachineEventRow:
    row = MachineEventRow(
        machine_kind=KIND, entity_id=ENTITY, env=ENV, event_type="DRAIN_ERROR", payload={},
        from_states=[], to_states=[], actions_run=[],
        fault={"kind": "drain_error", "error": "InterpreterStoppedError"},
        occurred_at="2026-10-21T03:00:00+00:00", phase="fault", prev_hash=prev,
    )  # fmt: skip
    return replace(row, row_hash=row_digest(row))


def test_with_no_head_provider_the_chain_starts_from_genesis_as_before() -> None:
    sink = InMemoryMachineEventSink()
    plugin = _plugin(sink)
    _commit(plugin)
    _commit(plugin)
    assert sink.rows[0].prev_hash == GENESIS_HASH and verify_chain(sink.rows)


def test_a_held_head_is_the_prev_hash_of_the_next_row() -> None:
    """A restored machine continues its key's chain from the head the sink holds."""
    heads = HeldHeads()
    heads.held = "ab" * 32
    plugin = _plugin(heads, head=heads.head)
    _commit(plugin)
    assert heads.rows[0].prev_hash == "ab" * 32


def test_a_key_the_sink_does_not_hold_falls_back_to_the_plugins_own_last_hash() -> None:
    sink = InMemoryMachineEventSink()
    plugin = _plugin(sink, head=lambda: None)
    _commit(plugin)
    _commit(plugin)
    assert sink.rows[0].prev_hash == GENESIS_HASH
    assert sink.rows[1].prev_hash == sink.rows[0].row_hash


def test_a_fault_row_appended_by_another_writer_is_picked_up_on_the_next_row() -> None:
    """The provider is asked on every row, so the chain runs through interleaved fault rows."""
    heads = HeldHeads()
    plugin = _plugin(heads, head=heads.head)
    _commit(plugin)
    heads.append(_fault_row(heads.rows[-1].row_hash))  # a fault writer, between two commits
    _commit(plugin)
    assert [r.phase for r in heads.rows] == ["commit", "fault", "commit"]
    assert heads.rows[2].prev_hash == heads.rows[1].row_hash
    assert verify_chain(heads.rows)


def test_a_credential_shaped_payload_key_is_stored_redacted_before_it_is_hashed() -> None:
    """Scenario 9: the stored payload holds REDACTION_MARKER and is the payload the hash covers."""
    sink = InMemoryMachineEventSink()
    plugin = _plugin(sink, redactor=system_event_redactor())
    hostile = "v" * 4  # a short placeholder, never a credential
    _commit(plugin, api_key=hostile, nested={"password": hostile, "qty": "1"}, symbol="BTCUSDT")
    [row] = sink.rows
    assert row.payload == {
        "api_key": REDACTION_MARKER,
        "nested": {"password": REDACTION_MARKER, "qty": "1"},
        "symbol": "BTCUSDT",
    }
    assert row.row_hash == row_digest(row) and verify_chain(sink.rows)
    assert hostile not in repr(row)


def test_without_a_redactor_the_payload_is_stored_as_before() -> None:
    sink = InMemoryMachineEventSink()
    _commit(_plugin(sink), qty="1")
    assert sink.rows[0].payload == {"qty": "1"}


def test_cv_plugins_forwards_the_head_provider_and_the_redactor() -> None:
    heads = HeldHeads()
    heads.held = "cd" * 32
    *_, audit = cv_plugins(
        machine_kind=KIND, lane="control", entity_id=ENTITY, env=ENV, metrics=Metrics("dev"),
        sink=heads, head=heads.head, redactor=system_event_redactor(),
    )  # fmt: skip
    _commit(audit, token=("t" * 3))
    assert heads.rows[0].prev_hash == "cd" * 32
    assert heads.rows[0].payload == {"token": REDACTION_MARKER}
