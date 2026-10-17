"""`AuthBreakGlassStateReadFailing` is a ticket, so quiet hours mute it, and its docs say what that
costs (#2496).

The ticket is the only signal that `AuthBreakGlassUsed` and `AuthBreakGlassAttempted` have gone
blind. The ticket route is muted in quiet hours (`infra/alertmanager/alertmanager.yml`): a reader
that fails from the start of the window leaves both pages silent until the window ends, and one
that recovers inside it is never reported. The records are not at risk (`audit_log` and
`system_events` keep them, and the next successful read publishes both counts), so the window is
accepted as the cost of a ticket, as it is for every `ExpectedMetricMissing*` guard. The runbook
section and the risk register bullet say so in the window's own hours, read here from the
Alertmanager config: a changed default fails this test until both name the new window.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[5]
ALERTMANAGER = ROOT / "infra" / "alertmanager" / "alertmanager.yml"
RUNBOOK = ROOT / "docs" / "plan" / "07-release-and-prr.md"
RISK_REGISTER = ROOT / "docs" / "plan" / "32-risk-register.md"
ALERT = "AuthBreakGlassStateReadFailing"


def _words(text: str) -> str:
    """One line of single-spaced words: line wraps and table padding do not matter."""
    return " ".join(text.split())


def _config() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(ALERTMANAGER.read_text(encoding="utf-8"))
    return loaded


def _quiet_hours() -> tuple[str, str]:
    """The first start and the last end of the `quiet_hours` interval, as committed (the default
    that `CV_ALERT_QUIET_HOURS` replaces at render time)."""
    (interval,) = (t for t in _config()["time_intervals"] if t["name"] == "quiet_hours")
    spans = [span for block in interval["time_intervals"] for span in block["times"]]
    return str(spans[0]["start_time"]), str(spans[-1]["end_time"])


def _runbook_row(element: str) -> str:
    """One row of the rule's runbook section, by its element label."""
    text = RUNBOOK.read_text(encoding="utf-8")
    start = text.index(f'<a id="alert-{ALERT.lower()}"></a>')
    section = text[start : text.index('<a id="', start + 1)]
    (row,) = (line for line in section.splitlines() if line.startswith(f"| {element}"))
    return _words(row)


def _runbook_what_fired() -> str:
    return _runbook_row("1. What fired")


def _risk_register_bullet() -> str:
    """The RSK-021 bullet that records the E09 detection gaps and what covers each."""
    lines = RISK_REGISTER.read_text(encoding="utf-8").splitlines()
    (bullet,) = (line for line in lines if "**E09 detection gaps (" in line)
    return _words(bullet)


DOCS: dict[str, Callable[[], str]] = {
    "runbook": _runbook_what_fired,
    "risk register": _risk_register_bullet,
}


def test_read_failure_ticket_is_muted_in_quiet_hours() -> None:
    """The premise of the docs below: the ticket route has the quiet-hours mute."""
    (ticket,) = (
        r for r in _config()["route"]["routes"] if r["matchers"] == ['severity = "ticket"']
    )
    assert ticket["mute_time_intervals"] == ["quiet_hours"]


@pytest.mark.parametrize("doc", sorted(DOCS))
def test_read_failure_ticket_docs_name_the_quiet_hours_window_and_how_long_the_pages_stay_blind(
    doc: str,
) -> None:
    start, end = _quiet_hours()
    hours = (int(end.split(":")[0]) - int(start.split(":")[0])) % 24
    text = DOCS[doc]()
    assert f"{start} to {end} UTC" in text, f"the {doc} must name the quiet hours {start}-{end}"
    assert f"up to {hours} hours" in text, f"the {doc} must say the pages can stay blind {hours} h"


@pytest.mark.parametrize("doc", sorted(DOCS))
def test_read_failure_ticket_docs_say_the_overnight_window_is_accepted(doc: str) -> None:
    text = DOCS[doc]()
    assert "accepted" in text, f"the {doc} must say the window is accepted as the cost of a ticket"
    assert "ExpectedMetricMissing" in text, f"the {doc} must name the guards that share the window"


def test_read_failure_runbook_escalation_row_says_an_overnight_failure_waits() -> None:
    row = _runbook_row("6. Escalation")
    assert "Owner at the next review" in row
    assert "overnight" in row, "the escalation row must say an overnight failure waits for 07:00"
