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
}

_LAST_OK = 'cv_audit_verify_last_ok_timestamp_seconds{env="live"}'
_STOPPED = 'cv_audit_verify_runs_total{env="live",result="stopped"}'
_PASSED = 'cv_audit_verify_runs_total{env="live",result="ok"}'
# A restart at 24 h re-seeds the gauge and resets the counter; start-up runs stop on each side.
_RESTART = {_LAST_OK: "60+0x1439 86400+0x245", _STOPPED: "0+0x4 1+0x1434 0+0x4 1+0x240"}
_PASS_AT_26H = {_LAST_OK: "60+0x1439 86400+0x119 93600+0x125", _PASSED: "0+0x1559 1+0x125"}
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
