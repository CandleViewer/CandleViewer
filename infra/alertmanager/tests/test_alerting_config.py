"""E04-T05: alert rules, routing config and lint-gate contract tests (no network)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

HERE = Path(__file__).resolve().parents[1]
INFRA = HERE.parent


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lint = _load("check_alert_rules")
AM: dict[str, Any] = yaml.safe_load(
    (HERE / "alertmanager.yml").read_text(encoding="utf-8")
)


def _rules() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in (INFRA / "prometheus" / "alerts").glob("*.yml"):
        for g in yaml.safe_load(f.read_text(encoding="utf-8"))["groups"]:
            out += [r for r in g["rules"] if "alert" in r]
    return out


def _bad_rule(tmp_path: Path, labels: str, annotations: str) -> list[str]:
    (tmp_path / "x.yml").write_text(
        "groups:\n- name: g\n  rules:\n  - alert: Bad\n    expr: up == 0\n"
        f"    labels: {labels}\n    annotations: {annotations}\n",
        encoding="utf-8",
    )
    result: list[str] = lint.check(tmp_path, "# x")
    return result


def test_repo_rules_pass_runbook_lint() -> None:
    assert lint.check() == []


def test_missing_runbook_fails_naming_rule(tmp_path: Path) -> None:
    assert _bad_rule(tmp_path, "{severity: page, component: c}", "{}") == [
        "Bad: missing annotations.runbook_url"
    ]


def test_bad_anchor_and_severity_fail(tmp_path: Path) -> None:
    errs = _bad_rule(
        tmp_path,
        "{severity: warning, component: c}",
        "{runbook_url: 'docs/plan/07-release-and-prr.md#nope'}",
    )
    assert any("severity" in e for e in errs) and any("anchor" in e for e in errs)


def test_only_two_severities() -> None:
    sev = {r["labels"]["severity"] for r in _rules()}
    assert sev <= {"page", "ticket", "none"}
    assert {r["alert"] for r in _rules() if r["labels"]["severity"] == "none"} == {
        "Watchdog"
    }


def test_required_rules_present() -> None:
    names = {r["alert"] for r in _rules()}
    required = {
        "NakedPositionDetected",
        "OmsUnknownOrders",
        "PostgresDown",
        "DiskCritical",
        "DiskHigh",
        "Watchdog",
        "AlertmanagerNotificationsFailed",
        "SyntheticAlert",
        "AuditChainVerificationFailed",
        "EgressIpChanged",
    }
    assert required <= names


def test_oms_unknown_orders_for_60s() -> None:
    r = next(r for r in _rules() if r["alert"] == "OmsUnknownOrders")
    assert r["for"] == "1m"


def test_absent_guards_are_ticket() -> None:
    guards = [r for r in _rules() if r["alert"].startswith("ExpectedMetricMissing")]
    assert guards and all(g["expr"].startswith("absent(") for g in guards)
    assert all(g["labels"]["severity"] == "ticket" for g in guards)


def test_promtool_cases_cover_every_new_page_rule() -> None:
    doc = yaml.safe_load(
        (INFRA / "prometheus" / "tests" / "system_alerts.test.yml").read_text(
            encoding="utf-8"
        )
    )
    covered = {a["alertname"] for t in doc["tests"] for a in t["alert_rule_test"]}
    extra = yaml.safe_load(
        (INFRA / "prometheus" / "tests" / "ingestion_alerts.test.yml").read_text(encoding="utf-8")
    )
    covered |= {a["alertname"] for t in extra["tests"] for a in t["alert_rule_test"]}
    page = {r["alert"] for r in _rules() if r["labels"]["severity"] == "page"}
    assert page - {"BybitClockDriftCritical"} <= covered


def test_grouping_and_repeat_intervals() -> None:
    r = AM["route"]
    assert r["group_by"] == ["alertname", "component", "env"]
    assert (r["group_wait"], r["group_interval"], r["repeat_interval"]) == (
        "30s",
        "5m",
        "4h",
    )
    by = {x["matchers"][0]: x for x in r["routes"]}
    assert by['severity = "page"']["repeat_interval"] == "30m"


def test_page_bypasses_quiet_hours_ticket_muted() -> None:
    by = {x["matchers"][0]: x for x in AM["route"]["routes"]}
    assert "mute_time_intervals" not in by['severity = "page"']
    assert by['severity = "ticket"']["mute_time_intervals"] == ["quiet_hours"]
    assert {t["name"] for t in AM["time_intervals"]} == {"quiet_hours"}


def test_receivers_exist_and_no_inline_secret() -> None:
    recv = {r["name"] for r in AM["receivers"]}
    assert all(x["receiver"] in recv for x in AM["route"]["routes"])
    text = (HERE / "alertmanager.yml").read_text(encoding="utf-8")
    assert "http://" not in text and "https://" not in text
    assert text.count("url_file:") == 3
    assert "alert_page_webhook_url" in text and "alert_ticket_webhook_url" in text


def _pg_rule() -> dict[str, Any]:
    return next(
        r
        for r in AM["inhibit_rules"]
        if r["source_matchers"] == ['alertname = "PostgresDown"']
    )


def _inhibited(component: str) -> bool:
    import re

    labels = {"severity": "ticket", "component": component}
    for m in _pg_rule()["target_matchers"]:
        k, op, v = re.match(r'(\w+)\s*(=~|=)\s*"?([^"]*)"?$', m).groups()  # type: ignore[union-attr]
        ok = re.fullmatch(v, labels.get(k, "")) if op == "=~" else labels.get(k) == v
        if not ok:
            return False
    return True


def test_postgres_inhibits_db_dependent_tickets() -> None:
    for c in ("storage", "oms", "rules", "book", "audit"):
        assert _inhibited(c), c


def test_postgres_does_not_inhibit_security_tickets() -> None:
    for c in ("auth", "secrets", "network", "clock"):
        assert not _inhibited(c), c


def test_alert_drill_refuses_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    m = _load("alert_drill")
    monkeypatch.setenv("CV_ALERT_DRILL_PUSH_URL", "http://evil.example.com")
    assert m.main(["fire"]) == 2
    assert m.build_request("http://127.0.0.1:9091", 1).data == b"cv_synthetic_alert 1\n"


def test_grouped_notifications_never_truncated_and_page_ticket_distinct() -> None:
    recv = {r["name"]: r["slack_configs"][0] for r in AM["receivers"] if "slack_configs" in r}
    assert recv["page"]["api_url_file"] != recv["ticket"]["api_url_file"]
    for r in recv.values():
        assert r["title"] == '{{ template "cv.title" . }}' and r["text"] == '{{ template "cv.body" . }}'
    assert "max_alerts" not in str(AM["receivers"])  # nothing truncates a grouped notification


def test_compose_wires_secrets_pushgateway_and_scrape() -> None:
    dc = yaml.safe_load(
        (INFRA / "compose" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    for name in (
        "alert_page_webhook_url",
        "alert_ticket_webhook_url",
        "alert_deadman_url",
    ):
        assert (
            name in dc["secrets"] and name in dc["services"]["alertmanager"]["secrets"]
        )
    assert "pushgateway" in dc["services"]
    prom = yaml.safe_load(
        (INFRA / "prometheus" / "prometheus.yml").read_text(encoding="utf-8")
    )
    assert any(
        "pushgateway:9091" in j["static_configs"][0]["targets"]
        for j in prom["scrape_configs"]
    )


def test_alert_drill_push_is_received(monkeypatch: pytest.MonkeyPatch) -> None:
    import http.server
    import threading

    got: list[tuple[str, bytes]] = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_PUT(self) -> None:
            got.append(
                (self.path, self.rfile.read(int(self.headers["Content-Length"])))
            )
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a: object) -> None:
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("CV_ALERT_DRILL_PUSH_URL", f"http://127.0.0.1:{srv.server_port}")
    m = _load("alert_drill")
    assert m.main(["fire"]) == 0 and m.main(["stop"]) == 0
    srv.shutdown()
    assert got[0][1] == b"cv_synthetic_alert 1\n"
    assert got[1][1] == b"cv_synthetic_alert 0\n"
    assert got[0][0].startswith("/metrics/job/alert_drill")
