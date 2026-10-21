"""Shared by the E17-T08 owner tests (23 §6.4): the real registry on a clock the test sets, and the
one `RegistryFeed` over it. No hub: the registry only records, and `served` reads what a `snap`
would carry, so nothing here reaches an interpreter."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from prometheus_client import REGISTRY

from candleviewer.machine_state_wiring import RegistryFeed
from candleviewer.ws.machines import MachineStateRegistry
from candleviewer.ws.topics import MACHINE_KINDS


def scope_missing_total() -> float:
    """`cv_machine_ws_scope_missing_total` over every kind: a payload recorded with no scope is a
    binding defect (§6.4). An unscoped kind has no series at all, so a book can never move it."""
    labels = ({"entity_kind": kind} for kind in MACHINE_KINDS)
    return sum(
        REGISTRY.get_sample_value("cv_machine_ws_scope_missing_total", k) or 0.0 for k in labels
    )


class Feed:
    def __init__(self) -> None:
        self.now, self._missing = 0.0, scope_missing_total()
        self.registry = MachineStateRegistry(clock=lambda: self.now)
        self.port = RegistryFeed(
            self.registry, environment="demo", now_ms=lambda: 1_789_132_262_000
        )

    def served(self, ch: str) -> dict[str, Any] | None:
        """The payload `sub` would be snapped with, or `None` when `ch` has no entry."""
        body = self.registry.build(cast(Any, SimpleNamespace(ch=ch)))
        return None if body is None else dict(body.structured)

    def expire(self) -> None:
        """60 s on: the retention of every terminal entry ends."""
        self.now += 61.0
        self.registry.sweep()

    def scope_missing(self) -> float:
        """Payloads recorded with no scope, of any kind, since this `Feed` was made."""
        return scope_missing_total() - self._missing
