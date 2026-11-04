"""#5817: a rule scoped by `applies_to` fires and acts on the evaluation tick (24 §11.5, E35-S04).

K1b's dispatch rig (`test_dispatch.start`): one tick evaluates the rule on its instance, its fire is
dispatched off the tick and its action reaches the simulation sink (a `simulate` rule) or the
executor's downstream (an `armed` one). A rule scoped to open positions or pending orders does so
as a rule on `any` or `account` does: no scope refusal is recorded or counted for it.

A genuine mismatch the gate refuses is counted under `scope` on every tick, and recorded once per
(rule, instance, reason) episode: by the tick that opens it, again when the reason changes or the
refusal clears and returns, and never by a tick that holds it.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from candleviewer.rules.evaluator import Evaluator
from candleviewer.rules.executor.dispatch import Fire
from candleviewer.rules.manager import RuleRow
from tests.rules.executor.test_dispatch import DispatchRig, _actions, rig, start
from tests.rules.test_scope_applies_to import APPLIES_TO
from tests.rules.test_scope_wiring import A, B

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
