"""tests/xstate_contract/chaos/_chaos.py — chaos rig over the library runtime (E50-Q01).

Four fault families (29-statechart-adoption-plan.md §1.7, E50-Q01 scope):

* **kill/restart** — a running machine is killed at a quiescence point with
  events still in its inbox: drained to the journal, sealed, stopped, then
  restored through `Restorer` (the only production path) and replayed once;
* **clock skew** — the injected `SimulatedClock` jumps far forward (every
  armed timer fires at once) and refuses to move backwards;
* **inbox overflow** — the lane inbox is flooded to its `CV_INBOX_BOUND`;
  the next send is refused loudly (`QueueOverflowError`), never dropped;
* **restore mid-invoke** — a machine parked in a state whose service is in
  flight is killed and restored; the restored machine is the same
  configuration and keeps accepting events.

Every machine is built through `cv.statechart.factory.build()` only (C-2.19).
No wall-clock sleeps, no network, files only under pytest tmp dirs (C-13.7).
"""

from __future__ import annotations

import dataclasses
from typing import Any

from xstate_statemachine import Interpreter, QueueOverflowError, SimulatedClock

from candleviewer.statechart import build
from candleviewer.statechart.config import CV_INBOX_BOUND
from candleviewer.statechart.persistence import (
    ChainTripLatch,
    InMemoryDrainJournal,
    MachineKey,
    Persister,
    Restorer,
    hmac_sealer,
)
from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import (
    Audit,
    AuditTap,
    Charts,
    Keys,
    Pager,
    Repo,
    all_events,
    lane_of,
    settle,
    walk,
)

REG = Registry()
_ENTITY = "00000000-0000-0000-0000-0000000e50c1"


def known_states(machine: str) -> set[str]:
    """Every absolute state id the chart declares (plus the root)."""
    chart = REG.get(machine)
    return {machine} | {f"{machine}.{p}" for p, _n in walk(chart)}


def assert_sound(machine: str, interp: Interpreter[Any]) -> None:
    """Post-chaos soundness: running, no fault, configuration inside the chart."""
    assert interp.error is None, f"{machine}: {interp.error!r}"
    assert interp.chain_trips == 0, machine
    ids = set(interp.current_state_ids)
    assert ids, machine
    assert ids <= known_states(machine), f"{machine}: {sorted(ids - known_states(machine))}"


@dataclasses.dataclass
class Live:
    """One running machine plus its injected clock and fault sinks."""

    machine: str
    source: str
    registry: Registry
    clock: SimulatedClock
    interp: Interpreter[Any]
    journal: InMemoryDrainJournal = dataclasses.field(default_factory=InMemoryDrainJournal)
    audit: Audit = dataclasses.field(default_factory=Audit)
    pager: Pager = dataclasses.field(default_factory=Pager)
    latch: ChainTripLatch = dataclasses.field(default_factory=ChainTripLatch)
    keys: Keys = dataclasses.field(default_factory=Keys)

    @property
    def key(self) -> MachineKey:
        return MachineKey(self.machine, _ENTITY, "demo")


async def start(machine: str, source: str, charts: Charts) -> Live:
    """Build *machine* parked at *source* with an injected `SimulatedClock`."""
    chart = REG.get(machine)
    reg = charts.registry(machine, chart, source)
    clock = SimulatedClock()
    res = await build(
        machine, clock=clock, lane=lane_of(machine), registry=reg, plugins=(AuditTap(),)
    )
    return Live(machine, source, reg, clock, res.interpreter)


def probe_event(machine: str) -> str:
    """A declared event (strict mode refuses undeclared ones at the call site)."""
    return sorted(all_events(REG.get(machine)))[0]


async def kill(live: Live) -> Any:
    """Kill at quiescence: drain inbox -> journal, seal, stop (29 §1.3)."""
    repo = Repo()
    await Persister(
        repo=repo,
        journal=live.journal,
        audit=live.audit,
        seal=hmac_sealer(live.keys, live.registry.get(live.machine)),
        machine_hash_of=live.registry.hash,
        pager=live.pager,
    ).persist(live.interp, key=live.key)
    assert not live.interp.is_running, f"{live.machine}: kill left it running"
    return repo.rows[live.key]


async def restart(live: Live, envelope: Any) -> Live:
    """Restore through the production `Restorer` on a fresh clock."""
    clock = SimulatedClock()
    res = await Restorer(
        registry=live.registry,
        keys=live.keys,
        journal=live.journal,
        audit=live.audit,
        pager=live.pager,
        latch=live.latch,
        plugins=lambda _key: [AuditTap()],
        clock=clock,
        lane=lane_of(live.machine),
    ).restore(live.key, envelope)
    await settle()
    return dataclasses.replace(live, clock=clock, interp=res.interpreter)


async def skew(live: Live, ms: float) -> None:
    """Jump the injected clock forward by *ms* (fires every due timer)."""
    pending = live.clock.set(live.clock.now() * 1000.0 + ms)
    if pending is not None:
        await pending
    await settle()


def flood(live: Live) -> tuple[int, bool]:
    """Fill the inbox without yielding; return `(accepted, refused_loudly)`."""
    bound = CV_INBOX_BOUND[lane_of(live.machine)]
    ev = probe_event(live.machine)
    accepted = 0
    for _ in range(bound):
        live.interp.send(ev)
        accepted += 1
    try:
        live.interp.send(ev)
    except QueueOverflowError:
        return accepted, True
    return accepted, False


# ---------------------------------------------------------------------------
# §Bn.7 chaos ledger: every catalogue invariant -> the fault family that
# stresses it on its machine (derived from the invariant text, reviewable).
# ---------------------------------------------------------------------------

FAMILIES = ("kill_restart", "clock_skew", "inbox_overflow", "restore_mid_invoke")

_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("restore_mid_invoke", ("invoke", "service", "in flight", "in-flight", "restore", "crash")),
    ("clock_skew", ("timer", "deadline", "after", "clock", "expire", "backoff", "cooldown", "ttl")),
    ("inbox_overflow", ("queue", "inbox", "overflow", "burst", "drop", "defer")),
)


def chart_for_number(number: int) -> str | None:
    """Machine key of the committed `BNN.<id>.machine.json`, or None."""
    from tests.xstate_contract.conftest import _MACHINES

    hits = sorted(_MACHINES.glob(f"B{number:02d}.*.machine.json"))
    return hits[0].name.split(".")[1] if hits else None


def invoke_states(machine: str) -> list[str]:
    """Stable leaves whose own node (or an ancestor) has an `invoke`."""
    from tests.xstate_contract._harness import node_at, stable_states

    chart = REG.get(machine)
    out: list[str] = []
    for leaf in stable_states(chart):
        parts = leaf.split(".")
        if any("invoke" in node_at(chart, ".".join(parts[: i + 1])) for i in range(len(parts))):
            out.append(leaf)
    return out


def family_for(text: str, machine: str) -> str:
    low = text.lower()
    for family, words in _KEYWORDS:
        if any(w in low for w in words):
            if family == "restore_mid_invoke" and not invoke_states(machine):
                return "kill_restart"
            return family
    return "kill_restart"


def catalogue_rows() -> list[tuple[str, int, str]]:
    """`(INV-Bn-x, n, text)` for every invariant row in the catalogue."""
    import re

    from tests.xstate_contract.membership import _CATALOGUE

    row = re.compile(r"^\|\s*\*\*(INV-B(\d+)-[a-z0-9]+)\*\*\s*\|(.*)\|\s*$")
    out: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    for line in _CATALOGUE.read_text(encoding="utf-8").splitlines():
        m = row.match(line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append((m.group(1), int(m.group(2)), m.group(3).strip()))
    return out
