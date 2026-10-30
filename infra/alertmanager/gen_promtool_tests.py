#!/usr/bin/env python3
"""E04-T05: regenerate infra/prometheus/tests/system_alerts.test.yml (promtool unit tests).

Each threshold rule gets a case whose series crosses the threshold (alert fires at
eval_time) and a case that stays healthy / recovers (no alert).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROM = Path(__file__).resolve().parents[1] / "prometheus"
#: The rule files the cases load and the lookups below read: the system set, and #837's account
#: set, whose cases are here so that the one promtool run CI makes covers them.
RULE_FILES = ("system_page.yml", "system_ticket.yml", "accounts.yml")
# #965 R7: a disable whose store raised (`result` `error`; a refusal is another result).
_ERRORED = 'cv_user_lifecycle_total{action="disable",env="live",result="error"}'
# #836: the key self-check's series.
_LATCH = 'cv_key_selfcheck_latch_state{env="live"}'
_MISSED = 'cv_key_selfcheck_missed_runs_total{env="live"}'
_EXPIRY = 'cv_key_soonest_expiry_seconds{env="live"}'
_FAILING = 'cv_keys_failing_policy{{env="live",rule="{}"}}'
_WD, _NA, _IP = "key_withdraw_permission", "key_permission_not_allowed", "key_ip_whitelist_mismatch"
# ADR-0037 S4a (#3009): the audit lane's series, each bound from process start.
_LANE = 'cv_audit_lane_{}{{env="live"}}'
_STATE = 'cv_audit_lane_state{{env="live",state="{}"}}'
# #1016 (E40-T04): the outbox's depth gauge and dead-letter counter, for alert.deliver and, as the
# silent case, for another topic (webhook.post).
_DEPTH = 'cv_outbox_depth{env="live",topic="alert.deliver"}'
_DEPTH_OTHER = 'cv_outbox_depth{env="live",topic="webhook.post"}'
_DEAD = 'cv_outbox_dead_total{env="live",topic="alert.deliver"}'
_DEAD_OTHER = 'cv_outbox_dead_total{env="live",topic="webhook.post"}'

# alert -> (series, firing values, healthy values, eval_time, extra labels)
SPEC: dict[str, tuple[str, str, str, str, dict[str, str]]] = {
    "NakedPositionDetected": (
        "naked_position_alerts_total",
        "0+0x10 1+0x10",
        "0+0x20",
        "15m",
        {},
    ),
    "OmsUnknownOrders": ("oms_unknown_orders", "0 2+0x10", "0+0x12", "5m", {}),
    # E29-T05 S8b (20 section 12.5): a position reading owed to protection for 60 s pages; one owed
    # 59 s does not.
    "OmsPositionReadingOwed": (
        "oms_position_reading_owed_age_seconds", "0+0x2 60+0x10", "59+0x12", "5m", {},
    ),
    "PostgresDown": ("pg_up", "0+0x10", "1+0x10", "5m", {}),
    "ClockDriftBlockingTrading": (
        "bybit_clock_drift_ms",
        "2000+0x10",
        "10+0x10",
        "5m",
        {},
    ),
    "DiskCritical": ("disk_used_ratio", "0.97+0x10", "0.5+0x10", "5m", {}),
    "AuditChainVerificationFailed": (
        "audit_chain_verification_failures_total",
        "0+0x10 1+0x10",
        "0+0x20",
        "15m",
        {},
    ),
    # Starts at 1 (degraded from the first scrape) — the real boot-failure shape.
    "KekUnavailable": (
        'cv_kek_degraded_state{env="live"}', "1+0x20", "0+0x20", "5m", {"env": "live"}
    ),
    # #889 S6b-2: as KekUnavailable, set at boot and held for the life of the process.
    "AuditSigningKeyUnavailable": (
        'cv_audit_signing_key_unavailable_state{env="live"}', "1+0x20", "0+0x20", "5m",
        {"env": "live"},
    ),
    # #2496: safe, then the hourly re-check finds an unsafe bind; pages with no hold time.
    "NetBindingUnsafe": (
        'net_binding_safe{env="live"}',
        "1+0x4 0+0x10",
        "1+0x15",
        "5m",
        {"env": "live"},
    ),
    "SyntheticAlert": ("cv_synthetic_alert", "1+0x10", "0+0x10", "5m", {}),
    "PublicWsDown": (
        'ws_connection_state{socket="public"}',
        "0+0x10",
        "1+0x10",
        "5m",
        {"socket": "public"},
    ),
    "DiskHigh": ("disk_used_ratio", "0.85+0x20", "0.5+0x20", "10m", {}),
    "RuleAutodisarm": ("rule_autodisarm_total", "0+0x10 1+0x10", "0+0x20", "15m", {}),
    "EnvMismatchAttempt": (
        "env_mismatch_attempts_total",
        "0+0x10 1+0x10",
        "0+0x20",
        "15m",
        {},
    ),
    "CredentialExpiryApproaching": (
        "credential_expiry_days",
        "5+0x30",
        "60+0x30",
        "20m",
        {},
    ),
    "AuthLockouts": ("auth_lockouts_total", "0+0x10 1+0x10", "0+0x20", "15m", {}),
    # #4648: one failed sign-in returned without the wait is enough.
    "AuthLoginFailureFloorMissed": (
        'auth_login_failure_floor_missed_total{env="live"}',
        "0+0x10 1+0x10",
        "0+0x20",
        "15m",
        {"env": "live"},
    ),
    # #4663: one sign-in attempt refused because verification was at capacity is enough.
    "AuthLoginVerifyRefused": (
        'auth_login_verify_refused_total{env="live"}',
        "0+0x10 1+0x10",
        "0+0x20",
        "15m",
        {"env": "live"},
    ),
    # #2496 (SR-022): a single accepted recovery code is enough.
    "AuthRecoveryCodeUsed": (
        'auth_recovery_codes_used_total{env="live"}',
        "0+0x10 1+0x10",
        "0+0x20",
        "15m",
        {"env": "live"},
    ),
    # #2496 item 3 (SR-023): the first scrape after the restart that follows a break-glass run
    # already reads 1 (the start-up read runs before cv-api serves), so the series starts at 1.
    "AuthBreakGlassUsed": (
        'auth_break_glass_unresolved_events{env="live"}',
        "1+0x20",
        "0+0x20",
        "5m",
        {"env": "live"},
    ),
    # #2496 review: a run that was already on record (2) and one more (3). The page reads the rise
    # against the maximum before the last 15 minutes, so the case evaluates once the 3 has been in
    # for a few scrapes and the right-hand window (which ends 15m earlier) still holds only 2s.
    "AuthBreakGlassAttempted": (
        'auth_break_glass_attempts{env="live"}',
        "2+0x10 3+0x10",
        "2+0x20",
        "20m",
        {"env": "live"},
    ),
    # #4479 C2: no grant on record (0), then the redemption's (1), read as the attempts page reads.
    "AuthOwnerBootstrapped": (
        'auth_owner_bootstraps{env="live"}',
        "0+0x10 1+0x10",
        "0+0x20",
        "20m",
        {"env": "live"},
    ),
    # #2914 (04 section 8.3 rule 2): one lost outcome record tickets, more than 5 in 15 minutes
    # pages. 4 is the near-miss: exactly 5 could page under Prometheus 3 (`increase` extrapolates
    # differently over its left-open ranges).
    "AuthAuditOutcomeLost": (
        'auth_audit_outcome_lost_total{action="auth.session_revoked",env="live"}',
        "0+0x10 1+0x10",
        "0+0x20",
        "15m",
        {"env": "live"},
    ),
    "AuthAuditOutcomesLostBurst": (
        'auth_audit_outcome_lost_total{action="auth.session_revoked",env="live"}',
        "0+0x10 8+0x10",
        "0+0x10 4+0x10",
        "15m",
        {"env": "live"},
    ),
    # #3794: one run that lists no day for a stream holding aged partitions is a ticket.
    "RollOffStreamUnlisted": (
        'recorder_rolloff_streams_unlisted_total{env="live",stream="orderbook_delta"}',
        "0+0x10 1+0x10",
        "0+0x20",
        "15m",
        {"env": "live", "stream": "orderbook_delta"},
    ),
    "CredentialVerificationFailures": (
        "credential_verification_failures_total",
        "0+0x10 1+0x10",
        "0+0x20",
        "15m",
        {},
    ),
    "OmsRateRejects": ("oms_rate_reject_total", "0+0x10 3+0x10", "0+0x20", "15m", {}),
    "EgressIpChanged": (
        "egress_ip_changes_total",
        "0+0x10 1+0x10",
        "0+0x20",
        "15m",
        {},
    ),
    "AlertmanagerNotificationsFailed": (
        "alertmanager_notifications_failed_total",
        "0+0x10 2+0x10",
        "0+0x20",
        "15m",
        {},
    ),
    # #2496 review: the reader failed every minute for a quarter of an hour (15 failures).
    "AuthBreakGlassStateReadFailing": (
        'auth_break_glass_state_read_failures_total{env="live"}',
        "0+1x15",
        "0+0x20",
        "15m",
        {"env": "live"},
    ),
    "UserDisableFailed": (_ERRORED, "0+0x10 1+0x10", "0+0x20", "15m", {"env": "live"}),
    "KeySelfCheckRunMissed": (_MISSED, "0+0x10 1+0x10", "0+0x20", "15m", {"env": "live"}),
    # #836 (SR-034): one ticket per band; a healthy case on the upper edge, or the unset 0.
    "KeyExpiringWithin14Days": (_EXPIRY, "864000+0x30", "1209600+0x30", "20m", {"env": "live"}),
    "KeyExpiringWithin7Days": (_EXPIRY, "259200+0x30", "604800+0x30", "20m", {"env": "live"}),
    "KeyExpiringWithin1Day": (_EXPIRY, "43200+0x30", "0+0x30", "20m", {"env": "live"}),
    # ADR-0037 S4a (#3009), the audit lane's tickets: a refusal a caller saw; the oldest unit's age
    # past 600 s (900) or keeping up (30); a held lane; the head going back across a restart (20,
    # then 3); a boot count already 2 at the first scrape (set before it); `quarantine/` growing.
    "AuditSinkRefusing": (
        'cv_audit_writer_refused_total{domain="auth",env="live"}',
        "0+0x5 1+0x20",
        "0+0x25",
        "10m",
        {"env": "live"},
    ),
    "AuditLaneBacklogAged": (
        _LANE.format("oldest_age_seconds"), "0+60x20", "30+0x20", "15m", {"env": "live"}
    ),
    "AuditLaneDrainHeld": (_STATE.format("held"), "1+0x20", "0+0x20", "5m", {"env": "live"}),
    "AuditLaneSeqRegressed": (
        _LANE.format("last_seq"), "10+1x10 3+1x10", "10+1x20", "25m", {"env": "live"}
    ),
    "AuditLaneBootOvershoot": (
        _LANE.format("boot_overshoot_frames_total"), "2+0x20", "0+0x20", "5m", {"env": "live"}
    ),
    "AuditLaneQuarantineGrowing": (
        _LANE.format("quarantine_bytes"), "100+0x10 400+0x20", "400+0x30", "20m", {"env": "live"}
    ),
    # #1016 (E40-T04): the alert.deliver backlog over 100 for 5 minutes; 100 itself is no backlog.
    "AlertOutboxBacklog": (_DEPTH, "101+0x20", "100+0x20", "10m", {"env": "live"}),
}

_LAST_OK = 'cv_audit_verify_last_ok_timestamp_seconds{env="live"}'
_LAST_OK_DEMO = 'cv_audit_verify_last_ok_timestamp_seconds{env="demo"}'
_STOPPED = 'cv_audit_verify_runs_total{env="live",result="stopped"}'
_PASSED = 'cv_audit_verify_runs_total{env="live",result="ok"}'
# A restart at 24 h re-seeds the gauge and resets the counter; start-up runs stop on each side.
_RESTART = {_LAST_OK: "60+0x1439 86400+0x245", _STOPPED: "0+0x4 1+0x1434 0+0x4 1+0x240"}
_PASS_AT_26H = {_LAST_OK: "60+0x1439 86400+0x119 93600+0x125", _PASSED: "0+0x1559 1+0x125"}
_STRAY = 'auth_disabled_user_sessions_revoked_total{env="live"}'
# One stray session at 6 min: the breach counter steps from 0 to 1. The first empty evaluation of
# the 15 m window is 21 m (3.x range selectors: 20 m), so `keep_firing_for: 9h30m` ends at 9 h 51 m
# (3.x: 9 h 50 m): firing at 9 h 49 m, resolved at 9 h 52 m.
_ONE_STRAY = {_STRAY: "0+0x5 1+0x700"}
# #3635 (#3497): the one counter of a WebSocket close that failed, the hub's and the registry's.
_CLOSE_FAILED = 'ws_session_revocation_close_failures_total{env="live"}'


def _steps(step: str, outcome: str) -> str:
    """#965: a `cv_user_lifecycle_steps_total` series (every one is bound at 0 from import)."""
    return f'cv_user_lifecycle_steps_total{{env="live",outcome="{outcome}",step="{step}"}}'


# One failure at 6 min, held and resolved as _ONE_STRAY is; a flat count is an old failure.
_RISE, _FLAT = "0+0x5 1+0x700", "3+0x700"
_SWEEP_FAILED = {_steps("session_sweep", "failed"): _RISE}
# A step that passed, an old failure and a failed grants push (the next ticket's).
_NO_STEP_FAILED = {
    _steps("session_sweep", "ok"): _RISE,
    _steps("rule_disarm", "failed"): _FLAT,
    _steps("grants_push", "failed"): _RISE,
}
_LATENCY = 'auth_revocation_latency_seconds_bucket{{env="live",le="{}"}}'


def _health(state: str, reason: str, *, moved: bool = False) -> str:
    """#837: a series of the health gauge, or of the transition counter (`moved`), every pair of
    which the runtime binds at start (account_health_wiring.py)."""
    name = "cv_account_health_transitions_total" if moved else "cv_account_health_state"
    return f'{name}{{env="live",reason="{reason}",state="{state}"}}'


_DOWN, _NEVER = _health("down", "no_success"), _health("down", "never_connected")
_INTO_DOWN, _SILENT = _health("down", "no_success", moved=True), _health("degraded", "ws_silent")
# Down at 6 min and still down; down from 6 min to 10 min and back at 11 min.
_STAYS_DOWN, _BACK_UP, _ZERO = "0+0x5 1+0x20", "0+0x5 1+0x4 0+0x15", "0+0x25"
_WARN = 'cv_key_rotation_notices_total{env="live",state="warn"}'
_OVERDUE = 'cv_key_rotation_notices_total{env="live",state="overdue"}'
# One overdue key, counted at 6 min and again a day later.
_A_DAY_APART = "0+0x5 1+0x1439 2+0x700"
# #914 (E29-T06, BQ-12): the trading reads' refused rows of another of our accounts, and of
# another environment (silent); a first refusal binds the series, so it starts with no sample.
_ACCOUNT_ROWS = 'bybit_rows_refused_total{env="live",reason="account"}'
_ENV_ROWS = 'bybit_rows_refused_total{env="live",reason="environment"}'
_FIRST_ROW = "_x5 1+0x700"


def _closes(fast: int, under_5: int, slow: int) -> dict[str, str]:
    """#3415: revocations at 6 min whose closes were initiated in at most 2.5 s (`fast`), in 2.5 to
    5 s (`under_5`) and in 5 to 10 s (`slow`), as cumulative buckets; lower edges add nothing."""
    counts = {"2.5": fast, "5.0": fast + under_5, "10.0": fast + under_5 + slow}
    counts["+Inf"] = counts["10.0"]
    return {_LATENCY.format(le): f"0+0x5 {n}+0x700" for le, n in counts.items()}


# #3009 S4a: a lane refusal or anomaly at 6 min, by its labels.
_REFUSED = 'cv_audit_lane_refused_total{{class="shared",env="live",reason="{}"}}'
_ANOMALY = 'cv_audit_lane_anomalies_total{{env="live",reason="{}"}}'
# A count a boot sets before the first scrape, read while the process (prometheus_client's
# process_start_time_seconds, same target) is under 15 minutes old (SR-S4A2-01, SR-S4A2-02).
_ON = 'instance="api:9108",job="candleviewer-api"'
_START = f"process_start_time_seconds{{{_ON}}}"
_CREATED = f'cv_audit_lane_created_total{{env="live",{_ON}}}'
_BOOTED = 'cv_audit_lane_anomalies_total{{env="live",' + _ON + ',reason="{}"}}'
# A restart gap of 30 minutes: the old process at 0 until 5 min, the new one from 36 min (2160 s),
# whose scan already counted 1; and a first boot at 30 min (1800 s) with no history at all.
_GAP, _GAP_START = "0+0x5 _x30 1+0x20", "0+0x5 _x30 2160+0x20"
_FIRST, _FIRST_START = "_x30 1+0x20", "_x30 1800+0x20"

# alert -> cases of (eval_time, fires, {series: values}) over several `env="live"` series.
MULTI: dict[str, tuple[tuple[str, bool, dict[str, str]], ...]] = {
    # #2111. Pages: last pass at 5 min; runs that keep stopping across the restart. Healthy: a
    # pass at 26 h, after the restart.
    # #2966: no runner wired in `live` (the gauge reads 0 and the counter has no series) pages at
    # the first evaluation and keeps paging. The same reading in `demo` (the fake backend runs no
    # job) and a job that has started (the gauge holds its start time) stay silent.
    # The 26 h threshold is 24 h (the daily run) + 5400 s (the longest deadline it covers; a longer
    # one needs the threshold raised, 24-internal-schemas.md section 15.4) + 30 min. A pass at 1 h
    # pins it from both sides: 25 h 30 min old (24 h + 5400 s, a healthy cadence at its slowest)
    # does not page, 26 h 1 min old does.
    "AuditVerifyNotPassing": (
        ("28h", True, {_LAST_OK: "300+0x1700"}),
        ("28h", True, {**_RESTART, _PASSED: "0+0x1685"}),
        ("5m", True, {_LAST_OK: "0+0x10"}),
        ("28h", True, {_LAST_OK: "0+0x1700"}),
        ("28h", False, {_LAST_OK_DEMO: "0+0x1700"}),
        ("5m", False, {_LAST_OK: "300+0x10"}),
        ("28h", False, {**_RESTART, **_PASS_AT_26H}),
        ("1590m", False, {_LAST_OK: "3600+0x1590"}),
        ("1621m", True, {_LAST_OK: "3600+0x1621"}),
    ),
    # #3029. A ticket with no `for`: fires on the first evaluation after the step and is held past
    # the 9 h quiet-hours mute (firing at 9 h 49 m, resolved at 9 h 52 m). A flat counter never fires.
    "AuthDisabledUserSessionRevoked": (
        ("6m", True, _ONE_STRAY),
        ("9h49m", True, _ONE_STRAY),
        ("9h52m", False, _ONE_STRAY),
        ("30m", False, {_STRAY: "3+0x700"}),
    ),
    # #965 R7: a failed cascade step fires on the first evaluation after it and is held past the
    # mute; nothing else fires it.
    "UserLifecycleStepFailed": (
        ("6m", True, _SWEEP_FAILED),
        ("9h49m", True, _SWEEP_FAILED),
        ("9h52m", False, _SWEEP_FAILED),
        ("6m", False, _NO_STEP_FAILED),
    ),
    # #2648 R7: a push that timed out or failed fires it; its hold is the ticket above's (the same
    # `for` and `keep_firing_for`, pinned in test_user_lifecycle_alert_rules.py). A push that ended
    # `pushed` and a failed cascade step (the ticket above) never fire it.
    "UserGrantsPushFailed": (
        ("6m", True, {_steps("grants_push", "timeout"): _RISE}),
        ("6m", True, {_steps("grants_push", "failed"): _RISE}),
        ("6m", False, {_steps("grants_push", "pushed"): _RISE, **_SWEEP_FAILED}),
    ),
    # #3415. One 6 s close fires at once (`for: 0m`) and is held as the ticket above. Silent: one
    # close under the 5 s edge, 1 slow close in 150 (p99 2.5 s; a p99.5 would fire) and no close at
    # all (NaN). 2 slow closes in 180 put the p99 at 5.5 s (a p98.5 would not fire). Each rank is
    # at least 0.2 of a close from a bucket count, so rounding cannot flip a case.
    "AuthRevocationLatencyHigh": (
        ("6m", True, _closes(0, 0, 1)),
        ("9h49m", True, _closes(0, 0, 1)),
        ("9h52m", False, _closes(0, 0, 1)),
        ("10m", False, _closes(0, 1, 0)),
        ("10m", False, _closes(149, 0, 1)),
        ("10m", True, _closes(178, 0, 2)),
        ("10m", False, _closes(0, 0, 0)),
    ),
    # #3635 (#3497): the failed-close counter, one series for the hub's closes and the registry's. A
    # ticket with no `for`: fires on the first evaluation after the step, is held as the tickets
    # above are (firing at 9 h 49 m, resolved at 9 h 52 m), and a flat count is an old failure.
    "WsRevocationCloseFailed": (
        ("6m", True, {_CLOSE_FAILED: _RISE}),
        ("9h49m", True, {_CLOSE_FAILED: _RISE}),
        ("9h52m", False, {_CLOSE_FAILED: _RISE}),
        ("30m", False, {_CLOSE_FAILED: _FLAT}),
    ),
    # #837. Pages: down after it was up, and still at 20 min, when the counter's 5 m window has
    # moved on; a down that recovered between two scrapes (the counter alone). Silent: back up and
    # the window moved on; never connected since boot; degraded.
    "AccountDown": (
        ("10m", True, {_DOWN: _STAYS_DOWN, _INTO_DOWN: _STAYS_DOWN}),
        ("20m", True, {_DOWN: _STAYS_DOWN, _INTO_DOWN: _STAYS_DOWN}),
        ("8m", True, {_DOWN: _ZERO, _INTO_DOWN: _STAYS_DOWN}),
        ("17m", False, {_DOWN: _BACK_UP, _INTO_DOWN: _STAYS_DOWN}),
        ("10m", False, {_NEVER: "1+0x25", _DOWN: _ZERO, _INTO_DOWN: _ZERO}),
        ("10m", False, {_SILENT: _STAYS_DOWN, _DOWN: _ZERO, _INTO_DOWN: _ZERO}),
    ),
    # #837: the any-event ticket of #3029 above, on one state's notices; the other state's are
    # silent, as is a flat count.
    "KeyRotationWarn": (
        ("6m", True, {_WARN: _RISE}),
        ("9h49m", True, {_WARN: _RISE}),
        ("9h52m", False, {_WARN: _RISE}),
        ("30m", False, {_WARN: _FLAT}),
        ("6m", False, {_WARN: _ZERO, _OVERDUE: _RISE}),
    ),
    # #914 (BQ-12): a rise, or a first sample with none an hour before, tickets at once and holds
    # through the quiet hours (the hour's window and 9 h 30 m), then resolves; another reason's
    # rows are silent, and so is a count already held an hour before, once its first hold ends.
    "BybitRowsRefusedAccount": (
        ("6m", True, {_ACCOUNT_ROWS: _RISE}),
        ("10h", True, {_ACCOUNT_ROWS: _RISE}),
        ("11h", False, {_ACCOUNT_ROWS: _RISE}),
        ("6m", True, {_ACCOUNT_ROWS: _FIRST_ROW}),
        ("6m", False, {_ENV_ROWS: _RISE}),
        ("11h", False, {_ACCOUNT_ROWS: _FLAT}),
    ),
    # #837: the same; resolved between two daily counts (20 h), fired again by the next (24 h 7 m).
    "KeyRotationOverdue": (
        ("6m", True, {_OVERDUE: _RISE}),
        ("9h49m", True, {_OVERDUE: _RISE}),
        ("9h52m", False, {_OVERDUE: _RISE}),
        ("20h", False, {_OVERDUE: _A_DAY_APART}),
        ("1447m", True, {_OVERDUE: _A_DAY_APART}),
        ("6m", False, {_OVERDUE: _ZERO, _WARN: _RISE}),
    ),
    # #836: a latch fires and holds until the restart that rebinds the gauge at 0. While a key
    # fails it is quiet (KeySelfCheckFailed fires); once that key passes, the latch fires again.
    "KeySelfCheckLatched": (
        ("5m", True, {_LATCH: "0+0x2 1+0x10"}),
        ("5m", False, {_LATCH: "1+0x10", _FAILING.format(_WD): "1+0x10"}),
        ("10m", True, {_LATCH: "1+0x20", _FAILING.format(_WD): "1+0x4 0+0x15"}),
        ("10m", False, {_LATCH: "1+0x4 0+0x15"}),  # the restart
    ),
    # #3009 S4a. A stopped lane or a refusal fires; a held lane's refusals are AuditLaneDrainHeld's.
    # A healthy lane (not stopped, nothing refused) is silent; a refusal holds 9 h 30 m past the
    # window, as the other held rules (S4A2-C2, S4A2-N2).
    "AuditLaneRefusing": (
        ("10m", True, {_STATE.format("stopped"): _RISE}),
        ("10m", True, {_REFUSED.format("full"): _RISE}),
        ("10m", False, {_STATE.format("held"): _RISE, _REFUSED.format("held"): _RISE}),
        ("10m", False, {_STATE.format(x): f"{int(x == 'open')}+0x20" for x in ("stopped", "open")}),
        ("10m", False, {_REFUSED.format("full"): "0+0x20"}),
        ("9h49m", True, {_REFUSED.format("full"): _RISE}),
        ("9h52m", False, {_REFUSED.format("full"): _RISE}),
    ),
    # A critical anomaly is AuditLaneAnomaly's, a torn tail alone AuditLaneTornTail's. One a boot's
    # scan counted fires after a restart gap or with no history; a young process at 0 is silent,
    # and an old one once its 15 minutes and the hold have passed.
    "AuditLaneAnomaly": (
        ("10m", True, {_ANOMALY.format("frame_rejected"): _RISE}),
        ("10m", False, {_ANOMALY.format("torn_tail"): _RISE}),
        ("45m", True, {_BOOTED.format("frame_rejected"): _GAP, _START: _GAP_START}),
        ("40m", True, {_BOOTED.format("seq_gap"): _FIRST, _START: _FIRST_START}),
        ("10m", False, {_BOOTED.format("frame_rejected"): "0+0x20", _START: "0+0x20"}),
        ("45m", False, {_BOOTED.format("torn_tail"): _GAP, _START: _GAP_START}),
        ("10h", False, {_BOOTED.format("frame_rejected"): "1+0x700", _START: "0+0x700"}),
        ("9h49m", True, {_ANOMALY.format("frame_rejected"): _RISE}),
        ("9h52m", False, {_ANOMALY.format("frame_rejected"): _RISE}),
    ),
    "AuditLaneTornTail": (
        ("10m", True, {_ANOMALY.format("torn_tail"): _RISE}),
        ("10m", False, {_ANOMALY.format("frame_rejected"): _RISE}),
        ("45m", True, {_BOOTED.format("torn_tail"): _GAP, _START: _GAP_START}),
        ("10m", False, {_BOOTED.format("torn_tail"): "0+0x20", _START: "0+0x20"}),
        ("9h49m", True, {_ANOMALY.format("torn_tail"): _RISE}),
        ("9h52m", False, {_ANOMALY.format("torn_tail"): _RISE}),
    ),
    # Frame 1 fires while its process is young: the first boot, and a re-creation by the process
    # after the creator, four minutes on (SR-S4A2-02). A process that made its lane is quiet once
    # its 15 minutes and the 9 h 30 m hold have passed; a young one that made none never fires.
    "AuditLaneCreated": (
        ("5m", True, {_CREATED: "1+0x700", _START: "0+0x700"}),
        ("610m", True, {_CREATED: "1+0x600 _x4 1+0x30", _START: "0+0x600 _x4 36300+0x30"}),
        ("10h", False, {_CREATED: "1+0x700", _START: "0+0x700"}),
        ("10m", False, {_CREATED: "0+0x30", _START: "0+0x30"}),
    ),
    # #1016 (E40-T04). Another topic's backlog is its owner's rule, not this one.
    "AlertOutboxBacklog": (("10m", False, {_DEPTH_OTHER: "101+0x20"}),),
    # #1016 (E40-T04): a dead-lettered alert.deliver row. A ticket with no `for`: fires on the first
    # evaluation after the step and is held past the quiet-hours mute (firing at 9 h 49 m,
    # resolved at 9 h 52 m), as the tickets above; a flat count is an old dead row, and another
    # topic's dead rows are not this rule's.
    "AlertOutboxDeadLettered": (
        ("6m", True, {_DEAD: _RISE}),
        ("9h49m", True, {_DEAD: _RISE}),
        ("9h52m", False, {_DEAD: _RISE}),
        ("30m", False, {_DEAD: _FLAT}),
        ("6m", False, {_DEAD_OTHER: _RISE}),
    ),
}

#: alert -> cases of (eval_time, {series: values}, the `rule` of each alert expected): #836's
#: failing-key alert fires once per failing rule, for every rule, and never for a rule at 0.
BY_RULE: dict[str, tuple[tuple[str, dict[str, str], tuple[str, ...]], ...]] = {
    "KeySelfCheckFailed": (
        ("5m", {_FAILING.format(_WD): "0+0x2 1+0x10"}, (_WD,)),
        ("5m", {_FAILING.format(_NA): "1+0x10", _FAILING.format(_IP): "2+0x10"}, (_IP, _NA)),
        ("10m", {_FAILING.format(_WD): "1+0x4 0+0x10"}, ()),  # fixed
    ),
}

_DAILY = 'cv_backup_last_success_age_seconds{env="live",kind="pg_dump"}'
_CONFIG = 'cv_backup_last_success_age_seconds{env="live",kind="config_bundle"}'
_BOOT_STEP = 'cv_audit_signing_key_boot_failures_total{{env="live",step="{}"}}'
# alert -> cases of (series, values, eval_time, fires, labels the alert keeps from its series).
LABELLED: dict[str, tuple[tuple[str, str, str, bool, dict[str, str]], ...]] = {
    # #889 S6b-2: a failed step fires at the first evaluation after it, by its `step`, and is held
    # as UserLifecycleStepFailed is (firing at 9 h 49 m, resolved at 9 h 52 m); an old failure
    # (a flat count) never fires.
    "AuditSigningKeyBootStepFailed": (
        (_BOOT_STEP.format("destroy"), _RISE, "6m", True, {"env": "live", "step": "destroy"}),
        (_BOOT_STEP.format("rewrap"), _RISE, "9h49m", True, {"env": "live", "step": "rewrap"}),
        (_BOOT_STEP.format("rewrap"), _RISE, "9h52m", False, {"env": "live", "step": "rewrap"}),
        (_BOOT_STEP.format("destroy"), _FLAT, "6m", False, {"env": "live", "step": "destroy"}),
    ),
    # #966 Q16: over 26 h (93600 s) for a daily kind, over 8 days (691200 s) for config_bundle,
    # held 15 min. Each age starts 20 min under its line and grows 60 s a minute, so it is over
    # from 21 min: silent at 35 min, firing at 36. config_bundle there is over 26 h, and silent.
    "BackupLastSuccessStale": (
        (_DAILY, "92400+60x40", "35m", False, {"env": "live", "kind": "pg_dump"}),
        (_DAILY, "92400+60x40", "36m", True, {"env": "live", "kind": "pg_dump"}),
        (_CONFIG, "690000+60x40", "35m", False, {"env": "live", "kind": "config_bundle"}),
        (_CONFIG, "690000+60x40", "36m", True, {"env": "live", "kind": "config_bundle"}),
    ),
}

# alert -> [(values, eval_time, fires)]: more cases on the same series (`_xN`: N missed scrapes).
# #2668 G1: rate(...[1m]) needs samples under a minute apart, so these cases sample every 30 s.
# The configured share is 0.25, so the threshold is 0.3 loop seconds per second: 10 per 30 s fires
# (0.333), 8.5 per 30 s (0.283), a missing share gauge (replay not wired) and the same 10 per 30 s
# against a configured 0.5 (threshold 0.6) stay quiet.
_LOOP, _SHARE = 'replay_loop_seconds_total{env="live"}', 'replay_loop_share_ratio{env="live"}'
FINE: dict[str, tuple[tuple[str, bool, dict[str, str]], ...]] = {
    "ReplayLoopShareHigh": (
        ("10m", True, {_LOOP: "0+10x40", _SHARE: "0.25x40"}),
        ("10m", False, {_LOOP: "0+8.5x40", _SHARE: "0.25x40"}),
        ("10m", False, {_LOOP: "0+10x40"}),
        ("10m", False, {_LOOP: "0+10x40", _SHARE: "0.5x40"}),
    ),
}
EXTRA: dict[str, list[tuple[str, str, bool]]] = {
    # E29-T05 S8b: a condition page, resolved once the reading is handed on and the gauge reads 0.
    "OmsPositionReadingOwed": [("0+0x2 75+0x4 0+0x10", "10m", False)],
    # #2496 item 3: the page rides out a gap shorter than its 15m window (the restart after a
    # break-glass run, a failed scrape) and ends once the last reading of 1 has aged out of it.
    # The gauge is a count: a second unresolved reset (2) pages the same as the first.
    "AuthBreakGlassUsed": [
        ("1+0x4 _x8", "12m", True),
        ("1+0x4 _x25", "25m", False),
        ("2+0x20", "5m", True),
    ],
    # #2496 review. `_xN` is N missed scrapes: the restart after a run is a gap, and the first
    # scrape after it carries the new count. The page rises over what was seen before the gap, ends
    # 15m after the first scrape that shows it, and sees no rise without a sample from before.
    "AuthBreakGlassAttempted": [
        ("0+0x20", "20m", False),  # no run on record
        ("2+0x10 _x20 3+0x10", "35m", True),  # a run while cv-api was stopped, then the restart
        ("2+0x10 _x20 3+0x40", "55m", False),  # 15m on: the window has moved past the rise
        ("_x30 3+0x20", "35m", False),  # no sample from before the run to compare with
    ],
    # #4479 C2: a rise pages as the attempts page does, and so does a first sample above 0, which
    # the attempts page sees no rise in (no sample from before it); each ends 15m after the first
    # scrape that shows the count. A bootstrapped database seen through an outage stays silent.
    "AuthOwnerBootstrapped": [
        ("_x30 1+0x20", "35m", True),  # Prometheus first scrapes cv-api after the redemption
        ("_x30 1+0x40", "50m", False),  # 15m on: the first sample is now in the older window
        ("0+0x10 1+0x40", "40m", False),  # 15m after the rise
        ("1+0x10 _x30 1+0x10", "45m", False),  # cv-api down half an hour on a bootstrapped db
    ],
    # #2496 review: a Postgres restart of two minutes is six failed statements (three a minute
    # since #4479 C2), under 10.
    # #3215: the threshold from both sides, 9 failures in the window (silent) and 10 (fires). Each
    # is a step up from a flat 0, so the 15m `increase` is the step itself and nothing is
    # extrapolated, whether or not Prometheus counts the window's first sample.
    "AuthBreakGlassStateReadFailing": [
        ("0+0x5 4+0x14", "15m", False),
        ("0+0x5 9+0x14", "15m", False),
        ("0+0x5 10+0x14", "15m", True),
    ],
    # #3009 S4a: a lower head after a restart gap of 30 minutes is a drop too; an operator
    # removing copies from `quarantine/` is no growth.
    "AuditLaneSeqRegressed": [("10+1x10 _x30 3+1x10", "55m", True)],
    # S4A2-N2: each held rule fires to the end of its hold and not past it; a backlog that
    # drained at 15 min holds until 9 h 45 m (SR-S4A2-04), growth seen until 70 min until 10 h 40 m.
    "AuditSinkRefusing": [("0+0x5 1+0x700", "9h49m", True), ("0+0x5 1+0x700", "9h52m", False)],
    "AuditLaneBacklogAged": [
        ("0+60x14 0+0x700", "9h44m", True),
        ("0+60x14 0+0x700", "9h47m", False),
    ],
    "AuditLaneQuarantineGrowing": [
        ("400+0x10 0+0x20", "20m", False),
        ("100+0x10 400+0x700", "10h39m", True),
        ("100+0x10 400+0x700", "10h42m", False),
    ],
    # #1016 (E40-T04): the 5 minute `for` from both sides (the series is over from the first
    # scrape, so 4 m is pending and 6 m fires), and a backlog that cleared at 10 minutes is no
    # longer firing at 20: a condition ticket carries no hold, unlike the event tickets.
    "AlertOutboxBacklog": [
        ("101+0x20", "4m", False),
        ("101+0x20", "6m", True),
        ("101+0x10 0+0x10", "20m", False),
    ],
}


def labels_of(name: str) -> dict[str, str]:
    for f in (PROM / "alerts" / rules for rules in RULE_FILES):
        for g in yaml.safe_load(f.read_text(encoding="utf-8"))["groups"]:
            for r in g["rules"]:
                if r["alert"] == name:
                    return dict(r["labels"])
    raise KeyError(name)


def annotations_of(name: str) -> dict[str, str]:
    for f in (PROM / "alerts" / rules for rules in RULE_FILES):
        for g in yaml.safe_load(f.read_text(encoding="utf-8"))["groups"]:
            for r in g["rules"]:
                if r["alert"] == name:
                    return {k: str(v) for k, v in r.get("annotations", {}).items()}
    raise KeyError(name)


def build() -> dict[str, Any]:
    tests: list[dict[str, Any]] = []
    for name, (series, fire, ok, at, extra) in SPEC.items():
        exp = {**labels_of(name), **extra}
        tests.append(
            {
                "interval": "1m",
                "input_series": [{"series": series, "values": fire}],
                "alert_rule_test": [
                    {
                        "eval_time": at,
                        "alertname": name,
                        "exp_alerts": [{"exp_labels": exp, "exp_annotations": annotations_of(name)}],
                    }
                ],
            }
        )
        tests.append(
            {
                "interval": "1m",
                "input_series": [{"series": series, "values": ok}],
                "alert_rule_test": [
                    {"eval_time": at, "alertname": name, "exp_alerts": []}
                ],
            }
        )
        for values, when, fires in EXTRA.get(name, []):
            expected = (
                [{"exp_labels": dict(exp), "exp_annotations": annotations_of(name)}]
                if fires
                else []
            )
            tests.append(
                {
                    "interval": "1m",
                    "input_series": [{"series": series, "values": values}],
                    "alert_rule_test": [
                        {"eval_time": when, "alertname": name, "exp_alerts": expected}
                    ],
                }
            )
    for name, cases in MULTI.items():
        for at, fires, case_series in cases:
            labels, notes = {**labels_of(name), "env": "live"}, annotations_of(name)
            expected = [{"exp_labels": labels, "exp_annotations": notes}] if fires else []
            tests.append(
                {
                    "interval": "1m",
                    "input_series": [{"series": s, "values": v} for s, v in case_series.items()],
                    "alert_rule_test": [
                        {"eval_time": at, "alertname": name, "exp_alerts": expected}
                    ],
                }
            )
    for name, fine in FINE.items():
        for at, fires, case_series in fine:
            labels, notes = {**labels_of(name), "env": "live"}, annotations_of(name)
            expected = [{"exp_labels": labels, "exp_annotations": notes}] if fires else []
            tests.append(
                {
                    "interval": "30s",
                    "input_series": [{"series": k, "values": v} for k, v in case_series.items()],
                    "alert_rule_test": [
                        {"eval_time": at, "alertname": name, "exp_alerts": expected}
                    ],
                }
            )
    for name, labelled in LABELLED.items():
        for series, values, at, fires, kept in labelled:
            alert = {
                "exp_labels": {**labels_of(name), **kept},
                "exp_annotations": annotations_of(name),
            }
            tests.append(
                {
                    "interval": "1m",
                    "input_series": [{"series": series, "values": values}],
                    "alert_rule_test": [
                        {"eval_time": at, "alertname": name, "exp_alerts": [alert] if fires else []}
                    ],
                }
            )
    for name, by_rule in BY_RULE.items():
        for at, case_series, rules in by_rule:
            labels, notes = {**labels_of(name), "env": "live"}, annotations_of(name)
            expected = [
                {"exp_labels": {**labels, "rule": rule}, "exp_annotations": dict(notes)}
                for rule in rules
            ]
            tests.append(
                {
                    "interval": "1m",
                    "input_series": [{"series": s, "values": v} for s, v in case_series.items()],
                    "alert_rule_test": [
                        {"eval_time": at, "alertname": name, "exp_alerts": expected}
                    ],
                }
            )
    return {
        "rule_files": [f"../alerts/{rules}" for rules in RULE_FILES],
        "evaluation_interval": "1m",
        "tests": tests,
    }


if __name__ == "__main__":
    out = PROM / "tests" / "system_alerts.test.yml"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        "# promtool test rules (E04-T05). Generated by infra/alertmanager/gen_promtool_tests.py.\n"
        + yaml.safe_dump(build(), sort_keys=False),
        encoding="utf-8",
    )
