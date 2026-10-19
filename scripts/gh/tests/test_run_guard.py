from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.gh import run_guard
from scripts.gh.models import Comment, Issue


def _issue(**overrides) -> Issue:
    base = dict(number=1, kind="Story", labels=frozenset({"type/story"}), body="", owner_login="alice")
    base.update(overrides)
    return Issue(**base)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_REPO", "CandleViewer/CandleViewer")
    monkeypatch.setenv("ISSUE_NUMBER", "1")
    monkeypatch.setenv("ACTOR_LOGIN", "some-human")
    monkeypatch.delenv("GOVERNANCE_ENFORCE", raising=False)


def test_enforcing_defaults_false() -> None:
    assert run_guard._enforcing() is False


def test_enforcing_true_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOVERNANCE_ENFORCE", "true")
    assert run_guard._enforcing() is True


def test_annotate_write_access_flags_failure() -> None:
    from scripts.gh.gh_adapter import GhApiError

    comments = [Comment(author_login="bob", body="x")]
    with patch("scripts.gh.gh_adapter.has_write_access", side_effect=GhApiError("boom")):
        annotated, failed = run_guard._annotate_write_access(comments, "CandleViewer/CandleViewer")
    assert failed is True
    assert annotated[0].author_has_write_access is False
    assert annotated[0].write_access_check_failed is True


def test_annotate_write_access_marks_holder() -> None:
    comments = [Comment(author_login="bob", body="x")]
    with patch("scripts.gh.gh_adapter.has_write_access", return_value=True):
        annotated, failed = run_guard._annotate_write_access(comments, "CandleViewer/CandleViewer")
    assert failed is False
    assert annotated[0].author_has_write_access is True


def test_main_kind_sync_observe_only_does_not_write_project_kind() -> None:
    with patch.object(run_guard.gh_adapter, "fetch_issue", return_value=(_issue(kind="Bug"), [])):
        with patch.object(run_guard.gh_adapter, "set_project_item_kind") as mock_set:
            rc = run_guard.main(["kind-sync"])
    mock_set.assert_not_called()
    assert rc == 0


def test_main_kind_sync_enforcing_writes_project_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.gh.gh_adapter import ProjectItemKind

    monkeypatch.setenv("GOVERNANCE_ENFORCE", "true")
    monkeypatch.setenv("PROJECTS_PAT", "fake-pat")
    item = ProjectItemKind(
        item_id="PVTI_1", field_id="PVTSSF_1", option_id_by_kind={"Bug": "OPT_bug"}, current_kind="Story"
    )
    with patch.object(run_guard.gh_adapter, "fetch_issue", return_value=(_issue(kind="Bug"), [])):
        with patch.object(run_guard.gh_adapter, "get_project_item_kind", return_value=item):
            with patch.object(run_guard.gh_adapter, "get_project_id", return_value="PVT_1"):
                with patch.object(run_guard.gh_adapter, "set_project_item_kind") as mock_set:
                    with patch.object(run_guard.gh_adapter, "post_or_update_decision_comment"):
                        run_guard.main(["kind-sync"])
    mock_set.assert_called_once_with("PVT_1", "PVTI_1", "PVTSSF_1", "OPT_bug")


def test_main_kind_sync_without_projects_pat_never_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOVERNANCE_ENFORCE", "true")
    monkeypatch.delenv("PROJECTS_PAT", raising=False)
    with patch.object(run_guard.gh_adapter, "fetch_issue", return_value=(_issue(kind="Bug"), [])):
        with patch.object(run_guard.gh_adapter, "set_project_item_kind") as mock_set:
            with patch.object(run_guard.gh_adapter, "post_or_update_decision_comment"):
                run_guard.main(["kind-sync"])
    mock_set.assert_not_called()


def test_main_qa_guard_blocks_and_returns_1_when_enforcing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOVERNANCE_ENFORCE", "true")
    with patch.object(run_guard.gh_adapter, "fetch_issue", return_value=(_issue(), [])):
        with patch.object(run_guard.gh_adapter, "reopen_issue") as mock_reopen:
            with patch.object(run_guard.gh_adapter, "post_or_update_decision_comment"):
                rc = run_guard.main(["qa-guard"])
    mock_reopen.assert_called_once()
    assert rc == 1


def test_main_qa_guard_observe_only_never_reopens() -> None:
    with patch.object(run_guard.gh_adapter, "fetch_issue", return_value=(_issue(), [])):
        with patch.object(run_guard.gh_adapter, "reopen_issue") as mock_reopen:
            rc = run_guard.main(["qa-guard"])
    mock_reopen.assert_not_called()
    assert rc == 0


def test_main_security_guard_label_sync_mode() -> None:
    issue = _issue(kind="Task", labels=frozenset({"area/auth-rbac"}))
    with patch.object(run_guard.gh_adapter, "fetch_issue", return_value=(issue, [])):
        with patch.object(run_guard.gh_adapter, "add_labels") as mock_add:
            run_guard.main(["security-guard", "--mode", "label-sync"])
    mock_add.assert_not_called()  # observe-only by default


def test_main_a11y_guard_uses_repo_owner_and_name() -> None:
    issue = _issue(kind="Task", labels=frozenset({"a11y"}), body="### a11y evidence\n\n_No response_\n")
    with patch.object(run_guard.gh_adapter, "fetch_issue", return_value=(issue, [])):
        rc = run_guard.main(["a11y-guard"])
    assert rc == 0
