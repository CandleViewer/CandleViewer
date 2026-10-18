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
# #965 R7: a disable whose store raised (`result` `error`; a refusal is another result).
_ERRORED = 'cv_user_lifecycle_total{action="disable",env="live",result="error"}'

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
}

_LAST_OK = 'cv_audit_verify_last_ok_timestamp_seconds{env="live"}'
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


def _closes(fast: int, under_5: int, slow: int) -> dict[str, str]:
    """#3415: revocations at 6 min whose sockets closed in at most 2.5 s (`fast`), in 2.5 to 5 s
    (`under_5`) and in 5 to 10 s (`slow`), as cumulative buckets; lower edges add nothing here."""
    counts = {"2.5": fast, "5.0": fast + under_5, "10.0": fast + under_5 + slow}
    counts["+Inf"] = counts["10.0"]
    return {_LATENCY.format(le): f"0+0x5 {n}+0x700" for le, n in counts.items()}


# alert -> cases of (eval_time, fires, {series: values}) over several `env="live"` series.
MULTI: dict[str, tuple[tuple[str, bool, dict[str, str]], ...]] = {
    # #2111. Pages: last pass at 5 min; runs that keep stopping across the restart. Healthy: no
    # runner wired (0); a pass at 26 h, after the restart.
    # The 26 h threshold is 24 h (the daily run) + 5400 s (the longest deadline it covers; a longer
    # one needs the threshold raised, 24-internal-schemas.md section 15.4) + 30 min. A pass at 1 h
    # pins it from both sides: 25 h 30 min old (24 h + 5400 s, a healthy cadence at its slowest)
    # does not page, 26 h 1 min old does.
    "AuditVerifyNotPassing": (
        ("28h", True, {_LAST_OK: "300+0x1700"}),
        ("28h", True, {**_RESTART, _PASSED: "0+0x1685"}),
        ("28h", False, {_LAST_OK: "0+0x1700"}),
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
}

# alert -> [(values, eval_time, fires)]: more cases on the same series (`_xN`: N missed scrapes).
EXTRA: dict[str, list[tuple[str, str, bool]]] = {
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
    # #2496 review: a Postgres restart of two minutes is four failed statements, far under 10.
    # #3215: the threshold from both sides, 9 failures in the window (silent) and 10 (fires). Each
    # is a step up from a flat 0, so the 15m `increase` is the step itself and nothing is
    # extrapolated, whether or not Prometheus counts the window's first sample.
    "AuthBreakGlassStateReadFailing": [
        ("0+0x5 4+0x14", "15m", False),
        ("0+0x5 9+0x14", "15m", False),
        ("0+0x5 10+0x14", "15m", True),
    ],
}


def labels_of(name: str) -> dict[str, str]:
    for f in sorted((PROM / "alerts").glob("system_*.yml")):
        for g in yaml.safe_load(f.read_text(encoding="utf-8"))["groups"]:
            for r in g["rules"]:
                if r["alert"] == name:
                    return dict(r["labels"])
    raise KeyError(name)


def annotations_of(name: str) -> dict[str, str]:
    for f in sorted((PROM / "alerts").glob("system_*.yml")):
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
    return {
        "rule_files": ["../alerts/system_page.yml", "../alerts/system_ticket.yml"],
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
