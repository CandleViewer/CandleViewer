#!/usr/bin/env python3
"""#4605: split the merge queue's Postgres/QuestDB integration suite into shards by measured cost.

`_job-integration.yml` ran `pytest tests/integration -m "integration and not perf and not flaky"`
in one job, and that step alone grew to 18-28 minutes against a 30-minute hang guard (run
40309420588 was cancelled at 30:00 and its PR ejected from the queue). The `integration-shard`
matrix now runs one shard per job, and the `integration` job, the check `ci-required` reads,
fails unless every shard and the `integration-stack` job passed.

The files are the ones `pytest tests/integration` collects from services/api: recursive, pytest's
default `python_files` (pyproject sets no other), no `__pycache__` or dot directories, as
`tools/ci/py_test_lanes.py` lists them. A file whose tests are all deselected by the marker
expression (the fixture-driven pipeline, the perf-marked files) still lands in a shard and is
deselected there, as before. The split is `governance_shards.shards`: `PINNED` files first,
then every other file greedily, heaviest first, to the lightest shard.

`WEIGHTS` holds the median seconds per file, over five merge-group runs of the `integration`
job on 2026-10-26, of every file that took 0.5 s or more, read from pytest's per-file progress
lines by `python tools/ci/integration_shards.py weigh LOG...` (`py_test_lanes.log_durations`;
each file's container start-up is inside it, no fixture is session-scoped): runs 40314689824
(job 121544380186, 18.2 min of pytest), 40313441542 (121540241321, 20.4 min), 40311572348
(121535134566, 24.9 min), 40309804896 (121528404102, 24.8 min) and 40309420588 (121526736412,
27.4 min, the cancelled run, whose suite step had finished). The medians sum to 1,456 s; the
slowest run took `SLOWEST_RUN_FACTOR` times that. Any other file costs `DEFAULT_WEIGHT`, the
median file, so a new, renamed or moved file always lands in exactly one shard
(`scripts/tests/test_integration_shards.py` proves it for every collected file) and stale
weights cost balance, never coverage. Refresh the table when a shard's pytest time, which each
shard writes to the job summary and the `integration` job tabulates, creeps up.

`python tools/ci/integration_shards.py 1 4` prints shard 1 of 4, one path per line, relative to
services/api. Stdlib only.
"""

from __future__ import annotations

import fnmatch
import math
import statistics
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from tools.ci.governance_shards import PYTHON_FILES, shards  # noqa: E402 - repo root added above
from tools.ci.py_test_lanes import log_durations  # noqa: E402 - repo root added above

API_ROOT = REPO_ROOT / "services" / "api"
SUITE = "tests/integration"
#: Files whose report the shard job uploads, so they run in the shard the upload step names:
#: {path: (shard, why)}.
PINNED: dict[str, tuple[int, str]] = {
    "tests/integration/storage/test_restore_drill.py": (
        1,
        "writes build/reports/restore-drill.json, uploaded as `restore-drill-report` "
        "(if-no-files-found: error) by shard 1",
    ),
    "tests/integration/storage/test_storage_perf_harness.py": (
        1,
        "writes build/reports/storage-perf.json when its perf tests run, uploaded as "
        "`storage-perf` by shard 1 (deselected here by `not perf`, so a warning only)",
    ),
}
#: The shard job's non-pytest time: set-up, checkout, uv sync, image pre-pull, collection and
#: uploads (about 70 s in run 40314689824), rounded up.
SHARD_OVERHEAD_S = 90
#: The slowest of the five runs over the sum of the medians (1,644 s / 1,456.2 s).
SLOWEST_RUN_FACTOR = 1.13
#: A shard job's `timeout-minutes` is its expected worst duration plus this (#4605).
TIMEOUT_MARGIN_MIN = 10
DEFAULT_WEIGHT = 6.3
WEIGHTS: dict[str, float] = {
    "tests/integration/bench/test_d2_bars_first_reads_questdb.py": 44.8,
    "tests/integration/storage/test_account_profiles_migration.py": 41.1,
    "tests/integration/storage/test_questdb_hot_tier.py": 38.5,
    "tests/integration/storage/test_order_submission_contract_pg.py": 33.4,
    "tests/integration/storage/test_backups_write_once_pg.py": 32.7,
    "tests/integration/storage/test_trade_groups_migration.py": 30.6,
    "tests/integration/storage/test_risk_state_migration.py": 30.1,
    "tests/integration/storage/test_sessions_view_as_store_pg.py": 28.2,
    "tests/integration/audit/test_audit_repository.py": 25.3,
    "tests/integration/storage/test_incidents_backups_migration.py": 24.6,
    "tests/integration/bench/test_d2_m2_tail_bound_questdb.py": 23.6,
    "tests/integration/storage/test_order_vocabulary_migration.py": 23.4,
    "tests/integration/storage/test_feature_flags_migration.py": 23.3,
    "tests/integration/bench/test_d2_m4_scan_bound_questdb.py": 22.7,
    "tests/integration/storage/test_settings_migration.py": 21.8,
    "tests/integration/auth/test_0024_api_keys_write_once_migration.py": 21.5,
    "tests/integration/storage/test_questdb_ddl_resume.py": 20.3,
    "tests/integration/storage/test_oms_core_migration.py": 18.1,
    "tests/integration/auth/test_0019_snapshot_withdraw_transfer_migration.py": 18.0,
    "tests/integration/storage/test_machine_persistence_migration.py": 17.9,
    "tests/integration/storage/test_audit_signing_keys_pg.py": 17.0,
    "tests/integration/storage/test_retention_policies_pg.py": 16.1,
    "tests/integration/storage/test_orders_store_pg.py": 15.9,
    "tests/integration/storage/test_auth_keys_pg.py": 15.6,
    "tests/integration/storage/test_replay_sessions_repository_pg.py": 14.9,
    "tests/integration/auth/test_bootstrap_owner_pg.py": 14.3,
    "tests/integration/auth/test_0017_exchange_accounts_api_keys_migration.py": 14.3,
    "tests/integration/storage/test_order_submission_migration.py": 14.0,
    "tests/integration/storage/test_recorded_stop_resolution_pg.py": 12.5,
    "tests/integration/bench/test_e26_replay_seek_questdb.py": 12.4,
    "tests/integration/storage/test_trade_groups_store_pg.py": 12.2,
    "tests/integration/admin/test_admin_fixture_b4b_pg.py": 12.0,
    "tests/integration/oms/test_submission_pipeline_pg.py": 11.4,
    "tests/integration/audit/test_two_writers_one_chain.py": 11.2,
    "tests/integration/storage/test_machine_persistence_json_migration.py": 10.9,
    "tests/integration/storage/test_replay_sessions_migration.py": 10.8,
    "tests/integration/storage/test_drawings_layout_race.py": 10.6,
    "tests/integration/admin/test_admin_abuse_pg.py": 10.6,
    "tests/integration/storage/test_sessions_view_as_migration.py": 10.3,
    "tests/integration/storage/test_account_access_store_pg.py": 9.8,
    "tests/integration/auth/test_0026_kek_versions_env_migration.py": 9.7,
    "tests/integration/storage/test_drawings_repository.py": 9.7,
    "tests/integration/storage/test_credentials_store_pg.py": 9.5,
    "tests/integration/storage/test_account_profiles_store_pg.py": 9.5,
    "tests/integration/admin/test_user_purge_pg.py": 9.3,
    "tests/integration/storage/test_recorder_repository.py": 9.2,
    "tests/integration/storage/test_drawings_migration.py": 9.1,
    "tests/integration/storage/test_users_purge_migration.py": 8.8,
    "tests/integration/auth/test_break_glass_reset_pg.py": 8.6,
    "tests/integration/storage/test_statechart_stores_pg.py": 8.5,
    "tests/integration/storage/test_storage_service_real.py": 8.5,
    "tests/integration/storage/test_order_submission_pg.py": 8.4,
    "tests/integration/storage/test_workspaces_repository.py": 8.2,
    "tests/integration/auth/test_auth_e2e_pg.py": 8.1,
    "tests/integration/storage/test_alerts_migration.py": 7.9,
    "tests/integration/storage/test_account_no_hard_delete_migration.py": 7.9,
    "tests/integration/auth/test_0020_kek_versions_migration.py": 7.9,
    "tests/integration/storage/test_ea_identity_write_once_migration.py": 7.8,
    "tests/integration/storage/test_workspaces_migration.py": 7.7,
    "tests/integration/storage/test_account_env_write_once_migration.py": 7.5,
    "tests/integration/audit/test_audit_guard_cv_app.py": 7.5,
    "tests/integration/admin/test_admin_fixture_b4a_pg.py": 7.4,
    "tests/integration/auth/test_bootstrap_redemption_pg.py": 7.4,
    "tests/integration/auth/test_bootstrap_owner_e2e_pg.py": 7.3,
    "tests/integration/oms/test_place_order_route_pg.py": 7.3,
    "tests/integration/auth/test_breakglass_cli_pg.py": 7.2,
    "tests/integration/storage/test_system_events_recipient_migration.py": 7.2,
    "tests/integration/storage/test_recorder_rolloff_questdb.py": 7.2,
    "tests/integration/auth/test_step_up_grant_race_pg.py": 7.2,
    "tests/integration/admin/test_user_admin_pg.py": 7.1,
    "tests/integration/storage/test_ea_env_parent_always_migration.py": 7.1,
    "tests/integration/audit/test_audit_chain_hardening_migration.py": 7.0,
    "tests/integration/storage/test_policy_disarm_migration.py": 6.9,
    "tests/integration/storage/test_rules_migration.py": 6.7,
    "tests/integration/storage/test_statechart_sink_pg.py": 6.6,
    "tests/integration/admin/test_user_lifecycle_pg.py": 6.6,
    "tests/integration/storage/test_questdb_migrate_step.py": 6.5,
    "tests/integration/storage/test_backups_pg.py": 6.4,
    "tests/integration/admin/test_admin_corrupt_chain_pg.py": 6.3,
    "tests/integration/storage/test_rule_perms_status_pg.py": 6.3,
    "tests/integration/storage/test_restore_drill.py": 6.3,
    "tests/integration/storage/test_export_key_store_pg.py": 6.2,
    "tests/integration/storage/test_accounts_store_pg.py": 6.2,
    "tests/integration/storage/test_indicator_presets_migration.py": 6.2,
    "tests/integration/storage/test_incident_upsert_pg.py": 6.2,
    "tests/integration/storage/test_guarded_privileges_pg.py": 6.1,
    "tests/integration/admin/test_admin_audit_10m_pg.py": 5.8,
    "tests/integration/auth/test_0001_identity_migration.py": 5.8,
    "tests/integration/auth/test_0016_audit_read_grants_migration.py": 5.7,
    "tests/integration/auth/test_disabled_user_sessions_pg.py": 5.7,
    "tests/integration/storage/test_identity_accounts_pg.py": 5.7,
    "tests/integration/storage/test_flags_store_pg.py": 5.6,
    "tests/integration/auth/test_invites_pg.py": 5.5,
    "tests/integration/storage/test_admin_readmodel_pg.py": 5.4,
    "tests/integration/storage/test_system_settings_pg.py": 5.4,
    "tests/integration/storage/test_incidents_pg.py": 5.3,
    "tests/integration/auth/test_auth_repositories_pg.py": 5.2,
    "tests/integration/oms/test_startup_sweep_pg.py": 5.2,
    "tests/integration/auth/test_login_lockout_race_pg.py": 5.2,
    "tests/integration/storage/test_retention_readers_action_pg.py": 5.2,
    "tests/integration/storage/test_alert_owner_gate_pg.py": 5.0,
    "tests/integration/storage/test_indicator_presets_repository.py": 5.0,
    "tests/integration/storage/test_notifications_union_pg.py": 4.9,
    "tests/integration/admin/test_admin_latched_machine_pg.py": 4.9,
    "tests/integration/admin/test_user_disable_route_pg.py": 4.8,
    "tests/integration/audit/test_audit_verify_batches.py": 4.8,
    "tests/integration/storage/test_alert_dispatcher_pg.py": 4.7,
    "tests/integration/admin/test_kek_rewrap_route_pg.py": 4.6,
    "tests/integration/admin/test_admin_fixture_seed_pg.py": 4.6,
    "tests/integration/migrations/test_boot_advisory_lock_integration.py": 4.6,
    "tests/integration/storage/test_kek_lineage_shared_db.py": 4.6,
    "tests/integration/storage/test_recorder_startup_reconcile_pg.py": 4.5,
    "tests/integration/audit/test_audit_query_page.py": 4.5,
    "tests/integration/storage/test_alerts_repository_pg.py": 4.5,
    "tests/integration/accounts/test_account_fixture_boot_guard_pg.py": 4.5,
    "tests/integration/admin/test_restore_guard_pg.py": 4.5,
    "tests/integration/storage/test_dms_episode_journal_pg.py": 4.5,
    "tests/integration/storage/test_alerts_ws_topic_pg.py": 4.5,
    "tests/integration/auth/test_user_roles_audit_timeout_pg.py": 4.4,
    "tests/integration/auth/test_user_roles_pg.py": 4.4,
    "tests/integration/audit/test_audit_lane_drain.py": 4.4,
    "tests/integration/storage/test_incident_ack_pg.py": 4.4,
    "tests/integration/storage/test_rules_store_pg.py": 4.3,
    "tests/integration/storage/test_oms_reads_pg.py": 4.3,
    "tests/integration/audit/test_audit_verify_runner_pg.py": 4.3,
    "tests/integration/storage/test_incident_list_pg.py": 4.3,
    "tests/integration/storage/test_recording_reads_pg.py": 4.2,
    "tests/integration/accounts/test_e28_fixture_seed_pg.py": 4.2,
    "tests/integration/storage/test_rule_disarm_adapter_pg.py": 4.2,
    "tests/integration/storage/test_incident_retention_pg.py": 4.2,
    "tests/integration/storage/test_backup_runs_pg.py": 4.2,
    "tests/integration/storage/test_alerts_channels_pg.py": 4.2,
    "tests/integration/audit/test_breakglass_fold_in.py": 4.2,
    "tests/integration/storage/test_seed_idempotency.py": 4.2,
    "tests/integration/storage/test_cv_app_role_privileges.py": 4.2,
    "tests/integration/storage/test_recording_lifecycle_pg.py": 4.1,
    "tests/integration/audit/test_audit_verify_checkpoints.py": 4.1,
    "tests/integration/audit/test_audit_text_storable.py": 4.1,
    "tests/integration/storage/test_backup_delete_pg.py": 4.1,
    "tests/integration/storage/test_instruments_repository.py": 4.1,
    "tests/integration/auth/test_api_keys_write_once_at_head.py": 4.1,
    "tests/integration/storage/test_backup_verify_pg.py": 4.1,
    "tests/integration/storage/test_alert_outbox_depth_pg.py": 4.0,
    "tests/integration/audit/test_audit_guard_privileged_role.py": 4.0,
    "tests/integration/storage/test_trade_grants_pg.py": 4.0,
    "tests/integration/audit/test_audit_canonical_pin.py": 4.0,
    "tests/integration/storage/test_recorder_retention_questdb.py": 3.9,
    "tests/integration/storage/test_replay_straddle_questdb.py": 3.9,
    "tests/integration/storage/test_cold_tier_export.py": 3.6,
    "tests/integration/storage/test_questdb_bars_tail.py": 3.6,
    "tests/integration/orderflow/test_indicator_priming.py": 3.5,
    "tests/integration/storage/test_questdb_bars_keyset.py": 3.5,
    "tests/integration/storage/test_recorded_reader_questdb.py": 3.5,
    "tests/integration/storage/test_recorder_stream_writer_questdb.py": 3.5,
    "tests/integration/storage/test_rolloff_lock_pg.py": 2.7,
    "tests/integration/audit/test_audit_query_timeout.py": 1.6,
}


def suite_files(api_root: Path = API_ROOT) -> list[str]:
    """Every test module `pytest tests/integration` collects, as POSIX paths of services/api."""
    found: list[str] = []
    for path in (api_root / SUITE).rglob("*.py"):
        relative = path.relative_to(api_root)
        if any(part == "__pycache__" or part.startswith(".") for part in relative.parts):
            continue
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in PYTHON_FILES):
            found.append(relative.as_posix())
    return sorted(found)


def split(files: Sequence[str], count: int) -> list[list[str]]:
    pinned = {name: shard for name, (shard, _) in PINNED.items()}
    return shards(files, count, weights=WEIGHTS, default=DEFAULT_WEIGHT, pinned=pinned)


def timeout_minutes(count: int, files: Sequence[str] | None = None) -> int:
    """The shard job's timeout: the heaviest shard at the slowest run's pace, plus the job's
    overhead, in whole minutes, plus `TIMEOUT_MARGIN_MIN`."""
    names = suite_files() if files is None else files
    heaviest = max(
        sum(WEIGHTS.get(n, DEFAULT_WEIGHT) for n in part) for part in split(names, count)
    )
    return math.ceil((heaviest * SLOWEST_RUN_FACTOR + SHARD_OVERHEAD_S) / 60) + TIMEOUT_MARGIN_MIN


def weigh(logs: Sequence[str]) -> dict[str, float]:
    """The median seconds per file over the job logs that time it (a shard's log times its own)."""
    runs = [log_durations(Path(log).read_text(encoding="utf-8", errors="replace")) for log in logs]
    names = sorted({name for run in runs for name in run})
    return {n: statistics.median(run[n] for run in runs if n in run) for n in names}


USAGE = "usage: integration_shards.py INDEX COUNT  (1 <= INDEX <= COUNT) | weigh LOG..."


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["weigh"] and len(args) > 1:
        for name, seconds in sorted(weigh(args[1:]).items(), key=lambda kv: (-kv[1], kv[0])):
            print(f'    "{name}": {seconds:.1f},')
        return 0
    if len(args) != 2 or not all(a.isdigit() for a in args):
        print(USAGE, file=sys.stderr)
        return 2
    index, count = int(args[0]), int(args[1])
    if not 1 <= index <= count:
        print(USAGE, file=sys.stderr)
        return 2
    chosen = split(suite_files(), count)[index - 1]
    if not chosen:
        print(f"integration_shards: shard {index} of {count} is empty", file=sys.stderr)
        return 1
    print("\n".join(chosen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
