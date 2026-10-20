"""A bus topic's `env` (E26-T03, `24-internal-schemas.md` §2.9): `live`, `demo`, `testnet`, or one
replay session's namespace, `replay-` plus its UUID in lower-case canonical form. Nothing else is a
topic, so a replay topic never equals a live one (C-2.11)."""

from __future__ import annotations

import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.bus.models import LIVE_ENVS, Topic, TopicPattern, is_replay_env, replay_env

SESSION = uuid.UUID("0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f18")


@pytest.mark.parametrize(
    "env", ["live", "demo", "testnet", "replay-0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f18"]
)
def test_topic_env_accepts_the_live_pipelines_and_a_replay_namespace(env: str) -> None:
    assert Topic(env=env, domain="md", symbol="BTCUSDT", detail="trade").env == env


@pytest.mark.parametrize(
    "env",
    [
        "test",
        "dev",
        "prod",
        "LIVE",
        "Demo",
        "replay",
        "replay-",
        "replay-0B7C5E1A-3F2D-4C8E-9A61-5D0E7B2C4F18",  # upper case is not canonical
        "replay-0b7c5e1a3f2d4c8e9a615d0e7b2c4f18",  # no dashes
        "replay-0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f1",  # one digit short
        "replay-0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f18-live",
        "live-0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f18",
        "replay_0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f18",
    ],
)
def test_topic_env_refuses_anything_else(env: str) -> None:
    with pytest.raises(ValidationError) as info:
        Topic(env=env, domain="md", symbol="BTCUSDT", detail="trade")
    assert [e["loc"] for e in info.value.errors()] == [("env",)]
    assert "topic env" in str(info.value)  # the bus's own refusal, not a charset one
    with pytest.raises(ValidationError):
        Topic.parse(f"{env}.md.BTCUSDT.trade")


def test_replay_env_is_the_sessions_lower_case_canonical_uuid() -> None:
    env = replay_env(SESSION)
    assert env == "replay-0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f18"
    assert Topic(env=env, domain="md", symbol="BTCUSDT", detail="trade").key == (
        "replay-0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f18.md.BTCUSDT.trade"
    )


@given(st.uuids())
def test_a_replay_topic_never_equals_or_matches_a_live_one(session: uuid.UUID) -> None:
    env = replay_env(session)
    assert is_replay_env(env) and env not in LIVE_ENVS
    replayed = Topic(env=env, domain="md", symbol="BTCUSDT", detail="book")
    for live in sorted(LIVE_ENVS):
        assert not is_replay_env(live)
        assert TopicPattern(env=live, domain="md", symbol="BTCUSDT", detail="book").matches(
            Topic(env=live, domain="md", symbol="BTCUSDT", detail="book")
        )
        assert not TopicPattern(env=live, domain="md", symbol="BTCUSDT", detail="book").matches(
            replayed
        )
    other = Topic(env=replay_env(uuid.UUID(int=session.int ^ 1)), domain="md", symbol="BTCUSDT")
    assert other.env != replayed.env  # one session's namespace is not another's
