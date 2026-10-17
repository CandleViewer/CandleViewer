"""E04-T05: alert rules, routing config and lint-gate contract tests (no network)."""

from __future__ import annotations

import importlib.util
import re
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
        "AuditVerifyNotPassing",  # #2111 R-5
        "EgressIpChanged",
        "CsrfRefusalsHigh",  # #2090 SR-041
        "CsrfRefusalAuditUnavailable",
        "AuthRecoveryCodeUsed",  # #2496 SR-022
        "NetBindingUnsafe",  # #2496 E09-T04
    }
    assert required <= names


def _reason_matcher(expr: str) -> tuple[str, set[str]]:
    """The one `reason` matcher in a PromQL expression: (operator, alternatives)."""
    found = re.findall(r'reason\s*(=~|!~|!=|=)\s*"([^"]*)"', expr)
    assert len(found) == 1, (expr, found)
    return found[0][0], set(found[0][1].split("|"))


def test_csrf_refusal_alerts_watch_the_bounded_metric() -> None:
    """#2090: the CSRF alerts use the closed-label counter, never a per-path series.
    #2264: matchers are parsed, not searched as substrings, so flipping an operator fails."""
    rules = {r["alert"]: r for r in _rules()}
    names = ("CsrfRefusalsHigh", "CsrfRefusalAuditUnavailable", "CsrfRefusalAuditDegraded")
    for name in names:
        assert "auth_csrf_refused_total" in rules[name]["expr"]
        assert rules[name]["labels"]["severity"] == "ticket"
        assert rules[name]["labels"]["component"] == "auth"
    bookkeeping = {"audit_unavailable", "audit_slow", "audit_throttled", "audit_saturated"}
    assert _reason_matcher(rules["CsrfRefusalsHigh"]["expr"]) == ("!~", bookkeeping)
    unavailable = _reason_matcher(rules["CsrfRefusalAuditUnavailable"]["expr"])
    assert unavailable == ("=", {"audit_unavailable"})
    degraded = _reason_matcher(rules["CsrfRefusalAuditDegraded"]["expr"])
    assert degraded == ("=~", {"audit_slow", "audit_saturated"})


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


#: The child routes by their whole matcher list (see `_routes_by_matchers`).
PAGE_ROUTE = ('severity = "page"',)
EVENT_PAGE_ROUTE = ('severity = "page"', 'resolves = "window"')
TICKET_ROUTE = ('severity = "ticket"',)


def _routes_by_matchers(
    routes: list[dict[str, Any]] | None = None,
) -> dict[tuple[str, ...], dict[str, Any]]:
    """The child routes keyed by their whole matcher list. The event route (#2931) shares its
    first matcher with the generic page route, so keying on `matchers[0]` keeps whichever is
    listed last, and a reorder would make a test check the other route without failing.
    `routes` replaces the configured child routes, to show what a different order would do."""
    listed = AM["route"]["routes"] if routes is None else routes
    by = {tuple(route["matchers"]): route for route in listed}
    assert len(by) == len(listed), "two child routes have the same matchers"
    return by


def test_grouping_and_repeat_intervals() -> None:
    r = AM["route"]
    assert r["group_by"] == ["alertname", "component", "env"]
    assert (r["group_wait"], r["group_interval"], r["repeat_interval"]) == (
        "30s",
        "5m",
        "4h",
    )
    assert _routes_by_matchers()[PAGE_ROUTE]["repeat_interval"] == "30m"


def test_page_bypasses_quiet_hours_ticket_muted() -> None:
    by = _routes_by_matchers()
    assert "mute_time_intervals" not in by[PAGE_ROUTE]
    assert by[TICKET_ROUTE]["mute_time_intervals"] == ["quiet_hours"]
    assert {t["name"] for t in AM["time_intervals"]} == {"quiet_hours"}


def test_route_lookup_by_matchers_does_not_depend_on_route_order() -> None:
    """#2931 review: the generic page route is found by its whole matcher list, so listing the
    event route after it (which `test_event_route_is_listed_before_the_generic_page_route`
    rejects on its own) cannot make the two tests above check the wrong route."""
    routes = AM["route"]["routes"]
    for order in (routes, list(reversed(routes))):
        by = _routes_by_matchers(order)
        assert by[PAGE_ROUTE]["receiver"] == "page"
        assert by[EVENT_PAGE_ROUTE]["receiver"] == "page_event"


def test_route_lookup_by_matchers_refuses_two_routes_with_the_same_matchers() -> None:
    """A duplicated matcher list would silently drop one route from the lookup."""
    duplicated = [*AM["route"]["routes"], dict(AM["route"]["routes"][-1])]
    with pytest.raises(AssertionError, match="same matchers"):
        _routes_by_matchers(duplicated)


def test_receivers_exist_and_no_inline_secret() -> None:
    recv = {r["name"] for r in AM["receivers"]}
    assert all(x["receiver"] in recv for x in AM["route"]["routes"])
    text = (HERE / "alertmanager.yml").read_text(encoding="utf-8")
    assert "http://" not in text and "https://" not in text
    # page, page_event (#2931: the page secret again), ticket, deadman
    assert text.count("url_file:") == 4
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


def test_ws_origin_refusal_alert_watches_the_bounded_close_reason() -> None:
    """#2239: the SR-042 WS Origin alert reads the closed-label close counter (no per-origin
    or per-IP series); a ticket for the auth owner, with its runbook entry."""
    rules = {r["alert"]: r for r in _rules()}
    rule = rules["WsOriginRefusalsHigh"]
    assert 'cv_ws_closes_total{reason="origin_forbidden"}' in rule["expr"]
    assert rule["for"] == "5m"
    assert rule["labels"] == {"severity": "ticket", "component": "auth"}
    url = rule["annotations"]["runbook_url"]
    assert url == "docs/plan/07-release-and-prr.md#alert-wsoriginrefusalshigh"


def _route_for(
    labels: dict[str, str], routes: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """The child route Alertmanager picks for `labels`: the first whose matchers all hold
    (no child route sets `continue`), else the root route. `routes` replaces the configured
    child routes, to show what a different order would do."""
    import re

    for route in AM["route"]["routes"] if routes is None else routes:
        assert not route.get("continue", False)
        pairs = [re.fullmatch(r'(\w+)\s*=\s*"([^"]*)"', m) for m in route["matchers"]]
        assert all(p is not None for p in pairs), route["matchers"]  # equality matchers only
        if all(p is not None and labels.get(p[1]) == p[2] for p in pairs):
            return dict(route)
    return dict(AM["route"])


def test_recovery_code_alert_pages_the_owner_on_any_use_even_in_quiet_hours() -> None:
    """#2496 (SR-022: each use "alerts the Owner"): any accepted recovery code pages at once.
    The alert resolves 15 minutes after a use. On the muted ticket route, one that fires and
    resolves inside quiet hours is never notified (#2660 review), so its route must have no
    mute. Its own component, so the page-over-ticket rule hides none of the `auth` tickets.
    The counter carries no user label; the runbook reads the audit log. #2931: it is an event
    page (`resolves: window`), so it takes the page channel without a [RESOLVED] message."""
    rules = _rules()
    rule = {r["alert"]: r for r in rules}["AuthRecoveryCodeUsed"]
    assert rule["expr"] == "sum by (env) (increase(auth_recovery_codes_used_total[15m])) > 0"
    assert rule["for"] == "0m"
    assert rule["labels"] == {
        "severity": "page",
        "component": "auth_recovery",
        "resolves": "window",
    }
    route = _route_for({**rule["labels"], "alertname": rule["alert"], "env": "live"})
    assert route["receiver"] == "page_event" and "mute_time_intervals" not in route
    url = rule["annotations"]["runbook_url"]
    assert url == "docs/plan/07-release-and-prr.md#alert-authrecoverycodeused"
    assert [r["alert"] for r in rules if r["labels"]["component"] == "auth_recovery"] == [
        "AuthRecoveryCodeUsed"
    ]


#: #2931: pages whose resolution only means "the rate window elapsed", not "someone acted". A
#: [RESOLVED] on the page channel reads as handled although the event still needs the Owner's
#: review, so each carries `resolves: window` and takes the receiver that sends no resolved
#: message. #2496 item 3 (the break-glass use alert) adds itself here with the same label.
#: Each reads `increase(<counter>[window]) > 0`: a recovery code was used; an audit chain
#: verification run failed (the break stands and is found again at the next start-up or nightly
#: run); a trade gap went unrecovered (the trades stay missing from the tape and the recording).
#: Not classified yet: `NakedPositionDetected`. Whether its [RESOLVED] means "protected again"
#: or only "the window moved on" depends on how the E32 watchdog counts
#: `naked_position_alerts_total`: once per detection (an event page), or on every scan while a
#: position is naked (a condition page). TODO(#932): decide there; add it here if it is the former.
EVENT_TYPE_PAGES = {
    "AuditChainVerificationFailed",
    "AuthRecoveryCodeUsed",
    "IngestionTradeGapUnrecovered",
}


def _alert_labels(rule: dict[str, Any]) -> dict[str, str]:
    """The labels Alertmanager routes on for a rule's alert: its rule labels, name and env."""
    return {**rule["labels"], "alertname": rule["alert"], "env": "live"}


def _slack(receiver: str) -> dict[str, Any]:
    """The one Slack config of a receiver."""
    (config,) = next(r for r in AM["receivers"] if r["name"] == receiver)["slack_configs"]
    return dict(config)


def _receiver_without_resolved(name: str) -> dict[str, Any]:
    """A receiver as configured, minus its name and `send_resolved`, the one setting the event
    receiver is meant to change. Every other key, at either level, is kept."""
    receiver = next(r for r in AM["receivers"] if r["name"] == name)
    out = {key: value for key, value in receiver.items() if key != "name"}
    out["slack_configs"] = [
        {key: value for key, value in config.items() if key != "send_resolved"}
        for config in receiver["slack_configs"]
    ]
    return out


def _matcher_holds(matcher: str, labels: dict[str, str]) -> bool:
    """Whether one Alertmanager matcher (`=`, `!=`, `=~`, `!~`) holds for `labels`."""
    parsed = re.fullmatch(r'(\w+)\s*(=~|!~|!=|=)\s*"([^"]*)"', matcher)
    assert parsed is not None, matcher
    key, op, value = parsed.groups()
    actual = labels.get(key, "")
    return {
        "=": actual == value,
        "!=": actual != value,
        "=~": re.fullmatch(value, actual) is not None,
        "!~": re.fullmatch(value, actual) is None,
    }[op]


def test_event_type_page_rules_carry_the_resolves_window_label() -> None:
    """#2931: the label is the only thing that tells an event page from a condition page, so
    the set of rules carrying it is pinned both ways. Every event-type page has it, and no
    condition page (whose [RESOLVED] means the condition cleared) picks it up and loses that
    message. Each reads a rate window, which is what makes its resolution "the window moved on"."""
    rules = {r["alert"]: r for r in _rules()}
    assert {name for name, r in rules.items() if "resolves" in r["labels"]} == EVENT_TYPE_PAGES
    for name in EVENT_TYPE_PAGES:
        assert rules[name]["labels"]["severity"] == "page"
        assert rules[name]["labels"]["resolves"] == "window"
        assert re.search(r"\[\d+[smhdw]\]", rules[name]["expr"]), rules[name]["expr"]


def test_event_type_page_goes_to_the_page_channel_without_a_resolved_message() -> None:
    """#2931: the firing page still reaches the Owner on the page webhook, with the same
    payload template and the same quiet-hours bypass and repeat as every page (SR-022). Only
    the [RESOLVED] message is gone. The whole receiver is compared bar `send_resolved`, so a
    key added to `page` later (a channel, an http_config, a second sink) has to be mirrored,
    and the route sets nothing but its receiver, matchers and repeat."""
    by = _routes_by_matchers()
    generic, event_route = by[PAGE_ROUTE], by[EVENT_PAGE_ROUTE]
    event_rules = [r for r in _rules() if r["alert"] in EVENT_TYPE_PAGES]
    assert {r["alert"] for r in event_rules} == EVENT_TYPE_PAGES
    for rule in event_rules:
        route = _route_for(_alert_labels(rule))
        assert route["receiver"] == "page_event"
        assert "mute_time_intervals" not in route
        assert route["repeat_interval"] == generic["repeat_interval"]
    assert set(event_route) == {"matchers", "receiver", "repeat_interval"}
    assert _slack("page_event")["send_resolved"] is False
    assert _receiver_without_resolved("page_event") == _receiver_without_resolved("page")


def test_pages_not_classified_as_event_pages_keep_their_resolved_notification() -> None:
    """#2931: a page without `resolves: window` keeps `page` and its [RESOLVED]. For a condition
    page (`pg_up == 0`, an unknown-order gauge, the mesh guard) that is right: it resolves
    because the condition cleared, which the Owner wants to read. `NakedPositionDetected` is in
    this group only because it is not classified yet (see EVENT_TYPE_PAGES)."""
    pages = [
        r
        for r in _rules()
        if r["labels"]["severity"] == "page" and r["alert"] not in EVENT_TYPE_PAGES
    ]
    condition_and_unclassified = {
        "PostgresDown",
        "OmsUnknownOrders",
        "NetBindingUnsafe",
        "NakedPositionDetected",
    }
    assert condition_and_unclassified <= {r["alert"] for r in pages}
    for rule in pages:
        assert _route_for(_alert_labels(rule))["receiver"] == "page", rule["alert"]
    assert _slack("page")["send_resolved"] is True


def test_event_route_is_listed_before_the_generic_page_route() -> None:
    """The first matching child route wins and none sets `continue`, so the generic
    `severity = "page"` route listed first would shadow the event route and send every event
    page its [RESOLVED] again."""
    routes = AM["route"]["routes"]
    generic = next(i for i, r in enumerate(routes) if r["matchers"] == ['severity = "page"'])
    event = next(i for i, r in enumerate(routes) if 'resolves = "window"' in r["matchers"])
    assert event < generic
    swapped = list(routes)
    swapped[event], swapped[generic] = swapped[generic], swapped[event]
    for rule in (r for r in _rules() if r["alert"] in EVENT_TYPE_PAGES):
        assert _route_for(_alert_labels(rule), swapped)["receiver"] == "page", rule["alert"]


def test_resolves_label_never_moves_a_ticket_to_the_page_channel() -> None:
    """The lint refuses `resolves` on a ticket; the route backs it up. A ticket that carries
    the label still lands on the ticket channel, muted in quiet hours."""
    route = _route_for({"severity": "ticket", "component": "auth", "resolves": "window"})
    assert route["receiver"] == "ticket"
    assert route["mute_time_intervals"] == ["quiet_hours"]


def test_event_type_page_is_not_a_target_of_any_inhibit_rule() -> None:
    """Security signals are never inhibited (see the PostgresDown rule's comment): no inhibit
    rule can hide an event page, whatever its source."""
    for rule in (r for r in _rules() if r["alert"] in EVENT_TYPE_PAGES):
        labels = _alert_labels(rule)
        for inhibit in AM["inhibit_rules"]:
            hidden = all(_matcher_holds(m, labels) for m in inhibit["target_matchers"])
            assert not hidden, (rule["alert"], inhibit)


def test_resolves_label_lint_accepts_window_on_a_page(tmp_path: Path) -> None:
    labels = "{severity: page, component: c, resolves: window}"
    assert _bad_rule(tmp_path, labels, "{runbook_url: 'docs/plan/07-release-and-prr.md#x'}") == []


def test_resolves_label_lint_rejects_another_value(tmp_path: Path) -> None:
    """A typo would fall through to the generic page route and quietly send the [RESOLVED] again."""
    labels = "{severity: page, component: c, resolves: Window}"
    errs = _bad_rule(tmp_path, labels, "{runbook_url: 'docs/plan/07-release-and-prr.md#x'}")
    assert errs == ["Bad: resolves label must be 'window'"]


def test_resolves_label_lint_rejects_a_ticket(tmp_path: Path) -> None:
    """Only pages have the event route, so on a ticket the label would do nothing."""
    labels = "{severity: ticket, component: c, resolves: window}"
    errs = _bad_rule(tmp_path, labels, "{runbook_url: 'docs/plan/07-release-and-prr.md#x'}")
    assert errs == ["Bad: resolves label is only valid on a page"]


def _promtool_cases() -> list[dict[str, Any]]:
    """Every `alert_rule_test` case of the system and the ingestion promtool test files."""
    cases: list[dict[str, Any]] = []
    for name in ("system_alerts.test.yml", "ingestion_alerts.test.yml"):
        doc = yaml.safe_load((INFRA / "prometheus" / "tests" / name).read_text(encoding="utf-8"))
        cases += [case for test in doc["tests"] for case in test["alert_rule_test"]]
    return cases


def test_promtool_case_for_each_event_page_expects_the_resolves_label() -> None:
    """The system promtool cases are generated from the rules (`gen_promtool_tests.py`) and the
    ingestion ones are written by hand: a rule label added without updating its case fails
    `promtool test rules` in CI, so check both files here."""
    firing = [
        case
        for case in _promtool_cases()
        if case["alertname"] in EVENT_TYPE_PAGES and case["exp_alerts"]
    ]
    assert {case["alertname"] for case in firing} == EVENT_TYPE_PAGES
    for case in firing:
        assert all(alert["exp_labels"]["resolves"] == "window" for alert in case["exp_alerts"])


#: The CI step that runs `amtool config routes test` (E04-T05).
CI_WORKFLOW = INFRA.parent / ".github" / "workflows" / "_job-py.yml"


def _ci_route_cases() -> list[tuple[str, dict[str, str]]]:
    """The cases of the CI loop `for r in "<receiver> <key>=<value> ..." ...; do amtool config
    routes test --verify.receivers=<receiver> <key>=<value> ...`: each as (receiver, labels)."""
    jobs = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    scripts = [
        step["run"]
        for job in jobs.values()
        for step in job.get("steps", [])
        if "config routes test" in step.get("run", "")
    ]
    assert len(scripts) == 1, "one CI step runs the amtool routes test"
    loop = re.search(r"\bfor r in (.*?); do\b", scripts[0], re.DOTALL)
    assert loop is not None, "the routes test loop"
    cases: list[tuple[str, dict[str, str]]] = []
    for word in re.findall(r'"([^"]*)"', loop[1]):
        receiver, *pairs = word.split()
        cases.append((receiver, dict(pair.split("=", 1) for pair in pairs)))
    return cases


def test_ci_routes_test_cases_resolve_to_the_receiver_they_expect() -> None:
    """Only CI can run `amtool config routes test` (it needs docker). The same lookup on the
    configured route tree here (the first matching child route, else the root) shows a case with
    a wrong receiver before the push, not in the `py` lane."""
    cases = _ci_route_cases()
    assert cases, "no routes test case found"
    for receiver, labels in cases:
        assert _route_for(labels)["receiver"] == receiver, (receiver, labels)


def test_ci_routes_test_loop_has_a_page_event_case_for_each_event_page() -> None:
    """#2931: `amtool check-config` accepts a receiver no route uses, and the tests above are a
    local gate, so a case per event page is what fails the `py` lane when the event route is
    deleted, listed below the generic page route, or shadowed by a route added above it. Each
    case carries the labels its rule does (alertname, severity, component and resolves; `env`
    comes from the series, not the rule) and expects `page_event`."""
    cases = _ci_route_cases()
    event_rules = [r for r in _rules() if r["alert"] in EVENT_TYPE_PAGES]
    assert {r["alert"] for r in event_rules} == EVENT_TYPE_PAGES
    for rule in event_rules:
        wanted = ("page_event", {**rule["labels"], "alertname": rule["alert"]})
        assert cases.count(wanted) == 1, rule["alert"]


def _runbook_section(rule: dict[str, Any]) -> str:
    """The runbook text under a rule's `runbook_url` anchor, up to the next anchor."""
    url: str = rule["annotations"]["runbook_url"]
    path, _, anchor = url.partition("#")
    text = (INFRA.parent / path).read_text(encoding="utf-8")
    start = text.index(f'<a id="{anchor}"></a>')
    end = text.find('<a id="', start + 1)
    return text[start:] if end == -1 else text[start:end]


def test_every_event_page_runbook_says_no_resolved_follows_and_to_act_either_way() -> None:
    """#2931: the runbook says what the Owner does after the page, whether or not it has
    resolved. Each event page's section names the missing [RESOLVED] message and says that its
    steps apply whether or not the alert has cleared."""
    for rule in (r for r in _rules() if r["alert"] in EVENT_TYPE_PAGES):
        section = _runbook_section(rule).lower()
        assert "[resolved]" in section, rule["alert"]
        assert "whether or not the alert has cleared" in section, rule["alert"]


def test_net_binding_alert_pages_as_soon_as_the_guard_trips() -> None:
    """#2496 (E09-T04: "an alert that fires immediately when the gauge goes to 0"). The
    component is its own, so this page never inhibits another component's ticket (the
    page-over-ticket rule matches on component), e.g. `EgressIpChanged` (network)."""
    rules = _rules()
    rule = {r["alert"]: r for r in rules}["NetBindingUnsafe"]
    assert rule["expr"] == "min by (env) (net_binding_safe) == 0"
    assert rule["for"] == "0m"
    assert rule["labels"] == {"severity": "page", "component": "net"}
    url = rule["annotations"]["runbook_url"]
    assert url == "docs/plan/07-release-and-prr.md#alert-netbindingunsafe"
    assert [r["alert"] for r in rules if r["labels"]["component"] == "net"] == [
        "NetBindingUnsafe"
    ]


def test_audit_verify_alert_pages_when_no_run_has_passed_for_26_hours() -> None:
    """#2111: a start-up or nightly verify run that keeps stopping finds no break, so
    `AuditChainVerificationFailed` stays silent; this page covers it. No run passed for 26 h (the
    daily run plus 2 h): by the gauge within one process, by the counter across restarts. A gauge
    at 0 (no runner wired) is dropped by `> 0` and the counter has no series then: no page. Its
    own component, so the page-over-ticket rule inhibits none of the `audit` tickets (next)."""
    rules = _rules()
    rule = {r["alert"]: r for r in rules}["AuditVerifyNotPassing"]
    assert rule["expr"] == (
        "time() - max by (env) (cv_audit_verify_last_ok_timestamp_seconds > 0) > 26 * 3600 "
        'or (sum by (env) (increase(cv_audit_verify_runs_total{result!="ok"}[26h])) > 0 '
        'unless sum by (env) (increase(cv_audit_verify_runs_total{result="ok"}[26h])) > 0)'
    )
    assert rule["for"] == "0m"
    assert rule["labels"] == {"severity": "page", "component": "audit_verify"}
    url = rule["annotations"]["runbook_url"]
    assert url == "docs/plan/07-release-and-prr.md#alert-auditverifynotpassing"
    route = _route_for({**rule["labels"], "alertname": rule["alert"], "env": "live"})
    assert route["receiver"] == "page"
    assert [r["alert"] for r in rules if r["labels"]["component"] == "audit_verify"] == [
        "AuditVerifyNotPassing"
    ]


def _matches(matchers: list[str], labels: dict[str, str]) -> bool:
    """Whether every Alertmanager matcher holds for `labels` (regexes are fully anchored)."""
    for matcher in matchers:
        hit = re.fullmatch(r'(\w+)\s*(=~|!~|!=|=)\s*"([^"]*)"', matcher)
        assert hit is not None, matcher
        key, op, want = hit.groups()
        got = labels.get(key, "")
        holds = {
            "=": got == want,
            "!=": got != want,
            "=~": re.fullmatch(want, got) is not None,
            "!~": re.fullmatch(want, got) is None,
        }[op]
        if not holds:
            return False
    return True


def _inhibits(source: dict[str, str], target: dict[str, str]) -> bool:
    """Whether an inhibit rule of the committed config lets alert `source` inhibit `target`."""
    return any(
        _matches(rule["source_matchers"], source)
        and _matches(rule["target_matchers"], target)
        and all(source.get(k, "") == target.get(k, "") for k in rule["equal"])
        for rule in AM["inhibit_rules"]
    )


def test_audit_verify_page_inhibits_no_audit_ticket() -> None:
    """#2111: the page-over-ticket rule matches on component and env, and this page can stand
    for days (a run that keeps stopping keeps it up until one passes). Its own component keeps it
    from inhibiting an `audit` ticket, a component the Postgres rule already lists for tickets.
    The control: the same page labelled `audit` does inhibit it, so a revert of the label fails."""
    rule = {r["alert"]: r for r in _rules()}["AuditVerifyNotPassing"]
    page = {**rule["labels"], "alertname": rule["alert"], "env": "live"}
    audit_ticket = {"severity": "ticket", "component": "audit", "env": "live"}
    assert _inhibits({**page, "component": "audit"}, audit_ticket)
    assert not _inhibits(page, audit_ticket)


def test_every_system_page_rule_has_an_absent_guard_on_its_series() -> None:
    """#2496: a page on a series that is never scraped can never fire, and nothing says so
    (`net_binding_safe` went unserved for the gauge's whole life). Every `system_page.yml`
    rule except the drill reads a series an `ExpectedMetricMissing*` guard watches."""
    import re

    guarded: set[str] = set()
    for r in _rules():
        hit = re.fullmatch(r"absent\((\w+)\)", r["expr"])
        if r["alert"].startswith("ExpectedMetricMissing") and hit:
            guarded.add(hit[1])
    page_file = INFRA / "prometheus" / "alerts" / "system_page.yml"
    unguarded = [
        r["alert"]
        for g in yaml.safe_load(page_file.read_text(encoding="utf-8"))["groups"]
        for r in g["rules"]
        if r["alert"] != "SyntheticAlert"
        and not any(re.search(rf"\b{m}\b", r["expr"]) for m in guarded)
    ]
    assert unguarded == []
