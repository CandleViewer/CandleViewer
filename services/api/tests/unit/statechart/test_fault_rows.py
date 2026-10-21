"""The fault-row writers (`statechart_wiring.FaultRows`, E50-T63): `PersistAudit` and
`RestoreAudit` over the `machine_events` sink. Each writes one `phase="fault"` row in the
machine's own chain (`prev_hash` from the sink's held head, after `seed(key)`), `payload` `{}`,
empty state lists, `occurred_at` from the injected UTC clock; a reason is cut to 256 characters;
a row never carries the blob, the tag or an event or context value (24 §17.6 "Faults").

They never raise: a raising `drain_error` would lose the drained events and a raising
`quarantine` would mask the refusal and skip its page (`persistence.Persister.persist`,
`Restorer._refuse`), so a writer that cannot write logs CRITICAL and pages P1 itself."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.statechart.persistence import MachineKey, Seal, SealedSnapshot
from candleviewer.statechart.plugins import CvAuditPlugin
from candleviewer.statechart.plugins.audit import (
    GENESIS_HASH,
    MachineEventRow,
    row_digest,
    verify_chain,
)
from candleviewer.statechart.schema import canonical_json
from candleviewer.statechart_wiring import FaultRows

T0 = datetime(2026, 10, 21, 3, 0, 0, 123456, tzinfo=UTC)
KEY = MachineKey("replay", "0a000000-0000-4000-8000-000000000001", "demo")
BLOB: dict[str, Any] = {"version": 3, "context": {"probe": "kept-out"}, "chain_trips": 0}
TAG = "ab" * 32
ENVELOPE = SealedSnapshot(
    key=KEY, version=3, machine_hash="d" * 64, snapshot=BLOB, seal=Seal(key_id="k1", tag=TAG)
)


class FakeChainSink:
    """`seed`, `head` and `append`, as `MachineEventWalSink` serves them; `fail_at` makes one
    of `seed` or `append` raise `error`."""

    def __init__(self, held: str | None = None) -> None:
        self.held = held
        self.rows: list[MachineEventRow] = []
        self.calls: list[str] = []
        self.fail_at: str | None = None
        self.error: BaseException = RuntimeError("the machine-event sink is not running")

    async def seed(self, key: MachineKey) -> None:
        self.calls.append("seed")
        if self.fail_at == "seed":
            raise self.error
        if self.held is None:
            self.held = GENESIS_HASH

    def head(self, key: MachineKey) -> str | None:
        return self.held

    def append(self, row: MachineEventRow) -> None:
        self.calls.append("append")
        if self.fail_at == "append":
            raise self.error
        self.rows.append(row)
        self.held = row.row_hash


class FakePager:
    def __init__(self) -> None:
        self.pages: list[tuple[str, str]] = []

    async def page(self, key: MachineKey, severity: str, message: str) -> None:
        self.pages.append((severity, message))


class Ops:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    def __call__(self, operation: str, outcome: str) -> None:
        self.seen.append((operation, outcome))


def _writers(
    sink: FakeChainSink | None = None,
) -> tuple[FaultRows, FakeChainSink, FakePager, Ops]:
    sink, pager, ops = sink or FakeChainSink(), FakePager(), Ops()
    return FaultRows(sink, pager, clock=lambda: T0, ops=ops), sink, pager, ops


_QUARANTINE_FAULT = {
    "kind": "restore_quarantined",
    "reason": "bad HMAC (CV-C53)",
    "machine_hash": "d" * 64,
    "version": 3,
    "hmac_key_id": "k1",
    "snapshot_sha256": hashlib.sha256(canonical_json(BLOB)).hexdigest(),
}
_WRITES = {
    "persist_refused": (
        lambda w: w.persist_refused(KEY, "context carries _fault (MUST-01)"),
        "PERSIST_REFUSED",
        {"kind": "persist_refused", "reason": "context carries _fault (MUST-01)"},
    ),
    "drain_error": (
        lambda w: w.drain_error(KEY, "InterpreterStoppedError"),
        "DRAIN_ERROR",
        {"kind": "drain_error", "error": "InterpreterStoppedError"},
    ),
    "quarantine": (
        lambda w: w.quarantine(KEY, ENVELOPE, "bad HMAC (CV-C53)"),
        "RESTORE_QUARANTINED",
        _QUARANTINE_FAULT,
    ),
}


@pytest.mark.parametrize("writer", list(_WRITES))
async def test_each_writer_appends_one_fault_row_in_the_machines_chain(writer: str) -> None:
    write, event_type, fault = _WRITES[writer]
    writers, sink, _pager, _ops = _writers(FakeChainSink(held="cc" * 32))
    await write(writers)
    [row] = sink.rows
    assert row == replace(
        MachineEventRow(
            machine_kind=KEY.machine_kind, entity_id=KEY.entity_id, env=KEY.env,
            event_type=event_type, payload={}, from_states=[], to_states=[], actions_run=[],
            fault=fault, occurred_at=T0.isoformat(), phase="fault", prev_hash="cc" * 32,
        ),
        row_hash=row.row_hash,
    )  # fmt: skip
    assert row.row_hash == row_digest(row)
    assert sink.calls == ["seed", "append"]  # seeded before the row is built


async def test_a_quarantine_row_carries_a_digest_never_the_blob_or_the_tag() -> None:
    writers, sink, _pager, ops = _writers()
    await writers.quarantine(KEY, ENVELOPE, "bad HMAC (CV-C53)")
    [row] = sink.rows
    assert TAG not in repr(row) and "kept-out" not in repr(row)
    assert ops.seen == [("quarantine", "ok")]


async def test_a_quarantine_of_an_envelope_without_a_seal_names_no_key_id() -> None:
    writers, sink, _pager, _ops = _writers()
    await writers.quarantine(KEY, replace(ENVELOPE, seal="stub"), "no HMAC seal")
    assert sink.rows[0].fault is not None and sink.rows[0].fault["hmac_key_id"] is None


async def test_a_reason_is_cut_to_256_characters() -> None:
    writers, sink, _pager, _ops = _writers()
    await writers.persist_refused(KEY, "r" * 300)
    fault = sink.rows[0].fault
    assert fault is not None and fault["reason"] == "r" * 256


async def test_a_refused_persist_pages_p1_and_the_other_writers_do_not() -> None:
    writers, _sink, pager, _ops = _writers()
    await writers.drain_error(KEY, "InterpreterStoppedError")
    await writers.quarantine(KEY, ENVELOPE, "bad HMAC (CV-C53)")  # the Restorer pages refusals
    assert pager.pages == []
    await writers.persist_refused(KEY, "context carries _fault (MUST-01)")
    [(severity, text)] = pager.pages
    assert severity == "P1" and "persist refused" in text and "MUST-01" in text


@pytest.mark.parametrize("at", ["seed", "append"])
@pytest.mark.parametrize("writer", list(_WRITES))
async def test_a_writer_that_cannot_write_never_raises_and_pages_p1(writer: str, at: str) -> None:
    write, event_type, _fault = _WRITES[writer]
    sink = FakeChainSink()
    sink.fail_at = at
    writers, _sink, pager, ops = _writers(sink)
    with capture_logs() as logs:
        await write(writers)  # never raises
    failed = [e for e in logs if e["event"] == "statechart_fault_row_failed"]
    assert [(e["event_type"], e["error"], e["log_level"]) for e in failed] == [
        (event_type, "RuntimeError", "critical")
    ]
    page = ("P1", f"machine_events fault row {event_type} not written (RuntimeError)")
    assert page in pager.pages
    assert "not running" not in repr(logs) + repr(pager.pages)  # the type only, never the text
    if writer == "quarantine":
        assert ops.seen == [("quarantine", "error")]


async def test_a_cancellation_passes_through_a_writer() -> None:
    sink = FakeChainSink()
    sink.fail_at, sink.error = "seed", asyncio.CancelledError()
    writers, _sink, pager, _ops = _writers(sink)
    with pytest.raises(asyncio.CancelledError):
        await writers.drain_error(KEY, "InterpreterStoppedError")
    assert pager.pages == []


async def test_fault_rows_and_the_plugins_rows_form_one_chain() -> None:
    """Scenario 5's unit twin: the plugin asks the sink for the head on every row."""
    sink = FakeChainSink()
    await sink.seed(KEY)
    plugin = CvAuditPlugin(
        machine_kind=KEY.machine_kind, entity_id=KEY.entity_id, env=KEY.env, sink=sink,
        write_ahead=False, head=lambda: sink.head(KEY), clock=lambda: T0,
    )  # fmt: skip
    interp = SimpleNamespace(_active_state_nodes=())
    plugin.on_event_received(interp, SimpleNamespace(type="PLAY", data={}))
    plugin.on_transition(interp, (), (), SimpleNamespace(event="PLAY"))
    writers, *_ = _writers(sink)
    await writers.drain_error(KEY, "InterpreterStoppedError")
    plugin.on_event_received(interp, SimpleNamespace(type="PAUSE", data={}))
    plugin.on_transition(interp, (), (), SimpleNamespace(event="PAUSE"))
    assert [r.phase for r in sink.rows] == ["commit", "fault", "commit"]
    assert verify_chain(sink.rows)
