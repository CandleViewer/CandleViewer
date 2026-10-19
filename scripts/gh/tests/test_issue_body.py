from __future__ import annotations

from scripts.gh.issue_body import (
    QA_DEVIATION_MARKER_RE,
    QA_SIGNOFF_MARKER_RE,
    find_repo_actions_run_urls,
    find_section,
    gov_bot_marker,
    is_na,
    is_no_response,
)


def test_find_section_present() -> None:
    body = "### Acceptance criteria\n\nSome text\nmore\n\n### Test plan\n\nplan text\n"
    assert find_section(body, "Acceptance criteria") == "Some text\nmore"
    assert find_section(body, "Test plan") == "plan text"


def test_find_section_absent_heading_is_none() -> None:
    body = "### Acceptance criteria\n\nfilled in\n"
    assert find_section(body, "Test plan") is None


def test_find_section_present_but_empty() -> None:
    body = "### Acceptance criteria\n\n\n### Test plan\n\nfilled in\n"
    assert find_section(body, "Acceptance criteria") == ""


def test_is_no_response_variants() -> None:
    assert is_no_response(None)
    assert is_no_response("")
    assert is_no_response("_No response_")
    assert not is_no_response("some real content")


def test_is_na_case_sensitive() -> None:
    assert is_na("N/A")
    assert not is_na("n/a")
    assert not is_na("NA")
    assert not is_na(None)


def test_find_repo_actions_run_urls_accepts_matching_repo() -> None:
    text = "See https://github.com/CandleViewer/CandleViewer/actions/runs/12345 for the axe run."
    urls = find_repo_actions_run_urls(text, "CandleViewer", "CandleViewer")
    assert urls == ["https://github.com/CandleViewer/CandleViewer/actions/runs/12345"]


def test_find_repo_actions_run_urls_rejects_foreign_link() -> None:
    text = "See https://example.com/axe-report for evidence."
    assert find_repo_actions_run_urls(text, "CandleViewer", "CandleViewer") == []


def test_find_repo_actions_run_urls_rejects_other_repo_actions_run() -> None:
    text = "https://github.com/other-org/other-repo/actions/runs/999"
    assert find_repo_actions_run_urls(text, "CandleViewer", "CandleViewer") == []


def test_find_repo_actions_run_urls_accepts_pre_transfer_owner_alias() -> None:
    # Run links written before the 2026-10-19 transfer name the old owner `basiltt`.
    text = "See https://github.com/basiltt/CandleViewer/actions/runs/12345 for the axe run."
    urls = find_repo_actions_run_urls(text, "CandleViewer", "CandleViewer")
    assert urls == ["https://github.com/basiltt/CandleViewer/actions/runs/12345"]


def test_find_repo_actions_run_urls_rejects_unrelated_owner_with_same_repo_name() -> None:
    text = "See https://github.com/someone-else/CandleViewer/actions/runs/12345 for the axe run."
    assert find_repo_actions_run_urls(text, "CandleViewer", "CandleViewer") == []


def test_find_repo_actions_run_urls_rejects_legacy_owner_with_other_repo_name() -> None:
    text = "https://github.com/basiltt/other-repo/actions/runs/999"
    assert find_repo_actions_run_urls(text, "CandleViewer", "CandleViewer") == []


def test_qa_signoff_marker_matches_pass_case_insensitively() -> None:
    assert QA_SIGNOFF_MARKER_RE.search("QA sign-off: pass")
    assert QA_SIGNOFF_MARKER_RE.search("qa sign-off: PASS")
    m = QA_SIGNOFF_MARKER_RE.search("QA sign-off: fail")
    assert m and m.group(1).lower() == "fail"


def test_qa_deviation_marker() -> None:
    assert QA_DEVIATION_MARKER_RE.search("Recording a QA capacity deviation for this sprint.")
    assert not QA_DEVIATION_MARKER_RE.search("nothing relevant here")


def test_gov_bot_marker_is_stable_per_guard() -> None:
    assert gov_bot_marker("qa-guard") == "<!-- gov-bot:qa-guard -->"
    assert gov_bot_marker("qa-guard") != gov_bot_marker("security-guard")
