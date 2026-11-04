"""E35-T15 PR 1 (#5745): a binding refusal is an evaluation skip, not a gate refusal.

K1b's dispatch rig (`test_dispatch.start`). A rule on accounts A and B whose ref pins B: instance B
reads B's key, and instance A, which may not read it, is skipped `scope` by the binding
(`EvaluationResult.binding_refused`). That refuses no action: nothing is counted under `scope` and
no per-action audit job is queued; the (rule, instance) episode's first skip offers one record-only
job naming the cause and the instance. A refusal by the tick's scope gate keeps its own record.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.rules.executor.dispatch import Fire
from candleviewer.rules.ir.models import MetricRef
from candleviewer.rules.scope import BINDING_CAUSE
from tests.rules.executor.test_dispatch import DispatchRig, Start, rig, start
from tests.rules.test_scope_wiring import OWNER, A, B

__all__ = ["rig", "start"]  # the fixtures, imported

#: The key instance B reads: the ref names no symbol (bound to BTCUSDT) and pins B.
PINNED = MetricRef.model_validate(
    {"metric": "price", "params": {"n": 14}, "symbol": "BTCUSDT", "account_id": str(B)}
)


async def _pinned_rule(rig: DispatchRig, account: uuid.UUID | None = B) -> str:
    """A simulate rule on [A, B] whose condition reads price pinned to `account` (None: open)."""
    rid = await rig.add("simulate", accounts=(A, B))
    _pin(await rig.row(rid), account)
    return rid


def _pin(row: Any, account: uuid.UUID | None) -> None:
    left = row.versions[0].ir["conditions"]["left"]
    if account is None:
        left.pop("account_id", None)
    else:
        left["account_id"] = str(account)


def _jobs(rig: DispatchRig, monkeypatch: pytest.MonkeyPatch) -> list[Fire]:
    """Every job offered to the audit queue, recorded as it is offered."""
    offered: list[Fire] = []
    queue = rig.audit_queue
    offer = queue.offer

    def recording(job: Fire) -> bool:
        offered.append(job)
        return offer(job)

    monkeypatch.setattr(queue, "offer", recording)
    return offered


async def _tick(rig: DispatchRig) -> None:
    """One tick with B's pinned key fresh, settled (`Rig.fire` pushes the unpinned one)."""
    assert rig.svc.metric_source is not None
    rig.svc.metric_source.push(PINNED, Decimal(150), rig.clock.t + 2_000)
    await rig.fire()
    await rig.settle()


def _binding_records(rig: DispatchRig) -> list[dict[str, str]]:
    return [
        d for e, d in rig.audits if e == "rule_action_scope_denied" and d["reason"] == BINDING_CAUSE
    ]


async def test_binding_refusal_counts_no_scope_refusal_and_queues_one_record(
    rig: DispatchRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = _jobs(rig, monkeypatch)
    rid = await _pinned_rule(rig)
    await _tick(rig)
    assert rig.counted.blocked() == {}  # no action refused: the rule was not evaluated on A
    assert [(j.rule_id, j.kind, len(j.requests)) for j in jobs] == [(rid, "scope_denial", 1)]
    [record] = _binding_records(rig)
    assert record == {
        "caller": record["caller"], "reason": BINDING_CAUSE, "rule_id": rid,
        "account": str(A), "symbol": "BTCUSDT",
    }  # fmt: skip
    assert str(B) not in " ".join(record.values())  # no account other than the instance's
    assert [r.instance.account_id for r in rig.simulated] == [B]  # B read its key and fired


async def test_binding_episode_records_once_until_its_refs_are_read(
    rig: DispatchRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = _jobs(rig, monkeypatch)
    rid = await _pinned_rule(rig)
    await _tick(rig)
    await _tick(rig)
    assert len(_binding_records(rig)) == 1 and len(jobs) == 1  # one per episode
    rig.source.grants = [(B, True, False)]  # the gate refuses A: says nothing of the binding
    await rig.svc.refresh_scope(OWNER)
    await _tick(rig)
    rig.source.grants = [(A, True, False), (B, True, False)]
    await rig.svc.refresh_scope(OWNER)
    await _tick(rig)
    assert len(_binding_records(rig)) == 1  # the gate's skips neither ended nor restarted it
    assert rig.counted.blocked() == {"scope": 1}  # the gate's refusal of A's one action
    _pin(await rig.row(rid), None)  # A now reads its own key: the episode ends
    await _tick(rig)
    _pin(await rig.row(rid), B)
    await _tick(rig)
    assert len(_binding_records(rig)) == 2  # a new episode, a new record


async def test_binding_episode_restarts_on_a_new_rule_version(rig: DispatchRig) -> None:
    rid = await _pinned_rule(rig)
    await _tick(rig)
    (await rig.row(rid)).versions[0].ir["version"] = 2
    await _tick(rig)
    assert len(_binding_records(rig)) == 2


async def test_gate_denial_still_writes_its_record_beside_a_binding_skip(
    start: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await start()
    jobs = _jobs(rig, monkeypatch)
    await _pinned_rule(rig)
    rig.source.grants = [(A, True, False)]  # B's grant withdrawn: the gate refuses B
    await rig.svc.refresh_scope(OWNER)
    await _tick(rig)
    assert rig.counted.blocked() == {"scope": 1}  # B's one action, once
    assert sorted(j.kind for j in jobs) == ["scope_denial", "scope_denial"]
    denials = sorted((d["reason"], d["account"]) for e, d in rig.audits)
    assert denials == [("grant_revoked", str(B)), (BINDING_CAUSE, str(A))]
    assert rig.simulated == []
