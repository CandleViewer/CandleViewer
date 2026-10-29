"""E42-T07 (#1025): the `system_events` row of a snapshot the inspector leaves out (22
`listStatecharts`): one critical `statechart` row per machine, environment and snapshot
`updated_at`, not one per read; none for a verified row; a fixed message and `details` without the
snapshot's content, key id or tag; a failing or stalled sink never fails the list or the detail.
Real HMAC seals over the fake store of `test_statechart_inspector`."""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import timedelta
from typing import Any

import pytest

from candleviewer.admin.inspector import (
    SEAL_EVENT_KIND,
    SEAL_EVENT_MESSAGE,
    SEAL_FAILED,
    BoundScope,
    SealFailures,
    SnapshotRow,
)
from candleviewer.admin_wiring import build_statechart_inspector
from candleviewer.api.admin_statecharts import machine_key
from candleviewer.observability.health_probes import SystemEvent
from tests.unit.admin.test_statechart_inspector import (
    ACC_A,
    ID_1,
    NOW,
    OWNER_VIEW,
    Keys,
    Store,
    fleet,
    inspector,
    row,
)

_SECRET_CONTEXT = {"api_secret": "never-written", "qty": "5"}


class Sink:
    """`SystemEventWriter`: records each event, or fails, or stalls."""

    def __init__(self, *, fail: bool = False, stall: bool = False) -> None:
        self.events: list[SystemEvent] = []
        self.fail, self.stall, self.attempts = fail, stall, 0

    async def write(self, event: SystemEvent) -> None:
        self.attempts += 1
        if self.stall:
            await asyncio.Event().wait()
        if self.fail:
            raise OSError("postgresql://cv:pw@db/cv is down")  # must never reach the log
        self.events.append(event)


def _forged(base: SnapshotRow | None = None) -> SnapshotRow:
    """An order whose snapshot was changed after sealing, its context holding a secret."""
    sealed = base or row("order", ID_1, ["lifecycle", "lifecycle.submitted"],
                         scope=BoundScope(frozenset({ACC_A})),
                         snapshot={"context": _SECRET_CONTEXT})  # fmt: skip
    return dataclasses.replace(
        sealed, envelope=dataclasses.replace(sealed.envelope, snapshot={"chain_trips": 9})
    )


def _wired(*rows: SnapshotRow, sink: Sink) -> Any:
    return inspector(*rows, system_events=sink)


async def _list_twice(*rows: SnapshotRow, sink: Sink) -> Any:
    wired = _wired(*rows, sink=sink)
    first = await wired.listing(OWNER_VIEW)
    await wired.listing(OWNER_VIEW)
    await wired.seal_failures.drain()
    return first


async def test_a_left_out_snapshot_writes_one_critical_row_however_often_it_is_read() -> None:
    sink = Sink()
    found = await _list_twice(*fleet(), _forged(), sink=sink)
    assert (found.snapshots.status, found.snapshots.detail) == ("error", SEAL_FAILED)
    (event,) = sink.events
    assert (event.component, event.kind, event.severity) == (
        "statechart", SEAL_EVENT_KIND, "critical",
    )  # fmt: skip
    assert event.message == SEAL_EVENT_MESSAGE and event.correlation_id is None
    assert event.details == {
        "machine_kind": "order", "machine": f"order:{ID_1}", "environment": "demo",
        "updated_at": NOW.isoformat(), "reason": "seal",
    }  # fmt: skip


async def test_the_row_carries_no_snapshot_content_key_id_or_tag() -> None:
    sink = Sink()
    forged = _forged()
    await _list_twice(forged, sink=sink)
    (event,) = sink.events
    text = repr(dataclasses.asdict(event))
    for leaked in ("never-written", "api_secret", "qty", "chain_trips", "k1"):
        assert leaked not in text, leaked
    assert forged.envelope.seal.tag not in text


async def test_a_verified_fleet_writes_no_row() -> None:
    sink = Sink()
    found = await _list_twice(*fleet(), sink=sink)
    assert found.snapshots.status == "ok" and sink.events == []


async def test_a_new_snapshot_version_of_the_same_machine_is_reported_again() -> None:
    sink, store = Sink(), Store(_forged())
    wired = inspector(store=store, system_events=sink)
    await wired.listing(OWNER_VIEW)
    newer = dataclasses.replace(_forged(), updated_at=NOW + timedelta(seconds=1))
    store.rows = (newer,)
    await wired.listing(OWNER_VIEW)
    await wired.listing(OWNER_VIEW)
    await wired.seal_failures.drain()
    assert [e.details["updated_at"] for e in sink.events] == [
        NOW.isoformat(), (NOW + timedelta(seconds=1)).isoformat(),
    ]  # fmt: skip


async def test_the_detail_and_the_list_share_one_row_per_version() -> None:
    sink = Sink()
    wired = _wired(_forged(), sink=sink)
    detail = await wired.detail(OWNER_VIEW, ("order",), ID_1, "demo")
    assert detail is not None and detail.snapshots.detail == SEAL_FAILED
    await wired.listing(OWNER_VIEW)
    await wired.seal_failures.drain()
    assert len(sink.events) == 1


async def test_a_hidden_machine_writes_no_row_from_the_detail() -> None:
    """Visibility is decided before the seal: a caller who may not see it reads nothing."""
    sink = Sink()
    wired = _wired(_forged(), sink=sink)
    assert await wired.detail(lambda kind, scope: False, ("order",), ID_1, "demo") is None
    await wired.seal_failures.drain()
    assert sink.events == []


async def test_a_kind_without_a_public_id_names_no_entity() -> None:
    sink = Sink()
    sealed = row("position_protection", ID_1, ["sl"])
    await _list_twice(_forged(sealed), sink=sink)
    (event,) = sink.events
    assert "machine" not in event.details and ID_1 not in repr(event)


@pytest.mark.parametrize("sink", [Sink(fail=True), Sink(stall=True)], ids=["fails", "stalls"])
async def test_a_failing_or_stalled_sink_never_fails_the_read(
    sink: Sink, caplog: pytest.LogCaptureFixture
) -> None:
    wired = inspector(*fleet(), _forged(), system_events=sink, seal_timeout_s=0.01)
    failures = wired.seal_failures
    assert failures is not None
    found = await wired.listing(OWNER_VIEW)
    assert found.snapshots.detail == SEAL_FAILED and len(found.items) > 0
    detail = await wired.detail(OWNER_VIEW, ("kill_switch",), None, "demo")
    assert detail is not None and detail.snapshots.status == "ok"
    await failures.drain()
    assert "pw@db" not in caplog.text
    await wired.listing(OWNER_VIEW)  # a failed write is forgotten: the next read tries again
    await failures.drain()
    assert sink.attempts == 2 and sink.events == []


async def test_writes_in_flight_are_bounded_and_the_skipped_version_retries() -> None:
    sink = Sink(stall=True)
    failures = SealFailures(sink, machine_key, timeout_s=60, max_in_flight=1)
    first, second = _forged(), dataclasses.replace(_forged(), environment="live")
    failures.report(first)
    failures.report(second)  # skipped: one write already in flight
    assert len(failures._tasks) == 1
    sink.stall = False
    for task in set(failures._tasks):
        task.cancel()
    await asyncio.sleep(0)
    await failures.drain()
    failures.report(second)
    await failures.drain()
    assert [e.details["environment"] for e in sink.events] == ["live"]


async def test_the_remembered_versions_are_bounded_oldest_first() -> None:
    sink = Sink()
    failures = SealFailures(sink, machine_key, max_reported=2)
    rows = [dataclasses.replace(_forged(), updated_at=NOW + timedelta(seconds=i)) for i in range(3)]
    for r in rows:
        failures.report(r)
    await failures.drain()
    failures.report(rows[0])  # forgotten: the oldest of three with room for two
    failures.report(rows[2])  # still remembered
    await failures.drain()
    assert len(sink.events) == 4


def test_the_builder_wires_the_sink_and_none_without_it() -> None:
    wired = build_statechart_inspector(store=Store(), keys=Keys(), system_events=Sink())
    assert isinstance(wired.seal_failures, SealFailures)
    assert build_statechart_inspector(store=Store(), keys=Keys()).seal_failures is None


async def test_a_row_off_the_contract_is_reported_as_off_contract_not_as_a_seal() -> None:
    """A row whose seal verifies but whose payload is off the contract, and one whose kind the
    registry lacks, are left out under `reason` `off_contract`, never the exception's text."""
    sealed = row("order", ID_1, ["lifecycle", "lifecycle.submitted"],
                 scope=BoundScope(frozenset({ACC_A})), snapshot={"chain_trips": -1})  # fmt: skip
    unknown = dataclasses.replace(_forged(), machine_kind="no_such_kind")
    sink = Sink()
    await _list_twice(sealed, unknown, sink=sink)
    assert sorted((e.details["machine_kind"], e.details["reason"]) for e in sink.events) == [
        ("no_such_kind", "off_contract"), ("order", "off_contract"),
    ]  # fmt: skip
    assert all(e.message == SEAL_EVENT_MESSAGE for e in sink.events)


async def test_the_inspector_without_a_sink_reports_nothing() -> None:
    wired = inspector(_forged())
    assert wired.seal_failures is None
    found = await wired.listing(OWNER_VIEW)
    assert found.snapshots.detail == SEAL_FAILED
