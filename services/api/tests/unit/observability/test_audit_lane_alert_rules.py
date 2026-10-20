"""ADR-0037 S4a (#3009): the journal-first audit lane's alert rules. Each rule reads a catalogued
series, is a ticket under its own components (`audit_lane`, `audit_sink`; PostgresDown's
inhibition matches `audit`), names its runbook, is in the drill matrix and has promtool cases that
fire and that stay silent (promtool runs in CI, not here). ADR-0037 makes seven of them pages: a
new page needs the Owner (#2701), so each says so above its expression. An event rule holds past
the quiet hours (`keep_firing_for`), as the WS any-event tickets do."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from candleviewer.observability.metrics_catalogue import CATALOGUE

_ROOT = Path(__file__).resolve().parents[5]
_RULES = _ROOT / "infra" / "prometheus" / "alerts" / "system_ticket.yml"
_CASES = _ROOT / "infra" / "prometheus" / "tests" / "system_alerts.test.yml"
_MATRIX = _ROOT / "qa" / "plans" / "e04-alert-drill-matrix.md"
_PENDING = "# page promotion pending owner approval (#2701; ADR-0037 lists it as a page)"
_PRR = "docs/plan/07-release-and-prr.md#alert-"
#: alert -> (anchor, held past the quiet hours, a page in ADR-0037)
LANE: dict[str, tuple[str, bool, bool]] = {
    "AuditSinkRefusing": ("auditsinkrefusing", True, True),
    "AuditLaneBacklogAged": ("auditlanebacklogaged", True, True),  # SR-S4A2-04
    "AuditLaneRefusing": ("auditlanerefusing", True, True),
    "AuditLaneDrainHeld": ("auditlanerefusing", False, True),
    "AuditLaneBootOvershoot": ("auditlanerefusing", False, False),
    "AuditLaneAnomaly": ("auditlaneanomaly", True, True),
    "AuditLaneTornTail": ("auditlaneanomaly", True, False),
    "AuditLaneQuarantineGrowing": ("auditlaneanomaly", True, False),
    "AuditLaneSeqRegressed": ("auditlaneseqregressed", False, True),
    "AuditLaneCreated": ("auditlaneseqregressed", True, True),
}


def _rules() -> dict[str, dict[str, Any]]:
    (group,) = yaml.safe_load(_RULES.read_text(encoding="utf-8"))["groups"]
    return {r["alert"]: r for r in group["rules"] if r["alert"] in LANE}


def test_each_lane_alert_is_a_ticket_with_its_runbook_and_its_quiet_hours_hold() -> None:
    rules = _rules()
    assert set(rules) == set(LANE)
    for name, (anchor, held, _) in LANE.items():
        rule = rules[name]
        component = "audit_sink" if name == "AuditSinkRefusing" else "audit_lane"
        assert rule["labels"] == {"severity": "ticket", "component": component}, name
        assert rule["annotations"]["runbook_url"] == _PRR + anchor, name
        assert (rule["for"], rule.get("keep_firing_for")) == ("0m", "9h30m" if held else None), name


def test_each_page_of_adr_0037_says_its_promotion_waits_for_the_owner() -> None:
    text = _RULES.read_text(encoding="utf-8")
    for name, (_, _, page) in LANE.items():
        block = text[text.index(f"- alert: {name}\n") :].split("- alert: ")[1]
        assert (_PENDING in block) == page, name


def test_each_rule_reads_catalogued_lane_series_that_name_it() -> None:
    specs = {s.name: s for s in CATALOGUE}
    for name, rule in _rules().items():
        series = set(re.findall(r"cv_audit_(?:lane|writer)_[a-z_]+", rule["expr"]))
        assert series and all(name in specs[s].alert for s in series), name


def test_each_rule_has_promtool_cases_that_fire_and_stay_silent_and_a_drill_row() -> None:
    doc = yaml.safe_load(_CASES.read_text(encoding="utf-8"))
    matrix = _MATRIX.read_text(encoding="utf-8")
    cases = [c for t in doc["tests"] for c in t["alert_rule_test"]]
    for name in LANE:
        fired = {bool(c["exp_alerts"]) for c in cases if c["alertname"] == name}
        assert fired == {True, False}, name
        assert re.search(rf"^\| {name} \| ticket \|", matrix, re.MULTILINE), name


def test_each_count_a_boot_sets_is_read_while_its_process_is_young() -> None:
    """SR-S4A2-01, -02: a boot's scan counts its anomaly rows, and frame 1 its creation, before
    the first scrape, so after a restart gap no `increase()` sees them. Those rules also read the
    count while the process is under 15 minutes old; the promtool cases pin how they fire."""
    young = "and on (job, instance) (time() - process_start_time_seconds < 900)"
    read = {name for name, rule in _rules().items() if young in " ".join(rule["expr"].split())}
    assert read == {"AuditLaneAnomaly", "AuditLaneTornTail", "AuditLaneCreated"}
