"""Unit (E16-T06): `RetentionManager.preview` / `run` / `run_nightly` against the Gherkin.

Default prunes on schedule; pinned never deleted; dry run deletes nothing (volume unchanged)
and audits; real run deletes only plan items with a write-ahead `data.deleted`; leased skip
then next-pass delete; unarchived hot day never dropped; interrupted run resumes exactly once;
shortening retention previews the exact bytes and range first.
"""

from __future__ import annotations

import pytest

from candleviewer.recorder.retention import (
    US_PER_DAY,
    CheckpointCorrupt,
    MemoryCheckpoint,
    PolicyRow,
    PruneScope,
    RetentionBusy,
)
from tests.unit.recorder._retention_fakes import NOW_US, Crash, T, World, day, manager


def _world() -> World:
    w = World()
    w.policies[(None, "trades")] = PolicyRow(None, "trades", 7, 30)
    return w


async def test_default_retention_prunes_old_trades_reports_bytes_and_next_run() -> None:
    w = _world()
    old = w.add_cold("BTCUSDT", T, 40)
    young = w.add_cold("BTCUSDT", T, 10)
    report = await manager(w).run_nightly()
    assert [i.key for i in report.deleted] == [old]
    assert young in w.cold[("BTCUSDT", T)] and old not in w.cold[("BTCUSDT", T)]
    assert report.freed_bytes == 100_000
    assert report.next_run_us == NOW_US + 24 * 3600 * 1_000_000


async def test_pinned_symbol_is_never_deleted_and_listed_protected_pinned() -> None:
    w = _world()
    w.pinned = {"ETHUSDT"}
    w.policies[("ETHUSDT", "trades")] = PolicyRow("ETHUSDT", "trades", 1, 1)
    w.add_cold("ETHUSDT", T, 400)
    w.add_hot(T, 300, {"ETHUSDT": 5})
    w.archived[("ETHUSDT", T)] = NOW_US
    plan = await manager(w).preview()
    assert plan.items == ()
    assert {p.reason for p in plan.protected} == {"pinned"}
    report = await manager(w).run_nightly()
    assert report.deleted == [] and w.deletes == []


async def test_applies_to_pinned_policy_never_unlocks_a_policy_run() -> None:
    w = _world()
    w.pinned = {"ETHUSDT"}
    w.policies[("ETHUSDT", "trades")] = PolicyRow("ETHUSDT", "trades", 1, 1, applies_to_pinned=True)
    w.add_cold("ETHUSDT", T, 400)
    await manager(w).run_nightly()
    assert w.deletes == []


async def test_dry_run_reports_exact_plan_deletes_nothing_and_audits_run() -> None:
    w = _world()
    w.add_cold("BTCUSDT", T, 40, rows=7)
    w.add_cold("BTCUSDT", T, 35, rows=3)
    before = w.volume()
    m = manager(w)
    plan = await m.preview()
    (s,) = plan.summary()
    assert (s.symbol, s.stream, s.rows, s.bytes) == ("BTCUSDT", "trades", 10, 10_000)
    assert (s.from_us, s.to_us) == (day(40), day(35) + US_PER_DAY)
    report = await m.run(plan, dry_run=True)
    assert w.volume() == before and w.deletes == [] and report.deleted == []
    assert [a for a, _ in w.audit] == ["retention.run"]
    assert w.audit[0][1]["dry_run"] == 1 and w.audit[0][1]["planned_bytes"] == 10_000


async def test_real_run_deletes_only_plan_items_with_write_ahead_data_deleted() -> None:
    w = _world()
    planned = w.add_cold("BTCUSDT", T, 40)
    m = manager(w)
    plan = await m.preview()
    late = w.add_cold("BTCUSDT", T, 50)  # appears after the plan: must survive
    seen: list[str] = []
    orig = m._cold.delete

    async def spy(symbol: str, stream: object, key: str) -> bool:
        seen.append(str(w.data_deleted()[-1]["partition"]))  # audit already written
        return await orig(symbol, stream, key)  # type: ignore[arg-type]  # fake passthrough

    m._cold.delete = spy  # type: ignore[method-assign]  # test spy on the fake port
    report = await m.run(plan, dry_run=False)
    assert [i.key for i in report.deleted] == [planned] and seen == [planned]
    assert late in w.cold[("BTCUSDT", T)]
    (rec,) = w.data_deleted()
    assert rec["actor"] == "system:retention" and rec["rows"] == 100
    assert (rec["range_start_us"], rec["range_end_us"]) == (day(40), day(40) + US_PER_DAY)


async def test_leased_partition_skipped_logged_then_deleted_next_pass() -> None:
    w = _world()
    key = w.add_cold("BTCUSDT", T, 40)
    w.leases["BTCUSDT"] = [(day(41), day(39))]
    plan = await manager(w).preview()
    assert [(p.item.key, p.reason) for p in plan.protected] == [(key, "leased")]
    assert (await manager(w).run_nightly()).deleted == []
    w.leases.clear()
    assert [i.key for i in (await manager(w).run_nightly()).deleted] == [key]


async def test_lease_taken_after_plan_is_honoured_at_delete_time() -> None:
    w = _world()
    w.add_cold("BTCUSDT", T, 40)
    m = manager(w)
    plan = await m.preview()
    w.leases["BTCUSDT"] = [(day(41), day(39))]
    report = await m.run(plan, dry_run=False)
    assert report.deleted == [] and [p.reason for p in report.skipped] == ["leased"]
    assert w.data_deleted() == []


async def test_unarchived_hot_day_is_never_dropped_and_alerts() -> None:
    w = _world()
    w.add_hot(T, 10, {"BTCUSDT": 5})
    w.archived[("BTCUSDT", T)] = day(12)  # watermark short of the day
    plan = await manager(w).preview()
    assert [p.reason for p in plan.protected] == ["not_archived"] and plan.items == ()
    assert w.events == []  # a preview never alerts
    report = await manager(w).run_nightly()
    assert report.deleted == [] and w.deletes == []
    assert [p.reason for p in report.protected] == ["not_archived"]  # held while planning
    assert w.events == [("WARNING", "retention.not_archived")]


async def test_archived_hot_day_past_hot_window_is_dropped() -> None:
    w = _world()
    w.add_hot(T, 10, {"BTCUSDT": 5, "ETHUSDT": 2})
    w.add_hot(T, 3, {"BTCUSDT": 5})  # inside 7 d hot window: not a candidate
    w.archived[("BTCUSDT", T)] = w.archived[("ETHUSDT", T)] = day(9)
    report = await manager(w).run_nightly()
    assert [i.start_us for i in report.deleted] == [day(10)]
    assert day(3) in w.hot[T]
    assert w.data_deleted()[0]["symbol"] == "BTCUSDT,ETHUSDT"


async def test_watermark_regression_after_plan_blocks_drop_and_alerts() -> None:
    w = _world()
    w.add_hot(T, 10, {"BTCUSDT": 5})
    w.archived[("BTCUSDT", T)] = day(9)
    m = manager(w)
    plan = await m.preview()
    w.archived[("BTCUSDT", T)] = 0
    report = await m.run(plan, dry_run=False)
    assert report.deleted == [] and ("WARNING", "retention.not_archived") in w.events


async def test_hot_day_shared_with_pinned_symbol_is_protected() -> None:
    w = _world()
    w.pinned = {"ETHUSDT"}
    w.add_hot(T, 10, {"BTCUSDT": 5, "ETHUSDT": 2})
    w.archived[("BTCUSDT", T)] = w.archived[("ETHUSDT", T)] = NOW_US
    plan = await manager(w).preview()
    assert [p.reason for p in plan.protected] == ["pinned"]


async def test_hot_day_inside_one_symbols_longer_window_is_protected() -> None:
    w = _world()
    w.policies[("ETHUSDT", "trades")] = PolicyRow("ETHUSDT", "trades", 30, 60)
    w.add_hot(T, 10, {"BTCUSDT": 5, "ETHUSDT": 2})
    w.archived[("BTCUSDT", T)] = w.archived[("ETHUSDT", T)] = NOW_US
    plan = await manager(w).preview()
    assert [(p.reason, p.info) for p in plan.protected] == [("hot_window", "ETHUSDT")]


async def test_interrupted_run_resumes_without_rescanning_completed_symbols() -> None:
    w = _world()
    keys = [w.add_cold(f"S{i:02d}USDT", T, 40) for i in range(10)]
    ckpt = MemoryCheckpoint()
    w.crash_on_delete = 4  # killed during the 4th delete, after 3 symbols completed
    with pytest.raises(Crash):
        await manager(w, ckpt).run_nightly()
    assert ckpt.doc is not None and len(ckpt.doc["done"]) == 3  # type: ignore[arg-type]  # list
    w.deletes.clear()
    report = await manager(w, ckpt).run_nightly()
    assert report.resumed
    assert w.deletes == [f"cold:{k}" for k in keys[3:]]  # completed symbols not re-touched
    assert all(not parts for parts in w.cold.values())
    ids = [d["deletion_id"] for d in w.data_deleted()]
    assert len(ids) == len(set(ids)) == 10  # exactly one write-ahead record per deletion
    assert ckpt.doc is None


async def test_failed_delete_keeps_pending_and_next_pass_finishes_without_reaudit() -> None:
    w = _world()
    w.add_cold("BTCUSDT", T, 40)
    ckpt = MemoryCheckpoint()
    m = manager(w, ckpt)

    async def boom(symbol: str, stream: object, key: str) -> bool:
        raise OSError("disk")

    real = m._cold.delete
    m._cold.delete = boom  # type: ignore[method-assign]  # inject a failing port
    first = await m.run_nightly()
    assert first.failed and ckpt.doc is not None and ckpt.doc["pending"]
    m._cold.delete = real  # type: ignore[method-assign]
    second = await m.run_nightly()
    assert len(second.deleted) == 1 and len(w.data_deleted()) == 1


async def test_corrupt_checkpoint_fails_closed() -> None:
    w = _world()
    w.add_cold("BTCUSDT", T, 40)
    ckpt = MemoryCheckpoint()
    ckpt.doc = {"version": 1, "plan_id": "x", "items": [], "created_us": 0, "done": []}
    with pytest.raises(CheckpointCorrupt):
        await manager(w, ckpt).run_nightly()
    assert w.deletes == []


async def test_audit_failure_before_delete_deletes_nothing() -> None:
    w = _world()
    w.add_cold("BTCUSDT", T, 40)
    m = manager(w)
    plan = await m.preview()
    w.fail_audit = True
    with pytest.raises(RuntimeError):
        await m.run(plan, dry_run=False)
    assert w.deletes == []


async def test_locked_volume_skips_nightly_and_refuses_run() -> None:
    w = _world()
    w.add_cold("BTCUSDT", T, 40)
    w.lock_free = False
    m = manager(w)
    assert (await m.run_nightly()).deleted == []
    with pytest.raises(RetentionBusy):
        await m.run(await m.preview(), dry_run=False)
    assert w.deletes == []


async def test_shortening_retention_preview_states_exact_bytes_and_range() -> None:
    w = _world()
    for n in (5, 8, 20):
        w.add_cold("BTCUSDT", T, n)
    what_if = {(None, "trades"): PolicyRow(None, "trades", 3, 7)}
    current = await manager(w).preview()
    shorter = await manager(w).preview(PruneScope(policies=what_if))
    assert current.items == ()
    (s,) = shorter.summary()
    assert (s.from_us, s.to_us, s.bytes) == (day(20), day(8) + US_PER_DAY, 200_000)
    assert str(shorter.total_gb) == "0.000" and shorter.total_bytes == 200_000
    assert w.deletes == []  # preview never mutates


async def test_scope_filters_symbols_and_streams() -> None:
    w = _world()
    w.add_cold("BTCUSDT", T, 40)
    w.add_cold("ETHUSDT", T, 40)
    plan = await manager(w).preview(PruneScope(symbols=("ETHUSDT",), streams=("trades",)))
    assert [i.symbols for i in plan.items] == [("ETHUSDT",)]
    assert (await manager(w).preview(PruneScope(streams=("tickers",)))).items == ()


async def test_purge_plan_refuses_pinned_without_include_and_skips_shared_hot_day() -> None:
    w = _world()
    w.pinned = {"BTCUSDT"}
    w.add_cold("BTCUSDT", T, 2)
    w.add_hot(T, 2, {"BTCUSDT": 1, "ETHUSDT": 1})
    w.add_hot(T, 3, {"BTCUSDT": 1})
    m = manager(w)
    plan = await m.plan_purge("BTCUSDT", NOW_US, include_pinned=False)
    assert plan.items == () and {p.reason for p in plan.protected} == {
        "pinned",
        "shared_partition",
    }
    forced = await m.plan_purge("BTCUSDT", NOW_US, include_pinned=True)
    assert len(forced.items) == 2 and forced.mode == "purge"
    report = await m.run(forced, dry_run=False)
    assert len(report.deleted) == 2 and len(w.data_deleted()) == 2
    assert day(2) in w.hot[T]  # shared day untouched


async def test_purge_run_rechecks_pin_added_after_plan() -> None:
    w = _world()
    w.add_cold("BTCUSDT", T, 2)
    m = manager(w)
    plan = await m.plan_purge("BTCUSDT", NOW_US, include_pinned=False)
    w.pinned = {"BTCUSDT"}
    report = await m.run(plan, dry_run=False)
    assert report.deleted == [] and [p.reason for p in report.skipped] == ["pinned"]


async def test_resolve_uses_stored_policies_and_pin() -> None:
    w = _world()
    w.pinned = {"ETHUSDT"}
    m = manager(w)
    assert (await m.resolve("ETHUSDT", "trades")).source == "pinned"
    assert (await m.resolve("BTCUSDT", "trades")).total_days == 30
    assert (await m.resolve("BTCUSDT", "tickers")).source == "stream_default"


async def test_hot_day_with_late_unarchived_rows_is_kept_and_critical() -> None:
    """Review H2: the watermark says archived, but rows arrived after the export."""
    w = _world()
    w.add_hot(T, 10, {"BTCUSDT": 5})
    w.archived[("BTCUSDT", T)] = day(9)
    m = manager(w)
    plan = await m.preview()  # archived at plan time
    assert len(plan.items) == 1
    w.late_rows[("BTCUSDT", day(10))] = 3  # late/backfilled rows land before the delete
    report = await m.run(plan, dry_run=False)
    assert report.deleted == [] and w.deletes == []
    assert [p.reason for p in report.skipped] == ["archive_mismatch"]
    assert ("CRITICAL", "archive.verification_failed") in w.events
    held = await manager(w).preview()  # and planning also holds it from now on
    assert [(p.reason, p.info) for p in held.protected] == [
        ("archive_mismatch", "BTCUSDT hot=8 cold=5")
    ]


async def test_late_rows_present_at_plan_time_are_held_reported_and_critical() -> None:
    """Review round 4 (A, the CI failure): late rows already on the archived day when the pass
    PLANS. The day is held while planning, so it never reaches the delete-time re-check; the
    report must still name it and the pass must still raise CRITICAL (never a silent skip)."""
    w = _world()
    w.add_hot(T, 10, {"BTCUSDT": 5})
    w.archived[("BTCUSDT", T)] = day(9)
    w.late_rows[("BTCUSDT", day(10))] = 3  # landed after the export, before this pass
    w.add_cold("BTCUSDT", T, 40)  # an expired cold partition still goes
    report = await manager(w).run_nightly()
    assert [i.tier for i in report.deleted] == ["cold"] and day(10) in w.hot[T]
    assert report.skipped == [] and report.failed == []
    assert [(p.item.tier, p.reason, p.info) for p in report.protected] == [
        ("hot", "archive_mismatch", "BTCUSDT hot=8 cold=5")
    ]
    assert w.events == [("CRITICAL", "archive.verification_failed")]
    (run_end,) = [d for a, d in w.audit if a == "retention.run" and d["phase"] == "end"]
    assert run_end["protected"] == 1


async def test_hot_day_without_cold_manifest_is_kept() -> None:
    w = _world()
    w.add_hot(T, 10, {"BTCUSDT": 5})
    w.archived[("BTCUSDT", T)] = day(9)
    w.cold_override[("BTCUSDT", day(10))] = None
    assert (await manager(w).run_nightly()).deleted == [] and w.deletes == []


async def test_hot_day_with_new_symbol_since_plan_is_kept() -> None:
    w = _world()
    w.add_hot(T, 10, {"BTCUSDT": 5})
    w.archived[("BTCUSDT", T)] = day(9)
    m = manager(w)
    plan = await m.preview()
    w.hot[T][day(10)]["ETHUSDT"] = 4  # backfilled after planning
    report = await m.run(plan, dry_run=False)
    assert report.deleted == [] and "new symbols" in report.skipped[0].info


async def test_checkpointed_hot_item_with_empty_symbols_is_refused() -> None:
    from candleviewer.recorder.retention import PruneItem, PrunePlan

    w = _world()
    w.add_hot(T, 10, {"BTCUSDT": 5})
    w.archived[("BTCUSDT", T)] = NOW_US
    item = PruneItem("hot", "trades", (), "x", day(10), day(9), 5, 5)
    report = await manager(w).run(PrunePlan(NOW_US, (item,), ()), dry_run=False)
    assert report.deleted == [] and w.deletes == []


async def test_each_deletion_has_intent_then_done_audit_records() -> None:
    """Review M1: audit before AND after; a crash between them is an intent without a done."""
    w = _world()
    w.add_cold("BTCUSDT", T, 40)
    await manager(w).run_nightly()
    seq = [d.get("phase") for a, d in w.audit if a == "data.deleted"]
    assert seq == ["intent", "done"]
    assert w.data_deleted()[0]["deletion_id"] == w.data_deleted_phase("done")[0]["deletion_id"]


async def test_failed_delete_writes_failed_record_with_class_name_only() -> None:
    w = _world()
    w.add_cold("BTCUSDT", T, 40)
    m = manager(w)

    async def boom(symbol: str, stream: object, key: str) -> bool:
        raise OSError("/secret/path/should/not/leak")

    m._cold.delete = boom  # type: ignore[method-assign]  # inject a failing port
    report = await m.run_nightly()
    (failed,) = w.data_deleted_phase("failed")
    assert failed["error"] == "OSError" and report.failed[0][1] == "OSError"
    assert all("/secret" not in str(d) for _, d in w.audit)


async def test_no_stream_without_rows_is_deleted_before_its_section7_horizon() -> None:
    """Review H1, end to end: with NO policy rows, nothing younger than §7 is deleted."""
    from candleviewer.recorder.retention import RetentionConfig
    from candleviewer.recorder.retention_defaults import STREAM_DEFAULTS
    from candleviewer.storage.models import StreamKind

    w = World()
    for stream in StreamKind:
        w.add_cold("BTCUSDT", stream, 40)
    m = manager(w)
    m._cfg = RetentionConfig(hot_streams=(), cold_streams=tuple(StreamKind))
    report = await m.run_nightly()
    assert report.deleted == []  # every §7 total is >= 90 d or forever
    assert all(STREAM_DEFAULTS[s.value][1] in (None, 90, 365, 730) for s in StreamKind)


async def test_bars_time_partitions_are_kept_forever_other_families_expire() -> None:
    """Review round 4 (1): §7 `bars_time` keeps forever, even under the seed's stream-wide
    `bars` row; `bars_tick/...` go at 24 mo. Checked again right before the delete."""
    from candleviewer.recorder.retention import PruneItem, PrunePlan, RetentionConfig
    from candleviewer.storage.models import StreamKind

    b = StreamKind.BARS
    w = World()
    w.policies[(None, "bars")] = PolicyRow(None, "bars", 90, 730)  # the repo seed's row
    keys = {f: f"bars/family={f}/symbol=BTCUSDT/bar_param=1m/ym=2024-01" for f in ("time", "tick")}
    for key in keys.values():
        w.cold.setdefault(("BTCUSDT", b), {})[key] = (day(800), 100)
    m = manager(w)
    m._cfg = RetentionConfig(hot_streams=(), cold_streams=(b,))
    assert [i.key for i in (await m.preview()).items] == [keys["tick"]]  # never planned
    report = await m.run_nightly()
    assert [i.key for i in report.deleted] == [keys["tick"]] and report.skipped == []
    assert list(w.cold[("BTCUSDT", b)]) == [keys["time"]]
    forged = PruneItem("cold", "bars", ("BTCUSDT",), keys["time"], day(800), day(799), 100, 1)
    again = await m.run(PrunePlan(NOW_US, (forged,), ()), dry_run=False)
    assert again.deleted == [] and [p.reason for p in again.skipped] == ["hot_window"]
    assert list(w.cold[("BTCUSDT", b)]) == [keys["time"]]


async def test_empty_symbol_item_is_refused_before_any_read() -> None:
    """Kills mutant H2-a: the empty-symbols guard must fire on its own (nothing is read)."""
    from candleviewer.recorder.retention import PruneItem, PrunePlan

    w = _world()
    w.add_hot(T, 10, {"BTCUSDT": 5})
    m = manager(w)
    reads: list[int] = []
    real = m._verify.hot_rows

    async def spy(stream: object, d: int) -> object:
        reads.append(d)
        return await real(stream, d)  # type: ignore[arg-type]  # passthrough

    m._verify.hot_rows = spy  # type: ignore[method-assign,assignment]  # spy the port
    item = PruneItem("hot", "trades", (), "x", day(10), day(9), 5, 5)
    report = await m.run(PrunePlan(NOW_US, (item,), ()), dry_run=False)
    assert report.deleted == [] and reads == []
    assert [(p.reason, p.info) for p in report.skipped] == [("not_archived", "no symbols")]


async def test_hot_day_reading_back_no_rows_is_never_dropped() -> None:
    """Kills mutant H2-d: an empty read-back (day vanished / read failed) proves nothing."""
    w = _world()
    w.add_hot(T, 10, {"BTCUSDT": 5})
    w.archived[("BTCUSDT", T)] = day(9)
    m = manager(w)
    plan = await m.preview()
    w.late_rows[("BTCUSDT", day(10))] = -5  # read-back now returns 0 rows
    report = await m.run(plan, dry_run=False)
    assert report.deleted == [] and w.deletes == []
    assert [(p.reason, p.info) for p in report.skipped] == [
        ("archive_mismatch", "no rows read back")
    ]
