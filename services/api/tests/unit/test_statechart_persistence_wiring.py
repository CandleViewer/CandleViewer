"""E50-T63: the statechart persistence bundle and its wiring in `create_app`, with no I/O.

`create_app(..., hmac_keys=)` builds `statechart_wiring.StatechartPersistence` on the real backend
when HMAC keys are injected (no provider exists yet: tests use fixed keys) and sets it on
`app.state.statechart_persistence`; without keys, or on the fake backend, it is `None` and persist,
restore and the inspector's snapshot slice stay unwired, failing closed (scenario 8). Wired, replay
sessions get the bundle's snapshot adapter, `control`-lane `Restorer` and `Persister`, and a gateway
gated by the latch-backed admission; the inspector gets the snapshot store and the keys; the two
persistence metric families are registered once, on the app's one facade."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from prometheus_client import generate_latest
from pydantic import SecretStr
from structlog.testing import capture_logs

import candleviewer.admin_wiring as admin_wiring
import candleviewer.app as app_module
from candleviewer.app import create_app
from candleviewer.settings import Settings
from candleviewer.statechart.config import LANES
from candleviewer.statechart.gateway import ALWAYS_ADMIT
from candleviewer.statechart.persistence import (
    ChainSeedError,
    InMemoryDrainJournal,
    MachineKey,
    Restorer,
    SealedSnapshot,
    open_sealed,
)
from candleviewer.statechart.plugins import CvAuditPlugin, CvErrorHooks, CvMetricsPlugin
from candleviewer.statechart.plugins.audit import GENESIS_HASH
from candleviewer.statechart_wiring import (
    LatchAdmission,
    PagerAdapter,
    StatechartPersistence,
)

KEY = MachineKey("replay", "0a000000-0000-4000-8000-000000000001", "demo")


class FixedKeys:
    """Fixed HMAC test keys, never real ones (no provider exists: a plan gap, #2701)."""

    def current(self) -> str:
        return "k1"

    def key(self, key_id: str) -> bytes:
        return {"k1": b"\x01" * 32}[key_id]


def _real(tmp_path: Path) -> Settings:
    return Settings(
        storage_backend="real",
        audit_wal_path=str(tmp_path / "audit" / "audit.wal"),
        bars_state_root=str(tmp_path / "bars"),
        auth_pepper=SecretStr("test-pepper"),
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
    )


class _Inspectors:
    """Spies on `build_statechart_inspector`: the keyword arguments of each call."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[dict[str, Any]] = []
        real = admin_wiring.build_statechart_inspector

        def spy(**kwargs: Any) -> Any:
            self.calls.append(kwargs)
            self.built = real(**kwargs)
            return self.built

        monkeypatch.setattr(app_module, "build_statechart_inspector", spy)


async def test_without_keys_the_bundle_is_none_and_persistence_stays_unwired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario 8: no bundle, so no flusher; replay's persist and restore stay unwired; the
    inspector's snapshot slice stays `unavailable`."""
    inspectors = _Inspectors(monkeypatch)
    app = create_app(_real(tmp_path))
    assert app.state.statechart_persistence is None
    sessions = app.state.app_context.replay.sessions
    assert (sessions._snapshots, sessions._restorer, sessions._persister) == (None, None, None)
    assert sessions._gateway._admission is ALWAYS_ADMIT
    [call] = inspectors.calls
    assert call.get("store") is None and call.get("keys") is None
    listing = await inspectors.built.listing(lambda *_: True)
    assert listing.snapshots.status == "unavailable"


def test_on_the_fake_backend_keys_wire_nothing(tmp_path: Path) -> None:
    app = create_app(Settings(audit_wal_path=str(tmp_path / "a.wal")), hmac_keys=FixedKeys())
    assert app.state.statechart_persistence is None


def test_with_keys_replay_the_inspector_and_the_metrics_are_wired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = FixedKeys()
    inspectors = _Inspectors(monkeypatch)
    app = create_app(_real(tmp_path), hmac_keys=keys)
    bundle = app.state.statechart_persistence
    assert isinstance(bundle, StatechartPersistence)
    sessions = app.state.app_context.replay.sessions
    assert sessions._snapshots is bundle.snapshots and sessions._persister is bundle.persister
    assert sessions._restorer is bundle.restorer("control")
    admission = sessions._gateway._admission
    assert isinstance(admission, LatchAdmission) and admission.latch is bundle.latch
    [call] = inspectors.calls
    assert call["store"] is bundle.snapshots and call["keys"] is keys
    exposition = generate_latest(app.state.app_context.metrics).decode()
    assert exposition.count("# HELP cv_machine_persist_ops_total ") == 1
    assert exposition.count("# HELP cv_machine_event_wal_pending ") == 1
    wal = bundle.sink.wal_path
    assert wal == tmp_path / "audit" / "machine_events.wal"  # beside the audit WAL


def test_one_restorer_per_lane_seeds_before_it_builds_the_plugin_triple(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_app(_real(tmp_path), hmac_keys=FixedKeys()).state.statechart_persistence
    monkeypatch.setattr(bundle.sink, "head", lambda key: GENESIS_HASH)  # as after `prepare`
    for lane in LANES:
        restorer = bundle.restorer(lane)
        assert restorer.lane == lane and restorer.prepare == bundle.sink.seed
        assert restorer.latch is bundle.latch and restorer.ops is not None
        errors, metrics, audit = restorer.plugins(KEY)
        assert isinstance(errors, CvErrorHooks) and isinstance(metrics, CvMetricsPlugin)
        assert isinstance(audit, CvAuditPlugin) and audit.write_ahead is (lane == "order")
        assert (audit.machine_kind, audit.entity_id, audit.env) == (
            KEY.machine_kind,
            KEY.entity_id,
            KEY.env,
        )
        assert audit._head is not None and audit._redactor is not None
    assert bundle.persister.ops is not None


async def test_the_registry_aware_sealer_seals_for_the_kind_of_the_key(tmp_path: Path) -> None:
    keys = FixedKeys()
    bundle = create_app(_real(tmp_path), hmac_keys=keys).state.statechart_persistence
    blob = {"version": 3, "context": {}, "cv_epoch": "e0" * 16}
    machine_hash = bundle.registry.hash("replay")
    seal = await bundle.persister.seal(blob, machine_hash, 3, KEY)
    envelope = SealedSnapshot(KEY, 3, machine_hash, blob, seal)
    chart = bundle.registry.get("replay")
    assert open_sealed(keys, chart, envelope, key=KEY, expected_machine_hash=machine_hash) == blob


class _Recorded:
    def __init__(self) -> None:
        self.steps: list[str] = []


async def test_plugins_for_seeds_then_runs_the_orphan_scan_then_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_app(_real(tmp_path), hmac_keys=FixedKeys()).state.statechart_persistence
    seen = _Recorded()

    async def seed(key: MachineKey) -> None:
        seen.steps.append(f"seed:{key.entity_id}")
        monkeypatch.setattr(bundle.sink, "head", lambda k: GENESIS_HASH)  # now held

    async def scan(self: Restorer, key: MachineKey) -> int:
        seen.steps.append(f"scan:{self.lane}")
        return 0

    monkeypatch.setattr(bundle.sink, "seed", seed)
    monkeypatch.setattr(Restorer, "page_unclaimed", scan)
    plugins = await bundle.plugins_for(KEY, "control")
    assert seen.steps == [f"seed:{KEY.entity_id}", "scan:control"] and len(plugins) == 3


async def test_a_seed_failure_in_plugins_for_is_a_chain_seed_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_app(_real(tmp_path), hmac_keys=FixedKeys()).state.statechart_persistence

    async def seed(key: MachineKey) -> None:
        raise ConnectionError("the head read failed")

    monkeypatch.setattr(bundle.sink, "seed", seed)
    with pytest.raises(ChainSeedError, match="ConnectionError"):
        await bundle.plugins_for(KEY, "control")


async def test_a_failing_orphan_scan_in_plugins_for_refuses_the_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_app(_real(tmp_path), hmac_keys=FixedKeys()).state.statechart_persistence

    async def seed(key: MachineKey) -> None:
        return None

    class Failing(InMemoryDrainJournal):
        async def list_unreplayed(self, key: MachineKey) -> Any:
            raise ConnectionError("the scan failed")

    monkeypatch.setattr(bundle.sink, "seed", seed)
    bundle.restorer("control").journal = Failing()
    with pytest.raises(ConnectionError):
        await bundle.plugins_for(KEY, "control")


async def test_the_bundle_stops_its_sink_then_disposes_its_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_app(_real(tmp_path), hmac_keys=FixedKeys()).state.statechart_persistence
    steps: list[str] = []

    async def stop() -> None:
        steps.append("sink.stop")

    async def dispose() -> None:
        steps.append("dispose")

    monkeypatch.setattr(bundle.sink, "stop", stop)
    monkeypatch.setattr(bundle.relational, "dispose", dispose)
    await bundle.stop()
    assert steps == ["sink.stop", "dispose"]


async def test_a_hanging_dispose_is_cut_by_the_stop_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from candleviewer import statechart_wiring

    bundle = create_app(_real(tmp_path), hmac_keys=FixedKeys()).state.statechart_persistence
    monkeypatch.setattr(statechart_wiring, "DISPOSE_TIMEOUT_S", 0.0)

    async def stop() -> None:
        return None

    async def dispose() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(bundle.sink, "stop", stop)
    monkeypatch.setattr(bundle.relational, "dispose", dispose)
    with capture_logs() as logs:
        await bundle.stop()
    assert [e["error"] for e in logs if e["event"] == "statechart_pool_dispose_failed"] == [
        "TimeoutError"
    ]


def test_persist_ops_counts_only_the_closed_sets(tmp_path: Path) -> None:
    app = create_app(_real(tmp_path), hmac_keys=FixedKeys())
    ops = app.state.statechart_persistence.ops
    ops.record("persist", "ok")
    ops.record("quarantine", "error")
    ops.record("vacuum", "ok")  # never a new series
    ops.record("persist", "maybe")
    samples = [
        line
        for line in generate_latest(app.state.app_context.metrics).decode().splitlines()
        if line.startswith("cv_machine_persist_ops_total{")
    ]
    assert len(samples) == 2
    assert all('operation="persist"' in s or 'operation="quarantine"' in s for s in samples)


async def test_the_pager_adapter_pages_through_the_log_pager() -> None:
    with capture_logs() as logs:
        await PagerAdapter().page(KEY, "P1", "snapshot refused: bad HMAC (CV-C53)")
    [line] = [e for e in logs if e["event"] == "statechart_alert"]
    assert line["cv_page"] is True and line["log_level"] == "critical" and line["kind"] == "replay"
    assert KEY.entity_id in line["summary"] and "bad HMAC" in line["summary"]


# --- review round 1 (E50-T63) ---------------------------------------------------------------


def test_the_bundle_repr_names_neither_the_keys_nor_the_pool(tmp_path: Path) -> None:
    """security-1: a debug line or an exception group that formats the bundle shows neither the
    HMAC key provider nor the repository that holds the DSN."""
    bundle = create_app(_real(tmp_path), hmac_keys=FixedKeys()).state.statechart_persistence
    text = repr(bundle)
    assert "keys=" not in text and "relational=" not in text and "FixedKeys" not in text
    assert "persister=" in text  # the rest of the repr is kept


async def test_a_direct_plugin_build_for_an_unseeded_key_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """security-2: the synchronous builder refuses a key whose head the sink does not hold: its
    first row would chain from the genesis and fork a stored chain. After a seed it builds. On the
    loop the app was built on, as `plugins_for` and a restore's `prepare` build: the sink serves
    that loop alone (D6, #913 L2)."""
    bundle = create_app(_real(tmp_path), hmac_keys=FixedKeys()).state.statechart_persistence
    with pytest.raises(ChainSeedError, match="unseeded") as refused:
        bundle.plugins(KEY, "control")
    assert refused.value.key == KEY
    monkeypatch.setattr(bundle.sink, "head", lambda key: GENESIS_HASH)
    assert len(bundle.plugins(KEY, "control")) == 3
