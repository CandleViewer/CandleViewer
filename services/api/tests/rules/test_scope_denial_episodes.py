"""#5817: the tick gate's refusals of a (rule, instance) are recorded once per episode.

`DenialEpisodes.first(result)` answers whether an evaluation opens an episode, so its refusal is
recorded: a refusal opens one; the same refusal, at the same rule version, holds it; another reason
or another version opens a new one; an evaluation the gate passes ends it; a skip decided before
the gate (`disabled`, `paused`) neither opens nor ends one. An episode also ends when its record
job is shed or its write fails (`forget`, `ending_on_failure`) and when its rule leaves the work
list (`retain`).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

import pytest

from candleviewer.rules.evaluator.engine import EvaluationResult
from candleviewer.rules.ir.models import RuleScope
from candleviewer.rules.scope import ActionRequest, DenialEpisodes, ScopeInstanceRef
from tests.rules.executor.request_builders import action_request

RULE, OTHER = "r-1", "r-2"
AT_A, AT_B = "BTCUSDT@a", "BTCUSDT@b"
REQ = action_request(
    RuleScope(level="account"), uuid.UUID(int=1), ScopeInstanceRef(AT_A, None, None)
)


def _refused(
    reason: str, instance: str = AT_A, version: int = 1, *, rule: str = RULE
) -> EvaluationResult:
    return EvaluationResult(rule, version, instance, "t", 0, False, "scope", scope_refusal=reason)


def _skipped(skipped: str | None, instance: str = AT_A, *, fired: bool = False) -> EvaluationResult:
    return EvaluationResult(RULE, 1, instance, "t", 0, fired, skipped)


def test_episodes_a_held_refusal_opens_once() -> None:
    episodes = DenialEpisodes()
    held = [episodes.first(_refused("grant_revoked")) for _ in range(4)]
    assert held == [True, False, False, False]


def test_episodes_another_reason_opens_a_new_episode() -> None:
    episodes = DenialEpisodes()
    reasons = ("manager_frozen", "manager_frozen", "grant_revoked", "grant_revoked")
    opened = [episodes.first(_refused(r)) for r in reasons]
    assert opened == [True, False, True, False]


def test_episodes_a_passed_evaluation_ends_the_episode_and_a_return_opens_one() -> None:
    episodes = DenialEpisodes()
    for passed in (_skipped(None, fired=True), _skipped(None), _skipped("cooldown")):
        assert episodes.first(_refused("grant_revoked"))
        assert not episodes.first(passed)  # the gate passed the instance: the episode ends
    assert episodes.first(_refused("grant_revoked"))


def test_episodes_a_skip_before_the_gate_neither_ends_nor_opens_one() -> None:
    episodes = DenialEpisodes()
    assert episodes.first(_refused("grant_revoked"))
    assert not episodes.first(_skipped("paused"))
    assert not episodes.first(_skipped("disabled"))
    assert not episodes.first(_refused("grant_revoked"))  # still the same episode


def test_episodes_are_per_instance_and_per_rule_version() -> None:
    episodes = DenialEpisodes()
    assert episodes.first(_refused("grant_revoked", AT_A))
    assert episodes.first(_refused("grant_revoked", AT_B))  # another instance: its own episode
    assert not episodes.first(_skipped(None, AT_A))  # A passes: B's episode holds
    assert not episodes.first(_refused("grant_revoked", AT_B))
    assert episodes.first(_refused("grant_revoked", AT_B, version=2))  # a new version: a new one


def test_episodes_forget_ends_the_episode_a_result_opened_while_it_holds() -> None:
    episodes = DenialEpisodes()
    frozen, revoked = _refused("manager_frozen"), _refused("grant_revoked")
    assert episodes.first(frozen)
    episodes.forget(frozen)  # its record job shed: the episode ends
    assert episodes.first(frozen)  # so the next evaluation opens it again
    assert episodes.first(revoked)  # another reason: a new episode
    episodes.forget(frozen)  # the earlier episode's late failure leaves this one open
    assert not episodes.first(revoked)


def test_episodes_retain_ends_the_episodes_of_a_rule_off_the_work_list() -> None:
    episodes = DenialEpisodes()
    gone = _refused("grant_revoked", rule=OTHER)
    assert episodes.first(_refused("grant_revoked")) and episodes.first(gone)
    episodes.retain({RULE})  # OTHER left the work list
    assert not episodes.first(_refused("grant_revoked"))  # RULE's episode holds
    assert episodes.first(gone)  # OTHER's ended: back, it opens one


async def _raises(_req: ActionRequest) -> bool:
    raise RuntimeError("the audit store takes no record")


async def _never_answers(_req: ActionRequest) -> bool:
    await asyncio.Event().wait()
    return False


async def _written(_req: ActionRequest) -> bool:
    return False  # the emitter's answer for an action it refused and recorded


@pytest.mark.parametrize(
    ("emit", "error"), [(_raises, RuntimeError), (_never_answers, TimeoutError)]
)
async def test_episodes_a_record_job_whose_write_fails_ends_its_episode(
    emit: Callable[[ActionRequest], Awaitable[bool]], error: type[Exception]
) -> None:
    """A write that raises, or that its bound cuts short (as the executor bounds each action),
    ends the episode, and the failure goes on to the job."""
    episodes, result = DenialEpisodes(), _refused("grant_revoked")
    assert episodes.first(result)
    with pytest.raises(error):
        async with asyncio.timeout(0):
            await episodes.ending_on_failure(result, emit)(REQ)
    assert episodes.first(result)  # ended: the next evaluation opens it and records it


async def test_episodes_a_record_job_that_writes_keeps_its_episode() -> None:
    episodes, result = DenialEpisodes(), _refused("grant_revoked")
    assert episodes.first(result)
    assert await episodes.ending_on_failure(result, _written)(REQ) is False  # its answer, as is
    assert not episodes.first(result)  # the episode holds
