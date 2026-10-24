"""What the policy's own audit records carry (#2188 S3b): the id of the request they are written
in (C-2.9's trace id) and `held_hidden` on a join that the actor's view hides (#492)."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

import pytest

from candleviewer.audit.redact import redact
from candleviewer.observability.context import bind_context, current_request_uuid
from candleviewer.recorder.errors import RecorderInvalidUpdateError
from candleviewer.recorder.policy import PolicyConfig, RecordingPolicy, user_actor
from tests.unit.recorder._fakes import FakeAudit, FakeBus, FakeClock, Mem

OWNER, MANAGER = user_actor("owner-1"), user_actor("mgr-2")


def _by(audit: FakeAudit, who: str) -> list[tuple[str, Any]]:
    """`(action, request id)` of the records `who` ("user" or "system") wrote."""
    return [(a, kw["request_id"]) for a, kw in audit.records if kw["actor_label"].startswith(who)]


async def test_a_users_records_carry_the_request_they_are_written_in(
    policy: RecordingPolicy, audit: FakeAudit
) -> None:
    rid = uuid.uuid4()
    with bind_context(request_id=rid):
        await policy.add_manual("BTCUSDT", OWNER)
        await policy.update_manual("BTCUSDT", OWNER, depth=50)
        await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
        await policy.remove_manual("BTCUSDT", OWNER)
    await policy.add_manual("ETHUSDT", OWNER)  # outside a request: a job, a test
    assert _by(audit, "user") == [
        ("recorder.start", rid),
        ("recorder.update", rid),
        ("retention.change", rid),
        ("recorder.stop", rid),
        ("recorder.start", None),
    ]


async def test_a_b11_hook_record_carries_no_request_id_though_its_task_could_read_one(
    policy: RecordingPolicy, audit: FakeAudit, clock: FakeClock
) -> None:
    """A chart's task copies the context `build()` ran in, so each hook of a chart a request
    started reads that request's id, the stop 30 minutes on too: the session's records get none."""
    seen: list[tuple[str, uuid.UUID | None]] = []

    async def hooks(symbol: str, hook: str, context: Mapping[str, object]) -> None:
        seen.append((hook, current_request_uuid()))

    policy.observe_states(hooks)
    rid = uuid.uuid4()
    with bind_context(request_id=rid):
        await policy.add_manual("BTCUSDT", OWNER)  # builds the chart, and so its task
    await policy.remove_manual("BTCUSDT", OWNER)
    clock.advance(1800)
    await policy.tick()  # no request: the grace ends and the chart stops
    assert ("unsubscribe", rid) in seen and {request for _, request in seen} == {rid}
    assert _by(audit, "system") == [("recorder.start", None), ("recorder.stop", None)]


async def test_a_join_marks_its_record_held_hidden_and_changes_nothing_else(
    policy: RecordingPolicy, audit: FakeAudit
) -> None:
    await policy.on_position_opened("BTCUSDT", "p1")  # held for another reason
    audit.records.clear()
    rid = uuid.uuid4()
    with bind_context(request_id=rid):
        await policy.add_manual("BTCUSDT", MANAGER, held_hidden=True)
    ((action, kw),) = audit.records
    assert (action, kw["outcome"], kw["request_id"]) == ("recorder.start", "success", rid)
    assert kw["after_state"] == {
        "symbol": "BTCUSDT", "reason": "manual", "actor": "mgr-2",
        "trigger_ref": "manual:mgr-2", "held_hidden": True,
    }  # fmt: skip
    assert redact(dict(kw["after_state"])) == kw["after_state"]  # the real writer stores it so
    assert policy.effective_set()["BTCUSDT"].reasons == ("manual", "position_open")


async def test_held_hidden_is_absent_unless_given_and_writes_nothing_on_its_own(
    policy: RecordingPolicy, audit: FakeAudit
) -> None:
    await policy.add_manual("BTCUSDT", OWNER, held_hidden=False)
    assert "held_hidden" not in audit.records[0][1]["after_state"]  # absent, not False
    audit.records.clear()
    await policy.add_manual("BTCUSDT", MANAGER, held_hidden=True)  # already manual: left alone
    assert audit.records == []


async def test_a_join_writes_the_same_row_checks_and_memory_as_an_add_without_the_flag(
    policy: RecordingPolicy, store: Mem, audit: FakeAudit
) -> None:
    for symbol in ("BTCUSDT", "ETHUSDT"):
        await policy.on_position_opened(symbol, "p1")  # held for another reason, as a join is
    await policy.add_manual("BTCUSDT", MANAGER, ("trades",), 50)
    await policy.add_manual("ETHUSDT", MANAGER, ("trades",), 50, held_hidden=True)

    def row(symbol: str) -> dict[str, Any]:
        found = store.active(symbol)
        assert found is not None
        return {k: v for k, v in found.items() if k not in ("id", "symbol")}

    assert row("ETHUSDT") == row("BTCUSDT")  # the adder, the streams, the depth, no pin
    entries = policy.effective_set()
    assert entries["ETHUSDT"].model_copy(update={"symbol": "BTCUSDT"}) == entries["BTCUSDT"]
    audit.records.clear()
    for symbol in ("BTCUSDT", "ETHUSDT"):  # the adder in memory, which the set does not show
        await policy.remove_manual(symbol, MANAGER)
    stops = [(kw["object_id"], kw["after_state"]["trigger_ref"]) for _, kw in audit.records]
    assert stops == [("BTCUSDT", "manual:mgr-2"), ("ETHUSDT", "manual:mgr-2")]
    audit.records.clear()
    with pytest.raises(RecorderInvalidUpdateError):  # the settings are checked all the same
        await policy.add_manual("SOLUSDT", MANAGER, depth=7, held_hidden=True)
    assert audit.records == [] and store.active("SOLUSDT") is None


async def test_a_cap_refusals_record_carries_the_request_it_ran_in(
    clock: FakeClock, bus: FakeBus, audit: FakeAudit, store: Mem
) -> None:
    capped = RecordingPolicy(
        disk_refuses=bool, bus=bus, audit=audit, env="demo", now=clock, recorded=store,
        config=PolicyConfig(max_symbols=1),
    )  # fmt: skip
    capped.positions_reloaded()
    try:
        await capped.add_manual("BTCUSDT", OWNER)  # takes the one slot
        rid = uuid.uuid4()
        with bind_context(request_id=rid):
            await capped.on_position_opened("SOLUSDT", "p1")  # refused for the cap
        denied = [kw["request_id"] for _, kw in audit.records if kw["outcome"] == "denied"]
        assert denied == [rid]
    finally:
        await capped.stop()
