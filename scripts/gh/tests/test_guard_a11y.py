from __future__ import annotations

from scripts.gh import guard_a11y as a11y
from scripts.gh.models import Comment, Issue


def _issue(body: str) -> Issue:
    return Issue(number=1, kind="Task", labels=frozenset({"a11y"}), body=body, owner_login="alice")


def test_valid_repo_run_link_in_body_is_allowed() -> None:
    issue = _issue(
        "### a11y evidence\n\n"
        "https://github.com/CandleViewer/CandleViewer/actions/runs/555\n"
    )
    decision = a11y.evaluate(issue, comments=[], repo_owner="CandleViewer", repo_name="CandleViewer")
    assert decision.allow


def test_foreign_link_in_body_is_rejected() -> None:
    # Gherkin: "An a11y ticket requires a real run link" -- external site link rejected.
    issue = _issue("### a11y evidence\n\nhttps://example.com/axe-report\n")
    decision = a11y.evaluate(issue, comments=[], repo_owner="CandleViewer", repo_name="CandleViewer")
    assert not decision.allow


def test_missing_evidence_section_is_rejected() -> None:
    issue = _issue("### Test plan\n\nsomething\n")
    decision = a11y.evaluate(issue, comments=[], repo_owner="CandleViewer", repo_name="CandleViewer")
    assert not decision.allow


def test_valid_link_in_comment_is_allowed() -> None:
    issue = _issue("### a11y evidence\n\n_No response_\n")
    comments = [Comment(author_login="dev", body="https://github.com/CandleViewer/CandleViewer/actions/runs/777")]
    decision = a11y.evaluate(issue, comments, repo_owner="CandleViewer", repo_name="CandleViewer")
    assert decision.allow


def test_non_a11y_ticket_is_not_gated() -> None:
    issue = Issue(number=2, kind="Task", labels=frozenset(), body="", owner_login="alice")
    decision = a11y.evaluate(issue, comments=[], repo_owner="CandleViewer", repo_name="CandleViewer")
    assert decision.allow
