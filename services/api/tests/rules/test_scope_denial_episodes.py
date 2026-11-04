"""#5817: the tick gate's refusals of a (rule, instance) are recorded once per episode.

`DenialEpisodes.first(result)` answers whether an evaluation opens an episode, so its refusal is
recorded: a refusal opens one; the same refusal, at the same rule version, holds it; another reason
or another version opens a new one; an evaluation the gate passes ends it; a skip decided before
the gate (`disabled`, `paused`) neither opens nor ends one.
"""

from __future__ import annotations

from candleviewer.rules.evaluator.engine import EvaluationResult
from candleviewer.rules.scope import DenialEpisodes

RULE = "r-1"
AT_A, AT_B = "BTCUSDT@a", "BTCUSDT@b"


def _refused(reason: str, instance: str = AT_A, version: int = 1) -> EvaluationResult:
    return EvaluationResult(RULE, version, instance, "t", 0, False, "scope", scope_refusal=reason)


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
