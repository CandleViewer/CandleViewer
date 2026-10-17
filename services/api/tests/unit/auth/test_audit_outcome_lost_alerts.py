"""#2914 item 5 (D1 rider): the alert rules on `auth_audit_outcome_lost_total`.

Any lost outcome record is a ticket (`system_ticket.yml`); more than 5 in 15 minutes is a page
(`system_page.yml`, so the page policy tests of `infra/alertmanager/tests` apply to it), under a
component of its own: the page-over-ticket inhibition matches on component and env, so a page under
`auth` would hide the lockout, step-up and CSRF tickets while the sink fails. promtool runs in CI;
here its cases are only checked to exist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[5]
_ALERTS = _ROOT / "infra" / "prometheus" / "alerts"
_PAGE_FILE, _TICKET_FILE = "system_page.yml", "system_ticket.yml"
_PROMTOOL_CASES = _ROOT / "infra" / "prometheus" / "tests" / "system_alerts.test.yml"
_ALERTMANAGER = _ROOT / "infra" / "alertmanager" / "alertmanager.yml"

TICKET = "AuthAuditOutcomeLost"
PAGE = "AuthAuditOutcomesLostBurst"
COMPONENT = "auth_audit"
_EXPR = "sum by (env) (increase(auth_audit_outcome_lost_total[15m])) > {n}"
_RUNBOOK = "docs/plan/07-release-and-prr.md#alert-authauditoutcomelost"


def _rules(only: str | None = None) -> dict[str, dict[str, Any]]:
    """The alert rules of every rule file, or of the one file named *only*."""
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(_ALERTS.glob(only or "*.yml")):
        for group in yaml.safe_load(path.read_text(encoding="utf-8"))["groups"]:
            found.update({r["alert"]: r for r in group["rules"] if "alert" in r})
    return found


def test_a_single_lost_record_is_a_ticket_and_more_than_five_in_the_window_a_page() -> None:
    ticket, page = _rules()[TICKET], _rules()[PAGE]
    assert ticket["expr"] == _EXPR.format(n=0) and page["expr"] == _EXPR.format(n=5)
    assert ticket["labels"] == {"severity": "ticket", "component": COMPONENT}
    assert page["labels"] == {"severity": "page", "component": COMPONENT}
    assert ticket["annotations"]["runbook_url"] == page["annotations"]["runbook_url"] == _RUNBOOK
    assert ticket["for"] == page["for"] == "0m"  # no hold time: a lost record is a gap now


def test_the_page_is_in_the_page_file_and_the_ticket_in_the_ticket_file() -> None:
    """Where the other pages and tickets of the system rules are, so the page policy tests that
    read `system_page.yml` (an `absent()` guard on every series a page reads) cover this page."""
    assert PAGE in _rules(_PAGE_FILE) and TICKET not in _rules(_PAGE_FILE)
    assert TICKET in _rules(_TICKET_FILE) and PAGE not in _rules(_TICKET_FILE)


def test_only_the_pair_has_the_component_so_the_page_hides_no_other_ticket() -> None:
    config = yaml.safe_load(_ALERTMANAGER.read_text(encoding="utf-8"))
    (inhibit,) = [
        r for r in config["inhibit_rules"] if r["source_matchers"] == ['severity = "page"']
    ]
    assert "component" in inhibit["equal"]  # a page hides the tickets of its own component and env
    sharing = {n for n, r in _rules().items() if r["labels"]["component"] == COMPONENT}
    assert sharing == {TICKET, PAGE}


def test_promtool_cases_load_both_rule_files_and_fire_and_stay_silent_for_both_alerts() -> None:
    document = yaml.safe_load(_PROMTOOL_CASES.read_text(encoding="utf-8"))
    assert {f"../alerts/{_PAGE_FILE}", f"../alerts/{_TICKET_FILE}"} <= set(document["rule_files"])
    outcomes: dict[str, list[bool]] = {TICKET: [], PAGE: []}
    for case in document["tests"]:
        for check in case["alert_rule_test"]:
            if check["alertname"] in outcomes:
                outcomes[check["alertname"]].append(bool(check["exp_alerts"]))
    assert outcomes == {TICKET: [True, False], PAGE: [True, False]}
