"""E35-T09 (#5000) slice 2d: what the tick refuses is recorded off the tick (BQ-4, BQ-5), and a
stop writes nothing (the K1b carry).

K1b's dispatch rig (`test_dispatch.start`): a refused fire's records go as one record-only job on
the audit queue, offered and never awaited; a full audit queue sheds the job and counts it; every
scope refusal counts once under `scope`; a fire cut short at stop keeps its run row `running`.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.rules.executor import dispatch
from candleviewer.rules.executor.keys import dedupe_key
from candleviewer.rules.executor.ports import ActionAuditFields, EventRow, RunRow
from candleviewer.rules.scope import ActionRequest
from tests.rules.executor.test_dispatch import GUARD_S, DispatchRig, Start, _actions, rig, start
from tests.rules.test_scope_wiring import A, B

__all__ = ["rig", "start"]  # the fixtures, imported


def _hold_refused_runs(
    rig: DispatchRig, monkeypatch: pytest.MonkeyPatch
) -> tuple[asyncio.Event, asyncio.Event]:
    """A refused fire's run row waits for `gate`: the audit worker holds its job, and `held` is
    set once it does."""
    gate, held, begin = asyncio.Event(), asyncio.Event(), rig.records.begin

    async def holding(run: RunRow, first: EventRow) -> None:
        if first.payload.get("blocked_by") == "backpressure":
            held.set()
            await gate.wait()
        await begin(run, first)

    monkeypatch.setattr(rig.records, "begin", holding)
    return gate, held


async def test_a_refused_fire_writes_one_blocked_record_per_action_off_the_tick(
    start: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tick that refuses the fire returns while its records are still unwritten; then the
    audit worker writes the run row (`throttled`) and per action `action_fail` (`blocked`,
    `backpressure`, no account) and `rules.blocked`, never `rules.fired`."""
    monkeypatch.setattr(dispatch, "FIRE_QUEUE_BOUND", 1)
    rig = await start()
    gate, held = _hold_refused_runs(rig, monkeypatch)
    rid = await rig.add("armed", actions=_actions("a1", "a2"))
    rig.sink.gate(rid)
    await rig.fire()
    await rig.sink.reached(1)  # fire 1 is in the sink; fire 2 waits; fire 3 is refused
    async with asyncio.timeout(GUARD_S):  # a tick that awaited the records would never return
        await rig.fire()
        await rig.fire()
    refused = uuid.UUID(int=3)
    async with asyncio.timeout(GUARD_S):
        await held.wait()  # the audit worker took the job, and holds its first write
    assert refused not in rig.records.runs and rig.audit_queue.queued == 0
    gate.set()
    rig.sink.release(rid, 4)
    await rig.settle()
    assert rig.records.closed[refused] == ("throttled", 0)
    assert rig.records.runs[refused].mode == "armed"  # the rule's own mode (below: `simulate`)
    rows = [(e.kind, e.payload["node_id"], e.payload["outcome"], e.payload["blocked_by"],
             e.payload["account_id"]) for r, e in rig.records.events if r == refused]  # fmt: skip
    assert rows == [("action_fail", n, "blocked", "backpressure", None) for n in ("a1", "a2")]
    mine = [
        (verb, f.node_id, f.blocked_by) for verb, f in rig.records.audits if f.run_id == refused
    ]
    assert mine == [("rules.blocked", n, "backpressure") for n in ("a1", "a2")]
    theirs = [f for _, f in rig.records.audits if f.run_id == refused]
    assert [(f.account_id, f.dedupe_key) for f in theirs] == [
        (None, _unresolved_key(f)) for f in theirs
    ]
    assert rig.counted.blocked() == {"backpressure": 2}


def _unresolved_key(f: ActionAuditFields) -> str:
    """An unresolved action's key (24 §11.9): its account is the JSON `null`."""
    return dedupe_key(
        rule_id=f.rule_id, version=f.version, scope_instance=f.scope_instance, node_id=f.node_id,
        run_id=f.run_id, account_id=None,
    )  # fmt: skip


async def test_a_refused_simulate_fire_is_recorded_under_its_own_mode(
    start: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `simulate` rule's fire the full queue refuses is recorded as an armed one's is (24 §11.5
    "The fire queue"), under its own mode: its run row names `simulate`, never `armed`, closed
    `throttled`, with its `rules.blocked` record, and no armer."""
    monkeypatch.setattr(dispatch, "FIRE_QUEUE_BOUND", 1)
    rig = await start()
    entered, release = asyncio.Event(), asyncio.Event()

    async def held(_req: ActionRequest) -> None:  # the simulation sink holds fire 1's worker
        entered.set()
        await release.wait()

    monkeypatch.setattr(rig.svc, "_simulation_sink", held)
    await rig.add("simulate")
    await rig.fire()
    async with asyncio.timeout(GUARD_S):
        await entered.wait()  # fire 1 is in the simulation sink
    await rig.fire()  # fire 2 waits
    await rig.fire()  # fire 3 is refused
    release.set()
    await rig.settle()
    refused = uuid.UUID(int=3)
    run = rig.records.runs[refused]
    assert (run.mode, rig.records.closed[refused]) == ("simulate", ("throttled", 0))
    mine = [(verb, f.blocked_by, f.armed_by) for verb, f in rig.records.audits]
    assert mine == [("rules.blocked", "backpressure", None)]
    assert set(rig.records.runs) == {refused}  # a simulate fire that ran writes no row


async def test_a_full_record_queue_sheds_and_counts_never_awaits(
    start: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the audit queue full, the refused fire's record job is shed on the tick, never
    awaited: counted under its kind, logged once per rule and episode, its actions still counted
    `backpressure` and nothing paged beyond the fire queue's own page."""
    monkeypatch.setattr(dispatch, "FIRE_QUEUE_BOUND", 1)
    monkeypatch.setattr(dispatch, "AUDIT_QUEUE_BOUND", 1)
    rig = await start()
    gate, held = _hold_refused_runs(rig, monkeypatch)
    rid = await rig.add("armed")
    rig.sink.gate(rid)
    await rig.fire()
    await rig.sink.reached(1)
    with capture_logs() as logs:
        async with asyncio.timeout(GUARD_S):  # a tick that awaited a record job would not return
            await rig.fire()  # fire 2 waits
            await rig.fire()  # fire 3 is refused: its record job is taken, then held
            await held.wait()
            await rig.fire()  # fire 4 is refused: its job waits
            await rig.fire()  # fire 5 is refused: its job is shed
    assert rig.counted.shed() == {"refused_fire": 1} and rig.counted.blocked() == {
        "backpressure": 3
    }
    shed = [e for e in logs if e["event"] == "rules.records_shed"]
    assert [(e["rule_id"], e["kind"], e["run_id"]) for e in shed] == [
        (rid, "refused_fire", str(uuid.UUID(int=5)))
    ]
    pages = [e for e in logs if e.get("cv_page")]
    assert [e["event"] for e in pages] == ["rules.dispatch_backpressure"]
    gate.set()
    rig.sink.release(rid, 2)
    await rig.settle()
    assert set(rig.records.closed) >= {uuid.UUID(int=3), uuid.UUID(int=4)}
    assert uuid.UUID(int=5) not in rig.records.runs


async def test_every_scope_denial_counts_once_under_scope(
    rig: DispatchRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BQ-5: the tick gate's refusals count as their audit job is offered, written or shed, and
    are not counted again when it is written; an armed action the dispatch-time re-check refuses
    counts once, as its `blocked` result. Each scope refusal, once."""
    skipped = await rig.add("armed", accounts=(B,), actions=_actions("a1", "a2"))
    rig.source.grants = [(A, True, False)]  # the grant on B is withdrawn: skipped `scope`
    await rig.fire()
    await rig.settle()
    assert rig.counted.blocked() == {"scope": 2} and len(rig.audits) == 2
    assert all(f.rule_id != skipped for _, f in rig.records.audits)  # no fire, no rule record
    resolver = rig.svc.scope_resolver
    assert resolver is not None
    gate = resolver.check_action

    def denied_at_dispatch(*args: Any, **kwargs: Any) -> Any:
        task = asyncio.current_task()
        if task is not None and task.get_name().startswith("rule-dispatch-worker"):
            return "grant_revoked"
        return gate(*args, **kwargs)

    monkeypatch.setattr(resolver, "check_action", denied_at_dispatch)
    (await rig.row(skipped)).mode = "disabled"  # no longer evaluated
    armed = await rig.add("armed")  # on A, which the tick's gate passes
    await rig.fire()
    await rig.settle()
    assert rig.counted.blocked() == {"scope": 3}
    refusals = [
        (f.rule_id, f.blocked_by) for verb, f in rig.records.audits if verb == "rules.blocked"
    ]
    assert (armed, "scope") in refusals and rig.sink.entered == []
    denials = [(event, data["reason"]) for event, data in rig.audits[2:]]
    assert denials == [("rule_action_scope_denied", "grant_revoked")]  # the emitter's own record


async def test_stop_leaves_an_in_flight_fires_run_row_running(rig: DispatchRig) -> None:
    """A fire cut short at stop keeps its run row `running`, with its last `action_start` and no
    outcome; nothing is written at shutdown, and the stop line keeps K1b's counts by rule."""
    rid = await rig.add("armed", actions=_actions("a1", "a2"))
    rig.sink.gate(rid)  # never released: the fire is cut short in its first action
    await rig.fire()
    await rig.sink.reached(1)
    with capture_logs() as logs:
        await rig.svc.stop(0.0)
    run = uuid.UUID(int=1)
    assert run in rig.records.runs and run not in rig.records.closed
    assert [(e.kind, e.node_ref) for r, e in rig.records.events if r == run] == [
        ("action_start", "a1")
    ]
    assert [f.node_id for verb, f in rig.records.audits if verb == "rules.fired"] == ["a1"]
    cancelled = [e for e in logs if e["event"] == "rules.fire_cancelled"]
    assert [(e["rule_id"], e["run_id"]) for e in cancelled] == [(rid, str(run))]
