"""E17-T08 PR 2b: `RegistryFeed`, the composition-root port of the machines feed (23 §6.4), over
the real `MachineStateRegistry` on a fake clock. No runtime import here (CV-LINT-IMPORT): a built
machine reaching the registry is proved by 2c's scenario tests (cut here for the C-4.8 cap)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from candleviewer.machine_state_wiring import RegistryFeed
from candleviewer.statechart.plugins import FeedBinding
from candleviewer.ws.machines import MachineStateRegistry
from candleviewer.ws.topics import EntityScope

A, U = UUID(int=0xA), UUID(int=0x1)
OID = "0a000000-0000-4000-8000-000000000001"
ON_A = EntityScope(frozenset({A}))


def _payload(chart: str, tags: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"machine_kind": chart, "state": "idle", "tags": list(tags), "degraded": False,
            "machine_hash": "0" * 64, "environment": "demo", "updated_at_ms": 1}  # fmt: skip


def _feed(registry: MachineStateRegistry) -> RegistryFeed:
    return RegistryFeed(registry, environment="demo", now_ms=lambda: 1)


@pytest.mark.parametrize(
    ("binding", "ch", "scope"),
    [
        (FeedBinding("oco", OID, frozenset({A})), f"machines.algo:{OID}.state", ON_A),
        (FeedBinding("session", OID, user=U), f"machines.session:{OID}.state", EntityScope(user=U)),
        (FeedBinding("kill_switch"), "machines.kill_switch.state", EntityScope()),
        (FeedBinding("book", "BTCUSDT"), "machines.book:BTCUSDT.state", EntityScope()),
    ],
)
def test_bind_names_the_entity_kind_and_binds_the_scope(
    binding: FeedBinding, ch: str, scope: EntityScope
) -> None:
    registry = MachineStateRegistry()
    _feed(registry).bind(binding).publish(_payload(binding.machine_kind), last=False)
    assert registry.scope(ch) == scope
    assert registry._entries[ch].payload == _payload(binding.machine_kind)


@pytest.mark.parametrize(
    ("binding", "message"),
    [(FeedBinding(c), "has no machines") for c in ("position_protection", "rule_instance")]
    + [(FeedBinding(c), "has no machines") for c in ("ws_conn", "paper_account", "nope")]  # W9
    + [(FeedBinding("order", OID.upper()), "machine entity")],
)
def test_a_chart_with_no_public_entity_or_a_bad_id_is_refused_at_bind(
    binding: FeedBinding, message: str
) -> None:
    with pytest.raises(ValueError, match=message):  # B8, B9, B13, B15 have no public id
        _feed(MachineStateRegistry()).bind(binding)


def test_a_terminal_entry_outlives_its_machine_and_an_older_stop_spares_a_newer_one() -> None:
    now = [0.0]
    registry, ch = MachineStateRegistry(clock=lambda: now[0]), f"machines.order:{OID}.state"
    binding = FeedBinding("order", OID, frozenset({A}))
    older, newer = _feed(registry).bind(binding), _feed(registry).bind(binding)
    older.publish(_payload("order"), last=False)
    newer.publish(_payload("order"), last=False)
    older.remove()  # a stopped machine's late `remove` leaves the entry a newer machine took over
    assert registry.scope(ch) is not None
    newer.remove()  # its own live entry goes with it
    assert registry.scope(ch) is None
    newer.publish(_payload("order", ("terminal",)), last=True)
    newer.remove()  # the registry keeps a terminal entry: retention ends it
    assert registry.scope(ch) is not None
    now[0] = 61.0
    assert registry.sweep() == 1 and registry.scope(ch) is None
