"""B14 `book` health chart driven through the factory with a BookEngine runtime
(E08-S05). The per-delta path never reaches the interpreter (INV-B14-a)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from xstate_statemachine import SimulatedClock

from candleviewer.book.models import BookPhase
from candleviewer.book.resync import BookEngine
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b14_book  # noqa: F401  (registers "book")
from tests.unit.book._builders import delta, lvl, snap


class _Sink:
    """Records the edges the engine emits and forwards them fire-and-forget
    (no receipt wait, CV-C51), exactly like `B14BookSupervisor`."""

    def __init__(self, interp: object) -> None:
        self.interp = interp
        self.sent: list[str] = []

    async def __call__(self, event: str) -> None:
        self.sent.append(event)
        await self.interp.send(event)  # type: ignore[attr-defined]


async def _ids(interp: object) -> set[str]:
    for _ in range(20):
        await asyncio.sleep(0)
    return {s.rsplit(".", 1)[-1] for s in interp.current_state_ids}  # type: ignore[attr-defined]


async def test_b14_supervised_lifecycle_and_hot_path_bypass() -> None:
    out: list[object] = []

    async def pub(ev: object) -> None:
        out.append(ev)

    async def resub() -> None: ...

    e = BookEngine(symbol="BTCUSDT", depth=200, publish=pub, resubscribe=resub, now_us=lambda: 0)
    r = await build("book", ctx={"book_key": "bk1"}, clock=SimulatedClock(), lane="platform")
    sup = _Sink(r.interpreter)
    e.health_sink = sup
    await e.start()
    assert "snapshot_pending" in await _ids(r.interpreter)
    assert e.phase is BookPhase.SNAPSHOT_PENDING
    await e.on_event(snap(10, [lvl(99, 1)], [lvl(101, 1)]))
    assert "live" in await _ids(r.interpreter)
    assert e.phase.value == BookPhase.LIVE.value
    for u in range(11, 20):
        await e.on_event(delta(u, u - 1, [lvl(99, u)]))
    assert "DELTA" not in sup.sent  # INV-B14-a
    await e.on_event(delta(30, 25))
    assert "snapshot_pending" in await _ids(r.interpreter)
    assert e.phase is BookPhase.SNAPSHOT_PENDING and e.resync_count == 1
    assert r.interpreter.context["resync_count"] == 1
    await r.interpreter.stop()


async def test_b14_without_runtime_is_inert() -> None:
    r = await build("book", ctx={"book_key": "none"}, clock=SimulatedClock(), lane="platform")
    await r.interpreter.send("SUBSCRIBE", wait=True)
    await r.interpreter.send("SNAPSHOT_TIMEOUT", wait=True)
    assert "snapshot_pending" in await _ids(r.interpreter)
    await r.interpreter.stop()


def test_book_hot_path_never_imports_statechart() -> None:
    """CV-LINT-HOTPATH fixture: book/*.py has no statechart import."""
    root = Path(__file__).resolve().parents[2] / "candleviewer" / "book"
    for f in root.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "candleviewer.statechart" not in text and "xstate_statemachine" not in text, f


async def test_b14_snapshot_round_trip_at_resync_quiescence_and_refusals() -> None:
    """Persist at the SNAPSHOT_PENDING quiescence point, restore, and refuse a
    forged / wrong-hash envelope (E08-S05 test plan)."""
    import dataclasses
    from typing import Any

    import pytest

    from candleviewer.statechart.persistence import (
        ChainTripLatch,
        InMemoryDrainJournal,
        MachineKey,
        Persister,
        Restorer,
        RestoreRefusedError,
        SealedSnapshot,
        hmac_sealer,
    )
    from candleviewer.statechart.registry import Registry

    class Keys:
        def current(self) -> str:
            return "k1"

        def key(self, key_id: str) -> bytes:
            return b"\x07" * 32

    class Repo:
        def __init__(self) -> None:
            self.rows: dict[MachineKey, SealedSnapshot] = {}

        async def write_snapshot(self, key: MachineKey, env: SealedSnapshot) -> None:
            self.rows[key] = env

    class Audit:
        def __init__(self) -> None:
            self.quarantined: list[str] = []

        async def drain_error(self, key: Any, error: str) -> None: ...
        async def persist_refused(self, key: Any, reason: str) -> None: ...
        async def quarantine(self, key: Any, env: Any, reason: str) -> None:
            self.quarantined.append(reason)

    class Pager:
        async def page(self, key: Any, severity: str, message: str) -> None: ...

    registry, keys, audit = Registry(), Keys(), Audit()
    key = MachineKey("book", "00000000-0000-0000-0000-0000000000b1", "live")
    r = await build("book", ctx={"book_key": "none"}, clock=SimulatedClock(), lane="platform")
    await r.interpreter.send("SUBSCRIBE", wait=True)
    assert "snapshot_pending" in await _ids(r.interpreter)
    repo = Repo()
    await Persister(
        repo=repo,
        journal=InMemoryDrainJournal(),
        audit=audit,
        seal=hmac_sealer(keys, registry.get("book")),
        machine_hash_of=registry.hash,
    ).persist(r.interpreter, key=key)
    env = repo.rows[key]

    def restorer() -> Restorer:
        return Restorer(
            registry=registry, keys=keys, journal=InMemoryDrainJournal(), audit=audit,
            pager=Pager(), latch=ChainTripLatch(), plugins=lambda _key: [],
            clock=SimulatedClock(), lane="platform",
        )  # fmt: skip

    res = await restorer().restore(key, env)
    try:
        assert "snapshot_pending" in await _ids(res.interpreter)  # resumes at quiescence
    finally:
        await res.interpreter.stop()
    for bad in (
        dataclasses.replace(env, machine_hash="0" * 64),
        dataclasses.replace(
            env,
            snapshot={**env.snapshot, "context": {**env.snapshot["context"], "resync_count": 9}},
        ),
    ):
        with pytest.raises(RestoreRefusedError):
            await restorer().restore(key, bad)
    assert len(audit.quarantined) == 2


async def test_b14_book_supervisor_attach_forwards_edges_and_detaches() -> None:
    """The non-hot `B14BookSupervisor` builds one chart per book and forwards
    edges without a receipt wait (CV-C51)."""
    from candleviewer.ingestion.book_supervisor import B14BookSupervisor

    s = B14BookSupervisor()
    sink = await s.attach("live:BTCUSDT:200", "BTCUSDT")
    interp = s.interpreter("live:BTCUSDT:200")
    assert interp is not None
    await sink("SUBSCRIBE")
    assert "snapshot_pending" in await _ids(interp)
    await sink("SNAPSHOT")
    assert "live" in await _ids(interp)
    s.detach("live:BTCUSDT:200")
    s.detach("missing")
    assert s.interpreter("live:BTCUSDT:200") is None
    for _ in range(20):
        await asyncio.sleep(0)
