"""Integration: the `machine_events` sink, chain seeding and the lifespan wiring on real Postgres 16
(E50-T63 #3801), set up like production: `pg_bootstrap.sql`'s roles, the migrations as `cv_owner`,
the stores as `cv_app` (the fixtures of `test_statechart_stores_pg.py`). The scenarios of the
ticket: the chain verifies across a restart (and breaks on a changed payload), a Postgres outage
with room in the WAL loses nothing, an append that cannot be made durable fails closed, a refusal
is a fault row never a snapshot, the sink is up before the modules and drained after them, the
wiring stays unwired without keys, and a credential-shaped payload key is stored redacted. Rows
are read back and `verify_chain` runs over payloads with integers, floats, unicode, nested lists
and nulls. `testcontainers` in CI."""

from __future__ import annotations

import asyncio
import dataclasses
import socket
import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from candleviewer.admin.wiring import build_machine_event_sink
from candleviewer.app import create_app
from candleviewer.audit.redact import REDACTION_MARKER
from candleviewer.main import _lifespan
from candleviewer.observability.metrics import Metrics
from candleviewer.settings import Settings
from candleviewer.statechart import build
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.factory import restore as restore_chart
from candleviewer.statechart.persistence import (
    MachineKey,
    PersistRefusedError,
    RestoreRefusedError,
)
from candleviewer.statechart.plugins import CvAuditPlugin
from candleviewer.statechart.plugins.audit import (
    GENESIS_HASH,
    MachineEventRow,
    row_digest,
    verify_chain,
)
from candleviewer.statechart_wiring import (
    EventFramesAdapter,
    EventsAdapter,
    StatechartPersistence,
    build_statechart_persistence,
)
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.statechart_sqlalchemy import SqlAlchemyEventStore
from tests.integration.storage.test_statechart_stores_pg import (  # the stores suite's fixtures
    _REGISTRY,
    FixedKeys,
    _login,
    _sql,
    pg_dsn,
)
from tests.unit.test_main_lifespan_stop_order import _app, _Stops

pytestmark = pytest.mark.integration
__all__ = ["pg_dsn"]  # the module-scoped container fixture, used by every test here

#: What must come back from the `json` columns as written (#3857), inside event payloads.
_PROBE = {"i": 7, "f": 0.1, "e16": 1e16, "negz": -0.0, "u": "é✓😀", "nested": [[1, [2.5, None]]]}
_REPLAY_CTX = {
    "session_id": None, "symbols": ["BTCUSDT"], "range_start": 0, "range_end": 60_000_000,
    "cursor": 0, "speed": 1.0, "loop": False, "paper_account_id": None, "coverage_gaps": [],
}  # fmt: skip


def _settings(dsn: str, root: Path) -> Settings:
    return Settings(
        storage_backend="real",
        pg_dsn=SecretStr(_login(dsn, "cv_app")),
        audit_wal_path=str(root / "audit" / "audit.wal"),
        bars_state_root=str(root / "bars"),
        auth_pepper=SecretStr("test-pepper"),
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
    )


def _bundle(dsn: str, root: Path) -> StatechartPersistence:
    bundle = build_statechart_persistence(
        _settings(dsn, root), hmac_keys=FixedKeys(), metrics=Metrics("demo"), registry=_REGISTRY
    )
    assert bundle is not None
    return bundle


def _key(kind: str = "persist_min") -> MachineKey:
    return MachineKey(kind, str(uuid.uuid4()), "demo")


async def _chain(dsn: str, key: MachineKey) -> list[MachineEventRow]:
    rel = SqlAlchemyRelationalRepository(_login(dsn, "cv_app"), "statechart-read")
    try:
        return await EventsAdapter(SqlAlchemyEventStore(rel)).chain(key)
    finally:
        await rel.dispose()


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def test_the_chain_verifies_across_a_restart(pg_dsn: str, tmp_path: Path) -> None:
    """Scenario 1 (and 9): write-ahead and commit rows, a persist, a new sink over the same WAL
    directory and database, a restore through `Restorer.restore` and more commits: one chain."""
    key = _key()
    first = _bundle(pg_dsn, tmp_path)
    await first.start()
    # The plugins are duck-typed: `build` takes them as the runtime's base (as the OMS does).
    plugins: tuple[Any, ...] = await first.plugins_for(key, "order")  # the order lane writes ahead
    built = await build("persist_min", clock=default_clock(), lane="order", plugins=plugins,
                        registry=_REGISTRY)  # fmt: skip
    interp = built.interpreter
    await interp.send("PING", wait=True, n=_PROBE, token="v" * 4)
    interp.send("PING", n="drained")  # pending at the persist: journaled, replayed on restore
    await first.persister.persist(interp, key=key)
    await first.stop()

    second = _bundle(pg_dsn, tmp_path)
    restorer = second.restorer("order")
    steps: list[str] = []
    seed, plugins_of = restorer.prepare, restorer.plugins
    assert seed is not None

    async def prepare(k: MachineKey) -> None:
        steps.append("prepare")
        await seed(k)

    def recording_plugins(k: MachineKey) -> Any:
        steps.append("plugins")
        return plugins_of(k)

    restorer.prepare, restorer.plugins = prepare, recording_plugins
    await second.start()
    envelope = await second.snapshots.load(key)
    assert envelope is not None
    restored = await restorer.restore(key, envelope)
    await restored.interpreter.send("PING", wait=True, n="after")
    await restored.interpreter.stop()
    await second.stop()

    assert steps == ["prepare", "plugins"]
    rows = await _chain(pg_dsn, key)
    assert {"ahead", "commit"} <= {r.phase for r in rows} and verify_chain(rows)
    first_row = next(r for r in rows if r.payload.get("n") == _PROBE)
    assert first_row.payload["token"] == REDACTION_MARKER  # stored redacted, as hashed
    _sql(pg_dsn, "ALTER TABLE machine_events DISABLE TRIGGER USER")
    try:
        _sql(pg_dsn, "UPDATE machine_events SET payload = '{\"n\": 8}'::json WHERE row_hash = %s",
             first_row.row_hash)  # fmt: skip
    finally:
        _sql(pg_dsn, "ALTER TABLE machine_events ENABLE TRIGGER USER")
    assert not verify_chain(await _chain(pg_dsn, key))


class _Switch:
    """The sink's store: unreachable (a closed port) until `up()`, then the real one."""

    def __init__(self, dsn: str) -> None:
        down = f"postgresql+asyncpg://cv_app@127.0.0.1:{_closed_port()}/candleviewer"
        self._down_rel = SqlAlchemyRelationalRepository(down, "statechart-down")
        self._up_rel = SqlAlchemyRelationalRepository(_login(dsn, "cv_app"), "statechart-up")
        self.store = EventFramesAdapter(EventsAdapter(SqlAlchemyEventStore(self._down_rel)))
        self._up = EventFramesAdapter(EventsAdapter(SqlAlchemyEventStore(self._up_rel)))

    def up(self) -> None:
        self.store = self._up

    async def insert_batch(self, frames: Any) -> None:
        await self.store.insert_batch(frames)

    async def head(self, machine_kind: str, entity_id: str, env: str) -> str:
        return await self.store.head(machine_kind, entity_id, env)

    async def close(self) -> None:
        await self._down_rel.dispose()
        await self._up_rel.dispose()


def _rows(key: MachineKey, n: int) -> list[MachineEventRow]:
    out, prev = [], GENESIS_HASH
    for i in range(n):
        row = MachineEventRow(
            machine_kind=key.machine_kind, entity_id=key.entity_id, env=key.env,
            event_type="PING", payload={"i": i, "probe": _PROBE}, from_states=["a"],
            to_states=["a"], actions_run=["record"], fault=None,
            occurred_at=f"2026-10-21T03:00:{i:02d}+00:00", phase="commit", prev_hash=prev,
        )  # fmt: skip
        row = dataclasses.replace(row, row_hash=row_digest(row))
        out.append(row)
        prev = row.row_hash
    return out


def _stored(dsn: str, key: MachineKey) -> list[str]:
    found = _sql(dsn, "SELECT row_hash FROM machine_events WHERE entity_id = %s ORDER BY seq",
                 key.entity_id)  # fmt: skip
    return [str(r[0]) for r in found]


async def test_an_outage_with_room_in_the_wal_loses_nothing(pg_dsn: str, tmp_path: Path) -> None:
    """Scenario 2: `append` returns once fsync'd; after recovery every row lands in order, once."""
    key, switch, failed = _key(), _Switch(pg_dsn), asyncio.Event()

    def flushed(outcome: str) -> None:
        if outcome == "error":
            failed.set()

    from candleviewer.admin.wiring import MachineEventSinkMetrics

    sink = build_machine_event_sink(
        _settings(pg_dsn, tmp_path), switch, metrics=MachineEventSinkMetrics(flushed=flushed)
    )
    await sink.start()
    rows = _rows(key, 5)
    try:
        for row in rows:
            sink.append(row)
        await asyncio.wait_for(failed.wait(), 30)  # the flusher met the outage
        assert _stored(pg_dsn, key) == []
        switch.up()
    finally:
        await sink.stop()  # drains within its grace once Postgres answers
        await switch.close()
    recovered = _Switch(pg_dsn)
    recovered.up()
    again = build_machine_event_sink(_settings(pg_dsn, tmp_path), recovered)
    await again.start()  # replays what the drain did not reach, idempotently
    await again.stop()
    await recovered.close()
    assert _stored(pg_dsn, key) == [r.row_hash for r in rows]


async def test_an_append_that_cannot_be_made_durable_fails_closed(
    pg_dsn: str, tmp_path: Path
) -> None:
    """Scenario 3: the WAL at its cap while Postgres is unreachable: the plugin's append raises
    `MachineEventUnavailable`, counted in `sink_failures`; the accepted rows land later."""
    key, switch = _key(), _Switch(pg_dsn)
    from candleviewer.admin.wiring import MachineEventSinkHandle

    sink = MachineEventSinkHandle(switch, tmp_path / "small.wal", max_bytes=4096)
    await sink.start()
    plugin = CvAuditPlugin(machine_kind=key.machine_kind, entity_id=key.entity_id, env=key.env,
                           sink=sink, write_ahead=False)  # fmt: skip
    interp = type("I", (), {"_active_state_nodes": ()})()
    for i in range(40):
        plugin.on_event_received(interp, type("E", (), {"type": "PING", "data": {"i": i}})())
        plugin.on_transition(interp, (), (), type("T", (), {"event": "PING"})())
    assert plugin.sink_failures > 0 and sink.append_failure_active
    switch.up()
    await sink.stop()
    again = MachineEventSinkHandle(switch.store, tmp_path / "small.wal", max_bytes=4096)
    await again.start()
    await again.stop()
    stored = await _chain(pg_dsn, key)
    assert stored and verify_chain(stored) and len(stored) == 40 - plugin.sink_failures
    await switch.close()


async def test_a_refusal_is_a_fault_row_never_a_snapshot(pg_dsn: str, tmp_path: Path) -> None:
    """Scenario 5: a tampered snapshot row and a `_fault` context write RESTORE_QUARANTINED and
    PERSIST_REFUSED rows in the machine's chain, leave `machine_snapshots` as it was, and page."""
    key, bundle = _key(), _bundle(pg_dsn, tmp_path)
    await bundle.start()
    try:
        plugins: tuple[Any, ...] = await bundle.plugins_for(key, "platform")
        interp = (await build("persist_min", clock=default_clock(), lane="platform",
                              plugins=plugins, registry=_REGISTRY)).interpreter  # fmt: skip
        await interp.send("PING", wait=True, n=1)
        await bundle.persister.persist(interp, key=key)
        _sql(pg_dsn, "UPDATE machine_snapshots SET hmac_tag = %s WHERE entity_id = %s",
             b"\x00" * 32, key.entity_id)  # fmt: skip
        before = _sql(pg_dsn, "SELECT * FROM machine_snapshots WHERE entity_id = %s", key.entity_id)
        envelope = await bundle.snapshots.load(key)
        assert envelope is not None
        with capture_logs() as logs:
            with pytest.raises(RestoreRefusedError):
                await bundle.restorer("platform").restore(key, envelope)
            again: tuple[Any, ...] = await bundle.plugins_for(key, "platform")
            fresh = (await build("persist_min", clock=default_clock(), lane="platform",
                                 plugins=again, registry=_REGISTRY)).interpreter  # fmt: skip
            fresh.context["_fault"] = {"kind": "ActionError"}
            with pytest.raises(PersistRefusedError):
                await bundle.persister.persist(fresh, key=key)
            await fresh.stop()
        after = _sql(pg_dsn, "SELECT * FROM machine_snapshots WHERE entity_id = %s", key.entity_id)
        assert after == before
        assert sum(bool(e.get("cv_page")) for e in logs if e["event"] == "statechart_alert") >= 2
    finally:
        await bundle.stop()
    rows = await _chain(pg_dsn, key)
    faults = [(r.event_type, r.fault["kind"]) for r in rows if r.phase == "fault" and r.fault]
    assert faults == [("RESTORE_QUARANTINED", "restore_quarantined"),
                      ("PERSIST_REFUSED", "persist_refused")]  # fmt: skip
    assert verify_chain(rows)


class _ReviveAndPersist:
    """As replay does: restores one machine in `start` and persists it in `stop` (here refused,
    so the persist writes a PERSIST_REFUSED row inside `stop_all`)."""

    def __init__(self, bundle: StatechartPersistence, key: MachineKey) -> None:
        self.bundle, self.key = bundle, key
        self.interp: Any = None

    async def start(self, ctx: object) -> None:
        envelope = await self.bundle.snapshots.load(self.key)
        assert envelope is not None
        self.interp = (await restore_chart(self.bundle.restorer("control"), self.key, envelope)
                       ).interpreter  # fmt: skip

    async def stop(self, grace_s: float) -> None:
        self.interp.context["_fault"] = {"kind": "ShutdownProbe"}
        try:
            await self.bundle.persister.persist(self.interp, key=self.key)
        except PersistRefusedError:
            await self.interp.stop()


async def test_the_sink_is_up_before_the_modules_and_drained_after_them(
    pg_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario 6: `create_app` on the real backend with keys, and a module that restores one
    machine in `start` and persists it in `stop`, under the real lifespan."""
    keys, key = FixedKeys(), _key("replay")
    settings = _settings(pg_dsn, tmp_path)
    earlier = create_app(settings, hmac_keys=keys).state.statechart_persistence
    await earlier.start()
    plugins = await earlier.plugins_for(key, "control")
    interp = (await build("replay", ctx=_REPLAY_CTX, clock=default_clock(), lane="control",
                          plugins=plugins)).interpreter  # fmt: skip
    interp.send("PREPARE")  # pending at the persist: the revive replays it
    await earlier.persister.persist(interp, key=key)
    await earlier.stop()

    bundle = create_app(settings, hmac_keys=keys).state.statechart_persistence
    stops = _Stops()
    app = _app(stops)
    app.state.statechart_persistence = bundle
    module = _ReviveAndPersist(bundle, key)
    app.state.app_context.replay = module
    at_dispose: list[list[str]] = []
    real_dispose = bundle.relational.dispose

    async def dispose() -> None:
        at_dispose.append(_stored(pg_dsn, key))
        await real_dispose()

    monkeypatch.setattr(bundle.relational, "dispose", dispose)
    async with _lifespan(app):
        assert module.interp is not None and module.interp.is_running  # revived in start_all
        assert bundle.sink.head(key) is not None  # its rows went through the running sink
    rows = await _chain(pg_dsn, key)
    assert rows[-1].event_type == "PERSIST_REFUSED" and verify_chain(rows)
    assert any(r.event_type == "PREPARE" and r.phase == "commit" for r in rows)
    assert at_dispose == [[r.row_hash for r in rows]]  # every row in before the pool closed


def test_without_keys_create_app_leaves_persistence_unwired(pg_dsn: str, tmp_path: Path) -> None:
    """Scenario 8, on the real backend against a live database: no keys, no bundle."""
    app = create_app(_settings(pg_dsn, tmp_path))
    assert app.state.statechart_persistence is None
    assert app.state.app_context.replay.sessions._restorer is None
