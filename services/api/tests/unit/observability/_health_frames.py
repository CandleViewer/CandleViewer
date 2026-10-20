"""Shared fakes of the health-frame tests (E42-T05, #966 BK-15): a probe, a clock, what a ClockGuard
answers, the `system` envelope of `23-ws-protocol.md` 13.1, and the one frame a publisher builds for
a snapshot, checked by the WS tests' own schema harness (`tests/unit/ws/_seq_support.py`)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from candleviewer.health_wiring import HealthSystemPublisher
from candleviewer.observability.health_probes import ComponentState, HealthSnapshot, ProbeResult
from tests.unit.ws._seq_support import validate


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


class Probe:
    timeout = 1.0

    def __init__(self, name: str, state: ComponentState, detail: str = "") -> None:
        self.name, self.state, self.detail = name, state, detail

    async def check(self) -> ProbeResult:
        return ProbeResult(self.state, self.detail)


class Guard:
    """What a `ClockGuard` answers to `offset_ms_or_none`: `offset`, whatever it is."""

    def __init__(self, offset: object) -> None:
        self.offset = offset

    def offset_ms_or_none(self) -> int | None:
        return cast(Any, self.offset)


def part(name: str, state: str, detail: str, last_good_at: str | None = None) -> dict[str, str]:
    """One expected `components[]` item; `last_good_at` is left out until there is one."""
    item = {"name": name, "state": state, "detail": detail}
    return item if last_good_at is None else item | {"last_good_at": last_good_at}


def envelope(body: dict[str, Any], s: int = 1) -> dict[str, Any]:
    """`body` as the `system` data frame a socket is sent."""
    return {"t": "d", "ch": "system", "s": s, "ts": 1, "e": "j", "p": body}


async def publish(snap: HealthSnapshot, guard: object = None) -> dict[str, Any]:
    """The frame a publisher with one recording sink builds for `snap`, checked as the §15.9
    `system` frame it must be."""
    publisher = HealthSystemPublisher(clock_guard=lambda: cast(Any, guard))
    sent: list[dict[str, Any]] = []
    publisher.direct_sinks.append(sent.append)
    await publisher(snap)
    (frame,) = sent
    validate(envelope(frame))
    return frame
