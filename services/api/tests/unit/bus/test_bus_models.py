"""Unit tests for `Topic`/`TopicPattern` (`candleviewer.bus.models`)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from candleviewer.bus.errors import InvalidTopicError
from candleviewer.bus.models import Topic, TopicPattern


def test_topic_key_joins_present_segments_with_dots() -> None:
    topic = Topic(env="demo", domain="md", symbol="BTCUSDT", detail="trade")
    assert topic.key == "demo.md.BTCUSDT.trade"


def test_topic_key_omits_absent_optional_segments() -> None:
    topic = Topic(env="demo", domain="health")
    assert topic.key == "demo.health"


def test_topic_construction_rejects_wildcard_segment() -> None:
    with pytest.raises(ValidationError):
        Topic(env="demo", domain="md", symbol="*")


def test_topic_construction_rejects_empty_segment() -> None:
    with pytest.raises(ValidationError):
        Topic(env="demo", domain="")


@pytest.mark.parametrize("tail", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("field", ["env", "domain", "symbol", "detail"])
def test_topic_construction_rejects_a_segment_ending_in_a_newline(field: str, tail: str) -> None:
    """#3555: `$` also matches before a final newline, so `match` took it, and the dotted key built
    from the topic then carried the newline. Each of the four segments is read."""
    legal = {"env": "demo", "domain": "md", "symbol": "BTCUSDT", "detail": "trade"}
    assert Topic(**legal).key == "demo.md.BTCUSDT.trade"
    with pytest.raises(ValidationError) as info:
        Topic(**{**legal, field: legal[field] + tail})
    assert [e["loc"] for e in info.value.errors()] == [(field,)]


def test_topic_parse_round_trips_key() -> None:
    key = "demo.md.BTCUSDT.trade"
    assert Topic.parse(key).key == key


def test_topic_parse_rejects_wrong_segment_count() -> None:
    with pytest.raises(InvalidTopicError):
        Topic.parse("demo")


def test_topic_pattern_matches_exact_topic() -> None:
    pattern = TopicPattern(env="demo", domain="md", symbol="BTCUSDT", detail="trade")
    topic = Topic(env="demo", domain="md", symbol="BTCUSDT", detail="trade")
    assert pattern.matches(topic)


def test_topic_pattern_wildcard_symbol_matches_any_symbol() -> None:
    pattern = TopicPattern.parse("demo.md.*.trade")
    assert pattern.matches(Topic(env="demo", domain="md", symbol="BTCUSDT", detail="trade"))
    assert pattern.matches(Topic(env="demo", domain="md", symbol="ETHUSDT", detail="trade"))


def test_topic_pattern_does_not_match_different_domain() -> None:
    pattern = TopicPattern.parse("demo.md.*.trade")
    assert not pattern.matches(Topic(env="demo", domain="oms", symbol="BTCUSDT", detail="trade"))


def test_topic_pattern_trailing_wildcard_matches_absent_position() -> None:
    """A trailing wildcard segment matches both a present and an absent
    value at that position (docstring: "any value including absent")."""
    pattern = TopicPattern.parse("demo.health.*")
    assert pattern.matches(Topic(env="demo", domain="health"))
    assert pattern.matches(Topic(env="demo", domain="health", symbol="BTCUSDT"))


def test_topic_pattern_concrete_symbol_does_not_match_absent_symbol() -> None:
    pattern = TopicPattern(env="demo", domain="md", symbol="BTCUSDT")
    assert not pattern.matches(Topic(env="demo", domain="md"))
