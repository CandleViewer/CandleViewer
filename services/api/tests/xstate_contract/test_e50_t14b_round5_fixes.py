"""tests/xstate_contract/test_e50_t14b_round5_fixes.py — E50-T14b (#2204).

The four round-5 chart fixes (docs/research/xstate/33-r5-findings-register.md §6),
catalogue rows marked *Corrected 2026-10-10 (#2204, OC-0N)*:

* OC-03 B04 `completing` consumes `LEG_A_FILL`/`LEG_B_FILL` (B4.3, INV-B4-e);
* OC-05 B19 `stale_lockout` leaves only on `OPERATOR_RESOLVED` (INV-B19-b);
* OC-06 B11 `degraded` consumes `STREAM_UNHEALTHY` (INV-B11-d);
* OC-08 B14 `buffered_deltas` bounded by `max_buffered_deltas` -> resync (INV-B14-d).

Golden trace per new arm, a hypothesis property per invariant, the B14 overflow
-> resync path with its audit row, and the snapshot-migration proof per machine:
the pre-#2204 chart (rebuilt by removing the new arms, pinned to the old locked
hash) snapshots, upcasts where the context shape changed (B14 only), re-seals
and restores under the new chart. Everything runs through the factory (C-2.19).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st
from xstate_statemachine import SimulatedClock

import candleviewer.statechart.bindings.b11_recording as b11
from candleviewer.statechart import BuildResult, build
from candleviewer.statechart.bindings import b14_book
from candleviewer.statechart.bindings import b19_reconciliation as b19
from candleviewer.statechart.book_upcasters import (
    B14_FROM_HASH,
    B14_TO_HASH,
    upcast_book_v0_to_v1,
)
from candleviewer.statechart.persistence import (
    ChainTripLatch,
    InMemoryDrainJournal,
    MachineKey,
    Persister,
    Restorer,
    hmac_sealer,
)
from candleviewer.statechart.plugins.audit import CvAuditPlugin, InMemoryMachineEventSink
from candleviewer.statechart.registry import Registry
from candleviewer.statechart.upcasters import get_upcaster, has_upcaster
from tests.unit.oms.reconcile_rig import ACCOUNT, Job
from tests.xstate_contract._harness import (
    Audit,
    AuditTap,
    Charts,
    Keys,
    Pager,
    Repo,
    instrument,
    lane_of,
    park,
    settle,
    tap,
)

REG = Registry()
_GOLDEN = Path(__file__).resolve().parent / "golden"
_HYP = settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])

#: machine_hashes.lock values before #2204 (the hashes a live snapshot could carry).
OLD_HASHES = {
    "oco": "fd7edafda40fc1b25974fbd5ac49f8b274e2944de44323bdcee2e3c3f2c56850",
    "reconciliation": "b3a706bdf71d28608839e79a6da2ee2d983ba7661c9a55e76f50a935e87a22ee",
    "recording": "2b7174e42a14631ca0429a28322d046993f0456b8fb1e7254c703daef06b6dc7",
    "book": B14_FROM_HASH,
}


async def _quiesce(n: int = 16) -> None:
    for _ in range(n):
        await settle()


def _leaf(interp: Any) -> str:
    return str(next(iter(interp.current_state_ids))).split(".", 1)[1]


def _arms(spec: Any) -> list[dict[str, Any]]:
    return [spec] if isinstance(spec, dict) else list(spec)


# ----------------------------------------------------------------------------- OC-03 B04


async def _oco_at_completing(
    charts: Charts, monkeypatch: pytest.MonkeyPatch, *, overshoots: bool
) -> tuple[Any, Any]:
    rec = instrument("oco", monkeypatch, "async_def", guards={"position_overshoots": overshoots})
    res = await park("oco", REG.get("oco"), "completing", charts)
    return res.interpreter, rec


@pytest.mark.parametrize("leg", ["a", "b"])
async def test_oc03_golden_late_fill_in_completing_is_recorded_not_deferred(
    leg: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    interp, rec = await _oco_at_completing(charts, monkeypatch, overshoots=False)
    try:
        await interp.send(f"LEG_{leg.upper()}_FILL", wait=True)
        await _quiesce()
        assert _leaf(interp) == "completing"
        assert rec.actions == [f"record_fill_{leg}"]
        assert interp.deferred_count == 0 and interp.error is None
        await interp.send("CHILDREN_TERMINAL", wait=True)
        await _quiesce()
        assert _leaf(interp) == "completed"
    finally:
        await interp.stop()


@pytest.mark.parametrize("leg", ["a", "b"])
async def test_oc03_golden_overshooting_late_fill_routes_to_overshoot(
    leg: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    interp, rec = await _oco_at_completing(charts, monkeypatch, overshoots=True)
    try:
        await interp.send(f"LEG_{leg.upper()}_FILL", wait=True)
        await _quiesce()
        assert _leaf(interp) == "overshoot"  # flatten_excess hangs (instrumented)
        assert rec.actions[:3] == [
            f"record_fill_{leg}",
            "raise_warning_alert",
            "journal_double_fill",
        ]
        assert interp.deferred_count == 0
    finally:
        await interp.stop()


def test_oc03_b4_3_completing_handles_both_fills_guarded_then_unguarded() -> None:
    on = REG.get("oco")["states"]["completing"]["on"]
    assert set(on) == {"CHILDREN_TERMINAL", "LEG_A_FILL", "LEG_B_FILL"}
    for leg in "AB":
        first, last = _arms(on[f"LEG_{leg}_FILL"])
        assert first["guard"] == "position_overshoots" and first["target"] == "#oco.overshoot"
        assert "guard" not in last and "target" not in last


@_HYP
@given(fills=st.lists(st.sampled_from(["LEG_A_FILL", "LEG_B_FILL"]), min_size=1, max_size=6))
async def test_oc03_property_b4_3_no_fill_is_ever_parked_in_completing(
    charts: Charts, fills: list[str]
) -> None:
    """B4.3 / INV-B4-e: any sequence of late fills is consumed; the defer buffer
    stays empty and `CHILDREN_TERMINAL` still completes (stub guard: no overshoot)."""
    interp = (await park("oco", REG.get("oco"), "completing", charts)).interpreter
    try:
        for ev in fills:
            await interp.send(ev, wait=True)
        await _quiesce()
        assert _leaf(interp) == "completing" and interp.deferred_count == 0
        await interp.send("CHILDREN_TERMINAL", wait=True)
        await _quiesce()
        assert _leaf(interp) == "completed"
    finally:
        await interp.stop()


# ----------------------------------------------------------------------------- OC-05 B19


async def _recon_locked(charts: Charts, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    rec = instrument("reconciliation", monkeypatch, "async_def")
    res = await park("reconciliation", REG.get("reconciliation"), "stale_lockout", charts)
    await _quiesce()
    rec.actions.clear()  # drop entry actions (lock + page) of the parked state
    return res.interpreter, rec


async def test_oc05_golden_operator_resolved_clears_lockout_audited(
    charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    interp, rec = await _recon_locked(charts, monkeypatch)
    try:
        await interp.send("OPERATOR_RESOLVED", wait=True)
        await _quiesce()
        assert _leaf(interp) == "idle"
        assert rec.actions == [
            "audit_operator_resolved",
            "reset_failures",
            "unlock_account_for_new_orders",
        ]
    finally:
        await interp.stop()


async def test_oc05_golden_reconnected_while_locked_is_audited_and_keeps_lock(
    charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    interp, rec = await _recon_locked(charts, monkeypatch)
    try:
        await interp.send("RECONNECTED", wait=True)
        await _quiesce()
        assert _leaf(interp) == "stale_lockout"
        assert rec.actions == ["audit_reconnect_while_locked"]  # no re-page, no re-lock
        assert interp.deferred_count == 0
    finally:
        await interp.stop()


def test_oc05_operator_resolved_is_the_only_exit_from_stale_lockout() -> None:
    on = REG.get("reconciliation")["states"]["stale_lockout"]["on"]
    exits = {ev for ev, spec in on.items() for arm in _arms(spec) if "target" in arm}
    assert exits == {"OPERATOR_RESOLVED"}


_B19_EVENTS = ["RECONNECTED", "SWEEP_DUE", "STARTUP", "UNKNOWN_ORDER", "RETRY_DUE", "CANCEL"]


def _into(event: str, leaf: str) -> tuple[str, frozenset[str]]:
    """An `AuditTap` transition: the event and the configuration it entered."""
    return event, frozenset({"reconciliation", f"reconciliation.{leaf}"})


_RESOLVED = _into("OPERATOR_RESOLVED", "idle")


@contextmanager
def _wired() -> Iterator[Job]:
    """B19's port wired to a clean pass over the recording OMS (`tests/unit/oms/reconcile_rig`),
    and cleared however the test ends. A trigger the lock deferred, replayed once the Owner
    resolved it, then runs a pass that completes, as in production, so the job rests in `idle`;
    unwired, that pass fails closed and locks the job again (the golden case below)."""
    job = Job()
    b19.set_ports(job.phases)
    try:
        yield job
    finally:
        b19.set_ports(None)


async def _recon_locked_for(charts: Charts) -> BuildResult:
    """B19 parked in `stale_lockout` on its real bindings, for the rig's account (the build's
    `input`, as a job is built), with an `AuditTap`."""
    return await build(
        "reconciliation",
        ctx={"account_id": str(ACCOUNT)},
        clock=SimulatedClock(),
        lane=lane_of("reconciliation"),
        registry=charts.registry("reconciliation", REG.get("reconciliation"), "stale_lockout"),
        plugins=(AuditTap(),),
    )


@_HYP
@given(noise=st.lists(st.sampled_from(_B19_EVENTS), max_size=8))
@example(noise=["SWEEP_DUE"] * 8)  # eight deferred triggers, each replayed as a pass
async def test_oc05_property_inv_b19_b_only_operator_resolved_clears_lockout(
    charts: Charts, noise: list[str]
) -> None:
    """INV-B19-b: no sequence of non-operator events leaves `stale_lockout` or clears the
    account's standing; the lock and page fire once; `OPERATOR_RESOLVED` then always reaches
    `idle` and clears the standing. The port is wired, as in production, so a trigger the lock
    deferred runs a clean pass once it is replayed."""
    with _wired() as job:
        result = await _recon_locked_for(charts)
        interp = result.interpreter
        try:
            for ev in noise:
                await interp.send(ev, wait=True)
                await _quiesce(4)
                assert _leaf(interp) == "stale_lockout"
                assert job.standing.is_stale(ACCOUNT)
            await interp.send("OPERATOR_RESOLVED", wait=True)
            await _quiesce()
            assert _RESOLVED in tap(result).transitions
            assert _leaf(interp) == "idle" and not job.standing.is_stale(ACCOUNT)
            stale = [n for _, n in job.notices.published if n.reason == "oms.account_stale"]
            assert len(stale) == 1
        finally:
            await interp.stop()


async def test_oc05_golden_unwired_trigger_replayed_after_resolve_locks_again(
    charts: Charts,
) -> None:
    """Unwired, B19's fetch fails closed with its stale window spent: a trigger the lock
    deferred, replayed once `OPERATOR_RESOLVED` reached `idle`, runs a pass that locks the job
    again. INV-B19-b still holds, as the Owner's resolve did reach `idle`."""
    b19.set_ports(None)
    result = await park("reconciliation", REG.get("reconciliation"), "stale_lockout", charts)
    interp = result.interpreter
    try:
        await interp.send("SWEEP_DUE", wait=True)
        await _quiesce(4)
        assert _leaf(interp) == "stale_lockout"  # deferred, not taken
        await interp.send("OPERATOR_RESOLVED", wait=True)
        await _quiesce()
        moves = tap(result).transitions
        after = moves[moves.index(_RESOLVED) + 1 :]
        assert _into("SWEEP_DUE", "fetching") in after
        assert after[-1][1] == frozenset({"reconciliation", "reconciliation.stale_lockout"})
        assert _leaf(interp) == "stale_lockout"
    finally:
        await interp.stop()


# ----------------------------------------------------------------------------- OC-06 B11

_ADD = {"type": "REASON_ADDED", "reason": "manual", "symbol": "BTCUSDT"}


async def _b11(events: list[dict[str, Any]]) -> tuple[Any, list[str]]:
    interp = (await build("recording", clock=SimulatedClock(), lane="platform")).interpreter
    hooks: list[str] = []

    async def _hook(name: str, _ctx: object) -> None:
        hooks.append(name)

    b11.attach_hook(interp, _hook)
    for ev in events:
        await interp.send(ev, wait=True)
        await _quiesce()
    return interp, hooks


async def test_oc06_golden_second_failure_in_degraded_is_recorded_not_deferred() -> None:
    interp, hooks = await _b11(
        [
            _ADD,
            {"type": "STREAM_UNHEALTHY", "stream": "trades"},
            {"type": "STREAM_UNHEALTHY", "stream": "book"},
        ]
    )
    try:
        assert _leaf(interp) == "degraded" and interp.deferred_count == 0
        assert interp.context["streams_healthy"] == {"trades": False, "book": False}
        assert hooks.count("degraded") == 1  # internal arm: no re-entry, no second alert
        await interp.send({"type": "STREAM_HEALTHY", "stream": "trades"}, wait=True)
        await _quiesce()
        assert _leaf(interp) == "degraded"  # pre-fix: back to `recording` with book down
        await interp.send({"type": "STREAM_HEALTHY", "stream": "book"}, wait=True)
        await _quiesce()
        assert _leaf(interp) == "recording" and interp.deferred_count == 0
    finally:
        await interp.stop()


_STREAMS = ["trades", "book", "tickers"]


@_HYP
@given(
    script=st.lists(
        st.tuples(
            st.sampled_from(["STREAM_UNHEALTHY", "STREAM_HEALTHY"]), st.sampled_from(_STREAMS)
        ),
        min_size=1,
        max_size=10,
    )
)
async def test_oc06_property_inv_b11_d_degraded_iff_some_stream_unhealthy(
    script: list[tuple[str, str]],
) -> None:
    """INV-B11-d: after any interleaving of health events the chart is `degraded`
    exactly when the model says some stream is down, and nothing is deferred.
    `STREAM_HEALTHY` is only sent for a stream the model holds unhealthy (the
    recorder's producer contract; a healthy report while `recording` is a
    pre-existing deferral outside OC-06)."""
    interp, _ = await _b11([_ADD])
    model: dict[str, bool] = {}
    try:
        for ev, stream in script:
            if ev == "STREAM_HEALTHY" and model.get(stream) is not False:
                continue
            await interp.send({"type": ev, "stream": stream}, wait=True)
            await _quiesce(8)
            model[stream] = ev == "STREAM_HEALTHY"
            degraded = not all(model.values())
            assert _leaf(interp) == ("degraded" if degraded else "recording")
            assert interp.deferred_count == 0
            if degraded:
                assert interp.context["streams_healthy"] == model
    finally:
        await interp.stop()


# ----------------------------------------------------------------------------- OC-08 B14


async def _appending_buffer_delta(_i: Any, context: dict[str, Any], *_a: object) -> None:
    """Test-local `buffer_delta` (production keeps the buffer in `BookEngine`, INV-B14-a)."""
    context["buffered_deltas"] = [*context["buffered_deltas"], len(context["buffered_deltas"])]


_BOOK_REGS: dict[int, Registry] = {}


def _book_registry(bound: int, charts: Charts) -> Registry:
    """`book` with `max_buffered_deltas = bound`, under the suite's session tmp dir."""
    if bound not in _BOOK_REGS:
        chart = copy.deepcopy(REG.get("book"))
        chart["context"]["max_buffered_deltas"] = bound
        d = charts._root / f"book__bound{bound}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "book.machine.json").write_text(json.dumps(chart), "utf-8")
        _BOOK_REGS[bound] = Registry(machines_dir=d)
    return _BOOK_REGS[bound]


async def _book(
    bound: int, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, InMemoryMachineEventSink]:
    monkeypatch.setitem(b14_book.ACTIONS, "buffer_delta", _appending_buffer_delta)
    sink = InMemoryMachineEventSink()
    audit = CvAuditPlugin(
        machine_kind="book", entity_id="BTCUSDT", env="demo", sink=sink, write_ahead=False
    )
    reg = _book_registry(bound, charts)
    res = await build(
        "book", clock=SimulatedClock(), lane="platform", registry=reg, plugins=(cast(Any, audit),)
    )
    await res.interpreter.send("SUBSCRIBE", wait=True)
    await _quiesce()
    return res.interpreter, sink


def _overflow_rows(sink: InMemoryMachineEventSink) -> list[Any]:
    return [r for r in sink.rows if "audit_buffer_overflow" in r.actions_run]


async def test_oc08_golden_full_buffer_resyncs_with_audit_record(
    charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    interp, sink = await _book(3, charts, monkeypatch)
    try:
        for _ in range(3):
            await interp.send("DELTA", wait=True)
        await _quiesce()
        assert interp.context["buffered_deltas"] == [0, 1, 2]
        await interp.send("DELTA", wait=True)  # the 4th delta never grows the buffer
        await _quiesce()
        assert _leaf(interp) == "snapshot_pending"  # desynced -> resync (C-2.5)
        assert interp.context["buffered_deltas"] == []  # clear_buffer on re-entry
        assert interp.context["resync_count"] == 1
        (row,) = _overflow_rows(sink)
        assert row.event_type == "DELTA" and row.phase == "commit"
        assert "book.desynced" in row.to_states  # then `always` -> snapshot_pending
    finally:
        await interp.stop()


async def test_oc08_golden_engine_buffer_overflow_edge_resyncs_with_audit_record(
    charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    interp, sink = await _book(1000, charts, monkeypatch)
    try:
        await interp.send("BUFFER_OVERFLOW", wait=True)
        await _quiesce()
        assert _leaf(interp) == "snapshot_pending" and interp.context["resync_count"] == 1
        (row,) = _overflow_rows(sink)
        assert row.event_type == "BUFFER_OVERFLOW"
    finally:
        await interp.stop()


@_HYP
@given(bound=st.integers(min_value=1, max_value=6), n=st.integers(min_value=0, max_value=20))
async def test_oc08_property_inv_b14_d_buffer_never_exceeds_bound(
    charts: Charts, bound: int, n: int
) -> None:
    """INV-B14-d: for any bound and any number of deltas the buffer stays
    `<= max_buffered_deltas`, and each overflow is one audited resync."""
    with pytest.MonkeyPatch.context() as mp:
        interp, sink = await _book(bound, charts, mp)
        try:
            for _ in range(n):
                await interp.send("DELTA", wait=True)
                await _quiesce(4)
                assert len(interp.context["buffered_deltas"]) <= bound
                assert _leaf(interp) == "snapshot_pending"
            assert interp.context["resync_count"] == n // (bound + 1)
            assert len(_overflow_rows(sink)) == n // (bound + 1)
        finally:
            await interp.stop()


@given(
    size=st.integers(min_value=0, max_value=50),
    bound=st.one_of(st.integers(min_value=1, max_value=50), st.none(), st.just("x")),
)
def test_oc08_property_delta_buffer_full_is_total_and_fail_safe(size: int, bound: Any) -> None:
    ctx: dict[str, Any] = {"buffered_deltas": list(range(size))}
    if bound is not None:
        ctx["max_buffered_deltas"] = bound
    got = b14_book.delta_buffer_full(ctx, None)
    if bound == "x":
        assert got is True  # broken bound => overflow => resync, never unbounded
    else:
        limit = b14_book.DEFAULT_MAX_BUFFERED_DELTAS if bound is None else bound
        assert got is (size >= limit)


async def test_oc08_chaos_book_engine_overflow_reaches_chart_as_buffer_overflow() -> None:
    """Chaos: the engine's buffer overflows while a snapshot is pending; the edge
    reaches the B14 chart as `BUFFER_OVERFLOW` and resyncs it (audited)."""
    from candleviewer.book.resync import BUFFER_BOUND, BookEngine
    from tests.unit.book._builders import delta

    assert (
        BUFFER_BOUND
        == b14_book.DEFAULT_MAX_BUFFERED_DELTAS
        == REG.get("book")["context"]["max_buffered_deltas"]
    )
    sink = InMemoryMachineEventSink()
    audit = CvAuditPlugin(
        machine_kind="book", entity_id="BTCUSDT", env="demo", sink=sink, write_ahead=False
    )
    interp = (
        await build("book", clock=SimulatedClock(), lane="platform", plugins=(cast(Any, audit),))
    ).interpreter
    edges: list[str] = []

    async def health(ev: str) -> None:
        edges.append(ev)
        await interp.send(ev)

    async def pub(_ev: object) -> None: ...

    async def resub() -> None: ...

    e = BookEngine(symbol="BTCUSDT", depth=50, publish=pub, resubscribe=resub, now_us=lambda: 0)
    e.health_sink = health
    try:
        await e.start()
        for i in range(BUFFER_BOUND + 1):
            await e.on_event(delta(i + 2, i + 1))
        await _quiesce()
        assert edges == ["SUBSCRIBE", "BUFFER_OVERFLOW"]
        assert "DELTA" not in edges  # INV-B14-a: the hot path never reaches the chart
        assert _leaf(interp) == "snapshot_pending" and interp.context["resync_count"] == 1
        assert [r.event_type for r in _overflow_rows(sink)] == ["BUFFER_OVERFLOW"]
    finally:
        await interp.stop()


# ----------------------------------------------------------------------------- snapshot migration


def _legacy_chart(machine: str) -> dict[str, Any]:
    """The pre-#2204 chart: the new arms removed, no `version` key."""
    old = copy.deepcopy(REG.get(machine))
    old.pop("version")
    s = old["states"]
    if machine == "oco":
        for ev in ("LEG_A_FILL", "LEG_B_FILL"):
            del s["completing"]["on"][ev]
    elif machine == "reconciliation":
        s["stale_lockout"]["on"] = {
            "RECONNECTED": {"target": "#reconciliation.fetching", "actions": ["reset_failures"]}
        }
    elif machine == "recording":
        del s["degraded"]["on"]["STREAM_UNHEALTHY"]
    else:
        del old["context"]["max_buffered_deltas"]
        on = s["snapshot_pending"]["on"]
        on["DELTA"] = {"actions": ["buffer_delta"]}
        del on["BUFFER_OVERFLOW"]
    return old


@pytest.mark.parametrize("machine", sorted(OLD_HASHES))
def test_migration_legacy_chart_is_exactly_the_old_locked_hash(machine: str) -> None:
    """The diff is exactly the catalogued arms (+ `version`, + B14 bound)."""
    from candleviewer.statechart.registry import machine_hash

    assert machine_hash(_legacy_chart(machine)) == OLD_HASHES[machine]
    assert REG.get(machine)["version"] == 1


@pytest.mark.parametrize("machine", sorted(OLD_HASHES))
def test_migration_context_shape_changes_only_for_b14(machine: str) -> None:
    """No upcaster for B04/B11/B19 (context shape unchanged); B14 has one."""
    old_keys = set(_legacy_chart(machine)["context"])
    new_keys = set(REG.get(machine)["context"])
    if machine == "book":
        assert new_keys - old_keys == {"max_buffered_deltas"}
        assert has_upcaster("book", B14_FROM_HASH, B14_TO_HASH)
        assert REG.hash("book") == B14_TO_HASH
    else:
        assert new_keys == old_keys


def test_migration_b14_upcaster_matches_golden_fixture() -> None:
    before = json.loads((_GOLDEN / "book.v0_to_v1.before.json").read_text("utf-8"))
    after = json.loads((_GOLDEN / "book.v0_to_v1.after.json").read_text("utf-8"))
    got = get_upcaster("book", B14_FROM_HASH)(before)
    for d in (got, after):
        d.pop("_comment")
    assert got == after
    assert "max_buffered_deltas" not in before  # pure: input untouched
    assert upcast_book_v0_to_v1({"max_buffered_deltas": 5}) == {"max_buffered_deltas": 5}


@pytest.mark.parametrize("machine", sorted(OLD_HASHES))
async def test_migration_pre_2204_snapshot_is_refused_loudly_never_silently_restored(
    machine: str, charts: Charts, tmp_path: Path
) -> None:
    """A snapshot sealed at the old hash is quarantined + paged P1 on restore
    (MUST-12), so a pre-fix machine can never resume on the new chart unnoticed;
    the owner re-drives it from the triggering event (INV-B19-e pattern)."""
    old = _legacy_chart(machine)
    d = tmp_path / machine
    d.mkdir()
    (d / f"{machine}.machine.json").write_text(json.dumps(old), "utf-8")
    old_reg = Registry(machines_dir=d)
    keys, audit, pager = Keys(), Audit(), Pager()
    key = MachineKey(machine, "00000000-0000-0000-0000-000000002204", "demo")
    res = await build(machine, clock=SimulatedClock(), lane=lane_of(machine), registry=old_reg)
    repo = Repo()
    await Persister(
        repo=repo,
        journal=InMemoryDrainJournal(),
        audit=audit,
        seal=hmac_sealer(keys, old),
        machine_hash_of=old_reg.hash,
        pager=pager,
    ).persist(res.interpreter, key=key)
    env = repo.rows[key]
    assert env.machine_hash == OLD_HASHES[machine]
    restorer = Restorer(
        registry=REG, keys=keys, journal=InMemoryDrainJournal(), audit=audit, pager=pager,
        latch=ChainTripLatch(), plugins=lambda _key: [], clock=SimulatedClock(),
        lane=lane_of(machine),
    )  # fmt: skip
    from candleviewer.statechart.persistence import RestoreRefusedError

    with pytest.raises(RestoreRefusedError):
        await restorer.restore(key, env)
    assert len(audit.quarantined) == 1 and pager.pages == ["P1"]
