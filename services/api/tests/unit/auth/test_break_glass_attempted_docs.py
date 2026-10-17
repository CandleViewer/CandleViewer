"""`AuthBreakGlassAttempted` stays silent without a sample to compare with, and its docs say when
(#2496, review round 2).

The rule (`infra/prometheus/alerts/system_page.yml`) pages when the highest count of the last 15
minutes is above `max_over_time(auth_break_glass_attempts[7d] offset 15m)`, the highest count of
the 7 days before them. With no sample in that span the right-hand side is empty, the comparison
returns nothing and the page stays silent: for a Prometheus with no history of the series, and
equally for a refused run after cv-api was stopped for more than a week. A completed reset still
pages through `AuthBreakGlassUsed`, which needs no history. The runbook, the rule's own comment and
the E09 threat model had named only the first case, so each now says the general one in the same
words. The words are built here from the rule's own windows: a changed window fails this test until
the docs say the new one.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[5]
RULES = ROOT / "infra" / "prometheus" / "alerts" / "system_page.yml"
RUNBOOK = ROOT / "docs" / "plan" / "07-release-and-prr.md"
THREAT_MODEL = ROOT / "docs" / "security" / "threat-models" / "e09-auth-rbac.md"
ALERT = "AuthBreakGlassAttempted"
SERIES = "auth_break_glass_attempts"


def _words(text: str) -> str:
    """One line of single-spaced words: line wraps and table padding do not matter."""
    return " ".join(text.split())


def _rule_expr() -> str:
    groups = yaml.safe_load(RULES.read_text(encoding="utf-8"))["groups"]
    (rule,) = (r for g in groups for r in g["rules"] if r.get("alert") == ALERT)
    return str(rule["expr"])


def _rule_comment() -> str:
    """The comment between the rule's `- alert:` line and its `expr:` line."""
    text = RULES.read_text(encoding="utf-8")
    start = text.index(f"- alert: {ALERT}\n")
    block = text[start : text.index("expr:", start)]
    return _words(" ".join(line.strip().lstrip("#") for line in block.splitlines()[1:]))


def _runbook_what_fired() -> str:
    """Element 1 of the rule's runbook section: the row that says when the page fires."""
    text = RUNBOOK.read_text(encoding="utf-8")
    start = text.index(f'<a id="alert-{ALERT.lower()}"></a>')
    section = text[start : text.index('<a id="', start + 1)]
    (row,) = (line for line in section.splitlines() if line.startswith("| 1. What fired"))
    return _words(row)


def _threat_model_row() -> str:
    """The one row of the E09 threat model that routes the break-glass detection."""
    lines = THREAT_MODEL.read_text(encoding="utf-8").splitlines()
    (row,) = (line for line in lines if f"`{ALERT}`" in line)
    return _words(row)


DOCS: dict[str, Callable[[], str]] = {
    "runbook": _runbook_what_fired,
    "rule comment": _rule_comment,
    "threat model": _threat_model_row,
}


def _no_sample_clause() -> str:
    """The condition under which the rule sees no rise, read off the rule's own windows."""
    expr = _rule_expr()
    older = re.search(rf"max_over_time\({SERIES}\[(\d+)d\] offset (\d+)m\)", expr)
    recent = re.search(rf"max_over_time\({SERIES}\[(\d+)m\]\)", expr)
    assert older and recent, f"the rule no longer compares two windows of the gauge: {expr}"
    days, offset = older.groups()
    assert recent.group(1) == offset, f"the two windows are no longer adjacent: {expr}"
    return f"no sample in the {days} days before the last {offset} minutes"


@pytest.mark.parametrize("doc", sorted(DOCS))
def test_attempted_page_docs_say_it_sees_no_rise_without_a_sample_in_the_older_window(
    doc: str,
) -> None:
    clause = _no_sample_clause()
    assert clause in DOCS[doc](), f"the {doc} must say it sees no rise with {clause}"
