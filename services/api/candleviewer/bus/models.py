"""Domain models for the bus module (M5).

`Topic` is the validated `{env}.{domain}.{symbol?}.{detail?}` identifier
(`docs/plan/20-architecture.md` §3 bus contract). `QueuePolicy` is the
three-way backpressure policy (§4.2). `StreamInvalidated` is the marker
delivered to an `INVALIDATE_ON_FULL` subscriber instead of a partial
sequence.

Security note (E08-T03 body): `Topic` construction rejects any segment
containing a wildcard character so a future client-facing subscription
(E17) cannot widen its scope by injecting `*`/`#` through a user-controlled
string — topics are built from validated symbol/domain enums only.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from candleviewer.domain.primitives import TsUs

WILDCARD = "*"
"""The single wildcard segment accepted only in `subscribe()` patterns, never
inside a concrete published `Topic`."""

_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class QueuePolicy(StrEnum):
    """Backpressure policy for a subscriber queue (§4.2 backpressure matrix).

    - ``NEVER_DROP``: publish awaits when the queue is full; nothing is lost.
      Used for trades and executions.
    - ``INVALIDATE_ON_FULL``: on overflow the subscriber receives a single
      `StreamInvalidated` marker instead of a partial delta sequence, then
      the queue is cleared to make room. Used for book deltas.
    - ``CONFLATE_LATEST``: only the newest event per topic is retained; an
      overflow replaces the pending item rather than blocking. Used for
      state-like topics (tickers, health, heatmap columns).
    """

    NEVER_DROP = "NEVER_DROP"
    INVALIDATE_ON_FULL = "INVALIDATE_ON_FULL"
    CONFLATE_LATEST = "CONFLATE_LATEST"


class StreamInvalidated(BaseModel):
    """Delivered to an `INVALIDATE_ON_FULL` subscriber in place of the
    partial sequence dropped on overflow (Gherkin: "Book deltas invalidate
    rather than skip"). The reason code is machine-readable (accessibility
    note: consuming UI surfaces must not rely on colour/icon alone)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    topic: str
    reason_code: Literal["queue_overflow"] = "queue_overflow"
    ts_event: TsUs


class Topic(BaseModel):
    """A validated, immutable bus topic: `{env}.{domain}.{symbol?}.{detail?}`.

    Construct only from validated enum/symbol values (never from raw
    user/client-controlled strings) so a wildcard segment can never be
    injected (security note)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    env: str
    domain: str
    symbol: str | None = None
    detail: str | None = None

    @field_validator("env", "domain", "symbol", "detail")
    @classmethod
    def _no_wildcards_or_empties(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not _SEGMENT_RE.fullmatch(value):
            from candleviewer.bus.errors import InvalidTopicError

            raise InvalidTopicError(
                f"topic segment {value!r} must match {_SEGMENT_RE.pattern} "
                "(no wildcards, no empty segments)"
            )
        return value

    @property
    def key(self) -> str:
        """The dotted wire representation, e.g. `demo.md.BTCUSDT.trade`."""
        parts = [self.env, self.domain]
        if self.symbol is not None:
            parts.append(self.symbol)
        if self.detail is not None:
            parts.append(self.detail)
        return ".".join(parts)

    @property
    def topic_class(self) -> str:
        """Metric-label-friendly class: `{domain}.{detail}` or `{domain}`."""
        return f"{self.domain}.{self.detail}" if self.detail else self.domain

    def __str__(self) -> str:
        return self.key

    @classmethod
    def parse(cls, key: str) -> Topic:
        """Parse a dotted key back into a `Topic` (used by tests/tools only;
        production publishers should construct `Topic(...)` directly)."""
        segments = key.split(".")
        if not 2 <= len(segments) <= 4:
            from candleviewer.bus.errors import InvalidTopicError

            raise InvalidTopicError(f"topic key {key!r} must have 2-4 segments")
        env, domain, *rest = segments
        symbol = rest[0] if len(rest) >= 1 else None
        detail = rest[1] if len(rest) >= 2 else None
        return cls(env=env, domain=domain, symbol=symbol, detail=detail)


class TopicPattern(BaseModel):
    """A subscription pattern: each field is either a concrete value or the
    `WILDCARD` sentinel (`*`), matching any value at that position. `symbol`/
    `detail` left as `None` mean "this position is absent", distinct from
    `WILDCARD` which means "any value including absent" only at the trailing
    positions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    env: str
    domain: str
    symbol: str | None = None
    detail: str | None = None

    def matches(self, topic: Topic) -> bool:
        def _seg(pattern: str | None, value: str | None) -> bool:
            if pattern is None:
                return value is None
            if pattern == WILDCARD:
                return True
            return pattern == value

        return (
            _seg(self.env, topic.env)
            and _seg(self.domain, topic.domain)
            and _seg(self.symbol, topic.symbol)
            and _seg(self.detail, topic.detail)
        )

    @classmethod
    def parse(cls, pattern: str) -> TopicPattern:
        segments = pattern.split(".")
        if not 2 <= len(segments) <= 4:
            from candleviewer.bus.errors import InvalidTopicError

            raise InvalidTopicError(f"topic pattern {pattern!r} must have 2-4 segments")
        env, domain, *rest = segments
        symbol = rest[0] if len(rest) >= 1 else None
        detail = rest[1] if len(rest) >= 2 else None
        return cls(env=env, domain=domain, symbol=symbol, detail=detail)
