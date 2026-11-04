"""#5817: a rule scoped by `applies_to` fires and acts on the evaluation tick (24 §11.5, E35-S04).

K1b's dispatch rig (`test_dispatch.start`): one tick evaluates the rule on its instance, its fire is
dispatched off the tick and its action reaches the simulation sink (a `simulate` rule) or the
executor's downstream (an `armed` one). A rule scoped to open positions or pending orders does so
as a rule on `any` or `account` does: no scope refusal is recorded or counted for it.

A genuine mismatch the gate refuses is counted under `scope` on every tick, and recorded once per
(rule, instance, reason) episode: by the tick that opens it, again when the reason changes or the
refusal clears and returns, and never by a tick that holds it. An episode whose record job is shed
or whose write fails ends, and so does every episode of a rule that leaves the work list: the next
tick that holds the refusal records it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

import pytest

from candleviewer.rules import service as rules_service
from candleviewer.rules.evaluator import Evaluator
from candleviewer.rules.evaluator.engine import EvaluationResult, scope_instance
from candleviewer.rules.executor import dispatch
from candleviewer.rules.executor.dispatch import Fire
from candleviewer.rules.manager import RuleRow
from candleviewer.rules.scope import DenialEpisodes
from tests.rules.executor.test_dispatch import AUDIT, DispatchRig, Start, _actions, rig, start
from tests.rules.test_scope_applies_to import APPLIES_TO
from tests.rules.test_scope_wiring import OWNER, A, B

__all__ = ["rig", "start"]  # the fixtures, imported


def _applying(row: RuleRow, applies_to: str) -> None:
    """The stored rule's scope narrowed to `applies_to` (the rig's rules are on `any`)."""
    row.versions[0].ir["scope"]["applies_to"] = applies_to


@pytest.mark.parametrize("mode", ["simulate", "armed"])
@pytest.mark.parametrize("applies_to", APPLIES_TO)
async def test_tick_rule_on_each_applies_to_fires_and_its_action_runs(
    rig: DispatchRig, applies_to: str, mode: str
) -> None:
    rid = await rig.add(mode)
    _applying(await rig.row(rid), applies_to)
    await rig.fire()
    await rig.settle()
    reached = rig.simulated if mode == "simulate" else rig.sink.entered
    assert [(r.rule_id, r.instance.account_id) for r in reached] == [(rid, A)]
    assert rig.audits == []  # no scope denial recorded
    assert rig.counted.blocked() == {}  # and none counted


@pytest.mark.parametrize("applies_to", APPLIES_TO)
async def test_tick_rule_on_each_applies_to_is_still_refused_for_a_withdrawn_grant(
    rig: DispatchRig, applies_to: str
) -> None:
    """The gate keeps its refusal for a genuine mismatch: the rule's grant on B is withdrawn, so
    its instance is skipped `scope`, recorded with that reason and counted, and nothing runs."""
    rid = await rig.add("armed", accounts=(B,))
    _applying(await rig.row(rid), applies_to)
    rig.source.grants = [(A, True, False)]
    await rig.fire()
    await rig.settle()
    assert rig.sink.entered == []
    assert [(e, d["reason"]) for e, d in rig.audits] == [
        ("rule_action_scope_denied", "grant_revoked")
    ]
    assert rig.counted.blocked() == {"scope": 1}


def _jobs(rig: DispatchRig, monkeypatch: pytest.MonkeyPatch) -> list[Fire]:
    """Every record-only job offered to the audit queue, recorded as it is offered."""
    offered: list[Fire] = []
    offer = rig.audit_queue.offer

    def recording(job: Fire) -> bool:
        offered.append(job)
        return offer(job)

    monkeypatch.setattr(rig.audit_queue, "offer", recording)
    return offered


def _denials(rig: DispatchRig) -> list[tuple[str, str]]:
    """The scope denials recorded, as (action, reason)."""
    return [(d["action"], d["reason"]) for e, d in rig.audits if e == "rule_action_scope_denied"]


async def _ticks(rig: DispatchRig, n: int) -> None:
    for _ in range(n):
        await rig.fire()
    await rig.settle()


async def test_a_held_refusal_is_recorded_once_and_counted_on_every_tick(
    rig: DispatchRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = _jobs(rig, monkeypatch)
    rid = await rig.add("armed", accounts=(B,))
    rig.source.grants = [(A, True, False)]  # the grant on B is withdrawn, and stays so
    await _ticks(rig, 4)
    assert _denials(rig) == [("send_notification", "grant_revoked")]  # one record
    assert [(j.rule_id, j.kind, len(j.requests)) for j in jobs] == [(rid, "scope_denial", 1)]
    assert rig.counted.blocked() == {"scope": 4}  # every tick's refusal, counted
    resolver = rig.svc.scope_resolver
    assert resolver is not None  # four by the gate, one by the record's own re-check
    assert resolver.suppressions_total["grant_revoked"] == 5
    assert rig.sink.entered == []


async def test_a_held_refusal_records_each_action_of_its_first_tick_only(rig: DispatchRig) -> None:
    await rig.add("simulate", accounts=(B,), actions=_actions("a1", "a2"))
    rig.source.grants = [(A, True, False)]
    await _ticks(rig, 3)
    assert _denials(rig) == [("send_notification", "grant_revoked")] * 2  # a1 and a2, once
    assert rig.counted.blocked() == {"scope": 6}
    assert rig.simulated == []


async def test_a_new_reason_opens_a_new_episode_and_records_again(rig: DispatchRig) -> None:
    await rig.add("armed", accounts=(B,))
    rig.source.grants = [(A, True, False), (B, True, True)]  # the grant on B frozen
    await _ticks(rig, 2)
    rig.source.grants = [(A, True, False)]  # then withdrawn
    await _ticks(rig, 2)
    reasons = [r for _, r in _denials(rig)]
    assert reasons == ["manager_frozen", "grant_revoked"]
    assert rig.counted.blocked() == {"scope": 4}


async def test_a_refusal_that_clears_and_returns_records_again(rig: DispatchRig) -> None:
    rid = await rig.add("armed", accounts=(B,))
    rig.source.grants = [(A, True, False)]
    await _ticks(rig, 2)
    rig.source.grants = [(A, True, False), (B, True, False)]  # restored: the rule fires
    await _ticks(rig, 1)
    assert [r.rule_id for r in rig.sink.entered] == [rid]
    rig.source.grants = [(A, True, False)]  # withdrawn again
    await _ticks(rig, 2)
    assert [r for _, r in _denials(rig)] == ["grant_revoked", "grant_revoked"]
    assert rig.counted.blocked() == {"scope": 4}


async def test_an_instance_held_refused_beside_one_that_fires_is_recorded_once(
    rig: DispatchRig,
) -> None:
    """Episodes are per instance: A firing on every tick never ends B's."""
    await rig.add("armed", accounts=(A, B))
    rig.source.grants = [(A, True, False)]
    await _ticks(rig, 3)
    assert [r.instance.account_id for r in rig.sink.entered] == [A, A, A]
    assert [d["account"] for e, d in rig.audits] == [str(B)]
    assert rig.counted.blocked() == {"scope": 3}


async def test_a_new_rule_version_opens_a_new_episode(rig: DispatchRig) -> None:
    rid = await rig.add("armed", accounts=(B,))
    rig.source.grants = [(A, True, False)]
    await _ticks(rig, 2)
    (await rig.row(rid)).versions[0].ir["version"] = 2
    await _ticks(rig, 2)
    assert [r for _, r in _denials(rig)] == ["grant_revoked", "grant_revoked"]


def _pause(ev: Evaluator) -> None:
    ev.pause()


def _resume(ev: Evaluator) -> None:
    ev.paused = False


def _disable(ev: Evaluator) -> None:
    ev.disabled_reason = "auto_disabled:test"


@pytest.mark.parametrize(("stop", "go"), [(_pause, _resume), (_disable, Evaluator.rearm)])
async def test_a_skip_before_the_gate_neither_ends_nor_opens_an_episode(
    rig: DispatchRig, stop: Callable[[Evaluator], None], go: Callable[[Evaluator], None]
) -> None:
    rid = await rig.add("armed", accounts=(B,))
    rig.source.grants = [(A, True, False)]
    await _ticks(rig, 1)
    ev = rig.runner._evaluators[rid]
    stop(ev)
    await _ticks(rig, 1)  # skipped before the gate: says nothing of it
    go(ev)
    await _ticks(rig, 1)  # the same refusal: the episode holds
    assert _denials(rig) == [("send_notification", "grant_revoked")]
    assert rig.counted.blocked() == {"scope": 2}


def _offers(rig: DispatchRig, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    """Each record-only job offered to the audit queue, as (rule, accepted)."""
    seen: list[tuple[str, bool]] = []
    offer = rig.audit_queue.offer

    def noting(job: Fire) -> bool:
        accepted = offer(job)
        seen.append((job.rule_id, accepted))
        return accepted

    monkeypatch.setattr(rig.audit_queue, "offer", noting)
    return seen


async def test_a_shed_record_job_is_offered_again_on_the_next_tick_that_holds_its_refusal(
    start: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A full audit queue sheds the job of an episode's first refusal, which ends the episode:
    the next tick that holds the refusal offers its records again, they are written once, and
    every refused tick is counted."""
    monkeypatch.setattr(dispatch, "AUDIT_QUEUE_BOUND", 1)
    rig = await start()
    offers = _offers(rig, monkeypatch)
    x = await rig.add("armed", accounts=(A,))
    y = await rig.add("armed", accounts=(B,))
    rig.sink.gate(AUDIT)  # an audit write waits for a release
    rig.source.grants = [(B, True, False)]  # tick 1: the grant on A withdrawn: X refused, Y fires
    await rig.fire()
    await rig.sink.until(lambda: len(rig.audits) == 1)  # X's job is held in its write
    rig.source.grants = [(A, True, True)]  # tick 2: every grant frozen: X anew, Y's job shed
    await rig.fire()
    rig.sink.release(AUDIT, 20)
    await rig.settle()
    await _ticks(rig, 3)  # ticks 3 to 5: both refusals hold
    assert offers == [(x, True), (x, True), (y, False), (y, True)]  # Y's again on tick 3 only
    assert [(d["account"], d["reason"]) for _, d in rig.audits] == [
        (str(A), "grant_revoked"), (str(A), "manager_frozen"), (str(B), "manager_frozen")
    ]  # fmt: skip
    assert rig.counted.shed() == {"scope_denial": 1}
    assert rig.counted.blocked() == {"scope": 9}  # X on five ticks, Y on four


async def test_every_rule_a_tick_refuses_is_recorded_once_as_the_audit_queue_drains(
    start: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Four rules refused on one tick, an audit queue of one: three first jobs are shed. While
    the refusal holds, each tick after the queue drains offers a shed episode's records again,
    until every rule is recorded once."""
    monkeypatch.setattr(dispatch, "AUDIT_QUEUE_BOUND", 1)
    rig = await start()
    offers = _offers(rig, monkeypatch)
    rules = [await rig.add("armed", accounts=(B,)) for _ in range(4)]
    rig.source.grants = [(A, True, False)]  # the grant on B withdrawn, and it stays so
    for _ in range(5):
        await _ticks(rig, 1)  # the queue drains after each tick
    assert sorted(r for r, accepted in offers if accepted) == sorted(rules)  # each one, once
    assert len(_denials(rig)) == 4 and len(offers) == 10
    assert rig.counted.shed() == {"scope_denial": 6}  # three, then two, then one
    assert rig.counted.blocked() == {"scope": 20}


def _first_write_refused(rig: DispatchRig, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The audit store refuses the first scope denial it is given: it raises and keeps nothing."""
    refused: list[str] = []
    passing = rig.sink.passing

    async def refusing(key: str) -> None:
        if key == AUDIT and not refused:
            refused.append(rig.audits.pop()[0])  # taken back: the store kept nothing
            raise RuntimeError("the audit store takes no record")
        await passing(key)

    monkeypatch.setattr(rig.sink, "passing", refusing)
    return refused


async def test_a_failed_record_write_ends_its_episode_so_a_later_tick_records_it(
    rig: DispatchRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    refused = _first_write_refused(rig, monkeypatch)
    await rig.add("armed", accounts=(B,))
    rig.source.grants = [(A, True, False)]  # the grant on B withdrawn, and it stays so
    await _ticks(rig, 1)  # the episode's only write fails
    assert refused == ["rule_action_scope_denied"] and _denials(rig) == []
    await _ticks(rig, 3)  # the refusal holds: the next tick opens the episode again
    assert _denials(rig) == [("send_notification", "grant_revoked")]
    assert rig.counted.blocked() == {"scope": 4}


async def test_a_rule_back_on_the_work_list_records_its_refusal_again(rig: DispatchRig) -> None:
    """A refused rule that leaves the work list ends its episodes: back at the same version and
    still refused for the same reason, it is recorded again."""
    rid = await rig.add("armed", accounts=(B,))
    rig.source.grants = [(A, True, False)]
    await _ticks(rig, 1)
    row = await rig.row(rid)
    row.mode = "disabled"  # off the work list: the runner drops its evaluator
    await _ticks(rig, 1)
    assert rid not in rig.runner._evaluators
    row.mode, row.armed_by = "armed", str(OWNER)
    await _ticks(rig, 1)
    assert _denials(rig) == [("send_notification", "grant_revoked")] * 2
    assert rig.counted.blocked() == {"scope": 2}


async def test_a_deleted_rule_keeps_no_episode(
    start: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[DenialEpisodes] = []

    def episodes() -> DenialEpisodes:
        made.append(DenialEpisodes())
        return made[-1]

    monkeypatch.setattr(rules_service, "DenialEpisodes", episodes)
    rig = await start()
    rid = await rig.add("armed", accounts=(B,))
    rig.source.grants = [(A, True, False)]
    await _ticks(rig, 1)
    (kept,) = made
    assert list(kept._open) == [(rid, scope_instance("BTCUSDT", str(B)))]  # open while refused
    (await rig.row(rid)).deleted = True
    await _ticks(rig, 1)
    assert rid not in rig.runner._evaluators and kept._open == {}


async def test_a_refusal_that_clears_without_a_fire_and_returns_records_again(
    rig: DispatchRig,
) -> None:
    """An evaluation the gate passes ends the episode though the rule does not fire."""
    await rig.add("armed", accounts=(B,))
    rig.source.grants = [(A, True, False)]
    await _ticks(rig, 2)
    rig.source.grants = [(A, True, False), (B, True, False)]  # restored
    await rig.fire(price="50")  # under the threshold: the gate passes and nothing fires
    await rig.settle()
    assert rig.sink.entered == []
    rig.source.grants = [(A, True, False)]  # withdrawn again
    await _ticks(rig, 2)
    assert [r for _, r in _denials(rig)] == ["grant_revoked", "grant_revoked"]
    assert rig.counted.blocked() == {"scope": 4}


async def test_a_scope_skip_without_the_gates_reason_is_offered_on_every_evaluation(
    rig: DispatchRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a refusal the gate names is held: a `scope` skip that carries no reason opens no
    episode, so each such evaluation offers its records."""
    jobs = _jobs(rig, monkeypatch)
    rid = await rig.add("armed", accounts=(B,))
    rig.source.grants = [(A, True, False)]  # the grant on B withdrawn
    await rig.svc.refresh_scope(OWNER)
    (item,) = await rig.mgr.evaluable_rules()
    instance = scope_instance("BTCUSDT", str(B))
    unmarked = EvaluationResult(rid, item.rule.version, instance, "tick", 0, False, "scope")
    on_fire = rig.runner._on_fire
    assert on_fire is not None
    on_fire(item, unmarked)
    on_fire(item, unmarked)
    await rig.settle()
    assert [(j.rule_id, j.kind) for j in jobs] == [(rid, "scope_denial")] * 2
    assert _denials(rig) == [("send_notification", "grant_revoked")] * 2
    assert rig.counted.blocked() == {"scope": 2}


#: The capabilities of the handlers that touch a position or an order (`rules.executor.handlers`).
_POSITION_OR_ORDER: Final = frozenset(
    {"oms_entry", "oms_reduce", "oms_cancel", "oms_amend", "position_stop", "algos"}
)


async def test_no_handler_that_touches_a_position_or_an_order_is_bound_yet(
    rig: DispatchRig,
) -> None:
    """A tripwire for the slices that bind these handlers, with the carry on E35-T12 and #915:
    the entity of each resolved target is judged at dispatch. No table maps an action type to
    its entity yet, so the running executor binds none of them; the slice that binds the first
    one brings that table and makes this test check that every bound type has an entity."""
    executor = rig.svc._executor
    assert executor is not None
    touching = {t: h for t, h in executor._handlers.items() if h.capability in _POSITION_OR_ORDER}
    assert len(touching) == 15  # every type of the six capabilities
    assert [t for t, h in touching.items() if h.handler is not None] == []
