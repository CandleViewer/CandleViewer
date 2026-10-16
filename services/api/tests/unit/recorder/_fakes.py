"""Shared fakes for the recorder unit tests: a settable clock, a recording bus and an audit sink
(no I/O, no sleeps). Tests import them from here, never from `conftest.py` or a test module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from candleviewer.bus.models import Topic


class FakeClock:
    def __init__(self, t: float = 1_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


@dataclass
class FakeBus:
    """Records each publish as `(topic key, event)`; `fail_next` makes the next publish raise."""

    events: list[tuple[str, Any]] = field(default_factory=list)
    fail_next: bool = False

    async def publish(self, topic: Topic, event: Any) -> None:
        if self.fail_next:
            self.fail_next = False
            raise OSError("bus unavailable")
        self.events.append((topic.key, event))


class FakeAudit:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.records.append((action, kwargs))

    def envs(self) -> list[tuple[str, str]]:
        return [(a, kw["env"]) for a, kw in self.records]

    def actions(self) -> list[str]:
        return [a for a, _ in self.records]
