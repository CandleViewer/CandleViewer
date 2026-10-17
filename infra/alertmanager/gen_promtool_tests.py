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
    # #2496 item 3 (SR-023): the first scrape after the restart that follows a break-glass run
    # already reads 1 (the start-up read runs before cv-api serves), so the series starts at 1.
    "AuthBreakGlassUsed": (
        'auth_break_glass_unresolved_events{env="live"}',
        "1+0x20",
        "0+0x20",
        "5m",
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
